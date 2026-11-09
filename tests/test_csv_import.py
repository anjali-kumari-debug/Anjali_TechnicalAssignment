"""All-or-nothing CSV product import (Part 10, Part 12)."""
import io
from pathlib import Path

import pytest

from app.extensions import db
from app.models import Product, StockMovement

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
HEADER = "product_code,product_name,category,price,stock_quantity,status\n"


def upload(client, content, name="products.csv"):
    if isinstance(content, str):
        content = content.encode("utf-8")
    return client.post("/products/import", data={"file": (io.BytesIO(content), name)},
                       content_type="multipart/form-data")


@pytest.fixture
def admin(make, client_for):
    return client_for(make.admin())


def test_valid_sample_imports_products_and_opening_stock(make, admin):
    response = upload(admin, (SAMPLES / "products_valid.csv").read_bytes(), "products_valid.csv")
    assert response.status_code == 302
    assert make.count(Product) == 5
    movements = make.run(lambda: db.session.execute(
        db.select(StockMovement.movement_type, StockMovement.quantity_change, StockMovement.reason)).all())
    assert len(movements) == 4  # PRD-104 has 0 stock -> no movement
    assert all(m.movement_type == "OPENING_STOCK" and m.reason == "CSV import: products_valid.csv" for m in movements)
    status = make.run(lambda: db.session.execute(
        db.select(Product.is_active).where(Product.product_code == "PRD-105")).scalar())
    assert status is False


def test_invalid_sample_imports_nothing_and_reports_every_row(make, admin):
    make.product(code="PRD-001")  # makes the last row a database duplicate
    before = make.count(Product)
    response = upload(admin, (SAMPLES / "products_invalid.csv").read_bytes())
    page = response.get_data(as_text=True)
    assert response.status_code == 400
    assert make.count(Product) == before          # row 2 was valid but was NOT imported
    for row, text in [(3, "Product name is required"), (4, "cannot be negative"), (5, "whole number"),
                      (6, "Active or Inactive"), (7, "already used in row 2"), (8, "2 decimal places"),
                      (9, "whole number"), (10, "PRD-001 already exists")]:
        assert f'<td class="num">{row}</td>' in page, row
        assert text in page, text


def test_one_bad_row_among_good_rows_imports_nothing(make, admin):
    csv_text = HEADER + "A-1,Good,Cat,10,1,Active\nA-2,Good,Cat,10,1,Active\nA-3,Bad,Cat,-5,1,Active\n"
    assert upload(admin, csv_text).status_code == 400
    assert make.count(Product) == 0
    assert make.movement_count() == 0


def test_duplicate_codes_differing_only_in_case_or_spaces(make, admin):
    csv_text = HEADER + "Dup-1,One,Cat,10,1,Active\n dup-1 ,Two,Cat,10,1,Active\n"
    page = upload(admin, csv_text).get_data(as_text=True)
    assert "Duplicate product code DUP-1 (already used in row 2)" in page
    assert make.count(Product) == 0


def test_existing_code_in_database_rejected_case_insensitively(make, admin):
    make.product(code="EXIST-1")
    page = upload(admin, HEADER + "exist-1,X,Cat,10,1,Active\n").get_data(as_text=True)
    assert "EXIST-1 already exists" in page


@pytest.mark.parametrize("header, expected", [
    ("product_code,product_name,category,price,stock_quantity\n", "Missing column(s): status"),
    ("product_code,product_name,category,price,stock_quantity,status,colour\n", "Unexpected column(s): colour"),
    ("product_code,product_code,category,price,stock_quantity,status\n", "Missing column(s): product_name"),
])
def test_header_is_validated(admin, header, expected):
    page = upload(admin, header + "A-1,Name,Cat,10,1,Active\n").get_data(as_text=True)
    assert expected in page


def test_excel_bom_and_blank_lines_and_mixed_case_status(make, admin):
    content = "﻿" + HEADER.replace("status", "Status") + "B-1,Bom,Cat,10,1,active\n\n,,,,,\nB-2,Two,Cat,5,0,INACTIVE\n"
    assert upload(admin, content.encode("utf-8")).status_code == 302
    assert make.count(Product) == 2


def test_wrong_number_of_values_and_empty_files(make, admin):
    page = upload(admin, HEADER + "C-1,Short,Cat,10\n").get_data(as_text=True)
    assert "Expected 6 values but found 4" in page
    assert "The file is empty" in upload(admin, b"").get_data(as_text=True)
    assert "no product rows" in upload(admin, HEADER).get_data(as_text=True)
    assert "UTF-8" in upload(admin, "product_code\xe9".encode("latin-1")).get_data(as_text=True)
    assert make.count(Product) == 0


def test_only_admin_can_import(make, client_for):
    response = upload(client_for(make.user()), HEADER + "D-1,X,Cat,10,1,Active\n")
    assert response.status_code == 403
    assert make.count(Product) == 0
