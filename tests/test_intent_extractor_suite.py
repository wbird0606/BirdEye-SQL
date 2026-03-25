"""
test_intent_extractor_suite.py
TDD: IntentExtractor — 欄位層級意圖萃取測試套件

涵蓋場景：
  1.  Simple SELECT        → READ
  2.  SELECT with WHERE    → READ + FILTER
  3.  SELECT *             → table-level READ
  4.  JOIN ON              → FILTER (推理攻擊防範)
  5.  GROUP BY / HAVING    → FILTER
  6.  ORDER BY             → FILTER
  7.  INSERT with columns  → INSERT
  8.  INSERT without cols  → table-level INSERT
  9.  UPDATE SET           → UPDATE + FILTER
  10. DELETE               → table-level DELETE + FILTER
  11. CASE WHEN            → 繼承父 intent
  12. Subquery in WHERE    → 子查詢 READ
  13. CTE                  → CTE 本身不重複計入，內部 SELECT 正常萃取
  14. UNION                → 兩側各自萃取
  15. INSERT-SELECT        → INSERT + 來源 READ
  16. Alias resolution     → alias 正確對應 schema.table
"""

import io
import json
import pytest
from birdeye.runner import BirdEyeRunner
from birdeye.intent_extractor import IntentExtractor

# ── 測試用 Schema Metadata ────────────────────────────────────────────────────
# 提供剛好能通過 Binder 驗證的最小欄位清單，
# 模擬 ZTA 實際場景（metadata 來自目標 DB）。
_TEST_METADATA_CSV = """\
table_name,column_name,data_type
Customer,CustomerID,int
Customer,FirstName,nvarchar
Customer,LastName,nvarchar
Customer,EmailAddress,nvarchar
Customer,Phone,nvarchar
Customer,SalesPerson,nvarchar
CustomerAddress,CustomerID,int
CustomerAddress,AddressID,int
Address,AddressID,int
Address,AddressLine1,nvarchar
Address,AddressLine2,nvarchar
Address,City,nvarchar
Address,StateProvince,nvarchar
Address,PostalCode,nvarchar
SalesOrderHeader,SalesOrderID,int
SalesOrderHeader,CustomerID,int
SalesOrderHeader,TotalDue,money
"""

# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def runner():
    r = BirdEyeRunner()
    r.load_metadata_from_csv(io.StringIO(_TEST_METADATA_CSV))
    return r


def intents_of(runner, sql):
    result   = runner.run(sql)                              # 完整 pipeline（含 binder）
    ast_dict = json.loads(result['json'])
    return IntentExtractor().extract(ast_dict)


def has_intent(intents, table, column, intent, schema=None):
    for i in intents:
        if i['table'] == table and i['column'] == column and i['intent'] == intent:
            if schema is None or i['schema'] == schema:
                return True
    return False


# ── 1. Simple SELECT ──────────────────────────────────────────────────────────

def test_select_columns_read(runner):
    sql = "SELECT FirstName, LastName FROM SalesLT.Customer"
    items = intents_of(runner, sql)
    assert has_intent(items, 'Customer', 'FirstName', 'READ', 'SalesLT')
    assert has_intent(items, 'Customer', 'LastName',  'READ', 'SalesLT')


# ── 2. SELECT with WHERE ──────────────────────────────────────────────────────

def test_where_column_is_filter(runner):
    sql = "SELECT FirstName FROM SalesLT.Customer WHERE CustomerID = 1"
    items = intents_of(runner, sql)
    assert has_intent(items, 'Customer', 'FirstName',  'READ',   'SalesLT')
    assert has_intent(items, 'Customer', 'CustomerID', 'FILTER', 'SalesLT')
    # CustomerID 不應出現在 READ（WHERE 不是投影）
    assert not has_intent(items, 'Customer', 'CustomerID', 'READ')


# ── 3. SELECT * ───────────────────────────────────────────────────────────────

def test_select_star_table_level_read(runner):
    sql = "SELECT * FROM SalesLT.Customer"
    items = intents_of(runner, sql)
    # #74 後 SELECT * 展開為 per-column intent
    customer_reads = [i for i in items if i["table"] == "Customer" and i["intent"] == "READ" and i["schema"] == "SalesLT"]
    assert len(customer_reads) > 0, "SELECT * should produce READ intents for Customer columns"


# ── 4. JOIN ON ────────────────────────────────────────────────────────────────

def test_join_on_is_filter(runner):
    sql = """
        SELECT c.FirstName, a.AddressLine1
        FROM SalesLT.Customer AS c
        JOIN SalesLT.CustomerAddress AS ca ON c.CustomerID = ca.CustomerID
        JOIN SalesLT.Address AS a ON ca.AddressID = a.AddressID
    """
    items = intents_of(runner, sql)
    assert has_intent(items, 'Customer', 'FirstName',   'READ')
    assert has_intent(items, 'Address',  'AddressLine1','READ')
    # JOIN ON 欄位 → FILTER
    assert has_intent(items, 'Customer',        'CustomerID', 'FILTER')
    assert has_intent(items, 'CustomerAddress', 'CustomerID', 'FILTER')
    assert has_intent(items, 'CustomerAddress', 'AddressID',  'FILTER')
    assert has_intent(items, 'Address',         'AddressID',  'FILTER')


# ── 5. GROUP BY / HAVING ──────────────────────────────────────────────────────

def test_group_by_having_is_filter(runner):
    sql = """
        SELECT CustomerID
        FROM SalesLT.SalesOrderHeader
        GROUP BY CustomerID
        HAVING COUNT(*) > 1
    """
    items = intents_of(runner, sql)
    assert has_intent(items, 'SalesOrderHeader', 'CustomerID', 'READ')
    assert has_intent(items, 'SalesOrderHeader', 'CustomerID', 'FILTER')


# ── 6. ORDER BY ───────────────────────────────────────────────────────────────

def test_order_by_is_filter(runner):
    sql = "SELECT FirstName FROM SalesLT.Customer ORDER BY LastName"
    items = intents_of(runner, sql)
    assert has_intent(items, 'Customer', 'FirstName', 'READ')
    assert has_intent(items, 'Customer', 'LastName',  'FILTER')


# ── 7. INSERT with columns ────────────────────────────────────────────────────

def test_insert_with_columns(runner):
    sql = "INSERT INTO SalesLT.Address (AddressLine1, City) VALUES ('123 St', 'NYC')"
    items = intents_of(runner, sql)
    assert has_intent(items, 'Address', 'AddressLine1', 'INSERT', 'SalesLT')
    assert has_intent(items, 'Address', 'City',         'INSERT', 'SalesLT')


# ── 8. TRUNCATE → table-level DELETE ─────────────────────────────────────────

def test_truncate_table_level_delete(runner):
    # TRUNCATE 無欄位清單，直接對整個資料表操作 → DELETE intent
    sql = "TRUNCATE TABLE SalesLT.Address"
    items = intents_of(runner, sql)
    assert has_intent(items, 'Address', None, 'DELETE', 'SalesLT')


# ── 9. UPDATE SET ─────────────────────────────────────────────────────────────

def test_update_set_is_update_where_is_filter(runner):
    sql = "UPDATE SalesLT.Address SET City = 'Boston' WHERE AddressID = 5"
    items = intents_of(runner, sql)
    assert has_intent(items, 'Address', 'City',      'UPDATE', 'SalesLT')
    assert has_intent(items, 'Address', 'AddressID', 'FILTER', 'SalesLT')
    assert not has_intent(items, 'Address', 'City', 'READ')


# ── 10. DELETE ────────────────────────────────────────────────────────────────

def test_delete_table_level_and_filter(runner):
    sql = "DELETE FROM SalesLT.Address WHERE AddressID = 5"
    items = intents_of(runner, sql)
    assert has_intent(items, 'Address', None,        'DELETE', 'SalesLT')
    assert has_intent(items, 'Address', 'AddressID', 'FILTER', 'SalesLT')


# ── 11. CASE WHEN ─────────────────────────────────────────────────────────────

def test_case_when_inherits_parent_intent(runner):
    sql = """
        SELECT CASE WHEN SalesPerson IS NULL THEN 'Unknown' ELSE SalesPerson END
        FROM SalesLT.Customer
    """
    items = intents_of(runner, sql)
    assert has_intent(items, 'Customer', 'SalesPerson', 'READ')


# ── 12. Subquery in WHERE ─────────────────────────────────────────────────────

def test_subquery_in_where(runner):
    sql = """
        SELECT FirstName FROM SalesLT.Customer
        WHERE CustomerID IN (
            SELECT CustomerID FROM SalesLT.SalesOrderHeader WHERE TotalDue > 100
        )
    """
    items = intents_of(runner, sql)
    assert has_intent(items, 'Customer',        'FirstName',  'READ')
    assert has_intent(items, 'Customer',        'CustomerID', 'FILTER')
    # 子查詢內部
    assert has_intent(items, 'SalesOrderHeader','CustomerID', 'READ')
    assert has_intent(items, 'SalesOrderHeader','TotalDue',   'FILTER')


# ── 13. CTE ───────────────────────────────────────────────────────────────────

def test_cte_inner_intents_extracted(runner):
    sql = """
        WITH TopCustomers AS (
            SELECT CustomerID FROM SalesLT.Customer WHERE CustomerID < 100
        )
        SELECT CustomerID FROM TopCustomers
    """
    items = intents_of(runner, sql)
    # CTE 定義內部的欄位必須被萃取
    assert has_intent(items, 'Customer', 'CustomerID', 'READ')
    assert has_intent(items, 'Customer', 'CustomerID', 'FILTER')
    # CTE 本身（TopCustomers）不應被當作真實資料表
    tables = {i['table'] for i in items}
    assert 'TopCustomers' not in tables


# ── 14. UNION ─────────────────────────────────────────────────────────────────

def test_union_both_sides_extracted(runner):
    sql = """
        SELECT FirstName FROM SalesLT.Customer
        UNION
        SELECT FirstName FROM SalesLT.Customer WHERE CustomerID = 1
    """
    items = intents_of(runner, sql)
    assert has_intent(items, 'Customer', 'FirstName',  'READ')
    assert has_intent(items, 'Customer', 'CustomerID', 'FILTER')


# ── 15. INSERT-SELECT ─────────────────────────────────────────────────────────

def test_insert_select_read_and_insert(runner):
    sql = """
        INSERT INTO SalesLT.Address (AddressLine1, City)
        SELECT AddressLine1, City FROM SalesLT.Address WHERE StateProvince = 'WA'
    """
    items = intents_of(runner, sql)
    assert has_intent(items, 'Address', 'AddressLine1',  'INSERT')
    assert has_intent(items, 'Address', 'City',          'INSERT')
    assert has_intent(items, 'Address', 'AddressLine1',  'READ')
    assert has_intent(items, 'Address', 'City',          'READ')
    assert has_intent(items, 'Address', 'StateProvince', 'FILTER')


# ── 16. Alias resolution ──────────────────────────────────────────────────────

def test_alias_resolves_to_real_schema_table(runner):
    sql = "SELECT c.FirstName FROM SalesLT.Customer AS c WHERE c.CustomerID = 1"
    items = intents_of(runner, sql)
    assert has_intent(items, 'Customer', 'FirstName',  'READ',   'SalesLT')
    assert has_intent(items, 'Customer', 'CustomerID', 'FILTER', 'SalesLT')
