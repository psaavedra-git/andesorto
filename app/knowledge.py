"""Carga negocio/catálogo/FAQ desde YAML y los convierte en texto para el system prompt."""
from pathlib import Path

import yaml


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def build_knowledge(data_dir: Path) -> str:
    negocio = _load(data_dir / "negocio.yaml")
    catalogo = _load(data_dir / "catalogo.yaml").get("productos", [])
    faq = _load(data_dir / "faq.yaml").get("faq", [])

    parts = ["# CONOCIMIENTO", "", "## Datos del negocio"]
    for key, value in negocio.items():
        parts.append(f"- {key.replace('_', ' ')}: {str(value).strip()}")

    parts += ["", "## Catálogo de productos"]
    for p in catalogo:
        parts.append(f"### {p.get('nombre', '(sin nombre)')}")
        for key, value in p.items():
            if key != "nombre" and value not in (None, ""):
                parts.append(f"- {key}: {str(value).strip()}")

    parts += ["", "## Preguntas frecuentes"]
    for item in faq:
        parts.append(f"P: {item.get('pregunta', '').strip()}")
        parts.append(f"R: {item.get('respuesta', '').strip()}")
        parts.append("")

    return "\n".join(parts).strip()
