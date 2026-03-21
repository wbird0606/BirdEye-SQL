import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
from birdeye.ast import TruncateStatement

# --- Test Data Setup ---

@pytest.fixture
def registry():
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
    ("TRUNCATE TABLE dbo.Address", "Address"),  # Note: parser currently only extracts table name
    ("TRUNCATE TABLE [dbo].[Address]", "Address"),  # Note: parser currently only extracts table name
])
def test_truncate_table_basic_parsing(sql, expected_table):
    """Test basic TRUNCATE TABLE syntax parsing."""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()

    assert isinstance(ast, TruncateStatement)
    assert ast.table.name == expected_table

# --- 2. TRUNCATE TABLE Semantic Validation Tests ---

def test_truncate_existing_table(registry):
    """Test TRUNCATE on existing table succeeds."""
    sql = "TRUNCATE TABLE Address"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)

    # Should not raise exception
    bound_ast = binder.bind(ast)
    assert isinstance(bound_ast, TruncateStatement)

def test_truncate_nonexistent_table(registry):
    """Test TRUNCATE on non-existent table fails."""
    sql = "TRUNCATE TABLE NonExistentTable"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)

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

def test_truncate_table_zta_security(registry):
    """Test that TRUNCATE TABLE adheres to ZTA security principles."""
    # This would test any security validations specific to TRUNCATE
    # For now, ensure basic validation works
    sql = "TRUNCATE TABLE Address"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)

    bound_ast = binder.bind(ast)
    assert bound_ast.table.name == "Address"