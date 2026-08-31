"""
row_filter.py coverage suite — targets RowFilterInjector end-to-end.
"""
import pytest
from birdeye.row_filter import RowFilterInjector

# ─── helpers ────────────────────────────────────────────────────────────────

def ident(name, qualifiers=None, alias=None):
    return {"node_type": "IdentifierNode", "name": name,
            "qualifiers": qualifiers or [], "alias": alias}

def literal(value, typ="STRING_LITERAL"):
    return {"node_type": "LiteralNode", "value": value, "type": typ, "alias": None}

def binexpr(op, left, right, alias=None):
    return {"node_type": "BinaryExpressionNode", "op": op,
            "left": left, "right": right, "alias": alias}

def select_stmt(table, columns=None, where=None, joins=None, alias=None,
                ctes=None, having=None, order_by=None, applies=None):
    return {
        "node_type": "SelectStatement",
        "table": table, "alias": alias,
        "columns": columns or [], "where": where,
        "joins": joins or [], "ctes": ctes or [],
        "having": having, "order_by": order_by or [],
        "applies": applies or [],
    }

def update_stmt(table, alias=None, where=None):
    return {"node_type": "UpdateStatement", "table": table,
            "alias": alias, "where": where}

def delete_stmt(table, alias=None, where=None):
    return {"node_type": "DeleteStatement", "table": table,
            "alias": alias, "where": where}

def filt(schema, table, column, op="=", value="1", vtype="LITERAL"):
    return {"Schema": schema, "Table": table, "Column": column,
            "Operator": op, "Value": value, "ValueType": vtype}

INJ = RowFilterInjector()

# ─── inject ──────────────────────────────────────────────────────────────────

class TestInject:
    def test_empty_filters_returns_original_object(self):
        ast = {"node_type": "SelectStatement"}
        assert INJ.inject(ast, []) is ast

    def test_matching_filter_returns_deep_copy_with_where(self):
        tbl = ident("Product", ["SalesLT"])
        ast = select_stmt(tbl)
        result = INJ.inject(ast, [filt("SALESLT", "PRODUCT", "ProductID")])
        assert result is not ast
        assert result["where"] is not None

# ─── _walk ───────────────────────────────────────────────────────────────────

class TestWalk:
    def test_none_is_noop(self):
        INJ._walk(None, [])

    def test_non_dict_is_noop(self):
        INJ._walk("string", [])

    def test_list_walks_each_item(self):
        tbl = ident("Product", ["SalesLT"])
        stmts = [select_stmt(tbl), select_stmt(tbl)]
        INJ._walk(stmts, [filt("SALESLT", "PRODUCT", "ProductID")])
        assert stmts[0]["where"] is not None
        assert stmts[1]["where"] is not None

    def test_script_node_walks_statements(self):
        tbl = ident("Product", ["SalesLT"])
        script = {"node_type": "ScriptNode",
                  "statements": [select_stmt(tbl)]}
        INJ._walk(script, [filt("SALESLT", "PRODUCT", "ProductID")])
        assert script["statements"][0]["where"] is not None

    def test_script_node_none_statements(self):
        script = {"node_type": "ScriptNode", "statements": None}
        INJ._walk(script, [filt("", "Product", "ID")])  # should not raise

    def test_select_no_match_leaves_where_none(self):
        stmt = select_stmt(ident("Address"))
        INJ._walk(stmt, [filt("", "PRODUCT", "ID")])
        assert stmt["where"] is None

    def test_select_injects_and_with_existing_where(self):
        tbl = ident("Product", ["SalesLT"])
        existing = binexpr("=", ident("Col"), literal("'x'"))
        stmt = select_stmt(tbl, where=existing)
        INJ._walk(stmt, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert stmt["where"]["op"] == "AND"

    def test_update_injects_where(self):
        tbl = ident("Product", ["SalesLT"])
        stmt = update_stmt(tbl)
        INJ._walk(stmt, [filt("SALESLT", "PRODUCT", "ProductID", value="5")])
        assert stmt["where"] is not None

    def test_delete_injects_where(self):
        tbl = ident("Product", ["SalesLT"])
        stmt = delete_stmt(tbl)
        INJ._walk(stmt, [filt("SALESLT", "PRODUCT", "ProductID", value="5")])
        assert stmt["where"] is not None

    def test_union_walks_left_and_right(self):
        tbl = ident("Product", ["SalesLT"])
        left = select_stmt(tbl)
        right = select_stmt(tbl)
        union = {"node_type": "UnionStatement", "left": left, "right": right}
        INJ._walk(union, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert left["where"] is not None
        assert right["where"] is not None

    def test_if_walks_then_and_else(self):
        tbl = ident("Product", ["SalesLT"])
        then_s = select_stmt(tbl)
        else_s = select_stmt(tbl)
        if_node = {"node_type": "IfStatement",
                   "then_block": [then_s], "else_block": [else_s]}
        INJ._walk(if_node, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert then_s["where"] is not None
        assert else_s["where"] is not None

    def test_if_none_blocks_is_noop(self):
        if_node = {"node_type": "IfStatement",
                   "then_block": None, "else_block": None}
        INJ._walk(if_node, [filt("", "Product", "ID")])

    def test_update_no_matching_filter(self):
        """line 68->exit: DML if applicable: False branch"""
        tbl = ident("Product", ["SalesLT"])
        stmt = update_stmt(tbl)
        INJ._walk(stmt, [filt("", "ADDRESS", "ID")])
        assert stmt["where"] is None

    def test_unknown_node_type_is_noop(self):
        """line 76->exit: no elif matches → silent noop"""
        node = {"node_type": "UnknownNode", "data": 42}
        INJ._walk(node, [filt("", "Product", "ID")])

# ─── _walk_subqueries_in_select ──────────────────────────────────────────────

class TestWalkSubqueries:
    def test_cte_query_is_walked(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        outer = select_stmt(ident("Address"), ctes=[{"name": "c", "query": inner}])
        INJ._walk(outer, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_table_is_select_subquery(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        stmt = {
            "node_type": "SelectStatement", "table": inner, "alias": "sub",
            "columns": [], "where": None, "joins": [], "ctes": [],
            "having": None, "order_by": [], "applies": [],
        }
        INJ._walk(stmt, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_table_is_union_subquery(self):
        inner_left = select_stmt(ident("Product", ["SalesLT"]))
        inner_right = select_stmt(ident("Product", ["SalesLT"]))
        union = {"node_type": "UnionStatement",
                 "left": inner_left, "right": inner_right}
        stmt = {
            "node_type": "SelectStatement", "table": union, "alias": "u",
            "columns": [], "where": None, "joins": [], "ctes": [],
            "having": None, "order_by": [], "applies": [],
        }
        INJ._walk(stmt, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner_left["where"] is not None

    def test_join_subquery_is_walked(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        join = {"table": inner, "alias": "p", "join_type": "INNER"}
        outer = select_stmt(ident("Address"), joins=[join])
        INJ._walk(outer, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_join_regular_table_not_walked(self):
        """line 90->88: join table is IdentifierNode (not subquery) → branch skipped"""
        join = {"table": ident("Customer", ["SalesLT"]), "alias": "c"}
        outer = select_stmt(ident("Address"), joins=[join])
        INJ._walk(outer, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert outer["where"] is None

    def test_apply_subquery_is_walked(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        outer = select_stmt(ident("Address"), applies=[{"subquery": inner}])
        INJ._walk(outer, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_column_expr_with_subquery(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        outer = select_stmt(ident("Address"), columns=[inner])
        INJ._walk(outer, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_where_expr_with_subquery(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        where = binexpr("IN", ident("ID"), inner)
        outer = select_stmt(ident("Address"), where=where)
        INJ._walk(outer, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_having_expr_with_subquery(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        outer = select_stmt(ident("Address"),
                            having=binexpr(">", ident("cnt"), inner))
        INJ._walk(outer, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_order_by_column_with_subquery(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        outer = select_stmt(ident("Address"),
                            order_by=[{"column": inner, "direction": "ASC"}])
        INJ._walk(outer, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

# ─── _walk_expr ───────────────────────────────────────────────────────────────

class TestWalkExpr:
    def test_none_is_noop(self):
        INJ._walk_expr(None, [])

    def test_non_dict_is_noop(self):
        INJ._walk_expr(99, [])

    def test_list_walks_each(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        INJ._walk_expr([inner, None], [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_select_in_expr(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        INJ._walk_expr(inner, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_union_in_expr(self):
        left = select_stmt(ident("Product", ["SalesLT"]))
        right = select_stmt(ident("Product", ["SalesLT"]))
        union = {"node_type": "UnionStatement", "left": left, "right": right}
        INJ._walk_expr(union, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert left["where"] is not None

    def test_binary_expr_list_right(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        node = binexpr("IN", ident("Col"), [inner])
        INJ._walk_expr(node, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_binary_expr_dict_right(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        node = binexpr("=", ident("Col"), inner)
        INJ._walk_expr(node, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_function_call_args(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        node = {"node_type": "FunctionCallNode", "name": "COUNT", "args": [inner]}
        INJ._walk_expr(node, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_cast_expression(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        node = {"node_type": "CastExpressionNode", "expr": inner, "type": "INT"}
        INJ._walk_expr(node, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_between_expression_target(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        node = {"node_type": "BetweenExpressionNode",
                "target": inner,
                "low": literal("1", "NUMERIC_LITERAL"),
                "high": literal("10", "NUMERIC_LITERAL")}
        INJ._walk_expr(node, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_case_expression_input(self):
        inner = select_stmt(ident("Product", ["SalesLT"]))
        node = {"node_type": "CaseExpressionNode",
                "input": inner, "branches": [], "else": None}
        INJ._walk_expr(node, [filt("SALESLT", "PRODUCT", "ProductID", value="1")])
        assert inner["where"] is not None

    def test_case_expression_when_then_else(self):
        f = filt("SALESLT", "PRODUCT", "ProductID", value="1")
        i_when = select_stmt(ident("Product", ["SalesLT"]))
        i_then = select_stmt(ident("Product", ["SalesLT"]))
        i_else = select_stmt(ident("Product", ["SalesLT"]))
        node = {"node_type": "CaseExpressionNode",
                "input": None,
                "branches": [{"when": i_when, "then": i_then}],
                "else": i_else}
        INJ._walk_expr(node, [f])
        assert i_when["where"] is not None
        assert i_then["where"] is not None
        assert i_else["where"] is not None

# ─── _build_alias_entries ────────────────────────────────────────────────────

class TestBuildAliasEntries:
    def test_simple_no_alias(self):
        entries = INJ._build_alias_entries(select_stmt(ident("Product")))
        assert entries == [("", "PRODUCT", "Product")]

    def test_with_schema_and_alias(self):
        entries = INJ._build_alias_entries(
            select_stmt(ident("Product", ["SalesLT"]), alias="p"))
        assert entries == [("SALESLT", "PRODUCT", "p")]

    def test_table_not_identifier_skipped(self):
        inner = select_stmt(ident("Product"))
        entries = INJ._build_alias_entries(select_stmt(inner))
        assert entries == []

    def test_none_table_skipped(self):
        entries = INJ._build_alias_entries(select_stmt(None))
        assert entries == []

    def test_empty_name_skipped(self):
        tbl = {"node_type": "IdentifierNode", "name": "", "qualifiers": [], "alias": None}
        entries = INJ._build_alias_entries(select_stmt(tbl))
        assert entries == []

    def test_join_tables_included(self):
        join = {"table": ident("Product", ["SalesLT"]), "alias": "p"}
        stmt = select_stmt(ident("Order", ["SalesLT"]), joins=[join])
        entries = INJ._build_alias_entries(stmt)
        assert len(entries) == 2
        assert entries[1] == ("SALESLT", "PRODUCT", "p")

# ─── _build_alias_entries_dml ────────────────────────────────────────────────

class TestBuildAliasEntriesDml:
    def test_valid_update(self):
        entries = INJ._build_alias_entries_dml(
            update_stmt(ident("Product", ["SalesLT"])))
        assert entries == [("SALESLT", "PRODUCT", "Product")]

    def test_no_table(self):
        entries = INJ._build_alias_entries_dml(
            {"node_type": "UpdateStatement", "table": None,
             "alias": None, "where": None})
        assert entries == []

    def test_table_not_identifier(self):
        inner = select_stmt(ident("Product"))
        entries = INJ._build_alias_entries_dml(
            {"node_type": "UpdateStatement", "table": inner,
             "alias": None, "where": None})
        assert entries == []

    def test_empty_name(self):
        tbl = {"node_type": "IdentifierNode", "name": "", "qualifiers": [], "alias": None}
        entries = INJ._build_alias_entries_dml(update_stmt(tbl))
        assert entries == []

    def test_with_alias(self):
        entries = INJ._build_alias_entries_dml(
            {"node_type": "UpdateStatement",
             "table": ident("Product", ["SalesLT"]),
             "alias": "p", "where": None})
        assert entries == [("SALESLT", "PRODUCT", "p")]

# ─── _match_filters ──────────────────────────────────────────────────────────

class TestMatchFilters:
    def test_match_table_only(self):
        result = INJ._match_filters(
            [("", "PRODUCT", "Product")],
            [filt("", "PRODUCT", "ID")])
        assert len(result) == 1

    def test_match_table_and_schema(self):
        result = INJ._match_filters(
            [("SALESLT", "PRODUCT", "p")],
            [filt("SALESLT", "PRODUCT", "ID")])
        assert len(result) == 1

    def test_no_match_wrong_table(self):
        result = INJ._match_filters(
            [("", "ADDRESS", "a")],
            [filt("", "PRODUCT", "ID")])
        assert result == []

    def test_no_match_wrong_schema(self):
        result = INJ._match_filters(
            [("HR", "PRODUCT", "p")],
            [filt("SALESLT", "PRODUCT", "ID")])
        assert result == []

    def test_partial_match_among_multiple_filters(self):
        result = INJ._match_filters(
            [("SALESLT", "PRODUCT", "p")],
            [filt("SALESLT", "PRODUCT", "ID"), filt("", "ADDRESS", "City")])
        assert len(result) == 1
        assert result[0]["Column"] == "ID"

# ─── _make_condition ─────────────────────────────────────────────────────────

class TestMakeCondition:
    _e = [("SALESLT", "PRODUCT", "p")]

    def test_literal_equals(self):
        cond = INJ._make_condition(filt("SALESLT", "PRODUCT", "ProductID", "=", "42"), self._e)
        assert cond["op"] == "="
        assert cond["left"]["name"] == "ProductID"
        assert cond["right"]["value"] == "42"

    def test_literal_in(self):
        cond = INJ._make_condition(
            filt("SALESLT", "PRODUCT", "ProductID", "IN", "1,2,3"), self._e)
        assert cond["op"] == "IN"
        assert isinstance(cond["right"], list)
        assert len(cond["right"]) == 3

    def test_literal_not_in(self):
        cond = INJ._make_condition(
            filt("SALESLT", "PRODUCT", "Status", "NOT IN", "X,Y"), self._e)
        assert cond["op"] == "NOT IN"
        assert len(cond["right"]) == 2

    def test_like_operator(self):
        cond = INJ._make_condition(
            filt("SALESLT", "PRODUCT", "Name", "LIKE", "Bike%"), self._e)
        assert cond["op"] == "LIKE"

    def test_subquery_dict_value(self):
        sub = {"node_type": "SelectStatement"}
        f = {"Schema": "SALESLT", "Table": "PRODUCT", "Column": "ProductID",
             "Operator": "IN", "Value": sub, "ValueType": "SUBQUERY"}
        cond = INJ._make_condition(f, self._e)
        assert cond["right"] is sub

    def test_subquery_string_raises_value_error(self):
        f = {"Schema": "SALESLT", "Table": "PRODUCT", "Column": "ProductID",
             "Operator": "IN", "Value": "SELECT 1", "ValueType": "SUBQUERY"}
        with pytest.raises(ValueError, match="SUBQUERY"):
            INJ._make_condition(f, self._e)

    def test_qualifier_applied_to_col_node(self):
        cond = INJ._make_condition(filt("SALESLT", "PRODUCT", "ProductID", value="1"), self._e)
        assert cond["left"]["qualifiers"] == ["p"]

    def test_defaults_when_fields_none(self):
        f = {"Schema": None, "Table": "PRODUCT", "Column": "ID",
             "Operator": None, "Value": "5", "ValueType": None}
        cond = INJ._make_condition(f, [("", "PRODUCT", "Product")])
        assert cond["op"] == "="

# ─── _make_literal ───────────────────────────────────────────────────────────

class TestMakeLiteral:
    def test_integer(self):
        lit = RowFilterInjector._make_literal("42")
        assert lit["type"] == "NUMERIC_LITERAL"
        assert lit["value"] == "42"

    def test_negative_integer(self):
        lit = RowFilterInjector._make_literal("-5")
        assert lit["type"] == "NUMERIC_LITERAL"

    def test_decimal(self):
        lit = RowFilterInjector._make_literal("3.14")
        assert lit["type"] == "NUMERIC_LITERAL"

    def test_scientific_notation(self):
        lit = RowFilterInjector._make_literal("1e10")
        assert lit["type"] == "NUMERIC_LITERAL"

    def test_ascii_string(self):
        lit = RowFilterInjector._make_literal("hello")
        assert lit["type"] == "STRING_LITERAL"
        assert lit["value"] == "'hello'"

    def test_single_quote_escaped(self):
        lit = RowFilterInjector._make_literal("it's")
        assert lit["value"] == "'it''s'"

    def test_unicode_gets_n_prefix(self):
        lit = RowFilterInjector._make_literal("你好")
        assert lit["value"].startswith("N'")
        assert lit["type"] == "STRING_LITERAL"

# ─── _find_qualifier ─────────────────────────────────────────────────────────

class TestFindQualifier:
    def test_match_with_schema(self):
        q = RowFilterInjector._find_qualifier(
            "SALESLT", "PRODUCT", [("SALESLT", "PRODUCT", "p")])
        assert q == "p"

    def test_match_no_schema(self):
        q = RowFilterInjector._find_qualifier(
            "", "PRODUCT", [("", "PRODUCT", "Product")])
        assert q == "Product"

    def test_no_match_returns_table_up(self):
        q = RowFilterInjector._find_qualifier(
            "", "PRODUCT", [("", "ADDRESS", "a")])
        assert q == "PRODUCT"

    def test_schema_disambiguates(self):
        entries = [("HR", "EMPLOYEE", "e"), ("SALESLT", "EMPLOYEE", "emp")]
        q = RowFilterInjector._find_qualifier("SALESLT", "EMPLOYEE", entries)
        assert q == "emp"

# ─── _and_conditions ─────────────────────────────────────────────────────────

class TestAndConditions:
    def _c(self, col):
        return binexpr("=", ident(col), literal("'1'"))

    def test_empty_conditions_returns_none(self):
        assert RowFilterInjector._and_conditions(None, []) is None

    def test_single_condition_no_existing(self):
        c = self._c("A")
        assert RowFilterInjector._and_conditions(None, [c]) is c

    def test_single_condition_with_existing(self):
        existing = self._c("existing")
        c = self._c("A")
        result = RowFilterInjector._and_conditions(existing, [c])
        assert result["op"] == "AND"
        assert result["left"] is existing
        assert result["right"] is c

    def test_multiple_conditions_chained(self):
        c1, c2, c3 = self._c("A"), self._c("B"), self._c("C")
        result = RowFilterInjector._and_conditions(None, [c1, c2, c3])
        assert result["op"] == "AND"
        assert result["right"] is c3
        assert result["left"]["op"] == "AND"
        assert result["left"]["right"] is c2
