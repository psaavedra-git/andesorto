"""Servidor FastAPI: webhook de WhatsApp Cloud API."""
import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .agent import make_client
from .bot import Bot
from .config import get_settings
from .forms import router as forms_router
from .store import Store
from .whatsapp import WhatsAppClient, parse_incoming, verify_signature

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("andesorto")

settings = get_settings()
app = FastAPI(title="AndesOrtoBOT")
bot = Bot(
    settings,
    Store(settings.db_path),
    WhatsAppClient(settings),
    make_client(settings),
)
app.state.settings = settings
app.state.bot = bot
app.include_router(forms_router)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/webhook", response_class=PlainTextResponse)
def verify(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    if mode == "subscribe" and settings.wa_verify_token and token == settings.wa_verify_token:
        return challenge
    raise HTTPException(status_code=403)


def _safe_handle(msg) -> None:
    try:
        bot.handle(msg)
    except Exception:
        log.exception("Error procesando mensaje %s", msg.id)


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    body = await request.body()
    if not verify_signature(settings.wa_app_secret, body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="invalid signature")
    # Meta exige 200 rápido: el LLM corre en segundo plano.
    for msg in parse_incoming(await request.json()):
        background.add_task(_safe_handle, msg)
    return {"ok": True}
