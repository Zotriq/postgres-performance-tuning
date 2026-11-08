# PostgreSQL Performance Tuning: A Measured Case Study

![tests](https://github.com/Zotriq/postgres-performance-tuning/actions/workflows/tests.yml/badge.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Python](https://img.shields.io/badge/Python-benchmark-3776AB?style=flat-square&logo=python&logoColor=white)

Six slow queries from a typical e-commerce app: why each one is slow, the fix, and **measured before/after
timings** on a database with 2,000,000 orders, 3,999,467 order items, 200,000 customers and 1,000,000
catalogue products.

Every number below was produced by [`bench/run.py`](bench/run.py) on PostgreSQL 16.15 and can be reproduced
with the scripts in this repo. Each fix was also checked to return **exactly the same rows** as the original query.

## Results

| Problem | Before | After | Speed-up | Technique |
|---|---:|---:|---:|---|
| [Customer order history page](#1-customer-order-history-page) | 58.8 ms | 0.13 ms | **460x** | Composite index |
| [Case-insensitive email login](#2-case-insensitive-email-login) | 25.6 ms | 0.06 ms | **403x** | Expression index |
| [Ops dashboard: pending orders this week](#3-ops-dashboard-pending-orders-this-week) | 65.7 ms | 3.02 ms | **22x** | Partial index |
| [Admin order list, page 10,000](#4-admin-order-list-page-10000) | 48.3 ms | 0.18 ms | **268x** | Keyset pagination |
| [Product search box](#5-product-search-box) | 232.4 ms | 1.76 ms | **132x** | Trigram GIN index |
| [Which orders contain this product?](#6-which-orders-contain-this-product) | 113.2 ms | 2.19 ms | **52x** | Index on second FK |

<sub>Median of 9 warm runs on a small 2-vCPU / 8 GB machine. Absolute times vary by hardware; the gap
between before and after is what matters, and it grows as tables grow, because most "before" plans read the
whole table.</sub>

## How I approach a slow database

1. **Find the queries that matter.** Use `pg_stat_statements` to sort by total time (calls × average), not just the slowest single query.
2. **Read the plan.** Run `EXPLAIN (ANALYZE, BUFFERS)` and look for `Seq Scan` on big tables, large "Rows Removed by Filter", sorts spilling to disk, and estimates far from actual row counts.
3. **Fix the access path.** Choose the right index type (B-tree, expression, partial, composite, GIN trigram) or rewrite the query (keyset pagination, no functions on indexed columns).
4. **Prove it.** Re-measure, confirm the planner uses the new index, and check the result is unchanged.
5. **Ship safely.** Use `CREATE INDEX CONCURRENTLY` in production, and don't add indexes that writes pay for but no query uses.

## The six cases

### 1. Customer order history page

*'My orders' page: a customer's 20 most recent orders.*

```sql
SELECT id, status, total, created_at FROM orders
WHERE customer_id = %(customer_id)s ORDER BY created_at DESC LIMIT 20
```

**Why it was slow:** No index on orders.customer_id. PostgreSQL does not index foreign keys automatically, so every page view scans all 2 million orders.

**Fix:** Composite B-tree index on (customer_id, created_at DESC), so the database jumps straight to that customer's orders instead of reading all of them.

```sql
CREATE INDEX orders_customer_created_idx ON orders (customer_id, created_at DESC);
```

**Result:** 58.8 ms → **0.13 ms** (460x faster). Rows read: 2,000,001 → 12.  
Plan: `Gather Merge, Limit, Seq Scan, Sort` → `Bitmap Heap Scan, Bitmap Index Scan, Limit, Sort`

### 2. Case-insensitive email login

*Login form looks a user up by email, ignoring case.*

```sql
SELECT id, full_name FROM customers WHERE lower(email) = lower(%(email)s)
```

**Why it was slow:** Wrapping the column in lower() means a plain index on email could never be used, so every login scans the whole customers table.

**Fix:** Expression index on lower(email), which matches the expression in the WHERE clause exactly.

```sql
CREATE INDEX customers_lower_email_idx ON customers (lower(email));
```

**Result:** 25.6 ms → **0.06 ms** (403x faster). Rows read: 200,000 → 1.  
Plan: `Gather, Seq Scan` → `Index Scan`

### 3. Ops dashboard: pending orders this week

*Warehouse dashboard refreshes every minute to show pending orders from the last 7 days.*

```sql
SELECT id, customer_id, total, created_at FROM orders
WHERE status = 'pending' AND created_at >= %(since)s ORDER BY created_at
```

**Why it was slow:** Only ~8% of orders are pending and the dashboard only wants recent ones, but without an index the database reads every order to find them.

**Fix:** Partial index: it only stores pending orders (~8% of the table), so it's small, cheap to maintain and stays in memory.

```sql
CREATE INDEX orders_pending_created_idx ON orders (created_at) WHERE status = 'pending';
```

**Result:** 65.7 ms → **3.02 ms** (22x faster). Rows read: 2,000,001 → 1,644.  
Plan: `Gather Merge, Seq Scan, Sort` → `Index Scan`

### 4. Admin order list, page 10,000

*Admin panel pages through all orders, 50 per page, using OFFSET.*

```sql
SELECT id, status, total FROM orders ORDER BY id LIMIT 50 OFFSET 500000
```

**Why it was slow:** OFFSET 500000 makes PostgreSQL read and throw away 500,000 rows before returning 50, so pages get slower the deeper you go.

**Fix:** Keyset (cursor) pagination: remember the last id on the page and continue from it. Every page costs the same. No schema change is needed, just a query rewrite.

```sql
-- no schema change
```

**Query after**

```sql
SELECT id, status, total FROM orders WHERE id > %(last_id)s ORDER BY id LIMIT 50
```

**Result:** 48.3 ms → **0.18 ms** (268x faster). Rows read: 500,050 → 50.  
Plan: `Index Scan, Limit` → `Index Scan, Limit`

### 5. Product search box

*Shop search box: products whose name contains the typed text.*

```sql
SELECT id, name, price FROM products_big WHERE name ILIKE %(pattern)s LIMIT 20
```

**Why it was slow:** A leading wildcard ('%lamp 98747%') can't use a normal B-tree index, so every search scans the whole catalogue.

**Fix:** Trigram GIN index (pg_trgm), which supports ILIKE '%...%' and fuzzy matching.

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX products_big_name_trgm_idx ON products_big USING gin (name gin_trgm_ops);
```

**Result:** 232.4 ms → **1.76 ms** (132x faster). Rows read: 999,999 → 3.  
Plan: `Gather, Limit, Seq Scan` → `Bitmap Heap Scan, Bitmap Index Scan, Limit`

### 6. Which orders contain this product?

*Product recall / support tool: all orders that include a given product.*

```sql
SELECT o.id, o.created_at, o.status FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE oi.product_id = %(product_id)s ORDER BY o.created_at DESC LIMIT 100
```

**Why it was slow:** order_items' primary key is (order_id, product_id), which only helps lookups that start with order_id. Filtering by product_id scans every line item.

**Fix:** Index on the second foreign key. A composite primary key only covers its leading column.

```sql
CREATE INDEX order_items_product_idx ON order_items (product_id);
```

**Result:** 113.2 ms → **2.19 ms** (52x faster). Rows read: 4,000,001 → 1,066.  
Plan: `Gather Merge, Index Scan, Limit, Nested Loop, Seq Scan, Sort` → `Bitmap Heap Scan, Bitmap Index Scan, Index Scan, Limit, Nested Loop, Sort`

## Run it yourself

```bash
createdb perf
psql perf -f sql/01_schema.sql
psql perf -v customers=200000 -v orders=2000000 -v products_big=1000000 -f sql/02_seed.sql   # about 1 minute
pip install -r requirements.txt
python bench/run.py --url postgresql://localhost/perf     # writes results.md and results.json
```

All the fixes together, production-safe (`CONCURRENTLY`, idempotent): [`sql/03_fixes.sql`](sql/03_fixes.sql).

## Tests

`pytest` seeds a smaller database and checks, for every case, that the fix returns identical rows, reads fewer
rows, and that the planner really uses the new index. It also checks that the fix script can safely be run twice.
GitHub Actions runs it against PostgreSQL 16 on every push.

```bash
PG_TEST_URL=postgresql://postgres@localhost:5432/perf_test pytest
```

## Files

```
sql/01_schema.sql    tables in their original state (primary keys only)
sql/02_seed.sql      deterministic synthetic data (sizes set with psql variables)
sql/03_fixes.sql     every fix, production-safe
bench/cases.py       the six cases: query, explanation, fix
bench/run.py         benchmark runner (timings, EXPLAIN ANALYZE, result comparison)
results.md / .json   the latest benchmark output
tests/               pytest suite
```

## License

MIT © Zohaib Tariq
