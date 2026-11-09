"""Part 11: the corrected calculate_total()."""
from decimal import Decimal

import pytest

from debugging.calculate_total import calculate_total


def original_calculate_total(items):  # the buggy version, kept to show the difference
    total = 0
    for item in items:
        amount = item["qty"] * item["rate"]
        total = amount
    return total


EXAMPLE = [{"qty": 2, "rate": 100}, {"qty": 3, "rate": 50}]


def test_original_returns_only_last_item():
    assert original_calculate_total(EXAMPLE) == 150


def test_corrected_example_returns_350():
    assert calculate_total(EXAMPLE) == Decimal("350.00")


def test_empty_list_returns_zero():
    assert calculate_total([]) == Decimal("0.00")


def test_decimal_rates():
    assert calculate_total([{"qty": 3, "rate": "0.10"}, {"qty": 1, "rate": 0.2}]) == Decimal("0.50")


def test_zero_rate_is_allowed():
    assert calculate_total([{"qty": 1, "rate": 0}]) == Decimal("0.00")


@pytest.mark.parametrize("item, missing", [({"rate": 10}, "qty"), ({"qty": 1}, "rate"), ({}, "qty")])
def test_missing_key_raises_clear_error(item, missing):
    with pytest.raises(ValueError, match=f"item 1: missing '{missing}'"):
        calculate_total([item])


@pytest.mark.parametrize("qty", [0, -1, 2.5, "2.0", None, "two", True, False])
def test_invalid_quantity_rejected(qty):
    with pytest.raises(ValueError, match="item 1"):
        calculate_total([{"qty": qty, "rate": 10}])


@pytest.mark.parametrize("rate", [-1, "-0.01", "NaN", "Infinity", "abc", None, True, "1.001"])
def test_invalid_rate_rejected(rate):
    with pytest.raises(ValueError, match="item 1"):
        calculate_total([{"qty": 1, "rate": rate}])


def test_error_names_the_bad_item_position():
    with pytest.raises(ValueError, match="item 2"):
        calculate_total([{"qty": 1, "rate": 10}, {"qty": -5, "rate": 10}])


def test_non_list_input_rejected():
    with pytest.raises(TypeError):
        calculate_total(None)
