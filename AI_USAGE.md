# AI usage disclosure

## Tools used

- **A general-purpose AI chat assistant** <!-- TODO: name the tool you used, e.g. ChatGPT / Gemini -->. Used for a first reading of the assignment: it
  produced a requirements checklist, a list of likely edge cases and a draft architecture plan.
- **Claude Code (Anthropic, Claude Opus model)** in VS Code. Used to:
  - research and verify the plan against the MySQL, SQLAlchemy, Flask and OWASP
    documentation
  - generate code, tests and documentation
  - run the test suite and a browser check

## Where AI helped

- Turning the 18-page brief into a checklist of requirements and edge cases.
- Checking framework behaviour that is easy to get wrong:
  - InnoDB locking reads under REPEATABLE READ
  - SQLAlchemy `populate_existing`
  - Flask-Login's redirect for API calls
  - MySQL collation rules
  - PyMySQL with MySQL 9 authentication
- Writing first drafts of the services, routes, templates, JavaScript, tests, README and
  API documentation.
- Writing the concurrency tests (two threads with separate database connections) and the
  headless-browser walkthrough used to check the JavaScript.

## Example prompts

1. *"Here is the assignment PDF and an analysis another assistant produced. Verify every
   technical claim against primary documentation (MySQL 9.6 manual, SQLAlchemy 2.0, Flask,
   OWASP) and list what is wrong or missing before we write any code."*
2. *"Implement confirm_order so that two users confirming orders for the same limited stock
   can never drive stock negative, and a repeated confirm never deducts twice. Explain the
   locking order and write a pytest that proves it with two real database connections."*
3. *"Write the all-or-nothing CSV import: validate the header and every row first, report
   every error with its spreadsheet row number, detect duplicates inside the file and in the
   database, and import nothing if any row is invalid."*

## How the generated code was reviewed

### Checks run during development

- **Real MySQL.** About 130 automated tests run against MySQL 9.6. They cover every Part 12
  scenario plus concurrency, permissions, API errors, CSV edge cases and the report rules.
- **Making sure the important tests can fail.** The code was temporarily broken and the
  concurrency tests were re-run:
  - with the row locks removed, the tests failed: 8 units were sold from a stock of 5
  - with `populate_existing` removed, the tests failed: stock was deducted twice
- **Headless Chrome walkthrough** of the real pages:
  - live totals
  - validation messages
  - confirm and cancel dialogs
  - the insufficient-stock message
  - a URL changed to another user's order
  - the CSV error table
- **SQL.** Every query in `sql/queries.sql` was run on the seeded data and the results were
  checked.

### My own review

<!-- TODO before submitting: describe what YOU did, in your own words. For example: which
     files you read line by line, the flows you traced by hand (create -> edit -> confirm ->
     cancel, CSV import), what you changed after reading, and what you tried in the browser.
     The interview will ask you to explain and modify this code. -->

## Corrections made

These are problems in the AI-generated plan or first drafts that were found and fixed.
Details and sources are in [docs/DECISIONS.md](docs/DECISIONS.md).

1. **Stale ORM object under a row lock.**
   - Problem: the plan said "lock the order row, then re-check its status". With SQLAlchemy
     the locked SELECT returned the *cached* object with the old status, so a double confirm
     deducted stock twice.
   - Fix: added `populate_existing=True`. A test fails without it.
2. **Order-number race.**
   - Problem: "count today's orders + 1" gives two concurrent orders the same number.
   - Fix: the number now comes from the AUTO_INCREMENT id, in the same transaction.
3. **Case-insensitive product codes.**
   - Problem: the plan's case-sensitive duplicate check would let `prd-001` and `PRD-001`
     through validation, and the import would then fail half-way through.
   - Fix: codes are normalised to upper case everywhere.
4. **Missing CSRF protection and a 302 instead of 401 for the API.** Both were added and are
   tested.
5. **Smaller fixes:**
   - Dropped a redundant `CSV_IMPORT` movement type.
   - Made customer email non-unique, as the brief only requires unique user emails.
   - Used `DATETIME` instead of `TIMESTAMP`.
   - Pinned SQLAlchemy below 2.1.
   - Added `PyMySQL[rsa]` for MySQL 9.
   - Gave a clear message for malformed JSON, which first returned a generic Werkzeug text.
6. **Fixed after a second, independent AI code review.** Each finding was re-checked against
   the code before fixing, and a regression test was added in `tests/test_edge_cases.py`.
   - Over-large quantities caused a 500 instead of a validation error.
   - An open-redirect gap (`/\evil.example`) in the login `next` parameter.
   - A customer name with a quote could break out of an inline `confirm()` script.
   - A race between delete and order creation gave a 500.
   - Draft line inserts took product locks in payload order.
   - The Save button was re-enabled before navigating away.
   - An anonymous API POST returned the CSRF error instead of 401.
