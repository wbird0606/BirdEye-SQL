import io
import pytest

from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
from birdeye.registry import MetadataRegistry
from birdeye.runner import BirdEyeRunner
from birdeye.ast import (
    IdentifierNode,
    LiteralNode,
    ExecStatement,
    SetStatement,
    IfStatement,
    CreateTableStatement,
    ColumnDefinitionNode,
    DropTableStatement,
    AlterTableStatement,
    SqlBulkCopyStatement,
    MergeStatement,
    MergeClauseNode,
    AssignmentNode,
    ScriptNode,
)
from birdeye.visualizer import ASTVisualizer
from birdeye.mermaid_exporter import MermaidExporter
from birdeye.reconstructor import ASTReconstructor
from birdeye.intent_extractor import IntentExtractor, INTENT_DELETE, INTENT_INSERT, INTENT_UPDATE


SIMPLE_CSV = (
    "table_name,column_name,data_type\n"
    "Address,AddressID,INT\n"
    "Address,City,NVARCHAR\n"
    "Customer,CustomerID,INT\n"
    "Customer,CompanyName,NVARCHAR\n"
)


def make_runner(csv_str=SIMPLE_CSV):
    r = BirdEyeRunner()
    r.load_metadata_from_csv(io.StringIO(csv_str))
    return r


def parse_script(sql):
    toks = Lexer(sql).tokenize()
    return Parser(toks, sql).parse_script()


# ---------------- runner ----------------

def test_runner_rewrite_qmark_comment_paths_and_prepare_errors():
    r = BirdEyeRunner()

    sql = "-- ? in line comment\nSELECT 1 /* block ? body */"
    rewritten, qn = r._rewrite_qmark_sql(sql)
    assert qn == 0
    assert "@P" not in rewritten

    with pytest.raises(ValueError, match="PARAM_MISSING"):
        r._prepare_sql_and_params("SELECT ?", None)

    with pytest.raises(ValueError, match="PARAM_FORMAT_INVALID"):
        r._prepare_sql_and_params("SELECT 1", 123)


# ---------------- parser ----------------

def test_parser_parse_script_empty_and_unexpected_eof():
    p = Parser(Lexer("").tokenize(), "")
    with pytest.raises(SyntaxError, match="Empty source"):
        p.parse_script()

    p2 = Parser(Lexer("").tokenize(), "")
    with pytest.raises(SyntaxError, match="Unexpected end of input"):
        p2._parse_one_statement()


def test_parser_dispatch_branches_in_parse_one_statement():
    # cover UPDATE/DELETE with CTE assignment in dispatch
    ast = parse_script(
        "WITH C AS (SELECT 1 AS X) UPDATE Address SET City = 'A' WHERE 1=1;"
        "WITH D AS (SELECT 1 AS X) DELETE FROM Address WHERE 1=1;"
    )
    assert len(ast.statements) == 2

    # cover BULK / IF / BEGIN / CREATE / ALTER / MERGE / PRINT / SET dispatches
    script2 = (
        "BULK INSERT INTO Address;"
        "IF 1=1 SELECT 1;"
        "BEGIN SELECT 1 END;"
        "CREATE TABLE T1 (C1 INT);"
        "ALTER TABLE Address ADD NewCol INT;"
        "MERGE Address USING Address ON 1=1 WHEN MATCHED THEN UPDATE SET AddressID = 1;"
        "PRINT 1;"
        "SET NOCOUNT ON;"
    )
    ast2 = parse_script(script2)
    assert len(ast2.statements) == 8


# ---------------- binder ----------------

def test_binder_helper_branches_and_structural_identifier_errors():
    b = Binder(MetadataRegistry())

    assert b._infer_type_from_value(None) == "UNKNOWN"
    assert b._infer_type_from_value(True) == "BIT"
    assert b._infer_type_from_value(1.2) == "FLOAT"
    assert b._infer_type_from_value(b"x") == "VARBINARY"
    assert b._infer_type_from_value(object()) == "UNKNOWN"

    norm, vals = b._normalize_external_params({
        "city": {"data_type": "nvarchar", "value": "Taipei"},
        "blob": b"abc",
    })
    assert norm["@CITY"] == "NVARCHAR"
    assert vals["@CITY"] == "Taipei"
    assert norm["@BLOB"] == "VARBINARY"

    assert b._is_safe_identifier("dbo.Address", allow_qualified=False) is False
    assert b._is_safe_identifier("a.b.c", allow_qualified=True) is False

    node = IdentifierNode(name="@tbl")
    b.external_param_values = {}
    with pytest.raises(SemanticError, match="requires a runtime parameter value"):
        b._resolve_structural_identifier(node, "FROM/JOIN table", allow_qualified=True)

    b.external_param_values = {"@TBL": "   "}
    with pytest.raises(SemanticError, match="must be a non-empty identifier string"):
        b._resolve_structural_identifier(node, "FROM/JOIN table", allow_qualified=True)

    b.external_param_values = {"@TBL": "A;DROP"}
    with pytest.raises(SemanticError, match="unsafe identifier"):
        b._resolve_structural_identifier(node, "FROM/JOIN table", allow_qualified=True)


def test_binder_merge_insert_values_path():
    runner = make_runner()
    sql = (
        "MERGE Address AS t USING Address AS s ON 1=0 "
        "WHEN NOT MATCHED THEN INSERT (AddressID, City) VALUES (1, 'X')"
    )
    result = runner.run(sql)
    assert result["status"] == "success"


# ---------------- intent extractor ----------------

def test_intent_extractor_walk_merge_and_expr_branches():
    ie = IntentExtractor()
    ie._seen = set()
    intents = []

    merge_node = {
        "node_type": "MergeStatement",
        "target": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": []},
        "target_alias": "t",
        "source": {
            "node_type": "SelectStatement",
            "columns": [{"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": ["Address"]}],
            "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": []},
        },
        "source_alias": "s",
        "on_condition": {
            "node_type": "BinaryExpressionNode",
            "left": {"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": ["s"]},
            "right": {"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": ["t"]},
        },
        "clauses": [
            {
                "action": "UPDATE",
                "set_clauses": [
                    {
                        "column": {"node_type": "IdentifierNode", "name": "City", "qualifiers": ["t"]},
                        "expr": {"node_type": "IdentifierNode", "name": "@p"},
                    }
                ],
            },
            {
                "action": "INSERT",
                "insert_columns": [{"node_type": "IdentifierNode", "name": "City"}],
                "insert_values": [
                    {
                        "node_type": "FunctionCallNode",
                        "name": "UPPER",
                        "args": [{"node_type": "IdentifierNode", "name": "City", "qualifiers": ["t"]}],
                    }
                ],
            },
            {"action": "DELETE"},
        ],
    }

    ie._walk_merge(merge_node, intents, cte_names=set())

    intent_types = {x["intent"] for x in intents}
    assert INTENT_UPDATE in intent_types
    assert INTENT_INSERT in intent_types
    assert INTENT_DELETE in intent_types


def test_intent_extractor_top_level_dispatch_if_merge_set_declare():
    ie = IntentExtractor()
    ast_dict = {
        "node_type": "ScriptNode",
        "statements": [
            {
                "node_type": "IfStatement",
                "condition": {
                    "node_type": "BinaryExpressionNode",
                    "left": {"node_type": "LiteralNode", "value": "1", "type": "NUMBER"},
                    "right": {"node_type": "LiteralNode", "value": "1", "type": "NUMBER"},
                },
                "then_block": [
                    {
                        "node_type": "SelectStatement",
                        "columns": [{"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": ["Address"]}],
                        "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": []},
                    }
                ],
                "else_block": [],
            },
            {
                "node_type": "MergeStatement",
                "target": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": []},
                "source": {
                    "node_type": "SelectStatement",
                    "columns": [{"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": ["Address"]}],
                    "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": []},
                },
                "on_condition": {
                    "node_type": "BinaryExpressionNode",
                    "left": {"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": ["Address"]},
                    "right": {"node_type": "LiteralNode", "value": "1", "type": "NUMBER"},
                },
                "clauses": [{"action": "DELETE"}],
            },
            {
                "node_type": "SetStatement",
                "is_option": False,
                "value": {
                    "node_type": "SelectStatement",
                    "columns": [{"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": ["Address"]}],
                    "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": []},
                },
            },
            {
                "node_type": "DeclareStatement",
                "default_value": {
                    "node_type": "SelectStatement",
                    "columns": [{"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": ["Address"]}],
                    "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": []},
                },
            },
        ],
    }

    intents = ie.extract(ast_dict)
    assert any(i.get("intent") == INTENT_DELETE for i in intents)


# ---------------- mermaid exporter ----------------

def test_mermaid_exporter_create_drop_alter_labels():
    exporter = MermaidExporter()
    ast_dict = {
        "node_type": "ScriptNode",
        "statements": [
            {
                "node_type": "CreateTableStatement",
                "table": {"node_type": "IdentifierNode", "name": "T", "qualifiers": ["dbo"]},
            },
            {"node_type": "AlterTableStatement"},
            {
                "node_type": "DropTableStatement",
                "table": {"node_type": "IdentifierNode", "name": "T", "qualifiers": ["dbo"]},
            },
        ],
    }

    txt = exporter.export(ast_dict)
    assert "CREATE TABLE dbo.T" in txt
    assert "ALTER TABLE" in txt
    assert "DROP TABLE dbo.T" in txt


# ---------------- reconstructor ----------------

def test_reconstructor_qmark_identifier_rewrite():
    rec = ASTReconstructor()
    sql = rec.to_sql({"node_type": "IdentifierNode", "name": "@P1", "param_input_mode": "qmark"})
    assert sql == "?"


# ---------------- visualizer ----------------

def test_visualizer_statement_branches_for_uncovered_lines():
    v = ASTVisualizer()

    create_stmt = CreateTableStatement()
    create_stmt.if_not_exists = True
    create_stmt.table = IdentifierNode(name="T1")
    create_stmt.columns = [ColumnDefinitionNode(name="C1", data_type="INT")]

    alter_stmt = AlterTableStatement()
    alter_stmt.table = IdentifierNode(name="Address")
    alter_stmt.action = "ADD"
    alter_stmt.column = ColumnDefinitionNode(name="NewCol", data_type="INT")

    bulk_stmt = SqlBulkCopyStatement()
    bulk_stmt.table = IdentifierNode(name="Address")

    set_stmt = SetStatement()
    set_stmt.is_option = False
    set_stmt.target = IdentifierNode(name="@x")
    set_stmt.value = LiteralNode("1", "NUMBER")

    if_stmt = IfStatement()
    if_stmt.condition = LiteralNode("1", "NUMBER")
    if_stmt.then_block = [create_stmt]
    if_stmt.else_block = [alter_stmt]

    exec_stmt = ExecStatement()
    exec_stmt.proc_name = "ProcAsString"
    exec_stmt.return_var = "@ret"
    exec_stmt.named_args = [IdentifierNode(name="@p")]

    merge_clause = MergeClauseNode()
    merge_clause.match_type = "MATCHED"
    merge_clause.action = "UPDATE"
    merge_clause.condition = LiteralNode("1", "NUMBER")
    merge_clause.set_clauses = [AssignmentNode(IdentifierNode(name="City"), LiteralNode("X", "STRING_LITERAL"))]

    merge_stmt = MergeStatement()
    merge_stmt.target = IdentifierNode(name="Address")
    merge_stmt.target_alias = "t"
    merge_stmt.source = IdentifierNode(name="Address")
    merge_stmt.source_alias = "s"
    merge_stmt.on_condition = LiteralNode("1", "NUMBER")
    merge_stmt.clauses = [merge_clause]

    drop_stmt = DropTableStatement()
    drop_stmt.table = IdentifierNode(name="T1")
    drop_stmt.if_exists = True

    script = ScriptNode([
        drop_stmt,
        create_stmt,
        alter_stmt,
        bulk_stmt,
        set_stmt,
        if_stmt,
        exec_stmt,
        merge_stmt,
    ])

    out = v.dump(script)
    assert "DROP_TABLE_STATEMENT" in out
    assert "CREATE_TABLE_STATEMENT" in out
    assert "ALTER_TABLE_STATEMENT" in out
    assert "BULK_COPY_STATEMENT" in out
    assert "SET_STATEMENT" in out
    assert "IF_STATEMENT" in out
    assert "EXEC_STATEMENT" in out
    assert "MERGE_STATEMENT" in out
