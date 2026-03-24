"""
test_binder_runner_coverage_suite.py

Covers missing lines in binder.py and runner.py:

binder.py:
  - Line 93:   get_cols in _bind_union returns [] for non-Select/Union node
  - Line 171:  Column not found in CTE/temp table virtual schema → SemanticError
  - Line 176:  Single-scope table with no registry entry, column passes through
  - Lines 198-203: Single-scope virtual schema (CTE/temp) column found / not found
  - Lines 205-206: Single-scope registry has_column check
  - Line 210:  Unknown qualifier raises SemanticError
  - Line 253:  ANY/ALL operator type incompatibility
  - Line 318:  Multi-column scalar subquery → inferred_type = "UNKNOWN"
  - Line 392:  _bind_declare with default_value (DECLARE @x INT = 5)
  - Line 458:  _check_agg_integrity for FunctionCallNode in GROUP BY validation
  - Lines 460-462: _check_agg_integrity for CaseExpressionNode in GROUP BY

runner.py:
  - Line 28:   load_metadata_from_csv with str input (uses io.StringIO)
  - Lines 68-72: parse_only() method
  - Line 94:   empty batch continue in run_script (consecutive GO separators)
"""

import pytest
import io
from birdeye.runner import BirdEyeRunner
from birdeye.binder import Binder, SemanticError
from birdeye.registry import MetadataRegistry


@pytest.fixture(scope="module")
def runner(global_runner):
    return global_runner


# ---------------------------------------------------------------------------
# runner.py coverage
# ---------------------------------------------------------------------------

def test_load_metadata_from_csv_string_input():
    """
    runner.py line 28: load_metadata_from_csv receives a plain str,
    triggers the isinstance(csv_content, str) branch → io.StringIO(csv_content).
    """
    runner_fresh = BirdEyeRunner()
    csv_str = "table_name,column_name,data_type\nAddress,AddressID,INT\n"
    runner_fresh.load_metadata_from_csv(csv_str)
    result = runner_fresh.run("SELECT AddressID FROM Address")
    assert result["status"] == "success"


def test_parse_only_returns_ast(runner):
    """
    runner.py lines 68-72: parse_only() skips the Binder entirely.
    The returned dict must contain 'ast'.
    """
    result = runner.parse_only("SELECT CustomerID FROM Customer")
    assert "ast" in result


def test_parse_only_accepts_unknown_columns(runner):
    """
    parse_only() must succeed even when the column does not exist in the
    registry, because no binding / schema validation takes place.
    """
    result = runner.parse_only("SELECT NonExistentColumn FROM NonExistentTable")
    assert "ast" in result


def test_run_script_empty_batch_between_consecutive_go():
    """
    runner.py line 94: consecutive GO separators produce empty batch_sql strings.
    The 'if not batch_sql: continue' guard must fire, skipping empty batches.
    """
    runner_fresh = BirdEyeRunner()
    csv_str = "table_name,column_name,data_type\nAddress,AddressID,INT\n"
    runner_fresh.load_metadata_from_csv(csv_str)

    sql = "SELECT AddressID FROM Address\nGO\n\nGO\nSELECT AddressID FROM Address"
    result = runner_fresh.run_script(sql)
    assert result["status"] == "success"
    # Two non-empty batches → two entries in batches list
    assert len(result["batches"]) == 2


# ---------------------------------------------------------------------------
# binder.py coverage
# ---------------------------------------------------------------------------

# --- Line 392: _bind_declare with default_value ---

def test_declare_with_default_value(runner):
    """
    binder.py line 392: DECLARE @x INT = 5 triggers _bind_declare which
    calls self._visit_expression(stmt.default_value).
    """
    result = runner.run("DECLARE @x INT = 5")
    assert result["status"] == "success"


# --- Line 210: Unknown qualifier raises SemanticError ---

def test_unknown_qualifier_raises_semantic_error(runner):
    """
    binder.py line 210: When f_qual is set but found_qual is False after
    searching all scopes, raise SemanticError("Unknown qualifier ...").
    """
    with pytest.raises(SemanticError, match="Unknown qualifier 'xyz'"):
        runner.run("SELECT xyz.CustomerID FROM Customer")


# --- Line 171: Column not found in CTE virtual schema ---

def test_cte_column_not_found_raises_semantic_error(runner):
    """
    binder.py line 171: CTE virtual schema exists but the requested column
    is absent → raise SemanticError("Column '...' not found in '...'").
    """
    sql = """
        WITH cte AS (SELECT CustomerID FROM Customer)
        SELECT NonExistent FROM cte
    """
    with pytest.raises(SemanticError):
        runner.run(sql)


# --- Lines 198-203: Single-scope virtual schema column found / not found ---

def test_cte_virtual_schema_column_found(runner):
    """
    binder.py lines 198-200: Single-scope virtual schema (CTE), column exists
    → set inferred_type and return (the happy path).
    """
    sql = """
        WITH cte AS (SELECT CustomerID FROM Customer)
        SELECT CustomerID FROM cte
    """
    result = runner.run(sql)
    assert result["status"] == "success"


def test_cte_virtual_schema_column_not_found_single_scope(runner):
    """
    binder.py lines 201-202: Single-scope virtual schema has the column name
    table in its dict but the requested column is absent (vs is non-empty)
    → raise SemanticError.
    This is the same code path as line 171 for the single-scope unqualified
    case; the CTE schema is non-empty but the column is missing.
    """
    sql = """
        WITH cte AS (SELECT CustomerID FROM Customer)
        SELECT CompanyName FROM cte
    """
    with pytest.raises(SemanticError):
        runner.run(sql)


# --- Lines 205-206: Single-scope registry has_column check ---

def test_single_scope_registry_has_column(runner):
    """
    binder.py lines 205-206: Single table in scope, no virtual schema, but
    registry.has_column succeeds → resolve type and return.
    A plain single-table query exercises this path when the column exists in
    the registry and there is exactly one table in scope.
    """
    result = runner.run(
        "SELECT AddressID FROM Address WHERE ModifiedDate > '2020-01-01'"
    )
    assert result["status"] == "success"


# --- Line 253: ANY/ALL type incompatibility ---

def test_any_all_type_mismatch_raises_semantic_error(runner):
    """
    binder.py line 253: CustomerID is INT; CompanyName is VARCHAR.
    Comparing INT > ANY (subquery returning VARCHAR) is incompatible.
    """
    sql = (
        "SELECT CustomerID FROM Customer "
        "WHERE CustomerID > ANY "
        "(SELECT CompanyName FROM Customer WHERE CustomerID = 1)"
    )
    with pytest.raises(SemanticError):
        runner.run(sql)


# --- Line 318: Multi-column scalar subquery → inferred_type = "UNKNOWN" ---

def test_multi_column_scalar_subquery_sets_unknown_type(runner):
    """
    binder.py line 318: When a subquery in expression position returns more
    than one column, inferred_type is set to "UNKNOWN" (not an error).
    The statement should complete binding successfully.
    """
    sql = (
        "SELECT (SELECT CustomerID, CompanyName FROM Customer "
        "WHERE CustomerID = 1) FROM Customer"
    )
    # Should succeed — multi-col scalar subquery gets UNKNOWN, not an exception
    result = runner.run(sql)
    assert result["status"] == "success"


# --- Line 93: get_cols returns [] for non-Select/Union node in _bind_union ---

def test_bind_union_get_cols_fallback():
    """
    binder.py line 93: The inner get_cols() helper inside _bind_union returns []
    for any node that is neither SelectStatement nor UnionStatement.
    This is a guard; triggering it requires injecting a synthetic node as one
    side of a UnionStatement.  We test it via the Binder directly.
    """
    from birdeye.ast import UnionStatement, SelectStatement, IdentifierNode, LiteralNode

    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(
        "table_name,column_name,data_type\nT,Col1,INT\n"
    ))
    binder = Binder(reg)

    # Build a UnionStatement where the right side is a raw node (not Select/Union)
    # so get_cols(right) returns [].
    left = SelectStatement()
    col = IdentifierNode(name="Col1")
    col.inferred_type = "INT"
    left.columns = [col]
    left.table = IdentifierNode(name="T")
    left.table_alias = None

    # A SelectStatement that has been pre-bound and has columns[] to avoid
    # recursing into real binding for the left side.
    # For the right side, use a LiteralNode (not Select/Union) to trigger line 93.
    lit = LiteralNode(value="1", type=None)
    lit.inferred_type = "INT"

    union = UnionStatement(left=left, right=lit, operator="UNION")

    # _bind_union calls get_cols on both sides; right side is LiteralNode → []
    # Left has 1 col, right has 0 cols → column count mismatch SemanticError.
    with pytest.raises(SemanticError, match="equal number of expressions"):
        binder._bind_union(union)


# --- Line 176: Single-scope table with no registry entry, column passes through ---

def test_single_scope_no_registry_entry_column_passthrough():
    """
    binder.py line 176: When the table is in scope and the qualifier resolves to
    it, but the registry has no column list for that table
    (registry.get_columns returns []) → the final else branch is skipped and
    the function returns without raising (pass-through for unknown schema).
    This simulates a schema-less table alias or a table not in the registry.
    """
    reg = MetadataRegistry()
    # Register the table with no columns so has_table passes but get_columns
    # returns [] and has_column returns False.
    reg.tables["GHOSTCOLS"] = {}

    from birdeye.ast import IdentifierNode

    binder = Binder(reg)
    binder.scopes.append({"GHOSTCOLS": "GHOSTCOLS"})
    binder.nullable_stack.append(set())

    # qualifiers=["GHOSTCOLS"] makes node.qualifier == "GHOSTCOLS"
    node = IdentifierNode(name="SomeCol", qualifiers=["GHOSTCOLS"])
    # Should NOT raise — registry.get_columns("GHOSTCOLS") returns [] → return (line 176)
    binder._resolve_identifier(node)
    # inferred_type stays at its default UNKNOWN; no SemanticError raised


# --- Line 392 (run_script path): DECLARE with default value in run_script ---

def test_declare_with_default_value_in_run_script():
    """
    binder.py line 392 via run_script: DECLARE @id INT = 5 followed by a SELECT
    that uses @id.  Both statements are in the same batch so the variable is
    visible to the SELECT.
    run_script creates a fresh Binder that persists across statements within one
    batch, so @id declared before GO is accessible after.
    """
    runner_fresh = BirdEyeRunner()
    csv_str = "table_name,column_name,data_type\nAddress,AddressID,INT\n"
    runner_fresh.load_metadata_from_csv(csv_str)

    sql = "DECLARE @id INT = 5\nSELECT AddressID FROM Address WHERE AddressID = @id"
    result = runner_fresh.run_script(sql)
    assert result["status"] == "success"


# --- Line 458: _check_agg_integrity for FunctionCallNode inside non-grouped col ---

def test_check_agg_integrity_function_in_non_grouped_col(runner):
    """
    binder.py line 458: When a SELECT column contains a non-aggregate
    FunctionCallNode that is not in GROUP BY, _check_agg_integrity recurses
    into its args.  This covers the elif isinstance(expr, FunctionCallNode) branch.
    LEN(CompanyName) is not an aggregate and CompanyName is not in GROUP BY
    CustomerID → SemanticError.
    """
    sql = (
        "SELECT LEN(CompanyName), COUNT(*) "
        "FROM Customer "
        "GROUP BY CustomerID"
    )
    with pytest.raises(SemanticError):
        runner.run(sql)


# --- Lines 460-462: _check_agg_integrity for CaseExpressionNode in GROUP BY ---

def test_check_agg_integrity_case_expression_not_in_group_by(runner):
    """
    binder.py lines 460-462: A CASE expression whose branches reference a column
    that is not in the GROUP BY list triggers the CaseExpressionNode branch of
    _check_agg_integrity.
    CompanyName is not in GROUP BY CustomerID → SemanticError.
    """
    sql = (
        "SELECT CASE WHEN CompanyName = 'AW00000001' THEN 'yes' ELSE 'no' END, "
        "COUNT(*) "
        "FROM Customer "
        "GROUP BY CustomerID"
    )
    with pytest.raises(SemanticError):
        runner.run(sql)
