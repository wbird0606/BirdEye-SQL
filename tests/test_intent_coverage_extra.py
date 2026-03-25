"""
test_intent_coverage_extra.py
Second-round coverage for intent_extractor.py remaining missing lines:
  95-96, 107, 120, 122, 124, 161, 164-165, 168-172, 178,
  276, 281, 299, 304, 314, 384-388, 404, 432, 453, 487
"""
import json
import pytest
from birdeye.intent_extractor import IntentExtractor
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.serializer import ASTSerializer


def parse_only(sql: str) -> dict:
    tokens = Lexer(sql).tokenize()
    ast = Parser(tokens, sql).parse()
    return json.loads(ASTSerializer().to_json(ast))


def has_intent(intents, table, column, intent, schema=None):
    for i in intents:
        if i["table"] == table and i["column"] == column and i["intent"] == intent:
            if schema is None or i["schema"] == schema:
                return True
    return False


# ── Lines 95-96: _collect_tables for CTE in SELECT ───────────────────────────

def test_collect_tables_cte_query():
    sql = ("WITH cte AS (SELECT CustomerID FROM SalesLT.Customer) "
           "SELECT CustomerID FROM cte")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t == "Customer" for _, t in tables)


# ── Line 107: _collect_tables derived table in FROM ──────────────────────────

def test_collect_tables_derived_table_from():
    sql = ("SELECT sub.CustomerID "
           "FROM (SELECT CustomerID FROM SalesLT.Customer) sub")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t == "Customer" for _, t in tables)


# ── Line 120: _collect_tables GROUP BY traversal ─────────────────────────────

def test_collect_tables_group_by_traversal():
    sql = ("SELECT CustomerID, COUNT(*) FROM SalesLT.Customer "
           "GROUP BY CustomerID")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t == "Customer" for _, t in tables)


# ── Line 122: _collect_tables ORDER BY traversal ─────────────────────────────

def test_collect_tables_order_by_traversal():
    sql = "SELECT CustomerID FROM SalesLT.Customer ORDER BY CustomerID"
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t == "Customer" for _, t in tables)


# ── Line 124: _collect_tables APPLY subquery traversal ───────────────────────

def test_collect_tables_apply_traversal():
    sql = ("SELECT c.CustomerID, sub.x "
           "FROM SalesLT.Customer c "
           "CROSS APPLY (SELECT 1 AS x) sub")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t == "Customer" for _, t in tables)


# ── Lines 161, 164-165, 168-172: _collect_tables expression nodes ─────────────

def test_collect_tables_where_cast_expression():
    sql = ("SELECT CustomerID FROM SalesLT.Customer "
           "WHERE CAST(CustomerID AS VARCHAR) = '1'")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t == "Customer" for _, t in tables)


def test_collect_tables_where_between_expression():
    sql = ("SELECT CustomerID FROM SalesLT.Customer "
           "WHERE CustomerID BETWEEN 1 AND 100")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t == "Customer" for _, t in tables)


def test_collect_tables_where_case_expression():
    sql = ("SELECT CustomerID FROM SalesLT.Customer "
           "WHERE CASE WHEN CustomerID > 0 THEN 1 ELSE 0 END = 1")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t == "Customer" for _, t in tables)


# ── Line 178: _walk(None) early return ───────────────────────────────────────

def test_walk_none_returns_immediately():
    ext = IntentExtractor()
    ext._seen = set()
    ext._walk(None, [], set())   # must not raise


# ── Line 276: _walk_update early return when no table ────────────────────────

def test_walk_update_no_table_returns_early():
    ext = IntentExtractor()
    ext._seen = set()
    intents = []
    ext._walk_update({"node_type": "UpdateStatement", "set": [], "where": None},
                     intents, set())
    assert intents == []


# ── Line 281: _walk_update with alias ────────────────────────────────────────

def test_walk_update_with_alias():
    ext = IntentExtractor()
    ext._seen = set()
    intents = []
    node = {
        "node_type": "UpdateStatement",
        "table": {"node_type": "IdentifierNode", "name": "Customer",
                  "qualifiers": ["SalesLT"]},
        "alias": "c",
        "set": [{
            "column": {"node_type": "IdentifierNode", "name": "FirstName",
                       "qualifiers": ["c"]},
            "expr": {"node_type": "LiteralNode", "value": "Alice",
                     "type": "STRING_LITERAL"},
        }],
        "where": None,
    }
    ext._walk_update(node, intents, set())
    assert any(i["intent"] == "UPDATE" for i in intents)


# ── Line 299: _walk_delete early return when no table ────────────────────────

def test_walk_delete_no_table_returns_early():
    ext = IntentExtractor()
    ext._seen = set()
    intents = []
    ext._walk_delete({"node_type": "DeleteStatement", "where": None},
                     intents, set())
    assert intents == []


# ── Line 304: _walk_delete with alias ────────────────────────────────────────

def test_walk_delete_with_alias():
    ext = IntentExtractor()
    ext._seen = set()
    intents = []
    node = {
        "node_type": "DeleteStatement",
        "table": {"node_type": "IdentifierNode", "name": "Customer",
                  "qualifiers": ["SalesLT"]},
        "alias": "c",
        "where": None,
    }
    ext._walk_delete(node, intents, set())
    assert any(i["intent"] == "DELETE" for i in intents)


# ── Line 314: _walk_insert early return when no table ────────────────────────

def test_walk_insert_no_table_returns_early():
    ext = IntentExtractor()
    ext._seen = set()
    intents = []
    ext._walk_insert({"node_type": "InsertStatement", "columns": [],
                      "source": None},
                     intents, set())
    assert intents == []


# ── Lines 384-388: _walk_subquery UnionStatement and else branch ──────────────

def test_walk_subquery_union_statement():
    ext = IntentExtractor()
    ext._seen = set()
    intents = []
    union_node = {
        "node_type": "UnionStatement",
        "left":  {"node_type": "SelectStatement", "table": None, "columns": [],
                  "ctes": [], "joins": [], "applies": [], "where": None,
                  "group_by": [], "having": None, "order_by": [], "is_star": False},
        "right": {"node_type": "SelectStatement", "table": None, "columns": [],
                  "ctes": [], "joins": [], "applies": [], "where": None,
                  "group_by": [], "having": None, "order_by": [], "is_star": False},
    }
    ext._walk_subquery(union_node, intents, set(), {})   # must not raise


def test_walk_subquery_else_branch():
    ext = IntentExtractor()
    ext._seen = set()
    intents = []
    ext._walk_subquery({"node_type": "LiteralNode", "value": "1"},
                       intents, set(), {})   # must not raise


# ── Line 404: _build_alias_map with None table_node ──────────────────────────

def test_build_alias_map_none_table_node():
    ext = IntentExtractor()
    node = {"node_type": "SelectStatement", "table": None, "alias": None,
            "joins": [], "columns": [], "is_star": False}
    alias_map, derived = ext._build_alias_map(node, set())
    assert alias_map == {}
    assert derived == set()


# ── Line 432: _table_info(None) ──────────────────────────────────────────────

def test_table_info_none_returns_empty():
    ext = IntentExtractor()
    schema, table = ext._table_info(None)
    assert schema == ""
    assert table  == ""


# ── Line 453: _resolve_col case-insensitive fallback ─────────────────────────

def test_resolve_col_case_insensitive_fallback():
    ext = IntentExtractor()
    alias_map = {"customer": ("SalesLT", "Customer")}
    id_node = {"node_type": "IdentifierNode", "name": "CustomerID",
               "qualifiers": ["CUSTOMER"]}
    schema, table, col = ext._resolve_col(id_node, alias_map)
    assert table == "Customer"
    assert col   == "CustomerID"


# ── Line 487: _resolve_col returns (None, None, col) ─────────────────────────

def test_resolve_col_multiple_tables_no_qualifier_returns_none():
    ext = IntentExtractor()
    alias_map = {
        "Customer": ("SalesLT", "Customer"),
        "Address":  ("SalesLT", "Address"),
    }
    id_node = {"node_type": "IdentifierNode", "name": "CustomerID",
               "qualifiers": [], "resolved_table": None}
    schema, table, col = ext._resolve_col(id_node, alias_map)
    assert table is None
    assert col   == "CustomerID"
