"""Páginas del formulario de pedido / reparación (servidas por el mismo bot)."""
import re
from html import escape

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse

from .orders import FORMS, PHONE_FIELD, finish_order, read_token

router = APIRouter()

CSS = """
:root{--bg:#f4f7f9;--card:#fff;--text:#1d2a33;--muted:#5d6b75;--accent:#0b7a75;--border:#d5dde3;--err:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#11181d;--card:#1a242b;--text:#e7eef2;--muted:#9fb0bb;--accent:#3cc1b9;--border:#2d3b45;--err:#f97066}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:560px;margin:0 auto;padding:24px 16px 48px}
.brand{font-weight:700;color:var(--accent);letter-spacing:.02em;margin-bottom:4px}
h1{font-size:1.35rem;margin:0 0 4px}p.sub{color:var(--muted);margin:0 0 20px}
form,.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px}
label{display:block;font-weight:600;margin:0 0 6px}.opt{font-weight:400;color:var(--muted)}
input,textarea{width:100%;padding:12px;border:1px solid var(--border);border-radius:10px;background:transparent;color:var(--text);font:inherit;margin-bottom:16px}
textarea{min-height:110px;resize:vertical}input:focus,textarea:focus{outline:2px solid var(--accent);border-color:transparent}
button{width:100%;padding:14px;border:0;border-radius:10px;background:var(--accent);color:#fff;font:600 1rem inherit;cursor:pointer}
.err{color:var(--err);margin:0 0 16px}.code{font-size:1.6rem;font-weight:700;color:var(--accent);margin:8px 0}
.note{color:var(--muted);font-size:.9rem;margin-top:16px}
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} · AndesOrto</title>
<style>{CSS}</style></head><body><main><div class="brand">AndesOrto</div>{body}</main></body></html>"""
    )


def _catalog_names(request: Request) -> list[str]:
    path = request.app.state.settings.data_dir / "catalogo.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return []
    return [str(p["nombre"]) for p in data.get("productos", []) if p.get("nombre")]


def _render_form(request: Request, tipo: str, token: str, wa_id: str | None, values: dict, error: str = "") -> HTMLResponse:
    form = FORMS[tipo]
    campos = list(form["campos"]) + ([] if wa_id else [PHONE_FIELD])
    names = "".join(f'<option value="{escape(n)}">' for n in _catalog_names(request))
    fields = []
    for key, label, kind, required in campos:
        val = escape(values.get(key, ""))
        req = " required" if required else ""
        lab = f'<label for="{key}">{escape(label)}{"" if required else " <span class=opt>(opcional)</span>"}</label>'
        if kind == "textarea":
            fields.append(f'{lab}<textarea id="{key}" name="{key}" maxlength="1500"{req}>{val}</textarea>')
        else:
            extra = ' list="catalogo" autocomplete="off"' if key == "aparato" else ""
            extra += ' inputmode="tel" placeholder="51 999 888 777"' if kind == "tel" else ""
            fields.append(f'{lab}<input id="{key}" name="{key}" type="{kind}" maxlength="200" value="{val}"{req}{extra}>')
    err = f'<p class="err">{escape(error)}</p>' if error else ""
    body = f"""<h1>{escape(form['titulo'])}</h1>
<p class="sub">Complete los datos y envíe. Le confirmaremos con un número de solicitud.</p>
<form method="post">{err}<input type="hidden" name="t" value="{escape(token)}">
{''.join(fields)}<datalist id="catalogo">{names}</datalist>
<button type="submit">Enviar solicitud</button>
<p class="note">La fecha de entrega se confirma después de la revisión del técnico.</p></form>"""
    return _page(form["titulo"], body)


@router.get("/f/{tipo}", response_class=HTMLResponse)
def show_form(request: Request, tipo: str, t: str = ""):
    if tipo not in FORMS:
        raise HTTPException(404)
    s = request.app.state.settings
    return _render_form(request, tipo, t, read_token(s, tipo, t), {})


@router.post("/f/{tipo}", response_class=HTMLResponse)
async def submit_form(request: Request, tipo: str, background: BackgroundTasks):
    if tipo not in FORMS:
        raise HTTPException(404)
    s = request.app.state.settings
    bot = request.app.state.bot
    raw = await request.form()
    token = str(raw.get("t", ""))
    wa_id = read_token(s, tipo, token)
    campos = list(FORMS[tipo]["campos"]) + ([] if wa_id else [PHONE_FIELD])
    data = {k: " ".join(str(raw.get(k, "")).split())[:1500] for k, *_ in campos}

    missing = [label for k, label, _, req in campos if req and not data[k]]
    if missing:
        return _render_form(request, tipo, token, wa_id, data, "Falta completar: " + ", ".join(missing))
    if not wa_id:
        phone = re.sub(r"\D", "", data["telefono"])
        if len(phone) == 9:  # celular peruano sin código de país
            phone = "51" + phone
        if not 10 <= len(phone) <= 15:
            return _render_form(request, tipo, token, wa_id, data, "Revise el número de WhatsApp de contacto.")
        data["telefono"] = phone

    code = bot.store.add_order(tipo, wa_id, data)
    background.add_task(finish_order, s, bot.store, bot.wa, tipo, code, wa_id, data)
    body = f"""<div class="card"><h1>¡Solicitud recibida!</h1>
<p>Su número de solicitud es:</p><div class="code">{escape(code)}</div>
<p>{'Le enviamos la confirmación por WhatsApp. ' if wa_id else ''}Nuestro equipo la revisará y le contactará.</p>
<p class="note">La fecha de entrega se confirma después de la revisión del técnico.</p></div>"""
    return _page("Solicitud recibida", body)
