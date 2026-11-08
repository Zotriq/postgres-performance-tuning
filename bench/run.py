"""Measure every case before and after its fix and write results.md / results.json.

    python bench/run.py --url postgresql://postgres@localhost/perf --runs 7

Each query is run several times after a warm-up and the median is reported, so
results reflect a warm cache (what users of a busy app actually see).
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import psycopg

from cases import CASES, Case

ROOT = Path(__file__).parents[1]


def timed(cur, sql: str, params: dict, runs: int) -> tuple[float, list]:
    cur.execute(sql, params)  # warm-up
    rows = cur.fetchall()
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        cur.execute(sql, params)
        cur.fetchall()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples), rows


def plan(cur, sql: str, params: dict) -> dict:
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
    root = cur.fetchone()[0][0]
    p = root["Plan"]

    def nodes(n):
        yield n
        for child in n.get("Plans", []):
            yield from nodes(child)

    all_nodes = list(nodes(p))
    return {
        "node_types": sorted({n["Node Type"] for n in all_nodes}),
        "index_names": sorted({n["Index Name"] for n in all_nodes if "Index Name" in n}),
        # Rows read by scan nodes = rows returned + rows filtered out, per loop (parallel workers count as loops).
        "rows_scanned": int(sum(
            (n.get("Actual Rows", 0) + n.get("Rows Removed by Filter", 0) + n.get("Rows Removed by Index Recheck", 0))
            * n.get("Actual Loops", 1)
            for n in all_nodes
            if n["Node Type"] in ("Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan")
        )),
        "shared_buffers": p.get("Shared Hit Blocks", 0) + p.get("Shared Read Blocks", 0),
        "execution_ms": root["Execution Time"],
    }


def run_case(conn, case: Case, runs: int) -> dict:
    with conn.cursor() as cur:
        for stmt in case.undo:
            cur.execute(stmt)
        cur.execute("ANALYZE")
        before_ms, before_rows = timed(cur, case.before, case.params, runs)
        before_plan = plan(cur, case.before, case.params)

        for stmt in case.fix:
            cur.execute(stmt)
        cur.execute("ANALYZE")
        after_ms, after_rows = timed(cur, case.after, case.params, runs)
        after_plan = plan(cur, case.after, case.params)

    return {
        "key": case.key,
        "title": case.title,
        "before_ms": round(before_ms, 2),
        "after_ms": round(after_ms, 2),
        "speedup": round(before_ms / after_ms, 1) if after_ms else None,
        "same_result": before_rows == after_rows,
        "before_plan": before_plan,
        "after_plan": after_plan,
    }


def write_markdown(results: list[dict], meta: dict) -> str:
    lines = [
        "# Benchmark results",
        "",
        f"PostgreSQL {meta['server_version']} · {meta['orders']:,} orders · {meta['customers']:,} customers · "
        f"{meta['order_items']:,} order items · {meta['products_big']:,} catalogue products · median of {meta['runs']} warm runs",
        "",
        "| Case | Before | After | Speed-up | Rows scanned before → after | Same result |",
        "|---|---:|---:|---:|---|:---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['title']} | {r['before_ms']:,.1f} ms | {r['after_ms']:,.2f} ms | **{r['speedup']:,.0f}x** | "
            f"{r['before_plan']['rows_scanned']:,} → {r['after_plan']['rows_scanned']:,} | {'✅' if r['same_result'] else '❌'} |"
        )
    lines += ["", "## Plans", ""]
    for r in results:
        lines.append(
            f"- **{r['title']}**: `{', '.join(r['before_plan']['node_types'])}` → `{', '.join(r['after_plan']['node_types'])}`"
            + (f" using `{', '.join(r['after_plan']['index_names'])}`" if r["after_plan"]["index_names"] else "")
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--runs", type=int, default=7)
    args = parser.parse_args()

    with psycopg.connect(args.url, autocommit=True) as conn:
        results = [run_case(conn, case, args.runs) for case in CASES]
        with conn.cursor() as cur:
            cur.execute("SHOW server_version")
            version = cur.fetchone()[0].split()[0]
            counts = {}
            for t in ("orders", "customers", "order_items", "products_big"):
                cur.execute(f"SELECT count(*) FROM {t}")
                counts[t] = cur.fetchone()[0]

    meta = {"server_version": version, "runs": args.runs, **counts}
    (ROOT / "results.json").write_text(json.dumps({"meta": meta, "results": results}, indent=2))
    (ROOT / "results.md").write_text(write_markdown(results, meta))
    print(write_markdown(results, meta))


if __name__ == "__main__":
    main()
