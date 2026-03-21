import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.visualizer import ASTVisualizer

def run_visualize(sql):
    """
    輔助函式：執行完整的解析與視覺化流程。
    從原始 SQL 字串轉換為格式化的樹狀文字輸出。
    """
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    ast = parser.parse()
    viz = ASTVisualizer()
    return viz.dump(ast)

@pytest.mark.parametrize("sql, expected_keywords", [
    # 1. 基礎 SELECT 與 FROM
    ("SELECT UserID FROM Users", 
     ["SELECT_STATEMENT", "COLUMNS", "IDENTIFIER: UserID", "FROM", "IDENTIFIER: Users"]),
    
    # 2. 別名掛載驗證
    ("SELECT u.UserID AS ID FROM Users AS u", 
     ["IDENTIFIER: UserID (Qual: u) AS ID", "ALIAS: u"]),
    
    # 3. 函數與嵌套參數
    ("SELECT UPPER(UserName) FROM Users", 
     ["FUNCTION: UPPER", "IDENTIFIER: UserName"]),
    
    # 4. 複雜 JOIN 與 ON 條件
    ("SELECT u.Name FROM Users u JOIN Orders o ON u.ID = o.UID", 
     ["INNER_JOIN", "IDENTIFIER: Orders", "ALIAS: o", "└── ON", "Qual: u", "Qual: o"]),
    
    # 5. ZTA 核心防禦：UPDATE 視覺化
    # 驗證是否包含強制性 WHERE 標籤
    ("UPDATE Users SET UserName = 'Bird' WHERE UserID = 1", 
     ["UPDATE_STATEMENT", "TABLE: Users", "SET", "EXPRESSION: =", "WHERE (MANDATORY)"]),
    
    # 6. ZTA 核心防禦：DELETE 視覺化
    ("DELETE FROM Users WHERE UserID = 1", 
     ["DELETE_STATEMENT", "FROM: Users", "WHERE (MANDATORY)"]),
    
    # 7. INSERT 語句結構
    ("INSERT INTO Users (UserID, UserName) VALUES (1, '家維')", 
     ["INSERT_STATEMENT", "INTO: Users", "COLUMNS", "UserID", "UserName", "VALUES", "LITERAL: 1"]),
    
    # 8. BulkCopy 映射驗證
    ("BULK INSERT INTO Logs", 
     ["BULK_COPY_STATEMENT", "TARGET TABLE: Logs"]),

    # 9. 複合邏輯條件層次
    ("DELETE FROM Users WHERE ID = 1 AND Status = 'Old'", 
     ["DELETE_STATEMENT", "EXPRESSION: AND", "EXPRESSION: =", "IDENTIFIER: Status"]),
])
def test_visualizer_output_integrity(sql, expected_keywords):
    """
    參數化測試：驗證視覺化工具是否能精確反映所有 DQL/DML 節點資訊。
    特別確保 ZTA 安全標籤（如 MANDATORY）被正確渲染。
    """
    output = run_visualize(sql)
    
    for keyword in expected_keywords:
        assert keyword in output, f"在 SQL: {sql} 的輸出中找不到預期標籤 '{keyword}'\n輸出內容：\n{output}"

def run_visualize_full(sql, runner):
    """執行完整流水線並回傳視覺化結果"""
    result = runner.run(sql)
    return result["tree"]

# --- 💡 TDD New: 語意視覺化測試 (Real Metadata & Types) ---

def test_visualizer_type_inference_display(global_runner):
    """驗證視覺化工具是否能顯示 Binder 推導出的數據類型"""
    # AddressID 在元數據中是 int
    sql = "SELECT AddressID FROM Address"
    output = run_visualize_full(sql, global_runner)

    # 預期輸出包含類型資訊
    assert "IDENTIFIER: AddressID" in output
    assert "[Type: INT]" in output

def test_visualizer_function_type_display(global_runner):
    """驗證函數回傳類型是否顯示在視覺化結果中"""
    # GETDATE() 回傳 DATETIME
    sql = "SELECT GETDATE()"
    output = run_visualize_full(sql, global_runner)

    assert "FUNCTION: GETDATE" in output
    assert "[Type: DATETIME]" in output

# --- 💡 TDD New: 進階語法視覺化測試 (Issue #45-48) ---

def test_visualizer_cte_display(global_runner):
    """驗證 CTE (WITH 子句) 的視覺化呈現"""
    sql = "WITH MyCTE AS (SELECT 1 AS A) SELECT A FROM MyCTE"
    output = run_visualize_full(sql, global_runner)
    assert "WITH (CTEs)" in output
    assert "CTE: MYCTE" in output
    assert "SELECT_STATEMENT" in output

def test_visualizer_union_display(global_runner):
    """驗證 UNION 集合運算的視覺化呈現"""
    sql = "SELECT 1 UNION ALL SELECT 2"
    output = run_visualize_full(sql, global_runner)
    assert "SET_OPERATION: UNION ALL" in output
    assert "LEFT" in output
    assert "RIGHT" in output

def test_visualizer_cast_display(global_runner):
    """驗證 CAST 轉型的視覺化呈現"""
    sql = "SELECT CAST(123 AS NVARCHAR)"
    output = run_visualize_full(sql, global_runner)
    assert "CAST TO NVARCHAR" in output
    assert "LITERAL: 123" in output

def test_visualizer_between_display(global_runner):
    """驗證 BETWEEN 範圍比較的視覺化呈現"""
    sql = "SELECT * FROM Address WHERE AddressID BETWEEN 1 AND 10"
    output = run_visualize_full(sql, global_runner)
    assert "EXPRESSION: BETWEEN" in output
    assert "TARGET" in output
    assert "LOW" in output
    assert "HIGH" in output

def test_visualizer_any_list_display(global_runner):
    """驗證 ANY 後接值列表的視覺化呈現 (LIST 標籤)"""
    sql = "SELECT * FROM Address WHERE AddressID > ANY (1, 2, 3)"
    output = run_visualize_full(sql, global_runner)
    assert "EXPRESSION: > ANY" in output
    assert "LIST" in output
    assert "ITEM#1" in output
    assert "LITERAL: 1" in output

# --- Issue #51/#52/#53: 新語句視覺化測試 ---

def test_visualizer_declare_statement():
    """DECLARE 語句應顯示 DECLARE_STATEMENT、變數名稱與型別"""
    output = run_visualize("DECLARE @counter INT")
    assert "DECLARE_STATEMENT" in output
    assert "@counter" in output
    assert "INT" in output

def test_visualizer_declare_with_default():
    """DECLARE @x INT = 0 應同時顯示預設值節點"""
    output = run_visualize("DECLARE @x INT = 0")
    assert "DECLARE_STATEMENT" in output
    assert "DEFAULT" in output
    assert "LITERAL: 0" in output

def test_visualizer_select_into(global_runner):
    """SELECT INTO #table 應顯示 INTO 節點與臨時表名稱"""
    output = run_visualize_full("SELECT AddressID INTO #Temp FROM Address", global_runner)
    assert "INTO: #Temp" in output

def test_visualizer_cross_apply(global_runner):
    """CROSS APPLY 應顯示 CROSS_APPLY 節點與子查詢"""
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    output = run_visualize_full(sql, global_runner)
    assert "CROSS_APPLY" in output
    assert "ALIAS: sub" in output

def test_visualizer_outer_apply(global_runner):
    """OUTER APPLY 應顯示 OUTER_APPLY 節點"""
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "OUTER APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    output = run_visualize_full(sql, global_runner)
    assert "OUTER_APPLY" in output
