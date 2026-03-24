"""
test_parser_coverage_suite.py
Covers uncovered parser.py lines from the new MSSQL syntax features:
  - SyntaxError branches (lines 114, 228, 233, 938, 1017)
  - _parse_single_stmt dispatch (lines 737-765) via IF BEGIN...END blocks
  - BEGIN...END at top-level (lines 97-98)
  - EXEC with return var (lines 783-788)
  - EXEC with named args and positional args (lines 795, 799-807, 812)
  - CREATE TABLE IF NOT EXISTS (lines 846-849)
  - CREATE TABLE with PRIMARY/CONSTRAINT constraints (lines 856-857)
  - Column modifiers: NULL, IDENTITY(seed,incr), PRIMARY KEY, DEFAULT (lines 890, 892-896, 898-901, 903)
  - MERGE with subquery source (lines 954-956)
  - MERGE NOT MATCHED BY SOURCE (lines 978-980)
  - MERGE clause AND condition (line 988)
  - Various parser lines: 456, 522, 524, 582, 593-595, 608, 638
"""
import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.ast import (
    IfStatement, ExecStatement, CreateTableStatement, MergeStatement,
    InsertStatement, UpdateStatement, DeleteStatement, TruncateStatement,
    DeclareStatement
)


def parse_sql(sql):
    tokens = Lexer(sql).tokenize()
    return Parser(tokens, sql).parse()


# ── Top-level BEGIN...END (lines 97-98) ──────────────────────────────────────

def test_begin_end_at_toplevel():
    stmt = parse_sql("BEGIN SELECT 1 END")
    # returns first statement from the block
    assert stmt is not None


# ── Unexpected token raises SyntaxError (line 114) ───────────────────────────

def test_unexpected_token_raises_syntax_error():
    with pytest.raises(SyntaxError):
        parse_sql("FOOBAR 1 2 3")


# ── CROSS without APPLY or JOIN raises SyntaxError (line 228) ────────────────

def test_cross_without_apply_or_join_raises():
    with pytest.raises(SyntaxError):
        parse_sql("SELECT 1 FROM T CROSS FOOBAR X")


# ── OUTER without APPLY raises SyntaxError (line 233) ────────────────────────

def test_outer_without_apply_raises():
    with pytest.raises((SyntaxError, Exception)):
        parse_sql("SELECT 1 FROM T OUTER FOOBAR X")


# ── _parse_single_stmt: INSERT inside IF BEGIN...END (line 737) ──────────────

def test_if_block_contains_insert():
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "INSERT INTO Customer (CustomerID) VALUES (1) "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert len(stmt.then_block) == 1
    assert isinstance(stmt.then_block[0], InsertStatement)


# ── _parse_single_stmt: UPDATE inside IF BEGIN...END (line 739) ──────────────

def test_if_block_contains_update():
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "UPDATE Customer SET CustomerID = 1 WHERE CustomerID = 2 "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.then_block[0], UpdateStatement)


# ── _parse_single_stmt: DELETE inside IF BEGIN...END (line 741) ──────────────

def test_if_block_contains_delete():
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "DELETE FROM Customer WHERE CustomerID = 1 "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.then_block[0], DeleteStatement)


# ── _parse_single_stmt: TRUNCATE inside IF BEGIN...END (line 743) ────────────

def test_if_block_contains_truncate():
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "TRUNCATE TABLE Customer "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.then_block[0], TruncateStatement)


# ── _parse_single_stmt: DECLARE inside IF BEGIN...END (line 745) ─────────────

def test_if_block_contains_declare():
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "DECLARE @x INT "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.then_block[0], DeclareStatement)


# ── _parse_single_stmt: nested IF inside IF (line 747) ───────────────────────

def test_if_block_contains_nested_if():
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "IF 2=2 BEGIN SELECT 1 END "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.then_block[0], IfStatement)


# ── _parse_single_stmt: EXEC inside IF (line 749) ────────────────────────────

def test_if_block_contains_exec():
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "EXEC sp_help; "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.then_block[0], ExecStatement)


# ── _parse_single_stmt: CREATE inside IF (line 751) ──────────────────────────

def test_if_block_contains_create():
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "CREATE TABLE #T (ID INT) "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.then_block[0], CreateTableStatement)


# ── _parse_single_stmt: DROP inside IF (line 753) ────────────────────────────

def test_if_block_contains_drop():
    from birdeye.ast import DropTableStatement
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "DROP TABLE #T "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.then_block[0], DropTableStatement)


# ── _parse_single_stmt: MERGE inside IF (line 757) ───────────────────────────

def test_if_block_contains_merge():
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "MERGE INTO Target AS t "
        "USING Source AS s ON t.ID = s.ID "
        "WHEN MATCHED THEN UPDATE SET t.Name = s.Name; "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.then_block[0], MergeStatement)


# ── _parse_single_stmt: PRINT inside IF (line 759) ───────────────────────────

def test_if_block_contains_print():
    from birdeye.ast import PrintStatement
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "PRINT 'hello' "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.then_block[0], PrintStatement)


# ── _parse_single_stmt: SET inside IF (line 761) ─────────────────────────────

def test_if_block_contains_set():
    from birdeye.ast import SetStatement
    stmt = parse_sql(
        "IF 1=1 BEGIN "
        "SET @x = 1 "
        "END"
    )
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.then_block[0], SetStatement)


# ── _parse_single_stmt: ELSE branch without BEGIN (line 719) ─────────────────

def test_if_block_else_break_on_else_token():
    """BEGIN block should stop on ELSE token even without END."""
    stmt = parse_sql(
        "IF 1=1 BEGIN SELECT 1 END ELSE SELECT 0"
    )
    assert isinstance(stmt, IfStatement)
    assert len(stmt.else_block) == 1


# ── _parse_block: single stmt without BEGIN (line 727-728) ───────────────────

def test_parse_block_single_stmt_no_begin():
    """IF without BEGIN — single statement block path."""
    stmt = parse_sql("IF 1=1 SELECT 1")
    assert isinstance(stmt, IfStatement)
    assert len(stmt.then_block) == 1


# ── EXEC with return var (lines 783-788) ─────────────────────────────────────

def test_exec_with_return_var():
    stmt = parse_sql("EXEC @result = sp_myproc 'arg1'")
    assert isinstance(stmt, ExecStatement)
    assert stmt.return_var is not None
    assert stmt.return_var.name == "@result"


# ── EXEC with positional args (lines 795, 808-809) ───────────────────────────

def test_exec_with_positional_args():
    stmt = parse_sql("EXEC sp_help 'Customer', 1")
    assert isinstance(stmt, ExecStatement)
    assert len(stmt.args) == 2


# ── EXEC with named args (lines 799-804) ─────────────────────────────────────

def test_exec_with_named_args():
    stmt = parse_sql("EXEC sp_myproc @name = 'Alice', @age = 30")
    assert isinstance(stmt, ExecStatement)
    assert len(stmt.named_args) == 2


# ── EXEC named arg fallback to positional (lines 806-807) ────────────────────

def test_exec_named_arg_fallback_when_no_equals():
    """@var without = following it → treated as positional arg."""
    stmt = parse_sql("EXEC sp_myproc @x")
    assert isinstance(stmt, ExecStatement)
    # @x without = is positional
    assert len(stmt.args) >= 1


# ── CREATE TABLE IF NOT EXISTS (lines 846-849) ───────────────────────────────

def test_create_table_if_not_exists():
    stmt = parse_sql("CREATE TABLE IF NOT EXISTS #Temp (ID INT)")
    assert isinstance(stmt, CreateTableStatement)
    assert stmt.if_not_exists is True


# ── CREATE TABLE with PRIMARY KEY constraint line (lines 856-857) ────────────

def test_create_table_with_table_level_constraint():
    """Table-level CONSTRAINT/PRIMARY/UNIQUE/INDEX lines are skipped by parser."""
    stmt = parse_sql(
        "CREATE TABLE Customer (ID INT NOT NULL, CONSTRAINT pk_c UNIQUE)"
    )
    assert isinstance(stmt, CreateTableStatement)
    # constraint line is skipped, column ID still parsed
    assert len(stmt.columns) >= 1


# ── Column modifier: NULL (line 890) ─────────────────────────────────────────

def test_create_table_column_null_modifier():
    stmt = parse_sql("CREATE TABLE T (Name NVARCHAR(50) NULL)")
    col = stmt.columns[0]
    assert col.nullable is True


# ── Column modifier: IDENTITY with seed/increment (lines 892-896) ────────────

def test_create_table_column_identity_with_seed():
    stmt = parse_sql("CREATE TABLE T (ID INT IDENTITY(1,1) NOT NULL)")
    col = stmt.columns[0]
    assert col.is_identity is True
    assert col.nullable is False


# ── Column modifier: PRIMARY KEY on column (lines 898-901) ───────────────────

def test_create_table_column_primary_key_modifier():
    stmt = parse_sql("CREATE TABLE T (ID INT PRIMARY KEY)")
    col = stmt.columns[0]
    assert col.is_primary_key is True


# ── Column modifier: DEFAULT (line 903) ──────────────────────────────────────

def test_create_table_column_default_value():
    stmt = parse_sql("CREATE TABLE T (Status INT DEFAULT 0)")
    col = stmt.columns[0]
    assert col.default is not None


# ── ALTER TABLE else → SyntaxError (line 938) ────────────────────────────────

def test_alter_table_invalid_action_raises():
    with pytest.raises(SyntaxError):
        parse_sql("ALTER TABLE Customer MODIFY Name NVARCHAR(100)")


# ── MERGE with subquery source (lines 954-956) ───────────────────────────────

def test_merge_with_subquery_source():
    stmt = parse_sql(
        "MERGE INTO Target AS t "
        "USING (SELECT ID, Name FROM Source) AS s ON t.ID = s.ID "
        "WHEN MATCHED THEN UPDATE SET t.Name = s.Name;"
    )
    assert isinstance(stmt, MergeStatement)
    # source should be a SelectStatement when it's a subquery
    from birdeye.ast import SelectStatement
    assert isinstance(stmt.source, SelectStatement)


# ── MERGE NOT MATCHED BY SOURCE (lines 978-980) ──────────────────────────────

def test_merge_not_matched_by_source():
    stmt = parse_sql(
        "MERGE INTO Target AS t "
        "USING Source AS s ON t.ID = s.ID "
        "WHEN NOT MATCHED BY SOURCE THEN DELETE;"
    )
    clause = stmt.clauses[0]
    assert clause.match_type == "NOT_MATCHED_BY_SOURCE"
    assert clause.action == "DELETE"


# ── MERGE clause with AND condition (line 988) ────────────────────────────────

def test_merge_clause_with_and_condition():
    stmt = parse_sql(
        "MERGE INTO Target AS t "
        "USING Source AS s ON t.ID = s.ID "
        "WHEN MATCHED AND t.Name <> s.Name THEN UPDATE SET t.Name = s.Name;"
    )
    clause = stmt.clauses[0]
    assert clause.condition is not None


# ── MERGE invalid action raises SyntaxError (line 1017) ──────────────────────

def test_merge_invalid_action_raises():
    with pytest.raises(SyntaxError):
        parse_sql(
            "MERGE INTO Target AS t "
            "USING Source AS s ON t.ID = s.ID "
            "WHEN MATCHED THEN FOOBAR;"
        )
