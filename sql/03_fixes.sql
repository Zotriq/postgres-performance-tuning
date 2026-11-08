-- All fixes from the case study, in one script. Run with: psql "$DATABASE_URL" -f sql/03_fixes.sql
-- CONCURRENTLY builds each index without blocking writes on a live production table.

-- Customer order history page: Composite B-tree index on (customer_id, created_at DESC), so the database jumps straight to that customer's orders instead of reading all of them.
CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_customer_created_idx ON orders (customer_id, created_at DESC);

-- Case-insensitive email login: Expression index on lower(email), which matches the expression in the WHERE clause exactly.
CREATE INDEX CONCURRENTLY IF NOT EXISTS customers_lower_email_idx ON customers (lower(email));

-- Ops dashboard: pending orders this week: Partial index: it only stores pending orders (~8% of the table), so it's small, cheap to maintain and stays in memory.
CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_pending_created_idx ON orders (created_at) WHERE status = 'pending';

-- Admin order list, page 10,000: Keyset (cursor) pagination: remember the last id on the page and continue from it. Every page costs the same. No schema change is needed, just a query rewrite.
-- (query rewrite only, see README)

-- Product search box: Trigram GIN index (pg_trgm), which supports ILIKE '%...%' and fuzzy matching.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX CONCURRENTLY IF NOT EXISTS products_big_name_trgm_idx ON products_big USING gin (name gin_trgm_ops);

-- Which orders contain this product?: Index on the second foreign key. A composite primary key only covers its leading column.
CREATE INDEX CONCURRENTLY IF NOT EXISTS order_items_product_idx ON order_items (product_id);
