"""
test_intent_edge_cases_suite.py
TDD: IntentExtractor edge cases — Issues #67~#70

  #67 多表 JOIN 中非限定欄位被靜默跳過
  #68 SELECT * 多表 JOIN 應對每個 table 各產生一筆 READ
  #69 SELECT 欄位中的相關子查詢無法解析外層 alias
  #70 CROSS APPLY 中的橫向參考無法解析外層 alias
"""

import io
import json
import pytest
from birdeye.runner import BirdEyeRunner
from birdeye.intent_extractor import IntentExtractor

# ── Schema ────────────────────────────────────────────────────────────────────

_CSV = """\
table_name,column_name,data_type
Customer,CustomerID,int
Customer,FirstName,nvarchar
Customer,LastName,nvarchar
Customer,SalesPerson,nvarchar
Address,AddressID,int
Address,AddressLine1,nvarchar
Address,City,nvarchar
SalesOrderHeader,SalesOrderID,int
SalesOrderHeader,CustomerID,int
SalesOrderHeader,TotalDue,money
"""

@pytest.fixture(scope="module")
def runner():
    r = BirdEyeRunner()
    r.load_metadata_from_csv(io.StringIO(_CSV))
    return r


def intents_of(runner, sql):
    result   = runner.run(sql)
    ast_dict = json.loads(result["json"])
    return IntentExtractor().extract(ast_dict)


def has_intent(intents, table, column, intent, schema=None):
    for i in intents:
        if i["table"] == table and i["column"] == column and i["intent"] == intent:
            if schema is None or i["schema"] == schema:
                return True
    return False


# ── Issue #67 ─────────────────────────────────────────────────────────────────
# 多表 JOIN 中非限定欄位應保留 intent（table=None），不能靜默丟棄

def test_67_unqualified_column_in_join_where_produces_filter(runner):
    """WHERE City = 'Seattle' — City 未加 qualifier，應產生 FILTER intent（即使 table 無法確定）"""
    sql = ("SELECT c.FirstName FROM SalesLT.Customer c "
           "JOIN SalesLT.Address a ON c.CustomerID = a.AddressID "
           "WHERE City = 'Seattle'")
    items = intents_of(runner, sql)
    # City 來自 Address，binder 可解析；應有 FILTER
    assert has_intent(items, "Address", "City", "FILTER", "SalesLT"), \
        "City should resolve to Address.City and produce FILTER intent"


def test_67_unqualified_column_in_join_select_produces_read(runner):
    """SELECT FirstName（非限定）在單表時應正確歸屬"""
    sql = ("SELECT FirstName FROM SalesLT.Customer c "
           "JOIN SalesLT.Address a ON c.CustomerID = a.AddressID")
    items = intents_of(runner, sql)
    # FirstName 只存在於 Customer，binder 解析後應歸屬 Customer
    assert has_intent(items, "Customer", "FirstName", "READ", "SalesLT"), \
        "FirstName should resolve to Customer.FirstName and produce READ intent"


# ── Issue #68 ─────────────────────────────────────────────────────────────────
# SELECT * 多表 JOIN 應對每張 table 各產生 table-level READ

def test_68_select_star_multi_join_reads_all_tables(runner):
    """SELECT * FROM Customer JOIN Address → 兩張 table 各一筆 READ"""
    sql = ("SELECT * FROM SalesLT.Customer c "
           "JOIN SalesLT.Address a ON c.CustomerID = a.AddressID")
    items = intents_of(runner, sql)
    assert has_intent(items, "Customer", None, "READ", "SalesLT"), \
        "SELECT * should produce table-level READ for Customer"
    assert has_intent(items, "Address", None, "READ", "SalesLT"), \
        "SELECT * should produce table-level READ for Address"


def test_68_select_star_three_way_join_reads_all_tables(runner):
    """SELECT * FROM 三表 JOIN → 三張 table 各一筆 READ"""
    sql = ("SELECT * FROM SalesLT.Customer c "
           "JOIN SalesLT.Address a ON c.CustomerID = a.AddressID "
           "JOIN SalesLT.SalesOrderHeader s ON c.CustomerID = s.CustomerID")
    items = intents_of(runner, sql)
    assert has_intent(items, "Customer",         None, "READ", "SalesLT")
    assert has_intent(items, "Address",          None, "READ", "SalesLT")
    assert has_intent(items, "SalesOrderHeader", None, "READ", "SalesLT")


# ── Issue #69 ─────────────────────────────────────────────────────────────────
# SELECT 欄位中的相關子查詢應能解析外層 alias

def test_69_correlated_subquery_in_select_outer_alias_filter(runner):
    """SELECT (SELECT COUNT(*) FROM Orders WHERE CustomerID = c.CustomerID)
       — c.CustomerID 應產生 FILTER intent 歸屬 Customer"""
    sql = ("SELECT c.FirstName, "
           "(SELECT COUNT(*) FROM SalesLT.SalesOrderHeader soh "
           " WHERE soh.CustomerID = c.CustomerID) AS order_count "
           "FROM SalesLT.Customer c")
    items = intents_of(runner, sql)
    # 外層 c.CustomerID 在子查詢 WHERE 中 → FILTER on Customer
    assert has_intent(items, "Customer", "CustomerID", "FILTER", "SalesLT"), \
        "Correlated reference c.CustomerID should produce FILTER on Customer"


def test_69_correlated_subquery_inner_table_also_extracted(runner):
    """相關子查詢內部的欄位也應被萃取"""
    sql = ("SELECT c.FirstName, "
           "(SELECT COUNT(*) FROM SalesLT.SalesOrderHeader soh "
           " WHERE soh.CustomerID = c.CustomerID) AS order_count "
           "FROM SalesLT.Customer c")
    items = intents_of(runner, sql)
    # 子查詢內部 soh.CustomerID → FILTER on SalesOrderHeader
    assert has_intent(items, "SalesOrderHeader", "CustomerID", "FILTER", "SalesLT"), \
        "Inner subquery column soh.CustomerID should produce FILTER on SalesOrderHeader"


# ── Issue #70 ─────────────────────────────────────────────────────────────────
# CROSS APPLY 子查詢應能解析外層 alias

def test_70_cross_apply_outer_alias_filter(runner):
    """CROSS APPLY WHERE soh.CustomerID = c.CustomerID
       — c.CustomerID 應產生 FILTER intent 歸屬 Customer"""
    sql = ("SELECT c.FirstName, sub.SalesOrderID "
           "FROM SalesLT.Customer c "
           "CROSS APPLY ("
           "  SELECT TOP 1 SalesOrderID "
           "  FROM SalesLT.SalesOrderHeader soh "
           "  WHERE soh.CustomerID = c.CustomerID"
           ") sub")
    items = intents_of(runner, sql)
    assert has_intent(items, "Customer", "CustomerID", "FILTER", "SalesLT"), \
        "CROSS APPLY lateral reference c.CustomerID should produce FILTER on Customer"


def test_70_cross_apply_inner_columns_extracted(runner):
    """CROSS APPLY 內部欄位應正常萃取"""
    sql = ("SELECT c.FirstName, sub.SalesOrderID "
           "FROM SalesLT.Customer c "
           "CROSS APPLY ("
           "  SELECT TOP 1 SalesOrderID "
           "  FROM SalesLT.SalesOrderHeader soh "
           "  WHERE soh.CustomerID = c.CustomerID"
           ") sub")
    items = intents_of(runner, sql)
    assert has_intent(items, "SalesOrderHeader", "CustomerID", "FILTER", "SalesLT"), \
        "Inner APPLY column soh.CustomerID should produce FILTER on SalesOrderHeader"
    assert has_intent(items, "SalesOrderHeader", "SalesOrderID", "READ", "SalesLT"), \
        "Inner APPLY SELECT column SalesOrderID should produce READ"
