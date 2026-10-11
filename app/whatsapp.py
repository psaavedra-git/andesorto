"""Cliente mínimo de la WhatsApp Cloud API (Meta)."""
import hashlib
import hmac
import logging
from dataclasses import dataclass

import httpx

from .config import Settings

log = logging.getLogger(__name__)


@dataclass
class IncomingMessage:
    id: str
    wa_id: str  # número del remitente, ej. "51987654321"
    type: str  # text, image, audio, ...
    text: str | None
    name: str | None = None
    button_id: str | None = None  # id del botón pulsado (mensajes interactivos)


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse_incoming(payload: dict) -> list[IncomingMessage]:
    """Extrae los mensajes del webhook; ignora notificaciones de estado (sent/delivered/read)."""
    out: list[IncomingMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                mtype = m.get("type", "")
                text = button_id = None
                if mtype == "text":
                    text = m.get("text", {}).get("body")
                elif mtype == "button":
                    text = m.get("button", {}).get("text")
                    button_id = m.get("button", {}).get("payload")
                elif mtype == "interactive":
                    inter = m.get("interactive", {})
                    reply = inter.get("button_reply") or inter.get("list_reply") or {}
                    text, button_id = reply.get("title"), reply.get("id")
                out.append(
                    IncomingMessage(
                        id=m.get("id", ""),
                        wa_id=m.get("from", ""),
                        type=mtype,
                        text=text,
                        name=names.get(m.get("from")),
                        button_id=button_id,
                    )
                )
    return out


class WhatsAppClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.s = settings
        self.http = http or httpx.Client(timeout=15)

    @property
    def _url(self) -> str:
        return f"https://graph.facebook.com/{self.s.wa_api_version}/{self.s.wa_phone_number_id}/messages"

    def _post(self, payload: dict) -> bool:
        try:
            r = self.http.post(self._url, json=payload, headers={"Authorization": f"Bearer {self.s.wa_token}"})
        except httpx.HTTPError as exc:
            log.error("WhatsApp send failed: %s", exc)
            return False
        if r.status_code >= 400:
            log.error("WhatsApp API %s: %s", r.status_code, r.text)
            return False
        return True

    def send_text(self, to: str, body: str) -> bool:
        return self._post(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body[:4096], "preview_url": False},
            }
        )

    def send_buttons(self, to: str, body: str, buttons: list[tuple[str, str]]) -> bool:
        """Hasta 3 botones de respuesta rápida: [(id, título ≤20 caracteres), ...]."""
        return self._post(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body[:1024]},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": bid, "title": title[:20]}} for bid, title in buttons[:3]
                        ]
                    },
                },
            }
        )

    def send_template(self, to: str, name: str, lang: str, params: list[str]) -> bool:
        return self._post(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": name,
                    "language": {"code": lang},
                    "components": [
                        {
                            "type": "body",
                            # Las plantillas no admiten saltos de línea en parámetros
                            "parameters": [{"type": "text", "text": " ".join(p.split())[:1000]} for p in params],
                        }
                    ],
                },
            }
        )

    def mark_as_read(self, message_id: str) -> None:
        self._post({"messaging_product": "whatsapp", "status": "read", "message_id": message_id})
