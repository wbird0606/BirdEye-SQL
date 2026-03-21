"""
Issue #51: 支援變數宣告 (DECLARE) 與批次分隔符 (GO)
TDD 測試套件

測試分層：
  1. Lexer   - token 識別
  2. Parser  - AST 節點建構
  3. Binder  - 變數作用域語意
  4. Runner  - run_script() 多語句整合
"""
import pytest
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.ast import DeclareStatement


# ─────────────────────────────────────────────
# 工具函式
# ─────────────────────────────────────────────

def tokenize(sql):
    return Lexer(sql).tokenize()

def parse(sql):
    tokens = Lexer(sql).tokenize()
    return Parser(tokens, sql).parse()


# ─────────────────────────────────────────────
# 1. Lexer 測試
# ─────────────────────────────────────────────

def test_lexer_declare_is_keyword():
    """DECLARE 應被識別為 KEYWORD_DECLARE，不是普通 IDENTIFIER"""
    tokens = tokenize("DECLARE @var INT")
    assert tokens[0].type == TokenType.KEYWORD_DECLARE

def test_lexer_at_prefix_is_identifier():
    """@varname 應被識別為 IDENTIFIER，且 value 含 @ 前綴"""
    tokens = tokenize("@myVar")
    assert tokens[0].type == TokenType.IDENTIFIER
    assert tokens[0].value == "@myVar"

def test_lexer_go_is_keyword():
    """GO (單獨出現) 應被識別為 KEYWORD_GO"""
    tokens = tokenize("GO")
    assert tokens[0].type == TokenType.KEYWORD_GO

def test_lexer_go_case_insensitive():
    """go / Go 也應被識別為 KEYWORD_GO"""
    for sql in ("go", "Go", "gO"):
        tokens = tokenize(sql)
        assert tokens[0].type == TokenType.KEYWORD_GO, f"Failed for: {sql!r}"


# ─────────────────────────────────────────────
# 2. Parser 測試
# ─────────────────────────────────────────────

def test_parser_declare_simple():
    """DECLARE @counter INT → DeclareStatement with var_name / var_type"""
    ast = parse("DECLARE @counter INT")
    assert isinstance(ast, DeclareStatement)
    assert ast.var_name == "@counter"
    assert ast.var_type == "INT"

def test_parser_declare_with_size():
    """DECLARE @name NVARCHAR(50) → var_type 為 NVARCHAR，括號內長度被吃掉"""
    ast = parse("DECLARE @name NVARCHAR(50)")
    assert isinstance(ast, DeclareStatement)
    assert ast.var_name == "@name"
    assert ast.var_type == "NVARCHAR"

def test_parser_declare_with_default_value():
    """DECLARE @count INT = 0 → default_value 不為 None"""
    ast = parse("DECLARE @count INT = 0")
    assert isinstance(ast, DeclareStatement)
    assert ast.var_name == "@count"
    assert ast.var_type == "INT"
    assert ast.default_value is not None

def test_parser_declare_with_trailing_semicolon():
    """DECLARE @x INT; 尾端分號不應造成 SyntaxError"""
    ast = parse("DECLARE @x INT;")
    assert isinstance(ast, DeclareStatement)


# ─────────────────────────────────────────────
# 3. Binder / 語意分析測試
# ─────────────────────────────────────────────

def test_binder_declare_registers_variable(global_runner):
    """run_script('DECLARE @id INT') 應成功，不拋出語意錯誤"""
    result = global_runner.run_script("DECLARE @id INT")
    assert result["status"] == "success"

def test_variable_usable_in_where_after_declare(global_runner):
    """
    DECLARE @id INT
    SELECT AddressID FROM Address WHERE AddressID = @id

    @id 已宣告，WHERE 中使用不應拋出 'Column not found'
    """
    script = (
        "DECLARE @id INT\n"
        "SELECT AddressID FROM Address WHERE AddressID = @id"
    )
    result = global_runner.run_script(script)
    assert result["status"] == "success"

def test_undeclared_variable_raises_error(global_runner):
    """使用未宣告的 @x 應拋出 SemanticError"""
    from birdeye.binder import SemanticError
    with pytest.raises(SemanticError):
        global_runner.run_script("SELECT AddressID FROM Address WHERE AddressID = @undeclared")


# ─────────────────────────────────────────────
# 4. Runner.run_script() 整合測試
# ─────────────────────────────────────────────

def test_run_script_go_splits_batches(global_runner):
    """GO 應將腳本分成兩個獨立批次"""
    script = (
        "SELECT AddressID FROM Address\n"
        "GO\n"
        "SELECT City FROM Address"
    )
    result = global_runner.run_script(script)
    assert result["status"] == "success"
    assert len(result["batches"]) == 2

def test_run_script_semicolon_splits_statements(global_runner):
    """分號應分隔同一批次內的多個語句"""
    script = "DECLARE @id INT; SELECT AddressID FROM Address WHERE AddressID = @id"
    result = global_runner.run_script(script)
    assert result["status"] == "success"
    # 同一批次下有 2 個語句
    assert len(result["batches"][0]) == 2

def test_variable_scope_persists_across_go_batches(global_runner):
    """
    第一批次 DECLARE @id INT
    GO
    第二批次 SELECT ... WHERE AddressID = @id
    變數作用域應跨批次保留
    """
    script = (
        "DECLARE @id INT\n"
        "GO\n"
        "SELECT AddressID FROM Address WHERE AddressID = @id"
    )
    result = global_runner.run_script(script)
    assert result["status"] == "success"
