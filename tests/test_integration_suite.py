import pytest
import os
from birdeye.runner import BirdEyeRunner
from birdeye.binder import SemanticError

@pytest.fixture
def runner():
    """初始化 Runner 並載入真實的 data/output.csv"""
    r = BirdEyeRunner()
    csv_path = os.path.join("data", "output.csv")
    with open(csv_path, "r", encoding="utf-8") as f:
        r.load_metadata_from_csv(f)
    return r

def test_full_pipeline_with_real_metadata(runner):
    """
    測試完整流程：載入真實元數據 -> 解析 SQL -> 語意驗證 -> 視覺化。
    目標表：Address (存在於 output.csv 中)
    """
    sql = "SELECT AddressID, City FROM Address WHERE StateProvinceID = 79"
    result = runner.run(sql)
    
    # 驗證輸出是否包含關鍵資訊
    assert "SELECT_STATEMENT" in result["tree"]
    assert "IDENTIFIER: AddressID" in result["tree"]
    assert "graph TD" in result["mermaid"]
    
    # 驗證類型推導 (AddressID 在 CSV 中標記為 int)
    ast = result["ast"]
    assert ast.columns[0].inferred_type == "INT"

# --- 💡 TDD New: 複雜整合案例 ---

def test_join_ambiguity_defense_real_meta(runner):
    """驗證在真實元數據下，JOIN 環境是否強制要求限定符 (ZTA 政策)"""
    # SalesOrderHeader 與 Customer 都有 CustomerID
    sql = """
    SELECT CustomerID 
    FROM SalesOrderHeader AS h
    JOIN Customer AS c ON h.CustomerID = c.CustomerID
    """
    # 預期失敗：CustomerID 具備歧義，未指定 h. 或 c.
    with pytest.raises(SemanticError, match="Column 'CustomerID' is ambiguous"):
        runner.run(sql)

def test_update_semantic_check_real_meta(runner):
    """驗證 UPDATE 語句在真實元數據下的欄位檢查"""
    # Product 表有 ListPrice 欄位，但沒有 GhostColumn
    sql = "UPDATE Product SET ListPrice = 99.9 WHERE GhostColumn = 1"
    with pytest.raises(SemanticError, match="Column 'GhostColumn' not found in 'Product'"):
        runner.run(sql)

def test_expression_type_inference_real_meta(runner):
    """驗證複雜表達式在真實元數據下的類型推導"""
    # SalesOrderDetail: UnitPrice (money), OrderQty (smallint)
    # 運算後應推導為 INT (或數值類型)
    sql = "SELECT UnitPrice * OrderQty FROM SalesOrderDetail"
    result = runner.run(sql)
    assert result["ast"].columns[0].inferred_type == "INT"

def test_zta_enforcement_with_real_metadata(runner):
    """驗證在真實元數據下，ZTA 政策是否依然有效"""
    # 定義別名 'a' 後，禁止使用 'Address'
    sql = "SELECT Address.AddressID FROM Address AS a"
    with pytest.raises(SemanticError, match="Original table name 'Address' cannot be used"):
        runner.run(sql)

def test_implicit_date_conversion_real_meta(runner):
    """驗證 DATETIME 類型與字串字面量是否能隱含轉型比較 (TDD Regression)"""
    # OrderDate (DATETIME) >= '2023-01-01' (NVARCHAR)
    sql = "SELECT SalesOrderID FROM SalesOrderHeader WHERE OrderDate >= '2023-01-01'"
    result = runner.run(sql)
    assert result["ast"].where_condition.inferred_type == "BIT"

def test_order_by_alias_resolution(runner):
    """驗證 ORDER BY 是否能正確解析 SELECT 中定義的別名 (TDD Regression)"""
    # 這裡 ProfitMargin 是別名，不是 Product 表的實體欄位
    sql = "SELECT (ListPrice - StandardCost) / StandardCost AS ProfitMargin FROM Product ORDER BY ProfitMargin DESC"
    # 如果修復成功，這行執行應該順利通過，不拋出 SemanticError: Column 'ProfitMargin' not found
    result = runner.run(sql)
    
    # 驗證 ORDER BY 的欄位推導類型是否正確對應到別名的結果 (INT)
    order_node = result["ast"].order_by_terms[0].column
    assert order_node.inferred_type == "INT"

