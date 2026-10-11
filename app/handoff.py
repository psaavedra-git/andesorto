"""Derivación a humano: pausa el chat, avisa al dueño y procesa los comandos del dueño."""
import re
import time

from .config import Settings
from .store import Store
from .whatsapp import WhatsAppClient

MOTIVOS = {
    "solicitud_explicita": "El cliente pidió hablar con una persona",
    "sin_respuesta": "El bot no tiene una respuesta clara",
    "queja": "Queja / cliente molesto",
    "pedido_comercial": "Quiere hacer un pedido o cotización",
}

OWNER_HELP = (
    "🤖 *Comandos AndesOrtoBOT*\n"
    "• *#pausados*: lista los chats derivados\n"
    "• *#bot on 51999888777*: reactiva el bot en ese chat\n"
    "• *#bot off 51999888777*: pausa el bot en ese chat"
)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def do_handoff(
    store: Store, wa: WhatsAppClient, s: Settings, wa_id: str, motivo: str, resumen: str, client_name: str | None
) -> None:
    store.pause(wa_id, motivo)
    if not s.owner_wa_number:
        return

    cliente = f"{client_name} (+{wa_id})" if client_name else f"+{wa_id}"
    motivo_txt = MOTIVOS.get(motivo, motivo)
    ultimos = store.history(wa_id, 6)
    transcript = "\n".join(
        f"{'👤' if m['role'] == 'user' else '🤖'} {m['content'][:300]}" for m in ultimos
    )
    text = (
        f"🔔 *Derivación AndesOrtoBOT*\n"
        f"*Cliente:* {cliente}\n"
        f"*Motivo:* {motivo_txt}\n"
        f"*Resumen:* {resumen}\n\n"
        f"*Últimos mensajes:*\n{transcript}\n\n"
        f"Escríbale a wa.me/{wa_id}\n"
        f"Para reactivar el bot: *#bot on {wa_id}*"
    )

    # Fuera de la ventana de 24 h solo llegan plantillas aprobadas: se intenta la plantilla
    # y, después, el texto libre (que sí llega si el dueño escribió al bot en las últimas 24 h).
    if s.owner_template_name:
        wa.send_template(s.owner_wa_number, s.owner_template_name, s.owner_template_lang, [cliente, motivo_txt, resumen])
    wa.send_text(s.owner_wa_number, text)


def handle_owner_command(store: Store, text: str, timeout_hours: float) -> str:
    cmd = text.strip().lower()
    if cmd.startswith("#pausados"):
        rows = store.paused_list()
        if not rows:
            return "✅ No hay chats derivados."
        lines = ["⏸️ *Chats derivados:*"]
        for r in rows:
            mins = int((time.time() - (r["paused_at"] or 0)) / 60)
            lines.append(f"• +{r['wa_id']} ({MOTIVOS.get(r['paused_reason'], r['paused_reason'])}, hace {mins} min)")
        if timeout_hours > 0:
            lines.append(f"\nSe reactivan solos tras {timeout_hours:g} h.")
        return "\n".join(lines)

    m = re.match(r"#bot\s+(on|off)\s+(.+)", cmd)
    if m:
        number = _digits(m.group(2))
        if not number:
            return "Indique el número, ej. *#bot on 51999888777*"
        if m.group(1) == "on":
            return f"✅ Bot reactivado para +{number}." if store.resume(number) else f"+{number} no estaba pausado."
        store.pause(number, "manual")
        return f"⏸️ Bot pausado para +{number}."

    return OWNER_HELP
