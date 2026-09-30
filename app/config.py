import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEMO_DATE = "2026-09-30"
LOW_MARGIN_THRESHOLD = 15
STAGES = ["Замер", "Проектирование", "Согласование", "Комплектация", "Производство",
          "Контроль качества", "Доставка", "Монтаж", "Приёмка", "Завершён"]
COST_FIELDS = ["revenue", "materials", "manufacturing", "delivery", "installation", "commission", "rework"]


@dataclass
class Settings:
    database_path: str = str(ROOT / "data/app.db")
    public_base_url: str = ""
    admin_username: str = "coordinator"
    admin_password: str = ""
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    coordinator_telegram_id: int | None = None
    allow_local_http: bool = False

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        path = Path(os.getenv("DATABASE_PATH", "data/app.db"))
        return cls(
            database_path=str(path if path.is_absolute() else ROOT / path),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
            admin_username=os.getenv("ADMIN_USERNAME", "coordinator"),
            admin_password=os.getenv("ADMIN_PASSWORD", ""),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", ""),
            coordinator_telegram_id=int(os.environ["COORDINATOR_TELEGRAM_ID"]) if os.getenv("COORDINATOR_TELEGRAM_ID") else None,
            allow_local_http=os.getenv("ALLOW_LOCAL_HTTP", "false").lower() == "true",
        )
