import pytest
from birdeye.ast import CastExpressionNode

def run_bind_with_runner(sql, runner):
    """輔助函式：執行完整流水線並回傳 AST"""
    return runner.run(sql)["ast"]

# --- 1. CAST 語法解析測試 ---

def test_cast_parsing_success(global_runner):
    """驗證 CAST(expr AS type) 是否能被正確解析"""
    sql = "SELECT CAST(ListPrice AS NVARCHAR) FROM Product"
    ast = run_bind_with_runner(sql, global_runner)
    
    node = ast.columns[0]
    assert isinstance(node, CastExpressionNode)
    assert node.target_type == "NVARCHAR"
    # 💡 核心驗證：型別必須被強制更新為 NVARCHAR
    assert node.inferred_type == "NVARCHAR"

def test_convert_parsing_success(global_runner):
    """驗證 CONVERT(type, expr) 是否能被正確解析"""
    sql = "SELECT CONVERT(INT, ListPrice) FROM Product"
    ast = run_bind_with_runner(sql, global_runner)
    
    node = ast.columns[0]
    assert isinstance(node, CastExpressionNode)
    assert node.is_convert is True
    assert node.target_type == "INT"
    assert node.inferred_type == "INT"

# --- 2. CAST 整合運算測試 ---

def test_cast_in_expression(global_runner):
    """驗證 CAST 後的結果是否能參與運算並通過相容性檢查"""
    # 將 ListPrice (MONEY) 轉為 NVARCHAR 後與字串相加
    sql = "SELECT 'Price: ' + CAST(ListPrice AS NVARCHAR) FROM Product"
    # 如果 CAST 成功將型別轉為 NVARCHAR，則字串家族的 '+' 運算應該通過
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.columns[0].inferred_type == "NVARCHAR"
