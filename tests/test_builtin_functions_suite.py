"""
Issue #5 (round 3): 內建函數補齊
- NULL 處理函數: ISNULL / COALESCE / NULLIF / IIF
- 數值函數: ABS / CEILING / FLOOR / ROUND / POWER
- 字串函數: REPLACE / LTRIM / RTRIM / CHARINDEX
- 日期函數: YEAR / MONTH / DAY / DATEADD / DATEDIFF / DATEPART
- 日期部分識別符 (DAY/MONTH/YEAR/...) 不誤判為欄位
TDD 測試套件
"""
import pytest
from birdeye.binder import SemanticError


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
