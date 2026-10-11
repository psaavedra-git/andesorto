"""Agente: Claude + herramientas (menú, formularios, derivación a humano)."""
from dataclasses import dataclass
from functools import lru_cache

import anthropic

from .config import Settings
from .knowledge import build_knowledge

HANDOFF_REPLY = (
    "Le comunico con una persona de nuestro equipo 🙌. "
    "En breve le escriben por este medio o desde el número del laboratorio."
)
FALLBACK_REPLY = (
    "Disculpe, tuve un inconveniente técnico. Le comunico con una persona de nuestro equipo."
)

HANDOFF_TOOL = {
    "name": "derivar_a_humano",
    "description": (
        "Deriva la conversación al dueño o al equipo de soporte de AndesOrto y pausa el bot en este chat. "
        "Úsala cuando el cliente pida hablar con una persona, cuando la respuesta no esté en el "
        "conocimiento (o figure como [COMPLETAR]), ante quejas, o cuando pida una cotización de un trabajo "
        "con características especiales. NO la uses para pedidos o reparaciones normales: para eso está "
        "enviar_formulario."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "motivo": {
                "type": "string",
                "enum": ["solicitud_explicita", "sin_respuesta", "queja", "pedido_comercial"],
            },
            "resumen": {
                "type": "string",
                "description": "Resumen breve (1–3 frases) de lo que necesita el cliente, para el equipo humano.",
            },
        },
        "required": ["motivo", "resumen"],
    },
}

MENU_TOOL = {
    "name": "mostrar_menu",
    "description": (
        "Muestra al cliente el menú con botones: Aparato nuevo, Reparación, Precios/trabajos. Úsala al saludar "
        "o iniciar la conversación, cuando el cliente pida el menú o las opciones, o cuando no quede claro qué "
        "necesita. El texto que escribas junto a esta herramienta se mostrará encima de los botones."
    ),
    "input_schema": {"type": "object", "properties": {}},
}

FORM_TOOL = {
    "name": "enviar_formulario",
    "description": (
        "Envía al cliente el enlace al formulario digital para registrar una solicitud. Úsala en cuanto el "
        "cliente quiera pedir la elaboración de un aparato nuevo (tipo 'nuevo') o la reparación de un aparato "
        "existente (tipo 'reparacion'). No pidas los datos por chat: se completan en el formulario."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"tipo": {"type": "string", "enum": ["nuevo", "reparacion"]}},
        "required": ["tipo"],
    },
}

TOOLS = [MENU_TOOL, FORM_TOOL, HANDOFF_TOOL]


def make_client(settings: Settings) -> anthropic.Anthropic:
    headers = {"anthropic-workspace-id": settings.anthropic_workspace_id} if settings.anthropic_workspace_id else None
    return anthropic.Anthropic(api_key=settings.anthropic_api_key or None, default_headers=headers)


@dataclass
class AgentResult:
    reply: str
    handoff: dict | None = None  # {"motivo": ..., "resumen": ...}
    show_menu: bool = False
    form: str | None = None  # "nuevo" | "reparacion"


@lru_cache
def _system_blocks(prompts_dir: str, data_dir: str) -> tuple:
    from pathlib import Path

    rules = (Path(prompts_dir) / "system.md").read_text(encoding="utf-8")
    knowledge = build_knowledge(Path(data_dir))
    return (
        {"type": "text", "text": rules},
        # El conocimiento es lo más largo y estable: se cachea.
        {"type": "text", "text": knowledge, "cache_control": {"type": "ephemeral"}},
    )


def reload_knowledge() -> None:
    _system_blocks.cache_clear()


def _normalize(history: list[dict]) -> list[dict]:
    """La API exige alternar user/assistant empezando por user: fusiona mensajes seguidos del mismo rol."""
    out: list[dict] = []
    for m in history:
        if not out and m["role"] != "user":
            continue
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n" + m["content"]
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def run_agent(client: anthropic.Anthropic, settings: Settings, history: list[dict]) -> AgentResult:
    messages = _normalize(history)
    if not messages:
        return AgentResult(reply=FALLBACK_REPLY, handoff={"motivo": "sin_respuesta", "resumen": "Historial vacío"})

    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=600,
            system=list(_system_blocks(str(settings.prompts_dir), str(settings.data_dir))),
            tools=TOOLS,
            messages=messages,
        )
    except anthropic.APIError as exc:
        return AgentResult(
            reply=FALLBACK_REPLY,
            handoff={"motivo": "sin_respuesta", "resumen": f"Error del LLM: {type(exc).__name__}"},
        )

    tools = {b.name: dict(b.input) for b in response.content if b.type == "tool_use"}
    text = "".join(b.text for b in response.content if b.type == "text").strip()

    if HANDOFF_TOOL["name"] in tools:
        # Si el modelo ya dio información útil (ej. el precio estándar), se conserva antes del aviso
        reply = f"{text}\n\n{HANDOFF_REPLY}" if text else HANDOFF_REPLY
        return AgentResult(reply=reply, handoff=tools[HANDOFF_TOOL["name"]])
    if FORM_TOOL["name"] in tools:
        tipo = tools[FORM_TOOL["name"]].get("tipo")
        return AgentResult(reply=text, form=tipo if tipo in ("nuevo", "reparacion") else "nuevo")
    if MENU_TOOL["name"] in tools:
        return AgentResult(reply=text, show_menu=True)
    if not text:
        return AgentResult(reply=HANDOFF_REPLY, handoff={"motivo": "sin_respuesta", "resumen": "Respuesta vacía del LLM"})
    return AgentResult(reply=text)
