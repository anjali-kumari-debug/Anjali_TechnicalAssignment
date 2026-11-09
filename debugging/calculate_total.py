"""Part 11 - Debugging exercise: corrected calculate_total().

Original (buggy) version:

    def calculate_total(items):
        total = 0
        for item in items:
            amount = item["qty"] * item["rate"]
            total = amount          # BUG: overwrites the running total
        return total

See debugging/EXPLANATION.md for the analysis. Tests: tests/test_debug_exercise.py
"""
from decimal import Decimal

from app.services.money import line_amount, parse_money, parse_quantity


def calculate_total(items):
    """Return the sum of qty x rate for every item, as a Decimal rounded to 2 places.

    * []                       -> Decimal('0.00')
    * missing "qty" or "rate"  -> ValueError naming the item and the key
    * qty must be a whole number > 0 (bool, float like 2.5, None, text are rejected)
    * rate must be a number >= 0 with at most 2 decimals (negative, NaN, text rejected)
    """
    if not isinstance(items, (list, tuple)):
        raise TypeError("items must be a list of {'qty': ..., 'rate': ...} dictionaries")

    total = Decimal("0.00")
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"item {position}: must be a dictionary")
        for key in ("qty", "rate"):
            if key not in item:
                raise ValueError(f"item {position}: missing '{key}'")
        try:
            qty = parse_quantity(item["qty"], field="qty")
            rate = parse_money(item["rate"], field="rate")
        except ValueError as exc:
            raise ValueError(f"item {position}: {exc}") from None
        total += line_amount(qty, rate)  # FIX: accumulate instead of overwrite
    return total
