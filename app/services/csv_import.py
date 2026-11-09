"""All-or-nothing product import from CSV (assignment Part 10).

Format:
    product_code,product_name,category,price,stock_quantity,status
    PRD-001,Keyboard,Accessories,1500,20,Active

Two phases:
  1. Read and validate the WHOLE file without writing anything: header, every field of
     every row, duplicate codes inside the file, and codes that already exist in the
     database (one query). Every problem is collected with its row number.
  2. Only if there are no problems at all: insert every product, plus an OPENING_STOCK
     movement for each product with stock > 0, in ONE transaction.
Row numbers match the spreadsheet: the header is row 1, the first product is row 2.
"""
import csv
import io

from sqlalchemy.exc import IntegrityError

from ..errors import ValidationError
from ..extensions import db
from ..models import MOVE_OPENING, Product
from .catalog import PRODUCT_CODE_RE, normalize_code
from .money import parse_money, parse_quantity
from .stock import record_movement
from .transaction import unit_of_work

COLUMNS = ["product_code", "product_name", "category", "price", "stock_quantity", "status"]
STATUSES = {"active": True, "inactive": False}
MAX_ROWS = 5000


def _error(row, field, message):
    return {"row": row, "field": field, "message": message}


def _read_text(file_storage):
    raw = file_storage.read()
    if not raw:
        raise ValidationError("The file is empty.", [_error(1, "file", "The file is empty.")])
    try:
        # utf-8-sig also accepts files saved by Excel, which start with a byte-order mark.
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError("The file is not UTF-8 text.", [
            _error(1, "file", "Could not read the file. Save it as 'CSV UTF-8 (Comma delimited)' and try again.")
        ]) from None


def _check_header(header):
    names = [name.strip().lower() for name in header]
    errors = []
    missing = [c for c in COLUMNS if c not in names]
    unexpected = [n for n in names if n not in COLUMNS]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if missing:
        errors.append(_error(1, "header", f"Missing column(s): {', '.join(missing)}."))
    if unexpected:
        errors.append(_error(1, "header", f"Unexpected column(s): {', '.join(n or '(blank)' for n in unexpected)}."))
    if duplicated:
        errors.append(_error(1, "header", f"Duplicated column(s): {', '.join(duplicated)}."))
    return names, errors


def _validate_row(row_number, values):
    """Return (clean_dict, errors) for one data row."""
    errors = []
    code = normalize_code(values["product_code"])
    if not code:
        errors.append(_error(row_number, "product_code", "Product code is required."))
    elif not PRODUCT_CODE_RE.match(code):
        errors.append(_error(row_number, "product_code",
                             f"'{values['product_code']}' is not a valid code (letters, digits, '-' or '_', max 50)."))

    name = values["product_name"].strip()
    if not name:
        errors.append(_error(row_number, "product_name", "Product name is required."))
    elif len(name) > 150:
        errors.append(_error(row_number, "product_name", "Product name must be 150 characters or fewer."))

    category = values["category"].strip()
    if not category:
        errors.append(_error(row_number, "category", "Category is required."))
    elif len(category) > 100:
        errors.append(_error(row_number, "category", "Category must be 100 characters or fewer."))

    price = None
    try:
        price = parse_money(values["price"], field="price")
    except ValueError as exc:
        errors.append(_error(row_number, "price", f"{exc} (got '{values['price']}')"))

    stock = None
    try:
        stock = parse_quantity(values["stock_quantity"], field="stock_quantity", allow_zero=True)
    except ValueError as exc:
        errors.append(_error(row_number, "stock_quantity", f"{exc} (got '{values['stock_quantity']}')"))

    status = values["status"].strip().lower()
    if status not in STATUSES:
        errors.append(_error(row_number, "status", f"Status must be Active or Inactive (got '{values['status']}')."))

    clean = {"product_code": code, "name": name, "category": category, "price": price,
             "stock_quantity": stock, "is_active": STATUSES.get(status)}
    return clean, errors


def parse_and_validate(file_storage):
    """Phase 1. Returns (rows, errors). Writes nothing."""
    reader = csv.reader(io.StringIO(_read_text(file_storage), newline=""))
    header = next(reader, None)
    if not header or not any(cell.strip() for cell in header):
        return [], [_error(1, "header", f"The first row must be the header: {','.join(COLUMNS)}")]
    names, errors = _check_header(header)
    if errors:
        return [], errors  # rows cannot be interpreted without a valid header

    rows, first_row_for_code = [], {}
    for row_number, cells in enumerate(reader, start=2):
        if not any(cell.strip() for cell in cells):
            continue  # ignore blank lines
        if len(rows) >= MAX_ROWS:
            errors.append(_error(row_number, "file", f"Too many rows (maximum {MAX_ROWS})."))
            break
        if len(cells) != len(COLUMNS):
            errors.append(_error(row_number, "row", f"Expected {len(COLUMNS)} values but found {len(cells)}."))
            continue
        clean, row_errors = _validate_row(row_number, dict(zip(names, cells)))
        errors.extend(row_errors)
        code = clean["product_code"]
        if code and code in first_row_for_code:
            errors.append(_error(row_number, "product_code",
                                 f"Duplicate product code {code} (already used in row {first_row_for_code[code]})."))
        elif code and PRODUCT_CODE_RE.match(code):
            first_row_for_code[code] = row_number
        rows.append((row_number, clean))

    if not rows and not errors:
        errors.append(_error(2, "file", "The file has a header but no product rows."))

    codes = list(first_row_for_code)
    if codes:
        existing = set(db.session.execute(
            db.select(Product.product_code).where(Product.product_code.in_(codes))).scalars())
        for code in sorted(c.upper() for c in existing):
            if code in first_row_for_code:
                errors.append(_error(first_row_for_code[code], "product_code", f"Product code {code} already exists."))

    errors.sort(key=lambda e: e["row"])
    return rows, errors


def import_products(file_storage, user):
    """Validate, then import everything or nothing. Returns the number of products created."""
    filename = (file_storage.filename or "upload.csv")[:100]
    rows, errors = parse_and_validate(file_storage)
    if errors:
        raise ValidationError(f"Nothing was imported: {len(errors)} problem(s) found.", errors)
    try:
        with unit_of_work():
            for _, clean in rows:
                product = Product(**clean)
                db.session.add(product)
                db.session.flush()
                if product.stock_quantity > 0:
                    record_movement(product, MOVE_OPENING, product.stock_quantity, f"CSV import: {filename}", user)
    except IntegrityError:
        # A code was created by someone else between validation and insert.
        raise ValidationError("Nothing was imported: a product code was added by another user during the import. "
                              "Please upload the file again.") from None
    return len(rows)
