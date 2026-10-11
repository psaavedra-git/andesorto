from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5-5"
    # Solo para claves de usuario (sk-ant-usr...) sin workspace asignado
    anthropic_workspace_id: str = ""

    wa_token: str = ""
    wa_phone_number_id: str = ""
    wa_app_secret: str = ""
    wa_verify_token: str = ""
    wa_api_version: str = "v21.0"

    owner_wa_number: str = ""
    owner_template_name: str = ""
    owner_template_lang: str = "es"
    handoff_timeout_hours: float = 24

    # Formularios de pedido / reparación
    public_base_url: str = "http://127.0.0.1:8000"  # URL pública del servidor (para armar los enlaces)
    form_secret: str = ""  # firma de los enlaces; si está vacío se usa wa_app_secret
    form_link_hours: float = 72
    notify_wa_number: str = ""  # quien recibe los pedidos (Karla)
    notify_template_name: str = ""  # plantilla aprobada para el aviso de pedido (opcional)
    sheets_webhook_url: str = ""  # URL del Apps Script publicado como aplicación web
    sheets_secret: str = ""

    db_path: str = str(BASE_DIR / "andesorto.db")
    history_limit: int = 20
    data_dir: Path = BASE_DIR / "data"
    prompts_dir: Path = BASE_DIR / "prompts"


@lru_cache
def get_settings() -> Settings:
    return Settings()
