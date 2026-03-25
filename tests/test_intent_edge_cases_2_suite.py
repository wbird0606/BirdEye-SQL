"""
test_intent_edge_cases_2_suite.py
TDD: IntentExtractor edge cases — Issues #71~#73

  #71 Derived table 欄位無法追蹤，FROM 子查詢 alias 未加入 alias_map
  #72 DELETE 相關子查詢 WHERE 中的外層 table 參考無法解析
  #73 UPDATE SET RHS 子查詢的 intent 未被萃取
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
Customer,SalesPerson,nvarchar
Address,AddressID,int
Address,AddressLine1,nvarchar
Address,City,nvarchar
CustomerAddress,CustomerID,int
CustomerAddress,AddressID,int
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


# ── Issue #71 ─────────────────────────────────────────────────────────────────
# Derived table (subquery in FROM) 的欄位應追蹤至來源 table

def test_71_derived_table_where_filter_traced_to_source(runner):
    """d.OrderCount 在 WHERE 中 → 應追蹤到來源 SalesOrderHeader"""
    sql = (
        "SELECT c.FirstName "
        "FROM SalesLT.Customer c "
        "JOIN ("
        "  SELECT CustomerID, COUNT(*) AS OrderCount "
        "  FROM SalesLT.SalesOrderHeader "
        "  GROUP BY CustomerID"
        ") AS d ON c.CustomerID = d.CustomerID "
        "WHERE d.OrderCount > 5"
    )
    items = intents_of(runner, sql)
    # d.CustomerID (JOIN ON) → FILTER on SalesOrderHeader
    assert has_intent(items, "SalesOrderHeader", "CustomerID", "FILTER", "SalesLT"), \
        "d.CustomerID in JOIN ON should produce FILTER on SalesOrderHeader"


def test_71_derived_table_join_on_filter(runner):
    """JOIN ON c.CustomerID = d.CustomerID → 兩側欄位都應有 FILTER intent"""
    sql = (
        "SELECT c.FirstName "
        "FROM SalesLT.Customer c "
        "JOIN ("
        "  SELECT CustomerID, COUNT(*) AS OrderCount "
        "  FROM SalesLT.SalesOrderHeader "
        "  GROUP BY CustomerID"
        ") AS d ON c.CustomerID = d.CustomerID "
        "WHERE d.OrderCount > 5"
    )
    items = intents_of(runner, sql)
    # c.CustomerID (JOIN ON) → FILTER on Customer
    assert has_intent(items, "Customer", "CustomerID", "FILTER", "SalesLT"), \
        "c.CustomerID in JOIN ON should produce FILTER on Customer"


def test_71_derived_table_inner_columns_extracted(runner):
    """Derived table 內部的 SELECT、GROUP BY 欄位應正常萃取"""
    sql = (
        "SELECT c.FirstName "
        "FROM SalesLT.Customer c "
        "JOIN ("
        "  SELECT CustomerID, COUNT(*) AS OrderCount "
        "  FROM SalesLT.SalesOrderHeader "
        "  GROUP BY CustomerID"
        ") AS d ON c.CustomerID = d.CustomerID "
        "WHERE d.OrderCount > 5"
    )
    items = intents_of(runner, sql)
    # 內部 GROUP BY CustomerID → FILTER on SalesOrderHeader
    assert has_intent(items, "SalesOrderHeader", "CustomerID", "FILTER", "SalesLT"), \
        "GROUP BY CustomerID inside derived table should produce FILTER on SalesOrderHeader"


# ── Issue #72 ─────────────────────────────────────────────────────────────────
# DELETE 相關子查詢中的外層 table 參考應能解析

def test_72_delete_correlated_subquery_outer_ref_filter(runner):
    """子查詢 WHERE ca.AddressID = Address.AddressID → Address.AddressID 應有 FILTER"""
    sql = (
        "DELETE FROM SalesLT.Address "
        "WHERE AddressID IN ("
        "  SELECT AddressID FROM SalesLT.CustomerAddress ca "
        "  WHERE ca.AddressID = Address.AddressID"
        ")"
    )
    items = intents_of(runner, sql)
    assert has_intent(items, "Address", "AddressID", "FILTER", "SalesLT"), \
        "Correlated Address.AddressID in DELETE subquery should produce FILTER on Address"


def test_72_delete_correlated_subquery_inner_filter(runner):
    """子查詢內部 ca.AddressID → FILTER on CustomerAddress"""
    sql = (
        "DELETE FROM SalesLT.Address "
        "WHERE AddressID IN ("
        "  SELECT AddressID FROM SalesLT.CustomerAddress ca "
        "  WHERE ca.AddressID = Address.AddressID"
        ")"
    )
    items = intents_of(runner, sql)
    assert has_intent(items, "CustomerAddress", "AddressID", "FILTER", "SalesLT"), \
        "Inner ca.AddressID should produce FILTER on CustomerAddress"


def test_72_delete_outer_where_still_extracted(runner):
    """DELETE 外層 WHERE AddressID → FILTER on Address"""
    sql = (
        "DELETE FROM SalesLT.Address "
        "WHERE AddressID IN ("
        "  SELECT AddressID FROM SalesLT.CustomerAddress ca "
        "  WHERE ca.AddressID = Address.AddressID"
        ")"
    )
    items = intents_of(runner, sql)
    # 外層 WHERE AddressID（非限定）→ Address（單表）→ FILTER
    assert has_intent(items, "Address", "AddressID", "FILTER", "SalesLT"), \
        "Outer WHERE AddressID should produce FILTER on Address"


# ── Issue #73 ─────────────────────────────────────────────────────────────────
# UPDATE SET RHS 子查詢中的外層 table 參考應能解析

_SQL_73 = (
    "UPDATE SalesLT.Customer "
    "SET SalesPerson = ("
    "  SELECT TOP 1 SalesPerson "
    "  FROM SalesLT.Customer c2 "
    "  WHERE c2.CustomerID < 100"
    ") "
    "WHERE CustomerID = 10"
)


def test_73_update_set_rhs_subquery_inner_filter(runner):
    """SET RHS 子查詢 WHERE c2.CustomerID → FILTER on Customer.CustomerID"""
    items = intents_of(runner, _SQL_73)
    assert has_intent(items, "Customer", "CustomerID", "FILTER", "SalesLT"), \
        "c2.CustomerID in UPDATE subquery WHERE should produce FILTER on Customer"


def test_73_update_set_column_is_update(runner):
    """SET SalesPerson → UPDATE on Customer.SalesPerson"""
    items = intents_of(runner, _SQL_73)
    assert has_intent(items, "Customer", "SalesPerson", "UPDATE", "SalesLT"), \
        "SET SalesPerson should produce UPDATE on Customer.SalesPerson"


def test_73_update_outer_where_filter(runner):
    """UPDATE 外層 WHERE CustomerID = 10 → FILTER on Customer.CustomerID"""
    items = intents_of(runner, _SQL_73)
    assert has_intent(items, "Customer", "CustomerID", "FILTER", "SalesLT"), \
        "Outer WHERE CustomerID should produce FILTER on Customer"
