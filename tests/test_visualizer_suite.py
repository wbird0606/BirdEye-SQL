import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.visualizer import ASTVisualizer

def run_visualize(sql):
    """輔助函式：執行完整的解析與視覺化流程"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    ast = parser.parse()
    viz = ASTVisualizer()
    return viz.dump(ast)

@pytest.mark.parametrize("sql, expected_keywords", [
    # --- 原有的 SELECT 案例 ---
    ("SELECT UserID FROM Users", 
     ["SELECT_STATEMENT", "COLUMNS", "IDENTIFIER: UserID", "FROM", "IDENTIFIER: Users"]),
    
    ("SELECT u.UserID AS ID FROM Users AS u", 
     ["IDENTIFIER: UserID (Qual: u) AS ID", "ALIAS: u"]),

    # --- 修正：移除 "COND"，改以 "WHERE (MANDATORY)" 為準 ---
    ("UPDATE Users SET UserName = 'Bird' WHERE UserID = 1", 
     ["UPDATE_STATEMENT", "TABLE: Users", "SET", "EXPRESSION: =", "WHERE (MANDATORY)"]),

    ("DELETE FROM Users WHERE UserID = 1", 
     ["DELETE_STATEMENT", "FROM: Users", "WHERE (MANDATORY)"]),

    # --- INSERT 與 BulkCopy 維持原狀 ---
    ("INSERT INTO Users (UserID, UserName) VALUES (1, '家維')", 
     ["INSERT_STATEMENT", "INTO: Users", "COLUMNS", "UserID", "UserName", "VALUES", "LITERAL: 1", "LITERAL: 家維"]),

    ("BULK INSERT INTO Logs", 
     ["BULK_COPY_STATEMENT", "TARGET TABLE: Logs"]),

    # --- 邊界案例 ---
    ("DELETE FROM Users WHERE ID = 1 AND Status = 'Old'", 
     ["DELETE_STATEMENT", "EXPRESSION: AND", "EXPRESSION: =", "IDENTIFIER: Status"]),
])
def test_visualizer_output_integrity(sql, expected_keywords):
    """
    參數化測試：驗證視覺化工具是否能精確反映所有 DQL/DML 節點資訊
    """
    output = run_visualize(sql)
    
    for keyword in expected_keywords:
        assert keyword in output, f"在 SQL: {sql} 的輸出中找不到預期標籤 '{keyword}'\n輸出內容：\n{output}"
        assert keyword in output, f"在 SQL: {sql} 的輸出中找不到預期標籤 '{keyword}'\n輸出內容：\n{output}"

def test_visualizer_indentation_logic():
    """
    專門驗證縮排邏輯，確保樹狀結構的層級感
    """
    sql = "SELECT UPPER(Name) FROM Users"
    output = run_visualize(sql)
    
    # 驗證 FUNCTION 下方的參數是否有更深的縮排 (2格 * 層級)
    lines = output.split('\n')
    func_idx = next(i for i, v in enumerate(lines) if "FUNCTION" in v)
    arg_idx = next(i for i, v in enumerate(lines) if "IDENTIFIER: Name" in v)
    
    assert lines[arg_idx].startswith("      "), "函數參數的縮排深度不符合預期"