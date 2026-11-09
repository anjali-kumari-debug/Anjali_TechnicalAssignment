"""Parsing, validation and calculation of quantities and money.

This is the single place where order arithmetic happens. Order services, the CSV import
and the debugging exercise all use these helpers, so the rules are never duplicated.

Rules (assignment Part 5):
    Item Amount     = Quantity x Rate
    Subtotal        = sum of Item Amounts
    Discount Amount = Subtotal x Discount Percentage / 100
    Grand Total     = Subtotal - Discount Amount
Money is rounded to 2 decimal places with ROUND_HALF_UP (0.005 -> 0.01).
"""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
MAX_DISCOUNT = Decimal("20")
MAX_MONEY = Decimal("9999999999.99")  # fits DECIMAL(12,2)
MAX_QUANTITY = 1_000_000_000  # per line / per adjustment
MAX_STOCK = 2_147_483_647  # MySQL INT maximum
_INTEGER_TEXT = re.compile(r"^-?[0-9]+$")


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_quantity(value, field="quantity", allow_zero=False) -> int:
    """Return a whole-number quantity or raise ValueError.

    Accepts an int, or a string of digits (HTML forms and CSV send strings).
    Rejects: bool (True is an int in Python!), floats like 2.5, '2.0', negatives, zero.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be a whole number.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and _INTEGER_TEXT.match(value.strip()):
        number = int(value.strip())
    else:
        raise ValueError(f"{field} must be a whole number.")
    if allow_zero and number < 0:
        raise ValueError(f"{field} cannot be negative.")
    if not allow_zero and number <= 0:
        raise ValueError(f"{field} must be greater than zero.")
    if number > MAX_QUANTITY:
        raise ValueError(f"{field} is too large.")
    return number


def parse_money(value, field="price") -> Decimal:
    """Return a non-negative Decimal with at most 2 decimal places, or raise ValueError.

    Accepts int, str, or float. Floats go through str() so 0.1 becomes Decimal('0.1')
    rather than 0.1000000000000000055511151231257827...
    """
    if isinstance(value, bool) or value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{field} is required and must be a number.")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a number.") from None
    if not amount.is_finite():
        raise ValueError(f"{field} must be a number.")
    if amount < 0:
        raise ValueError(f"{field} cannot be negative.")
    if amount > MAX_MONEY:
        raise ValueError(f"{field} is too large.")
    if amount != amount.quantize(CENT, rounding=ROUND_HALF_UP):
        raise ValueError(f"{field} can have at most 2 decimal places.")
    return amount.quantize(CENT)


def parse_discount(value) -> Decimal:
    """Discount percentage: 0 to 20 inclusive, max 2 decimal places. Missing/blank means 0."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal("0.00")
    percent = parse_money(value, field="discount_percentage")
    if percent > MAX_DISCOUNT:
        raise ValueError("discount_percentage must be between 0 and 20.")
    return percent


def fits_money_column(value: Decimal) -> bool:
    """True if the value fits DECIMAL(12,2). Larger values would be rejected by MySQL."""
    return value <= MAX_MONEY


def line_amount(quantity: int, rate: Decimal) -> Decimal:
    return round_money(Decimal(quantity) * rate)


def order_totals(line_amounts, discount_percentage: Decimal):
    """Return (subtotal, discount_amount, grand_total) for a list of line amounts."""
    subtotal = round_money(sum(line_amounts, Decimal("0")))
    discount_amount = round_money(subtotal * discount_percentage / Decimal("100"))
    grand_total = subtotal - discount_amount
    return subtotal, discount_amount, grand_total
