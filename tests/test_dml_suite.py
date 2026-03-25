import pytest
import io
import json
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
from birdeye.ast import TruncateStatement
from birdeye.serializer import ASTSerializer
from birdeye.visualizer import ASTVisualizer

# --- (from test_dml_suite.py) ---

@pytest.fixture
def dml_reg():
    """
    建立 DML 測試專用的元數據註冊表。
    包含 Users 表與基本欄位，用於驗證變更操作的合法性。
    """
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Users,Email,VARCHAR\n"
        "Users,Status,VARCHAR\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_parse(sql):
    """執行 Lexer 與 Parser 的流水線，回傳 AST"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    return parser.parse()

def run_bind_with_runner(sql, runner):
    """整合 BirdEyeRunner 執行完整驗證"""
    return runner.run(sql)["ast"]

# --- 2. 語法解析成功測試 (DML Parsing) ---

@pytest.mark.parametrize("sql, expected_type, expected_table, set_count", [
    # 基礎 UPDATE 語法 (使用真實 Product 表)
    ("UPDATE Product SET Name = 'Bird' WHERE ProductID = 1", "UpdateStatement", "PRODUCT", 1),
    # 多欄位 UPDATE 語法
    ("UPDATE Product SET Name = 'New', Color = 'Blue' WHERE ProductID = 1", "UpdateStatement", "PRODUCT", 2),
    # 基礎 DELETE 語法
    ("DELETE FROM Product WHERE ProductID = 1", "DeleteStatement", "PRODUCT", 0),
])
def test_dml_parsing_success(sql, expected_type, expected_table, set_count):
    """驗證 UPDATE 與 DELETE 是否能正確轉換為對應的 AST 節點"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()

    assert ast.__class__.__name__ == expected_type
    assert ast.table.name.upper() == expected_table
    if expected_type == "UpdateStatement":
        assert len(ast.set_clauses) == set_count
    assert ast.where_condition is not None

# --- 💡 TDD New: DML 語意錯誤與類型檢查 (Real Metadata) ---

@pytest.mark.parametrize("sql, error_match", [
    # 欄位不存在於 SET 子句中
    ("UPDATE Product SET GhostColumn = 1 WHERE ProductID = 1", "Column 'GhostColumn' not found in 'Product'"),
    # 欄位不存在於 WHERE 子句中
    ("DELETE FROM Product WHERE UnknownCol = 99", "Column 'UnknownCol' not found in 'Product'"),
    # 💡 類型不匹配測試 (ListPrice 是 money/numeric，給字串應報錯)
    ("UPDATE Product SET ListPrice = 'Free' WHERE ProductID = 1", "Cannot compare MONEY with NVARCHAR"),
])
def test_dml_semantic_errors(global_runner, sql, error_match):
    """驗證 Binder 是否能根據真實元數據精準攔截非法欄位或類型錯誤"""
    with pytest.raises(SemanticError, match=error_match):
        run_bind_with_runner(sql, global_runner)


# --- (from test_insert_suite.py) ---

@pytest.fixture
def insert_reg():
    """
    建立寫入測試專用的元數據。
    包含 Users 與 Logs 表，用於驗證不同寫入場景的結構對齊。
    """
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Users,Email,VARCHAR\n"
        "Logs,LogID,INT\n"
        "Logs,Message,VARCHAR\n"
        "Logs,CreatedAt,DATETIME\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

# --- 2. INSERT 語法解析測試 (Real Metadata) ---

@pytest.mark.parametrize("sql, expected_table, col_count, val_count", [
    # 指定欄位的標準寫入 (Product 表)
    ("INSERT INTO Product (ProductID, Name) VALUES (1, 'Bird')", "PRODUCT", 2, 2),
    # 帶有函數調用的寫入
    ("INSERT INTO Product (ProductID, Name, SellStartDate) VALUES (1, 'A', GETDATE())", "PRODUCT", 3, 3),
])
def test_insert_parsing_success(global_runner, sql, expected_table, col_count, val_count):
    """驗證 INSERT 語句是否能正確解析為 AST 節點"""
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.__class__.__name__ == "InsertStatement"
    assert ast.table.name.upper() == expected_table
    assert len(ast.columns) == col_count
    assert len(ast.values) == val_count

# --- 3. ZTA 欄位對齊與語意防禦 (Real Metadata) ---

@pytest.mark.parametrize("sql, error_match", [
    # 欄位數量不匹配 (指定 2 欄但給 1 值)
    ("INSERT INTO Product (ProductID, Name) VALUES (1)", "Column count mismatch: Expected 2, got 1"),
    # 寫入不存在的欄位
    ("INSERT INTO Product (GhostColumn) VALUES (1)", "Column 'GhostColumn' not found in 'Product'"),
    # 💡 嚴格類型防禦：StandardCost 是 money，給字串應報錯
    ("INSERT INTO Product (StandardCost) VALUES ('High')", "Cannot compare MONEY with NVARCHAR"),
    # 全表寫入數量檢查 (Product 在 output.csv 中有 17 欄)
    ("INSERT INTO Product VALUES (1, 'A')", "Column count mismatch: Expected 17, got 2"),
])
def test_insert_semantic_errors(global_runner, sql, error_match):
    """驗證 Binder 是否能根據真實元數據執行 ZTA 寫入檢查"""
    with pytest.raises(SemanticError, match=error_match):
        run_bind_with_runner(sql, global_runner)

# --- 4. SqlBulkCopy 語義映射測試 (Bulk Insert) ---

def test_bulk_copy_mapping():
    """
    驗證 SqlBulkCopy 映射節點，這在處理大量軍事數據寫入時具備高效能語義。
    """
    sql = "BULK INSERT INTO Product"
    ast = run_parse(sql)
    assert ast.__class__.__name__ == "SqlBulkCopyStatement"
    assert ast.table.name.upper() == "PRODUCT"

def test_bulk_copy_semantic_validation(global_runner):
    """驗證 BulkCopy 的目標表必須存在於真實元數據中"""
    sql = "BULK INSERT INTO NonExistentTable"
    with pytest.raises(SemanticError, match="Table 'NonExistentTable' not found"):
        run_bind_with_runner(sql, global_runner)


# --- (from test_insert_advanced_suite.py) ---

def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


# ─────────────────────────────────────────────
# Issue #57: INSERT INTO ... SELECT
# ─────────────────────────────────────────────

def test_parser_insert_select_produces_insert_statement():
    """INSERT INTO ... SELECT 應解析為 InsertStatement，source 為 SelectStatement"""
    from birdeye.ast import InsertStatement, SelectStatement
    ast = parse("INSERT INTO Address (AddressID, City) SELECT AddressID, City FROM Address")
    assert isinstance(ast, InsertStatement)
    assert isinstance(ast.source, SelectStatement)


def test_parser_insert_select_no_columns():
    """INSERT INTO T SELECT ... (不指定欄位) 應成功解析"""
    from birdeye.ast import InsertStatement
    ast = parse("INSERT INTO Address SELECT AddressID, City FROM Address")
    assert isinstance(ast, InsertStatement)


def test_insert_select_basic(global_runner):
    """INSERT INTO ... SELECT 基本用法應成功綁定"""
    result = global_runner.run(
        "INSERT INTO Address (AddressID, City) "
        "SELECT AddressID, City FROM Address WHERE AddressID = 1"
    )
    assert result["status"] == "success"


def test_insert_select_type_mismatch_raises(global_runner):
    """INSERT-SELECT 型別不相容時應拋出 SemanticError"""
    with pytest.raises(SemanticError):
        global_runner.run(
            "INSERT INTO Address (AddressID, City) "
            "SELECT City, AddressID FROM Address"
        )


def test_insert_select_column_count_mismatch_raises(global_runner):
    """INSERT-SELECT 欄位數不符時應拋出 SemanticError"""
    with pytest.raises(SemanticError):
        global_runner.run(
            "INSERT INTO Address (AddressID) "
            "SELECT AddressID, City FROM Address"
        )


def test_insert_select_serialization():
    """INSERT-SELECT 應序列化為含 source 欄位的 JSON"""
    ast = parse("INSERT INTO Address (AddressID) SELECT AddressID FROM Address")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["node_type"] == "InsertStatement"
    assert data["source"] is not None
    assert data["source"]["node_type"] == "SelectStatement"
    assert data["values"] is None


def test_insert_select_visualizer():
    """INSERT-SELECT 視覺化應顯示 SOURCE 節點"""
    ast = parse("INSERT INTO Address (AddressID) SELECT AddressID FROM Address")
    output = ASTVisualizer().dump(ast)
    assert "INSERT_STATEMENT" in output
    assert "SOURCE" in output


# ─────────────────────────────────────────────
# Issue #58: Multi-row INSERT VALUES
# ─────────────────────────────────────────────

def test_parser_multirow_values_count():
    """Multi-row VALUES 應解析出正確的列數"""
    from birdeye.ast import InsertStatement
    ast = parse("INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B'), (3, 'C')")
    assert isinstance(ast, InsertStatement)
    assert len(ast.value_rows) == 3


def test_parser_single_row_values_backward_compat():
    """單列 VALUES 仍應向後相容"""
    from birdeye.ast import InsertStatement
    ast = parse("INSERT INTO Address (AddressID, City) VALUES (1, 'Taipei')")
    assert isinstance(ast, InsertStatement)
    assert len(ast.value_rows) == 1


def test_multirow_insert_basic(global_runner):
    """Multi-row INSERT VALUES 基本用法應成功綁定"""
    result = global_runner.run(
        "INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B')"
    )
    assert result["status"] == "success"


def test_multirow_insert_type_check(global_runner):
    """Multi-row VALUES 每一列皆應通過型別檢查"""
    result = global_runner.run(
        "INSERT INTO Address (AddressID, City) "
        "VALUES (10, 'X'), (20, 'Y'), (30, 'Z')"
    )
    assert result["status"] == "success"


def test_multirow_insert_type_mismatch_raises(global_runner):
    """Multi-row VALUES 其中一列型別錯誤時應拋出 SemanticError"""
    with pytest.raises(SemanticError):
        global_runner.run(
            "INSERT INTO Address (AddressID, City) VALUES (1, 'A'), ('bad', 2)"
        )


def test_multirow_insert_serialization():
    """Multi-row VALUES 應序列化為含多組 value_rows 的 JSON"""
    ast = parse("INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B')")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["node_type"] == "InsertStatement"
    assert isinstance(data["value_rows"], list)
    assert len(data["value_rows"]) == 2


def test_multirow_insert_visualizer():
    """Multi-row VALUES 視覺化應顯示多組 VALUES ROW"""
    ast = parse("INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B')")
    output = ASTVisualizer().dump(ast)
    assert "INSERT_STATEMENT" in output
    assert "VALUES ROW #1" in output
    assert "VALUES ROW #2" in output


# --- (from test_truncate_table_suite.py) ---

@pytest.fixture
def truncate_registry():
    """Mock registry with sample tables for testing."""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Orders,OrderID,INT\n"
        "Orders,UserID,INT\n"
        "Products,ProductID,INT\n"
        "Products,ProductName,VARCHAR\n"
        "Address,AddressID,INT\n"
        "Address,AddressLine1,VARCHAR\n"
        "Address,City,VARCHAR\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

# --- 1. Basic TRUNCATE TABLE Parsing Tests ---

@pytest.mark.parametrize("sql, expected_table", [
    ("TRUNCATE TABLE Address", "Address"),
    ("TRUNCATE TABLE [Address]", "Address"),
    ("TRUNCATE TABLE dbo.Address", "Address"),
    ("TRUNCATE TABLE [dbo].[Address]", "Address"),
])
def test_truncate_table_basic_parsing(sql, expected_table):
    """Test basic TRUNCATE TABLE syntax parsing."""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()

    assert isinstance(ast, TruncateStatement)
    assert ast.table.name == expected_table

# --- 2. TRUNCATE TABLE Semantic Validation Tests ---

def test_truncate_existing_table(truncate_registry):
    """Test TRUNCATE on existing table succeeds."""
    sql = "TRUNCATE TABLE Address"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(truncate_registry)

    bound_ast = binder.bind(ast)
    assert isinstance(bound_ast, TruncateStatement)

def test_truncate_nonexistent_table(truncate_registry):
    """Test TRUNCATE on non-existent table fails."""
    sql = "TRUNCATE TABLE NonExistentTable"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(truncate_registry)

    with pytest.raises(SemanticError, match="Table 'NonExistentTable' not found"):
        binder.bind(ast)

# --- 3. TRUNCATE TABLE Integration Tests ---

def test_truncate_table_full_pipeline(global_runner):
    """Test TRUNCATE TABLE through full BirdEyeRunner pipeline."""
    sql = "TRUNCATE TABLE Address"
    result = global_runner.run(sql)

    assert "ast" in result
    assert isinstance(result["ast"], TruncateStatement)
    assert result["ast"].table.name == "Address"

# --- 4. Error Handling Tests ---

@pytest.mark.parametrize("invalid_sql", [
    "TRUNCATE Users",  # Missing TABLE keyword
    "TRUNCATE TABLE",  # Missing table name
    "TRUNCATE TABLE Users ExtraStuff",  # Extra tokens
])
def test_truncate_table_syntax_errors(invalid_sql):
    """Test TRUNCATE TABLE syntax error handling."""
    lexer = Lexer(invalid_sql)
    parser = Parser(lexer.tokenize(), invalid_sql)

    with pytest.raises(SyntaxError):
        parser.parse()

# --- 5. ZTA Security Tests ---

def test_truncate_table_zta_security(truncate_registry):
    """Test that TRUNCATE TABLE adheres to ZTA security principles."""
    sql = "TRUNCATE TABLE Address"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(truncate_registry)

    bound_ast = binder.bind(ast)
    assert bound_ast.table.name == "Address"
