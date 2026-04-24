"""Tests targeting every remaining uncovered branch to reach 100% coverage."""
import io
import pytest

from birdeye.ast import (
    AlterTableStatement,
    AssignmentNode,
    BinaryExpressionNode,
    CreateTableStatement,
    FunctionCallNode,
    IdentifierNode,
    IfStatement,
    LiteralNode,
    MergeClauseNode,
    MergeStatement,
    OverClauseNode,
    SelectStatement,
)
from birdeye.binder import Binder, SemanticError
from birdeye.intent_extractor import IntentExtractor
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.registry import MetadataRegistry
from birdeye.visualizer import ASTVisualizer


def parse_sql(sql: str):
    return Parser(Lexer(sql).tokenize(), sql).parse()


def minimal_registry() -> MetadataRegistry:
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO("table_name,column_name,data_type\nT,A,INT\n"))
    return reg


# ── binder.py 116->118 ────────────────────────────────────────────────────────
# False branch of `if isinstance(o.column, IdentifierNode):` in ORDER BY loop.
# Triggered when ORDER BY uses a function call instead of a plain identifier.

def test_binder_order_by_non_identifier_skips_structural_resolve():
    binder = Binder(minimal_registry())
    # ORDER BY with an arithmetic expression (BinaryExpressionNode, not IdentifierNode)
    # triggers the false branch at line 116 and line 118.
    stmt = parse_sql("SELECT A FROM T ORDER BY A + 1")
    binder._bind_select(stmt)
    # If we reach here without error, the false branch at line 116 was taken.


# ── binder.py 332->283 ───────────────────────────────────────────────────────
# False branch of `elif self.registry.get_columns(rt):` when the table exists
# in scope but has no columns in the registry → fall through to next scope.

def test_binder_resolve_identifier_table_absent_from_registry():
    binder = Binder(MetadataRegistry())  # empty registry
    binder.scopes = [{"GHOSTTABLE": "GHOSTTABLE"}]
    binder.nullable_stack = [set()]
    node = IdentifierNode("col1")
    with pytest.raises(SemanticError, match="not found"):
        binder._resolve_identifier(node)


# ── binder.py 392->399 ───────────────────────────────────────────────────────
# False branch of `elif isinstance(expr.right, (SelectStatement, UnionStatement)):`
# in the ANY/ALL block: right is neither a list nor a subquery.

def test_binder_any_all_with_scalar_right_returns_bit():
    binder = Binder(minimal_registry())
    expr = BinaryExpressionNode(
        left=LiteralNode("1", TokenType.NUMERIC_LITERAL),
        operator="> ANY",
        right=LiteralNode("2", TokenType.NUMERIC_LITERAL),
    )
    assert binder._visit_expression(expr) == "BIT"


# ── binder.py 394->399 ───────────────────────────────────────────────────────
# False branch of `if hasattr(expr.right, 'columns') and expr.right.columns:`
# when right is a SelectStatement whose column list is empty.

def test_binder_any_all_subquery_with_no_columns_returns_bit():
    binder = Binder(minimal_registry())
    sel = SelectStatement()
    sel.columns = []
    expr = BinaryExpressionNode(
        left=LiteralNode("1", TokenType.NUMERIC_LITERAL),
        operator="> ANY",
        right=sel,
    )
    assert binder._visit_expression(expr) == "BIT"


# ── binder.py 407->409 ───────────────────────────────────────────────────────
# False branch of `elif isinstance(expr.right, (SelectStatement, UnionStatement)):`
# in the IN/NOT IN block: right is neither a list nor a subquery.

def test_binder_in_with_scalar_right_returns_bit():
    binder = Binder(minimal_registry())
    expr = BinaryExpressionNode(
        left=LiteralNode("1", TokenType.NUMERIC_LITERAL),
        operator="IN",
        right=LiteralNode("2", TokenType.NUMERIC_LITERAL),
    )
    assert binder._visit_expression(expr) == "BIT"


# ── binder.py 527->526 ───────────────────────────────────────────────────────
# False branch of `if col_names:` in the INSERT-SELECT loop.
# Triggered when INSERT has no explicit column list and the table has no
# columns in the registry, so col_names resolves to [].

def test_binder_insert_select_empty_col_names():
    reg = MetadataRegistry()
    reg.tables["GHOST"] = {}  # table known to registry but with no columns
    binder = Binder(reg)
    stmt = parse_sql("INSERT INTO Ghost SELECT 1")
    binder._bind_node(stmt)  # must not raise


# ── binder.py 587->exit ──────────────────────────────────────────────────────
# False branch of `if stmt.table and hasattr(stmt.table, 'name'):` in
# _bind_create_table when table is None → early return with no-op.

def test_binder_create_table_none_table_is_noop():
    binder = Binder(minimal_registry())
    create = CreateTableStatement()
    create.table = None  # already default; explicit for clarity
    binder._bind_create_table(create)  # must not raise


# ── binder.py 612->611 ───────────────────────────────────────────────────────
# False branch of `if hasattr(sc, 'right') and sc.right is not None:` in
# _bind_merge when a set-clause has right = None → skips _visit_expression.

def test_binder_merge_set_clause_with_null_right():
    binder = Binder(minimal_registry())
    merge = MergeStatement()
    clause = MergeClauseNode()
    clause.condition = None
    clause.set_clauses = [AssignmentNode(column=IdentifierNode("A"), expression=None)]
    clause.insert_values = []
    merge.clauses = [clause]
    binder._bind_merge(merge)  # must not raise


# ── intent_extractor.py 117->113 ─────────────────────────────────────────────
# False branch of `if table and table.upper() not in local_ctes:` in the
# JOIN loop: the joined table IS a local CTE, so it is excluded from tables.

def test_intent_collect_tables_join_cte_is_excluded():
    ext = IntentExtractor()
    cte_query = {
        "node_type": "SelectStatement", "ctes": [], "table": None,
        "joins": [], "columns": [], "where": None, "group_by": [],
        "having": None, "order_by": [], "applies": [],
    }
    node = {
        "node_type": "SelectStatement",
        "ctes": [{"name": "MyCTE", "query": cte_query}],
        "table": {"node_type": "IdentifierNode", "name": "RealTable", "qualifiers": []},
        "joins": [{"table": {"node_type": "IdentifierNode", "name": "MyCTE", "qualifiers": []}}],
        "where": None, "having": None, "group_by": [], "order_by": [], "applies": [], "columns": [],
    }
    tables = set()
    ext._collect_tables(node, tables, set())
    table_names = {t[1] for t in tables}
    assert "MYCTE" not in table_names
    assert "RealTable" in table_names


# ── intent_extractor.py 144->146 ─────────────────────────────────────────────
# False branch of `if table and table.upper() not in cte_names:` for UPDATE:
# the target table name matches a CTE name → excluded from collected tables.

def test_intent_collect_tables_update_cte_target_excluded():
    ext = IntentExtractor()
    upd = {
        "node_type": "UpdateStatement",
        "table": {"node_type": "IdentifierNode", "name": "MyCTE", "qualifiers": []},
        "where": None,
        "set": [],
    }
    tables = set()
    ext._collect_tables(upd, tables, {"MYCTE"})
    assert not tables


# ── intent_extractor.py 154->156 ─────────────────────────────────────────────
# False branch of `if table and table.upper() not in cte_names:` for INSERT:
# the target table name matches a CTE name → excluded.

def test_intent_collect_tables_insert_cte_target_excluded():
    ext = IntentExtractor()
    ins = {
        "node_type": "InsertStatement",
        "table": {"node_type": "IdentifierNode", "name": "MyCTE", "qualifiers": []},
        "source": None,
    }
    tables = set()
    ext._collect_tables(ins, tables, {"MYCTE"})
    assert not tables


# ── intent_extractor.py 486->488 ─────────────────────────────────────────────
# False branch of `if alias:` in _build_alias_map._register when the derived
# table (subquery) has no alias → alias is not added to derived_aliases.

def test_intent_build_alias_map_derived_table_no_alias():
    ext = IntentExtractor()
    node = {
        "node_type": "SelectStatement",
        "table": {"node_type": "SelectStatement"},  # subquery as FROM source
        "alias": "",  # falsy → skip derived_aliases.add
        "joins": [],
    }
    _, derived = ext._build_alias_map(node, set(), intents=None)
    assert "" not in derived


# ── parser.py line 558 ───────────────────────────────────────────────────────
# Line 558 is in the ANY/ALL branch: empty parens after `> ANY` raises SyntaxError.
# `IN ()` is handled by a separate code path; `> ANY ()` hits line 558.

def test_parser_any_empty_parens_raises_syntax_error():
    with pytest.raises(SyntaxError):
        parse_sql("SELECT 1 WHERE 1 > ANY ()")


# ── visualizer.py 215->217 ───────────────────────────────────────────────────
# False branch of `if node.table:` for CreateTableStatement → TABLE line skipped.

def test_visualizer_create_table_no_table_node():
    viz = ASTVisualizer()
    create = CreateTableStatement()
    create.table = None
    out = viz.dump(create)
    assert "CREATE_TABLE_STATEMENT" in out


# ── visualizer.py 222->224 ───────────────────────────────────────────────────
# False branch of `if node.table:` for AlterTableStatement → TABLE line skipped.

def test_visualizer_alter_table_no_table_node():
    viz = ASTVisualizer()
    alter = AlterTableStatement()
    alter.table = None
    out = viz.dump(alter)
    assert "ALTER_TABLE_STATEMENT" in out


# ── visualizer.py 248->251 ───────────────────────────────────────────────────
# False branch of `if node.condition is not None:` for IfStatement → CONDITION
# block skipped when condition is None.

def test_visualizer_if_statement_no_condition():
    viz = ASTVisualizer()
    if_stmt = IfStatement()
    if_stmt.condition = None
    out = viz.dump(if_stmt)
    assert "IF_STATEMENT" in out


# ── visualizer.py 276->279 ───────────────────────────────────────────────────
# False branch of `if node.target:` for MergeStatement → TARGET line skipped.

def test_visualizer_merge_no_target():
    viz = ASTVisualizer()
    merge = MergeStatement()
    merge.target = None
    out = viz.dump(merge)
    assert "MERGE_STATEMENT" in out


# ── visualizer.py 428->430 ───────────────────────────────────────────────────
# False branch of `if node.frame_start:` in OverClauseNode rendering:
# frame_type is set but frame_start is None → START line skipped.

def test_visualizer_over_frame_type_without_frame_start():
    viz = ASTVisualizer()
    over = OverClauseNode()
    over.frame_type = "ROWS"
    over.frame_start = None  # already default; explicit for clarity
    over.frame_end = "UNBOUNDED FOLLOWING"
    func = FunctionCallNode("SUM", [LiteralNode("1", TokenType.NUMERIC_LITERAL)])
    func.over_clause = over
    out = viz.dump(func)
    assert "FRAME: ROWS" in out
    assert "END: UNBOUNDED FOLLOWING" in out
