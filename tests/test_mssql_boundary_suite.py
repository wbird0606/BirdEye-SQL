"""
MSSQL 特殊語法邊界測試套件

針對探測測試發現的三個真實 Bug 補充邊界測試：
  Bug-1: 負數字面值 (WHERE id = -1) → SyntaxError
  Bug-2: 全域臨時表 ##TableName → 未正確處理
  Bug-3: APPLY 無別名 → 存取時報錯

TDD: 先寫測試 (Red)，再修 code (Green)。
"""
import pytest
from birdeye.binder import SemanticError
from birdeye.lexer import Lexer
from birdeye.parser import Parser


def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


# ─────────────────────────────────────────────
# Bug-1: 負數字面值
# ─────────────────────────────────────────────

def test_negative_literal_in_where(global_runner):
    """WHERE AddressID = -1 應成功解析與綁定"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE AddressID = -1"
    )
    assert result["status"] == "success"


def test_negative_literal_in_select_column(global_runner):
    """SELECT -1 應成功解析 (無 FROM 的純量查詢)"""
    result = global_runner.run("SELECT -1")
    assert result["status"] == "success"


def test_negative_literal_arithmetic(global_runner):
    """SELECT AddressID - -1 FROM Address 應成功解析（雙重負號）"""
    result = global_runner.run(
        "SELECT AddressID - -1 FROM Address"
    )
    assert result["status"] == "success"


def test_negative_literal_parses_to_ast():
    """Parser 應將 -5 解析為帶負號的 LiteralNode 或等效表達式"""
    from birdeye.ast import LiteralNode, BinaryExpressionNode
    ast = parse("SELECT -5")
    col = ast.columns[0]
    # 允許兩種實作：直接帶負號的 LiteralNode，或 0 - 5 的 BinaryExpressionNode
    is_negative_literal = isinstance(col, LiteralNode) and col.value.startswith("-")
    is_unary_expr = isinstance(col, BinaryExpressionNode) and col.operator == "-"
    assert is_negative_literal or is_unary_expr, (
        f"Expected negative literal or unary minus expression, got {type(col)}: {col}"
    )


# ─────────────────────────────────────────────
# Bug-2: 全域臨時表 ##TableName
# ─────────────────────────────────────────────

def test_global_temp_table_select_into(global_runner):
    """SELECT INTO ##GlobalTemp 應成功，並在 temp_schemas 中注冊"""
    result = global_runner.run(
        "SELECT AddressID, City INTO ##GAddr FROM Address"
    )
    assert result["status"] == "success"


def test_global_temp_table_query_after_creation(global_runner):
    """
    第一次 run(): SELECT INTO ##GT1
    第二次 run(): SELECT FROM ##GT1
    全域臨時表 schema 應跨 run() 保留
    """
    global_runner.run("SELECT AddressID INTO ##GT1 FROM Address")
    result = global_runner.run("SELECT AddressID FROM ##GT1")
    assert result["status"] == "success"


def test_global_temp_table_in_where(global_runner):
    """全域臨時表建立後可在 WHERE 中使用其欄位"""
    global_runner.run("SELECT AddressID, City INTO ##GT2 FROM Address")
    result = global_runner.run(
        "SELECT AddressID FROM ##GT2 WHERE AddressID > 0"
    )
    assert result["status"] == "success"


def test_global_temp_table_in_join(global_runner):
    """全域臨時表可作為 JOIN 的右側資料來源"""
    global_runner.run("SELECT AddressID INTO ##GT3 FROM Address")
    result = global_runner.run(
        "SELECT a.AddressID "
        "FROM Address a "
        "JOIN ##GT3 g ON a.AddressID = g.AddressID"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Bug-3: APPLY 無別名 (no alias)
# ─────────────────────────────────────────────

def test_apply_without_alias_binds_successfully(global_runner):
    """
    CROSS APPLY 不指定別名時，子查詢仍應成功綁定。
    外層 SELECT 只存取左側表欄位，不存取 APPLY 子查詢欄位。
    """
    sql = (
        "SELECT a.AddressID "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID)"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"


def test_apply_without_alias_lateral_scope(global_runner):
    """APPLY 無別名時，子查詢仍可參照外層欄位 (橫向作用域)"""
    sql = (
        "SELECT a.City "
        "FROM Address a "
        "CROSS APPLY (SELECT AddressID FROM Address WHERE City = a.City)"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"


def test_apply_with_unregistered_qualifier_raises_error(global_runner):
    """
    試圖以未定義的 qualifier 存取 APPLY 子查詢欄位應拋出 SemanticError。
    此行為符合 MSSQL 語意：無別名的 APPLY 其欄位不可透過 qualifier 存取。
    """
    sql = (
        "SELECT a.AddressID, ghost.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID)"
    )
    with pytest.raises(SemanticError):
        global_runner.run(sql)
