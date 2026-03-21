"""
MSSQL 特殊語法邊界測試套件

針對探測測試發現的三個真實 Bug 補充邊界測試：
  Bug-1: 負數字面值 (WHERE id = -1) → SyntaxError
  Bug-2: 全域臨時表 ##TableName → 未正確處理
  Bug-3: APPLY 無別名 → 存取時報錯

TDD: 先寫測試 (Red)，再修 code (Green)。
"""
import pytest
from birdeye.binder import SemanticError
from birdeye.lexer import Lexer
from birdeye.parser import Parser


def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


# --- (from test_mssql_boundary_suite.py) ---

# ─────────────────────────────────────────────
# Bug-1: 負數字面值
# ─────────────────────────────────────────────

def test_negative_literal_in_where(global_runner):
    """WHERE AddressID = -1 應成功解析與綁定"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE AddressID = -1"
    )
    assert result["status"] == "success"


def test_negative_literal_in_select_column(global_runner):
    """SELECT -1 應成功解析 (無 FROM 的純量查詢)"""
    result = global_runner.run("SELECT -1")
    assert result["status"] == "success"


def test_negative_literal_arithmetic(global_runner):
    """SELECT AddressID - -1 FROM Address 應成功解析（雙重負號）"""
    result = global_runner.run(
        "SELECT AddressID - -1 FROM Address"
    )
    assert result["status"] == "success"


def test_negative_literal_parses_to_ast():
    """Parser 應將 -5 解析為帶負號的 LiteralNode 或等效表達式"""
    from birdeye.ast import LiteralNode, BinaryExpressionNode
    ast = parse("SELECT -5")
    col = ast.columns[0]
    is_negative_literal = isinstance(col, LiteralNode) and col.value.startswith("-")
    is_unary_expr = isinstance(col, BinaryExpressionNode) and col.operator == "-"
    assert is_negative_literal or is_unary_expr, (
        f"Expected negative literal or unary minus expression, got {type(col)}: {col}"
    )


# ─────────────────────────────────────────────
# Bug-2: 全域臨時表 ##TableName
# ─────────────────────────────────────────────

def test_global_temp_table_select_into(global_runner):
    """SELECT INTO ##GlobalTemp 應成功，並在 temp_schemas 中注冊"""
    result = global_runner.run(
        "SELECT AddressID, City INTO ##GAddr FROM Address"
    )
    assert result["status"] == "success"


def test_global_temp_table_query_after_creation(global_runner):
    """
    第一次 run(): SELECT INTO ##GT1
    第二次 run(): SELECT FROM ##GT1
    全域臨時表 schema 應跨 run() 保留
    """
    global_runner.run("SELECT AddressID INTO ##GT1 FROM Address")
    result = global_runner.run("SELECT AddressID FROM ##GT1")
    assert result["status"] == "success"


def test_global_temp_table_in_where(global_runner):
    """全域臨時表建立後可在 WHERE 中使用其欄位"""
    global_runner.run("SELECT AddressID, City INTO ##GT2 FROM Address")
    result = global_runner.run(
        "SELECT AddressID FROM ##GT2 WHERE AddressID > 0"
    )
    assert result["status"] == "success"


def test_global_temp_table_in_join(global_runner):
    """全域臨時表可作為 JOIN 的右側資料來源"""
    global_runner.run("SELECT AddressID INTO ##GT3 FROM Address")
    result = global_runner.run(
        "SELECT a.AddressID "
        "FROM Address a "
        "JOIN ##GT3 g ON a.AddressID = g.AddressID"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Bug-3: APPLY 無別名 (no alias)
# ─────────────────────────────────────────────

def test_apply_without_alias_binds_successfully(global_runner):
    """
    CROSS APPLY 不指定別名時，子查詢仍應成功綁定。
    外層 SELECT 只存取左側表欄位，不存取 APPLY 子查詢欄位。
    """
    sql = (
        "SELECT a.AddressID "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID)"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"


def test_apply_without_alias_lateral_scope(global_runner):
    """APPLY 無別名時，子查詢仍可參照外層欄位 (橫向作用域)"""
    sql = (
        "SELECT a.City "
        "FROM Address a "
        "CROSS APPLY (SELECT AddressID FROM Address WHERE City = a.City)"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"


def test_apply_with_unregistered_qualifier_raises_error(global_runner):
    """
    試圖以未定義的 qualifier 存取 APPLY 子查詢欄位應拋出 SemanticError。
    此行為符合 MSSQL 語意：無別名的 APPLY 其欄位不可透過 qualifier 存取。
    """
    sql = (
        "SELECT a.AddressID, ghost.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID)"
    )
    with pytest.raises(SemanticError):
        global_runner.run(sql)


# --- (from test_operators_union_subq_suite.py) ---

# ─────────────────────────────────────────────
# Modulo operator %
# ─────────────────────────────────────────────

def test_modulo_basic(global_runner):
    """AddressID % 2 應成功"""
    result = global_runner.run("SELECT AddressID % 2 FROM Address")
    assert result["status"] == "success"


def test_modulo_in_where(global_runner):
    """WHERE 中使用 % 應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE AddressID % 2 = 0"
    )
    assert result["status"] == "success"


def test_modulo_with_alias(global_runner):
    """% 運算結果附帶 alias 應成功"""
    result = global_runner.run(
        "SELECT AddressID % 10 AS Remainder FROM Address"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Bitwise AND operator &
# ─────────────────────────────────────────────

def test_bitwise_and_basic(global_runner):
    """AddressID & 1 應成功"""
    result = global_runner.run("SELECT AddressID & 1 FROM Address")
    assert result["status"] == "success"


def test_bitwise_and_in_where(global_runner):
    """WHERE 中使用 & 應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE AddressID & 1 = 1"
    )
    assert result["status"] == "success"


def test_bitwise_and_with_alias(global_runner):
    """& 運算結果附帶 alias 應成功"""
    result = global_runner.run(
        "SELECT AddressID & 255 AS Masked FROM Address"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# UNION as derived table
# ─────────────────────────────────────────────

def test_union_as_derived_table(global_runner):
    """FROM (SELECT ... UNION SELECT ...) AS Sub 應成功"""
    result = global_runner.run(
        "SELECT Sub.AddressID FROM "
        "(SELECT AddressID FROM Address UNION SELECT AddressID FROM Address) AS Sub"
    )
    assert result["status"] == "success"


def test_union_all_as_derived_table(global_runner):
    """FROM (SELECT ... UNION ALL SELECT ...) AS Sub 應成功"""
    result = global_runner.run(
        "SELECT Sub.AddressID FROM "
        "(SELECT AddressID FROM Address UNION ALL SELECT AddressID FROM Address) AS Sub"
    )
    assert result["status"] == "success"


def test_union_derived_table_with_where(global_runner):
    """UNION 衍生資料表搭配外層 WHERE 應成功"""
    result = global_runner.run(
        "SELECT Sub.AddressID FROM "
        "(SELECT AddressID FROM Address WHERE StateProvinceID = 1 "
        "UNION SELECT AddressID FROM Address WHERE StateProvinceID = 2) AS Sub "
        "WHERE Sub.AddressID > 0"
    )
    assert result["status"] == "success"


def test_union_derived_table_select_star(global_runner):
    """UNION 衍生資料表搭配 SELECT * 應成功"""
    result = global_runner.run(
        "SELECT * FROM "
        "(SELECT AddressID FROM Address UNION SELECT AddressID FROM Address) AS Sub"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Combined: modulo + bitwise
# ─────────────────────────────────────────────

def test_modulo_and_bitwise_combined(global_runner):
    """同時使用 % 和 & 應成功"""
    result = global_runner.run(
        "SELECT AddressID % 10 AS Mod, AddressID & 255 AS Bits FROM Address"
    )
    assert result["status"] == "success"


# --- (from test_string_set_ops_suite.py) ---

# ─────────────────────────────────────────────
# 字串函數
# ─────────────────────────────────────────────

def test_concat_function(global_runner):
    result = global_runner.run("SELECT CONCAT(City, ', ', AddressLine1) FROM Address")
    assert result["status"] == "success"


def test_concat_two_args(global_runner):
    result = global_runner.run("SELECT CONCAT(City, AddressLine1) FROM Address")
    assert result["status"] == "success"


def test_format_function(global_runner):
    result = global_runner.run("SELECT FORMAT(ModifiedDate, 'yyyy-MM-dd') FROM Address")
    assert result["status"] == "success"


def test_space_function(global_runner):
    result = global_runner.run("SELECT SPACE(5)")
    assert result["status"] == "success"


def test_ascii_function(global_runner):
    result = global_runner.run("SELECT ASCII(City) FROM Address")
    assert result["status"] == "success"


def test_char_function(global_runner):
    result = global_runner.run("SELECT CHAR(65)")
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# CAST / CONVERT 增強
# ─────────────────────────────────────────────

def test_cast_with_length(global_runner):
    """CAST(x AS VARCHAR(10)) 應成功"""
    result = global_runner.run("SELECT CAST(AddressID AS VARCHAR(10)) FROM Address")
    assert result["status"] == "success"


def test_cast_decimal_precision(global_runner):
    """CAST(x AS DECIMAL(18,2)) 應成功"""
    result = global_runner.run("SELECT CAST(AddressID AS DECIMAL(18,2)) FROM Address")
    assert result["status"] == "success"


def test_convert_with_type_length(global_runner):
    """CONVERT(VARCHAR(20), expr) 應成功"""
    result = global_runner.run("SELECT CONVERT(VARCHAR(20), ModifiedDate) FROM Address")
    assert result["status"] == "success"


def test_convert_three_args(global_runner):
    """CONVERT(VARCHAR, expr, style) 應成功"""
    result = global_runner.run("SELECT CONVERT(VARCHAR, ModifiedDate, 120) FROM Address")
    assert result["status"] == "success"


def test_convert_three_args_with_length(global_runner):
    """CONVERT(VARCHAR(20), expr, style) 應成功"""
    result = global_runner.run("SELECT CONVERT(VARCHAR(20), ModifiedDate, 120) FROM Address")
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# COUNT(DISTINCT col)
# ─────────────────────────────────────────────

def test_count_distinct(global_runner):
    """COUNT(DISTINCT col) 應成功"""
    result = global_runner.run("SELECT COUNT(DISTINCT City) FROM Address")
    assert result["status"] == "success"


def test_count_distinct_with_group_by(global_runner):
    """GROUP BY 搭配 COUNT(DISTINCT) 應成功"""
    result = global_runner.run(
        "SELECT StateProvinceID, COUNT(DISTINCT City) AS UniqCities "
        "FROM Address GROUP BY StateProvinceID"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# INTERSECT / EXCEPT
# ─────────────────────────────────────────────

def test_intersect_basic(global_runner):
    """INTERSECT 集合運算子應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address INTERSECT SELECT AddressID FROM Address"
    )
    assert result["status"] == "success"


def test_except_basic(global_runner):
    """EXCEPT 集合運算子應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address EXCEPT SELECT AddressID FROM Address"
    )
    assert result["status"] == "success"


def test_intersect_with_where(global_runner):
    """INTERSECT 搭配 WHERE 應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE StateProvinceID = 1 "
        "INTERSECT "
        "SELECT AddressID FROM Address WHERE StateProvinceID = 2"
    )
    assert result["status"] == "success"


def test_except_as_derived_table(global_runner):
    """EXCEPT 作為衍生資料表應成功"""
    result = global_runner.run(
        "SELECT Sub.AddressID FROM "
        "(SELECT AddressID FROM Address EXCEPT SELECT AddressID FROM Address WHERE StateProvinceID < 0) AS Sub"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# 純量子查詢 (scalar subquery)
# ─────────────────────────────────────────────

def test_scalar_subquery_in_select(global_runner):
    """純量子查詢作為 SELECT 欄位應成功"""
    result = global_runner.run(
        "SELECT (SELECT MAX(AddressID) FROM Address) AS MaxID"
    )
    assert result["status"] == "success"


def test_scalar_subquery_with_table(global_runner):
    """純量子查詢搭配主表應成功"""
    result = global_runner.run(
        "SELECT AddressID, (SELECT MAX(AddressID) FROM Address) AS MaxID "
        "FROM Address"
    )
    assert result["status"] == "success"


def test_correlated_subquery_in_where(global_runner):
    """關聯子查詢在 WHERE IN 中應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address a "
        "WHERE AddressID IN "
        "(SELECT AddressID FROM Address a2 WHERE a2.StateProvinceID = a.StateProvinceID)"
    )
    assert result["status"] == "success"
import pytest


# ─────────────────────────────────────────────
# TRY_CAST
# ─────────────────────────────────────────────

def test_try_cast_basic(global_runner):
    """TRY_CAST(col AS TYPE) 應成功"""
    result = global_runner.run("SELECT TRY_CAST(City AS INT) FROM Address")
    assert result["status"] == "success"


def test_try_cast_numeric(global_runner):
    """TRY_CAST(numeric col AS VARCHAR) 應成功"""
    result = global_runner.run("SELECT TRY_CAST(AddressID AS VARCHAR) FROM Address")
    assert result["status"] == "success"


def test_try_cast_with_length(global_runner):
    """TRY_CAST(col AS VARCHAR(10)) 應成功"""
    result = global_runner.run("SELECT TRY_CAST(AddressID AS VARCHAR(10)) FROM Address")
    assert result["status"] == "success"


def test_try_cast_with_alias(global_runner):
    """TRY_CAST 搭配 alias 應成功"""
    result = global_runner.run(
        "SELECT TRY_CAST(City AS INT) AS NumericCity FROM Address"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# TRY_CONVERT
# ─────────────────────────────────────────────

def test_try_convert_basic(global_runner):
    """TRY_CONVERT(TYPE, expr) 應成功"""
    result = global_runner.run("SELECT TRY_CONVERT(INT, City) FROM Address")
    assert result["status"] == "success"


def test_try_convert_with_style(global_runner):
    """TRY_CONVERT(TYPE, expr, style) 應成功"""
    result = global_runner.run(
        "SELECT TRY_CONVERT(VARCHAR, ModifiedDate, 120) FROM Address"
    )
    assert result["status"] == "success"


def test_try_convert_with_length(global_runner):
    """TRY_CONVERT(VARCHAR(20), expr) 應成功"""
    result = global_runner.run(
        "SELECT TRY_CONVERT(VARCHAR(20), AddressID) FROM Address"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# 巢狀衍生資料表 (nested derived tables)
# ─────────────────────────────────────────────

def test_nested_derived_table_two_levels(global_runner):
    """兩層巢狀衍生資料表應成功"""
    result = global_runner.run(
        "SELECT Outer2.AddressID FROM "
        "(SELECT AddressID FROM (SELECT AddressID FROM Address) AS Inner2) AS Outer2"
    )
    assert result["status"] == "success"


def test_nested_derived_table_with_filter(global_runner):
    """巢狀衍生資料表搭配 WHERE 應成功"""
    result = global_runner.run(
        "SELECT Lvl2.AddressID FROM "
        "(SELECT AddressID FROM "
        "(SELECT AddressID FROM Address WHERE StateProvinceID > 0) AS Lvl1"
        ") AS Lvl2 "
        "WHERE Lvl2.AddressID > 0"
    )
    assert result["status"] == "success"


def test_nested_union_derived_table(global_runner):
    """巢狀 UNION 衍生資料表應成功"""
    result = global_runner.run(
        "SELECT Outer3.AddressID FROM "
        "(SELECT AddressID FROM Address UNION SELECT AddressID FROM Address) AS Outer3"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Bracket-quoted keyword aliases [Outer]
# ─────────────────────────────────────────────

def test_bracket_quoted_outer_alias(global_runner):
    """[Outer] bracket-quoted 別名應成功"""
    result = global_runner.run(
        "SELECT [Outer].AddressID FROM "
        "(SELECT AddressID FROM Address) AS [Outer]"
    )
    assert result["status"] == "success"


def test_bracket_quoted_inner_alias(global_runner):
    """[Inner] bracket-quoted 別名應成功"""
    result = global_runner.run(
        "SELECT [Inner].AddressID FROM "
        "(SELECT AddressID FROM Address) AS [Inner]"
    )
    assert result["status"] == "success"
