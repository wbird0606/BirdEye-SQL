"""
跨 Issue 整合測試套件
驗證 #51(DECLARE/GO) × #52(Temp Table) × #53(APPLY) × #54(進階型別)
的交叉互動是否正常運作。

各 issue 的單元測試只保證自身功能，本套件補齊：
  - 兩個以上 issue 功能同時出現時的正確性
  - run_script 在混合語句下的完整行為
"""
import pytest
from birdeye.binder import SemanticError


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
    # 建立臨時表
    global_runner.run("SELECT AddressID, City INTO #ApplySrc FROM Address")
    # 對臨時表用 APPLY
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
