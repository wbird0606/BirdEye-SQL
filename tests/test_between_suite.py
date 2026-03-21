import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
from birdeye.ast import BetweenExpressionNode

def run_bind_with_runner(sql, runner):
    """輔助函式：執行完整流水線並回傳 AST"""
    return runner.run(sql)["ast"]

# --- 1. BETWEEN 語法解析測試 ---

def test_between_parsing_success(global_runner):
    """驗證 Parser 是否能正確識別 BETWEEN 語法並建構三元節點"""
    sql = "SELECT ProductID FROM Product WHERE ListPrice BETWEEN 100 AND 500"
    ast = run_bind_with_runner(sql, global_runner)
    
    node = ast.where_condition
    assert isinstance(node, BetweenExpressionNode)
    assert node.is_not is False
    assert node.low.value == "100"
    assert node.high.value == "500"

def test_not_between_parsing_success(global_runner):
    """驗證 NOT BETWEEN 的解析"""
    sql = "SELECT ProductID FROM Product WHERE ListPrice NOT BETWEEN 10 AND 20"
    ast = run_bind_with_runner(sql, global_runner)
    
    node = ast.where_condition
    assert isinstance(node, BetweenExpressionNode)
    assert node.is_not is True

# --- 2. ZTA 型別安全與相容性測試 ---

def test_between_type_compatibility_valid(global_runner):
    """驗證當所有操作數同屬一個家族時應通過 (如 DATES 與 STRS)"""
    sql = "SELECT * FROM SalesOrderHeader WHERE OrderDate BETWEEN '2023-01-01' AND GETDATE()"
    # 這應該順利通過，因為 DATES 與 STRS/DATES 是相容的
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.where_condition.inferred_type == "BIT"

def test_between_type_compatibility_invalid(global_runner):
    """🛡️ ZTA 政策：驗證 BETWEEN 操作數不相容時應攔截"""
    # ListPrice (MONEY) BETWEEN 100 (INT) AND 'High' (NVARCHAR)
    sql = "SELECT * FROM Product WHERE ListPrice BETWEEN 100 AND 'High'"
    with pytest.raises(SemanticError, match="Incompatible types in BETWEEN"):
        run_bind_with_runner(sql, global_runner)

# --- 3. 語法容錯測試 ---

def test_between_missing_and(global_runner):
    """驗證 BETWEEN 語法缺少 AND 時拋出錯誤"""
    sql = "SELECT * FROM Product WHERE ListPrice BETWEEN 100 OR 500"
    # 目前 Parser 可能會因為找不到 AND 而報錯
    with pytest.raises(SyntaxError, match="Expected AND"):
        run_bind_with_runner(sql, global_runner)
