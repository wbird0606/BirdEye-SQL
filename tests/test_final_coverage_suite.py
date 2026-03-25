"""
test_final_coverage_suite.py

補齊所有剩餘未覆蓋行的最終測試套件。

binder.py  : 192, 226, 233, 276, 419-424, 433-434, 438-444, 458-465, 469-470, 540
parser.py  : 456, 522, 524, 582, 593-595, 608, 719, 734, 756, 763-765, 788, 795, 850
lexer.py   : 124, 343-344, 354, 374, 376, 378, 391
reconstructor.py : 218, 222, 224, 262-264
registry.py : 135, 159
serializer.py : 36, 200
visualizer.py : 115, 126, 146-148, 172
intent_extractor.py : 454, 488
"""

import io
import json
import pytest

from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
from birdeye.registry import MetadataRegistry
from birdeye.runner import BirdEyeRunner
from birdeye.serializer import ASTSerializer
from birdeye.reconstructor import ASTReconstructor
from birdeye.visualizer import ASTVisualizer
from birdeye.intent_extractor import IntentExtractor
from birdeye.ast import (
    IdentifierNode, LiteralNode, InsertStatement, CaseExpressionNode,
)


def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


def make_runner(csv_str):
    r = BirdEyeRunner()
    r.load_metadata_from_csv(io.StringIO(csv_str))
    return r


SIMPLE_CSV = (
    "table_name,column_name,data_type\n"
    "Address,AddressID,INT\n"
    "Address,City,NVARCHAR\n"
    "Customer,CustomerID,INT\n"
    "Customer,CompanyName,NVARCHAR\n"
)


# ─────────────────────────────────────────────────────────────────
# binder.py
# ─────────────────────────────────────────────────────────────────

def test_binder_192_qualified_col_not_found_in_cte_virtual_schema():
    """binder.py 192: qualifier resolves to CTE but col is absent → SemanticError."""
    runner = make_runner(SIMPLE_CSV)
    sql = """
        WITH cte AS (SELECT CustomerID FROM Customer)
        SELECT cte.NoSuchCol FROM cte JOIN Address ON cte.CustomerID = Address.AddressID
    """
    with pytest.raises(SemanticError):
        runner.run(sql)


def test_binder_226_single_scope_empty_virtual_schema():
    """binder.py 226: single scope has an empty virtual schema → pass-through (no error)."""
    reg = MetadataRegistry()
    binder = Binder(reg)
    # Temp table registered with empty schema dict
    binder.temp_schemas["#GHOST"] = {}
    binder.scopes.append({"#GHOST": "#GHOST"})
    binder.nullable_stack.append(set())
    node = IdentifierNode(name="AnyCol")
    # Should NOT raise — empty virtual schema = pass-through
    binder._resolve_identifier(node)


def test_binder_233_column_not_found_in_any_scope():
    """binder.py 233: unqualified column not found in any scope → SemanticError."""
    runner = make_runner(SIMPLE_CSV)
    sql = (
        "SELECT NoSuchColAnywhere "
        "FROM Customer JOIN Address ON Customer.CustomerID = Address.AddressID"
    )
    with pytest.raises(SemanticError, match="not found"):
        runner.run(sql)


def test_binder_276_any_all_list_type_mismatch():
    """binder.py 276: ANY/ALL with value list containing incompatible type → SemanticError."""
    runner = make_runner(SIMPLE_CSV)
    sql = "SELECT AddressID FROM Address WHERE AddressID > ANY (1, 'hello')"
    with pytest.raises(SemanticError, match="Incompatible"):
        runner.run(sql)


def test_binder_419_424_bind_if():
    """binder.py 419-424: _bind_if — condition + then/else blocks are all visited."""
    runner = make_runner(SIMPLE_CSV)
    result = runner.run("IF 1=1 SELECT AddressID FROM Address")
    assert result["status"] == "success"


def test_binder_419_424_bind_if_with_else():
    """binder.py 419-424: IF...ELSE — both branches visited."""
    runner = make_runner(SIMPLE_CSV)
    result = runner.run(
        "IF 1=1 SELECT AddressID FROM Address ELSE SELECT City FROM Address"
    )
    assert result["status"] == "success"


def test_binder_433_434_exec_with_args():
    """binder.py 433-434: _bind_exec visits each arg expression."""
    runner = make_runner(SIMPLE_CSV)
    result = runner.run("EXEC SomeProc 1, 2, 3")
    assert result["status"] == "success"


def test_binder_438_444_set_variable():
    """binder.py 438-444: _bind_set updates variable_scope."""
    runner = make_runner(SIMPLE_CSV)
    result = runner.run_script(
        "DECLARE @x INT\nSET @x = 5\nSELECT AddressID FROM Address WHERE AddressID = @x"
    )
    assert result["status"] == "success"


def test_binder_438_444_set_option():
    """binder.py 443-444: SET OPTION path (stmt.is_option=True) visits value expression."""
    runner = make_runner(SIMPLE_CSV)
    result = runner.run("SET NOCOUNT ON")
    assert result["status"] == "success"


def test_binder_458_465_merge():
    """binder.py 458-465: _bind_merge visits on_condition and clause expressions."""
    runner = make_runner(SIMPLE_CSV)
    # Use only literals to avoid scope/column resolution issues in _bind_merge
    sql = "MERGE Address USING Address ON 1 = 1 WHEN MATCHED THEN UPDATE SET AddressID = 1"
    result = runner.run(sql)
    assert result["status"] == "success"


def test_binder_469_470_print():
    """binder.py 469-470: _bind_print visits the expression."""
    runner = make_runner(SIMPLE_CSV)
    result = runner.run("PRINT 'hello world'")
    assert result["status"] == "success"


def test_binder_540_case_else_in_agg_check():
    """binder.py 540: CASE else_expr recurses in _check_agg_integrity."""
    runner = make_runner(SIMPLE_CSV)
    # WHEN/THEN use GROUP BY column or literal (no raise) so ELSE is reached at line 540
    sql = (
        "SELECT CASE WHEN CustomerID > 0 THEN 'yes' ELSE CompanyName END, COUNT(*) "
        "FROM Customer GROUP BY CustomerID"
    )
    with pytest.raises(SemanticError):
        runner.run(sql)


# ─────────────────────────────────────────────────────────────────
# parser.py
# ─────────────────────────────────────────────────────────────────

def test_parser_456_not_without_in_like_between():
    """parser.py 456: NOT followed by unexpected token → SyntaxError."""
    with pytest.raises(SyntaxError, match="Expected LIKE, BETWEEN, or IN after NOT"):
        parse("SELECT * FROM Address WHERE AddressID NOT 5")


def test_parser_522_bitwise_pipe():
    """parser.py 522: '|' bitwise OR operator."""
    ast = parse("SELECT 1 | 2")
    assert ast is not None


def test_parser_524_bitwise_caret():
    """parser.py 524: '^' bitwise XOR operator."""
    ast = parse("SELECT 3 ^ 1")
    assert ast is not None


def test_parser_582_not_in_primary_without_exists():
    """parser.py 582: NOT in primary context not followed by EXISTS → SyntaxError."""
    with pytest.raises(SyntaxError, match="Expected EXISTS after NOT"):
        parse("SELECT (NOT 5) FROM Address")


def test_parser_593_595_bitwise_tilde():
    """parser.py 593-595: '~' unary bitwise NOT."""
    ast = parse("SELECT ~1")
    assert ast is not None


def test_parser_608_unary_minus_on_non_literal():
    """parser.py 608: unary minus on non-literal produces BinaryExpressionNode."""
    ast = parse("SELECT -GETDATE()")
    assert ast is not None


def test_parser_719_else_inside_begin_block():
    """parser.py 719: ELSE token seen inside BEGIN block before END → break."""
    # ELSE appears inside BEGIN block → break at line 719; no END so no trailing-token error
    ast = parse("IF 1=1 BEGIN SELECT 1 ELSE")
    assert ast is not None


def test_parser_756_alter_in_if_block():
    """parser.py 756: ALTER TABLE inside IF block via _parse_single_stmt."""
    ast = parse("IF 1=1 ALTER TABLE Address ADD NewCol INT")
    assert ast is not None


def test_parser_763_765_bulk_insert_in_if_block():
    """parser.py 763-765: BULK INSERT via _parse_single_stmt (IDENTIFIER 'BULK')."""
    ast = parse("IF 1=1 BULK INSERT INTO Address")
    assert ast is not None


def test_parser_788_exec_positional_var_arg():
    """parser.py 788: EXEC @retvar not followed by '=' → pos restored, treated as proc name."""
    # EXEC @var without = means @var is the proc name (not a return variable)
    ast = parse("EXEC @dynamic_proc 1, 2")
    assert ast is not None


def test_parser_850_create_table_if_not_exists_identifier_exists():
    """parser.py 850: CREATE TABLE IF NOT EXISTS where EXISTS is IDENTIFIER token."""
    # Standard path uses KEYWORD_EXISTS; this fallback handles when it's an IDENTIFIER
    # We can cover the normal path since _match may fail and _consume(IDENTIFIER) fires
    ast = parse("CREATE TABLE IF NOT EXISTS #tmp (id INT)")
    assert ast is not None


# ─────────────────────────────────────────────────────────────────
# lexer.py
# ─────────────────────────────────────────────────────────────────

def test_lexer_124_token_repr():
    """lexer.py 124: Token.__repr__ is callable."""
    tokens = Lexer("SELECT 1").tokenize()
    r = repr(tokens[0])
    assert "Token" in r


def test_lexer_343_344_le_operator():
    """lexer.py 343-344: '<=' produces SYMBOL_LE token."""
    tokens = Lexer("WHERE x <= 5").tokenize()
    types = [t.type for t in tokens]
    assert TokenType.SYMBOL_LE in types


def test_lexer_354_exclamation_without_equal():
    """lexer.py 354: '!' not followed by '=' → skip char (no token produced)."""
    # Should not raise
    tokens = Lexer("SELECT 1!2").tokenize()
    assert tokens is not None


def test_lexer_374_376_378_bitwise_tokens():
    """lexer.py 374, 376, 378: '|', '^', '~' produce correct tokens."""
    tokens = Lexer("1 | 2 ^ 3 & ~4").tokenize()
    types = [t.type for t in tokens]
    assert TokenType.SYMBOL_PIPE in types
    assert TokenType.SYMBOL_CARET in types
    assert TokenType.SYMBOL_TILDE in types


def test_lexer_391_unknown_char_skipped():
    """lexer.py 391: unrecognized character → advance (no crash)."""
    tokens = Lexer("SELECT 1 $ 2").tokenize()
    assert tokens is not None


# ─────────────────────────────────────────────────────────────────
# reconstructor.py
# ─────────────────────────────────────────────────────────────────

def test_reconstructor_218_identity_column():
    """reconstructor.py 218: ColumnDefinitionNode with is_identity → IDENTITY in output."""
    ast = parse("CREATE TABLE #tmp (id INT IDENTITY(1,1))")
    data = json.loads(ASTSerializer().to_json(ast))
    sql = ASTReconstructor().to_sql(data)
    assert "IDENTITY" in sql


def test_reconstructor_222_primary_key_column():
    """reconstructor.py 222: ColumnDefinitionNode with is_primary_key → PRIMARY KEY."""
    ast = parse("CREATE TABLE #tmp (id INT PRIMARY KEY)")
    data = json.loads(ASTSerializer().to_json(ast))
    sql = ASTReconstructor().to_sql(data)
    assert "PRIMARY KEY" in sql


def test_reconstructor_224_default_column():
    """reconstructor.py 224: ColumnDefinitionNode with default → DEFAULT in output."""
    ast = parse("CREATE TABLE #tmp (id INT DEFAULT 0)")
    data = json.loads(ASTSerializer().to_json(ast))
    sql = ASTReconstructor().to_sql(data)
    assert "DEFAULT" in sql


def test_reconstructor_262_264_merge_delete_clause():
    """reconstructor.py 262-264: MERGE WHEN MATCHED THEN DELETE."""
    ast = parse("MERGE Address USING Address ON 1 = 1 WHEN MATCHED THEN DELETE")
    data = json.loads(ASTSerializer().to_json(ast))
    sql = ASTReconstructor().to_sql(data)
    assert "DELETE" in sql


# ─────────────────────────────────────────────────────────────────
# registry.py
# ─────────────────────────────────────────────────────────────────

def test_registry_135_bytes_input():
    """registry.py 135: load_from_csv accepts bytes → decoded to utf-8."""
    reg = MetadataRegistry()
    reg.load_from_csv(io.BytesIO(b"table_name,column_name,data_type\nT,C,INT\n"))
    assert reg.has_table("T")
    assert reg.has_column("T", "C")


def test_registry_159_skip_empty_row():
    """registry.py 159: rows with empty table_name or column_name are skipped."""
    reg = MetadataRegistry()
    csv = "table_name,column_name,data_type\n,,\nT,C,INT\n"
    reg.load_from_csv(io.StringIO(csv))
    assert reg.has_table("T")
    assert not reg.has_table("")


# ─────────────────────────────────────────────────────────────────
# serializer.py
# ─────────────────────────────────────────────────────────────────

def test_serializer_36_serialize_tuple():
    """serializer.py 36: _serialize handles a plain Python tuple."""
    s = ASTSerializer()
    lit1 = LiteralNode(value="1", type=TokenType.NUMERIC_LITERAL)
    lit2 = LiteralNode(value="2", type=TokenType.NUMERIC_LITERAL)
    result = s._serialize((lit1, lit2))
    assert isinstance(result, list)
    assert len(result) == 2


def test_serializer_200_if_statement():
    """serializer.py 200: IfStatement serialized with then_block/else_block."""
    ast = parse("IF 1=1 SELECT 1 ELSE SELECT 2")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["node_type"] == "IfStatement"
    assert "then_block" in data
    assert "else_block" in data


# ─────────────────────────────────────────────────────────────────
# visualizer.py
# ─────────────────────────────────────────────────────────────────

def test_visualizer_115_update_with_alias():
    """visualizer.py 115: UpdateStatement with table_alias shown in tree."""
    from birdeye.ast import UpdateStatement, BinaryExpressionNode, AssignmentNode
    stmt = UpdateStatement()
    stmt.table = IdentifierNode(name="Address")
    stmt.table_alias = "a"
    stmt.set_clauses = [AssignmentNode(
        column=IdentifierNode(name="City"),
        expression=LiteralNode(value="X", type=TokenType.STRING_LITERAL)
    )]
    stmt.where_condition = BinaryExpressionNode(
        left=IdentifierNode(name="AddressID"),
        operator="=",
        right=LiteralNode(value="1", type=TokenType.NUMERIC_LITERAL)
    )
    output = ASTVisualizer().dump(stmt)
    assert "UPDATE_STATEMENT" in output
    assert "ALIAS: a" in output


def test_visualizer_126_delete_with_alias():
    """visualizer.py 126: DeleteStatement with table_alias shown in tree."""
    from birdeye.ast import DeleteStatement, BinaryExpressionNode
    stmt = DeleteStatement()
    stmt.table = IdentifierNode(name="Address")
    stmt.table_alias = "a"
    stmt.where_condition = BinaryExpressionNode(
        left=IdentifierNode(name="AddressID"),
        operator="=",
        right=LiteralNode(value="1", type=TokenType.NUMERIC_LITERAL)
    )
    output = ASTVisualizer().dump(stmt)
    assert "DELETE_STATEMENT" in output
    assert "ALIAS: a" in output


def test_visualizer_146_148_insert_values_path():
    """visualizer.py 146-148: InsertStatement with plain values list (not value_rows)."""
    from birdeye.ast import InsertStatement, IdentifierNode as ID
    stmt = InsertStatement()
    stmt.table = ID(name="T")
    stmt.columns = []
    stmt.values = [LiteralNode(value="1", type=TokenType.NUMERIC_LITERAL)]
    stmt.value_rows = []
    stmt.source = None
    output = ASTVisualizer().dump(stmt)
    assert "INSERT_STATEMENT" in output
    assert "VALUES" in output


def test_visualizer_172_case_with_input_expr():
    """visualizer.py 172: CaseExpressionNode with input_expr → _visit(input_expr) called."""
    ast = parse(
        "SELECT CASE CustomerID WHEN 1 THEN 'a' ELSE 'b' END FROM Customer"
    )
    output = ASTVisualizer().dump(ast)
    assert "CASE_EXPRESSION" in output
    # input_expr (CustomerID) is rendered as a child node
    assert "CustomerID" in output


# ─────────────────────────────────────────────────────────────────
# intent_extractor.py
# ─────────────────────────────────────────────────────────────────

def test_binder_462_merge_clause_with_condition():
    """binder.py 462: MERGE clause has AND condition → _visit_expression(clause.condition)."""
    runner = make_runner(SIMPLE_CSV)
    sql = (
        "MERGE Address USING Address ON 1 = 1 "
        "WHEN MATCHED AND 1 = 1 THEN UPDATE SET AddressID = 1"
    )
    result = runner.run(sql)
    assert result["status"] == "success"


def test_parser_638_dot_without_star_raises():
    """parser.py 638/702: 'Address.' followed by keyword → 'Expected identifier'."""
    with pytest.raises(SyntaxError, match="Expected identifier"):
        parse("SELECT Address. FROM Address")


def test_parser_765_unrecognized_token_in_single_stmt():
    """parser.py 765: _parse_single_stmt returns None for unrecognized token."""
    # ROLLBACK is not recognized → _parse_single_stmt returns None (line 765),
    # then parse() raises because the token was not consumed.
    with pytest.raises(SyntaxError, match="Unexpected token"):
        parse("IF 1=1 ROLLBACK")


def test_reconstructor_264_merge_unknown_action():
    """reconstructor.py 264: MERGE clause with non-standard action falls back."""
    rec = ASTReconstructor()
    clause_dict = {
        "node_type": "MergeClauseNode",
        "match_type": "MATCHED",
        "condition": None,
        "action": "UNKNOWN_ACTION",
        "set_clauses": [],
        "insert_columns": [],
        "insert_values": [],
    }
    result = rec.to_sql(clause_dict)
    assert "UNKNOWN_ACTION" in result


def test_intent_extractor_454_three_part_qualifier():
    """intent_extractor.py 454: qualifiers with 2+ parts → (schema, table, col)."""
    extractor = IntentExtractor()
    id_node = {"qualifiers": ["SalesLT", "Customer"], "name": "CustomerID"}
    schema, table, col = extractor._resolve_col(id_node, {})
    assert schema == "SalesLT"
    assert table == "Customer"
    assert col == "CustomerID"


def test_intent_extractor_488_add_with_empty_table():
    """intent_extractor.py 488: _add with empty table returns immediately (no append)."""
    extractor = IntentExtractor()
    extractor._seen = set()
    intents = []
    extractor._add(intents, "", "", "col", "READ")
    assert intents == []
