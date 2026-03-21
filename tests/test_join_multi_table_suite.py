import pytest
from birdeye.binder import SemanticError

def run_bind_with_runner(sql, runner):
    """使用全域 Runner 執行完整繫結"""
    return runner.run(sql)["ast"]

# --- 1. 多表歧義攔截測試 (Ambiguity Defense) ---

def test_multi_table_ambiguity(global_runner):
    """
    驗證歧義攔截：當 ProductID 同時存在於多表，未指定限定符應報錯。
    使用 SalesOrderDetail 與 Product (皆含 ProductID)。
    """
    sql = """
        SELECT ProductID
        FROM SalesOrderDetail d
        JOIN Product p ON d.ProductID = p.ProductID
    """
    with pytest.raises(SemanticError, match="Column 'ProductID' is ambiguous"):
        run_bind_with_runner(sql, global_runner)

# --- 2. ZTA 別名強制失效原則 (Alias Shadowing) ---

def test_alias_invalidation_chain(global_runner):
    """
    驗證 ZTA 政策：定義別名後，禁止以原始表名存取欄位。
    """
    sql = """
        SELECT Address.City
        FROM Address AS a
        JOIN StateProvince AS s ON a.StateProvinceID = s.StateProvinceID
    """
    with pytest.raises(SemanticError, match="Original table name 'Address' cannot be used"):
        run_bind_with_runner(sql, global_runner)

# --- 3. 跨表欄位存在性檢查 ---

def test_multi_table_column_not_found(global_runner):
    """驗證在多表環境下，搜尋不存在的欄位應精確報錯"""
    sql = """
        SELECT d.SalesOrderID, p.GhostCol
        FROM SalesOrderDetail d
        JOIN Product p ON d.ProductID = p.ProductID
    """
    with pytest.raises(SemanticError, match="Column 'GhostCol' not found"):
        run_bind_with_runner(sql, global_runner)
