import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- 1. 測試環境設置 ---

@pytest.fixture
def func_reg():
    """建立包含函數定義與基礎表的元數據"""
    reg = MetadataRegistry()
    # 載入表結構
    csv_data = "table_name,column_name,data_type\nUsers,UserName,NVARCHAR\nUsers,Password,NVARCHAR\n"
    reg.load_from_csv(io.StringIO(csv_data))
    
    # 💡 模擬 Issue #34 預期新增的函數註冊介面
    # register_function(name, type, min_args, max_args)
    reg.register_function("LEN", "SCALAR", 1, 1)
    reg.register_function("UPPER", "SCALAR", 1, 1)
    reg.register_function("LOWER", "SCALAR", 1, 1)
    reg.register_function("SUBSTRING", "SCALAR", 3, 3)
    reg.register_function("GETDATE", "SCALAR", 0, 0)
    reg.register_function("SUM", "AGGREGATE", 1, 1)
    return reg

def run_bind(sql, registry):
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

# --- 2. 標量函數語意檢查測試 ---

def test_scalar_function_binding(func_reg):
    """驗證常用字串函數是否能正確綁定與解析"""
    sql = "SELECT UPPER(UserName), LEN(Password) FROM Users"
    # 如果 Binder 能從 Registry 讀取定義，這就不會拋出錯誤
    ast = run_bind(sql, func_reg)
    assert ast.columns[0].name == "UPPER"
    assert ast.columns[1].name == "LEN"

def test_function_argument_count_mismatch(func_reg):
    """🛡️ ZTA 政策：驗證函數參數數量必須精準匹配"""
    # LEN() 預期 1 個參數，給 2 個應報錯
    sql = "SELECT LEN(UserName, Password) FROM Users"
    with pytest.raises(SemanticError, match="Function 'LEN' expects 1 arguments, got 2"):
        run_bind(sql, func_reg)

def test_no_arg_function_getdate(func_reg):
    """驗證無參數函數 (如 GETDATE()) 的支援"""
    sql = "SELECT GETDATE() AS Now"
    ast = run_bind(sql, func_reg)
    assert ast.columns[0].name == "GETDATE"
    assert len(ast.columns[0].args) == 0

# --- 3. ZTA 安全沙箱測試 (Security Sandboxing) ---

def test_block_unregistered_system_function(func_reg):
    """🛡️ ZTA 核心：禁止調用未在註冊表中的函數 (防止注入高風險系統函數)"""
    # 假設攻擊者嘗試使用 OPENROWSET 進行跨庫攻擊
    sql = "SELECT * FROM OPENROWSET('SQLNCLI', 'Server=ATTACKER;Trusted_Connection=yes', 'SELECT * FROM sys.tables')"
    # 注意：這可能先在 Parser 報錯，或在 Binder 報錯，取決於實作
    with pytest.raises((SemanticError, SyntaxError)):
        run_bind(sql, func_reg)

def test_block_sensitive_security_function(func_reg):
    """🛡️ ZTA 政策：明確攔截已知的敏感安全函數"""
    sql = "SELECT IS_SRVROLEMEMBER('sysadmin') FROM Users"
    with pytest.raises(SemanticError, match="Function 'IS_SRVROLEMEMBER' is restricted"):
        run_bind(sql, func_reg)

# --- 4. 嵌套與組合測試 ---

def test_nested_functions_and_case(func_reg):
    """驗證函數嵌套在 CASE WHEN 中的複雜場景"""
    sql = """
        SELECT CASE 
            WHEN LEN(UserName) > 5 THEN UPPER(UserName) 
            ELSE LOWER(UserName) 
        END FROM Users
    """
    # 測試 Scope Stack 是否能支撐函數在 CASE 分支中的遞迴綁定
    ast = run_bind(sql, func_reg)
    assert ast.columns[0].branches[0][1].name == "UPPER"