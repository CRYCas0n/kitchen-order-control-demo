"""Operational CLI: reads credentials from .env; never prints tokens."""
import argparse
import asyncio
import json
import sqlite3
from pathlib import Path

import httpx

from app.config import Settings
from app.database import connect, initialize, now


def add_user(settings, telegram_id, role, code, name):
    if telegram_id <= 0:
        raise ValueError("Use a real positive Telegram user ID")
    with connect(settings.database_path) as db:
        db.execute("""INSERT INTO telegram_users VALUES (?,?,?,?,1) ON CONFLICT(telegram_id)
                      DO UPDATE SET display_name=excluded.display_name,role=excluded.role,assignee_code=excluded.assignee_code,active=1""",
                   (telegram_id, name, role, code))
        db.execute("DELETE FROM telegram_sessions WHERE telegram_id=?", (telegram_id,))


async def telegram_setup(settings, set_webhook=False):
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing")
    async with httpx.AsyncClient(timeout=20) as client:
        async def call(method, body):
            try:
                response = await client.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}", json=body)
                result = response.json()
                if not response.is_success or not result.get("ok"):
                    raise SystemExit(f"Telegram {method} failed (HTTP {response.status_code})")
                return result["result"]
            except httpx.HTTPError:
                raise SystemExit(f"Telegram {method}: connection failed") from None
        me = await call("getMe", {})
        print("Bot:", me["username"])
        if set_webhook:
            if not settings.public_base_url.startswith("https://") or not settings.telegram_webhook_secret:
                raise SystemExit("PUBLIC_BASE_URL=https://... and TELEGRAM_WEBHOOK_SECRET are required")
            await call("setWebhook", {"url":settings.public_base_url+"/telegram/webhook",
                       "secret_token":settings.telegram_webhook_secret,"allowed_updates":["message","callback_query"],
                       "max_connections":4,"drop_pending_updates":False})
            await call("setMyCommands", {"commands":[{"command":"start","description":"Войти и получить задания"},
                        {"command":"tasks","description":"Мои задания"},{"command":"cancel","description":"Отменить текущий диалог"}]})
        info=await call("getWebhookInfo", {})
        print(json.dumps({k:info.get(k) for k in ("url","pending_update_count","last_error_date","last_error_message")},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="command",required=True)
    user=sub.add_parser("add-user")
    user.add_argument("telegram_id",type=int)
    user.add_argument("role",choices=["installer","measurer","coordinator"])
    user.add_argument("assignee_code")
    user.add_argument("display_name")
    backup=sub.add_parser("backup");backup.add_argument("destination")
    sub.add_parser("webhook");sub.add_parser("telegram-info");sub.add_parser("outbox")
    args=parser.parse_args();settings=Settings.from_env();initialize(settings.database_path)
    if args.command=="add-user":
        add_user(settings,args.telegram_id,args.role,args.assignee_code,args.display_name)
        print("User saved. Open /start in the bot.")
    elif args.command=="backup":
        destination=Path(args.destination).resolve()
        if destination==Path(settings.database_path).resolve() or destination.exists():
            raise SystemExit("Choose a new backup path; existing files are never overwritten")
        destination.parent.mkdir(parents=True,exist_ok=True)
        with connect(settings.database_path) as source:
            target=sqlite3.connect(destination)
            try:source.backup(target)
            finally:target.close()
        print("SQLite backup created")
    elif args.command=="outbox":
        with connect(settings.database_path) as db:
            for row in db.execute("SELECT id,notification,status,error,created_at FROM telegram_outbox WHERE status!='sent' ORDER BY id"):
                print(json.dumps(dict(row),ensure_ascii=False))
    else:asyncio.run(telegram_setup(settings,args.command=="webhook"))


if __name__=="__main__":main()
