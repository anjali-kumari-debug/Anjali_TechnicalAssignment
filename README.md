# Sales Order & Inventory Management

**Savyant Systems · Fresher / Trainee Software Developer technical assignment**
**Candidate:** Anjali Kumari

This web app lets a small trading company manage its customers, products, sales orders and
stock. Users can:
- maintain master data
- create multi-item orders with discounts
- confirm or cancel orders, with stock updated safely under concurrency
- import products from CSV
- review sales and stock reports

| | |
|---|---|
| Backend | Python 3.11+ (developed on 3.13), Flask 3.1, SQLAlchemy 2.0, Flask-Login, Flask-WTF (CSRF) |
| Database | MySQL 8.0.16+ (developed on MySQL 9.6). CHECK constraints need 8.0.16 or later |
| Frontend | Server-rendered HTML (Jinja2), plain CSS, vanilla JavaScript (`fetch()`) |
| Tests | pytest, run against a real MySQL test database |

Contents:

1. [Setup](#1-setup)
2. [Sample accounts](#2-sample-accounts)
3. [Running the tests](#3-running-the-tests)
4. [Project structure](#4-project-structure)
5. [Roles and permissions](#5-roles-and-permissions)
6. [Database design](#6-database-design)
7. [Order calculations](#7-order-calculations)
8. [Order status and stock: the concurrency approach](#8-order-status-and-stock-the-concurrency-approach)
9. [CSV import](#9-csv-import)
10. [Reports and SQL](#10-reports-and-sql)
11. [REST API](#11-rest-api)
12. [Assumptions](#12-assumptions)
13. [Known limitations and incomplete items](#13-known-limitations-and-incomplete-items)
14. [Git workflow](#14-git-workflow)
15. [Demo walkthrough](#15-demo-walkthrough)

Other documents:
- [docs/API.md](docs/API.md): API reference with request/response examples
- [docs/DECISIONS.md](docs/DECISIONS.md): design decisions and the research behind them
- [sql/queries.sql](sql/queries.sql): the five SQL queries
- [debugging/EXPLANATION.md](debugging/EXPLANATION.md): Part 11 debugging exercise
- [AI_USAGE.md](AI_USAGE.md): AI usage disclosure

---

## 1. Setup

### Prerequisites

- Python 3.11 or newer (`python3 --version`)
- MySQL 8.0.16 or newer, running locally. On macOS with Homebrew:
  `brew install mysql && brew services start mysql`
- git

### Steps

```bash
# 1. Get the code
git clone <repository-url> Anjali_TechnicalAssignment
cd Anjali_TechnicalAssignment

# 2. Create the databases and an application user (once). Use your own password.
mysql -u root -p <<'SQL'
CREATE DATABASE savyant_db   CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE savyant_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'savyant_app'@'localhost' IDENTIFIED BY 'choose-a-password';
GRANT ALL PRIVILEGES ON savyant_db.*   TO 'savyant_app'@'localhost';
GRANT ALL PRIVILEGES ON savyant_test.* TO 'savyant_app'@'localhost';
SQL

# 3. Python environment
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 4. Configuration
cp .env.example .env
#    Edit .env:
#    - put your MySQL password in DATABASE_URL and TEST_DATABASE_URL
#    - set SECRET_KEY to a random value:  python -c "import secrets; print(secrets.token_hex(32))"
#    - optionally change SEED_ADMIN_PASSWORD / SEED_SALES_PASSWORD

# 5. Create the tables and the sample data
flask init-db          # runs db/schema.sql (asks before dropping existing tables)
flask seed             # sample users, customers, products and orders

# 6. Run
flask run              # open http://127.0.0.1:5001
```

You can also load the schema without Flask:
`mysql -u savyant_app -p savyant_db < db/schema.sql`.

**Dependencies.** All dependencies are pinned in [requirements.txt](requirements.txt).
- `PyMySQL[rsa]` pulls in `cryptography`. MySQL 8.4+/9.x accounts use
  `caching_sha2_password`, and PyMySQL needs it for that login method.
- SQLAlchemy is pinned to the 2.0 series. Flask-SQLAlchemy 3.1 has not been released for 2.1.

## 2. Sample accounts

`flask seed` creates these accounts. **Their passwords come from your `.env`**
(`SEED_ADMIN_PASSWORD`, `SEED_SALES_PASSWORD`), so no real credentials are in the
repository. `.env.example` contains demo values for local use only.

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@example.com` | value of `SEED_ADMIN_PASSWORD` (demo: `Admin@12345`) |
| Sales User | `ravi@example.com` | value of `SEED_SALES_PASSWORD` (demo: `Sales@12345`) |
| Sales User | `meera@example.com` | value of `SEED_SALES_PASSWORD` |

To create more accounts, run `flask create-user`. It prompts for the name, email, role and
password.

The seed data includes:
- the worked example from the assignment (2 × Keyboard @ 1,500 + 3 × Mouse @ 500, 10% off = **₹4,050.00**)
- a Draft order
- a Cancelled order
- confirmed orders in earlier months
- an inactive customer and an inactive product

## 3. Running the tests

The tests need the `savyant_test` database from step 2 and `TEST_DATABASE_URL` in `.env`.
The suite recreates the tables itself, and refuses to run if the URL does not contain "test".

```bash
source .venv/bin/activate
pytest                 # all tests (about 140, ~3 seconds)
pytest -v tests/test_concurrency.py
pytest tests/test_debug_exercise.py
```

The tests run on **MySQL, not SQLite**. The property under test is row locking
(`SELECT ... FOR UPDATE`), and SQLite silently ignores it.

| Assignment scenario (Part 12) | Test |
|---|---|
| Order with multiple items and discount → correct subtotal/grand total | `test_money.py::test_assignment_example_multi_item_with_discount`, `test_orders.py::test_create_order_calculates_totals_on_server` |
| Zero or negative quantity → rejected | `test_money.py::test_zero_negative_or_non_whole_quantity_rejected`, `test_orders.py::test_order_validation_errors` |
| Discount outside 0–20% → rejected | `test_money.py::test_discount_outside_0_to_20_rejected`, `test_orders.py::test_order_validation_errors` |
| Confirmation with sufficient stock → confirmed, stock deducted | `test_orders.py::test_confirm_with_sufficient_stock_deducts_and_records_movements` |
| Confirmation with one insufficient item → no stock or status change | `test_orders.py::test_confirm_with_one_insufficient_item_changes_nothing` |
| Repeated confirmation → no additional deduction | `test_orders.py::test_repeated_confirmation_does_not_deduct_again`, `test_concurrency.py::test_same_order_confirmed_twice_at_once_deducts_once` |
| Cancellation of a Confirmed order → stock restored once | `test_orders.py::test_cancel_confirmed_order_restores_stock_once` |
| Sales User accesses another user's order → access denied | `test_permissions.py::test_sales_user_cannot_access_another_users_order` |
| CSV containing an invalid row → no products imported | `test_csv_import.py::test_one_bad_row_among_good_rows_imports_nothing`, `test_csv_import.py::test_invalid_sample_imports_nothing_and_reports_every_row` |
| *Extra:* two users confirming for the same limited stock | `test_concurrency.py` (real threads, separate DB connections) |

## 4. Project structure

```
app/
  __init__.py          create_app(): config, extensions, blueprints, error handlers
  config.py            settings from environment variables (.env)
  models.py            ORM models (mirror db/schema.sql)
  errors.py            AppError types -> JSON (API) or HTML (pages); no tracebacks to clients
  permissions.py       admin_required, get_order_for_user (ownership + row locking)
  services/            business logic: no HTTP code in here
    money.py           quantity/money/discount parsing, line and order totals (one place)
    orders.py          create/edit Draft, confirm, cancel
    stock.py           product row locking, stock adjustments, movement records
    catalog.py         customers and products: validation, search, safe delete
    csv_import.py      two-phase all-or-nothing import
    reports.py         report SQL
    transaction.py     unit_of_work(): one commit or one rollback per operation
  routes/              thin HTTP layer
    auth.py            login / logout
    web.py             HTML pages
    api.py             JSON API
  templates/, static/  Jinja templates, CSS, JavaScript (api.js, order_form.js, order_detail.js)
  cli.py               flask init-db / seed / create-user
db/schema.sql          tables, keys, constraints, indexes
sql/queries.sql        the five standalone queries
samples/               valid and invalid CSV files
debugging/             Part 11 corrected function + explanation
tests/                 pytest suite
docs/                  API reference, design decisions
```

Code is organised in three layers:
- **Routes** only translate HTTP to function calls.
- **Services** hold the rules.
- **Models / SQL** hold the data.

The HTML pages and the JSON API call the same service functions, so every validation and
permission rule is written once.

## 5. Roles and permissions

All checks are enforced on the server.

| Action | Admin | Sales User |
|---|---|---|
| View customers / products | all (active and inactive) | **active only** |
| Create / edit / delete customers and products | yes | no (403) |
| Adjust stock, import CSV | yes | no (403) |
| Create orders | yes | yes |
| View / edit / confirm / cancel orders | **all** orders | **own** orders only |
| Reports | yes | no (403) |

How unauthorised requests are answered:
- **Another user's order.** The response is `403 Access denied`, on both the API and the
  HTML pages. Order lists are filtered in SQL (`WHERE created_by = current user`), so other
  users' orders never reach the browser.
- **Not logged in.** Pages redirect to the login page. `/api/*` returns `401` JSON, so
  `fetch()` never receives the login page as if it were data.

Other security measures:
- Passwords are hashed with salted scrypt (Werkzeug, `scrypt:131072:8:1`, OWASP-level cost).
- Every form and every `fetch()` POST/PUT carries a CSRF token.
- Session cookies are `HttpOnly` and `SameSite=Lax`.
- The login page shows the same message, after the same password-hash work, for an unknown
  email and a wrong password.
- `?next=` redirects are limited to this site.

## 6. Database design

```
users 1──* sales_orders *──1 customers
              │ 1
              *
      sales_order_items *──1 products 1──* stock_movements *──1 users
                                          *
                                          │ 0..1
                                     sales_orders
```

| Table | Purpose | Key constraints |
|---|---|---|
| `users` | Login accounts | `email` UNIQUE, `role` ENUM('Admin','Sales User'), `password_hash` (never returned by the API) |
| `customers` | Customer master | `is_active` flag; indexes on name, email, mobile, is_active |
| `products` | Product master | `product_code` UNIQUE; `price DECIMAL(12,2) CHECK >= 0`; `stock_quantity INT CHECK >= 0` |
| `sales_orders` | Order header | `order_number` UNIQUE; FK customer and creator (RESTRICT); `discount_percentage DECIMAL(5,2) CHECK 0..20`; stored subtotal, discount and grand total |
| `sales_order_items` | Order lines | FK order (CASCADE) and product (RESTRICT); `quantity CHECK > 0`; **`UNIQUE(sales_order_id, product_id)`** |
| `stock_movements` | Stock ledger | Signed `quantity_change` (CHECK ≠ 0); type OPENING_STOCK / ORDER_CONFIRM / ORDER_CANCEL / ADJUSTMENT; optional related order; mandatory reason; who and when |

Important decisions (more detail in [docs/DECISIONS.md](docs/DECISIONS.md)):

- **Money is `DECIMAL(12,2)`** in MySQL and `decimal.Decimal` in Python. Floats are never
  used for money.
- **Deletion is restricted, not cascaded.**
  - Foreign keys to customers and products are `ON DELETE RESTRICT`.
  - The app checks first and answers *"…cannot be deleted. Deactivate it instead."* The
    FK constraint is the safety net.
  - A customer is deletable only if **no order of any status** references it.
  - A product is deletable only if no order line **and no stock movement** references it.
    So a product created with opening stock > 0 can be deactivated but not deleted.
  - Orders are never deleted, only cancelled.
- **The rate is stored on each order line.**
  - `sales_order_items.rate` is copied from the product's price when the line is added.
  - Later price changes don't touch existing orders.
- **Stock is a ledger.**
  - `products.stock_quantity` changes only through code that also writes a
    `stock_movements` row: opening stock, adjustment, confirm or cancel.
  - The product edit form cannot change stock. As a result
    `stock_quantity = SUM(quantity_change)` for every product, and a test checks this.
- **Duplicate products in one order** are rejected by validation and by the
  `UNIQUE(sales_order_id, product_id)` key.
- **Product codes** are trimmed and upper-cased. MySQL's default collation compares text
  case-insensitively, so `prd-001` and `PRD-001` are the same code.
- **Order numbers** (`SO-YYYYMMDD-NNNNN`) are built from the AUTO_INCREMENT id, inside the
  same transaction as the insert. They are unique even when two users save at the same
  instant. The catch is that numbers can have gaps when a transaction rolls back.
- **Order date** is set by the server to today's date. The client cannot send it.
- **Timestamps** use `DATETIME`, not `TIMESTAMP`, which has a 2038 limit and converts by
  time zone.

## 7. Order calculations

Totals are computed **only on the server**
([app/services/money.py](app/services/money.py)). The browser shows a live preview using the
same rule.

```
Item Amount     = Quantity × Rate
Subtotal        = Σ Item Amounts
Discount Amount = round_half_up(Subtotal × Discount% / 100, 2 dp)
Grand Total     = Subtotal − Discount Amount
```

- **Rounding.** `ROUND_HALF_UP` to 2 decimal places (0.125 → 0.13). Item amounts are exact,
  because an integer times a 2-decimal rate needs no rounding. Only the discount is rounded,
  so `subtotal − discount = grand total` always holds.
- **Quantity** must be a whole number > 0. `2.5`, `"2.0"`, `0`, negatives and `true` are
  rejected. In Python `True` is an `int`, so it is checked explicitly.
- **Discount** must be 0–20 inclusive, with at most 2 decimals.
- **Size limits.** A line amount or order total that would not fit `DECIMAL(12,2)`
  (₹9,999,999,999.99) is rejected with a validation message.
- **Ignored client fields.** Rate, amount, totals, status, owner and order date sent by the
  browser are ignored.
- **JavaScript preview.** The browser computes in integer **paise** to avoid float errors
  (`0.1 + 0.2 ≠ 0.3`). It formats with `Intl.NumberFormat('en-IN')`, e.g. ₹1,23,456.50.

## 8. Order status and stock: the concurrency approach

| Current | Action | Result | Stock |
|---|---|---|---|
| Draft | Edit | Draft | no change (Drafts do **not** reserve stock) |
| Draft | Confirm | Confirmed | deduct every line |
| Draft | Cancel | Cancelled | no change |
| Confirmed | Cancel | Cancelled | restore every line once |
| Confirmed / Cancelled | Edit / Confirm | 409, read-only | no change |
| Cancelled | Cancel | 409 | no change |

### How conflicting stock updates are prevented

The app uses **pessimistic row locking inside one database transaction**
([app/services/orders.py](app/services/orders.py) `confirm_order`):

1. **Lock the order row and its items** with `SELECT … FOR UPDATE`.
   - If the same order is confirmed twice at the same moment, the second request waits here.
   - When the first commits, the second sees status `Confirmed` and gets `409`. Stock is
     deducted only once.
2. **Lock every product on the order** with `SELECT … FOR UPDATE`, **in ascending id order**.
   - Two orders that need the same limited stock are serialised. The second waits until the
     first commits, then reads the *reduced* stock.
   - Every path that touches product rows takes those locks in ascending id order:
     - confirm, cancel and stock adjustment lock them explicitly
     - saving a Draft inserts its lines in product-id order; each insert takes a shared
       foreign-key lock on its product
   - So two transactions should not end up each holding a lock the other needs, which is
     what causes deadlocks.
3. **Check every line.** If any product is short (or inactive), raise an error, which rolls
   back everything. The response lists every short product with requested and available
   quantities.
4. **Deduct stock, write one `ORDER_CONFIRM` movement per line, set the status, and commit.**
   Status, stock and movements are saved in **one transaction**, and the commit releases the
   locks.

Why not just check, then update in Python?
- Under MySQL's default `REPEATABLE READ`, a plain `SELECT` reads a snapshot. Two requests
  could both read "5 in stock", both decide "4 is fine", and both write 1. That sells 8 units
  out of 5.
- A locking read (`FOR UPDATE`) always reads the latest committed row and blocks other
  writers until commit.
- The test suite proves this with real concurrent threads ([tests/test_concurrency.py](tests/test_concurrency.py)).
  When the locks were removed in an experiment, the same test failed: both confirmations
  succeeded.

Three further details:
- **`populate_existing`.** SQLAlchemy keeps one object per row in its session. Without
  `populate_existing=True`, the locked `SELECT` would hand back the *already-loaded* object
  with the old status `Draft`, and the order would be deducted twice. The test for
  simultaneous double confirmation fails without it.
- **Database backstop.** `CHECK (stock_quantity >= 0)` means that even a bug elsewhere
  cannot store negative stock.
- **Lock waits.** Lock waits are capped at 5 s (`innodb_lock_wait_timeout`). If the
  database still reports a lock timeout or deadlock, the user gets `409 "Another user is
  updating the same stock right now. Please try again."` instead of an error page.
- **Constraint backstop.** The same applies when a database constraint catches a race the
  application check missed, e.g. a product deleted while someone adds it to an order. The
  answer is a 409, never a 500.

Stock adjustments by an Admin use the same product lock:
- the change can be positive or negative and a reason is mandatory
- a result below zero is rejected
- every adjustment writes an `ADJUSTMENT` movement

## 9. CSV import

Products → **Import CSV** (Admin only). Format:

```
product_code,product_name,category,price,stock_quantity,status
PRD-001,Keyboard,Accessories,1500,20,Active
```

The import has two phases. If **any** row is invalid, **nothing** is imported.

1. **Validate everything first, without writing anything.**
   - Exact header check: missing, unexpected or duplicate columns.
   - Every field of every row: required text, price ≥ 0 with at most 2 decimals, whole-number
     stock ≥ 0, status `Active`/`Inactive` in any case.
   - Duplicate codes **inside the file**, compared after trimming and upper-casing.
   - Codes that **already exist** in the database, checked with one query.
   - Every problem is reported with its **row number**. The header is row 1, so the first
     product is row 2, matching what a spreadsheet shows.
2. **Only if there are no errors**, insert all products in one transaction. Opening stock is
   recorded as an `OPENING_STOCK` movement with reason `CSV import: <file name>`.

Other handling:
- Files saved by Excel (with a UTF-8 byte-order mark) work.
- Blank lines are ignored.
- Files that are not UTF-8 get a clear message.
- Uploads are limited to 2 MB / 5,000 rows.

Sample files:
- [samples/products_valid.csv](samples/products_valid.csv): 5 products
- [samples/products_invalid.csv](samples/products_invalid.csv): 1 valid row and 8 problems,
  including a duplicate that differs only in case and a code that already exists in the seed
  data

## 10. Reports and SQL

Reports are Admin-only and count **Confirmed orders only**.

| Report | Notes |
|---|---|
| Customer sales summary | Order-date range, both ends inclusive. Includes customers with **zero** confirmed orders. Each order counted once. |
| Product sales summary | Quantity sold, and gross value = Σ line amounts **before** the order discount |
| Low stock | Products with stock **strictly below** the entered threshold |
| Stock movement history | Product, type, signed change, order number, reason, user, time; filter by product |

The customer summary query is written so that it neither drops nor double-counts:

```sql
FROM customers c
LEFT JOIN sales_orders so
       ON so.customer_id = c.id
      AND so.status = 'Confirmed'          -- filters in ON, not WHERE
      AND so.order_date >= :date_from
      AND so.order_date <  :date_to + 1 day
```

- **Filters in `ON`.** A `WHERE` filter on `so` would turn the `LEFT JOIN` into an inner join
  and drop customers with no orders.
- **`COUNT(so.id)`, not `COUNT(*)`.** `COUNT(*)` would count 1 for a customer with no orders.
- **No join to `sales_order_items`.** `grand_total` is already on the order, and joining
  items would repeat each order once per item.

The five standalone queries are in [sql/queries.sql](sql/queries.sql). Each is commented,
including how ties are handled for "top three". Note one case: "customers who have never
placed **any** order" counts orders of **every** status. A customer whose only order is a
Draft has still placed an order.

## 11. REST API

See [docs/API.md](docs/API.md). It covers every endpoint, the error format, status codes and
curl examples with real responses.

Summary:
- `GET /api/products`
- `GET /api/orders`
- `POST /api/orders`
- `GET` and `PUT /api/orders/{id}`
- `POST /api/orders/{id}/confirm`
- `POST /api/orders/{id}/cancel`

## 12. Assumptions

- **Scope.** One currency (INR) and one stock location. Taxes, delivery and payments are out
  of scope, as stated in the brief.
- **Order date.** The order date is the day the order is created, set by the server. It does
  not change when the Draft is edited or confirmed.
- **Rates on edited Drafts.**
  - A line keeps the rate stored when it was added.
  - A product newly added to a Draft takes the product's current price.
  - Prices are never refreshed automatically.
- **Validation when confirming.**
  - The customer and every product must **still be active**. If something was deactivated
    after the Draft was created, confirmation is refused with a clear message.
  - Prices are not re-checked.
- **Sales Users and orders.** A Sales User may confirm and cancel **their own** orders. The
  assignment says they "create and manage their own orders".
- **Another user's order** returns **403** ("Access denied"), not 404, following the
  assignment's wording. The alternative, 404 to hide that the order exists, is discussed in
  DECISIONS.md.
- **Repeated actions.** Repeated confirm/cancel requests return **409 Conflict** and change
  nothing.
- **Customer email** is required and must look like an email, but it is not unique. Two
  customers may share a company address. Only user emails are unique.
- **Mobile numbers** accept 8–20 characters: digits, an optional leading `+`, spaces and
  hyphens.

## 13. Known limitations and incomplete items

All 14 parts are implemented. Limitations I know about:

- **No automatic retry.** After a lock timeout or deadlock (rare, because of lock ordering),
  the user is asked to retry rather than the server retrying automatically.
- **Order number gaps.** Order numbers come from AUTO_INCREMENT ids, so a rolled-back create
  leaves a gap. The daily part is the creation date, and the counter does not reset each day.
- **No migrations.** `db/schema.sql` is the schema, and `flask init-db` recreates it. A
  production system would use migrations, e.g. Alembic.
- **Report scale.** The stock movement history shows the latest 500 rows. Report pages are
  not paginated.
- **No browser tests in the suite.** The JavaScript is not covered by the pytest suite.
  During development it was checked with a scripted headless-Chrome walkthrough: live totals,
  validation, dialogs, insufficient stock, the 403 page and CSV import. To check it by hand,
  follow section 15.
- **Admin features left out.** There is no password reset, user management screen or audit
  log of master-data edits. These are outside the brief.
- **Dev server only.** Run it with `flask run` (local only). For deployment, use a WSGI server
  such as gunicorn, HTTPS, and `SESSION_COOKIE_SECURE=True`.

## 14. Git workflow

- Meaningful commits, one per feature.
- The CSV import was built on the branch **`feature/csv-import`** and merged into `main` with
  `--no-ff`, so the merge is visible in the history.
- To see it: `git log --oneline --graph`.
- `.env`, virtual environments and caches are ignored (see [.gitignore](.gitignore)).

## 15. Demo walkthrough

These are the steps used for the demo video.

1. Log in as **Admin**.
   - Customers: search, filter inactive, edit; try to delete a customer with orders (refused).
   - Products: create one with opening stock, then adjust stock with a reason.
   - Products: try to delete a product with history (refused).
2. Log in as **Ravi (Sales User)**.
   - New order: pick a customer and add Keyboard ×2 and Mouse ×3 to see the live totals.
   - Set a 10% discount: the grand total shows ₹4,050.00.
   - Try a duplicate row, quantity 0 and discount 25: clear messages appear.
   - Save, edit the Draft, then confirm (a dialog asks first, and the button is disabled while
     sending). Stock goes down.
   - Create an order for 30 USB-C Hubs (stock 3) and confirm: it is refused with
     "Only 3 in stock" and nothing changes.
   - Cancel a confirmed order: stock is restored once. Cancel again: refused.
   - Change the URL to another user's order (`/orders/3`): **403**.
3. Log in as **Admin**.
   - Reports: customer summary by date range (customers with no orders show 0), product
     summary, low stock, movement history.
   - Import `samples/products_invalid.csv`: a row-numbered error table appears and nothing is
     imported.
   - Import `samples/products_valid.csv`: 5 products are added.
4. Run `pytest` to show the test suite.
