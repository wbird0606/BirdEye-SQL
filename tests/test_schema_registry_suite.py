"""
test_schema_registry_suite.py — Schema-qualified table registry 支援

TDD 驅動：先寫測試，再改實作。
涵蓋：
  1. Registry 載入 4-col CSV（含 table_schema）
  2. _resolve_key 向下相容：3-col CSV + schema-qualified 查詢
  3. 跨 schema 同名表格不互相覆蓋
  4. Binder 在 FROM SalesLT.Customer 時正確查找 SALESLT.CUSTOMER key
"""

from __future__ import annotations
import io
import pytest

from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError


# ── helpers ──────────────────────────────────────────────────────────────────

def make_registry(csv_text: str) -> MetadataRegistry:
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_text))
    return reg


def run_bind(sql: str, reg: MetadataRegistry):
    tokens = Lexer(sql).tokenize()
    ast = Parser(tokens, sql).parse()
    return Binder(reg).bind(ast)


# ── 1. 四欄 CSV（含標頭）載入 ────────────────────────────────────────────────

CSV_WITH_SCHEMA_HEADER = (
    "table_schema,table_name,column_name,data_type\n"
    "SalesLT,Customer,CustomerID,int\n"
    "SalesLT,Customer,FirstName,nvarchar\n"
    "SalesLT,Customer,EmailAddress,nvarchar\n"
    "SalesLT,Address,AddressID,int\n"
    "SalesLT,Address,City,nvarchar\n"
)

CSV_WITH_SCHEMA_NO_HEADER = (
    "SalesLT,Customer,CustomerID,int\n"
    "SalesLT,Customer,FirstName,nvarchar\n"
    "SalesLT,Address,AddressID,int\n"
    "SalesLT,Address,City,nvarchar\n"
)


def test_load_4col_with_header_has_table():
    """4-col 有標頭：has_table 以 SCHEMA.TABLE 為 key"""
    reg = make_registry(CSV_WITH_SCHEMA_HEADER)
    assert reg.has_table("SalesLT.Customer")
    assert reg.has_table("SalesLT.Address")


def test_load_4col_with_header_columns():
    """4-col 有標頭：get_columns 回傳正確欄位"""
    reg = make_registry(CSV_WITH_SCHEMA_HEADER)
    cols = reg.get_columns("SalesLT.Customer")
    assert "CUSTOMERID" in cols
    assert "FIRSTNAME" in cols
    assert "EMAILADDRESS" in cols


def test_load_4col_with_header_has_column():
    """4-col 有標頭：has_column / get_column_type 正常運作"""
    reg = make_registry(CSV_WITH_SCHEMA_HEADER)
    assert reg.has_column("SalesLT.Customer", "CustomerID")
    assert reg.get_column_type("SalesLT.Customer", "CustomerID") == "INT"


def test_load_4col_no_header_has_table():
    """4-col 無標頭：自動偵測欄位數量，key = SCHEMA.TABLE"""
    reg = make_registry(CSV_WITH_SCHEMA_NO_HEADER)
    assert reg.has_table("SalesLT.Customer")
    assert reg.has_table("SalesLT.Address")


def test_load_4col_no_header_columns():
    """4-col 無標頭：get_columns 回傳正確欄位"""
    reg = make_registry(CSV_WITH_SCHEMA_NO_HEADER)
    cols = reg.get_columns("SalesLT.Customer")
    assert "CUSTOMERID" in cols
    assert "FIRSTNAME" in cols


# ── 2. 向下相容：3-col CSV + schema-qualified 查詢 ───────────────────────────

CSV_3COL_NO_HEADER = (
    "Customer,CustomerID,int\n"
    "Customer,FirstName,nvarchar\n"
    "Address,AddressID,int\n"
)

CSV_3COL_WITH_HEADER = (
    "table_name,column_name,data_type\n"
    "Customer,CustomerID,int\n"
    "Customer,FirstName,nvarchar\n"
)


def test_3col_backward_compat_plain_lookup():
    """3-col CSV：原本的 has_table('Customer') 仍有效"""
    reg = make_registry(CSV_3COL_NO_HEADER)
    assert reg.has_table("Customer")
    assert reg.has_column("Customer", "CustomerID")


def test_3col_schema_qualified_fallback_has_table():
    """3-col CSV：查詢 'SalesLT.Customer' 應 fallback 到 'Customer'"""
    reg = make_registry(CSV_3COL_NO_HEADER)
    assert reg.has_table("SalesLT.Customer")


def test_3col_schema_qualified_fallback_get_columns():
    """3-col CSV：get_columns('SalesLT.Customer') fallback 到 'Customer'"""
    reg = make_registry(CSV_3COL_NO_HEADER)
    cols = reg.get_columns("SalesLT.Customer")
    assert "CUSTOMERID" in cols


def test_3col_schema_qualified_fallback_has_column():
    """3-col CSV：has_column('SalesLT.Customer', 'CustomerID') fallback"""
    reg = make_registry(CSV_3COL_NO_HEADER)
    assert reg.has_column("SalesLT.Customer", "CustomerID")


def test_3col_with_header_backward_compat():
    """3-col 有標頭：原有行為不受影響"""
    reg = make_registry(CSV_3COL_WITH_HEADER)
    assert reg.has_table("Customer")
    assert reg.get_column_type("Customer", "CustomerID") == "INT"


# ── 2b. 4-col registry + unqualified SQL ─────────────────────────────────────

def test_4col_unqualified_lookup_single_schema():
    """4-col registry，SQL 無 schema 時 fallback 到唯一符合的 SCHEMA.TABLE"""
    reg = make_registry(CSV_WITH_SCHEMA_HEADER)
    # 只有 SalesLT.Customer，無 schema 查詢應自動找到它
    assert reg.has_table("Customer")
    assert reg.has_column("Customer", "CustomerID")
    assert reg.get_column_type("Customer", "CustomerID") == "INT"
    assert "CUSTOMERID" in reg.get_columns("Customer")


def test_4col_unqualified_lookup_ambiguous():
    """4-col registry，同名表格在多個 schema → unqualified 查詢不符合任何"""
    reg = make_registry(CSV_MULTI_SCHEMA)
    # SalesLT.Customer 和 HR.Customer 都存在 → 不應 fallback
    assert not reg.has_table("Customer")


# ── 3. 跨 schema 同名表格隔離 ────────────────────────────────────────────────

CSV_MULTI_SCHEMA = (
    "table_schema,table_name,column_name,data_type\n"
    "SalesLT,Customer,CustomerID,int\n"
    "SalesLT,Customer,EmailAddress,nvarchar\n"
    "HR,Customer,EmployeeID,int\n"
    "HR,Customer,Department,nvarchar\n"
)


def test_multi_schema_no_collision_has_table():
    """同名表格在不同 schema 下各自存在，互不干擾"""
    reg = make_registry(CSV_MULTI_SCHEMA)
    assert reg.has_table("SalesLT.Customer")
    assert reg.has_table("HR.Customer")


def test_multi_schema_columns_isolated():
    """SalesLT.Customer 與 HR.Customer 欄位互不混入"""
    reg = make_registry(CSV_MULTI_SCHEMA)
    sales_cols = set(reg.get_columns("SalesLT.Customer"))
    hr_cols    = set(reg.get_columns("HR.Customer"))

    assert "CUSTOMERID"   in sales_cols
    assert "EMAILADDRESS" in sales_cols
    assert "EMPLOYEEID"   not in sales_cols

    assert "EMPLOYEEID"   in hr_cols
    assert "DEPARTMENT"   in hr_cols
    assert "EMAILADDRESS" not in hr_cols


def test_multi_schema_column_type_isolated():
    """get_column_type 對不同 schema 的同名表格回傳各自欄位類型"""
    reg = make_registry(CSV_MULTI_SCHEMA)
    assert reg.get_column_type("SalesLT.Customer", "CustomerID") == "INT"
    assert reg.has_column("HR.Customer", "Department")
    assert not reg.has_column("SalesLT.Customer", "Department")


def test_multi_schema_get_column_count():
    """get_column_count 對各 schema 各自計算"""
    reg = make_registry(CSV_MULTI_SCHEMA)
    assert reg.get_column_count("SalesLT.Customer") == 2
    assert reg.get_column_count("HR.Customer") == 2


# ── 4. Binder + schema-qualified FROM 子句 ───────────────────────────────────

CSV_BINDER = (
    "table_schema,table_name,column_name,data_type\n"
    "SalesLT,Customer,CustomerID,int\n"
    "SalesLT,Customer,FirstName,nvarchar\n"
    "SalesLT,Customer,EmailAddress,nvarchar\n"
    "SalesLT,Address,AddressID,int\n"
    "SalesLT,Address,City,nvarchar\n"
)


def test_binder_schema_qualified_table_no_alias():
    """SELECT col FROM Schema.Table（無別名）正確 bind"""
    reg = make_registry(CSV_BINDER)
    ast = run_bind("SELECT CustomerID FROM SalesLT.Customer", reg)
    assert ast.columns[0].inferred_type == "INT"


def test_binder_schema_qualified_table_with_alias():
    """SELECT alias.col FROM Schema.Table AS alias 正確 bind"""
    reg = make_registry(CSV_BINDER)
    ast = run_bind("SELECT c.CustomerID FROM SalesLT.Customer c", reg)
    assert ast.columns[0].inferred_type == "INT"


def test_binder_schema_qualified_unknown_table_raises():
    """不存在的 schema.table 應 raise SemanticError"""
    reg = make_registry(CSV_BINDER)
    with pytest.raises(SemanticError, match="not found"):
        run_bind("SELECT ID FROM dbo.Customer", reg)


def test_binder_schema_qualified_star_expansion():
    """SELECT * FROM Schema.Table 展開欄位數量正確"""
    reg = make_registry(CSV_BINDER)
    ast = run_bind("SELECT * FROM SalesLT.Customer", reg)
    assert len(ast.columns) == 3  # CustomerID, FirstName, EmailAddress


def test_binder_multi_schema_join():
    """JOIN 跨 schema 同名表格，各自解析正確欄位"""
    csv = (
        "table_schema,table_name,column_name,data_type\n"
        "SalesLT,Customer,CustomerID,int\n"
        "SalesLT,Customer,FirstName,nvarchar\n"
        "HR,Customer,EmployeeID,int\n"
        "HR,Customer,Department,nvarchar\n"
    )
    reg = make_registry(csv)
    sql = (
        "SELECT s.CustomerID, h.EmployeeID "
        "FROM SalesLT.Customer s "
        "JOIN HR.Customer h ON s.CustomerID = h.EmployeeID"
    )
    ast = run_bind(sql, reg)
    assert ast.columns[0].inferred_type == "INT"
    assert ast.columns[1].inferred_type == "INT"


def test_binder_resolved_table_is_unqualified():
    """binder 設定的 resolved_table 應為不含 schema 的純 table name，
    讓 intent_extractor 能正確從 alias_map 反查 schema。"""
    from birdeye.serializer import ASTSerializer
    import json

    reg = make_registry(CSV_BINDER)
    # 多表 JOIN：EmailAddress 無 qualifier，binder 需設 resolved_table = "Customer"
    sql = (
        "SELECT EmailAddress FROM SalesLT.Customer "
        "JOIN SalesLT.Address ON 1=1"
    )
    ast = run_bind(sql, reg)
    # EmailAddress 應被 resolved 到 Customer
    email_col = ast.columns[0]
    assert hasattr(email_col, "resolved_table")
    # resolved_table 不應含 schema prefix
    assert "." not in email_col.resolved_table
