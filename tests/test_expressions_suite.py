import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser, BinaryExpressionNode, FunctionCallNode
from birdeye.binder import Binder, SemanticError
from birdeye.ast import BetweenExpressionNode, CastExpressionNode


def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


def run_bind_with_runner(sql, runner):
    """輔助函式：執行完整流水線並回傳 AST"""
    return runner.run(sql)["ast"]


# --- (from test_expression_suite.py) ---

def run_parse_expr_root(sql):
    """輔助函式：解析 SQL 並根據語句類型回傳關鍵表達式節點"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    ast = parser.parse()

    if ast.__class__.__name__ == "SelectStatement":
        return ast.columns[0]
    elif ast.__class__.__name__ == "UpdateStatement":
        return ast.set_clauses[0].right
    elif ast.__class__.__name__ == "InsertStatement":
        return ast.values[0]
    elif ast.__class__.__name__ == "DeleteStatement":
        return ast.where_condition
    return None

# --- 1. 基礎算術與優先級 (SELECT) ---

@pytest.mark.parametrize("sql, top_op, child_op", [
    ("SELECT UserID + 100 FROM Users", "+", None),
    ("SELECT (1 + 2) * 3 FROM Users", "*", "+"),
    # 💡 TDD New: 運算子優先級測試 (應先乘後加，所以頂層是 +)
    ("SELECT 1 + 2 * 3 FROM Users", "+", "*"),
    # 💡 TDD New: 減法與除法測試 (Issue: Parser 遺漏 - 與 /)
    ("SELECT (ListPrice - Cost) / Cost FROM Product", "/", "-"),
])
def test_expression_precedence(sql, top_op, child_op):
    """驗證運算子優先級 (PEMDAS) 是否正確反映在 AST 層級"""
    node = run_parse_expr_root(sql)
    assert node.operator == top_op
    if child_op:
        found = (hasattr(node.left, 'operator') and node.left.operator == child_op) or \
                (hasattr(node.right, 'operator') and node.right.operator == child_op)
        assert found, f"在 SQL: {sql} 的 AST 中找不到預期的子運算子 '{child_op}'"

# --- 2. 比較運算子測試 (New) ---

@pytest.mark.parametrize("sql, expected_op", [
    ("SELECT * FROM Users WHERE Salary > 5000", ">"),
    ("SELECT * FROM Users WHERE Age < 18", "<"),
    ("SELECT * FROM Users WHERE ID >= 10", ">="),
    ("SELECT * FROM Users WHERE Status != 'Active'", "!="),
    ("SELECT * FROM Users WHERE Status <> 'Old'", "<>"),
    # 💡 TDD New: 支援 IS NULL 與 IS NOT NULL 運算子
    ("SELECT * FROM Users WHERE Status IS NULL", "IS NULL"),
    ("SELECT * FROM Users WHERE Status IS NOT NULL", "IS NOT NULL"),
    # 💡 TDD New: 支援 LIKE 運算子
    ("SELECT * FROM Users WHERE Name LIKE '%Bird%'", "LIKE"),
    ("SELECT * FROM Users WHERE Name NOT LIKE 'Cat%'", "NOT LIKE"),
])
def test_comparison_expression(sql, expected_op):
    """驗證比較運算子 (GT, LT, GE, LE, NE) 是否正確解析"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    node = ast.where_condition
    assert isinstance(node, BinaryExpressionNode)
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
        assert isinstance(node, FunctionCallNode)
        assert node.name == left_name

# --- 3. 複雜邏輯條件 (ZTA 核心) ---

def test_complex_zta_condition():
    """驗證多層級邏輯運算 (AND/OR) 的嵌套結構"""
    sql = "DELETE FROM Users WHERE ID = 1 AND (Status = 'A' OR Status = 'B')"
    node = run_parse_expr_root(sql)

    assert node.operator == "AND"
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


# --- (from test_between_suite.py) ---

# --- 1. BETWEEN 語法解析測試 ---

def test_between_parsing_success(global_runner):
    """驗證 Parser 是否能正確識別 BETWEEN 語法並建構三元節點"""
    sql = "SELECT ProductID FROM Product WHERE ListPrice BETWEEN 100 AND 500"
    ast = run_bind_with_runner(sql, global_runner)

    node = ast.where_condition
    assert isinstance(node, BetweenExpressionNode)
    assert node.is_not is False
    assert node.low.value == "100"
    assert node.high.value == "500"

def test_not_between_parsing_success(global_runner):
    """驗證 NOT BETWEEN 的解析"""
    sql = "SELECT ProductID FROM Product WHERE ListPrice NOT BETWEEN 10 AND 20"
    ast = run_bind_with_runner(sql, global_runner)

    node = ast.where_condition
    assert isinstance(node, BetweenExpressionNode)
    assert node.is_not is True

# --- 2. ZTA 型別安全與相容性測試 ---

def test_between_type_compatibility_valid(global_runner):
    """驗證當所有操作數同屬一個家族時應通過 (如 DATES 與 STRS)"""
    sql = "SELECT * FROM SalesOrderHeader WHERE OrderDate BETWEEN '2023-01-01' AND GETDATE()"
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.where_condition.inferred_type == "BIT"

def test_between_type_compatibility_invalid(global_runner):
    """🛡️ ZTA 政策：驗證 BETWEEN 操作數不相容時應攔截"""
    sql = "SELECT * FROM Product WHERE ListPrice BETWEEN 100 AND 'High'"
    with pytest.raises(SemanticError, match="Incompatible types in BETWEEN"):
        run_bind_with_runner(sql, global_runner)

# --- 3. 語法容錯測試 ---

def test_between_missing_and(global_runner):
    """驗證 BETWEEN 語法缺少 AND 時拋出錯誤"""
    sql = "SELECT * FROM Product WHERE ListPrice BETWEEN 100 OR 500"
    with pytest.raises(SyntaxError, match="Expected AND"):
        run_bind_with_runner(sql, global_runner)


# --- (from test_case_when_suite.py) ---

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


# --- (from test_cast_suite.py) ---

# --- 1. CAST 語法解析測試 ---

def test_cast_parsing_success(global_runner):
    """驗證 CAST(expr AS type) 是否能被正確解析"""
    sql = "SELECT CAST(ListPrice AS NVARCHAR) FROM Product"
    ast = run_bind_with_runner(sql, global_runner)

    node = ast.columns[0]
    assert isinstance(node, CastExpressionNode)
    assert node.target_type == "NVARCHAR"
    assert node.inferred_type == "NVARCHAR"

def test_convert_parsing_success(global_runner):
    """驗證 CONVERT(type, expr) 是否能被正確解析"""
    sql = "SELECT CONVERT(INT, ListPrice) FROM Product"
    ast = run_bind_with_runner(sql, global_runner)

    node = ast.columns[0]
    assert isinstance(node, CastExpressionNode)
    assert node.is_convert is True
    assert node.target_type == "INT"
    assert node.inferred_type == "INT"

# --- 2. CAST 整合運算測試 ---

def test_cast_in_expression(global_runner):
    """驗證 CAST 後的結果是否能參與運算並通過相容性檢查"""
    sql = "SELECT 'Price: ' + CAST(ListPrice AS NVARCHAR) FROM Product"
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.columns[0].inferred_type == "NVARCHAR"
