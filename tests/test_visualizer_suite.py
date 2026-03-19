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

def test_visualizer_indentation_logic():
    """
    專門驗證縮排邏輯，確保樹狀結構具有正確的層級感。
    """
    sql = "SELECT UPPER(Name) FROM Users"
    output = run_visualize(sql)
    
    # 驗證 FUNCTION 下方的參數是否有正確的縮排深度
    lines = output.split('\n')
    try:
        # 尋找包含 IDENTIFIER: Name 的行
        arg_line = next(line for line in lines if "IDENTIFIER: Name" in line)
        # 根據視覺化邏輯，參數應有至少 6 格以上的縮排（層級遞增）
        assert arg_line.startswith("      "), f"函數參數的縮排深度不符合預期：\n{output}"
    except StopIteration:
        pytest.fail("輸出中找不到預期的識別碼節點")