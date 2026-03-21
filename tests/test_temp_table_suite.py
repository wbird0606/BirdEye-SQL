import pytest
from birdeye.ast import SelectStatement, IdentifierNode

def run_bind_with_runner(sql, runner):
    """輔助函式：執行完整流水線並回傳 AST"""
    return runner.run(sql)["ast"]

# --- 1. SELECT INTO 語法解析測試 ---

def test_select_into_temp_table_parsing(global_runner):
    """驗證 SELECT ... INTO #Temp 語法解析"""
    sql = "SELECT AddressID, City INTO #MyTemp FROM Address"
    ast = run_bind_with_runner(sql, global_runner)
    
    assert ast.into_table is not None
    assert ast.into_table.name == "#MyTemp"
    assert ast.table.name == "Address"

# --- 2. 標識符 # 前綴支援測試 ---

def test_lexer_supports_hash_prefix(global_runner):
    """驗證 Lexer 是否允許標識符以 # 開頭 (臨時表規範)"""
    sql = "SELECT * FROM #TempTable"
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.table.name == "#TempTable"

# --- 3. 語意註冊測試 (進階) ---

def test_temp_table_scope_registration(global_runner):
    """
    驗證 SELECT INTO 之後，臨時表是否被註冊進作用域。
    這模擬了連續語句的行為。
    """
    # 1. 建立臨時表
    sql1 = "SELECT AddressID, City INTO #T1 FROM Address"
    global_runner.run(sql1)
    
    # 2. 查詢該臨時表
    sql2 = "SELECT AddressID FROM #T1"
    # 如果修復成功，這行不會報 "Table #T1 not found"
    result = global_runner.run(sql2)
    assert result["status"] == "success"
