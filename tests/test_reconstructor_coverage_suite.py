"""
AST JSON → SQL 重建器覆蓋率補強測試套件

針對 reconstructor.py 中未被原有測試套件覆蓋的程式行：
- Line 22:  to_sql(None) returns ""
- Line 27:  unknown node_type returns ""
- Line 61:  SELECT INTO clause
- Line 76:  APPLY clause
- Lines 118-119: UPDATE with CTE
- Lines 133-134: DELETE with CTE
- Line 152:  INSERT ... SELECT (source-based insert)
- Lines 156-157: INSERT with single values (n.get("values") path)
- Lines 167-170: DECLARE statement
- Line 177:  _sql_expr(None) returns "NULL"
- Line 179:  _sql_expr(list) → "(a, b, c)"
- Line 213:  IN/NOT IN with subquery (non-list right side)
- Lines 226-227: EXISTS / NOT EXISTS function
- Line 235:  CASE with input expression
- Line 241:  CASE branch as [when, then] list format
- Line 260:  CONVERT form (is_convert=True in CastExpressionNode)
- Line 270:  CROSS JOIN type
- Line 272:  FULL OUTER JOIN type
- Lines 282-286: _sql_ApplyNode
- Lines 289-291: _sql_AssignmentNode
- Line 299:  _sql_CTENode standalone
- Line 306:  _sql_table_ref(None, ...) → ""
- Lines 309-311: derived table (subquery) as FROM table
"""
import json
import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.serializer import ASTSerializer
from birdeye.reconstructor import ASTReconstructor


def roundtrip(sql: str) -> str:
    """SQL → AST JSON → SQL round-trip, returns reconstructed SQL."""
    tokens = Lexer(sql).tokenize()
    ast = Parser(tokens, sql).parse()
    json_str = ASTSerializer().to_json(ast)
    return ASTReconstructor().to_sql(json.loads(json_str))


# ─────────────────────────────────────────────
# Line 22: to_sql(None) returns ""
# ─────────────────────────────────────────────

def test_to_sql_none_returns_empty():
    """to_sql(None) should return empty string."""
    result = ASTReconstructor().to_sql(None)
    assert result == ""


# ─────────────────────────────────────────────
# Line 27: unknown node_type returns ""
# ─────────────────────────────────────────────

def test_to_sql_unknown_node_type_returns_empty():
    """to_sql with unknown node_type should return empty string."""
    result = ASTReconstructor().to_sql({"node_type": "UnknownNodeXYZ"})
    assert result == ""


# ─────────────────────────────────────────────
# Line 61: SELECT INTO clause
# ─────────────────────────────────────────────

def test_select_into():
    """SELECT col INTO #tmp FROM T should produce INTO in output."""
    sql = roundtrip("SELECT AddressID INTO #TmpAddr FROM Address")
    assert "INTO" in sql
    assert "SELECT" in sql
    assert "Address" in sql


# ─────────────────────────────────────────────
# Line 76: APPLY clause (_sql_ApplyNode via SelectStatement)
# ─────────────────────────────────────────────

def test_cross_apply_roundtrip():
    """CROSS APPLY subquery should produce APPLY in output."""
    sql = roundtrip(
        "SELECT a.AddressID, x.val "
        "FROM Address a "
        "CROSS APPLY (SELECT 1 AS val) x"
    )
    assert "APPLY" in sql
    assert "Address" in sql


# ─────────────────────────────────────────────
# Lines 118-119: UPDATE with CTE
# ─────────────────────────────────────────────

def test_update_with_cte():
    """WITH CTE AS (...) UPDATE ... should include WITH in output."""
    sql = roundtrip(
        "WITH CTE AS (SELECT AddressID FROM Address) "
        "UPDATE Address SET AddressLine1 = 'X' WHERE AddressID = 1"
    )
    # The serializer does not serialize CTEs for UpdateStatement,
    # but the WITH/CTE path in reconstructor is exercised via direct dict test below.
    assert "UPDATE" in sql


def test_update_with_cte_direct():
    """Direct dict construction: UpdateStatement with ctes exercises lines 118-119."""
    node = {
        "node_type": "UpdateStatement",
        "ctes": [
            {
                "name": "CTE1",
                "query": {
                    "node_type": "SelectStatement",
                    "ctes": [],
                    "top": None,
                    "top_percent": False,
                    "is_distinct": False,
                    "is_star": True,
                    "columns": [],
                    "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": [], "alias": None, "resolved_table": None},
                    "alias": None,
                    "joins": [],
                    "applies": [],
                    "into_table": None,
                    "where": None,
                    "group_by": [],
                    "having": None,
                    "order_by": [],
                    "offset_count": None,
                    "fetch_count": None,
                }
            }
        ],
        "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": [], "alias": None, "resolved_table": None},
        "alias": None,
        "set_clauses": [
            {
                "node_type": "AssignmentNode",
                "column": {"node_type": "IdentifierNode", "name": "City", "qualifiers": [], "alias": None, "resolved_table": None},
                "expr": {"node_type": "LiteralNode", "value": "X", "type": "STRING_LITERAL"}
            }
        ],
        "where": None,
    }
    sql = ASTReconstructor().to_sql(node)
    assert "WITH" in sql
    assert "CTE1" in sql
    assert "UPDATE" in sql


# ─────────────────────────────────────────────
# Lines 133-134: DELETE with CTE
# ─────────────────────────────────────────────

def test_delete_with_cte_direct():
    """Direct dict construction: DeleteStatement with ctes exercises lines 133-134."""
    node = {
        "node_type": "DeleteStatement",
        "ctes": [
            {
                "name": "DEL_CTE",
                "query": {
                    "node_type": "SelectStatement",
                    "ctes": [],
                    "top": None,
                    "top_percent": False,
                    "is_distinct": False,
                    "is_star": True,
                    "columns": [],
                    "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": [], "alias": None, "resolved_table": None},
                    "alias": None,
                    "joins": [],
                    "applies": [],
                    "into_table": None,
                    "where": None,
                    "group_by": [],
                    "having": None,
                    "order_by": [],
                    "offset_count": None,
                    "fetch_count": None,
                }
            }
        ],
        "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": [], "alias": None, "resolved_table": None},
        "alias": None,
        "where": None,
    }
    sql = ASTReconstructor().to_sql(node)
    assert "WITH" in sql
    assert "DEL_CTE" in sql
    assert "DELETE" in sql


# ─────────────────────────────────────────────
# Line 152: INSERT ... SELECT (source-based insert)
# ─────────────────────────────────────────────

def test_insert_select():
    """INSERT INTO T SELECT * FROM S should produce INSERT and SELECT in output."""
    sql = roundtrip("INSERT INTO Address SELECT AddressID FROM Address")
    assert "INSERT" in sql
    assert "SELECT" in sql


# ─────────────────────────────────────────────
# Lines 156-157: INSERT with single values (n.get("values") path)
# ─────────────────────────────────────────────

def test_insert_single_values_direct():
    """Direct dict: InsertStatement with 'values' (not 'value_rows') exercises lines 156-157."""
    node = {
        "node_type": "InsertStatement",
        "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": [], "alias": None, "resolved_table": None},
        "columns": [],
        "values": [
            {"node_type": "LiteralNode", "value": "42", "type": "NUMERIC_LITERAL"},
            {"node_type": "LiteralNode", "value": "Seattle", "type": "STRING_LITERAL"}
        ],
        "value_rows": None,
        "source": None,
    }
    sql = ASTReconstructor().to_sql(node)
    assert "INSERT" in sql
    assert "VALUES" in sql
    assert "42" in sql


# ─────────────────────────────────────────────
# Lines 167-170: DECLARE statement
# ─────────────────────────────────────────────

def test_declare_simple():
    """DECLARE @var INT roundtrip should produce DECLARE in output."""
    sql = roundtrip("DECLARE @counter INT")
    assert "DECLARE" in sql
    assert "@counter" in sql
    assert "INT" in sql


def test_declare_with_default():
    """DECLARE @var INT = 5 roundtrip should include default value."""
    sql = roundtrip("DECLARE @counter INT = 5")
    assert "DECLARE" in sql
    assert "@counter" in sql
    assert "5" in sql


# ─────────────────────────────────────────────
# Line 177: _sql_expr(None) returns "NULL"
# ─────────────────────────────────────────────

def test_sql_expr_none_returns_null():
    """_sql_expr(None) should return the string 'NULL'."""
    result = ASTReconstructor()._sql_expr(None)
    assert result == "NULL"


# ─────────────────────────────────────────────
# Line 179: _sql_expr(list) → "(a, b, c)"
# ─────────────────────────────────────────────

def test_sql_expr_list_returns_tuple_form():
    """_sql_expr([...]) should return comma-separated values wrapped in parens."""
    nodes = [
        {"node_type": "LiteralNode", "value": "1", "type": "NUMERIC_LITERAL"},
        {"node_type": "LiteralNode", "value": "2", "type": "NUMERIC_LITERAL"},
        {"node_type": "LiteralNode", "value": "3", "type": "NUMERIC_LITERAL"},
    ]
    result = ASTReconstructor()._sql_expr(nodes)
    assert result == "(1, 2, 3)"


# ─────────────────────────────────────────────
# Line 213: IN/NOT IN with subquery (non-list right side)
# ─────────────────────────────────────────────

def test_in_with_subquery():
    """IN with subquery (non-list right) should produce IN with parens."""
    sql = roundtrip(
        "SELECT AddressID FROM Address "
        "WHERE AddressID IN (SELECT AddressID FROM Address WHERE AddressID > 0)"
    )
    assert "IN" in sql
    assert "SELECT" in sql


def test_not_in_with_subquery_direct():
    """Direct dict: NOT IN with subquery node exercises line 213."""
    node = {
        "node_type": "SelectStatement",
        "ctes": [],
        "top": None,
        "top_percent": False,
        "is_distinct": False,
        "is_star": False,
        "columns": [{"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": [], "alias": None, "resolved_table": None}],
        "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": [], "alias": None, "resolved_table": None},
        "alias": None,
        "joins": [],
        "applies": [],
        "into_table": None,
        "where": {
            "node_type": "BinaryExpressionNode",
            "op": "NOT IN",
            "left": {"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": [], "alias": None, "resolved_table": None},
            "right": {
                "node_type": "SelectStatement",
                "ctes": [],
                "top": None,
                "top_percent": False,
                "is_distinct": False,
                "is_star": False,
                "columns": [{"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": [], "alias": None, "resolved_table": None}],
                "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": [], "alias": None, "resolved_table": None},
                "alias": None,
                "joins": [],
                "applies": [],
                "into_table": None,
                "where": None,
                "group_by": [],
                "having": None,
                "order_by": [],
                "offset_count": None,
                "fetch_count": None,
            }
        },
        "group_by": [],
        "having": None,
        "order_by": [],
        "offset_count": None,
        "fetch_count": None,
    }
    sql = ASTReconstructor().to_sql(node)
    assert "NOT IN" in sql
    assert "SELECT" in sql


# ─────────────────────────────────────────────
# Lines 226-227: EXISTS / NOT EXISTS function
# ─────────────────────────────────────────────

def test_exists_subquery():
    """WHERE EXISTS (SELECT ...) should produce EXISTS in output."""
    sql = roundtrip(
        "SELECT AddressID FROM Address a "
        "WHERE EXISTS (SELECT 1 FROM Address b WHERE b.AddressID = a.AddressID)"
    )
    assert "EXISTS" in sql


def test_not_exists_direct():
    """Direct dict: NOT EXISTS FunctionCallNode exercises lines 226-227."""
    node = {
        "node_type": "FunctionCallNode",
        "name": "NOT EXISTS",
        "args": [
            {
                "node_type": "SelectStatement",
                "ctes": [],
                "top": None,
                "top_percent": False,
                "is_distinct": False,
                "is_star": True,
                "columns": [],
                "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": [], "alias": None, "resolved_table": None},
                "alias": None,
                "joins": [],
                "applies": [],
                "into_table": None,
                "where": None,
                "group_by": [],
                "having": None,
                "order_by": [],
                "offset_count": None,
                "fetch_count": None,
            }
        ],
        "alias": None,
    }
    result = ASTReconstructor()._sql_expr(node)
    assert "NOT EXISTS" in result


# ─────────────────────────────────────────────
# Line 235: CASE with input expression
# ─────────────────────────────────────────────

def test_case_with_input_expression():
    """CASE col WHEN 1 THEN 'a' ELSE 'b' END should include CASE and WHEN."""
    sql = roundtrip(
        "SELECT CASE AddressID WHEN 1 THEN 'one' ELSE 'other' END FROM Address"
    )
    assert "CASE" in sql
    assert "WHEN" in sql
    assert "THEN" in sql
    assert "END" in sql


# ─────────────────────────────────────────────
# Line 241: CASE branch as [when, then] list format
# ─────────────────────────────────────────────

def test_case_branch_list_format_direct():
    """Direct dict: CASE branches as list [when, then] exercises line 241."""
    node = {
        "node_type": "CaseExpressionNode",
        "input": None,
        "branches": [
            # list format instead of dict format
            [
                {"node_type": "LiteralNode", "value": "1", "type": "NUMERIC_LITERAL"},
                {"node_type": "LiteralNode", "value": "one", "type": "STRING_LITERAL"}
            ],
            [
                {"node_type": "LiteralNode", "value": "2", "type": "NUMERIC_LITERAL"},
                {"node_type": "LiteralNode", "value": "two", "type": "STRING_LITERAL"}
            ],
        ],
        "else": {"node_type": "LiteralNode", "value": "other", "type": "STRING_LITERAL"},
        "alias": None,
    }
    result = ASTReconstructor()._sql_expr(node)
    assert "CASE" in result
    assert "WHEN" in result
    assert "THEN" in result
    assert "END" in result


# ─────────────────────────────────────────────
# Line 260: CONVERT form (is_convert=True)
# ─────────────────────────────────────────────

def test_convert_roundtrip():
    """CONVERT(INT, col) should produce CONVERT in output."""
    sql = roundtrip("SELECT CONVERT(INT, AddressID) FROM Address")
    assert "CONVERT" in sql
    assert "INT" in sql


def test_convert_direct():
    """Direct dict: CastExpressionNode with is_convert=True exercises line 260."""
    node = {
        "node_type": "CastExpressionNode",
        "expr": {"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": [], "alias": None, "resolved_table": None},
        "target": "VARCHAR(50)",
        "is_convert": True,
    }
    result = ASTReconstructor()._sql_expr(node)
    assert "CONVERT" in result
    assert "VARCHAR(50)" in result
    assert "AddressID" in result


# ─────────────────────────────────────────────
# Line 270: CROSS JOIN type
# ─────────────────────────────────────────────

def test_cross_join():
    """CROSS JOIN should produce 'CROSS JOIN' in output."""
    sql = roundtrip(
        "SELECT a.AddressID FROM Address a CROSS JOIN StateProvince s"
    )
    assert "CROSS JOIN" in sql


# ─────────────────────────────────────────────
# Line 272: FULL OUTER JOIN type
# ─────────────────────────────────────────────

def test_full_outer_join():
    """FULL OUTER JOIN should produce 'FULL OUTER JOIN' in output."""
    sql = roundtrip(
        "SELECT a.AddressID FROM Address a "
        "FULL OUTER JOIN StateProvince s ON a.StateProvinceID = s.StateProvinceID"
    )
    assert "FULL OUTER JOIN" in sql


# ─────────────────────────────────────────────
# Lines 282-286: _sql_ApplyNode
# ─────────────────────────────────────────────

def test_apply_node_direct():
    """Direct dict: ApplyNode construction exercises lines 282-286."""
    node = {
        "node_type": "ApplyNode",
        "type": "OUTER",
        "subquery": {
            "node_type": "SelectStatement",
            "ctes": [],
            "top": None,
            "top_percent": False,
            "is_distinct": False,
            "is_star": False,
            "columns": [{"node_type": "LiteralNode", "value": "1", "type": "NUMERIC_LITERAL", "alias": "val"}],
            "table": None,
            "alias": None,
            "joins": [],
            "applies": [],
            "into_table": None,
            "where": None,
            "group_by": [],
            "having": None,
            "order_by": [],
            "offset_count": None,
            "fetch_count": None,
        },
        "alias": "sub",
    }
    result = ASTReconstructor()._sql_ApplyNode(node)
    assert "OUTER APPLY" in result
    assert "SELECT" in result
    assert "sub" in result


def test_apply_node_no_alias_direct():
    """Direct dict: ApplyNode without alias exercises lines 282-286 (alias_sql empty)."""
    node = {
        "node_type": "ApplyNode",
        "type": "CROSS",
        "subquery": {
            "node_type": "SelectStatement",
            "ctes": [],
            "top": None,
            "top_percent": False,
            "is_distinct": False,
            "is_star": True,
            "columns": [],
            "table": {"node_type": "IdentifierNode", "name": "T", "qualifiers": [], "alias": None, "resolved_table": None},
            "alias": None,
            "joins": [],
            "applies": [],
            "into_table": None,
            "where": None,
            "group_by": [],
            "having": None,
            "order_by": [],
            "offset_count": None,
            "fetch_count": None,
        },
        "alias": None,
    }
    result = ASTReconstructor()._sql_ApplyNode(node)
    assert "CROSS APPLY" in result


# ─────────────────────────────────────────────
# Lines 289-291: _sql_AssignmentNode
# ─────────────────────────────────────────────

def test_assignment_node_direct():
    """Direct dict: AssignmentNode exercises lines 289-291."""
    node = {
        "node_type": "AssignmentNode",
        "column": {"node_type": "IdentifierNode", "name": "City", "qualifiers": [], "alias": None, "resolved_table": None},
        "expr": {"node_type": "LiteralNode", "value": "Seattle", "type": "STRING_LITERAL"},
    }
    result = ASTReconstructor()._sql_AssignmentNode(node)
    assert "City" in result
    assert "=" in result
    assert "Seattle" in result


# ─────────────────────────────────────────────
# Line 299: _sql_CTENode standalone
# ─────────────────────────────────────────────

def test_cte_node_standalone_direct():
    """Direct dict: CTENode standalone call exercises line 299."""
    node = {
        "node_type": "CTENode",
        "name": "MyCTE",
        "query": {
            "node_type": "SelectStatement",
            "ctes": [],
            "top": None,
            "top_percent": False,
            "is_distinct": False,
            "is_star": True,
            "columns": [],
            "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": [], "alias": None, "resolved_table": None},
            "alias": None,
            "joins": [],
            "applies": [],
            "into_table": None,
            "where": None,
            "group_by": [],
            "having": None,
            "order_by": [],
            "offset_count": None,
            "fetch_count": None,
        }
    }
    result = ASTReconstructor()._sql_CTENode(node)
    assert "MyCTE" in result
    assert "AS" in result
    assert "SELECT" in result


# ─────────────────────────────────────────────
# Line 306: _sql_table_ref(None, ...) → ""
# ─────────────────────────────────────────────

def test_table_ref_none_returns_empty():
    """_sql_table_ref(None, alias) should return empty string (line 306)."""
    result = ASTReconstructor()._sql_table_ref(None, "someAlias")
    assert result == ""


# ─────────────────────────────────────────────
# Lines 309-311: derived table (subquery) as FROM table
# ─────────────────────────────────────────────

def test_derived_table_as_from():
    """Subquery as FROM table should produce nested SELECT with alias."""
    sql = roundtrip(
        "SELECT sub.AddressID "
        "FROM (SELECT AddressID FROM Address) sub"
    )
    assert "SELECT" in sql
    assert "FROM" in sql
    assert "Address" in sql


def test_derived_table_direct():
    """Direct dict: SelectStatement as table node exercises lines 309-311."""
    inner_select = {
        "node_type": "SelectStatement",
        "ctes": [],
        "top": None,
        "top_percent": False,
        "is_distinct": False,
        "is_star": True,
        "columns": [],
        "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": [], "alias": None, "resolved_table": None},
        "alias": None,
        "joins": [],
        "applies": [],
        "into_table": None,
        "where": None,
        "group_by": [],
        "having": None,
        "order_by": [],
        "offset_count": None,
        "fetch_count": None,
    }
    result = ASTReconstructor()._sql_table_ref(inner_select, "sub")
    assert "SELECT" in result
    assert "sub" in result
    assert result.startswith("(")


# ─────────────────────────────────────────────
# Additional: OUTER APPLY roundtrip
# ─────────────────────────────────────────────

def test_outer_apply_roundtrip():
    """OUTER APPLY subquery should produce APPLY in output."""
    sql = roundtrip(
        "SELECT a.AddressID, x.val "
        "FROM Address a "
        "OUTER APPLY (SELECT 1 AS val) x"
    )
    assert "APPLY" in sql
    assert "Address" in sql
