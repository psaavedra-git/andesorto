import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import orders
from app.config import Settings
from app.forms import router
from app.orders import make_form_link, read_token
from app.store import Store

CLIENT = "51911111111"
KARLA = "51922222222"


class FakeWA:
    def __init__(self):
        self.sent = []

    def send_text(self, to, body):
        self.sent.append((to, body))
        return True

    def send_template(self, *a):
        return True


@pytest.fixture
def env(tmp_path, monkeypatch):
    s = Settings(
        _env_file=None,
        db_path=str(tmp_path / "f.db"),
        form_secret="fs",
        public_base_url="https://bot.example",
        notify_wa_number=KARLA,
        sheets_webhook_url="https://script.example/exec",
        sheets_secret="ss",
    )
    sheet_rows = []
    monkeypatch.setattr(
        orders.httpx, "post", lambda url, json, **kw: sheet_rows.append(json) or type("R", (), {"status_code": 200, "text": '{"ok":true}'})()
    )
    app = FastAPI()
    wa, store = FakeWA(), Store(s.db_path)
    app.state.settings = s
    app.state.bot = type("B", (), {"store": store, "wa": wa})()
    app.include_router(router)
    return s, TestClient(app), wa, store, sheet_rows


def test_token_roundtrip_and_tamper(env):
    s, *_ = env
    link = make_form_link(s, "nuevo", CLIENT)
    assert link.startswith("https://bot.example/f/nuevo?t=")
    token = link.split("t=")[1]
    assert read_token(s, "nuevo", token) == CLIENT
    assert read_token(s, "reparacion", token) is None  # firmado para otro tipo
    wa_id, exp, sig = token.split(".")
    assert read_token(s, "nuevo", f"51900000000.{exp}.{sig}") is None
    old = int(time.time()) - 10
    assert read_token(s, "nuevo", f"{CLIENT}.{old}.{orders._sign(s, 'nuevo', CLIENT, old)}") is None
    assert read_token(s, "nuevo", "basura") is None


def test_form_get_shows_fields(env):
    s, c, *_ = env
    token = make_form_link(s, "nuevo", CLIENT).split("t=")[1]
    html = c.get(f"/f/nuevo?t={token}").text
    for name in ("aparato", "doctor", "paciente", "color", "indicaciones"):
        assert f'name="{name}"' in html
    assert 'name="telefono"' not in html  # ya sabemos su WhatsApp
    assert 'name="telefono"' in c.get("/f/nuevo").text  # acceso desde la web
    assert c.get("/f/otro").status_code == 404


def test_submit_from_whatsapp_link(env):
    s, c, wa, store, rows = env
    token = make_form_link(s, "nuevo", CLIENT).split("t=")[1]
    data = {"t": token, "aparato": "Placa Hawley", "doctor": "Dra. Pérez", "paciente": "Juan <b>", "color": "Azul", "indicaciones": "Con resorte"}
    r = c.post("/f/nuevo", data=data)
    assert r.status_code == 200 and "AO-N-0001" in r.text and "Juan <b>" not in r.text
    assert rows[0]["codigo"] == "AO-N-0001" and rows[0]["secret"] == "ss" and rows[0]["whatsapp"] == CLIENT
    to_karla = [b for to, b in wa.sent if to == KARLA]
    to_client = [b for to, b in wa.sent if to == CLIENT]
    assert to_karla and "Placa Hawley" in to_karla[0] and "Dra. Pérez" in to_karla[0]
    assert to_client and "AO-N-0001" in to_client[0]


def test_submit_missing_fields(env):
    s, c, wa, store, rows = env
    r = c.post("/f/reparacion", data={"aparato": "Placa", "telefono": "999888777"})
    assert "Falta completar" in r.text and not rows and not wa.sent


def test_submit_from_web_requires_phone_and_normalizes(env):
    s, c, wa, store, rows = env
    data = {"aparato": "Placa", "doctor": "Dr. X", "paciente": "Ana", "descripcion": "Se rompió el arco", "telefono": "999 888 777"}
    r = c.post("/f/reparacion", data=data)
    assert "AO-R-0001" in r.text
    assert rows[0]["whatsapp"] == "51999888777" and rows[0]["origen"] == "Web"
    assert [to for to, _ in wa.sent] == [KARLA]  # al doctor no se le escribe (fuera de la ventana de 24 h)
