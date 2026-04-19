"""基於 metadata 的 SQL → JSON → SQL roundtrip 測試。"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from collections import defaultdict

import pytest

from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.serializer import ASTSerializer
from birdeye.reconstructor import ASTReconstructor


METADATA_PATH = Path("data/output.csv")


def _quote_identifier(name: str) -> str:
    if name.replace("_", "").isalnum() and " " not in name and "." not in name:
        return name
    return f"[{name}]"


def _load_metadata_tables() -> dict[str, list[str]]:
    if not METADATA_PATH.exists():
        return {}
    tables: dict[str, list[str]] = {}
    with METADATA_PATH.open("r", encoding="utf-8") as csv_file:
        reader = csv.reader(csv_file)
        for row in reader:
            if not row or len(row) < 4:
                continue
            schema, table_name, column_name, _data_type = row[:4]
            tables.setdefault(f"{schema}.{table_name}", []).append(column_name)
    return tables


def _load_metadata_column_types() -> dict[str, dict[str, str]]:
    if not METADATA_PATH.exists():
        return {}
    tables: dict[str, dict[str, str]] = {}
    with METADATA_PATH.open("r", encoding="utf-8") as csv_file:
        reader = csv.reader(csv_file)
        for row in reader:
            if not row or len(row) < 4:
                continue
            schema, table_name, column_name, data_type = row[:4]
            tables.setdefault(f"{schema}.{table_name}", {})[column_name] = data_type.lower()
    return tables


def _metadata_table_keys() -> list[str]:
    return sorted(_load_metadata_tables().keys())


def _metadata_table_keys_with_min_columns(min_count: int) -> list[str]:
    tables = _load_metadata_tables()
    return sorted(table_key for table_key, columns in tables.items() if len(columns) >= min_count)


def _metadata_table_keys_with_date_columns() -> list[str]:
    table_types = _load_metadata_column_types()
    date_types = {"date", "datetime", "smalldatetime", "timestamp"}
    return sorted(
        table_key
        for table_key, column_types in table_types.items()
        if any(data_type in date_types for data_type in column_types.values())
    )


def _metadata_join_candidates() -> list[tuple[str, str, str]]:
    tables = _load_metadata_tables()
    column_to_tables: dict[str, list[str]] = defaultdict(list)
    for table_key, columns in tables.items():
        for column in columns:
            column_to_tables[column].append(table_key)

    preferred_columns = [
        "CustomerID",
        "AddressID",
        "ProductID",
        "SalesOrderID",
        "ProductCategoryID",
        "ProductModelID",
        "ProductDescriptionID",
        "Description",
        "Culture",
        "Name",
    ]

    candidates: list[tuple[str, str, str]] = []
    for column in preferred_columns:
        tables_with_column = sorted(set(column_to_tables.get(column, [])))
        if len(tables_with_column) < 2:
            continue
        for index, left_table in enumerate(tables_with_column):
            for right_table in tables_with_column[index + 1 :]:
                candidates.append((left_table, right_table, column))
    return candidates


def _split_table_key(table_key: str) -> tuple[str, str]:
    schema, table = table_key.split(".", 1)
    return schema, table


def _build_roundtrip_sql(schema: str, table: str, columns: list[str]) -> str:
    qualified_table = f"{schema}.{_quote_identifier(table)}"
    select_columns = ", ".join(_quote_identifier(column) for column in columns)
    return f"SELECT {select_columns} FROM {qualified_table}"


def _build_aliased_select_sql(schema: str, table: str, columns: list[str], alias: str, top_n: int = 3) -> str:
    table_ref = f"{schema}.{_quote_identifier(table)} AS {alias}"
    select_columns = ", ".join(f"{alias}.{_quote_identifier(column)}" for column in columns)
    order_column = f"{alias}.{_quote_identifier(columns[0])}"
    return f"SELECT TOP {top_n} {select_columns} FROM {table_ref} ORDER BY {order_column}"


def _build_window_sql(schema: str, table: str, columns: list[str], date_column: str) -> str:
    alias = "t"
    table_ref = f"{schema}.{_quote_identifier(table)} AS {alias}"
    select_columns = ", ".join(f"{alias}.{_quote_identifier(column)}" for column in columns)
    return (
        f"SELECT {select_columns}, "
        f"ROW_NUMBER() OVER (PARTITION BY {alias}.{_quote_identifier(columns[0])} ORDER BY {alias}.{_quote_identifier(date_column)}) AS rn "
        f"FROM {table_ref}"
    )


def _build_join_sql(left_schema: str, left_table: str, right_schema: str, right_table: str, join_column: str, columns: list[str]) -> str:
    left_alias = "l"
    right_alias = "r"
    left_ref = f"{left_schema}.{_quote_identifier(left_table)} AS {left_alias}"
    right_ref = f"{right_schema}.{_quote_identifier(right_table)} AS {right_alias}"
    select_list = [f"{left_alias}.{_quote_identifier(column)}" for column in columns]
    if join_column not in columns:
        select_list.insert(0, f"{left_alias}.{_quote_identifier(join_column)}")
    select_sql = ", ".join(select_list[:4])
    return (
        f"SELECT {select_sql} "
        f"FROM {left_ref} "
        f"JOIN {right_ref} ON {left_alias}.{_quote_identifier(join_column)} = {right_alias}.{_quote_identifier(join_column)}"
    )


def _roundtrip_sql(sql: str) -> str:
    tokens = Lexer(sql).tokenize()
    ast = Parser(tokens, sql).parse()
    json_str = ASTSerializer().to_json(ast)
    reconstructed_sql = ASTReconstructor().from_json_str(json_str)

    # 再解析一次，確認重建後的 SQL 仍然可被轉成 AST / JSON。
    tokens_2 = Lexer(reconstructed_sql).tokenize()
    ast_2 = Parser(tokens_2, reconstructed_sql).parse()
    json.loads(ASTSerializer().to_json(ast_2))
    return reconstructed_sql


def test_metadata_roundtrip_select_statements():
    """根據 metadata 產生代表性 SELECT，確認可 JSON roundtrip。"""
    tables = _load_metadata_tables()

    # 選取具代表性的表，避免整份 metadata 都變成過慢的超大測試。
    samples = [
        ("SalesLT", "Address"),
        ("SalesLT", "Customer"),
        ("SalesLT", "Product"),
        ("SalesLT", "SalesOrderHeader"),
        ("SalesLT", "SalesOrderDetail"),
        ("SalesLT", "ProductCategory"),
        ("SalesLT", "ProductModel"),
        ("dbo", "BuildVersion"),
    ]

    for schema, table in samples:
        table_key = f"{schema}.{table}"
        assert table_key in tables, f"Metadata missing table: {schema}.{table}"
        columns = tables[table_key]
        assert columns, f"Metadata missing columns for table: {schema}.{table}"

        # 只取前兩個欄位，讓 roundtrip 保持簡單且可預期。
        chosen_columns = columns[:2] if len(columns) >= 2 else columns[:1]
        sql = _build_roundtrip_sql(schema, table, chosen_columns)
        reconstructed_sql = _roundtrip_sql(sql)

        assert "SELECT" in reconstructed_sql
        assert "FROM" in reconstructed_sql
        assert table in reconstructed_sql
        for column in chosen_columns:
            assert column in reconstructed_sql


@pytest.mark.parametrize("table_key", _metadata_table_keys_with_min_columns(2))
def test_metadata_roundtrip_all_tables_with_alias_top_order(table_key):
    """每個至少有兩欄的 metadata 表，都跑 alias + TOP + ORDER BY 版本。"""
    tables = _load_metadata_tables()
    schema, table = _split_table_key(table_key)
    columns = tables[table_key][:2]
    sql = _build_aliased_select_sql(schema, table, columns, alias="t")
    reconstructed_sql = _roundtrip_sql(sql)

    assert "SELECT" in reconstructed_sql
    assert "TOP" in reconstructed_sql
    assert "ORDER BY" in reconstructed_sql
    assert "AS t" in reconstructed_sql or "AS T" in reconstructed_sql
    for column in columns:
        assert column in reconstructed_sql


@pytest.mark.parametrize("table_key", _metadata_table_keys())
def test_metadata_roundtrip_all_tables(table_key):
    """每個 metadata 表都至少做一次基本 roundtrip。"""
    tables = _load_metadata_tables()
    assert table_key in tables, f"Metadata missing table: {table_key}"

    columns = tables[table_key]
    assert columns, f"Metadata missing columns for table: {table_key}"

    schema, table = _split_table_key(table_key)
    chosen_columns = columns[:2] if len(columns) >= 2 else columns[:1]
    sql = _build_roundtrip_sql(schema, table, chosen_columns)
    reconstructed_sql = _roundtrip_sql(sql)

    assert "SELECT" in reconstructed_sql
    assert "FROM" in reconstructed_sql
    assert table in reconstructed_sql
    for column in chosen_columns:
        assert column in reconstructed_sql


def test_metadata_roundtrip_complex_queries():
    """根據 metadata 產生較複雜的查詢，確認解析與重建都成功。"""
    tables = _load_metadata_tables()

    cases = [
        {
            "name": "customer_address_join",
            "sql": (
                "SELECT c.CustomerID, c.FirstName, c.LastName, a.City, a.PostalCode "
                "FROM SalesLT.Customer AS c "
                "JOIN SalesLT.CustomerAddress AS ca ON c.CustomerID = ca.CustomerID "
                "JOIN SalesLT.Address AS a ON ca.AddressID = a.AddressID"
            ),
            "table_keys": ["SalesLT.Customer", "SalesLT.CustomerAddress", "SalesLT.Address"],
            "required_columns": ["CustomerID", "FirstName", "LastName", "City", "PostalCode", "AddressID"],
        },
        {
            "name": "customer_address_bridge_join",
            "sql": (
                "SELECT c.CustomerID, ca.AddressID, a.City "
                "FROM SalesLT.Customer AS c "
                "JOIN SalesLT.CustomerAddress AS ca ON c.CustomerID = ca.CustomerID "
                "JOIN SalesLT.Address AS a ON ca.AddressID = a.AddressID "
                "ORDER BY c.CustomerID"
            ),
            "table_keys": ["SalesLT.Customer", "SalesLT.CustomerAddress", "SalesLT.Address"],
            "required_columns": ["CustomerID", "AddressID", "City"],
        },
        {
            "name": "sales_group_by_having",
            "sql": (
                "SELECT soh.CustomerID, COUNT(*) AS OrderCount "
                "FROM SalesLT.SalesOrderHeader AS soh "
                "JOIN SalesLT.SalesOrderDetail AS sod ON soh.SalesOrderID = sod.SalesOrderID "
                "GROUP BY soh.CustomerID "
                "HAVING COUNT(*) > 0 "
                "ORDER BY OrderCount DESC"
            ),
            "table_keys": ["SalesLT.SalesOrderHeader", "SalesLT.SalesOrderDetail"],
            "required_columns": ["CustomerID", "SalesOrderID"],
        },
        {
            "name": "sales_order_date_window",
            "sql": (
                "SELECT soh.SalesOrderID, soh.OrderDate, "
                "ROW_NUMBER() OVER (PARTITION BY soh.CustomerID ORDER BY soh.OrderDate) AS rn "
                "FROM SalesLT.SalesOrderHeader AS soh"
            ),
            "table_keys": ["SalesLT.SalesOrderHeader"],
            "required_columns": ["SalesOrderID", "CustomerID", "OrderDate"],
        },
        {
            "name": "product_category_lookup",
            "sql": (
                "SELECT p.ProductID, p.Name, pc.Name AS CategoryName "
                "FROM SalesLT.Product AS p "
                "JOIN SalesLT.ProductCategory AS pc ON p.ProductCategoryID = pc.ProductCategoryID "
                "ORDER BY p.ProductID"
            ),
            "table_keys": ["SalesLT.Product", "SalesLT.ProductCategory"],
            "required_columns": ["ProductID", "Name", "ProductCategoryID"],
        },
        {
            "name": "product_model_description_join",
            "sql": (
                "SELECT pmd.ProductID, pmd.Name, pmd.Description "
                "FROM SalesLT.vProductAndDescription AS pmd "
                "WHERE pmd.ProductID IN (SELECT ProductID FROM SalesLT.Product)"
            ),
            "table_keys": ["SalesLT.vProductAndDescription", "SalesLT.Product"],
            "required_columns": ["ProductID", "Name", "Description"],
        },
        {
            "name": "product_window_by_date",
            "sql": (
                "SELECT p.ProductID, p.Name, "
                "ROW_NUMBER() OVER (PARTITION BY p.ProductCategoryID ORDER BY p.SellStartDate) AS rn "
                "FROM SalesLT.Product AS p"
            ),
            "table_keys": ["SalesLT.Product"],
            "required_columns": ["ProductID", "Name", "ProductCategoryID", "SellStartDate"],
        },
        {
            "name": "product_subquery_filter",
            "sql": (
                "SELECT p.ProductID, p.Name "
                "FROM SalesLT.Product AS p "
                "WHERE p.ProductID IN (SELECT ProductID FROM SalesLT.SalesOrderDetail)"
            ),
            "table_keys": ["SalesLT.Product", "SalesLT.SalesOrderDetail"],
            "required_columns": ["ProductID", "Name"],
        },
        {
            "name": "error_log_subquery",
            "sql": (
                "SELECT e.ErrorLogID, e.ErrorTime "
                "FROM dbo.ErrorLog AS e "
                "WHERE e.ErrorLogID IN (SELECT ErrorLogID FROM dbo.ErrorLog)"
            ),
            "table_keys": ["dbo.ErrorLog"],
            "required_columns": ["ErrorLogID", "ErrorTime"],
        },
        {
            "name": "window_function_roundtrip",
            "sql": (
                "SELECT soh.SalesOrderID, soh.CustomerID, "
                "ROW_NUMBER() OVER (PARTITION BY soh.CustomerID ORDER BY soh.OrderDate) AS rn "
                "FROM SalesLT.SalesOrderHeader AS soh"
            ),
            "table_keys": ["SalesLT.SalesOrderHeader"],
            "required_columns": ["SalesOrderID", "CustomerID", "OrderDate"],
        },
    ]

    for case in cases:
        for table_key in case["table_keys"]:
            assert table_key in tables, f"Metadata missing table: {table_key}"
        for column in case["required_columns"]:
            assert any(column in tables[table_key] for table_key in case["table_keys"]), (
                f"Metadata missing column '{column}' for case: {case['name']}"
            )

        reconstructed_sql = _roundtrip_sql(case["sql"])
        assert "SELECT" in reconstructed_sql
        assert "FROM" in reconstructed_sql
        assert case["sql"].split()[1] in reconstructed_sql or "ROW_NUMBER" in reconstructed_sql
        if "JOIN" in case["sql"]:
            assert "JOIN" in reconstructed_sql
        if "GROUP BY" in case["sql"]:
            assert "GROUP BY" in reconstructed_sql
        if "HAVING" in case["sql"]:
            assert "HAVING" in reconstructed_sql
        if "WHERE" in case["sql"]:
            assert "WHERE" in reconstructed_sql
        if "OVER" in case["sql"]:
            assert "OVER" in reconstructed_sql


def test_metadata_roundtrip_all_date_tables_have_window_queries():
    """有日期欄位的表，補測 window function roundtrip。"""
    tables = _load_metadata_tables()
    if not tables:
        pytest.skip("data/output.csv not available")
    date_types = {"date", "datetime", "smalldatetime", "timestamp"}

    for table_key, columns in tables.items():
        date_columns = []
        with METADATA_PATH.open("r", encoding="utf-8") as csv_file:
            reader = csv.reader(csv_file)
            for row in reader:
                if len(row) < 4:
                    continue
                schema, table_name, column_name, data_type = row[:4]
                if f"{schema}.{table_name}" == table_key and data_type.lower() in date_types:
                    date_columns.append(column_name)

        if len(columns) < 2 or not date_columns:
            continue

        schema, table = _split_table_key(table_key)
        window_columns = columns[:2]
        sql = _build_window_sql(schema, table, window_columns, date_columns[0])
        reconstructed_sql = _roundtrip_sql(sql)

        assert "ROW_NUMBER" in reconstructed_sql
        assert "OVER" in reconstructed_sql
        assert "PARTITION BY" in reconstructed_sql
        assert "ORDER BY" in reconstructed_sql
        assert date_columns[0] in reconstructed_sql


def test_metadata_roundtrip_join_candidates():
    """針對 metadata 中可直接對接的表，補測 join roundtrip。"""
    tables = _load_metadata_tables()

    for left_key, right_key, join_column in _metadata_join_candidates():
        if left_key not in tables or right_key not in tables:
            continue
        if join_column not in tables[left_key] or join_column not in tables[right_key]:
            continue

        left_schema, left_table = _split_table_key(left_key)
        right_schema, right_table = _split_table_key(right_key)
        sql = _build_join_sql(left_schema, left_table, right_schema, right_table, join_column, tables[left_key][:2])
        reconstructed_sql = _roundtrip_sql(sql)

        assert "JOIN" in reconstructed_sql
        assert join_column in reconstructed_sql
        assert "ON" in reconstructed_sql