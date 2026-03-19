import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser, BinaryExpressionNode, FunctionCallNode

def run_parse_expr_root(sql):
    """輔助函式：解析 SQL 並根據語句類型回傳關鍵表達式節點"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    ast = parser.parse()
    
    # 根據不同的 Statement 類型提取表達式
    if ast.__class__.__name__ == "SelectStatement":
        return ast.columns[0]
    elif ast.__class__.__name__ == "UpdateStatement":
        return ast.set_clauses[0].right  # 取 SET Col = Expr 的 Expr
    elif ast.__class__.__name__ == "InsertStatement":
        return ast.values[0]             # 取第一個寫入值
    elif ast.__class__.__name__ == "DeleteStatement":
        return ast.where_condition       # 取 WHERE 條件
    return None

# --- 1. 基礎算術與優先級 (SELECT) ---

@pytest.mark.parametrize("sql, expected_op", [
    ("SELECT UserID + 100 FROM Users", "+"),
    ("SELECT (1 + 2) * 3 FROM Users", "*"),
])
def test_select_expression_logic(sql, expected_op):
    node = run_parse_expr_root(sql)
    assert node.operator == expected_op

# --- 2. DML 表達式整合測試 (Issue #27, #28) ---

@pytest.mark.parametrize("sql, expected_op, left_name", [
    # UPDATE 中的算術運算
    ("UPDATE Users SET Salary = Salary * 1.1 WHERE ID = 1", "*", "Salary"),
    # DELETE 中的邏輯運算
    ("DELETE FROM Users WHERE Age = 20 OR Status = 'Old'", "OR", None),
    # INSERT 中的函數調用
    ("INSERT INTO Logs VALUES (UPPER('System'))", None, "UPPER"),
])
def test_dml_expression_integration(sql, expected_op, left_name):
    """驗證 DML 語句是否能正確調用表達式解析器"""
    node = run_parse_expr_root(sql)
    
    if expected_op:
        assert isinstance(node, BinaryExpressionNode)
        assert node.operator == expected_op
        if left_name and hasattr(node.left, 'name'):
            assert node.left.name == left_name
    elif left_name:
        # 處理函數調用情況
        assert isinstance(node, FunctionCallNode)
        assert node.name == left_name

# --- 3. 複雜邏輯條件 (ZTA 核心) ---

def test_complex_zta_condition():
    """驗證多層級邏輯運算 (AND/OR) 的嵌套結構"""
    sql = "DELETE FROM Users WHERE ID = 1 AND (Status = 'A' OR Status = 'B')"
    node = run_parse_expr_root(sql)
    
    # 頂層應該是 AND
    assert node.operator == "AND"
    # 右側應該是括號內的 OR
    assert node.right.operator == "OR"
    assert node.right.left.left.name == "Status"

# --- 4. 函數與星號處理 ---

def test_function_with_multiple_args():
    """驗證多參數函數的表達式解析"""
    sql = "SELECT CONCAT(FirstName, ' ', LastName) FROM Users"
    node = run_parse_expr_root(sql)
    assert node.name == "CONCAT"
    assert len(node.args) == 3

def test_count_star_integration():
    """驗證 COUNT(*) 在不同語句中的穩定性"""
    sql = "SELECT COUNT(*) FROM Users"
    node = run_parse_expr_root(sql)
    assert node.name == "COUNT"
    assert node.args[0].name == "*"