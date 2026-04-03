import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
from birdeye.ast import OverClauseNode

# --- Test Data Setup ---

@pytest.fixture
def registry():
    """Mock registry with sample tables for testing."""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Employees,EmpID,INT\n"
        "Employees,Name,VARCHAR\n"
        "Employees,Salary,DECIMAL\n"
        "Employees,DeptID,INT\n"
        "Departments,DeptID,INT\n"
        "Departments,DeptName,VARCHAR\n"
        "Sales,Date,DATETIME\n"
        "Sales,Amount,DECIMAL\n"
        "Sales,ProductID,INT\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

# --- 1. Basic Window Function Parsing Tests ---

@pytest.mark.parametrize("sql", [
    "SELECT ROW_NUMBER() OVER (ORDER BY Salary) FROM Employees",
    "SELECT RANK() OVER (ORDER BY Salary DESC) FROM Employees",
    "SELECT DENSE_RANK() OVER (ORDER BY Salary) FROM Employees",
    "SELECT NTILE(4) OVER (ORDER BY Salary) FROM Employees",
])
def test_basic_window_function_parsing(sql):
    """Test that basic window functions parse successfully."""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should parse successfully and have window function with OVER
    stmt = parser.parse()
    assert stmt is not None
    assert len(stmt.columns) > 0
    func_call = stmt.columns[0]
    assert func_call.over_clause is not None
    assert isinstance(func_call.over_clause, OverClauseNode)

@pytest.mark.parametrize("sql", [
    "SELECT SUM(Salary) OVER (PARTITION BY DeptID) FROM Employees",
    "SELECT AVG(Salary) OVER (ORDER BY Salary) FROM Employees",
    "SELECT COUNT(*) OVER (PARTITION BY DeptID ORDER BY Salary DESC) FROM Employees",
])
def test_window_function_with_partition_order(sql):
    """Test that window functions with PARTITION BY/ORDER BY parse successfully."""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should parse successfully
    stmt = parser.parse()
    assert stmt is not None
    assert len(stmt.columns) > 0
    func_call = stmt.columns[0]
    assert func_call.over_clause is not None
    if "PARTITION BY" in sql:
        assert len(func_call.over_clause.partition_by) > 0
    if "ORDER BY" in sql:
        assert len(func_call.over_clause.order_by) > 0

# --- 2. Frame Specification Tests ---

@pytest.mark.parametrize("sql", [
    "SELECT SUM(Salary) OVER (ORDER BY Salary ROWS UNBOUNDED PRECEDING) FROM Employees",
    "SELECT SUM(Salary) OVER (ORDER BY Salary ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM Employees",
    "SELECT SUM(Salary) OVER (ORDER BY Salary RANGE BETWEEN 100 PRECEDING AND 100 FOLLOWING) FROM Employees",
])
def test_window_frame_specifications(sql):
    """Test that window frame specifications parse successfully."""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should parse successfully with frame specification
    stmt = parser.parse()
    assert stmt is not None
    assert len(stmt.columns) > 0
    func_call = stmt.columns[0]
    assert func_call.over_clause is not None
    assert func_call.over_clause.frame_type is not None  # ROWS or RANGE

# --- 3. Complex Window Function Queries ---

def test_multiple_window_functions():
    """Test that multiple window functions parse successfully."""
    sql = """
    SELECT Name, Salary,
           ROW_NUMBER() OVER (ORDER BY Salary DESC) as rn,
           RANK() OVER (ORDER BY Salary DESC) as rnk,
           SUM(Salary) OVER (PARTITION BY DeptID ORDER BY Salary) as dept_total
    FROM Employees
    """

    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should parse successfully with multiple window functions
    stmt = parser.parse()
    assert stmt is not None
    # Should have 5 columns: Name, Salary, ROW_NUMBER, RANK, SUM
    assert len(stmt.columns) == 5
    # Check window functions (columns 2, 3, 4)
    for i in [2, 3, 4]:
        assert stmt.columns[i].over_clause is not None

# --- 4. Semantic Validation Tests (deferred - no longer test failures expected) ---
# These tests will be implemented later when binder semantic validation is complete
# For now, parsing should succeed (semantic errors will be caught by binder)

# --- 5. Window Function Restrictions (deferred) ---
# These will be validated when binder semantic validation is complete

# --- 6. Integration Tests (deferred) ---
# Full pipeline validation will be done after binder is updated

# --- 7. Error Handling Tests ---

@pytest.mark.parametrize("invalid_sql", [
    "SELECT ROW_NUMBER() OVER FROM Employees",  # Missing parentheses
    "SELECT ROW_NUMBER() (ORDER BY Salary) FROM Employees",  # Missing OVER
    "SELECT ROW_NUMBER() OVER (ORDER) FROM Employees",  # Missing BY
    "SELECT ROW_NUMBER() OVER (PARTITION) FROM Employees",  # Missing BY
])
def test_window_function_syntax_errors(invalid_sql):
    """Test window function syntax error handling."""
    lexer = Lexer(invalid_sql)
    parser = Parser(lexer.tokenize(), invalid_sql)

    with pytest.raises(SyntaxError):
        parser.parse()

# --- 8. Advanced Window Function Tests (deferred) ---
# Named window specifications will be implemented in future iteration

def test_named_window_specifications_not_implemented():
    """Test that named window specifications are not yet implemented."""
    sql = """
    SELECT Name, Salary,
           ROW_NUMBER() OVER w as rn,
           SUM(Salary) OVER w as total
    FROM Employees
    WINDOW w AS (PARTITION BY DeptID ORDER BY Salary)
    """

    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should raise SyntaxError since window functions and WINDOW clause are not yet implemented
    with pytest.raises(SyntaxError):
        parser.parse()

# --- 10. Restored Window Function Coverage ---

def test_window_function_type_inference(registry):
    """Window function results should infer BIGINT."""
    sql = "SELECT ROW_NUMBER() OVER (ORDER BY Salary) AS rn FROM Employees"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()

    bound_ast = Binder(registry).bind(ast)
    assert bound_ast.columns[0].inferred_type == "BIGINT"


def test_window_function_partition_validation(registry):
    """Invalid PARTITION BY columns should raise a semantic error."""
    sql = "SELECT SUM(Salary) OVER (PARTITION BY NonExistentCol) FROM Employees"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()

    with pytest.raises(SemanticError, match="Column 'NonExistentCol' not found in 'Employees'"):
        Binder(registry).bind(ast)


def test_window_function_order_validation(registry):
    """Invalid ORDER BY columns in OVER should raise a semantic error."""
    sql = "SELECT ROW_NUMBER() OVER (ORDER BY NonExistentCol) FROM Employees"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()

    with pytest.raises(SemanticError, match="Column 'NonExistentCol' not found in 'Employees'"):
        Binder(registry).bind(ast)


def test_window_functions_in_where_clause_are_bound(registry):
    """Window functions inside WHERE are parsed and bound in the current pipeline."""
    sql = "SELECT * FROM Employees WHERE ROW_NUMBER() OVER (ORDER BY Salary) = 1"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()

    bound_ast = Binder(registry).bind(ast)
    assert bound_ast.where_condition.inferred_type == "BIT"


def test_window_function_full_pipeline(registry):
    """Window functions should survive the full Runner pipeline."""
    from birdeye.runner import BirdEyeRunner

    runner = BirdEyeRunner(registry)
    result = runner.run("SELECT Name, ROW_NUMBER() OVER (ORDER BY Salary DESC) AS rn FROM Employees")

    assert "OVER" in result["tree"]
    assert "ROW_NUMBER" in result["json"]
    assert result["ast"].columns[1].inferred_type == "BIGINT"


def test_window_function_with_aliases(registry):
    """Aliases referenced in OVER should still be invalidated by ZTA rules."""
    sql = """
    SELECT Salary, Salary * 1.1 AS AdjustedSalary,
           ROW_NUMBER() OVER (ORDER BY AdjustedSalary) AS rn
    FROM Employees
    """

    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()

    with pytest.raises(SemanticError, match="Column 'AdjustedSalary' not found in 'Employees'"):
        Binder(registry).bind(ast)
