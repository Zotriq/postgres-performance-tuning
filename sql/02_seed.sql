-- Deterministic synthetic data. Sizes are set with psql variables:
--   psql -v customers=200000 -v orders=2000000 -f sql/02_seed.sql
SELECT setseed(0.42);

INSERT INTO customers
SELECT g,
       'user' || g || '@' || (ARRAY['gmail.com','yahoo.com','outlook.com','company.io'])[1 + g % 4],
       (ARRAY['Ayesha','Liam','Sofia','Omar','Emma','Bilal','Noah','Sara','Lucas','Hina'])[1 + g % 10] || ' ' ||
       (ARRAY['Khan','Smith','Rossi','Ahmed','Brown','Garcia','Malik','Chen','Silva','Ali'])[1 + (g / 10) % 10],
       (ARRAY['Pakistan','United States','United Kingdom','Germany','UAE','Canada'])[1 + g % 6],
       timestamptz '2023-01-01' + (random() * interval '1000 days')
FROM generate_series(1, :customers) AS g;

INSERT INTO products
SELECT g,
       (ARRAY['Wireless','Ergonomic','Smart','Compact','Premium','Eco'])[1 + g % 6] || ' ' ||
       (ARRAY['Keyboard','Monitor','Headphones','Desk Lamp','Webcam','Mouse','Charger','Backpack'])[1 + (g / 6) % 8] || ' ' || g,
       (ARRAY['Accessories','Displays','Audio','Office','Travel'])[1 + g % 5],
       round((5 + random() * 495)::numeric, 2)
FROM generate_series(1, 5000) AS g;

INSERT INTO orders
SELECT g,
       1 + floor(random() * :customers)::bigint,
       CASE WHEN r < 0.70 THEN 'shipped' WHEN r < 0.85 THEN 'paid' WHEN r < 0.93 THEN 'pending'
            WHEN r < 0.97 THEN 'refunded' ELSE 'cancelled' END,
       round((10 + random() * 990)::numeric, 2),
       timestamptz '2024-01-01' + ((g::float / :orders) * interval '700 days') + (random() * interval '1 hour')
FROM (SELECT g, random() AS r FROM generate_series(1, :orders) AS g) s;

INSERT INTO order_items
SELECT o.id, p.pid, 1 + (o.id + p.pid) % 3
FROM orders o
CROSS JOIN LATERAL (
    SELECT DISTINCT 1 + ((o.id * k * 7919) % 5000) AS pid FROM generate_series(1, 1 + o.id % 3) AS k
) p;

INSERT INTO products_big
SELECT g,
       (ARRAY['Wireless','Ergonomic','Smart','Compact','Premium','Eco','Vintage','Pro'])[1 + g % 8] || ' ' ||
       (ARRAY['Keyboard','Monitor','Headphones','Desk Lamp','Webcam','Mouse','Charger','Backpack','Speaker','Stand'])[1 + (g / 8) % 10] || ' ' || g,
       round((5 + random() * 495)::numeric, 2)
FROM generate_series(1, :products_big) AS g;

ANALYZE;
