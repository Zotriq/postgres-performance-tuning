"""The six slow queries, why they are slow, and the fix for each.

Every case has:
  before  - the query as the application originally sent it
  fix     - DDL to apply (indexes / extensions); may be empty
  after   - the query after the fix (often identical; sometimes rewritten)
  undo    - DDL that restores the "before" state, so the benchmark is repeatable
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    key: str
    title: str
    scenario: str
    before: str
    after: str
    fix: list[str]
    undo: list[str]
    why: str
    technique: str
    params: dict = field(default_factory=dict)


CASES: list[Case] = [
    Case(
        key="customer_history",
        title="Customer order history page",
        scenario="'My orders' page: a customer's 20 most recent orders.",
        before="""SELECT id, status, total, created_at FROM orders
WHERE customer_id = %(customer_id)s ORDER BY created_at DESC LIMIT 20""",
        after="""SELECT id, status, total, created_at FROM orders
WHERE customer_id = %(customer_id)s ORDER BY created_at DESC LIMIT 20""",
        fix=["CREATE INDEX orders_customer_created_idx ON orders (customer_id, created_at DESC)"],
        undo=["DROP INDEX IF EXISTS orders_customer_created_idx"],
        why="No index on orders.customer_id. PostgreSQL does not index foreign keys automatically, "
            "so every page view scans all 2 million orders.",
        technique="Composite B-tree index on (customer_id, created_at DESC), so the database jumps straight "
                  "to that customer's orders instead of reading all of them.",
        params={"customer_id": 4242},
    ),
    Case(
        key="email_login",
        title="Case-insensitive email login",
        scenario="Login form looks a user up by email, ignoring case.",
        before="SELECT id, full_name FROM customers WHERE lower(email) = lower(%(email)s)",
        after="SELECT id, full_name FROM customers WHERE lower(email) = lower(%(email)s)",
        fix=["CREATE INDEX customers_lower_email_idx ON customers (lower(email))"],
        undo=["DROP INDEX IF EXISTS customers_lower_email_idx"],
        why="Wrapping the column in lower() means a plain index on email could never be used, "
            "so every login scans the whole customers table.",
        technique="Expression index on lower(email), which matches the expression in the WHERE clause exactly.",
        params={"email": "USER150123@Company.IO"},
    ),
    Case(
        key="pending_dashboard",
        title="Ops dashboard: pending orders this week",
        scenario="Warehouse dashboard refreshes every minute to show pending orders from the last 7 days.",
        before="""SELECT id, customer_id, total, created_at FROM orders
WHERE status = 'pending' AND created_at >= %(since)s ORDER BY created_at""",
        after="""SELECT id, customer_id, total, created_at FROM orders
WHERE status = 'pending' AND created_at >= %(since)s ORDER BY created_at""",
        fix=["CREATE INDEX orders_pending_created_idx ON orders (created_at) WHERE status = 'pending'"],
        undo=["DROP INDEX IF EXISTS orders_pending_created_idx"],
        why="Only ~8% of orders are pending and the dashboard only wants recent ones, but without an "
            "index the database reads every order to find them.",
        technique="Partial index: it only stores pending orders (~8% of the table), so it's small, cheap to "
                  "maintain and stays in memory.",
        params={"since": "2025-11-24"},
    ),
    Case(
        key="deep_pagination",
        title="Admin order list, page 10,000",
        scenario="Admin panel pages through all orders, 50 per page, using OFFSET.",
        before="SELECT id, status, total FROM orders ORDER BY id LIMIT 50 OFFSET 500000",
        after="SELECT id, status, total FROM orders WHERE id > %(last_id)s ORDER BY id LIMIT 50",
        fix=[],
        undo=[],
        why="OFFSET 500000 makes PostgreSQL read and throw away 500,000 rows before returning 50, "
            "so pages get slower the deeper you go.",
        technique="Keyset (cursor) pagination: remember the last id on the page and continue from it. "
                  "Every page costs the same. No schema change is needed, just a query rewrite.",
        params={"last_id": 500000},
    ),
    Case(
        key="product_search",
        title="Product search box",
        scenario="Shop search box: products whose name contains the typed text.",
        before="SELECT id, name, price FROM products_big WHERE name ILIKE %(pattern)s LIMIT 20",
        after="SELECT id, name, price FROM products_big WHERE name ILIKE %(pattern)s LIMIT 20",
        fix=[
            "CREATE EXTENSION IF NOT EXISTS pg_trgm",
            "CREATE INDEX products_big_name_trgm_idx ON products_big USING gin (name gin_trgm_ops)",
        ],
        undo=["DROP INDEX IF EXISTS products_big_name_trgm_idx"],
        why="A leading wildcard ('%lamp 98747%') can't use a normal B-tree index, so every search scans the "
            "whole catalogue.",
        technique="Trigram GIN index (pg_trgm), which supports ILIKE '%...%' and fuzzy matching.",
        params={"pattern": "%lamp 98747%"},
    ),
    Case(
        key="product_orders",
        title="Which orders contain this product?",
        scenario="Product recall / support tool: all orders that include a given product.",
        before="""SELECT o.id, o.created_at, o.status FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE oi.product_id = %(product_id)s ORDER BY o.created_at DESC LIMIT 100""",
        after="""SELECT o.id, o.created_at, o.status FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE oi.product_id = %(product_id)s ORDER BY o.created_at DESC LIMIT 100""",
        fix=["CREATE INDEX order_items_product_idx ON order_items (product_id)"],
        undo=["DROP INDEX IF EXISTS order_items_product_idx"],
        why="order_items' primary key is (order_id, product_id), which only helps lookups that start with "
            "order_id. Filtering by product_id scans every line item.",
        technique="Index on the second foreign key. A composite primary key only covers its leading column.",
        params={"product_id": 1234},
    ),
]
