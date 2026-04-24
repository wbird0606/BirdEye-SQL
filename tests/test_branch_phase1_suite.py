import json

from birdeye.ast import LiteralNode, PrintStatement
from birdeye.lexer import Lexer, TokenType
from birdeye.mermaid_exporter import MermaidExporter
from birdeye.reconstructor import ASTReconstructor
from birdeye.serializer import ASTSerializer


def test_lexer_unmatched_right_paren_tokenizes_without_pop_error():
    tokens = Lexer(")").tokenize()
    assert tokens[0].type == TokenType.SYMBOL_RPAREN
    assert tokens[-1].type == TokenType.EOF


def test_serializer_print_statement_branch():
    stmt = PrintStatement(LiteralNode("hello", TokenType.STRING_LITERAL))
    payload = json.loads(ASTSerializer().to_json(stmt))
    assert payload["node_type"] == "PrintStatement"
    assert payload["expr"]["value"] == "hello"


def test_serializer_unknown_node_falls_through_to_return_only_node_type():
    class DummyNode:
        pass

    payload = ASTSerializer()._serialize(DummyNode())
    assert payload["node_type"] == "DummyNode"


def test_reconstructor_select_offset_without_fetch():
    node = {
        "node_type": "SelectStatement",
        "ctes": [],
        "top": None,
        "top_percent": False,
        "is_distinct": False,
        "is_star": True,
        "columns": [],
        "table": {"node_type": "IdentifierNode", "name": "Address", "qualifiers": []},
        "alias": None,
        "joins": [],
        "applies": [],
        "into_table": None,
        "where": None,
        "group_by": [],
        "having": None,
        "order_by": [],
        "offset_count": 5,
        "fetch_count": None,
    }
    sql = ASTReconstructor().to_sql(node)
    assert "OFFSET 5 ROWS" in sql
    assert "FETCH NEXT" not in sql


def test_reconstructor_literal_already_quoted_and_case_without_else():
    r = ASTReconstructor()
    lit = r._sql_LiteralNode({"node_type": "LiteralNode", "value": "'abc'", "type": "STRING_LITERAL"})
    assert lit == "'abc'"

    case_node = {
        "node_type": "CaseExpressionNode",
        "branches": [
            {
                "when": {"node_type": "LiteralNode", "value": "1", "type": "NUMERIC_LITERAL"},
                "then": {"node_type": "LiteralNode", "value": "ok", "type": "STRING_LITERAL"},
            }
        ],
    }
    case_sql = r._sql_CaseExpressionNode(case_node)
    assert case_sql.startswith("CASE")
    assert "ELSE" not in case_sql


def test_reconstructor_over_clause_without_frame_bounds():
    over_node = {
        "node_type": "OverClauseNode",
        "partition_by": [],
        "order_by": [],
        "frame_type": "ROWS",
        "frame_start": None,
        "frame_end": None,
    }
    sql = ASTReconstructor()._sql_OverClauseNode(over_node)
    assert sql == "OVER (ROWS)"


def test_mermaid_guard_and_missing_child_edge_paths(monkeypatch):
    exporter = MermaidExporter()

    assert exporter._clean_text("") == ""
    assert exporter._build_tree(None) is None
    assert exporter._build_tree("not-a-dict") is None

    original = MermaidExporter._build_tree
    call_depth = {"n": 0}

    def wrapped(self, node):
        call_depth["n"] += 1
        if call_depth["n"] > 1 and isinstance(node, dict) and node.get("force_none"):
            return None
        return original(self, node)

    monkeypatch.setattr(MermaidExporter, "_build_tree", wrapped)

    ast_dict = {
        "node_type": "SelectStatement",
        "table": {"force_none": True},
        "joins": [{"force_none": True}],
    }
    code = exporter.export(ast_dict)
    assert "graph TD" in code
