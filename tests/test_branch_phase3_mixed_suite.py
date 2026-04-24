import io

from birdeye.ast import (
    AlterTableStatement,
    BinaryExpressionNode,
    CaseExpressionNode,
    CreateTableStatement,
    DropTableStatement,
    FunctionCallNode,
    IdentifierNode,
    IfStatement,
    InsertStatement,
    LiteralNode,
    MergeClauseNode,
    MergeStatement,
    OverClauseNode,
    OrderByNode,
    PrintStatement,
    SetStatement,
    SqlBulkCopyStatement,
)
from birdeye.binder import Binder
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


# ---------------- Parser remaining branches ----------------


def test_parser_contains_identifier_case_true_paths():
    p = Parser([], "")

    case_input = CaseExpressionNode(input_expr=IdentifierNode("x"))
    assert p._contains_identifier(case_input) is True

    case_branch = CaseExpressionNode(input_expr=LiteralNode("1", TokenType.NUMERIC_LITERAL))
    case_branch.branches.append((IdentifierNode("w"), LiteralNode("2", TokenType.NUMERIC_LITERAL)))
    assert p._contains_identifier(case_branch) is True


def test_parser_keyword_function_empty_args_branch():
    ast = parse_sql("SELECT LEFT()")
    assert ast.columns[0].name == "LEFT"


def test_parser_over_partition_and_order_with_commas():
    ast1 = parse_sql("SELECT SUM(1) OVER (PARTITION BY A, B) FROM T")
    assert ast1 is not None

    ast2 = parse_sql("SELECT SUM(1) OVER (ORDER BY A, B) FROM T")
    assert ast2 is not None


def test_parser_drop_if_without_exists_and_alter_drop_without_column():
    drop_stmt = parse_sql("DROP TABLE IF T")
    assert drop_stmt.if_exists is False
    assert drop_stmt.table.name == "T"

    alter_stmt = parse_sql("ALTER TABLE T DROP c")
    assert alter_stmt.action == "DROP"
    assert alter_stmt.column.name == "c"


# ---------------- Binder remaining branches ----------------


def test_binder_bind_node_bulk_drop_alter_paths():
    reg = minimal_registry()
    binder = Binder(reg)

    bulk = SqlBulkCopyStatement()
    bulk.table = IdentifierNode("T")
    binder._bind_node(bulk)

    binder._bind_node(DropTableStatement())
    binder._bind_node(AlterTableStatement())


def test_binder_type_compatibility_extra_groups():
    binder = Binder(minimal_registry())
    assert binder._is_type_compatible("DATE", "DATETIME") is True
    assert binder._is_type_compatible("GEOGRAPHY", "GEOMETRY") is True
    assert binder._is_type_compatible("VARBINARY", "IMAGE") is True
    assert binder._is_type_compatible("XML", "XML") is True


def test_binder_visit_any_all_and_in_with_subquery_variants():
    binder = Binder(minimal_registry())

    left = LiteralNode("1", TokenType.NUMERIC_LITERAL)

    any_expr = BinaryExpressionNode(left=left, operator="> ANY", right=parse_sql("SELECT 1"))
    assert binder._visit_expression(any_expr) == "BIT"

    in_expr = BinaryExpressionNode(left=left, operator="IN", right=parse_sql("SELECT 1"))
    assert binder._visit_expression(in_expr) == "BIT"


def test_binder_visit_union_expression_returns_table():
    binder = Binder(minimal_registry())
    union = parse_sql("SELECT 1 UNION SELECT 2")
    assert binder._visit_expression(union) == "TABLE"


def test_binder_insert_without_registry_columns_and_misc_falsey_paths():
    reg = MetadataRegistry()
    reg.tables["T"] = {}
    binder = Binder(reg)

    stmt = InsertStatement()
    stmt.table = IdentifierNode("T")
    stmt.values = [LiteralNode("1", TokenType.NUMERIC_LITERAL)]
    binder._bind_insert(stmt)

    if_stmt = IfStatement()
    binder._bind_if(if_stmt)

    set_stmt = SetStatement()
    set_stmt.target = IdentifierNode("@X")
    set_stmt.value = None
    set_stmt.is_option = False
    binder._bind_set(set_stmt)

    set_opt = SetStatement()
    set_opt.is_option = True
    set_opt.value = None
    binder._bind_set(set_opt)


def test_binder_create_merge_print_and_agg_short_paths():
    binder = Binder(minimal_registry())

    create_stmt = CreateTableStatement()
    create_stmt.table = IdentifierNode("RealTable")
    binder._bind_create_table(create_stmt)

    merge = MergeStatement()
    merge.clauses = [MergeClauseNode()]
    binder._bind_merge(merge)

    binder._bind_print(PrintStatement())

    case_expr = CaseExpressionNode(input_expr=FunctionCallNode("SUM", [LiteralNode("1", TokenType.NUMERIC_LITERAL)]))
    assert binder._is_agg_raw(case_expr) is True

    expr = IdentifierNode("A")
    groups = [IdentifierNode("A")]
    binder._check_agg_integrity(expr, groups)


# ---------------- Intent extractor remaining branches ----------------


def test_intent_collect_tables_false_paths_and_walk_guards():
    ext = IntentExtractor()
    ext._seen = set()

    select_node = {
        "node_type": "SelectStatement",
        "ctes": [],
        "table": {"node_type": "IdentifierNode", "name": "T", "qualifiers": []},
        "joins": [{"table": {"node_type": "SelectStatement"}}],
        "where": None,
        "having": None,
        "group_by": [],
        "order_by": [],
        "applies": [],
        "columns": [],
    }
    tables = set()
    ext._collect_tables(select_node, tables, set())

    upd = {"node_type": "UpdateStatement", "table": {"node_type": "SelectStatement"}, "where": None, "set": []}
    ext._collect_tables(upd, tables, set())

    ins = {"node_type": "InsertStatement", "table": {"node_type": "SelectStatement"}, "source": None}
    ext._collect_tables(ins, tables, set())

    intents = []
    ext._walk({"node_type": "TruncateStatement", "table": {"node_type": "IdentifierNode", "name": "CTE1", "qualifiers": []}}, intents, {"CTE1"})
    ext._walk({"node_type": "SetStatement", "is_option": True, "value": None}, intents, set())
    ext._walk({"node_type": "DeclareStatement"}, intents, set())


def test_intent_walk_select_merge_expr_and_alias_builder_false_paths():
    ext = IntentExtractor()
    ext._seen = set()
    intents = []

    ext._walk_select(
        {
            "node_type": "SelectStatement",
            "ctes": [{"name": "C", "query": {"node_type": "SelectStatement", "ctes": [], "table": None, "joins": [], "columns": [], "where": None, "group_by": [], "having": None, "order_by": [], "applies": [], "is_star": False}}],
            "table": {"node_type": "IdentifierNode", "name": "T", "qualifiers": []},
            "alias": "t",
            "joins": [],
            "columns": [],
            "is_star": True,
            "into_table": {"node_type": "IdentifierNode", "name": "C", "qualifiers": []},
            "where": None,
            "group_by": [],
            "having": None,
            "order_by": [],
            "applies": [],
        },
        intents,
        set(),
    )

    ext._walk_update(
        {
            "node_type": "UpdateStatement",
            "table": {"node_type": "IdentifierNode", "name": "T", "qualifiers": []},
            "set": [{"column": {"node_type": "LiteralNode"}, "expr": None}],
            "where": None,
        },
        intents,
        set(),
    )

    ext._walk_insert(
        {
            "node_type": "InsertStatement",
            "table": {"node_type": "IdentifierNode", "name": "T", "qualifiers": []},
            "columns": [{"node_type": "LiteralNode"}],
            "source": None,
        },
        intents,
        set(),
    )

    ext._walk_merge(
        {
            "node_type": "MergeStatement",
            "source": None,
            "source_alias": "",
            "target": {"node_type": "IdentifierNode", "name": "C", "qualifiers": []},
            "target_alias": "",
            "on_condition": None,
            "clauses": [
                {"action": "UPDATE", "set_clauses": [{"column": {"node_type": "LiteralNode"}, "expr": None}]},
                {"action": "INSERT", "insert_columns": [{"node_type": "LiteralNode"}], "insert_values": []},
                {"action": "UPSERT"},
            ],
        },
        intents,
        {"C"},
    )

    ext._walk_expr(
        {"node_type": "IdentifierNode", "name": "A", "qualifiers": []},
        {"T1": ("", "T1"), "T2": ("", "T2")},
        "READ",
        intents,
        set(),
    )

    select_for_alias = {
        "node_type": "SelectStatement",
        "table": {"node_type": "SelectStatement"},
        "alias": "D",
        "joins": [],
    }
    _, derived = ext._build_alias_map(select_for_alias, set(), intents=None)
    assert "D" in derived


# ---------------- Visualizer remaining branches ----------------


def test_visualizer_optional_statement_fields_falsey_paths():
    viz = ASTVisualizer()

    drop_stmt = DropTableStatement()
    out_drop = viz.dump(drop_stmt)
    assert "DROP_TABLE_STATEMENT" in out_drop

    create_stmt = CreateTableStatement()
    create_stmt.table = IdentifierNode("T")
    out_create = viz.dump(create_stmt)
    assert "CREATE_TABLE_STATEMENT" in out_create

    alter_stmt = AlterTableStatement()
    alter_stmt.table = IdentifierNode("T")
    out_alter = viz.dump(alter_stmt)
    assert "ALTER_TABLE_STATEMENT" in out_alter

    set_opt = SetStatement()
    set_opt.is_option = True
    out_set_opt = viz.dump(set_opt)
    assert "SET_OPTION" in out_set_opt

    set_stmt = SetStatement()
    set_stmt.is_option = False
    out_set = viz.dump(set_stmt)
    assert "SET_STATEMENT" in out_set

    if_stmt = IfStatement()
    if_stmt.condition = LiteralNode("1", TokenType.NUMERIC_LITERAL)
    out_if = viz.dump(if_stmt)
    assert "IF_STATEMENT" in out_if

    merge_stmt = MergeStatement()
    merge_stmt.target = IdentifierNode("T")
    out_merge = viz.dump(merge_stmt)
    assert "MERGE_STATEMENT" in out_merge

    out_print = viz.dump(PrintStatement())
    assert "PRINT_STATEMENT" in out_print


def test_visualizer_case_and_over_clause_optional_fields():
    viz = ASTVisualizer()

    case = CaseExpressionNode()
    case.branches = [(LiteralNode("1", TokenType.NUMERIC_LITERAL), LiteralNode("2", TokenType.NUMERIC_LITERAL))]
    out_case = viz.dump(case)
    assert "CASE_EXPRESSION" in out_case

    over = OverClauseNode()
    over.frame_type = "ROWS"
    over.frame_start = "CURRENT ROW"
    func = FunctionCallNode("SUM", [LiteralNode("1", TokenType.NUMERIC_LITERAL)])
    func.over_clause = over

    out_over = viz.dump(func)
    assert "OVER_CLAUSE" in out_over
    assert "FRAME: ROWS" in out_over
