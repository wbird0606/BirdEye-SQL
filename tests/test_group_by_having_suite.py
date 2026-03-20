import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- 1. 測試環境設置 ---

@pytest.fixture
def agg_reg():
    """建立包含銷售數據的元數據，用於測試聚合邏輯"""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Sales,SaleID,INT\n"
        "Sales,ProductID,INT\n"
        "Sales,Amount,DECIMAL\n"
        "Sales,Region,VARCHAR\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_bind_with_runner(sql, runner):
    """整合 BirdEyeRunner 執行完整驗證"""
    return runner.run(sql)["ast"]

# --- 2. GROUP BY 語法解析測試 (Real Metadata) ---

def test_group_by_parsing(global_runner):
    """驗證 Parser 是否能正確識別真實元數據下的 GROUP BY"""
    # SalesOrderDetail: ProductID, SalesOrderID, LineTotal
    sql = "SELECT ProductID, SUM(LineTotal) FROM SalesOrderDetail GROUP BY ProductID"
    ast = run_bind_with_runner(sql, global_runner)

    assert len(ast.group_by_cols) == 1
    assert ast.group_by_cols[0].name == "ProductID"

# --- 3. HAVING 子句解析測試 (Real Metadata) ---

def test_having_parsing(global_runner):
    """驗證 HAVING 子句是否能正確解析真實元數據下的表達式"""
    sql = "SELECT ProductID FROM SalesOrderDetail GROUP BY ProductID HAVING SUM(LineTotal) > 1000"
    ast = run_bind_with_runner(sql, global_runner)

    assert ast.having_condition is not None
    assert ast.having_condition.operator == ">"

# --- 4. ZTA 聚合安全性校驗 (Real Metadata) ---

def test_error_non_aggregated_column_real_meta(global_runner):
    """🛡️ ZTA 政策：禁止選擇既不在 GROUP BY 中也沒有被聚合的欄位 (真實元數據)"""
    # SalesOrderID 沒被聚合也沒在 GROUP BY 裡，應報錯
    sql = "SELECT ProductID, SalesOrderID FROM SalesOrderDetail GROUP BY ProductID"
    with pytest.raises(SemanticError, match="Column 'SalesOrderID' must appear in the GROUP BY clause"):
        run_bind_with_runner(sql, global_runner)

def test_error_aggregate_in_where_real_meta(global_runner):
    """🛡️ ZTA 政策：禁止在 WHERE 子句中使用聚合函數 (真實元數據)"""
    sql = "SELECT ProductID FROM SalesOrderDetail WHERE SUM(LineTotal) > 100 GROUP BY ProductID"
    with pytest.raises(SemanticError, match="Aggregate functions are not allowed in WHERE clause"):
        run_bind_with_runner(sql, global_runner)

# --- 💡 TDD New: CASE WHEN 中的聚合完整性 ---

def test_error_case_agg_integrity(global_runner):
    """🛡️ ZTA 政策：驗證 CASE 邏輯內部的聚合完整性"""
    # CASE 中的 ELSE LineTotal 未聚合，應攔截
    sql = """
        SELECT CASE 
            WHEN ProductID > 0 THEN SUM(LineTotal) 
            ELSE LineTotal 
        END FROM SalesOrderDetail GROUP BY ProductID
    """
    with pytest.raises(SemanticError, match="Column 'LineTotal' must appear in the GROUP BY clause"):
        run_bind_with_runner(sql, global_runner)

# --- 💡 TDD New: 複雜表達式在 GROUP BY 中的完整性檢查 ---

def test_group_by_complex_expression_integrity(global_runner):
    """驗證當整個表達式 (如函數) 存在於 GROUP BY 中時，其內部欄位不會觸發未聚合錯誤"""
    # SUBSTRING(Name, 1, 5) 既在 SELECT 中，也在 GROUP BY 中
    # 這時不應報錯 Column 'Name' must appear...
    sql = """
        SELECT SUBSTRING(Name, 1, 5) AS ShortName, COUNT(ProductID) 
        FROM Product 
        GROUP BY SUBSTRING(Name, 1, 5)
    """
    # 如果修復成功，這行執行應該順利通過
    ast = run_bind_with_runner(sql, global_runner)
    assert len(ast.columns) == 2