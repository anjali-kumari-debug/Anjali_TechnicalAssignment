# REST API

All endpoints return JSON. They use the same session login as the web pages, and the same
service functions. Validation and permission rules are therefore identical in the browser
and the API.

| Method | Endpoint | Purpose | Who |
|--------|----------|---------|-----|
| GET  | `/api/products` | List **active** products, with search and pagination | any logged-in user |
| GET  | `/api/orders` | List orders you may see (Sales User: own; Admin: all) | any logged-in user |
| POST | `/api/orders` | Create a **Draft** order | any logged-in user |
| GET  | `/api/orders/{id}` | Order with its items | owner or Admin |
| PUT  | `/api/orders/{id}` | Replace a Draft's customer, discount and items | owner or Admin |
| POST | `/api/orders/{id}/confirm` | Confirm and deduct stock | owner or Admin |
| POST | `/api/orders/{id}/cancel` | Cancel; restore stock if it was Confirmed | owner or Admin |

`PUT /api/orders/{id}` is an addition to the five required endpoints. The assignment allows
"equivalent routes", and Draft orders must be editable.

## Conventions

- **Money** is sent and returned as a **decimal string** (`"1500.00"`), never a float.
  Requests may send numbers or strings.
- **Dates** use ISO 8601 (`"2026-11-09"`).
- **Ignored fields.** The server never reads `rate`, `amount`, `subtotal`, `grand_total`,
  `status`, `created_by` or `order_date` from a request. It always takes or calculates them
  itself.
- **Request bodies** must be JSON with `Content-Type: application/json`.
- **CSRF.** Every `POST`/`PUT` needs an `X-CSRFToken` header. The token is in the
  `<meta name="csrf-token">` tag of any page. The browser JavaScript sends it automatically.

### Errors

Every error has the same shape:

```json
{"error": {"code": "INSUFFICIENT_STOCK", "message": "Human-readable text", "details": [ ... ]}}
```

| Status | When | `code` examples |
|--------|------|-----------------|
| 400 | Invalid input (field-level `details`), malformed JSON, missing CSRF token | `VALIDATION_ERROR`, `BAD_REQUEST`, `CSRF_FAILED` |
| 401 | Not logged in (the API never redirects to the login page) | `UNAUTHORIZED` |
| 403 | Another user's order, or an Admin-only action | `FORBIDDEN` |
| 404 | Order/product does not exist, unknown URL | `NOT_FOUND` |
| 405 | Wrong HTTP method | `METHOD_NOT_ALLOWED` |
| 409 | Valid request that conflicts with current state: insufficient stock, order not Draft, already cancelled, row locked by another user | `INSUFFICIENT_STOCK`, `CANNOT_CONFIRM`, `ORDER_NOT_DRAFT`, `ORDER_ALREADY_CANCELLED`, `BUSY` |
| 415 | Body not sent as JSON | `UNSUPPORTED_MEDIA_TYPE` |
| 500 | Unexpected error. The body has a generic message only; details go to the server log. | `INTERNAL_ERROR` |

## Trying it with curl

```bash
BASE=http://127.0.0.1:5001
JAR=/tmp/savyant-cookies
csrf() { curl -s -b $JAR -c $JAR "$BASE$1" | sed -n 's/.*name="csrf-token" content="\([^"]*\)".*/\1/p'; }

# 1. Log in (the login form is CSRF-protected too)
curl -s -b $JAR -c $JAR -o /dev/null -X POST $BASE/login \
  --data-urlencode "csrf_token=$(csrf /login)" \
  --data-urlencode "email=ravi@example.com" --data-urlencode "password=$SEED_SALES_PASSWORD"

# 2. Get a token for API calls
TOKEN=$(csrf /orders)
```

The examples below were captured from the seeded database, logged in as `ravi@example.com`
(Sales User). Responses are pretty-printed.

### GET /api/products

Query parameters: `q` (code or name contains), `category`, `page` (default 1) and `per_page`
(default 20, max 100).

```bash
curl -s -b $JAR "$BASE/api/products?q=PRD-00&per_page=2"
```

```json
{
  "items": [
    {"id": 1, "product_code": "PRD-001", "name": "Keyboard", "category": "Accessories",
     "price": "1500.00", "stock_quantity": 17, "is_active": true},
    {"id": 2, "product_code": "PRD-002", "name": "Mouse", "category": "Accessories",
     "price": "500.00", "stock_quantity": 40, "is_active": true}
  ],
  "page": 1, "per_page": 2, "pages": 3, "total": 5
}
```

### POST /api/orders → 201

```bash
curl -s -b $JAR -X POST $BASE/api/orders -H "Content-Type: application/json" -H "X-CSRFToken: $TOKEN" \
  -d '{"customer_id": 1, "discount_percentage": "10",
       "items": [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 3}]}'
```

```json
{
  "id": 7,
  "order_number": "SO-20261109-00007",
  "status": "Draft",
  "order_date": "2026-11-09",
  "customer": {"id": 1, "name": "Sharma Traders"},
  "created_by": {"id": 2, "name": "Ravi Sales"},
  "created_at": "2026-11-09T18:29:25",
  "discount_percentage": "10.00",
  "subtotal": "4500.00",
  "discount_amount": "450.00",
  "grand_total": "4050.00",
  "items": [
    {"id": 10, "product_id": 1, "product_code": "PRD-001", "product_name": "Keyboard",
     "quantity": 2, "rate": "1500.00", "amount": "3000.00"},
    {"id": 11, "product_id": 2, "product_code": "PRD-002", "product_name": "Mouse",
     "quantity": 3, "rate": "500.00", "amount": "1500.00"}
  ]
}
```

Invalid input → **400**, with one entry per problem:

```bash
curl ... -d '{"customer_id": 1, "discount_percentage": "25",
              "items": [{"product_id": 1, "quantity": 0}, {"product_id": 1, "quantity": 2}]}'
```

```json
{"error": {
  "code": "VALIDATION_ERROR",
  "message": "Please correct the order.",
  "details": [
    {"field": "discount_percentage", "message": "discount_percentage must be between 0 and 20."},
    {"field": "items[0].quantity", "message": "Row 1: quantity must be greater than zero."},
    {"field": "items[1].product_id", "message": "Row 2: this product is already in the order."}
  ]
}}
```

### GET /api/orders/{id} → 200

Returns the same shape as the create response.

### PUT /api/orders/{id} → 200 (Draft only)

The body has the same shape as for create. The `items` list is the complete new set of lines.

- Products not in the list are removed.
- Products already on the order keep their **stored rate**.
- Newly added products take the product's **current** price.

```bash
curl -s -b $JAR -X PUT $BASE/api/orders/7 -H "Content-Type: application/json" -H "X-CSRFToken: $TOKEN" \
  -d '{"customer_id": 1, "discount_percentage": "5", "items": [{"product_id": 1, "quantity": 1}]}'
```

```json
{"id": 7, "status": "Draft", "discount_percentage": "5.00", "subtotal": "1500.00",
 "discount_amount": "75.00", "grand_total": "1425.00",
 "items": [{"product_id": 1, "product_code": "PRD-001", "quantity": 1, "rate": "1500.00", "amount": "1500.00", "...": "..."}],
 "...": "..."}
```

Editing a Confirmed or Cancelled order → **409** `ORDER_NOT_DRAFT`.

### POST /api/orders/{id}/confirm → 200

```bash
curl -s -b $JAR -X POST $BASE/api/orders/7/confirm -H "X-CSRFToken: $TOKEN"
```

This returns the order with `"status": "Confirmed"`, and stock is deducted. Repeating the
call does **not** deduct again:

```json
{"error": {"code": "ORDER_NOT_DRAFT", "message": "Order SO-20261109-00007 is already Confirmed; it cannot be confirmed."}}
```

If any line is short, **409** is returned, nothing changes, and every short product is listed:

```json
{"error": {
  "code": "INSUFFICIENT_STOCK",
  "message": "Order cannot be confirmed: insufficient stock.",
  "details": [{"product_code": "PRD-004", "requested": 30, "available": 3,
               "message": "Only 3 in stock, 30 requested."}]
}}
```

If a product or the customer has been deactivated since the Draft was created, you get
**409** `CANNOT_CONFIRM` or `CUSTOMER_INACTIVE`.

### POST /api/orders/{id}/cancel → 200

- Draft → Cancelled: stock does not change.
- Confirmed → Cancelled: the deducted quantities are restored once.
- Cancelling again returns:

```json
{"error": {"code": "ORDER_ALREADY_CANCELLED", "message": "Order SO-20261109-00007 is already Cancelled."}}
```

### Permission and error examples

```text
GET  /api/orders/3            (Meera's order, requested by Ravi)
403  {"error": {"code": "FORBIDDEN", "message": "Access denied. You can only access your own orders."}}

GET  /api/orders/9999
404  {"error": {"code": "NOT_FOUND", "message": "Order 9999 was not found."}}

GET  /api/orders/1            (no session cookie)
401  {"error": {"code": "UNAUTHORIZED", "message": "Please log in to continue."}}

POST /api/orders/1/cancel     (no X-CSRFToken header)
400  {"error": {"code": "CSRF_FAILED", "message": "The security (CSRF) token is missing or expired. Reload the page and try again."}}

POST /api/orders  body: {oops
400  {"error": {"code": "BAD_REQUEST", "message": "The request body is not valid JSON."}}
```
