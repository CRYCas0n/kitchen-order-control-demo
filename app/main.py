import asyncio
import contextlib
import json
import logging
import secrets
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from .config import ROOT, Settings
from .database import add_history, connect, dashboard, get_order, initialize, now
from .telegram import TelegramAPI, delivery_loop, process_update
from .validation import ReworkInput

security = HTTPBasic(auto_error=False)


def create_app(settings=None, telegram_api=None, worker=True):
    settings = settings or Settings.from_env()
    initialize(settings.database_path)
    api = telegram_api or TelegramAPI(settings.telegram_bot_token)

    @asynccontextmanager
    async def lifespan(app):
        # After a crash, 'sending' may have reached Telegram: never blindly resend.
        with connect(settings.database_path) as db:
            db.execute("UPDATE telegram_outbox SET status='uncertain',error='Процесс остановился во время отправки; проверьте доставку' WHERE status='sending'")
        task = asyncio.create_task(delivery_loop(settings.database_path, api)) if worker else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="Контроль заказов кухонной фабрики", debug=False, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.settings = settings

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith(("/api/", "/admin")) else "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": "Некорректные данные. Сумма должна быть от 0 до 1 000 000 000 ₽, максимум два знака после запятой."})

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        logging.getLogger(__name__).error("Request failed: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера. Повторите запрос позже."})

    def admin(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)):
        local = settings.allow_local_http and request.url.hostname in ("localhost", "127.0.0.1", "testserver")
        if request.url.scheme != "https" and not local:
            raise HTTPException(403, "Для административного интерфейса требуется HTTPS")
        if not settings.admin_password:
            raise HTTPException(503, "Доступ координатора ещё не настроен")
        if credentials is None or not (
            secrets.compare_digest(credentials.username.encode(), settings.admin_username.encode()) and
            secrets.compare_digest(credentials.password.encode(), settings.admin_password.encode())
        ):
            raise HTTPException(401, "Требуется вход координатора", headers={"WWW-Authenticate": 'Basic realm="Coordinator", charset="UTF-8"'})
        return credentials.username

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static/index.html")

    @app.get("/admin")
    def admin_page(username=Depends(admin)):
        return FileResponse(ROOT / "templates/admin.html")

    @app.get("/api/health")
    def health():
        try:
            with connect(settings.database_path) as db:
                db.execute("SELECT COUNT(*) FROM orders").fetchone()
            return {"status": "ok", "database": "ok", "timestamp": now(), "version": "1.0.0"}
        except sqlite3.Error:
            return JSONResponse(status_code=503, content={"status": "unavailable", "database": "unavailable"})

    @app.get("/api/dashboard")
    def get_dashboard():
        with connect(settings.database_path) as db:
            return dashboard(db)

    @app.get("/api/orders")
    def orders():
        with connect(settings.database_path) as db:
            return dashboard(db)["orders"]

    @app.get("/api/orders/{order_id}")
    def order(order_id: int):
        with connect(settings.database_path) as db:
            result = get_order(db, order_id)
        if result is None:
            raise HTTPException(404, "Заказ не найден")
        return result

    @app.get("/api/orders/{order_id}/history")
    def history(order_id: int):
        return order(order_id)["history"]

    @app.post("/api/admin/orders/{order_id}/rework")
    def rework(order_id: int, body: ReworkInput, request: Request, username=Depends(admin),
               x_requested_with: str | None = Header(default=None)):
        if x_requested_with != "kitchen-control":
            raise HTTPException(403, "Отсутствует защитный заголовок")
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Недопустимый источник запроса")
        with connect(settings.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT rework_actual FROM costs WHERE order_id=?", (order_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Заказ или финансовые данные не найдены")
            value = float(body.rework_actual)
            db.execute("UPDATE costs SET rework_actual=?,updated_at=? WHERE order_id=?", (value, now(), order_id))
            db.execute("UPDATE orders SET updated_at=? WHERE id=?", (now(), order_id))
            previous = "не указана" if row[0] is None else f"{row[0]:,.2f} ₽".replace(",", " ")
            add_history(db, order_id, "rework_changed", f"Стоимость переделки изменена: {previous} → {value:,.2f} ₽".replace(",", " "),
                        source="admin", actor_type="coordinator", actor_ref="Координатор", payload={"old": row[0], "new": value})
            return get_order(db, order_id)

    @app.post("/telegram/webhook")
    async def webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
        expected = settings.telegram_webhook_secret
        if not expected or not x_telegram_bot_api_secret_token or not secrets.compare_digest(expected.encode(), x_telegram_bot_api_secret_token.encode()):
            raise HTTPException(403, "Недопустимый webhook secret")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 262144:
                raise HTTPException(413, "Слишком большой запрос")
        try:
            update = json.loads(raw)
            if not isinstance(update, dict):
                raise ValueError()
            with connect(settings.database_path) as db:
                db.execute("BEGIN IMMEDIATE")
                return process_update(db, update, settings)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(422, "Некорректный Telegram update") from None

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app


app = create_app()
