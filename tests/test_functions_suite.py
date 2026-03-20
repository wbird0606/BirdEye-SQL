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

def run_bind_with_runner(sql, runner):
    """整合 BirdEyeRunner 執行完整驗證"""
    return runner.run(sql)["ast"]

# --- 2. 標量函數語意檢查測試 ---

def test_scalar_function_binding(global_runner):
    """驗證常用字串函數是否能正確從內建 Registry 綁定"""
    # 使用 Person 表 (存在於 data/output.csv)
    sql = "SELECT UPPER(FirstName), LEN(Suffix) FROM Person"
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.columns[0].name == "UPPER"
    assert ast.columns[1].name == "LEN"

def test_function_argument_count_mismatch(global_runner):
    """🛡️ ZTA 政策：驗證函數參數數量必須精準匹配"""
    # LEN() 預期 1 個參數
    sql = "SELECT LEN(FirstName, LastName) FROM Person"
    with pytest.raises(SemanticError, match="Function 'LEN' expects 1 arguments, got 2"):
        run_bind_with_runner(sql, global_runner)

# --- 💡 TDD New: 函數參數類型驗證 ---

def test_function_argument_type_mismatch(global_runner):
    """🛡️ ZTA 政策：驗證函數參數類型是否嚴格匹配 (Issue #35)"""
    # SUBSTRING(string, start, length) -> NVARCHAR, INT, INT
    # 傳入 SUBSTRING(FirstName, 'A', 'B') 應報錯
    sql = "SELECT SUBSTRING(FirstName, 'A', 'B') FROM Person"
    with pytest.raises(SemanticError, match="Function 'SUBSTRING' expects INT, but got NVARCHAR"):
        run_bind_with_runner(sql, global_runner)

# --- 3. ZTA 安全沙箱測試 (Security Sandboxing) ---

def test_block_unregistered_system_function(global_runner):
    """🛡️ ZTA 核心：禁止調用未在註冊表中的函數"""
    sql = "SELECT GHOST_FUNC(FirstName) FROM Person"
    with pytest.raises(SemanticError, match="Unknown function 'GHOST_FUNC'"):
        run_bind_with_runner(sql, global_runner)

def test_block_sensitive_security_function(global_runner):
    """🛡️ ZTA 政策：明確攔截已知的敏感安全函數 (Restricted List)"""
    # IS_SRVROLEMEMBER 已在 registry.py 的 restricted_functions 中
    sql = "SELECT IS_SRVROLEMEMBER('sysadmin')"
    with pytest.raises(SemanticError, match="Function 'IS_SRVROLEMEMBER' is restricted"):
        run_bind_with_runner(sql, global_runner)

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