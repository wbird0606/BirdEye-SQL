"""
Issue #5 (round 5): 字串函數補齊、型別轉換增強、集合運算子、純量子查詢
- CONCAT / FORMAT / SPACE / CHAR / ASCII
- CAST(x AS TYPE(len)) / CONVERT(TYPE(len), expr) / CONVERT(TYPE, expr, style)
- COUNT(DISTINCT col)
- INTERSECT / EXCEPT 集合運算子
- 純量子查詢 (scalar subquery) 作為 SELECT 欄位
TDD 測試套件 — Red → Green
"""
import pytest


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
