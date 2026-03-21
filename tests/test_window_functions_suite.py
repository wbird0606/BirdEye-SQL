import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
# Note: WindowFunctionNode and OverClauseNode not yet implemented
# from birdeye.ast import WindowFunctionNode, OverClauseNode

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

# --- 1. Basic Window Function Parsing Tests ---

@pytest.mark.parametrize("sql", [
    "SELECT ROW_NUMBER() OVER (ORDER BY Salary) FROM Employees",
    "SELECT RANK() OVER (ORDER BY Salary DESC) FROM Employees",
    "SELECT DENSE_RANK() OVER (ORDER BY Salary) FROM Employees",
    "SELECT NTILE(4) OVER (ORDER BY Salary) FROM Employees",
])
def test_basic_window_function_parsing_not_implemented(sql):
    """Test that window functions are not yet implemented (should raise SyntaxError)."""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should raise SyntaxError since window functions are not yet implemented
    with pytest.raises(SyntaxError):
        parser.parse()

@pytest.mark.parametrize("sql", [
    "SELECT SUM(Salary) OVER (PARTITION BY DeptID) FROM Employees",
    "SELECT AVG(Salary) OVER (ORDER BY Salary) FROM Employees",
    "SELECT COUNT(*) OVER (PARTITION BY DeptID ORDER BY Salary DESC) FROM Employees",
])
def test_window_function_with_partition_order_not_implemented(sql):
    """Test that window functions with PARTITION BY/ORDER BY are not yet implemented."""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should raise SyntaxError since window functions are not yet implemented
    with pytest.raises(SyntaxError):
        parser.parse()

# --- 2. Frame Specification Tests ---

# --- 2. Frame Specification Tests ---

@pytest.mark.parametrize("sql", [
    "SELECT SUM(Salary) OVER (ORDER BY Salary ROWS UNBOUNDED PRECEDING) FROM Employees",
    "SELECT SUM(Salary) OVER (ORDER BY Salary ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM Employees",
    "SELECT SUM(Salary) OVER (ORDER BY Salary RANGE BETWEEN 100 PRECEDING AND 100 FOLLOWING) FROM Employees",
])
def test_window_frame_specifications_not_implemented(sql):
    """Test that window frame specifications are not yet implemented."""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should raise SyntaxError since window functions are not yet implemented
    with pytest.raises(SyntaxError):
        parser.parse()

# --- 3. Complex Window Function Queries ---

def test_multiple_window_functions_not_implemented():
    """Test that multiple window functions are not yet implemented."""
    sql = """
    SELECT Name, Salary,
           ROW_NUMBER() OVER (ORDER BY Salary DESC) as rn,
           RANK() OVER (ORDER BY Salary DESC) as rnk,
           SUM(Salary) OVER (PARTITION BY DeptID ORDER BY Salary) as dept_total
    FROM Employees
    """

    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should raise SyntaxError since window functions are not yet implemented
    with pytest.raises(SyntaxError):
        parser.parse()

# --- 4. Semantic Validation Tests ---

def test_window_function_type_inference_not_implemented(registry):
    """Test that window function type inference is not yet implemented."""
    sql = "SELECT ROW_NUMBER() OVER (ORDER BY Salary) as rn FROM Employees"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should raise SyntaxError since window functions are not yet implemented
    with pytest.raises(SyntaxError):
        parser.parse()

def test_window_function_partition_validation_not_implemented(registry):
    """Test that PARTITION BY validation is not yet implemented."""
    sql = "SELECT SUM(Salary) OVER (PARTITION BY NonExistentCol) FROM Employees"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should raise SyntaxError since window functions are not yet implemented
    with pytest.raises(SyntaxError):
        parser.parse()

def test_window_function_order_validation_not_implemented(registry):
    """Test that ORDER BY validation is not yet implemented."""
    sql = "SELECT ROW_NUMBER() OVER (ORDER BY NonExistentCol) FROM Employees"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should raise SyntaxError since window functions are not yet implemented
    with pytest.raises(SyntaxError):
        parser.parse()

# --- 5. Window Function Restrictions ---

def test_window_functions_only_in_select_not_implemented():
    """Test that window functions restrictions are not yet implemented."""
    # This test would check that window functions can only be used in SELECT
    # For now, since window functions aren't implemented, any attempt should fail
    sql = "SELECT * FROM Employees WHERE ROW_NUMBER() OVER (ORDER BY Salary) = 1"

    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should raise SyntaxError since window functions are not yet implemented
    with pytest.raises(SyntaxError):
        parser.parse()

# --- 6. Integration Tests ---

def test_window_function_full_pipeline_not_implemented(global_runner):
    """Test that window functions are not yet implemented in full pipeline."""
    sql = "SELECT Name, ROW_NUMBER() OVER (ORDER BY Salary DESC) as rn FROM Employees"

    # Should raise SyntaxError since window functions are not yet implemented
    with pytest.raises(SyntaxError):
        global_runner.run(sql)

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

# --- 8. Advanced Window Function Tests ---

def test_window_function_with_aliases_not_implemented():
    """Test that window functions with aliases are not yet implemented."""
    sql = """
    SELECT Salary, Salary * 1.1 as AdjustedSalary,
           ROW_NUMBER() OVER (ORDER BY AdjustedSalary) as rn
    FROM Employees
    """

    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)

    # Should raise SyntaxError since window functions are not yet implemented
    with pytest.raises(SyntaxError):
        parser.parse()

# --- 9. Named Window Specifications ---

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
