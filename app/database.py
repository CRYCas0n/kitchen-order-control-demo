import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .calculations import enrich, summarize_orders
from .config import COST_FIELDS, DEMO_DATE, LOW_MARGIN_THRESHOLD, STAGES


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    stage_values = ",".join(f"'{stage}'" for stage in STAGES)
    costs = ",\n".join(f"{field}_{kind} NUMERIC CHECK({field}_{kind} IS NULL OR (typeof({field}_{kind}) IN ('integer','real') AND {field}_{kind} >= 0 AND {field}_{kind} <= 1000000000))"
                        for kind in ("plan", "actual") for field in COST_FIELDS)
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(f"""
        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY, order_number TEXT NOT NULL UNIQUE,
          client_alias TEXT NOT NULL, sales_point_type TEXT NOT NULL CHECK(sales_point_type IN ('Шоурум','Дилер')),
          sales_point TEXT NOT NULL, city TEXT NOT NULL, coordinator TEXT NOT NULL,
          stage_executor TEXT NOT NULL, stage TEXT NOT NULL CHECK(stage IN ({stage_values})),
          promised_date_initial TEXT NOT NULL, forecast_date TEXT NOT NULL, completed_date TEXT,
          next_action TEXT NOT NULL, next_action_due TEXT NOT NULL,
          problem_type TEXT, problem_comment TEXT, problem_help_needed TEXT,
          problem_status TEXT NOT NULL DEFAULT 'none' CHECK(problem_status IN ('none','open','resolved')),
          project_version TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
          role TEXT NOT NULL CHECK(role IN ('measurer','installer')),
          assignee_code TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new'
            CHECK(status IN ('new','accepted','problem','transfer_requested','completed')),
          due_date TEXT NOT NULL, accepted_at TEXT, completed_at TEXT, proposed_date TEXT,
          transfer_reason TEXT, checklist_result TEXT, comment TEXT, photo_file_id TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS costs (
          order_id INTEGER PRIMARY KEY REFERENCES orders(id), {costs}, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telegram_updates (update_id INTEGER PRIMARY KEY, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history (
          id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
          task_id INTEGER REFERENCES tasks(id), event_type TEXT NOT NULL,
          actor_type TEXT NOT NULL, actor_ref TEXT NOT NULL,
          source TEXT NOT NULL CHECK(source IN ('telegram','admin','simulation','system')),
          comment TEXT NOT NULL, telegram_update_id INTEGER UNIQUE,
          payload TEXT NOT NULL DEFAULT '{{}}', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS history_order ON history(order_id,id);
        CREATE TABLE IF NOT EXISTS telegram_users (
          telegram_id INTEGER PRIMARY KEY, display_name TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('measurer','installer','coordinator')),
          assignee_code TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS telegram_sessions (
          telegram_id INTEGER PRIMARY KEY REFERENCES telegram_users(telegram_id), action TEXT NOT NULL,
          task_id INTEGER NOT NULL REFERENCES tasks(id), step TEXT NOT NULL, nonce TEXT NOT NULL,
          payload TEXT NOT NULL DEFAULT '{{}}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telegram_outbox (
          id INTEGER PRIMARY KEY, update_id INTEGER NOT NULL REFERENCES telegram_updates(update_id),
          dedupe_key TEXT NOT NULL UNIQUE, method TEXT NOT NULL, body TEXT NOT NULL,
          order_id INTEGER REFERENCES orders(id), notification INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','sent','failed','uncertain')),
          error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """)


def add_history(db, order_id, event_type, comment, *, source="system", actor_type="system",
                actor_ref="Система", task_id=None, update_id=None, payload=None):
    db.execute("""INSERT INTO history(order_id,task_id,event_type,actor_type,actor_ref,source,
                  comment,telegram_update_id,payload,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
               (order_id, task_id, event_type, actor_type, actor_ref, source, comment, update_id,
                json.dumps(payload or {}, ensure_ascii=False), now()))


def get_order(db, order_id):
    row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if row is None:
        return None
    result = enrich(dict(row), db.execute("SELECT * FROM costs WHERE order_id=?", (order_id,)).fetchone())
    # Telegram IDs, raw payloads and photo identifiers stay server-side.
    result["history"] = [dict(h) for h in db.execute("""SELECT id,event_type,actor_type,actor_ref,source,comment,created_at
                                           FROM history WHERE order_id=? ORDER BY id DESC""", (order_id,))]
    result["tasks"] = [dict(t) for t in db.execute("""SELECT id,role,status,due_date,accepted_at,completed_at,proposed_date,
                                    transfer_reason,comment FROM tasks WHERE order_id=?""", (order_id,))]
    return result


def dashboard(db):
    # One read snapshot for orders, costs and history, including concurrent Telegram/admin writes.
    if not db.in_transaction:
        db.execute("BEGIN")
    orders = [get_order(db, row[0]) for row in db.execute("SELECT id FROM orders ORDER BY id")]
    summary = summarize_orders(orders)
    return {"demo_date": DEMO_DATE, "low_margin_threshold": LOW_MARGIN_THRESHOLD,
            "source": "backend", "stages": STAGES, "generated_at": now(), "orders": orders,
            "kpis": summary["kpis"], "summary": summary}
