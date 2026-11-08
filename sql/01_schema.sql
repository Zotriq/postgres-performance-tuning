-- E-commerce schema in its "before" state: primary keys only, like many real
-- databases that grew without anyone looking at query plans.
DROP TABLE IF EXISTS order_items, orders, products, customers CASCADE;

CREATE TABLE customers (
    id          bigint PRIMARY KEY,
    email       text NOT NULL,
    full_name   text NOT NULL,
    country     text NOT NULL,
    created_at  timestamptz NOT NULL
);

CREATE TABLE products (
    id        bigint PRIMARY KEY,
    name      text NOT NULL,
    category  text NOT NULL,
    price     numeric(10,2) NOT NULL
);

CREATE TABLE orders (
    id           bigint PRIMARY KEY,
    customer_id  bigint NOT NULL REFERENCES customers(id),
    status       text NOT NULL,          -- pending | paid | shipped | refunded | cancelled
    total        numeric(12,2) NOT NULL,
    created_at   timestamptz NOT NULL
);

CREATE TABLE order_items (
    order_id    bigint NOT NULL REFERENCES orders(id),
    product_id  bigint NOT NULL REFERENCES products(id),
    quantity    int NOT NULL,
    PRIMARY KEY (order_id, product_id)
);

-- Large product catalogue for the search case (a marketplace with 1M listings).
DROP TABLE IF EXISTS products_big;
CREATE TABLE products_big (
    id     bigint PRIMARY KEY,
    name   text NOT NULL,
    price  numeric(10,2) NOT NULL
);
