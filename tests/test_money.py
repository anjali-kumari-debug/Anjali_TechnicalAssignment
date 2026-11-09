"""Order arithmetic and input validation (assignment Part 5, Part 12)."""
from decimal import Decimal

import pytest

from app.services.money import line_amount, order_totals, parse_discount, parse_money, parse_quantity


def test_assignment_example_multi_item_with_discount():
    # Keyboard 2 x 1500 + Mouse 3 x 500, 10% discount
    amounts = [line_amount(2, Decimal("1500.00")), line_amount(3, Decimal("500.00"))]
    subtotal, discount, grand = order_totals(amounts, Decimal("10"))
    assert amounts == [Decimal("3000.00"), Decimal("1500.00")]
    assert (subtotal, discount, grand) == (Decimal("4500.00"), Decimal("450.00"), Decimal("4050.00"))


def test_discount_rounds_half_up_and_totals_reconcile():
    subtotal, discount, grand = order_totals([Decimal("100.05")], Decimal("12.5"))  # 12.50625
    assert discount == Decimal("12.51")
    assert subtotal - discount == grand == Decimal("87.54")


def test_exact_half_paisa_rounds_up():
    # 2.50 x 5% = 0.125 -> 0.13 with ROUND_HALF_UP (banker's rounding would give 0.12)
    assert order_totals([Decimal("2.50")], Decimal("5"))[1] == Decimal("0.13")


@pytest.mark.parametrize("bad", [0, -1, "-3", 2.5, "2.0", "abc", "", None, True, False, "1e3"])
def test_zero_negative_or_non_whole_quantity_rejected(bad):
    with pytest.raises(ValueError):
        parse_quantity(bad)


@pytest.mark.parametrize("good, expected", [(1, 1), ("7", 7), (" 12 ", 12)])
def test_valid_quantities(good, expected):
    assert parse_quantity(good) == expected


@pytest.mark.parametrize("bad", ["-0.01", "20.01", "25", "NaN", "Infinity", "abc", "1.005", True, "1e400"])
def test_discount_outside_0_to_20_rejected(bad):
    with pytest.raises(ValueError):
        parse_discount(bad)


@pytest.mark.parametrize("good, expected", [("0", "0.00"), (0, "0.00"), ("20", "20.00"), ("12.5", "12.50"),
                                            (None, "0.00"), ("", "0.00")])
def test_discount_boundaries_accepted(good, expected):
    assert parse_discount(good) == Decimal(expected)


def test_money_from_float_is_exact():
    assert parse_money(0.1) == Decimal("0.10")
    with pytest.raises(ValueError):
        parse_money("-1")
