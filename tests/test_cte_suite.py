import pytest
from birdeye.ast import SelectStatement, CTENode

def run_bind_with_runner(sql, runner):
    """輔助函式：執行完整流水線並回傳 AST"""
    return runner.run(sql)["ast"]

# --- 1. CTE 語法解析測試 ---

def test_cte_parsing_success(global_runner):
    """驗證 WITH Name AS (...) SELECT ... 語法解析"""
    sql = """
        WITH BasicCTE AS (
            SELECT AddressID, City FROM Address
        )
        SELECT City FROM BasicCTE
    """
    ast = run_bind_with_runner(sql, global_runner)
    
    # 這裡的 ast 可能是 UnionStatement 或 SelectStatement (取決於主查詢)
    # 我們預期 SelectStatement 被增強以持有 ctes 資訊
    target = ast
    while hasattr(target, 'left'): target = target.left # 處理嵌套
    
    assert len(target.ctes) == 1
    assert target.ctes[0].name == "BASICCTE"

# --- 2. ZTA 語意作用域與星號展開 ---

def test_cte_semantic_star_expansion(global_runner):
    """驗證 Binder 能否正確識別 CTE 產出的虛擬表並進行星號展開"""
    sql = """
        WITH SimpleCTE AS (
            SELECT AddressID, City FROM Address
        )
        SELECT * FROM SimpleCTE
    """
    # 如果 Binder 正確將 SimpleCTE 註冊進 Scope，星號展開應產生 2 個欄位
    ast = run_bind_with_runner(sql, global_runner)
    
    # 取得主 SELECT 語句
    main_query = ast
    assert len(main_query.columns) == 2
    assert main_query.columns[0].name == "ADDRESSID"
    assert main_query.columns[1].name == "CITY"

# --- 3. 複雜多重 CTE 測試 ---

def test_multiple_ctes_parsing(global_runner):
    """驗證逗號分隔的多重 CTE 解析"""
    sql = """
        WITH CTE1 AS (SELECT 1 AS A), 
             CTE2 AS (SELECT 2 AS B)
        SELECT A, B FROM CTE1 JOIN CTE2 ON 1=1
    """
    ast = run_bind_with_runner(sql, global_runner)
    assert len(ast.ctes) == 2
    assert ast.ctes[0].name == "CTE1"
    assert ast.ctes[1].name == "CTE2"
