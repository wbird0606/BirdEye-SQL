import pytest

from birdeye.ast import CaseExpressionNode, LiteralNode
from birdeye.lexer import Lexer, Token, TokenType
from birdeye.parser import Parser


def parse_sql(sql: str):
    return Parser(Lexer(sql).tokenize(), sql).parse()


def test_parser_peek_out_of_range_returns_none():
    p = Parser(Lexer("SELECT 1").tokenize(), "SELECT 1")
    assert p._peek(9999) is None


def test_parser_parse_unexpected_end_after_with(monkeypatch):
    tokens = [Token(TokenType.KEYWORD_WITH, "WITH", 0, 4)]
    p = Parser(tokens, "WITH")

    def fake_parse_ctes():
        p.pos = len(tokens)
        return []

    monkeypatch.setattr(p, "_parse_ctes", fake_parse_ctes)
    with pytest.raises(SyntaxError, match="Unexpected end of input"):
        p.parse()


def test_parser_parse_one_statement_unexpected_end_after_with(monkeypatch):
    tokens = [Token(TokenType.KEYWORD_WITH, "WITH", 0, 4)]
    p = Parser(tokens, "WITH")

    def fake_parse_ctes():
        p.pos = len(tokens)
        return []

    monkeypatch.setattr(p, "_parse_ctes", fake_parse_ctes)
    with pytest.raises(SyntaxError, match="Unexpected end of input"):
        p._parse_one_statement()


def test_parser_parse_script_hits_insert_truncate_declare_paths():
    sql = "INSERT INTO Address VALUES (1); TRUNCATE TABLE Address; DECLARE @x INT"
    script = Parser(Lexer(sql).tokenize(), sql).parse_script()
    assert len(script.statements) == 3


def test_parser_join_subquery_requires_alias_branch():
    sql = "SELECT * FROM Address a JOIN (SELECT 1 AS x) ON 1 = 1"
    with pytest.raises(SyntaxError, match="JOIN subquery must have an alias"):
        parse_sql(sql)


def test_parser_join_on_non_binary_condition_branch():
    sql = "SELECT * FROM Address a JOIN Address b ON 1"
    ast = parse_sql(sql)
    assert len(ast.joins) == 1
    assert ast.joins[0].on_left is None
    assert ast.joins[0].on_right is None


def test_parser_contains_identifier_case_false_paths():
    p = Parser([], "")
    case = CaseExpressionNode(input_expr=LiteralNode("1", TokenType.NUMERIC_LITERAL))
    case.branches.append((LiteralNode("2", TokenType.NUMERIC_LITERAL), LiteralNode("3", TokenType.NUMERIC_LITERAL)))
    assert p._contains_identifier(case) is False


def test_parser_primary_unexpected_end_branch():
    p = Parser([], "")
    with pytest.raises(SyntaxError, match="Unexpected end of input"):
        p._parse_primary()


def test_parser_function_call_with_empty_args_branch():
    ast = parse_sql("SELECT F()")
    assert ast is not None


def test_parser_case_without_when_branch_raises():
    with pytest.raises(SyntaxError, match="CASE expression must have at least one WHEN branch"):
        parse_sql("SELECT CASE 1 END")


def test_parser_over_partition_single_item_no_comma_branch():
    ast = parse_sql("SELECT SUM(1) OVER (PARTITION BY AddressID) FROM Address")
    assert ast is not None


def test_parser_over_order_single_item_no_comma_branch():
    ast = parse_sql("SELECT SUM(1) OVER (ORDER BY AddressID) FROM Address")
    assert ast is not None


def test_parser_frame_unbounded_following_branch():
    ast = parse_sql("SELECT SUM(1) OVER (ORDER BY AddressID ROWS UNBOUNDED FOLLOWING) FROM Address")
    assert ast is not None


def test_parser_block_skips_none_statement_branch(monkeypatch):
    sql = "BEGIN SELECT 1 END"
    p = Parser(Lexer(sql).tokenize(), sql)

    def fake_parse_single_stmt():
        # Consume one token to ensure block loop progresses.
        p._advance()
        return None

    monkeypatch.setattr(p, "_parse_single_stmt", fake_parse_single_stmt)
    stmts = p._parse_block()
    assert stmts == [None]


def test_parser_create_table_with_no_columns_branch():
    ast = parse_sql("CREATE TABLE T ()")
    assert ast is not None


def test_parser_column_def_not_without_null_branch():
    ast = parse_sql("CREATE TABLE T (c INT NOT KEY)")
    assert ast is not None


def test_parser_column_def_identity_without_parens_branch():
    ast = parse_sql("CREATE TABLE T (id INT IDENTITY)")
    assert ast is not None


def test_parser_column_def_primary_without_key_branch():
    ast = parse_sql("CREATE TABLE T (id INT PRIMARY)")
    assert ast is not None


def test_parser_drop_table_if_exists_branch():
    ast = parse_sql("DROP TABLE IF EXISTS T")
    assert ast.if_exists is True


def test_parser_alter_drop_column_optional_keyword_branch():
    ast = parse_sql("ALTER TABLE T DROP COLUMN c")
    assert ast.action == "DROP"


def test_parser_merge_update_multiple_set_clauses_continue_loop_branch():
    sql = (
        "MERGE INTO T USING S ON 1=1 "
        "WHEN MATCHED THEN UPDATE SET a=1, b=2"
    )
    ast = parse_sql(sql)
    assert ast.clauses[0].action == "UPDATE"
    assert len(ast.clauses[0].set_clauses) == 2


def test_parser_merge_insert_without_column_list_branch():
    sql = (
        "MERGE INTO T USING S ON 1=1 "
        "WHEN NOT MATCHED THEN INSERT VALUES (1)"
    )
    ast = parse_sql(sql)
    assert ast.clauses[0].action == "INSERT"
    assert len(ast.clauses[0].insert_columns) == 0
