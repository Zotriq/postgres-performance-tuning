# Benchmark results

PostgreSQL 16.15 · 2,000,000 orders · 200,000 customers · 3,999,467 order items · 1,000,000 catalogue products · median of 9 warm runs

| Case | Before | After | Speed-up | Rows scanned before → after | Same result |
|---|---:|---:|---:|---|:---:|
| Customer order history page | 58.8 ms | 0.13 ms | **460x** | 2,000,001 → 12 | ✅ |
| Case-insensitive email login | 25.6 ms | 0.06 ms | **403x** | 200,000 → 1 | ✅ |
| Ops dashboard: pending orders this week | 65.7 ms | 3.02 ms | **22x** | 2,000,001 → 1,644 | ✅ |
| Admin order list, page 10,000 | 48.3 ms | 0.18 ms | **268x** | 500,050 → 50 | ✅ |
| Product search box | 232.4 ms | 1.76 ms | **132x** | 999,999 → 3 | ✅ |
| Which orders contain this product? | 113.2 ms | 2.19 ms | **52x** | 4,000,001 → 1,066 | ✅ |

## Plans

- **Customer order history page**: `Gather Merge, Limit, Seq Scan, Sort` → `Bitmap Heap Scan, Bitmap Index Scan, Limit, Sort` using `orders_customer_created_idx`
- **Case-insensitive email login**: `Gather, Seq Scan` → `Index Scan` using `customers_lower_email_idx`
- **Ops dashboard: pending orders this week**: `Gather Merge, Seq Scan, Sort` → `Index Scan` using `orders_pending_created_idx`
- **Admin order list, page 10,000**: `Index Scan, Limit` → `Index Scan, Limit` using `orders_pkey`
- **Product search box**: `Gather, Limit, Seq Scan` → `Bitmap Heap Scan, Bitmap Index Scan, Limit` using `products_big_name_trgm_idx`
- **Which orders contain this product?**: `Gather Merge, Index Scan, Limit, Nested Loop, Seq Scan, Sort` → `Bitmap Heap Scan, Bitmap Index Scan, Index Scan, Limit, Nested Loop, Sort` using `order_items_product_idx, orders_pkey`
