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
    sql = "SELECT AddressID, City FROM Address WHERE AddressID > 0"
    result = runner.run(sql)

    assert "SELECT_STATEMENT" in result["tree"]
    assert "IDENTIFIER: AddressID" in result["tree"]
    assert "graph TD" in result["mermaid"]

    ast = result["ast"]
    assert ast.columns[0].inferred_type == "INT"

# --- 💡 TDD New: 複雜整合案例 ---

def test_join_ambiguity_defense_real_meta(runner):
    """驗證在真實元數據下，JOIN 環境是否強制要求限定符 (ZTA 政策)"""
    sql = """
    SELECT CustomerID
    FROM SalesOrderHeader AS h
    JOIN Customer AS c ON h.CustomerID = c.CustomerID
    """
    with pytest.raises(SemanticError, match="Column 'CustomerID' is ambiguous"):
        runner.run(sql)

def test_update_semantic_check_real_meta(runner):
    """驗證 UPDATE 語句在真實元數據下的欄位檢查"""
    sql = "UPDATE Product SET ListPrice = 99.9 WHERE GhostColumn = 1"
    with pytest.raises(SemanticError, match="Column 'GhostColumn' not found in 'Product'"):
        runner.run(sql)

def test_expression_type_inference_real_meta(runner):
    """驗證複雜表達式在真實元數據下的類型推導"""
    sql = "SELECT UnitPrice * OrderQty FROM SalesOrderDetail"
    result = runner.run(sql)
    assert result["ast"].columns[0].inferred_type == "INT"

def test_zta_enforcement_with_real_metadata(runner):
    """驗證在真實元數據下，ZTA 政策是否依然有效"""
    sql = "SELECT Address.AddressID FROM Address AS a"
    with pytest.raises(SemanticError, match="Original table name 'Address' cannot be used"):
        runner.run(sql)

def test_implicit_date_conversion_real_meta(runner):
    """驗證 DATETIME 類型與字串字面量是否能隱含轉型比較 (TDD Regression)"""
    sql = "SELECT SalesOrderID FROM SalesOrderHeader WHERE OrderDate >= '2023-01-01'"
    result = runner.run(sql)
    assert result["ast"].where_condition.inferred_type == "BIT"

def test_order_by_alias_resolution(runner):
    """驗證 ORDER BY 是否能正確解析 SELECT 中定義的別名 (TDD Regression)"""
    sql = "SELECT (ListPrice - StandardCost) / StandardCost AS ProfitMargin FROM Product ORDER BY ProfitMargin DESC"
    result = runner.run(sql)

    order_node = result["ast"].order_by_terms[0].column
    assert order_node.inferred_type == "INT"

# --- 💡 TDD Legacy Integration: 舊有核心案例回歸 ---

def test_legacy_complex_case_integration(runner):
    """驗證舊有的複雜 CASE WHEN 與類型推導在最新引擎下依然穩定"""
    sql = """
        SELECT CASE
            WHEN ListPrice > 1000 THEN 'Premium'
            ELSE 'Standard'
        END AS Tier
        FROM Product
    """
    result = runner.run(sql)
    assert result["ast"].columns[0].inferred_type == "NVARCHAR"

def test_legacy_multi_join_ambiguity_defense(runner):
    """驗證舊有的多表關聯歧義防禦在最新引擎下依然有效"""
    sql = "SELECT ModifiedDate FROM SalesOrderHeader h JOIN Address a ON h.BillToAddressID = a.AddressID"
    with pytest.raises(SemanticError, match="Column 'ModifiedDate' is ambiguous"):
        runner.run(sql)

def test_legacy_agg_integrity_violation(runner):
    """驗證舊有的聚合完整性檢查 (ZTA 政策) 依然能攔截非法查詢"""
    sql = "SELECT ProductID, Name FROM Product GROUP BY ProductID"
    with pytest.raises(SemanticError, match="Column 'Name' must appear in the GROUP BY clause"):
        runner.run(sql)

def test_legacy_string_escaping_regression(runner):
    """驗證字串轉義邊界 (Issue #5) 依然穩定"""
    sql = "SELECT 'O''Brien' FROM Address"
    result = runner.run(sql)
    assert result["ast"].columns[0].value == "O'Brien"


# --- (from test_cross_issue_integration_suite.py) ---

# ─────────────────────────────────────────────
# #51 × #52: DECLARE + SELECT INTO
# ─────────────────────────────────────────────

def test_declare_var_used_in_select_into_where(global_runner):
    """
    DECLARE @city NVARCHAR(50)
    SELECT City INTO #FilteredAddr FROM Address WHERE City = @city

    @city 已宣告 → WHERE 可使用，SELECT INTO 可成功建立 #FilteredAddr
    """
    script = (
        "DECLARE @city NVARCHAR(50)\n"
        "SELECT City INTO #FilteredAddr FROM Address WHERE City = @city"
    )
    result = global_runner.run_script(script)
    assert result["status"] == "success"
    assert len(result["batches"][0]) == 2

def test_go_batch_select_into_then_query(global_runner):
    """
    第一批: SELECT INTO #BatchTemp
    GO
    第二批: SELECT 直接查詢 #BatchTemp

    GO 分批後，temp_schemas 應跨批次保留
    """
    script = (
        "SELECT AddressID, City INTO #BatchTemp FROM Address\n"
        "GO\n"
        "SELECT AddressID FROM #BatchTemp"
    )
    result = global_runner.run_script(script)
    assert result["status"] == "success"
    assert len(result["batches"]) == 2


# ─────────────────────────────────────────────
# #51 × #53: DECLARE + APPLY
# ─────────────────────────────────────────────

def test_declare_var_visible_in_apply_subquery(global_runner):
    """
    DECLARE @id INT
    SELECT a.City FROM Address a
    CROSS APPLY (SELECT City FROM Address WHERE AddressID = @id) sub

    APPLY 子查詢應能讀到外層 variable_scope 中的 @id
    """
    script = (
        "DECLARE @id INT\n"
        "SELECT a.City FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = @id) sub"
    )
    result = global_runner.run_script(script)
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# #52 × #53: Temp Table + APPLY
# ─────────────────────────────────────────────

def test_temp_table_as_apply_source(global_runner):
    """
    先建立臨時表，再對其使用 CROSS APPLY

    SELECT INTO #T1 建立臨時表
    → SELECT FROM #T1 CROSS APPLY (...) 存取它
    """
    global_runner.run("SELECT AddressID, City INTO #ApplySrc FROM Address")
    sql = (
        "SELECT t.AddressID, sub.City "
        "FROM #ApplySrc t "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = t.AddressID) sub"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# #51 × #54: DECLARE + 進階型別
# ─────────────────────────────────────────────

def test_declare_uniqueidentifier_variable(global_runner):
    """DECLARE @uid UNIQUEIDENTIFIER 應被成功解析與綁定"""
    result = global_runner.run_script("DECLARE @uid UNIQUEIDENTIFIER")
    assert result["status"] == "success"

def test_declare_uniqueidentifier_used_in_where(global_runner):
    """
    DECLARE @uid UNIQUEIDENTIFIER
    SELECT rowguid FROM Address WHERE rowguid = @uid

    @uid (UNIQUEIDENTIFIER) 與 rowguid (UNIQUEIDENTIFIER) 型別相容
    """
    script = (
        "DECLARE @uid UNIQUEIDENTIFIER\n"
        "SELECT rowguid FROM Address WHERE rowguid = @uid"
    )
    result = global_runner.run_script(script)
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# #53 × 既有功能: APPLY + GROUP BY / ORDER BY
# ─────────────────────────────────────────────

def test_apply_with_order_by(global_runner):
    """CROSS APPLY 的結果集可在外層 ORDER BY 中使用"""
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub "
        "ORDER BY a.AddressID"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"

def test_apply_with_where(global_runner):
    """CROSS APPLY 後的外層 WHERE 可存取左側表欄位"""
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub "
        "WHERE a.AddressID > 1"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"

def test_multiple_apply_nodes(global_runner):
    """同一 FROM 子句可包含多個 APPLY，各自的 alias 獨立可見"""
    sql = (
        "SELECT a.AddressID, s1.City, s2.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) s1 "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) s2"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# #53 × #54: APPLY + 進階型別函數
# ─────────────────────────────────────────────

def test_apply_with_advanced_type_function(global_runner):
    """
    CROSS APPLY 子查詢中使用 NEWID() (UNIQUEIDENTIFIER)
    與 rowguid (UNIQUEIDENTIFIER) 比較，型別應相容
    """
    sql = (
        "SELECT a.AddressID "
        "FROM Address a "
        "CROSS APPLY (SELECT rowguid FROM Address WHERE rowguid = NEWID()) sub"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# #53 × 既有功能: CTE + APPLY
# ─────────────────────────────────────────────

def test_cte_combined_with_apply(global_runner):
    """
    WITH CTE AS (SELECT AddressID FROM Address)
    SELECT c.AddressID, sub.City
    FROM CTE c
    CROSS APPLY (SELECT City FROM Address WHERE AddressID = c.AddressID) sub

    CTE 作為 APPLY 的左側來源，子查詢參照 CTE 欄位 (橫向作用域)
    """
    sql = (
        "WITH AddrCTE AS (SELECT AddressID FROM Address) "
        "SELECT c.AddressID, sub.City "
        "FROM AddrCTE c "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = c.AddressID) sub"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# #53 × 既有功能: UNION + APPLY (APPLY 在其中一臂)
# ─────────────────────────────────────────────

def test_union_with_apply_in_one_arm(global_runner):
    """
    UNION 其中一個 SELECT 使用 APPLY，另一個不使用
    兩臂投影欄位數需相同
    """
    sql = (
        "SELECT a.AddressID "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub "
        "UNION "
        "SELECT AddressID FROM Address"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"
