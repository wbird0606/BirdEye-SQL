"""
test_74_star_intent_suite.py
TDD: Issue #74 — COUNT(*) / SELECT * 應展開成所有欄位的 READ intent

問題：
  - SELECT COUNT(*) 和 SELECT * 不產生欄位層級 intent
  - Permission API 無法逐欄比對，查詢直接送到 SQL Server
  - SQL Server 欄位層級安全性才攔截，屬於 ZTA bypass

修法：
  - IntentExtractor.expand_star_intents(intents, runner)
    將 column=None 的 READ intent 展開成各欄位的 READ intent
"""

import io
import json
import pytest
from birdeye.runner import BirdEyeRunner
from birdeye.intent_extractor import IntentExtractor

_CSV = """\
table_name,column_name,data_type
Customer,CustomerID,int
Customer,FirstName,nvarchar
Customer,LastName,nvarchar
Customer,EmailAddress,nvarchar
Customer,Phone,nvarchar
Address,AddressID,int
Address,City,nvarchar
"""

@pytest.fixture(scope="module")
def runner():
    r = BirdEyeRunner()
    r.load_metadata_from_csv(io.StringIO(_CSV))
    return r


def expanded_intents(runner, sql):
    result   = runner.run(sql)
    ast_dict = json.loads(result["json"])
    intents  = IntentExtractor().extract(ast_dict)
    return IntentExtractor().expand_star_intents(intents, runner)


def has_intent(intents, table, column, intent):
    return any(
        i["table"].upper() == table.upper() and
        (i["column"] or "").upper() == (column or "").upper() and
        i["intent"] == intent
        for i in intents
    )


# ── COUNT(*) ──────────────────────────────────────────────────────────────────

def test_74_count_star_expands_all_columns(runner):
    """COUNT(*) 應展開成 Customer 所有欄位的 READ intent"""
    items = expanded_intents(runner, "SELECT COUNT(*) AS Total FROM SalesLT.Customer")
    assert has_intent(items, "Customer", "CustomerID",    "READ")
    assert has_intent(items, "Customer", "FirstName",     "READ")
    assert has_intent(items, "Customer", "EmailAddress",  "READ")
    assert has_intent(items, "Customer", "Phone",         "READ")


def test_74_count_star_no_none_column(runner):
    """展開後不應有 column=None 的 READ intent"""
    items = expanded_intents(runner, "SELECT COUNT(*) AS Total FROM SalesLT.Customer")
    star_reads = [i for i in items if i["table"] == "Customer" and i["intent"] == "READ" and i["column"] is None]
    assert star_reads == [], f"Should not have column=None READ, got: {star_reads}"


# ── SELECT * ──────────────────────────────────────────────────────────────────

def test_74_select_star_expands_all_columns(runner):
    """SELECT * 應展開成 Customer 所有欄位的 READ intent"""
    items = expanded_intents(runner, "SELECT * FROM SalesLT.Customer")
    assert has_intent(items, "Customer", "CustomerID",    "READ")
    assert has_intent(items, "Customer", "FirstName",     "READ")
    assert has_intent(items, "Customer", "EmailAddress",  "READ")
    assert has_intent(items, "Customer", "Phone",         "READ")


def test_74_select_star_no_none_column(runner):
    """SELECT * 展開後不應有 column=None 的 READ"""
    items = expanded_intents(runner, "SELECT * FROM SalesLT.Customer")
    star_reads = [i for i in items if i["table"] == "Customer" and i["intent"] == "READ" and i["column"] is None]
    assert star_reads == [], f"Should not have column=None READ, got: {star_reads}"


# ── 正常 SELECT 不受影響 ───────────────────────────────────────────────────────

def test_74_specific_column_select_unchanged(runner):
    """指定欄位的 SELECT 不應受 expand 影響"""
    items = expanded_intents(runner, "SELECT FirstName, LastName FROM SalesLT.Customer")
    assert has_intent(items, "Customer", "FirstName",  "READ")
    assert has_intent(items, "Customer", "LastName",   "READ")
    # EmailAddress 沒被 SELECT，不應出現
    assert not has_intent(items, "Customer", "EmailAddress", "READ"), \
        "EmailAddress should not appear for specific column SELECT"


# ── COUNT(*) with JOIN ────────────────────────────────────────────────────────

def test_74_count_star_with_join_expands_both_tables(runner):
    """COUNT(*) JOIN 時兩個 table 都應展開"""
    sql = ("SELECT COUNT(*) FROM SalesLT.Customer c "
           "JOIN SalesLT.Address a ON c.CustomerID = a.AddressID")
    items = expanded_intents(runner, sql)
    assert has_intent(items, "Customer", "EmailAddress", "READ")
    assert has_intent(items, "Address",  "City",         "READ")
