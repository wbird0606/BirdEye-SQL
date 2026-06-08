"""
BirdEye Web API Load Test
=========================

啟動方式（需先開 web server：python web/app.py）：

  # 互動式 Web UI（瀏覽器開 http://localhost:8089）
  locust -f locustfile.py --host http://127.0.0.1:5000

  # 無頭模式（CI / 自動化）
  locust -f locustfile.py --host http://127.0.0.1:5000 \
         --headless -u 20 -r 5 --run-time 60s \
         --html report_load.html

  # 快速冒煙：10 users, 30 秒
  locust -f locustfile.py --host http://127.0.0.1:5000 \
         --headless -u 10 -r 2 --run-time 30s

參數說明：
  -u  : 總虛擬使用者數 (users)
  -r  : 每秒新增使用者數 (spawn-rate)
  --run-time : 測試持續時間
  --html  : 產生 HTML 報告
"""
import json
import random
from locust import HttpUser, task, between, events


# ── Test SQL payload library ──────────────────────────────────────────────────

_PAYLOADS = {
    "simple": {
        "sql": "SELECT AddressID, AddressLine1, City, PostalCode FROM SalesLT.Address"
    },
    "top_n": {
        "sql": "SELECT TOP (100) CustomerID, FirstName, LastName FROM SalesLT.Customer ORDER BY CustomerID"
    },
    "aggregation": {
        "sql": (
            "SELECT CustomerID, COUNT(*) AS OrderCount, SUM(SubTotal) AS Total "
            "FROM SalesLT.SalesOrderHeader "
            "GROUP BY CustomerID HAVING COUNT(*) > 1 ORDER BY Total DESC"
        )
    },
    "join": {
        "sql": (
            "SELECT c.CustomerID, c.FirstName, soh.SalesOrderID, soh.SubTotal "
            "FROM SalesLT.Customer c "
            "JOIN SalesLT.SalesOrderHeader soh ON c.CustomerID = soh.CustomerID "
            "WHERE soh.SubTotal > 500"
        )
    },
    "window": {
        "sql": (
            "SELECT SalesOrderID, CustomerID, "
            "ROW_NUMBER() OVER (PARTITION BY CustomerID ORDER BY OrderDate) AS rn "
            "FROM SalesLT.SalesOrderHeader"
        )
    },
    "cte": {
        "sql": (
            "WITH TopCust AS ("
            "  SELECT CustomerID, SUM(SubTotal) AS Total "
            "  FROM SalesLT.SalesOrderHeader GROUP BY CustomerID"
            ") "
            "SELECT c.FirstName, c.LastName, t.Total "
            "FROM SalesLT.Customer c JOIN TopCust t ON c.CustomerID = t.CustomerID "
            "WHERE t.Total > 1000 ORDER BY t.Total DESC"
        )
    },
    "with_params": {
        "sql": "SELECT AddressID, City FROM SalesLT.Address WHERE PostalCode = @zip",
        "params": {"@zip": "98011"},
    },
}


# ── User profile: typical developer using the web UI ─────────────────────────

class TypicalUser(HttpUser):
    """
    模擬一般開發者使用頻率：多數是簡單查詢，偶爾做複雜分析。
    wait_time: 每個請求之間等 0.5~2 秒（模擬真實使用節奏）。
    """
    wait_time = between(0.5, 2.0)

    @task(5)
    def parse_simple(self):
        self.client.post("/api/parse", json=_PAYLOADS["simple"],
                         name="/api/parse [simple]")

    @task(3)
    def parse_join(self):
        self.client.post("/api/parse", json=_PAYLOADS["join"],
                         name="/api/parse [join]")

    @task(2)
    def parse_aggregation(self):
        self.client.post("/api/parse", json=_PAYLOADS["aggregation"],
                         name="/api/parse [aggregation]")

    @task(1)
    def parse_cte(self):
        self.client.post("/api/parse", json=_PAYLOADS["cte"],
                         name="/api/parse [cte]")

    @task(2)
    def parse_with_params(self):
        self.client.post("/api/parse", json=_PAYLOADS["with_params"],
                         name="/api/parse [params]")

    @task(1)
    def health_check(self):
        self.client.get("/health", name="/health")


# ── User profile: proxy/service (no wait, maximum throughput) ────────────────

class ProxyUser(HttpUser):
    """
    模擬 zta-proxy 呼叫模式：無停頓、持續打 /intents + /rewrite。
    用於測量服務的最大吞吐量上限。
    """
    wait_time = between(0, 0.1)

    @task(4)
    def intents_simple(self):
        self.client.post("/intents",
                         json={"sql": _PAYLOADS["simple"]["sql"], "db_id": 0},
                         name="/intents [simple]")

    @task(2)
    def intents_join(self):
        self.client.post("/intents",
                         json={"sql": _PAYLOADS["join"]["sql"], "db_id": 0},
                         name="/intents [join]")

    @task(1)
    def rewrite_no_filters(self):
        # 先取得 ast_json，再做 rewrite（模擬 proxy 兩步流程）
        resp = self.client.post(
            "/api/parse",
            json=_PAYLOADS["simple"],
            name="/api/parse [for rewrite]",
        )
        if resp.status_code == 200:
            ast_json = resp.json().get("result", {}).get("json", "")
            if ast_json:
                self.client.post("/rewrite",
                                 json={"ast_json": ast_json, "row_filters": []},
                                 name="/rewrite [no filters]")


# ── 壓力模式：快速 spike（用於找最大 QPS 和崩潰點）────────────────────────────

class SpikeUser(HttpUser):
    """
    無等待時間的極限模式。搭配 --users 50+ 使用，觀察錯誤率和 p99 延遲。
    只打最輕量的端點，排除 Python pipeline 瓶頸，純測 Flask 路由/序列化開銷。
    """
    wait_time = between(0, 0)

    @task
    def health(self):
        self.client.get("/health")


# ── Event hooks: 在 console 輸出關鍵統計 ─────────────────────────────────────

@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    stats = environment.stats
    total = stats.total
    if total.num_requests == 0:
        return
    print("\n" + "="*60)
    print(f"  Total requests : {total.num_requests:,}")
    print(f"  Failures       : {total.num_failures:,}  ({total.fail_ratio*100:.1f}%)")
    print(f"  RPS (avg)      : {total.avg_response_time and total.num_requests / max(total.total_response_time/1000, 1):.1f}")
    print(f"  Latency p50    : {total.get_response_time_percentile(0.5):.0f} ms")
    print(f"  Latency p95    : {total.get_response_time_percentile(0.95):.0f} ms")
    print(f"  Latency p99    : {total.get_response_time_percentile(0.99):.0f} ms")
    print("="*60)
