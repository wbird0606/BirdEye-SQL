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
    # 案例 1：基礎 SELECT 與 FROM
    ("SELECT UserID FROM Users", 
     ["SELECT_STATEMENT", "COLUMNS", "IDENTIFIER: UserID", "FROM", "IDENTIFIER: Users"]),
    
    # 案例 2：別名掛載驗證
    ("SELECT u.UserID AS ID FROM Users AS u", 
     ["IDENTIFIER: UserID (Qual: u) AS ID", "ALIAS: u"]),
    
    # 案例 3：函數與嵌套參數
    ("SELECT UPPER(UserName) FROM Users", 
     ["FUNCTION: UPPER", "IDENTIFIER: UserName"]),
    
    # 案例 4：複雜 JOIN 與 ON 條件
    ("SELECT u.Name FROM Users u JOIN Orders o ON u.ID = o.UID", 
     ["INNER_JOIN", "IDENTIFIER: Orders", "ALIAS: o", "└── ON", "Qual: u", "Qual: o"]),
    
    # 案例 5：算術運算子與優先級層次
    ("SELECT (Price + 10) * 1.1 FROM Products", 
     ["EXPRESSION: *", "EXPRESSION: +", "LITERAL: 10 (NUMERIC_LITERAL)", "LITERAL: 1.1"]),
    
    # 案例 6：星號展開標記 (ZTA 核心)
    ("SELECT * FROM Users", 
     ["SELECT_STATEMENT", "FROM", "IDENTIFIER: Users"]),
])
def test_visualizer_output_integrity(sql, expected_keywords):
    """
    參數化測試：驗證視覺化工具是否能精確反映 AST 節點資訊
    """
    output = run_visualize(sql)
    
    for keyword in expected_keywords:
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