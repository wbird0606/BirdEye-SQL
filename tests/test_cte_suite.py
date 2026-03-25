import pytest
from birdeye.ast import SelectStatement, CTENode, UpdateStatement, DeleteStatement
from birdeye.binder import SemanticError
from birdeye.lexer import Lexer
from birdeye.parser import Parser


def run_bind_with_runner(sql, runner):
    """輔助函式：執行完整流水線並回傳 AST"""
    return runner.run(sql)["ast"]


def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


# --- (from test_cte_suite.py) ---

# --- 1. CTE 語法解析測試 ---

def test_cte_parsing_success(global_runner):
    """驗證 WITH Name AS (...) SELECT ... 語法解析"""
    sql = """
        WITH BasicCTE AS (
            SELECT AddressID, City FROM Address
        )
        SELECT City FROM BasicCTE
    """
    ast = run_bind_with_runner(sql, global_runner)

    target = ast
    while hasattr(target, 'left'): target = target.left

    assert len(target.ctes) == 1
    assert target.ctes[0].name == "BASICCTE"

# --- 2. ZTA 語意作用域與星號展開 ---

def test_cte_semantic_star_expansion(global_runner):
    """驗證 Binder 能否正確識別 CTE 產出的虛擬表並進行星號展開"""
    sql = """
        WITH SimpleCTE AS (
            SELECT AddressID, City FROM Address
        )
        SELECT * FROM SimpleCTE
    """
    ast = run_bind_with_runner(sql, global_runner)

    main_query = ast
    assert len(main_query.columns) == 2
    assert main_query.columns[0].name == "ADDRESSID"
    assert main_query.columns[1].name == "CITY"

# --- 3. 複雜多重 CTE 測試 ---

def test_multiple_ctes_parsing(global_runner):
    """驗證逗號分隔的多重 CTE 解析"""
    sql = """
        WITH CTE1 AS (SELECT 1 AS A),
             CTE2 AS (SELECT 2 AS B)
        SELECT A, B FROM CTE1 JOIN CTE2 ON 1=1
    """
    ast = run_bind_with_runner(sql, global_runner)
    assert len(ast.ctes) == 2
    assert ast.ctes[0].name == "CTE1"
    assert ast.ctes[1].name == "CTE2"


# --- (from test_cte_dml_suite.py) ---

# ─────────────────────────────────────────────
# CTE + UPDATE
# ─────────────────────────────────────────────

def test_parser_cte_update_has_ctes():
    """WITH CTE ... UPDATE 的 UpdateStatement 應附帶 ctes"""
    ast = parse(
        "WITH CTE AS (SELECT AddressID FROM Address) "
        "UPDATE Address SET City = 'X' WHERE AddressID IN (SELECT AddressID FROM CTE)"
    )
    assert isinstance(ast, UpdateStatement)
    assert hasattr(ast, 'ctes') and len(ast.ctes) == 1
    assert ast.ctes[0].name == "CTE"


def test_cte_update_basic(global_runner):
    """WITH CTE AS (...) UPDATE ... WHERE IN (SELECT FROM CTE) 應成功"""
    result = global_runner.run(
        "WITH CTE AS (SELECT AddressID FROM Address) "
        "UPDATE Address SET City = 'X' WHERE AddressID IN (SELECT AddressID FROM CTE)"
    )
    assert result["status"] == "success"


def test_cte_update_filtered(global_runner):
    """WITH 帶過濾條件的 CTE 用於 UPDATE 應成功"""
    result = global_runner.run(
        "WITH FilteredIDs AS (SELECT AddressID FROM Address WHERE AddressID > 10) "
        "UPDATE Address SET City = 'Updated' "
        "WHERE AddressID IN (SELECT AddressID FROM FilteredIDs)"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# CTE + DELETE
# ─────────────────────────────────────────────

def test_parser_cte_delete_has_ctes():
    """WITH CTE ... DELETE 的 DeleteStatement 應附帶 ctes"""
    ast = parse(
        "WITH CTE AS (SELECT AddressID FROM Address WHERE AddressID < 0) "
        "DELETE FROM Address WHERE AddressID IN (SELECT AddressID FROM CTE)"
    )
    assert isinstance(ast, DeleteStatement)
    assert hasattr(ast, 'ctes') and len(ast.ctes) == 1


def test_cte_delete_basic(global_runner):
    """WITH CTE AS (...) DELETE ... WHERE IN (SELECT FROM CTE) 應成功"""
    result = global_runner.run(
        "WITH CTE AS (SELECT AddressID FROM Address WHERE AddressID < 0) "
        "DELETE FROM Address WHERE AddressID IN (SELECT AddressID FROM CTE)"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Multiple CTEs + DML
# ─────────────────────────────────────────────

def test_multiple_ctes_with_update(global_runner):
    """多個 CTE 搭配 UPDATE 應成功"""
    result = global_runner.run(
        "WITH A AS (SELECT AddressID FROM Address), "
        "B AS (SELECT AddressID FROM Address WHERE AddressID > 5) "
        "UPDATE Address SET City = 'X' "
        "WHERE AddressID IN (SELECT AddressID FROM A) "
        "AND AddressID IN (SELECT AddressID FROM B)"
    )
    assert result["status"] == "success"


def test_cte_not_visible_outside_dml(global_runner):
    """CTE 只在該語句內有效，不應影響後續查詢"""
    global_runner.run(
        "WITH TempCTE AS (SELECT AddressID FROM Address) "
        "UPDATE Address SET City = 'X' WHERE AddressID IN (SELECT AddressID FROM TempCTE)"
    )
    # 下一個 run() TempCTE 不應存在
    with pytest.raises(SemanticError):
        global_runner.run("SELECT AddressID FROM TempCTE")
