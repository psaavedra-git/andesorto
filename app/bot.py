"""Orquestación de un mensaje entrante: dueño → comandos; cliente → menú/formulario/agente, o silencio si está derivado."""
import logging

import anthropic

from .agent import run_agent
from .config import Settings
from .handoff import do_handoff, handle_owner_command
from .orders import form_link_message
from .store import Store
from .whatsapp import IncomingMessage, WhatsAppClient

log = logging.getLogger(__name__)

NON_TEXT_REPLY = (
    "Por ahora solo puedo leer mensajes de texto 🙏. ¿Podría escribirme su consulta? "
    "Si prefiere hablar con una persona, escríbame *asesor*."
)
WELCOME = "¡Hola! 👋 Soy el asistente de *AndesOrto*. ¿En qué le puedo ayudar?"
MENU_BUTTONS = [("nuevo", "🦷 Aparato nuevo"), ("reparacion", "🔧 Reparación"), ("precios", "💲 Precios/trabajos")]
PRICES_PROMPT = "Quiero consultar precios o tipos de trabajo."


class Bot:
    def __init__(self, settings: Settings, store: Store, wa: WhatsAppClient, llm: anthropic.Anthropic):
        self.s = settings
        self.store = store
        self.wa = wa
        self.llm = llm

    def handle(self, msg: IncomingMessage) -> None:
        if not self.store.mark_processed(msg.id):
            return  # reintento de Meta
        self.wa.mark_as_read(msg.id)

        if self.s.owner_wa_number and msg.wa_id == self.s.owner_wa_number:
            self.wa.send_text(msg.wa_id, handle_owner_command(self.store, msg.text or "", self.s.handoff_timeout_hours))
            return

        if msg.button_id == "precios":
            content = PRICES_PROMPT
        elif msg.text:
            content = msg.text
        else:
            content = f"[envió un mensaje de tipo {msg.type}]"
        self.store.add_message(msg.wa_id, "user", content)

        if self.store.is_paused(msg.wa_id, self.s.handoff_timeout_hours):
            return  # lo atiende un humano

        if not msg.text:
            self._reply(msg.wa_id, NON_TEXT_REPLY)
            return

        # Botones del menú: aparato nuevo / reparación van directo al formulario, sin pasar por el LLM
        if msg.button_id in ("nuevo", "reparacion"):
            self._reply(msg.wa_id, form_link_message(self.s, msg.button_id, msg.wa_id))
            return

        result = run_agent(self.llm, self.s, self.store.history(msg.wa_id, self.s.history_limit))
        if result.show_menu:
            body = result.reply or WELCOME
            self.store.add_message(msg.wa_id, "assistant", body + "\n[menú: Aparato nuevo | Reparación | Precios/trabajos]")
            self.wa.send_buttons(msg.wa_id, body, MENU_BUTTONS)
            return
        if result.reply:
            self._reply(msg.wa_id, result.reply)
        if result.form:
            self._reply(msg.wa_id, form_link_message(self.s, result.form, msg.wa_id))
        if result.handoff:
            log.info("Handoff %s: %s", msg.wa_id, result.handoff)
            do_handoff(
                self.store,
                self.wa,
                self.s,
                msg.wa_id,
                result.handoff.get("motivo", "sin_respuesta"),
                result.handoff.get("resumen", ""),
                msg.name,
            )

    def _reply(self, wa_id: str, text: str) -> None:
        self.store.add_message(wa_id, "assistant", text)
        self.wa.send_text(wa_id, text)
