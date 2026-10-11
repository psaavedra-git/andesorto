"""Simulador de consola: conversa con el agente sin WhatsApp (usa Claude real y una BD temporal).

Uso:  python scripts/chat_local.py      (requiere ANTHROPIC_API_KEY en .env)
Comandos: /reset borra el historial · /salir
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


from app.agent import make_client, run_agent  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.orders import form_link_message  # noqa: E402


def main() -> None:
    s = get_settings()
    llm = make_client(s)
    history: list[dict] = []
    print("AndesOrtoBOT (simulador). /reset para reiniciar, /salir para terminar.\n")
    while True:
        try:
            text = input("👤 ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text == "/salir":
            break
        if text == "/reset":
            history.clear()
            print("— historial borrado —\n")
            continue
        history.append({"role": "user", "content": text})
        result = run_agent(llm, s, history[-s.history_limit :])
        history.append({"role": "assistant", "content": result.reply})
        if result.reply:
            print(f"🤖 {result.reply}")
        if result.show_menu:
            print("   [botones] 🦷 Aparato nuevo | 🔧 Reparación | 💲 Precios/trabajos")
        if result.form:
            print(f"🤖 {form_link_message(s, result.form, 'SIMULADOR')}")
        if result.handoff:
            print(f"   ⚠️  DERIVACIÓN → {result.handoff}  (en producción el bot se pausa aquí)")
        print()


if __name__ == "__main__":
    main()
