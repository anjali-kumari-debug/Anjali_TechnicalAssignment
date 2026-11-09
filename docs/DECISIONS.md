# Design decisions and research log

This file records why the app is built the way it is. The README has the short version.

Several items correct an earlier AI-generated analysis that I used as a starting point. Each
correction was checked against primary documentation, and where possible against this code
running on MySQL. They are marked **Corrected**.

## 1. Stack

| Decision | Reason |
|---|---|
| Flask 3 + SQLAlchemy 2.0 ORM + Flask-Login | Explicit control over transactions and row locks (`with_for_update()`); small enough to explain line by line. Django's ORM hides more; FastAPI would need extra work for server-rendered pages with cookie sessions. |
| Server-rendered Jinja pages + vanilla JS `fetch()` | The brief asks for a simple functional UI and tests DOM/fetch skills (Part 7); no build step. |
| `db/schema.sql` as the schema source of truth | Shows the SQL directly (keys, CHECKs, indexes). The ORM models mirror it, and the tests build their database from this file. |
| SQLAlchemy pinned `>=2.0.57,<2.1` | Flask-SQLAlchemy 3.1.1 has no upper bound, so a plain install would pull SQLAlchemy 2.1, which it was never released against. |
| `PyMySQL[rsa]` | MySQL 9 removed `mysql_native_password`. `caching_sha2_password` needs RSA key exchange over plain TCP, which needs `cryptography`. Without it, the first login after a server restart can fail. |

## 2. Concurrency (Part 6)

**Decision:** pessimistic locking, `SELECT … FOR UPDATE`, inside one transaction.

- **Order.** Lock the order row first, then the product rows in ascending id order.
- **Why the plain check fails.** Under InnoDB's default REPEATABLE READ, a plain SELECT
  reads a snapshot, so "check stock in Python, then UPDATE" lets two requests both pass the
  check. A locking read returns the latest committed row and blocks other writers until
  commit.
  - MySQL manual, *Locking Reads*: https://dev.mysql.com/doc/refman/9.6/en/innodb-locking-reads.html
- **Deadlocks.** Acquiring locks in a consistent order prevents the confirm-vs-confirm
  deadlock. The manual says to "do those operations in a consistent order each time"
  (*How to Minimize and Handle Deadlocks*).
- **Why lock products before writing movement rows.** Inserting a child row (a stock movement
  pointing at a product) takes a *shared* lock on the parent product. Two transactions that
  each hold a shared lock and then try to upgrade it would deadlock. Locking the products
  `FOR UPDATE` first avoids this.

**Alternative considered:** an atomic conditional `UPDATE products SET stock = stock - :q
WHERE id = :id AND stock >= :q`, then checking the row count.
- It is safe, but it reports only the first short line.
- It still needs a separate guard on the order status.
- Locking and then checking every line in Python gives a complete error message, and it is
  easier to explain.

**Corrected: `populate_existing`.**
- The earlier analysis said only "lock the order row, then re-check its status". With the
  SQLAlchemy ORM that is **not enough**.
- If the order object is already in the session (it was loaded by the ownership check), a
  locking SELECT does not overwrite its attributes. The code sees the stale `Draft` status
  and deducts twice.
- Fix: `.execution_options(populate_existing=True)` on every locking query.
- Verified: with the option removed, `test_same_order_confirmed_twice_at_once_deducts_once`
  fails, because both confirmations succeed.
- Source: SQLAlchemy `Query.with_for_update` documentation, which recommends combining it
  with `populate_existing`.

**Corrected: items must come from the locking read.**
- Lazy-loading `order.items` after taking the lock would run a *plain* SELECT. That reads
  the transaction's older snapshot and could miss an edit committed while we waited.
- The locked query loads the items in the same `SELECT … JOIN … FOR UPDATE`.

**Ownership is checked before locking.** A Sales User therefore cannot hold row locks on
someone else's order just by calling confirm on it.

**Lock wait timeout** is set to 5 s per session (the default is 50 s). MySQL errors 1205
(lock wait timeout) and 1213 (deadlock) are rolled back and returned as `409 BUSY`. There is
no automatic retry, which is a documented limitation.

## 3. Money and rounding (Parts 3, 5)

- **Types.** `DECIMAL(12,2)` in MySQL and `decimal.Decimal` in Python. Rounding is
  `ROUND_HALF_UP` to 0.01 and happens once, on the discount amount.
- **Number parsing.**
  - Input numbers go through `str()` before `Decimal()`, because `Decimal(0.1)` is not 0.1.
  - NaN and Infinity are rejected (`Decimal.is_finite()`).
  - More than 2 decimal places is rejected rather than silently rounded.
- **`bool` is an `int` in Python.** `True` passes `isinstance(x, int)`, so quantities reject
  bools explicitly.
- **JSON output.** Money is returned as decimal **strings**. Flask serialises `Decimal` with
  `str()`.
- **Dates.** Flask's default JSON date format is an RFC 1123 string, so the models call
  `.isoformat()` instead.
- **JavaScript.** The browser computes in integer paise and uses basis points for the
  discount, so its preview rounds the same way as the server.

## 4. Order numbers

**Corrected.** A format like `SO-20261109-0001`, generated by counting today's orders, races:
two concurrent creates compute the same number, and one fails on the UNIQUE index.

- **Fix:**
  1. Insert with `order_number = NULL`. The column is UNIQUE and nullable, and multiple NULLs
     are allowed.
  2. `flush()` to get the AUTO_INCREMENT id.
  3. Set `SO-<date>-<id>` in the same transaction.
- **Why it's safe.** InnoDB guarantees unique ids across concurrent inserts.
- **Trade-off:** rolled-back inserts leave gaps, which is documented.

## 5. Text comparison and product codes

**Corrected.** The earlier plan compared CSV codes with a case-sensitive Python `set`.

- MySQL's default collation `utf8mb4_0900_ai_ci` is case-insensitive, so `PRD-001` and
  `prd-001` collide on the UNIQUE index. The file would pass validation and then fail
  half-way through the insert.
- 0900 collations are also NO PAD: trailing spaces make strings different.
- **Fix:** every code is `strip().upper()`'d on the way in, in the form, the CSV and the
  duplicate checks.
- Source: MySQL manual, *Unicode Character Sets* and *Trailing Space Handling*.

## 6. Authentication, CSRF and API errors

**Corrected: CSRF was missing from the earlier analysis.**
- Session-cookie auth plus `fetch()` POST requests and a multipart upload form are all
  open to cross-site request forgery.
- **Fix:** Flask-WTF `CSRFProtect` covers every POST/PUT. The token is put in a
  `<meta name="csrf-token">` tag and sent as `X-CSRFToken` by `api.js`. Cookies are
  `SameSite=Lax` (Flask's default is unset) and `HttpOnly`.

**Corrected: 401 instead of a redirect.**
- By default, Flask-Login answers an anonymous request with a 302 to the login page. `fetch()`
  follows it and gets the login HTML with status 200, so the API would never report
  "unauthenticated".
- **Fix:** `login_manager.blueprint_login_views = {"api": None}` makes the API raise 401.
  The app-level JSON error handler renders it.

**Error handlers are app-level**, so routing errors are JSON too. Blueprint handlers do not
see 404/405 routing errors. The codes covered are 400/401/403/404/405/409/413/415/500, and
none of them return a traceback.

**Passwords** use Werkzeug scrypt with N=2^17 (`scrypt:131072:8:1`), the OWASP-recommended
cost. Werkzeug's default is N=2^15.
- Source: OWASP Password Storage Cheat Sheet.

**Another user's order: 403 or 404?**
- OWASP notes that returning 404 hides whether the record exists.
- I chose **403**, because the assignment's test wording is "Access denied" and this is an
  internal staff application. Switching is a one-line change in `get_order_for_user`.

## 7. Schema details

- **`DATETIME`, not `TIMESTAMP`.** `TIMESTAMP` ends in 2038 and is converted using the session
  time zone.
- **ENUMs.** MySQL ENUM for role, status and movement type. The SQLAlchemy `Enum` is declared
  with plain string values, not a Python `enum.Enum`. With a Python enum class, SQLAlchemy
  stores the member *names* (`CONFIRMED`) rather than the values (`Confirmed`).
- **Movement types.** Only four: OPENING_STOCK, ORDER_CONFIRM, ORDER_CANCEL, ADJUSTMENT.
  - **Corrected.** The earlier plan also had a separate CSV_IMPORT type.
  - The brief says imported stock is *opening stock*, so imports use OPENING_STOCK with the
    reason `CSV import: <file>`.
- **Customer email is not UNIQUE.** The brief requires uniqueness only for user email.
- **No ORM relationship from Customer to its orders.** With a plain relationship,
  `session.delete(customer)` would first try `UPDATE sales_orders SET customer_id = NULL`.
  The delete service checks for references and returns a friendly 409 instead.
- **Running `schema.sql` from Python.** PyMySQL runs one statement per call, so
  `flask init-db` strips comments and splits the file on `;`. The schema therefore avoids
  triggers and procedures.

## 8. Tests

- **MySQL only.** SQLAlchemy drops `FOR UPDATE` when compiling for SQLite, so concurrency
  tests on SQLite would pass without proving anything.
- **Committed test data.** Test data is committed and cleaned with `DELETE` after each test,
  child tables first. The concurrency tests need to see the data from several connections.
  `TRUNCATE` is not used: it fails on tables referenced by foreign keys, and it waits for
  metadata locks.
- **Proving the tests can fail.** The concurrency tests were run against a deliberately
  broken version (no locks, plus a small delay). Both confirmations succeeded and 8 units
  were sold from a stock of 5. The tests caught it.
- **Flask-Login context.** The test body does not keep an application context open. Flask
  reuses an active app context for test requests, and Flask-Login caches the current user in
  `g`, so two clients logged in as different users in one test would otherwise see the same
  user.
