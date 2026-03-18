import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# 準備輕量級的 Mock Registry
MOCK_CSV_DATA = """table_name,column_name,data_type
Users,UserID,INT
Users,UserName,VARCHAR
Orders,OrderID,INT
"""

@pytest.fixture
def registry():
    csv_file = io.StringIO(MOCK_CSV_DATA)
    reg = MetadataRegistry()
    reg.load_from_csv(csv_file)
    return reg

def get_ast(sql):
    """輔助函數：快速產生 AST"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    return parser.parse()

def test_binder_valid_columns(registry):
    """測試：合法的表與欄位，Binder 應該靜默通過，不報錯"""
    ast = get_ast("SELECT UserID, UserName FROM Users")
    binder = Binder(registry)
    bound_ast = binder.bind(ast)
    
    assert bound_ast.table.name.upper() == "USERS"
    assert len(bound_ast.columns) == 2

def test_binder_invalid_table(registry):
    """測試：查詢不存在的表，必須精準攔截"""
    ast = get_ast("SELECT UserID FROM GhostTable")
    binder = Binder(registry)

    # 修正 Match 字串以符合 Binder.py 的現狀
    with pytest.raises(SemanticError, match="Table 'GhostTable' not found"):
        binder.bind(ast)

def test_binder_invalid_column(registry):
    """測試：查詢存在的表，但欄位不存在"""
    ast = get_ast("SELECT Password FROM Users")
    binder = Binder(registry)

    # 修正 Match 字串
    with pytest.raises(SemanticError, match="Column 'Password' not found in 'Users'"):
        binder.bind(ast)

def test_binder_expand_star(registry):
    """測試：遇到 SELECT *，必須自動從 Registry 展開所有真實欄位"""
    ast = get_ast("SELECT * FROM Users")
    binder = Binder(registry)
    bound_ast = binder.bind(ast)
    
    # 原本 ast.is_select_star 是 True，且 columns 是空的
    # Bind 之後，columns 應該被填入 UserID 和 UserName
    assert bound_ast.is_select_star is True
    assert len(bound_ast.columns) == 2
    assert bound_ast.columns[0].name.upper() == "USERID"
    assert bound_ast.columns[1].name.upper() == "USERNAME"