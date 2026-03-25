"""
test_all_cases_intent_suite.py — 對應 ZTA test_all_cases.py 的 BirdEye intent 驗證
對每個 SQL 案例確認 intent 提取結果：
  - 預期 200（允許）：intents 不含 Customer.EmailAddress / Customer.Phone
  - 預期 403（禁止）：intents 含有 Customer.EmailAddress 或 Customer.Phone
    或 SELECT * / COUNT(*) 展開後含禁止欄位
"""

from __future__ import annotations
import json
import pytest

from birdeye.intent_extractor import IntentExtractor
from birdeye.reconstructor import ASTReconstructor

# ── 禁止欄位定義（對應真實權限設定）────────────────────────────────────────────
DENIED = {("SalesLT", "Customer", "EmailAddress"),
          ("SalesLT", "Customer", "Phone"),
          ("SalesLT", "Customer", "EMAILADDRESS"),
          ("SalesLT", "Customer", "PHONE")}

# ── 測試案例（與 ZTA test_all_cases.py 同步） ─────────────────────────────────
# (名稱, SQL, params_placeholder已替換, 預期 HTTP)
# params 已 inline 替換 ? → 具體值，供 BirdEye parser 解析
TEST_CASES = [
    # C1 Customer 單欄位
    ("C1-01", "SELECT CustomerID, FirstName, LastName FROM SalesLT.Customer", 200),
    ("C1-02", "SELECT EmailAddress FROM SalesLT.Customer", 403),
    ("C1-03", "SELECT Phone FROM SalesLT.Customer", 403),
    ("C1-04", "SELECT CustomerID, FirstName, EmailAddress FROM SalesLT.Customer", 403),
    ("C1-05", "SELECT CustomerID, FirstName, Phone FROM SalesLT.Customer", 403),
    ("C1-06", "SELECT EmailAddress, Phone FROM SalesLT.Customer", 403),
    ("C1-07", "SELECT * FROM SalesLT.Customer", 403),
    # C2 Address
    ("C2-01", "SELECT AddressID, AddressLine1, City FROM SalesLT.Address", 200),
    ("C2-02", "SELECT * FROM SalesLT.Address", 200),
    # C3 TOP N
    ("C3-01", "SELECT TOP 5 CustomerID, FirstName FROM SalesLT.Customer", 200),
    ("C3-02", "SELECT TOP 5 CustomerID, EmailAddress FROM SalesLT.Customer", 403),
    ("C3-03", "SELECT TOP 3 AddressID, City FROM SalesLT.Address", 200),
    # C4 WHERE (? 已替換)
    ("C4-01", "SELECT CustomerID, FirstName FROM SalesLT.Customer WHERE CustomerID > 10", 200),
    ("C4-02", "SELECT CustomerID, EmailAddress FROM SalesLT.Customer WHERE CustomerID > 10", 403),
    ("C4-03", "SELECT CustomerID, FirstName FROM SalesLT.Customer WHERE CustomerID = 1", 200),
    ("C4-04", "SELECT CustomerID, EmailAddress FROM SalesLT.Customer WHERE CustomerID = 1", 403),
    ("C4-05", "SELECT CustomerID, FirstName FROM SalesLT.Customer WHERE FirstName = 'Keith'", 200),
    ("C4-06", "SELECT CustomerID, FirstName FROM SalesLT.Customer WHERE CustomerID > 1 AND CustomerID < 100", 200),
    # C5 COUNT
    ("C5-01", "SELECT COUNT(*) AS Total FROM SalesLT.Customer", 403),
    ("C5-02", "SELECT COUNT(*) AS Total FROM SalesLT.Address", 200),
    ("C5-03", "SELECT COUNT(CustomerID) AS Total FROM SalesLT.Customer", 200),
    ("C5-04", "SELECT COUNT(EmailAddress) AS Total FROM SalesLT.Customer", 403),
    ("C5-05", "SELECT COUNT(*) AS Total FROM SalesLT.Customer WHERE CustomerID > 10", 403),
    ("C5-06", "SELECT COUNT(*) AS Total FROM SalesLT.Address WHERE City = 'Seattle'", 200),
    # C6 JOIN
    ("C6-01",
     "SELECT c.FirstName, a.City FROM SalesLT.Customer c "
     "JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID "
     "JOIN SalesLT.Address a ON ca.AddressID = a.AddressID", 200),
    ("C6-02",
     "SELECT c.EmailAddress, a.City FROM SalesLT.Customer c "
     "JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID "
     "JOIN SalesLT.Address a ON ca.AddressID = a.AddressID", 403),
    ("C6-03",
     "SELECT a.AddressID, a.City, a.StateProvince FROM SalesLT.Customer c "
     "JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID "
     "JOIN SalesLT.Address a ON ca.AddressID = a.AddressID", 200),
    ("C6-04",
     "SELECT TOP 3 c.FirstName, a.City FROM SalesLT.Customer c "
     "JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID "
     "JOIN SalesLT.Address a ON ca.AddressID = a.AddressID", 200),
    # C7 ORDER BY / DISTINCT / GROUP BY
    ("C7-01", "SELECT CustomerID, FirstName FROM SalesLT.Customer ORDER BY FirstName", 200),
    ("C7-02", "SELECT CustomerID, EmailAddress FROM SalesLT.Customer ORDER BY EmailAddress", 403),
    ("C7-03", "SELECT DISTINCT City FROM SalesLT.Address", 200),
    ("C7-04", "SELECT DISTINCT EmailAddress FROM SalesLT.Customer", 403),
    ("C7-05", "SELECT City, COUNT(*) AS Total FROM SalesLT.Address GROUP BY City", 200),
    ("C7-06", "SELECT CompanyName, COUNT(*) AS Total FROM SalesLT.Customer GROUP BY CompanyName", 403),
    ("C7-07", "SELECT EmailAddress, COUNT(*) AS Total FROM SalesLT.Customer GROUP BY EmailAddress", 403),
]


def _extract_intents(sql: str, global_runner) -> list[dict]:
    """執行完整 pipeline 並展開 star intents。"""
    result   = global_runner.run(sql)
    ast_dict = json.loads(result['json'])
    intents  = IntentExtractor().extract(ast_dict)
    intents  = IntentExtractor().expand_star_intents(intents, global_runner)
    return intents


def _has_denied(intents: list[dict]) -> bool:
    """檢查 intents 是否包含任何禁止欄位。"""
    for i in intents:
        key = (i.get("schema"), i.get("table"), i.get("column"))
        if key in DENIED:
            return True
    return False


@pytest.mark.parametrize("name,sql,expected_http", TEST_CASES, ids=[c[0] for c in TEST_CASES])
def test_intent(name, sql, expected_http, global_runner):
    intents     = _extract_intents(sql, global_runner)
    has_denied  = _has_denied(intents)
    should_deny = expected_http == 403

    assert has_denied == should_deny, (
        f"\n  SQL          : {sql}\n"
        f"  期望禁止     : {should_deny}\n"
        f"  實際含禁止   : {has_denied}\n"
        f"  intents      : {['.'.join([i['schema'], i['table'], str(i['column'])]) for i in intents]}"
    )
