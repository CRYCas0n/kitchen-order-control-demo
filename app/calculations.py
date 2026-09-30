from decimal import Decimal, ROUND_HALF_UP

from .config import COST_FIELDS, DEMO_DATE, LOW_MARGIN_THRESHOLD, STAGES
from .validation import iso_date, money


def economics(costs, kind="actual"):
    values = {field: costs.get(f"{field}_{kind}") for field in COST_FIELDS}
    missing = [field for field, value in values.items() if value is None]
    parsed = {field: money(value) for field, value in values.items() if value is not None}
    result = {"complete": not missing, "missing": missing, "variable_costs": None,
              "margin_income": None, "margin_percent": None, "low_margin": False, "negative_margin": False}
    if missing:
        return result
    expenses = sum((parsed[field] for field in COST_FIELDS[1:]), Decimal(0))
    margin = parsed["revenue"] - expenses
    percent = margin / parsed["revenue"] * 100 if parsed["revenue"] else None
    result.update(variable_costs=float(expenses), margin_income=float(margin),
                  margin_percent=float(percent.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if percent is not None else None,
                  low_margin=percent is not None and percent < LOW_MARGIN_THRESHOLD,
                  negative_margin=margin < 0)
    return result


def deadlines(order):
    promised = iso_date(order["promised_date_initial"])
    forecast = iso_date(order["forecast_date"])
    completed = order["stage"] == "Завершён"
    if order["stage"] not in STAGES:
        raise ValueError("Неизвестная стадия")
    if completed and not order.get("completed_date"):
        raise ValueError("Нет даты завершения")
    if not completed and order.get("completed_date"):
        raise ValueError("Дата завершения указана у активного заказа")
    late = completed and iso_date(order["completed_date"]) > promised
    overdue = not completed and promised < iso_date(DEMO_DATE)
    return {"active": not completed, "overdue": overdue, "delay_risk": not completed and forecast > promised,
            "completed_late": late,
            "deadline_label": ("Завершён с опозданием" if late else "Завершён вовремя") if completed else
                              ("Просрочен" if overdue else "В срок")}


def enrich(order, costs):
    result = dict(order)
    result["costs"] = dict(costs) if costs else {}
    try:
        for field in ("order_number", "client_alias", "coordinator", "stage_executor", "next_action"):
            if not result.get(field):
                raise ValueError(f"Не заполнено поле {field}")
        iso_date(result["next_action_due"])
        result.update(deadlines(result))
        result["economy"] = {kind: economics(result["costs"], kind) for kind in ("plan", "actual")}
        result["open_problem"] = result.get("problem_status") == "open"
        result["incomplete"] = not result["economy"]["actual"]["complete"]
        result["low_margin"] = result["economy"]["actual"]["low_margin"] or result["economy"]["actual"]["negative_margin"]
        result["data_error"] = None
    except (ValueError, KeyError, TypeError) as exc:
        result.update(data_error=f"Ошибка данных: {exc}", active=False, overdue=False, delay_risk=False,
                      open_problem=False, incomplete=True, low_margin=False, economy={})
    return result


def summarize_orders(orders):
    """Aggregate the already calculated order flags and economics; never substitute missing costs."""
    kpis = {key: sum(bool(o.get(key)) for o in orders) for key in
            ("active", "overdue", "open_problem", "delay_risk", "incomplete", "low_margin")}
    deadline_counts = dict.fromkeys(("on_time", "risk", "overdue", "completed_late"), 0)
    margin_counts = dict.fromkeys(("normal", "low", "negative", "incomplete", "not_calculable"), 0)
    complete = []
    percentages = []
    invalid_count = 0
    for order in orders:
        if order.get("data_error"):
            invalid_count += 1
            margin_counts["incomplete"] += 1
            continue
        # The chart is a partition; the KPI flags may overlap by design.
        bucket = ("completed_late" if order["completed_late"] else "overdue" if order["overdue"]
                  else "risk" if order["delay_risk"] else "on_time")
        deadline_counts[bucket] += 1
        actual = order["economy"]["actual"]
        if not actual["complete"]:
            margin_counts["incomplete"] += 1
            continue
        complete.append(order)
        if actual["margin_percent"] is not None:
            percentages.append(Decimal(str(actual["margin_percent"])))
        bucket = ("negative" if actual["negative_margin"] else "not_calculable" if actual["margin_percent"] is None
                  else "low" if actual["low_margin"] else "normal")
        margin_counts[bucket] += 1

    def total(value):
        return float(sum((Decimal(str(value(o))) for o in complete), Decimal(0))) if complete else None

    attention = [o for o in orders if any(o.get(key) for key in
                 ("overdue", "open_problem", "delay_risk", "incomplete", "low_margin", "data_error"))]
    # Only three obvious groups; earliest next action breaks ties within each group.
    attention.sort(key=lambda o: (
        0 if o.get("overdue") and o.get("open_problem") else 1 if o.get("overdue") or o.get("open_problem") else 2,
        o.get("next_action_due") or "9999-12-31", o["id"]))
    return {
        "kpis": kpis,
        "stages": [{"stage": stage, "count": sum(o["stage"] == stage for o in orders)} for stage in STAGES],
        "deadlines": deadline_counts,
        "margins": margin_counts,
        "finance": {
            "revenue_actual": total(lambda o: o["costs"]["revenue_actual"]),
            "margin_income": total(lambda o: o["economy"]["actual"]["margin_income"]),
            "average_margin_percent": float((sum(percentages) / len(percentages)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)) if percentages else None,
            "complete_count": len(complete), "average_count": len(percentages),
            "loss_count": margin_counts["negative"],
        },
        "attention_ids": [o["id"] for o in attention[:5]], "attention_total": len(attention),
        "invalid_count": invalid_count, "total_count": len(orders),
    }
