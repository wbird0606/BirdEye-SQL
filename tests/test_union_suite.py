import pytest
from birdeye.ast import UnionStatement, SelectStatement
from birdeye.binder import SemanticError

def run_bind_with_runner(sql, runner):
    """輔助函式：執行完整流水線並回傳 AST"""
    return runner.run(sql)["ast"]

# --- 1. UNION 語法解析測試 ---

def test_union_parsing_success(global_runner):
    """驗證 Parser 是否能正確識別 UNION 並連結兩個 SELECT"""
    sql = "SELECT AddressID FROM Address UNION SELECT 1"
    ast = run_bind_with_runner(sql, global_runner)
    
    assert isinstance(ast, UnionStatement)
    assert ast.operator == "UNION"
    assert isinstance(ast.left, SelectStatement)
    assert isinstance(ast.right, SelectStatement)

def test_union_all_parsing_success(global_runner):
    """驗證 UNION ALL 語法"""
    sql = "SELECT City FROM Address UNION ALL SELECT 'Taipei'"
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.operator == "UNION ALL"

# --- 2. ZTA 結構安全性驗證 (核心資安點) ---

def test_union_column_count_mismatch(global_runner):
    """🛡️ ZTA 政策：UNION 兩側欄位數量必須完全一致"""
    # 左側 2 欄，右側 1 欄
    sql = "SELECT AddressID, City FROM Address UNION SELECT 1"
    with pytest.raises(SemanticError, match="All queries combined using a UNION operator must have an equal number of expressions"):
        run_bind_with_runner(sql, global_runner)

def test_union_type_compatibility_invalid(global_runner):
    """🛡️ ZTA 政策：UNION 對應位置的欄位型別家族必須相容"""
    # AddressID (INT) 與 'SomeString' (NVARCHAR) 不相容
    sql = "SELECT AddressID FROM Address UNION SELECT 'SomeString'"
    with pytest.raises(SemanticError, match="Incompatible types in UNION"):
        run_bind_with_runner(sql, global_runner)

# --- 3. 遞迴 UNION 測試 ---

def test_union_triple_recursive(global_runner):
    """驗證多重 UNION 的鏈式解析"""
    sql = "SELECT 1 UNION SELECT 2 UNION SELECT 3"
    ast = run_bind_with_runner(sql, global_runner)
    # 預期：Union(Union(Select1, Select2), Select3)
    assert isinstance(ast, UnionStatement)
    assert isinstance(ast.left, UnionStatement)
