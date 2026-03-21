import pytest
from birdeye.binder import SemanticError

def run_bind_with_runner(sql, runner):
    """使用全域 Runner 執行完整繫結"""
    return runner.run(sql)["ast"]

# --- 1. 基礎 CASE WHEN 解析與繫結 ---

def test_basic_case_binding(global_runner):
    """驗證基礎 CASE WHEN 結構與欄位繫結"""
    sql = "SELECT CASE WHEN AddressID > 100 THEN 'High' ELSE 'Low' END FROM Address"
    ast = run_bind_with_runner(sql, global_runner)
    
    case_node = ast.columns[0]
    assert case_node.__class__.__name__ == "CaseExpressionNode"
    assert case_node.inferred_type == "NVARCHAR"

# --- 2. ZTA 語意防禦測試 ---

def test_case_invalid_column_in_branch(global_runner):
    """🛡️ ZTA 政策：驗證 CASE 分支中引用不存在的欄位應攔截"""
    sql = "SELECT CASE WHEN GhostCol = 1 THEN 1 ELSE 0 END FROM Address"
    with pytest.raises(SemanticError, match="Column 'GhostCol' not found"):
        run_bind_with_runner(sql, global_runner)

def test_case_type_consistency_invalid(global_runner):
    """🛡️ ZTA 政策：驗證 CASE 分支結果型別不相容時應攔截"""
    # THEN 是數值，ELSE 是字串
    sql = "SELECT CASE WHEN AddressID > 0 THEN 1 ELSE 'Zero' END FROM Address"
    with pytest.raises(SemanticError, match="CASE branches have incompatible types"):
        run_bind_with_runner(sql, global_runner)

# --- 3. 進階巢狀與子查詢 ---

def test_case_nested_subquery_binding(global_runner):
    """驗證 CASE 內部嵌套子查詢的語意分析"""
    sql = """
        SELECT CASE 
            WHEN AddressID > (SELECT 100) THEN 'A' 
            ELSE 'B' 
        END FROM Address
    """
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.columns[0].branches[0][0].right.__class__.__name__ == "SelectStatement"
