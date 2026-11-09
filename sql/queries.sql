-- Part 9: standalone SQL queries (MySQL 8.0+).
-- Run against the seeded database, e.g.:
--     mysql -u savyant_app -p savyant_db < sql/queries.sql
-- "Sales" means Confirmed orders only (Draft orders are not sales; Cancelled orders were reversed).


-- 1. Top three customers by Confirmed order grand total -------------------------------
-- grand_total is stored on the order header, so sales_order_items is not joined
-- (joining items would repeat each order once per item and inflate the sum).
-- Ties at the cut-off are broken by customer name so the result is deterministic.
SELECT c.id,
       c.name,
       COUNT(so.id)        AS confirmed_orders,
       SUM(so.grand_total) AS total_sales
FROM customers c
JOIN sales_orders so ON so.customer_id = c.id
WHERE so.status = 'Confirmed'
GROUP BY c.id, c.name
ORDER BY total_sales DESC, c.name
LIMIT 3;

-- Variant that keeps every customer tied for 3rd place (may return more than 3 rows):
-- WITH ranked AS (
--     SELECT c.id, c.name, SUM(so.grand_total) AS total_sales,
--            RANK() OVER (ORDER BY SUM(so.grand_total) DESC) AS sales_rank
--     FROM customers c
--     JOIN sales_orders so ON so.customer_id = c.id AND so.status = 'Confirmed'
--     GROUP BY c.id, c.name
-- )
-- SELECT * FROM ranked WHERE sales_rank <= 3 ORDER BY sales_rank, name;


-- 2. Top three products by quantity sold in Confirmed orders --------------------------
SELECT p.id,
       p.product_code,
       p.name,
       SUM(soi.quantity) AS quantity_sold
FROM sales_order_items soi
JOIN sales_orders so ON so.id = soi.sales_order_id
JOIN products p      ON p.id = soi.product_id
WHERE so.status = 'Confirmed'
GROUP BY p.id, p.product_code, p.name
ORDER BY quantity_sold DESC, p.product_code
LIMIT 3;


-- 3. Customers who have never placed any order ----------------------------------------
-- "Any order" means any status: a customer with only a Draft or Cancelled order HAS
-- placed an order, so there is deliberately no status filter here.
SELECT c.id,
       c.name,
       c.email,
       c.city,
       c.is_active
FROM customers c
WHERE NOT EXISTS (
    SELECT 1 FROM sales_orders so WHERE so.customer_id = c.id
)
ORDER BY c.name;


-- 4. Month-wise Confirmed sales totals, grouped by year and month ----------------------
-- The SELECT list uses exactly the GROUP BY expressions (required by ONLY_FULL_GROUP_BY,
-- which is on by default in MySQL 8).
SELECT YEAR(so.order_date)   AS sales_year,
       MONTH(so.order_date)  AS sales_month,
       COUNT(*)              AS confirmed_orders,
       SUM(so.subtotal)      AS gross_sales,
       SUM(so.discount_amount) AS total_discount,
       SUM(so.grand_total)   AS net_sales
FROM sales_orders so
WHERE so.status = 'Confirmed'
GROUP BY YEAR(so.order_date), MONTH(so.order_date)
ORDER BY sales_year, sales_month;


-- 5. Products below a supplied stock threshold -----------------------------------------
-- "Below" is strictly less than. Change the value of @threshold as needed.
SET @threshold = 5;

SELECT p.id,
       p.product_code,
       p.name,
       p.category,
       p.stock_quantity,
       p.is_active
FROM products p
WHERE p.stock_quantity < @threshold
ORDER BY p.stock_quantity, p.product_code;
