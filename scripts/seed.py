"""Repeatable demo seed. Existing data is preserved unless --reset is explicit."""
import argparse
import copy
import json
from datetime import date, timedelta
from pathlib import Path

from app.config import COST_FIELDS, ROOT, STAGES, Settings
from app.calculations import enrich, summarize_orders
from app.database import add_history, connect, dashboard, initialize

SEED_TIME = "2026-09-30T08:00:00+00:00"


def seed(path, reset=False):
    initialize(path)
    with connect(path) as db:
        if db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] and not reset:
            return False
        if reset:
            for table in ("telegram_outbox", "telegram_sessions", "history", "telegram_updates", "tasks", "costs", "orders"):
                db.execute(f"DELETE FROM {table}")
        points = [("Шоурум", "Центральный", "Саратов"), ("Шоурум", "Северный", "Саратов"),
                  ("Шоурум", "Набережная", "Энгельс"), ("Дилер", "Волга", "Самара"),
                  ("Дилер", "Контур", "Казань"), ("Дилер", "Дом", "Пенза"),
                  ("Дилер", "Линия", "Ульяновск"), ("Дилер", "Форма", "Волгоград")]
        stages = ["Монтаж", "Замер", "Монтаж", "Комплектация", "Производство", "Доставка",
                  "Проектирование", "Согласование", "Контроль качества", "Приёмка", "Завершён", "Завершён"] + STAGES[:8] + ["Производство", "Монтаж", "Доставка", "Приёмка"]
        actions = dict(zip(STAGES, ["Провести замер", "Подготовить проект", "Согласовать версию проекта", "Проверить комплектность",
                                   "Изготовить модули", "Провести контроль качества", "Доставить кухню", "Завершить монтаж",
                                   "Согласовать акт приёмки", "Заказ завершён"]))
        for i, stage in enumerate(stages, 1):
            point = points[(i-1) % len(points)]
            promised = date(2026, 9, 25) + timedelta(days=(i * 3) % 18)
            if i in (1, 4, 5):
                promised = date(2026, 9, 27)
            if i == 11:
                promised = date(2026, 9, 29)
            forecast = promised + timedelta(days=5 if i in (1, 4, 5, 6, 13) else 0)
            completed = promised + timedelta(days=2 if i == 12 else -1) if stage == "Завершён" else None
            executor = "Илья Мартынов" if stage == "Монтаж" else "Павел Лесков" if stage == "Замер" else ["Анна Миронова", "Денис Соколов", "Елена Волкова"][i % 3]
            problem = i in (4, 5)
            db.execute("""INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (i, f"КФ-{2600+i}", f"Клиент {i:02d}", *point, "Мария Орлова" if i % 2 else "Артём Белов",
                        executor, stage, promised.isoformat(), forecast.isoformat(), completed.isoformat() if completed else None,
                        "Дозаказать фасад" if problem else actions[stage], "2026-10-01" if i <= 3 else forecast.isoformat(),
                        "Комплектация" if i == 4 else "Переделка" if i == 5 else None,
                        "Отсутствует фасад шириной 600 мм" if i == 4 else "Повреждена столешница, требуется замена" if i == 5 else None,
                        "Согласовать замену и дату поставки" if problem else None, "open" if problem else "none",
                        f"v{1+i%3}.0", SEED_TIME, SEED_TIME))
            plan = [300000 + (i % 5)*20000, 120000, 30000, 10000, 15000, 15000, 10000]
            actual = list(plan)
            if i == 5:
                actual[-1] = 200000
            if i == 6:
                actual[-1] = 100000
            if i == 7:
                actual[2] = None
            if i == 8:
                actual[-1] = 0
            if i == 1:
                plan = actual = [300000, 120000, 30000, 10000, 15000, 15000, 10000]
            values = [i, *plan, *actual, SEED_TIME]
            db.execute(f"INSERT INTO costs VALUES ({','.join('?' for _ in values)})", values)
            if stage in ("Монтаж", "Замер"):
                role = "installer" if stage == "Монтаж" else "measurer"
                # Orders 1, 2, 3 are the dedicated live-demo tasks.
                code = "INSTALL-01" if role == "installer" else "MEASURE-01"
                if i > 3:
                    code = code.replace("01", "02")
                db.execute("""INSERT INTO tasks(id,order_id,role,assignee_code,status,due_date,created_at,updated_at)
                              VALUES (?,?,?,?,?,?,?,?)""", (i, i, role, code, "new", "2026-10-01", SEED_TIME, SEED_TIME))
            add_history(db, i, "seed", "Создан учебный заказ. Все имена и суммы вымышлены.")
            db.execute("UPDATE history SET created_at=? WHERE order_id=?", (SEED_TIME, i))
        return True


def export(path, destination):
    with connect(path) as db:
        data = dashboard(db)
    data["source"] = "simulation"
    data["generated_at"] = SEED_TIME
    # Precompute the one offline demonstration with the same Python aggregation as the API.
    # Browser simulation never implements its own deadline, margin or priority rules.
    changes = {"problem_type": "Комплектация", "problem_comment": "Отсутствует фасад 600 мм (имитация)",
               "problem_help_needed": "Согласовать доставку фасада", "problem_status": "open",
               "next_action": "Согласовать доставку фасада"}
    simulated = copy.deepcopy(data["orders"])
    order = next(o for o in simulated if o["id"] == 1)
    order.update(changes)
    order.update(enrich(order, order["costs"]))
    data["simulation"] = {"order_id": 1, "changes": {**changes, "open_problem": order["open_problem"]},
                          "summary": summarize_orders(simulated)}
    Path(destination).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Delete demo business data; keep allowlisted users")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    print("Seed created" if seed(settings.database_path, args.reset) else "Existing database preserved")
    if args.export:
        export(settings.database_path, ROOT / "static/demo-data.json")
        print("Offline snapshot exported")
