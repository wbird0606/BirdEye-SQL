import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- 1. 測試環境設置 ---

@pytest.fixture
def agg_reg():
    """建立包含銷售數據的元數據，用於測試聚合邏輯"""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Sales,SaleID,INT\n"
        "Sales,ProductID,INT\n"
        "Sales,Amount,DECIMAL\n"
        "Sales,Region,VARCHAR\n"
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

# --- 2. GROUP BY 語法解析測試 ---

def test_group_by_parsing():
    """驗證 Parser 是否能正確識別 GROUP BY 與多欄位分組"""
    sql = "SELECT Region, SUM(Amount) FROM Sales GROUP BY Region, ProductID"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    
    assert len(ast.group_by_cols) == 2
    assert ast.group_by_cols[0].name == "Region"

# --- 3. HAVING 子句解析測試 ---

def test_having_parsing():
    """驗證 HAVING 子句是否能正確解析表達式"""
    sql = "SELECT Region FROM Sales GROUP BY Region HAVING SUM(Amount) > 1000"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    
    assert ast.having_condition is not None
    assert ast.having_condition.operator == ">"

# --- 4. ZTA 聚合安全性校驗 (核心關鍵) ---

def test_error_non_aggregated_column(agg_reg):
    """
    🛡️ ZTA 政策：禁止選擇既不在 GROUP BY 中也沒有被聚合的欄位。
    這是為了防止語意模糊導致的數據洩漏。
    """
    sql = "SELECT ProductID, Amount FROM Sales GROUP BY ProductID"
    # Amount 沒被聚合也沒在 GROUP BY 裡，應報錯
    with pytest.raises(SemanticError, match="Column 'Amount' must appear in the GROUP BY clause or be used in an aggregate function"):
        run_bind(sql, agg_reg)

def test_error_aggregate_in_where(agg_reg):
    """
    🛡️ ZTA 政策：禁止在 WHERE 子句中使用聚合函數。
    """
    sql = "SELECT Region FROM Sales WHERE SUM(Amount) > 100 GROUP BY Region"
    with pytest.raises(SemanticError, match="Aggregate functions are not allowed in WHERE clause"):
        run_bind(sql, agg_reg)

def test_valid_group_by_binding(agg_reg):
    """驗證合法的分組查詢是否能通過綁定"""
    sql = "SELECT Region, COUNT(SaleID) FROM Sales GROUP BY Region"
    ast = run_bind(sql, agg_reg)
    assert len(ast.columns) == 2