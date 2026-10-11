import hashlib
import hmac
import time
from types import SimpleNamespace

import pytest

from app.agent import HANDOFF_REPLY, _normalize, run_agent
from app.bot import NON_TEXT_REPLY, Bot
from app.config import Settings
from app.handoff import handle_owner_command
from app.knowledge import build_knowledge
from app.store import Store
from app.whatsapp import IncomingMessage, parse_incoming, verify_signature

OWNER = "51900000000"
CLIENT = "51911111111"


# ---------- fakes ----------
class FakeWA:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.templates: list[tuple] = []
        self.buttons: list[tuple] = []

    def send_text(self, to, body):
        self.sent.append((to, body))
        return True

    def send_buttons(self, to, body, buttons):
        self.sent.append((to, body))
        self.buttons.append((to, [b[0] for b in buttons]))
        return True

    def send_template(self, to, name, lang, params):
        self.templates.append((to, name, params))
        return True

    def mark_as_read(self, _id):
        pass


def text_block(t):
    return SimpleNamespace(type="text", text=t)


def tool_block(motivo, resumen):
    return SimpleNamespace(type="tool_use", name="derivar_a_humano", input={"motivo": motivo, "resumen": resumen})


def tool(name, **inp):
    return SimpleNamespace(type="tool_use", name=name, input=inp)


class FakeLLM:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self._responses.pop(0))


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        owner_wa_number=OWNER,
        owner_template_name="alerta_derivacion",
        wa_app_secret="secret",
        db_path=str(tmp_path / "t.db"),
    )


@pytest.fixture
def store(settings):
    return Store(settings.db_path)


def msg(text, mid="m1", frm=CLIENT, mtype="text", button_id=None):
    return IncomingMessage(id=mid, wa_id=frm, type=mtype, text=text, name="Dra. Pérez", button_id=button_id)


# ---------- whatsapp ----------
def test_signature():
    body = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_signature("secret", body, sig)
    assert not verify_signature("secret", body, "sha256=deadbeef")
    assert not verify_signature("secret", body, None)
    assert not verify_signature("", body, sig)


def test_parse_incoming_text_and_status():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": CLIENT, "profile": {"name": "Ana"}}],
                            "messages": [
                                {"id": "a", "from": CLIENT, "type": "text", "text": {"body": "hola"}},
                                {"id": "b", "from": CLIENT, "type": "image", "image": {}},
                            ],
                        }
                    },
                    {"value": {"statuses": [{"id": "x", "status": "read"}]}},
                ]
            }
        ]
    }
    msgs = parse_incoming(payload)
    assert [(m.id, m.type, m.text, m.name) for m in msgs] == [("a", "text", "hola", "Ana"), ("b", "image", None, "Ana")]


# ---------- knowledge ----------
def test_knowledge_includes_catalog_and_faq(settings):
    k = build_knowledge(settings.data_dir)
    assert "S/ 10" in k and "Preguntas frecuentes" in k and "AndesOrto" in k


# ---------- agent ----------
def test_normalize_merges_and_starts_with_user():
    h = [
        {"role": "assistant", "content": "x"},
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "c"},
    ]
    assert _normalize(h) == [{"role": "user", "content": "a\nb"}, {"role": "assistant", "content": "c"}]


def test_agent_text_reply(settings):
    llm = FakeLLM([text_block("Atendemos de 9 a 18 h.")])
    r = run_agent(llm, settings, [{"role": "user", "content": "horario?"}])
    assert r.reply == "Atendemos de 9 a 18 h." and r.handoff is None
    call = llm.calls[0]
    assert call["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert {t["name"] for t in call["tools"]} == {"derivar_a_humano", "mostrar_menu", "enviar_formulario"}


def test_agent_tool_call_is_handoff(settings):
    llm = FakeLLM([text_block("Claro."), tool_block("solicitud_explicita", "Quiere hablar con Jimmy")])
    r = run_agent(llm, settings, [{"role": "user", "content": "quiero hablar con Jimmy"}])
    assert r.reply == f"Claro.\n\n{HANDOFF_REPLY}"
    assert r.handoff == {"motivo": "solicitud_explicita", "resumen": "Quiere hablar con Jimmy"}


# ---------- bot flow ----------
def test_bot_replies_and_dedupes(settings, store):
    wa, llm = FakeWA(), FakeLLM([text_block("Hola doctora")])
    bot = Bot(settings, store, wa, llm)
    bot.handle(msg("hola"))
    bot.handle(msg("hola"))  # reintento de Meta con el mismo id
    assert wa.sent == [(CLIENT, "Hola doctora")]
    assert len(llm.calls) == 1


def test_handoff_pauses_and_notifies_owner(settings, store):
    wa = FakeWA()
    llm = FakeLLM([tool_block("sin_respuesta", "Pregunta precio de alineadores")])
    bot = Bot(settings, store, wa, llm)
    bot.handle(msg("¿precio de alineadores?", "m1"))

    assert wa.sent[0] == (CLIENT, HANDOFF_REPLY)
    owner_msgs = [b for to, b in wa.sent if to == OWNER]
    assert owner_msgs and CLIENT in owner_msgs[0] and "alineadores" in owner_msgs[0]
    assert wa.templates and wa.templates[0][0] == OWNER
    assert store.is_paused(CLIENT, 24)

    # Mientras está pausado, el bot no responde ni llama al LLM
    n_sent = len(wa.sent)
    bot.handle(msg("¿sigue ahí?", "m2"))
    assert len(wa.sent) == n_sent and len(llm.calls) == 1
    assert store.history(CLIENT, 10)[-1]["content"] == "¿sigue ahí?"  # pero queda en el historial


def test_owner_reactivates_bot(settings, store):
    wa = FakeWA()
    bot = Bot(settings, store, wa, FakeLLM([text_block("De nuevo aquí")]))
    store.pause(CLIENT, "queja")

    bot.handle(msg("#pausados", "o1", frm=OWNER))
    assert CLIENT in wa.sent[-1][1]

    bot.handle(msg(f"#bot on +{CLIENT}", "o2", frm=OWNER))
    assert "reactivado" in wa.sent[-1][1]
    assert not store.is_paused(CLIENT, 24)

    bot.handle(msg("hola", "m3"))
    assert wa.sent[-1] == (CLIENT, "De nuevo aquí")


def test_owner_unknown_command_gets_help(store):
    assert "Comandos" in handle_owner_command(store, "hola", 24)


def test_pause_timeout_auto_resumes(store):
    store.pause(CLIENT, "queja")
    store._conn.execute("UPDATE conversations SET paused_at = ?", (time.time() - 25 * 3600,))
    assert not store.is_paused(CLIENT, 24)


def test_non_text_message(settings, store):
    wa, llm = FakeWA(), FakeLLM()
    Bot(settings, store, wa, llm).handle(msg(None, mtype="audio"))
    assert wa.sent == [(CLIENT, NON_TEXT_REPLY)] and not llm.calls


# ---------- menú y formularios ----------
def test_menu_tool_sends_buttons(settings, store):
    wa = FakeWA()
    Bot(settings, store, wa, FakeLLM([text_block("¡Hola doctora!"), tool("mostrar_menu")])).handle(msg("hola"))
    assert wa.buttons == [(CLIENT, ["nuevo", "reparacion", "precios"])]
    assert wa.sent == [(CLIENT, "¡Hola doctora!")]


def test_button_nuevo_sends_form_link_without_llm(settings, store):
    wa, llm = FakeWA(), FakeLLM()
    Bot(settings, store, wa, llm).handle(msg("🦷 Aparato nuevo", mtype="interactive", button_id="nuevo"))
    assert not llm.calls
    assert "/f/nuevo?t=" in wa.sent[0][1]


def test_button_precios_goes_to_llm(settings, store):
    wa, llm = FakeWA(), FakeLLM([text_block("Tarifario: A S/ 10")])
    Bot(settings, store, wa, llm).handle(msg("💲 Precios/trabajos", mtype="interactive", button_id="precios"))
    assert llm.calls[0]["messages"][-1]["content"].startswith("Quiero consultar precios")
    assert wa.sent == [(CLIENT, "Tarifario: A S/ 10")]


def test_form_tool_from_free_text(settings, store):
    wa = FakeWA()
    llm = FakeLLM([text_block("Con gusto."), tool("enviar_formulario", tipo="reparacion")])
    Bot(settings, store, wa, llm).handle(msg("se me rompió una placa, necesito repararla"))
    assert wa.sent[0] == (CLIENT, "Con gusto.")
    assert "/f/reparacion?t=" in wa.sent[1][1]
