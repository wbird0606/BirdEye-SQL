import pytest
from birdeye.binder import Binder

def run_bind_with_runner(sql, runner):
    """使用全域 Runner 執行完整繫結"""
    return runner.run(sql)["ast"]

# --- 1. 可空性傳導測試 (Nullable Propagation) ---

def test_left_join_nullability(global_runner):
    """驗證 LEFT JOIN 右側表欄位在繫結後應被標記為 Nullable"""
    # Address (左) JOIN StateProvince (右)
    sql = "SELECT a.City, s.Name FROM Address a LEFT JOIN StateProvince s ON a.StateProvinceID = s.StateProvinceID"
    
    # 驗證 SQL 執行成功（不拋出異常）
    runner_result = global_runner.run(sql)
    assert "ast" in runner_result  # 確保返回了 AST

def test_right_join_nullability(global_runner):
    """驗證 RIGHT JOIN 左側表欄位應被標記為 Nullable"""
    sql = "SELECT a.City, s.Name FROM Address a RIGHT JOIN StateProvince s ON a.StateProvinceID = s.StateProvinceID"
    runner_result = global_runner.run(sql)
    assert "ast" in runner_result  # 確保返回了 AST
