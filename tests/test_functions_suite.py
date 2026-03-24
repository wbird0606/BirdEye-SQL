import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- (from test_functions_suite.py) ---

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

def run_bind_with_runner(sql, runner):
    """整合 BirdEyeRunner 執行完整驗證"""
    return runner.run(sql)["ast"]

# --- 2. 標量函數語意檢查測試 ---

def test_scalar_function_binding(global_runner):
    """驗證常用字串函數是否能正確從內建 Registry 綁定"""
    sql = "SELECT UPPER(FirstName), LEN(LastName) FROM Customer"
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.columns[0].name == "UPPER"
    assert ast.columns[1].name == "LEN"

def test_function_argument_count_mismatch(global_runner):
    """🛡️ ZTA 政策：驗證函數參數數量必須精準匹配"""
    sql = "SELECT LEN(FirstName, LastName) FROM Customer"
    with pytest.raises(SemanticError, match="Function 'LEN' expects 1 arguments, got 2"):
        run_bind_with_runner(sql, global_runner)

# --- 💡 TDD New: 函數參數類型驗證 ---

def test_function_argument_type_mismatch(global_runner):
    """🛡️ ZTA 政策：驗證函數參數類型是否嚴格匹配 (Issue #35)"""
    sql = "SELECT SUBSTRING(FirstName, 'A', 'B') FROM Customer"
    with pytest.raises(SemanticError, match="Function 'SUBSTRING' expects INT, but got NVARCHAR"):
        run_bind_with_runner(sql, global_runner)

# --- 3. ZTA 安全沙箱測試 (Security Sandboxing) ---

def test_block_unregistered_system_function(global_runner):
    """🛡️ ZTA 核心：禁止調用未在註冊表中的函數"""
    sql = "SELECT GHOST_FUNC(FirstName) FROM Customer"
    with pytest.raises(SemanticError, match="Unknown function 'GHOST_FUNC'"):
        run_bind_with_runner(sql, global_runner)

def test_block_sensitive_security_function(global_runner):
    """🛡️ ZTA 政策：明確攔截已知的敏感安全函數 (Restricted List)"""
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
    ast = run_bind(sql, func_reg)
    assert ast.columns[0].branches[0][1].name == "UPPER"


# --- (from test_builtin_functions_suite.py) ---

# ─────────────────────────────────────────────
# NULL 處理函數
# ─────────────────────────────────────────────

def test_isnull_function(global_runner):
    result = global_runner.run("SELECT ISNULL(City, 'Unknown') FROM Address")
    assert result["status"] == "success"


def test_coalesce_function(global_runner):
    result = global_runner.run("SELECT COALESCE(City, AddressLine1) FROM Address")
    assert result["status"] == "success"


def test_nullif_function(global_runner):
    result = global_runner.run("SELECT NULLIF(City, AddressLine1) FROM Address")
    assert result["status"] == "success"


def test_iif_function(global_runner):
    result = global_runner.run(
        "SELECT IIF(AddressID > 0, 'Positive', 'Zero') FROM Address"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# 數值函數
# ─────────────────────────────────────────────

def test_abs_function(global_runner):
    result = global_runner.run("SELECT ABS(AddressID) FROM Address")
    assert result["status"] == "success"


def test_ceiling_function(global_runner):
    result = global_runner.run("SELECT CEILING(AddressID) FROM Address")
    assert result["status"] == "success"


def test_floor_function(global_runner):
    result = global_runner.run("SELECT FLOOR(AddressID) FROM Address")
    assert result["status"] == "success"


def test_round_function(global_runner):
    result = global_runner.run("SELECT ROUND(AddressID, 0) FROM Address")
    assert result["status"] == "success"


def test_power_function(global_runner):
    result = global_runner.run("SELECT POWER(AddressID, 2) FROM Address")
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# 字串函數
# ─────────────────────────────────────────────

def test_replace_function(global_runner):
    result = global_runner.run("SELECT REPLACE(City, 'a', 'b') FROM Address")
    assert result["status"] == "success"


def test_ltrim_rtrim_function(global_runner):
    result = global_runner.run("SELECT LTRIM(RTRIM(City)) FROM Address")
    assert result["status"] == "success"


def test_charindex_function(global_runner):
    result = global_runner.run("SELECT CHARINDEX('a', City) FROM Address")
    assert result["status"] == "success"


def test_left_right_function(global_runner):
    result = global_runner.run("SELECT LEFT(City, 3), RIGHT(City, 3) FROM Address")
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# 日期函數
# ─────────────────────────────────────────────

def test_year_function(global_runner):
    result = global_runner.run("SELECT YEAR(ModifiedDate) FROM Address")
    assert result["status"] == "success"


def test_month_function(global_runner):
    result = global_runner.run("SELECT MONTH(ModifiedDate) FROM Address")
    assert result["status"] == "success"


def test_day_function(global_runner):
    result = global_runner.run("SELECT DAY(ModifiedDate) FROM Address")
    assert result["status"] == "success"


def test_dateadd_function(global_runner):
    result = global_runner.run(
        "SELECT DATEADD(DAY, 1, ModifiedDate) FROM Address"
    )
    assert result["status"] == "success"


def test_datediff_function(global_runner):
    result = global_runner.run(
        "SELECT DATEDIFF(DAY, ModifiedDate, GETDATE()) FROM Address"
    )
    assert result["status"] == "success"


def test_datepart_function(global_runner):
    result = global_runner.run(
        "SELECT DATEPART(YEAR, ModifiedDate) FROM Address"
    )
    assert result["status"] == "success"


def test_date_part_identifiers_not_column_error(global_runner):
    """DAY/MONTH/YEAR 等日期部分識別符不應被誤判為欄位名稱"""
    for part in ["DAY", "MONTH", "YEAR", "HOUR", "MINUTE", "SECOND"]:
        result = global_runner.run(
            f"SELECT DATEPART({part}, ModifiedDate) FROM Address"
        )
        assert result["status"] == "success", f"DATEPART({part}) failed"


def test_dateadd_various_parts(global_runner):
    """DATEADD 各種日期部分均應成功"""
    for part in ["YEAR", "MONTH", "DAY", "HOUR"]:
        result = global_runner.run(
            f"SELECT DATEADD({part}, 1, ModifiedDate) FROM Address"
        )
        assert result["status"] == "success", f"DATEADD({part}) failed"
