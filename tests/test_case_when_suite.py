import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- 1. 測試環境設置 ---

@pytest.fixture
def case_reg():
    """建立包含員工資料的元數據"""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Employees,EmpID,INT\n"
        "Employees,Salary,DECIMAL\n"
        "Employees,DeptID,INT\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_bind(sql, registry):
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

# --- 2. Lexer 關鍵字識別測試 ---

def test_lexer_case_keywords():
    """驗證 Lexer 能識別 CASE 邏輯的所有關鍵字"""
    sql = "CASE WHEN Salary > 100 THEN 'High' ELSE 'Low' END"
    lexer = Lexer(sql)
    tokens = [t.type for t in lexer.tokenize()]
    
    assert TokenType.KEYWORD_CASE in tokens
    assert TokenType.KEYWORD_WHEN in tokens
    assert TokenType.KEYWORD_THEN in tokens
    assert TokenType.KEYWORD_ELSE in tokens
    assert TokenType.KEYWORD_END in tokens

# --- 3. Parser 結構測試 (Parsing) ---

def test_searched_case_parsing():
    """驗證 '搜尋式 CASE' 的解析結構 (CASE WHEN condition THEN ...)"""
    sql = "SELECT CASE WHEN Salary > 5000 THEN 1 ELSE 0 END FROM Employees"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    
    # 預期投影欄位中包含 CaseExpressionNode
    case_node = ast.columns[0]
    assert case_node.__class__.__name__ == "CaseExpressionNode"
    assert len(case_node.branches) == 1
    assert case_node.else_expr is not None

def test_simple_case_parsing():
    """驗證 '簡單式 CASE' 的解析結構 (CASE expr WHEN val THEN ...)"""
    sql = "SELECT CASE DeptID WHEN 1 THEN 'IT' WHEN 2 THEN 'HR' END FROM Employees"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    
    case_node = ast.columns[0]
    # 簡單式 CASE 會帶有 input_expression (DeptID)
    assert case_node.input_expr is not None
    assert case_node.input_expr.name == "DeptID"
    assert len(case_node.branches) == 2

# --- 4. 語意綁定與 ZTA 政策測試 (Semantic) ---

def test_case_semantic_binding(case_reg):
    """驗證 CASE 分支中的標識符是否能正確綁定作用域"""
    sql = "SELECT CASE WHEN e.Salary > 0 THEN e.EmpID END FROM Employees e"
    ast = run_bind(sql, case_reg)
    
    case_node = ast.columns[0]
    # 檢查 WHEN 分支中的 Salary 是否已解析
    condition = case_node.branches[0][0] # (when_expr, then_expr)
    assert condition.left.qualifier == "e"

def test_case_invalid_column_in_branch(case_reg):
    """🛡️ ZTA 政策：CASE 分支中引用不存在的欄位應攔截"""
    sql = "SELECT CASE WHEN UnknownCol = 1 THEN 1 END FROM Employees"
    with pytest.raises(SemanticError, match="Column 'UnknownCol' not found in 'Employees'"):
        run_bind(sql, case_reg)

def test_case_nested_subquery_binding(case_reg):
    """驗證 CASE 內部嵌套子查詢與 Scope Stack 的整合"""
    # 模擬：如果薪水大於平均(子查詢)，標記為 'Bonus'
    sql = """
        SELECT CASE 
            WHEN Salary > (SELECT 5000) THEN 'Bonus' 
            ELSE 'Normal' 
        END FROM Employees
    """
    # 只要 Binder 的 Scope Stack (Issue #32) 有正確運作，這應該能通過
    ast = run_bind(sql, case_reg)
    assert ast.columns[0].branches[0][0].right.__class__.__name__ == "SelectStatement"

# --- 💡 TDD New: CASE 類型一致性測試 ---

def test_case_type_consistency_valid(case_reg):
    """驗證 CASE 分支類型一致時能成功推導"""
    # 所有分支皆為數值
    sql = "SELECT CASE WHEN Salary > 5000 THEN 100 ELSE 0 END FROM Employees"
    ast = run_bind(sql, case_reg)
    assert ast.columns[0].inferred_type == "INT"

def test_case_type_consistency_invalid(case_reg):
    """🛡️ ZTA 政策：CASE 分支類型不相容時應攔截 (如 INT vs VARCHAR)"""
    # THEN 分支為 INT，ELSE 分支為 VARCHAR
    sql = "SELECT CASE WHEN Salary > 5000 THEN 1 ELSE 'Zero' END FROM Employees"
    # 預期失敗：不相容的類型
    with pytest.raises(SemanticError, match="CASE branches have incompatible types"):
        run_bind(sql, case_reg)