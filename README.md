# AndesOrtoBOT

Agente de WhatsApp para **AndesOrto**. Usa la WhatsApp Cloud API oficial de Meta y Claude.

- Menú con 3 botones: **Aparato nuevo**, **Reparación** y **Precios / trabajos**.
- Pedidos y reparaciones se registran con un **formulario web** (servido por el bot). Cada solicitud recibe un código (`AO-N-0001`, `AO-R-0001`), se guarda en un **Google Sheet**, se avisa a **Karla** por WhatsApp y el doctor recibe la confirmación.
- Responde preguntas frecuentes y precios del tarifario estándar. No promete fechas de entrega: se confirman después de la revisión del técnico.
- **Deriva** al dueño o al equipo cuando el cliente lo pide, se queja, pide cotizar un trabajo especial o la respuesta no está en el conocimiento. En ese caso el bot se **pausa** en ese chat y avisa al dueño por WhatsApp.

## Estructura
| Ruta | Qué es |
|---|---|
| `data/negocio.yaml`, `data/catalogo.yaml`, `data/faq.yaml` | **Conocimiento del bot**: editar aquí (hoy tiene datos de ejemplo) |
| `prompts/system.md` | Reglas y tono del agente |
| `app/main.py` | Webhook FastAPI (`GET/POST /webhook`, `/health`) |
| `app/bot.py` | Flujo por mensaje (dedupe → dueño/comandos → pausa → agente) |
| `app/agent.py` | Claude + herramientas `mostrar_menu`, `enviar_formulario`, `derivar_a_humano` |
| `app/handoff.py` | Pausa, aviso al dueño y comandos del dueño |
| `app/orders.py`, `app/forms.py` | Formularios: enlaces firmados, página web, registro y avisos |
| `apps_script/Code.gs` | Script que escribe las solicitudes en el Google Sheet |
| `app/whatsapp.py` | Envío y recepción con la Cloud API |
| `app/store.py` | SQLite: historial, pausas y deduplicación |

## Probar en local (sin WhatsApp)
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # y poner ANTHROPIC_API_KEY
python scripts/chat_local.py    # conversación por consola
pytest                          # tests
```

## Configurar WhatsApp Cloud API (Meta)
1. En **developers.facebook.com**, crear una app de tipo *Business* y agregar el producto **WhatsApp**.
2. En *WhatsApp > Configuración de la API*, agregar y verificar el número del laboratorio. Ese número **no puede** estar activo en la app de WhatsApp: si lo está, hay que eliminar la cuenta en el teléfono. Para empezar se puede usar el número de prueba de Meta.
3. En Business Manager, ir a *Usuarios del sistema*, crear un usuario admin, asignarle la app y la cuenta de WhatsApp y generar un **token permanente** con permisos `whatsapp_business_messaging` y `whatsapp_business_management`. Ese token va en `WA_TOKEN`.
4. Copiar el **Phone number ID** en `WA_PHONE_NUMBER_ID` y la **clave secreta de la app** (Configuración > Básica) en `WA_APP_SECRET`.
5. En *WhatsApp > Configuración > Webhook*, poner la URL `https://<su-dominio>/webhook` y el token de verificación igual a `WA_VERIFY_TOKEN`. Luego suscribirse al campo **messages**.
6. En WhatsApp Manager, crear la plantilla de categoría **Utilidad** con nombre `alerta_derivacion` en idioma `es`:
   > Nueva derivación de AndesOrtoBOT. Cliente: {{1}}. Motivo: {{2}}. Resumen: {{3}}. Revise WhatsApp para ver el detalle.

   La plantilla es necesaria porque Meta solo permite texto libre al dueño si este escribió al número del bot en las últimas 24 h. Un truco útil: que el dueño le escriba **#pausados** al bot cada mañana, así se abre la ventana y recibe el detalle completo.

Para desarrollo, exponer el servidor local con `uvicorn app.main:app --port 8000` y `ngrok http 8000` (o `cloudflared`).

## Formularios y Google Sheet
- Los enlaces que envía el bot (`/f/nuevo?t=…`, `/f/reparacion?t=…`) identifican el WhatsApp del doctor y vencen a las `FORM_LINK_HOURS` horas.
- Para la web de AndesOrto, enlace directamente a `https://<servidor>/f/nuevo` y `https://<servidor>/f/reparacion`. Sin enlace firmado, el formulario pide el WhatsApp de contacto.
- **Configurar el Google Sheet:** siga las instrucciones al inicio de [apps_script/Code.gs](apps_script/Code.gs) y luego complete `SHEETS_WEBHOOK_URL` y `SHEETS_SECRET` en `.env`. Si el Sheet falla, la solicitud igual queda guardada en la base del bot (tabla `orders`).
- **Aviso a Karla:** `NOTIFY_WA_NUMBER`. Fuera de la ventana de 24 h se necesita una plantilla aprobada (`NOTIFY_TEMPLATE_NAME`, categoría Utilidad, 2 variables), por ejemplo:
  > Nueva solicitud {{1}} en AndesOrto: {{2}}. Revise la hoja de solicitudes.

## Comandos del dueño
El dueño los escribe al número del bot desde `OWNER_WA_NUMBER`:
- `#pausados`: lista los chats derivados.
- `#bot on 51999888777`: reactiva el bot en ese chat.
- `#bot off 51999888777`: pausa el bot en ese chat (por ejemplo, para atenderlo uno mismo).

Los chats derivados se reactivan solos tras `HANDOFF_TIMEOUT_HOURS` (por defecto 24 h).

## Despliegue
Con Docker en Railway, Render o Fly.io, con un volumen persistente montado en `/data` para la base SQLite. Las variables de entorno se configuran según `.env.example`.

## Actualizar el conocimiento
Editar los YAML de `data/` y reiniciar el servicio. Todo lo que diga `[COMPLETAR]` el bot **no lo inventa**: deriva a una persona.
