"""Transactional Telegram dialogue and durable delivery queue; no polling."""
import asyncio
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

import httpx

from .database import add_history, connect, now
from .validation import iso_date

logger = logging.getLogger(__name__)
ROLES = {"installer": "Монтажник", "measurer": "Замерщик", "coordinator": "Координатор"}
MAX_SQLITE_ID = 2**63 - 1
CHECKLISTS = {
    "installer": ["Монтаж завершён", "Основные элементы проверены", "Замечания зафиксированы", "Рабочая зона передана"],
    "measurer": ["Основные размеры проверены", "Особенности помещения зафиксированы", "Необходимые замечания добавлены"],
}


class TelegramAPI:
    def __init__(self, token):
        self.token = token

    async def call(self, method, body):
        if not self.token:
            return "failed", "Telegram не настроен"
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.post(f"https://api.telegram.org/bot{self.token}/{method}", json=body)
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
                return "uncertain", "Некорректное подтверждение Telegram; проверьте доставку перед повтором"
            if response.is_success and data.get("ok"):
                return "sent", None
            # Do not log request URLs or raw remote errors: they may contain secrets.
            return "failed", f"Telegram отклонил запрос (HTTP {response.status_code})"
        except (httpx.HTTPError, ValueError):
            return "uncertain", "Нет подтверждения доставки; проверьте Telegram перед повтором"


def queue(db, update_id, key, body, *, method="sendMessage", order_id=None, notification=False):
    db.execute("""INSERT OR IGNORE INTO telegram_outbox(update_id,dedupe_key,method,body,order_id,notification,created_at,updated_at)
                  VALUES (?,?,?,?,?,?,?,?)""",
               (update_id, f"{update_id}:{key}", method, json.dumps(body, ensure_ascii=False), order_id, int(notification), now(), now()))


def buttons(rows):
    return {"inline_keyboard": [[{"text": label, "callback_data": data} for label, data in row] for row in rows]}


def process_update(db, update, settings):
    """Caller owns BEGIN IMMEDIATE. Business writes, sessions and outbox commit together."""
    uid = update.get("update_id")
    if type(uid) is not int or not 0 <= uid <= MAX_SQLITE_ID:
        raise ValueError("Некорректный update_id")
    if not db.execute("INSERT OR IGNORE INTO telegram_updates VALUES (?,?)", (uid, now())).rowcount:
        return {"ok": True, "duplicate": True}
    callback = update.get("callback_query") or {}
    message = callback.get("message") or update.get("message") or {}
    sender = callback.get("from") or message.get("from") or {}
    telegram_id = sender.get("id")
    chat = message.get("chat") or {}
    if type(telegram_id) is not int or not 0 < telegram_id <= MAX_SQLITE_ID or chat.get("type") != "private" or chat.get("id") != telegram_id or sender.get("is_bot"):
        return {"ok": True, "ignored": True}
    if callback.get("id"):
        queue(db, uid, "ack", {"callback_query_id": callback["id"]}, method="answerCallbackQuery")

    def reply(text, markup=None):
        body = {"chat_id": telegram_id, "text": text}
        if markup:
            body["reply_markup"] = markup
        queue(db, uid, "reply", body)

    user = db.execute("SELECT * FROM telegram_users WHERE telegram_id=? AND active=1", (telegram_id,)).fetchone()
    if user is None:
        reply(f"Ваш Telegram ID: {telegram_id}. Передайте его администратору для подключения.")
        return {"ok": True}
    user = dict(user)
    text = (message.get("text") or "").strip()
    data = callback.get("data", "")
    if not isinstance(data, str):
        data = ""
    if not callback and text in ("/start", "/tasks", "/cancel"):
        db.execute("DELETE FROM telegram_sessions WHERE telegram_id=?", (telegram_id,))
        if user["role"] == "coordinator":
            reply("Вы подключены как координатор. Здесь будут уведомления о проблемах и переносах. "
                  + (f"Интерфейс: {settings.public_base_url}/admin" if settings.public_base_url else "Адрес интерфейса сообщит администратор."))
        else:
            tasks = db.execute("""SELECT t.id,o.order_number,o.stage,t.due_date FROM tasks t JOIN orders o ON o.id=t.order_id
                                  WHERE t.assignee_code=? AND t.role=? AND t.status!='completed' ORDER BY t.id""",
                               (user["assignee_code"], user["role"])).fetchall()
            reply(f"{user['display_name']} · {ROLES[user['role']]}\nВаши задания. Для отмены диалога: /cancel",
                  buttons([[(f"{t['order_number']} · {t['stage']} · {t['due_date']}", f"task:{t['id']}")] for t in tasks]) if tasks else None)
        return {"ok": True}

    def own_task(task_id):
        if not 0 < task_id <= MAX_SQLITE_ID:
            return None
        task = db.execute("""SELECT t.*,o.stage,o.order_number FROM tasks t JOIN orders o ON o.id=t.order_id
                             WHERE t.id=? AND t.assignee_code=? AND t.role=?""",
                          (task_id, user["assignee_code"], user["role"])).fetchone()
        return dict(task) if task else None

    def history(task, event, comment, payload=None):
        add_history(db, task["order_id"], event, comment, source="telegram", actor_type=user["role"],
                    actor_ref=f"{user['display_name']} / {ROLES[user['role']]}", task_id=task["id"], update_id=uid, payload=payload)
        db.execute("UPDATE orders SET updated_at=? WHERE id=?", (now(), task["order_id"]))

    def notify(task, summary):
        target = settings.coordinator_telegram_id
        coordinator = db.execute("SELECT 1 FROM telegram_users WHERE telegram_id=? AND role='coordinator' AND active=1", (target,)).fetchone()
        if not target or not coordinator:
            add_history(db, task["order_id"], "notification_failed", "Уведомление не отправлено: координатор не подключён.")
            return False
        queue(db, uid, "coordinator", {"chat_id": target,
              "text": f"{task['order_number']} · {user['display_name']} / {ROLES[user['role']]}\n{summary}"},
              order_id=task["order_id"], notification=True)
        return True

    parts = data.split(":")
    if parts[0] in ("task", "accept", "problem", "transfer", "done") and len(parts) == 2 and parts[1].isdigit():
        task = own_task(int(parts[1]))
        if not task:
            reply("Нет доступа к этому заданию. Откройте /tasks.")
            return {"ok": True}
        if task["status"] == "completed":
            reply("Задание уже выполнено. Откройте /tasks.")
            return {"ok": True}
        expected_stage = "Монтаж" if user["role"] == "installer" else "Замер"
        if task["stage"] != expected_stage:
            reply("Стадия заказа изменилась. Обратитесь к координатору.")
            return {"ok": True}
        action = parts[0]
        db.execute("DELETE FROM telegram_sessions WHERE telegram_id=?", (telegram_id,))
        if action == "task":
            reply(f"{task['order_number']} · {task['stage']}\nСрок задания: {task['due_date']}", buttons([
                [("Принял задание", f"accept:{task['id']}"), ("Выполнено", f"done:{task['id']}")],
                [("Есть проблема", f"problem:{task['id']}"), ("Нужен перенос", f"transfer:{task['id']}")]]))
        elif action == "accept":
            if task["accepted_at"]:
                reply("Вы уже приняли это задание.")
            else:
                db.execute("UPDATE tasks SET status='accepted',accepted_at=?,updated_at=? WHERE id=?", (now(), now(), task["id"]))
                history(task, "accepted", "Исполнитель принял задание")
                reply("Задание принято. /tasks — вернуться к списку.")
        else:
            step = {"problem": "type", "transfer": "date", "done": "checklist"}[action]
            nonce = secrets.token_hex(4)
            db.execute("INSERT INTO telegram_sessions VALUES (?,?,?,?,?,?,?)", (telegram_id, action, task["id"], step, nonce, "{}", now()))
            if action == "problem":
                reply("Укажите тип проблемы (например: комплектация, повреждение, проект). /cancel — отмена.")
            elif action == "transfer":
                reply("Предлагаемая дата: ГГГГ-ММ-ДД. Это запрос координатору, обещанный клиенту срок не изменится.")
            else:
                reply("Подтвердите каждый пункт перед сдачей:\n" + "\n".join(f"• {item}" for item in CHECKLISTS[user["role"]]),
                      buttons([[("Все пункты проверены", f"check:{nonce}")]]))
        return {"ok": True}

    session = db.execute("SELECT * FROM telegram_sessions WHERE telegram_id=?", (telegram_id,)).fetchone()
    if session is None:
        reply("Выберите задание через /tasks.")
        return {"ok": True}
    session = dict(session)
    task = own_task(session["task_id"])
    if not task or task["status"] == "completed" or task["stage"] != ("Монтаж" if user["role"] == "installer" else "Замер"):
        db.execute("DELETE FROM telegram_sessions WHERE telegram_id=?", (telegram_id,))
        reply("Задание недоступно или стадия изменилась. Откройте /tasks.")
        return {"ok": True}
    if datetime.fromisoformat(session["updated_at"]) < datetime.now(timezone.utc) - timedelta(hours=24):
        db.execute("DELETE FROM telegram_sessions WHERE telegram_id=?", (telegram_id,))
        reply("Диалог истёк. Начните заново через /tasks.")
        return {"ok": True}
    payload = json.loads(session["payload"])
    action, step, nonce = session["action"], session["step"], session["nonce"]

    def advance(next_step):
        db.execute("UPDATE telegram_sessions SET step=?,payload=?,updated_at=? WHERE telegram_id=?",
                   (next_step, json.dumps(payload, ensure_ascii=False), now(), telegram_id))

    if callback and data not in (f"check:{nonce}", f"skip:{nonce}", f"confirm:{nonce}"):
        reply("Эта кнопка устарела. Продолжите текущий диалог или /cancel.")
        return {"ok": True}
    if step == "confirm":
        if data != f"confirm:{nonce}":
            reply("Нажмите «Подтвердить» в последнем сообщении или /cancel.")
            return {"ok": True}
        if action == "problem":
            db.execute("""UPDATE orders SET problem_type=?,problem_comment=?,problem_help_needed=?,problem_status='open',
                          next_action=?,next_action_due=? WHERE id=?""",
                       (payload["type"], payload["comment"], payload["help"], payload["help"], task["due_date"], task["order_id"]))
            db.execute("UPDATE tasks SET status='problem',comment=?,updated_at=? WHERE id=?", (payload["comment"], now(), task["id"]))
            history(task, "problem", f"Сообщил о проблеме: {payload['type']}. {payload['comment']}. Нужна помощь: {payload['help']}", payload)
            queued = notify(task, f"Проблема: {payload['type']}\n{payload['comment']}\nНужна помощь: {payload['help']}\nСледующее действие: {payload['help']}")
            reply("Проблема сохранена. " + ("Уведомление координатору поставлено в очередь." if queued else
                  "Координатор не подключён, уведомление не отправлено. Сообщите администратору.") + " /tasks")
        elif action == "transfer":
            db.execute("UPDATE tasks SET status='transfer_requested',proposed_date=?,transfer_reason=?,updated_at=? WHERE id=?",
                       (payload["date"], payload["reason"], now(), task["id"]))
            db.execute("UPDATE orders SET next_action=? WHERE id=?", ("Рассмотреть запрос переноса на " + payload["date"], task["order_id"]))
            history(task, "transfer_requested", f"Запрос переноса на {payload['date']}: {payload['reason']}. Обещанный срок и прогноз не изменены.", payload)
            notify(task, f"Запрос переноса: {payload['date']}\nПричина: {payload['reason']}\nСледующее действие: согласовать или отклонить запрос. Клиентский срок не изменён.")
            reply("Запрос сохранён. Обещанный срок и прогноз не изменены. /tasks")
        else:
            next_stage = "Приёмка" if user["role"] == "installer" else "Проектирование"
            db.execute("""UPDATE tasks SET status='completed',completed_at=?,checklist_result=?,comment=?,photo_file_id=?,updated_at=? WHERE id=?""",
                       (now(), json.dumps(payload["checklist"], ensure_ascii=False), payload["comment"], payload.get("photo_file_id"), now(), task["id"]))
            db.execute("UPDATE orders SET stage=?,next_action=?,stage_executor=coordinator WHERE id=?",
                       (next_stage, "Согласовать акт приёмки" if next_stage == "Приёмка" else "Назначить проектировщика", task["order_id"]))
            history(task, "completed", f"Задание выполнено. {payload['comment']}. Заказ переведён в «{next_stage}»; весь заказ не закрыт.",
                    {"checklist": payload["checklist"], "photo_attached": bool(payload.get("photo_file_id"))})
            reply(f"Задание выполнено. Стадия заказа: «{next_stage}». Заказ ещё не завершён. /tasks")
        db.execute("DELETE FROM telegram_sessions WHERE telegram_id=?", (telegram_id,))
        return {"ok": True}
    if step == "checklist":
        if data != f"check:{nonce}":
            reply("Проверьте checklist и нажмите кнопку подтверждения. /cancel — отмена.")
        else:
            payload["checklist"] = CHECKLISTS[user["role"]]
            advance("comment")
            reply("Добавьте короткий комментарий о выполнении и замечаниях.")
        return {"ok": True}
    if step == "photo":
        photos = message.get("photo") if not callback else None
        if photos:
            payload["photo_file_id"] = photos[-1]["file_id"]
        elif data != f"skip:{nonce}":
            reply("Пришлите фотографию либо нажмите «Без фотографии».", buttons([[("Без фотографии", f"skip:{nonce}")]]))
            return {"ok": True}
        advance("confirm")
        reply(f"Сдать задание {task['order_number']}?\n{payload['comment']}\nФото: {'да' if payload.get('photo_file_id') else 'нет'}",
              buttons([[("Подтвердить", f"confirm:{nonce}")]]))
        return {"ok": True}
    if callback or not text or len(text) > 700 or text.startswith("/"):
        reply("Введите текст от 1 до 700 символов. Для отмены: /cancel.")
        return {"ok": True}
    if action == "problem":
        payload[step] = text
        if step == "type":
            advance("comment")
            reply("Коротко опишите, что произошло.")
        elif step == "comment":
            advance("help")
            reply("Какая помощь нужна? Укажите следующее требуемое действие.")
        else:
            advance("confirm")
            reply(f"{task['order_number']}\nТип: {payload['type']}\n{payload['comment']}\nПомощь: {payload['help']}",
                  buttons([[("Подтвердить", f"confirm:{nonce}")]]))
    elif action == "transfer":
        if step == "date":
            try:
                iso_date(text)
            except ValueError:
                reply("Некорректная дата. Используйте ГГГГ-ММ-ДД, например 2026-10-05.")
                return {"ok": True}
            payload["date"] = text
            advance("reason")
            reply("Укажите причину переноса.")
        else:
            payload["reason"] = text
            advance("confirm")
            reply(f"Запрос переноса на {payload['date']}\nПричина: {text}\nОбещанный срок и прогноз не изменятся.",
                  buttons([[("Подтвердить", f"confirm:{nonce}")]]))
    else:
        payload["comment"] = text
        advance("photo")
        reply("Пришлите фотографию, если нужна, или пропустите этот шаг.", buttons([[("Без фотографии", f"skip:{nonce}")]]))
    return {"ok": True}


async def drain_outbox(path, api):
    """Claim before send. Ambiguous delivery is never retried automatically (Telegram has no idempotency key)."""
    while True:
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM telegram_outbox WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                return
            row = dict(row)
            db.execute("UPDATE telegram_outbox SET status='sending',updated_at=? WHERE id=?", (now(), row["id"]))
        try:
            status, error = await api.call(row["method"], json.loads(row["body"]))
        except Exception:
            # The request might already have reached Telegram; never retry it blindly.
            status, error = "uncertain", "Ошибка обработки доставки; проверьте Telegram перед повтором"
        with connect(path) as db:
            db.execute("UPDATE telegram_outbox SET status=?,error=?,updated_at=? WHERE id=?", (status, error, now(), row["id"]))
            if row["notification"]:
                comment = "Координатору отправлено уведомление" if status == "sent" else f"Доставка уведомления: {error}"
                add_history(db, row["order_id"], f"notification_{status}", comment)
        if status != "sent":
            logger.warning("Telegram outbox %s: %s", row["id"], status)


async def delivery_loop(path, api):
    while True:
        try:
            await drain_outbox(path, api)
        except Exception:
            logger.error("Outbox processing failed; pending messages remain in database")
        await asyncio.sleep(2)
