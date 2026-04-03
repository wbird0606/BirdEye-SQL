"""
AST JSON → SQL 重建器測試套件
TDD: Red → Green
"""
import json
import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.serializer import ASTSerializer
from birdeye.reconstructor import ASTReconstructor


def roundtrip(sql: str) -> str:
    """SQL → AST JSON → SQL 往返轉換，回傳重建後的 SQL"""
    tokens = Lexer(sql).tokenize()
    ast = Parser(tokens, sql).parse()
    json_str = ASTSerializer().to_json(ast)
    return ASTReconstructor().to_sql(json.loads(json_str))


# ─────────────────────────────────────────────
# SELECT 基本
# ─────────────────────────────────────────────

def test_select_star():
    sql = roundtrip("SELECT * FROM Address")
    assert "SELECT" in sql and "*" in sql and "Address" in sql

def test_select_columns():
    sql = roundtrip("SELECT AddressID, City FROM Address")
    assert "AddressID" in sql and "City" in sql and "Address" in sql

def test_select_with_alias():
    sql = roundtrip("SELECT AddressID AS ID FROM Address")
    assert "AddressID" in sql and "AS" in sql and "ID" in sql

def test_select_with_table_alias():
    sql = roundtrip("SELECT a.AddressID FROM Address a")
    assert "AddressID" in sql and "Address" in sql

def test_select_distinct():
    sql = roundtrip("SELECT DISTINCT City FROM Address")
    assert "DISTINCT" in sql and "City" in sql

def test_select_top():
    sql = roundtrip("SELECT TOP 10 AddressID FROM Address")
    assert "TOP" in sql and "10" in sql

def test_select_top_percent():
    sql = roundtrip("SELECT TOP 10 PERCENT AddressID FROM Address")
    assert "TOP" in sql and "PERCENT" in sql

# ─────────────────────────────────────────────
# WHERE / 條件表達式
# ─────────────────────────────────────────────

def test_where_condition():
    sql = roundtrip("SELECT AddressID FROM Address WHERE AddressID > 0")
    assert "WHERE" in sql and ">" in sql

def test_where_and():
    sql = roundtrip("SELECT AddressID FROM Address WHERE AddressID > 0 AND City = 'X'")
    assert "AND" in sql

def test_where_is_null():
    sql = roundtrip("SELECT AddressID FROM Address WHERE City IS NULL")
    assert "IS NULL" in sql

def test_where_like():
    sql = roundtrip("SELECT AddressID FROM Address WHERE City LIKE 'A%'")
    assert "LIKE" in sql

def test_where_in_list():
    sql = roundtrip("SELECT AddressID FROM Address WHERE AddressID IN (1, 2, 3)")
    assert "IN" in sql

# ─────────────────────────────────────────────
# JOIN
# ─────────────────────────────────────────────

def test_inner_join():
    sql = roundtrip("SELECT a.AddressID FROM Address a JOIN StateProvince s ON a.StateProvinceID = s.StateProvinceID")
    assert "JOIN" in sql and "ON" in sql

def test_left_join():
    sql = roundtrip("SELECT a.AddressID FROM Address a LEFT JOIN StateProvince s ON a.StateProvinceID = s.StateProvinceID")
    assert "LEFT" in sql and "JOIN" in sql

# ─────────────────────────────────────────────
# GROUP BY / HAVING / ORDER BY
# ─────────────────────────────────────────────

def test_group_by():
    sql = roundtrip("SELECT StateProvinceID, COUNT(*) AS C FROM Address GROUP BY StateProvinceID")
    assert "GROUP BY" in sql

def test_having():
    sql = roundtrip("SELECT StateProvinceID, COUNT(*) AS C FROM Address GROUP BY StateProvinceID HAVING COUNT(*) > 1")
    assert "HAVING" in sql

def test_order_by():
    sql = roundtrip("SELECT AddressID FROM Address ORDER BY AddressID DESC")
    assert "ORDER BY" in sql and "DESC" in sql

def test_offset_fetch():
    sql = roundtrip("SELECT AddressID FROM Address ORDER BY AddressID OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY")
    assert "OFFSET" in sql and "FETCH" in sql

# ─────────────────────────────────────────────
# CASE WHEN
# ─────────────────────────────────────────────

def test_case_when():
    sql = roundtrip("SELECT CASE WHEN AddressID > 0 THEN 'Pos' ELSE 'Zero' END FROM Address")
    assert "CASE" in sql and "WHEN" in sql and "THEN" in sql and "END" in sql

# ─────────────────────────────────────────────
# DML
# ─────────────────────────────────────────────

def test_update():
    sql = roundtrip("UPDATE Address SET City = 'X' WHERE AddressID = 1")
    assert "UPDATE" in sql and "SET" in sql and "WHERE" in sql

def test_delete():
    sql = roundtrip("DELETE FROM Address WHERE AddressID = 1")
    assert "DELETE" in sql and "WHERE" in sql

def test_insert_values():
    sql = roundtrip("INSERT INTO Address (AddressID, City) VALUES (1, 'X')")
    assert "INSERT" in sql and "VALUES" in sql

def test_truncate():
    sql = roundtrip("TRUNCATE TABLE Address")
    assert "TRUNCATE" in sql and "Address" in sql

# ─────────────────────────────────────────────
# UNION / INTERSECT / EXCEPT
# ─────────────────────────────────────────────

def test_union():
    sql = roundtrip("SELECT AddressID FROM Address UNION SELECT AddressID FROM Address")
    assert "UNION" in sql

def test_union_all():
    sql = roundtrip("SELECT AddressID FROM Address UNION ALL SELECT AddressID FROM Address")
    assert "UNION ALL" in sql

def test_intersect():
    sql = roundtrip("SELECT AddressID FROM Address INTERSECT SELECT AddressID FROM Address")
    assert "INTERSECT" in sql

def test_except():
    sql = roundtrip("SELECT AddressID FROM Address EXCEPT SELECT AddressID FROM Address")
    assert "EXCEPT" in sql

# ─────────────────────────────────────────────
# CTE
# ─────────────────────────────────────────────

def test_cte_select():
    sql = roundtrip("WITH CTE AS (SELECT AddressID FROM Address) SELECT AddressID FROM CTE")
    assert "WITH" in sql and "AS" in sql

# ─────────────────────────────────────────────
# CAST / BETWEEN / Functions
# ─────────────────────────────────────────────

def test_cast():
    sql = roundtrip("SELECT CAST(AddressID AS VARCHAR) FROM Address")
    assert "CAST" in sql and "AS" in sql

def test_between():
    sql = roundtrip("SELECT AddressID FROM Address WHERE AddressID BETWEEN 1 AND 100")
    assert "BETWEEN" in sql and "AND" in sql

def test_function_call():
    sql = roundtrip("SELECT LEN(City) FROM Address")
    assert "LEN" in sql

# ─────────────────────────────────────────────
# API: from_json_str
# ─────────────────────────────────────────────

def test_from_json_string():
    """from_json_str 接受 JSON 字串"""
    tokens = Lexer("SELECT AddressID FROM Address").tokenize()
    ast = Parser(tokens, "SELECT AddressID FROM Address").parse()
    json_str = ASTSerializer().to_json(ast)
    sql = ASTReconstructor().from_json_str(json_str)
    assert "SELECT" in sql and "AddressID" in sql

# ─────────────────────────────────────────────
# 窗函數 (Window Functions) - JSON → SQL
# ─────────────────────────────────────────────

def test_window_function_row_number_basic():
    """ROW_NUMBER() OVER - 基本窗函數"""
    sql = roundtrip("SELECT AddressID, ROW_NUMBER() OVER (ORDER BY AddressID) AS rn FROM Address")
    assert "ROW_NUMBER" in sql and "OVER" in sql and "ORDER BY" in sql

def test_window_function_partition_by():
    """ROW_NUMBER() OVER PARTITION BY"""
    sql = roundtrip("SELECT AddressID, ROW_NUMBER() OVER (PARTITION BY PostalCode ORDER BY AddressID) AS rn FROM Address")
    assert "PARTITION BY" in sql and "PostalCode" in sql

def test_window_function_rank():
    """RANK() 窗函數"""
    sql = roundtrip("SELECT RANK() OVER (ORDER BY City) AS rnk FROM Address")
    assert "RANK" in sql and "OVER" in sql

def test_window_function_lag_lead():
    """LAG() 窗函數"""
    sql = roundtrip("SELECT LAG(City) OVER (ORDER BY AddressID) FROM Address")
    assert "LAG" in sql and "OVER" in sql
