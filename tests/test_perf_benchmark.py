"""
Pipeline performance benchmarks — run with:
    PYTHONPATH=. pytest tests/test_perf_benchmark.py -v --benchmark-sort=mean

Requires pytest-benchmark (pip install pytest-benchmark).
Skipped automatically when the package is not installed.
"""
import pytest

pytest.importorskip("pytest_benchmark", reason="pytest-benchmark not installed; run: pip install pytest-benchmark")


# ── SQL fixtures of increasing complexity ────────────────────────────────────

SQL_SIMPLE = "SELECT AddressID, City FROM SalesLT.Address"

SQL_AGGREGATION = """
SELECT CustomerID, COUNT(*) AS OrderCount, SUM(SubTotal) AS Total
FROM SalesLT.SalesOrderHeader
GROUP BY CustomerID
HAVING COUNT(*) > 1
"""

SQL_JOIN = """
SELECT c.CustomerID, c.FirstName, c.LastName, soh.SubTotal
FROM SalesLT.Customer c
JOIN SalesLT.SalesOrderHeader soh ON c.CustomerID = soh.CustomerID
WHERE soh.SubTotal > 1000
ORDER BY soh.SubTotal DESC
"""

SQL_WINDOW = """
SELECT SalesOrderID, CustomerID,
       ROW_NUMBER() OVER (PARTITION BY CustomerID ORDER BY OrderDate) AS rn,
       SUM(SubTotal) OVER (PARTITION BY CustomerID) AS CustomerTotal
FROM SalesLT.SalesOrderHeader
"""

SQL_CTE = """
WITH TopCustomers AS (
    SELECT CustomerID, SUM(SubTotal) AS Total
    FROM SalesLT.SalesOrderHeader
    GROUP BY CustomerID
)
SELECT c.FirstName, c.LastName, t.Total
FROM SalesLT.Customer c
JOIN TopCustomers t ON c.CustomerID = t.CustomerID
WHERE t.Total > 5000
ORDER BY t.Total DESC
"""

SQL_MULTI_STMT = SQL_SIMPLE + ";\n" + SQL_JOIN + ";\n" + SQL_WINDOW


# ── Benchmark: core pipeline stages ──────────────────────────────────────────

class TestPipelineBenchmark:
    """每個 test 都會被 pytest-benchmark 自動多次執行並統計。"""

    def test_simple_select(self, benchmark, global_runner):
        result = benchmark(global_runner.run_multi, SQL_SIMPLE)
        assert result["status"] == "success"

    def test_aggregation_having(self, benchmark, global_runner):
        result = benchmark(global_runner.run_multi, SQL_AGGREGATION)
        assert result["status"] == "success"

    def test_join_where_order(self, benchmark, global_runner):
        result = benchmark(global_runner.run_multi, SQL_JOIN)
        assert result["status"] == "success"

    def test_window_functions(self, benchmark, global_runner):
        result = benchmark(global_runner.run_multi, SQL_WINDOW)
        assert result["status"] == "success"

    def test_cte_complex(self, benchmark, global_runner):
        result = benchmark(global_runner.run_multi, SQL_CTE)
        assert result["status"] == "success"

    def test_multi_statement(self, benchmark, global_runner):
        result = benchmark(global_runner.run_multi, SQL_MULTI_STMT)
        assert result["status"] == "success"


# ── Benchmark: individual stages (isolate bottleneck) ────────────────────────

class TestStageBenchmark:

    def test_parse_only(self, benchmark, global_runner):
        """Lexer + Parser 單獨耗時（不含 Binder）"""
        result = benchmark(global_runner.parse_only_multi, SQL_CTE)
        assert "ast" in result

    def test_full_vs_parse_only(self, global_runner):
        """比較 parse_only 和 full pipeline 耗時差異（Binder overhead）"""
        import time

        rounds = 200
        t0 = time.perf_counter()
        for _ in range(rounds):
            global_runner.parse_only_multi(SQL_JOIN)
        parse_ms = (time.perf_counter() - t0) / rounds * 1000

        t0 = time.perf_counter()
        for _ in range(rounds):
            global_runner.run_multi(SQL_JOIN)
        full_ms = (time.perf_counter() - t0) / rounds * 1000

        print(f"\n  parse_only: {parse_ms:.3f} ms/req")
        print(f"  full pipeline: {full_ms:.3f} ms/req")
        print(f"  binder overhead: {full_ms - parse_ms:.3f} ms ({(full_ms/parse_ms - 1)*100:.1f}%)")
        assert full_ms < 100, f"Full pipeline too slow: {full_ms:.1f} ms"


# ── Benchmark: intent extraction ─────────────────────────────────────────────

class TestIntentBenchmark:

    def test_intent_extract(self, benchmark, global_runner):
        from birdeye.intent_extractor import IntentExtractor
        import json
        result = global_runner.run_multi(SQL_CTE)
        ast_dict = json.loads(result["json"])
        extractor = IntentExtractor()
        intents = benchmark(extractor.extract, ast_dict)
        assert len(intents) > 0

    def test_star_expand(self, benchmark, global_runner):
        from birdeye.intent_extractor import IntentExtractor
        import json
        result = global_runner.run_multi("SELECT * FROM SalesLT.Address")
        ast_dict = json.loads(result["json"])
        extractor = IntentExtractor()
        intents = extractor.extract(ast_dict)
        expanded = benchmark(extractor.expand_star_intents, intents, global_runner)
        assert any(i.get("column") for i in expanded)
