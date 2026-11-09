-- Sales Order & Inventory Management: database schema
-- Target: MySQL 8.0.16+ (CHECK constraints are enforced from 8.0.16). Developed on MySQL 9.6.
--
-- Run manually:   mysql -u savyant_app -p savyant_db < db/schema.sql
-- Or via Flask:   flask init-db
--
-- Note: this file is executed statement-by-statement (split on ';') by `flask init-db`
-- and by the test suite, so keep it free of DELIMITER blocks, triggers and procedures.
--
-- Design notes
--  * Money is DECIMAL(12,2); never FLOAT/DOUBLE.
--  * Foreign keys to master data use ON DELETE RESTRICT so a customer/product that is
--    referenced by an order (or a product referenced by a stock movement) cannot be deleted.
--    The application checks first and shows "deactivate instead"; RESTRICT is the backstop.
--  * Order items are owned by their order (ON DELETE CASCADE). Orders themselves are never
--    deleted by the application; they are cancelled.
--  * Default collation utf8mb4_0900_ai_ci is case-insensitive, so product_code 'prd-001'
--    and 'PRD-001' collide on the UNIQUE index. The app normalises codes to upper case.

DROP TABLE IF EXISTS stock_movements;
DROP TABLE IF EXISTS sales_order_items;
DROP TABLE IF EXISTS sales_orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id            INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    name          VARCHAR(100)  NOT NULL,
    email         VARCHAR(150)  NOT NULL,
    password_hash VARCHAR(255)  NOT NULL,
    role          ENUM('Admin', 'Sales User') NOT NULL DEFAULT 'Sales User',
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE customers (
    id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
    name       VARCHAR(150) NOT NULL,
    email      VARCHAR(150) NOT NULL,
    mobile     VARCHAR(20)  NOT NULL,
    city       VARCHAR(100) NOT NULL,
    is_active  BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_customers_name (name),
    KEY idx_customers_email (email),
    KEY idx_customers_mobile (mobile),
    KEY idx_customers_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE products (
    id             INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    product_code   VARCHAR(50)   NOT NULL,
    name           VARCHAR(150)  NOT NULL,
    category       VARCHAR(100)  NOT NULL,
    price          DECIMAL(12,2) NOT NULL,
    stock_quantity INT           NOT NULL DEFAULT 0,
    is_active      BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_products_code (product_code),
    KEY idx_products_name (name),
    KEY idx_products_category_active (category, is_active),
    CONSTRAINT chk_products_price_non_negative CHECK (price >= 0),
    CONSTRAINT chk_products_stock_non_negative CHECK (stock_quantity >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE sales_orders (
    id                  INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    -- NULL only for the instant between INSERT and the id-based number being assigned
    -- (same transaction). UNIQUE allows multiple NULLs.
    order_number        VARCHAR(30)   NULL,
    customer_id         INT UNSIGNED  NOT NULL,
    order_date          DATE          NOT NULL,
    status              ENUM('Draft', 'Confirmed', 'Cancelled') NOT NULL DEFAULT 'Draft',
    discount_percentage DECIMAL(5,2)  NOT NULL DEFAULT 0.00,
    subtotal            DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    discount_amount     DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    grand_total         DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    created_by          INT UNSIGNED  NOT NULL,
    created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_sales_orders_number (order_number),
    KEY idx_sales_orders_customer (customer_id),
    KEY idx_sales_orders_status_date (status, order_date),
    KEY idx_sales_orders_created_by (created_by),
    CONSTRAINT fk_sales_orders_customer FOREIGN KEY (customer_id)
        REFERENCES customers (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_sales_orders_created_by FOREIGN KEY (created_by)
        REFERENCES users (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_sales_orders_discount_range CHECK (discount_percentage >= 0 AND discount_percentage <= 20),
    CONSTRAINT chk_sales_orders_amounts CHECK (subtotal >= 0 AND discount_amount >= 0 AND grand_total >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE sales_order_items (
    id             INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    sales_order_id INT UNSIGNED  NOT NULL,
    product_id     INT UNSIGNED  NOT NULL,
    quantity       INT           NOT NULL,
    rate           DECIMAL(12,2) NOT NULL,  -- product price captured when the line was added
    amount         DECIMAL(12,2) NOT NULL,  -- quantity * rate
    PRIMARY KEY (id),
    -- One row per product per order: enforces "reject duplicate products" at DB level.
    UNIQUE KEY uq_sales_order_items_order_product (sales_order_id, product_id),
    KEY idx_sales_order_items_product (product_id),
    CONSTRAINT fk_sales_order_items_order FOREIGN KEY (sales_order_id)
        REFERENCES sales_orders (id) ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_sales_order_items_product FOREIGN KEY (product_id)
        REFERENCES products (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_sales_order_items_quantity CHECK (quantity > 0),
    CONSTRAINT chk_sales_order_items_rate CHECK (rate >= 0),
    CONSTRAINT chk_sales_order_items_amount CHECK (amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE stock_movements (
    id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
    product_id       INT UNSIGNED NOT NULL,
    movement_type    ENUM('OPENING_STOCK', 'ORDER_CONFIRM', 'ORDER_CANCEL', 'ADJUSTMENT') NOT NULL,
    quantity_change  INT          NOT NULL,  -- signed: + adds stock, - removes stock
    related_order_id INT UNSIGNED NULL,      -- set for ORDER_CONFIRM / ORDER_CANCEL
    reason           VARCHAR(255) NOT NULL,
    created_by       INT UNSIGNED NOT NULL,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_stock_movements_product_time (product_id, created_at),
    KEY idx_stock_movements_order (related_order_id),
    CONSTRAINT fk_stock_movements_product FOREIGN KEY (product_id)
        REFERENCES products (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_stock_movements_order FOREIGN KEY (related_order_id)
        REFERENCES sales_orders (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_stock_movements_created_by FOREIGN KEY (created_by)
        REFERENCES users (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_stock_movements_nonzero CHECK (quantity_change <> 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
