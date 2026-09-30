import re
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, field_validator


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Дата должна иметь формат ГГГГ-ММ-ДД")
    return date.fromisoformat(value)


def money(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("Укажите сумму числом")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Некорректная сумма") from exc
    if not number.is_finite() or number < 0 or number > 1_000_000_000 or number != number.quantize(Decimal("0.01")):
        raise ValueError("Сумма: от 0 до 1 000 000 000 ₽, не более двух знаков после запятой")
    return number


class ReworkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rework_actual: Decimal

    @field_validator("rework_actual", mode="before")
    @classmethod
    def validate_money(cls, value):
        return money(value)
