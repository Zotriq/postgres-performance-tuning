"""Run every case on a small seeded database and check the fix is correct and actually used.

    PG_TEST_URL=postgresql://postgres@localhost:5432/perf_test pytest
"""

import os
import pathlib
import subprocess
import sys

import psycopg
import pytest

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "bench"))

from cases import CASES  # noqa: E402
from run import plan, run_case  # noqa: E402

URL = os.getenv("PG_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set PG_TEST_URL")


@pytest.fixture(scope="module")
def conn():
    for f, extra in (("01_schema.sql", []), ("02_seed.sql", ["-v", "customers=20000", "-v", "orders=200000", "-v", "products_big=200000"])):
        subprocess.run(["psql", URL, "-q", "-v", "ON_ERROR_STOP=1", *extra, "-f", str(ROOT / "sql" / f)], check=True)
    with psycopg.connect(URL, autocommit=True) as c:
        yield c


@pytest.mark.parametrize("case", CASES, ids=[c.key for c in CASES])
def test_fix_returns_same_rows_and_uses_index(conn, case):
    result = run_case(conn, case, runs=2)
    assert result["same_result"], "the fix changed the query result"
    assert result["after_plan"]["rows_scanned"] < result["before_plan"]["rows_scanned"]
    if case.fix:
        expected = [s.split()[2] for s in case.fix if s.startswith("CREATE INDEX")][0]
        assert expected in result["after_plan"]["index_names"]


def test_cases_return_rows(conn):
    """Guard against benchmarking a query that matches nothing."""
    with conn.cursor() as cur:
        for case in CASES:
            if case.key in ("email_login", "deep_pagination"):
                continue  # the small test dataset has fewer customers and orders
            cur.execute(case.after, case.params)
            assert cur.fetchall(), f"{case.key} returned no rows"


def test_fix_script_is_idempotent(conn):
    for _ in range(2):
        subprocess.run(["psql", URL, "-q", "-v", "ON_ERROR_STOP=1", "-f", str(ROOT / "sql" / "03_fixes.sql")], check=True)
