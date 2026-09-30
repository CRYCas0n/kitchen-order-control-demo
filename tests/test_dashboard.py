import unittest

from app.calculations import enrich, summarize_orders
from app.config import COST_FIELDS


def sample(order_id, revenue=100, materials=20, **changes):
    order = dict(id=order_id, order_number=f"DEMO-{order_id}", client_alias="Тест",
                 coordinator="Координатор", stage_executor="Исполнитель", stage="Монтаж",
                 next_action="Проверить", next_action_due="2026-10-01", promised_date_initial="2026-10-01",
                 forecast_date="2026-10-01", completed_date=None, problem_status="none")
    order.update(changes)
    costs = {f"{field}_{kind}": 0 for kind in ("plan", "actual") for field in COST_FIELDS}
    costs.update(revenue_actual=revenue, materials_actual=materials)
    return enrich(order, costs)


class DashboardTests(unittest.TestCase):
    def test_finance_uses_complete_actuals_and_arithmetic_average(self):
        orders = [sample(1), sample(2, materials=90), sample(3, materials=120),
                  sample(4, materials=None), sample(5, revenue=0, materials=0), sample(6, revenue=0, materials=10)]
        summary = summarize_orders(orders)
        self.assertEqual(summary["finance"], {
            "revenue_actual": 300, "margin_income": 60, "average_margin_percent": 23.33,
            "complete_count": 5, "average_count": 3, "loss_count": 2})
        self.assertEqual(summary["margins"], {"normal": 1, "low": 1, "negative": 2, "incomplete": 1, "not_calculable": 1})
        self.assertEqual(sum(summary["margins"].values()), 6)
        self.assertEqual(summary["kpis"]["low_margin"], 3)
        self.assertEqual(summary["kpis"]["incomplete"], 1)

    def test_unknown_finance_is_not_zero_and_empty_average_is_null(self):
        for orders in ([], [sample(1, materials=None)]):
            with self.subTest(orders=len(orders)):
                finance = summarize_orders(orders)["finance"]
                self.assertIsNone(finance["revenue_actual"])
                self.assertIsNone(finance["margin_income"])
                self.assertIsNone(finance["average_margin_percent"])
        zero = summarize_orders([sample(1, revenue=0, materials=0)])["finance"]
        self.assertEqual(zero["revenue_actual"], 0)
        self.assertEqual(zero["margin_income"], 0)
        self.assertIsNone(zero["average_margin_percent"])

    def test_deadline_partition_and_overlapping_kpis(self):
        orders = [sample(1), sample(2, forecast_date="2026-10-03"),
                  sample(3, promised_date_initial="2026-09-29", forecast_date="2026-10-03"),
                  sample(4, stage="Завершён", promised_date_initial="2026-09-28", completed_date="2026-09-27"),
                  sample(5, stage="Завершён", promised_date_initial="2026-09-28", completed_date="2026-09-30")]
        summary = summarize_orders(orders)
        self.assertEqual(summary["deadlines"], {"on_time": 2, "risk": 1, "overdue": 1, "completed_late": 1})
        self.assertEqual(summary["kpis"]["delay_risk"], 2)
        self.assertEqual(summary["kpis"]["overdue"], 1)
        self.assertEqual(summary["kpis"]["active"], 3)
        self.assertEqual(sum(s["count"] for s in summary["stages"]), 5)
        self.assertEqual(len(summary["stages"]), 10)
        for key, count in summary["kpis"].items():
            self.assertEqual(count, len([o for o in orders if o[key]]))

    def test_top_five_puts_overdue_open_problems_first(self):
        orders = [sample(1, problem_status="open", next_action_due="2026-10-01"),
                  sample(2, promised_date_initial="2026-09-28", next_action_due="2026-10-02"),
                  sample(3, promised_date_initial="2026-09-29", problem_status="open", next_action_due="2026-10-08"),
                  sample(4, materials=None), sample(5, materials=95),
                  sample(6, forecast_date="2026-10-04"), sample(7)]
        summary = summarize_orders(orders)
        self.assertEqual(summary["attention_ids"], [3, 1, 2, 4, 5])
        self.assertEqual(summary["attention_total"], 6)
        self.assertEqual(summarize_orders(list(reversed(orders)))["attention_ids"], [3, 1, 2, 4, 5])

    def test_bad_row_is_excluded_and_reported(self):
        summary = summarize_orders([sample(1), sample(2, forecast_date="bad-date")])
        self.assertEqual(summary["invalid_count"], 1)
        self.assertEqual(sum(summary["deadlines"].values()), 1)
        self.assertEqual(summary["finance"]["revenue_actual"], 100)
        self.assertEqual(summary["margins"]["incomplete"], 1)


if __name__ == "__main__":
    unittest.main()
