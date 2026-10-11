"""Pedidos: enlaces firmados al formulario, registro (SQLite + Google Sheet) y avisos por WhatsApp."""
import hashlib
import hmac
import logging
import time
from datetime import datetime

import httpx

from .config import Settings
from .store import Store
from .whatsapp import WhatsAppClient

log = logging.getLogger(__name__)

# (clave, etiqueta, tipo de input, obligatorio)
FORMS: dict[str, dict] = {
    "nuevo": {
        "titulo": "Solicitud de aparato nuevo",
        "etiqueta": "Aparato nuevo",
        "campos": [
            ("aparato", "Nombre del aparato", "text", True),
            ("doctor", "Doctor solicitante", "text", True),
            ("paciente", "Nombre del paciente", "text", True),
            ("color", "Color", "text", False),
            ("indicaciones", "Características o indicaciones para su elaboración", "textarea", True),
        ],
    },
    "reparacion": {
        "titulo": "Solicitud de reparación",
        "etiqueta": "Reparación",
        "campos": [
            ("aparato", "Aparato a reparar", "text", True),
            ("doctor", "Doctor solicitante", "text", True),
            ("paciente", "Nombre del paciente", "text", True),
            ("descripcion", "Descripción del daño o del arreglo solicitado", "textarea", True),
        ],
    },
}
PHONE_FIELD = ("telefono", "WhatsApp de contacto del doctor", "tel", True)


# ---------- enlaces firmados ----------
def _secret(s: Settings) -> bytes:
    return (s.form_secret or s.wa_app_secret or "andesorto-dev").encode()


def _sign(s: Settings, tipo: str, wa_id: str, exp: int) -> str:
    return hmac.new(_secret(s), f"{tipo}.{wa_id}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def make_form_link(s: Settings, tipo: str, wa_id: str) -> str:
    exp = int(time.time() + s.form_link_hours * 3600)
    token = f"{wa_id}.{exp}.{_sign(s, tipo, wa_id, exp)}"
    return f"{s.public_base_url.rstrip('/')}/f/{tipo}?t={token}"


def read_token(s: Settings, tipo: str, token: str | None) -> str | None:
    """Devuelve el wa_id si el token es válido y no venció; si no, None (formulario 'anónimo' desde la web)."""
    try:
        wa_id, exp, sig = (token or "").split(".")
        if int(exp) < time.time():
            return None
    except ValueError:
        return None
    return wa_id if hmac.compare_digest(sig, _sign(s, tipo, wa_id, int(exp))) else None


# ---------- registro y avisos ----------
def form_link_message(s: Settings, tipo: str, wa_id: str) -> str:
    accion = "registrar su pedido" if tipo == "nuevo" else "registrar la reparación"
    return (
        f"📝 Para {accion}, complete este formulario breve (2 minutos):\n"
        f"{make_form_link(s, tipo, wa_id)}\n\n"
        "Al enviarlo, le confirmamos por aquí con su número de solicitud."
    )


def _summary(tipo: str, code: str, data: dict, wa_id: str | None) -> str:
    form = FORMS[tipo]
    icon = "🆕" if tipo == "nuevo" else "🔧"
    lines = [f"{icon} *{form['etiqueta']} – {code}*"]
    for key, label, _, _ in form["campos"]:
        if data.get(key):
            lines.append(f"*{label.split(' para ')[0]}:* {data[key]}")
    contacto = wa_id or data.get("telefono")
    if contacto:
        lines.append(f"*WhatsApp:* +{contacto}  (wa.me/{contacto})")
    return "\n".join(lines)


def _push_to_sheet(s: Settings, row: dict) -> None:
    if not s.sheets_webhook_url:
        return
    try:
        r = httpx.post(
            s.sheets_webhook_url, json={"secret": s.sheets_secret, **row}, timeout=20, follow_redirects=True
        )
        if r.status_code >= 400 or '"ok":true' not in r.text.replace(" ", ""):
            log.error("Google Sheet respondió %s: %s", r.status_code, r.text[:300])
    except httpx.HTTPError as exc:
        log.error("No se pudo escribir en Google Sheet: %s", exc)


def finish_order(s: Settings, store: Store, wa: WhatsAppClient, tipo: str, code: str, wa_id: str | None, data: dict) -> None:
    """Efectos externos (pueden tardar): Google Sheet + WhatsApp. Se ejecuta en segundo plano."""
    _push_to_sheet(
        s,
        {
            "tipo": tipo,
            "codigo": code,
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "whatsapp": wa_id or data.get("telefono", ""),
            "origen": "WhatsApp" if wa_id else "Web",
            **{k: data.get(k, "") for k, *_ in FORMS[tipo]["campos"]},
        },
    )

    summary = _summary(tipo, code, data, wa_id)
    if s.notify_wa_number:
        if s.notify_template_name:
            wa.send_template(
                s.notify_wa_number,
                s.notify_template_name,
                s.owner_template_lang,
                [code, f"{FORMS[tipo]['etiqueta']}: {data.get('aparato', '')} – Dr(a). {data.get('doctor', '')}"],
            )
        wa.send_text(s.notify_wa_number, summary)

    if wa_id:
        confirm = (
            f"✅ Recibimos su solicitud *{code}*.\n\n{summary.split(chr(10), 1)[1]}\n\n"
            "Nuestro equipo la revisará. La fecha de entrega se confirma después de la revisión del técnico"
            + (", igual que el precio si el trabajo tiene características especiales." if tipo == "nuevo" else ".")
        )
        wa.send_text(wa_id, confirm)
        store.add_message(wa_id, "assistant", confirm)
