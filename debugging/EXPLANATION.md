# Part 11: Debugging exercise

## The bug

```python
def calculate_total(items):
    total = 0
    for item in items:
        amount = item["qty"] * item["rate"]
        total = amount      # <- overwrites
    return total
```

`total = amount` **replaces** the running total on every loop iteration instead of
adding to it, so the function returns only the **last** item's amount.

For `[{"qty": 2, "rate": 100}, {"qty": 3, "rate": 50}]`:

| iteration | amount | total after the line |
|-----------|--------|----------------------|
| 1         | 200    | 200                  |
| 2         | 150    | **150** (200 is lost) |

The function returns 150 instead of 350. The fix is to accumulate: `total += amount`.

## Corrected function

[`calculate_total.py`](calculate_total.py). It reuses the application's own validation
and rounding helpers (`app/services/money.py`), so the exercise and the order screens
follow exactly the same rules.

## Behaviour decisions

| Case | Behaviour | Why |
|------|-----------|-----|
| Empty list `[]` | Returns `Decimal('0.00')` | The total of nothing is zero; an empty order is rejected elsewhere (order validation requires at least one item), not by the arithmetic. |
| `"qty"` or `"rate"` missing | `ValueError("item 2: missing 'rate'")` | One clear error type with the item position, instead of a bare `KeyError: 'rate'`. |
| `qty` is 0, negative, `2.5`, `"2.0"`, `None`, text | `ValueError` | Quantities are whole numbers greater than zero (assignment scope). |
| `qty` is `True` / `False` | `ValueError` | `bool` is a subclass of `int` in Python, so `True * 100 == 100` would silently pass a naive `isinstance(qty, int)` check. |
| `rate` is negative, `NaN`, `Infinity`, text, `None`, or has more than 2 decimals | `ValueError` | Money must be a real, non-negative amount in rupees and paise. |
| `rate` is `0` | Allowed | A free item is legitimate. |
| `rate` given as a float, e.g. `0.1` | Converted via `str()` to `Decimal('0.1')` | `Decimal(0.1)` would be `0.1000000000000000055511151231257827...`. |
| Result type | `Decimal` with 2 decimal places (`Decimal('350.00')`) | Avoids floating-point error; `Decimal('350.00') == 350` is `True`. |

## Tests

`tests/test_debug_exercise.py` checks the original example (350), the empty list,
missing keys, and every invalid input listed above. It also shows the original
implementation returning 150. Run it with:

```bash
pytest tests/test_debug_exercise.py -v
```
