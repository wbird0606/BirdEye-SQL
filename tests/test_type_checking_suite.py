import pytest
from birdeye.binder import SemanticError

def run_bind_with_runner(sql, runner):
    """使用全域 Runner 執行完整繫結"""
    return runner.run(sql)["ast"]

# --- 1. 函數參數型別檢查 ---

def test_function_parameter_type_mismatch(global_runner):
    """驗證函數參數型別不匹配時的報警"""
    # Product.ProductID 是 INT，UPPER 預期 NVARCHAR
    sql = "SELECT UPPER(ProductID) FROM Product"
    with pytest.raises(SemanticError, match="Function 'UPPER' expects NVARCHAR"):
        run_bind_with_runner(sql, global_runner)

# --- 2. 運算子型別安全 ---

def test_binary_op_type_mismatch(global_runner):
    """驗證運算子兩側型別家族不相容時的攔截"""
    # Product.Name (NVARCHAR) + 100 (INT)
    sql = "SELECT Name + 100 FROM Product"
    with pytest.raises(SemanticError, match=r"Operator '\+' cannot be applied to"):
        run_bind_with_runner(sql, global_runner)

# --- 3. CASE 分支型別一致性 ---

def test_case_result_consistency(global_runner):
    """🛡️ ZTA 政策：驗證 CASE 所有分支結果型別家族是否相容"""
    # THEN 分支為字串 ('Admin')，ELSE 分支為數值 (999)
    sql = "SELECT CASE WHEN ProductID = 1 THEN 'Admin' ELSE 999 END FROM Product"
    with pytest.raises(SemanticError, match="CASE branches have incompatible types"):
        run_bind_with_runner(sql, global_runner)

def test_arithmetic_on_strings_blocked(global_runner):
    """驗證字串類型禁止進行算術除法"""
    # Name (字串家族) 除以 2 (數值家族)
    sql = "SELECT Name / 2 FROM Product"
    with pytest.raises(SemanticError, match="Operator '/' cannot be applied"):
        run_bind_with_runner(sql, global_runner)
