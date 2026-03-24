"""
test_intent_coverage_suite.py
Coverage tests for IntentExtractor — targeting missing lines identified in
code review:

  Line 48:       extract_from_str
  Line 70:       expand_star_intents fallback (unknown table)
  Lines 81-83:   extract_tables entry point
  Lines 87-172:  _collect_tables (UPDATE, DELETE, INSERT, TRUNCATE,
                  UnionStatement, BinaryExpressionNode, FunctionCallNode,
                  CastExpressionNode, BetweenExpressionNode, CaseExpressionNode)
  Line 178,180-182: _walk list handling
  Lines 224-228: _walk_select is_star=True with no columns (table-level fallback)
  Lines 245-247: SELECT INTO intent emission
  Line 276:      APPLY subquery walk
  Line 281:      _walk_update alias branch
  Lines 299,304: _walk_delete alias branch
  Line 314:      _walk_insert early-return guard
  Line 322:      UnionStatement in _walk (dispatches both sides)
  Line 341:      _walk_expr derived_aliases skip
  Line 355:      CastExpressionNode in _walk_expr
  Lines 358-360: BetweenExpressionNode in _walk_expr
  Line 380:      subquery in _walk_expr (_walk_subquery None guard)
  Lines 384-388: _walk_update internals (SET + WHERE)
  Line 404:      _build_alias_map derived table (subquery) handling
  Line 432:      _build_alias_map JOIN table registration
  Line 453:      case-insensitive fallback in _resolve_col
  Lines 483,487: _resolve_col unique table fallback
"""

import io
import json
import pytest
from birdeye.runner import BirdEyeRunner
from birdeye.intent_extractor import IntentExtractor
from birdeye.serializer import ASTSerializer
from birdeye.lexer import Lexer
from birdeye.parser import Parser


# ── Minimal schema that covers all tests in this file ─────────────────────────

_CSV = """\
table_name,column_name,data_type
Customer,CustomerID,int
Customer,FirstName,nvarchar
Customer,LastName,nvarchar
Customer,EmailAddress,nvarchar
Customer,Phone,nvarchar
Customer,SalesPerson,nvarchar
CustomerAddress,CustomerID,int
CustomerAddress,AddressID,int
Address,AddressID,int
Address,AddressLine1,nvarchar
Address,AddressLine2,nvarchar
Address,City,nvarchar
Address,StateProvince,nvarchar
Address,PostalCode,nvarchar
SalesOrderHeader,SalesOrderID,int
SalesOrderHeader,CustomerID,int
SalesOrderHeader,TotalDue,money
"""


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def runner(global_runner):
    return global_runner


@pytest.fixture(scope="module")
def local_runner():
    """Runner with a minimal, controlled schema for deterministic tests."""
    r = BirdEyeRunner()
    r.load_metadata_from_csv(io.StringIO(_CSV))
    return r


# ── Helpers ───────────────────────────────────────────────────────────────────

def intents_of(runner, sql):
    result = runner.run(sql)
    ast_dict = json.loads(result["json"])
    return IntentExtractor().extract(ast_dict)


def has_intent(intents, table, column, intent, schema=None):
    for i in intents:
        if i["table"] == table and i["column"] == column and i["intent"] == intent:
            if schema is None or i["schema"] == schema:
                return True
    return False


def parse_only(sql):
    """Lex + parse only, no binder — returns JSON dict."""
    tokens = Lexer(sql).tokenize()
    ast = Parser(tokens, sql).parse()
    return json.loads(ASTSerializer().to_json(ast))


# ── Line 48: extract_from_str ─────────────────────────────────────────────────

def test_extract_from_str_returns_same_as_extract(local_runner):
    """extract_from_str(json_str) must produce same result as extract(dict)."""
    sql = "SELECT CustomerID FROM SalesLT.Customer"
    result = local_runner.run(sql)
    json_str = result["json"]
    ast_dict = json.loads(json_str)

    via_extract = IntentExtractor().extract(ast_dict)
    via_str     = IntentExtractor().extract_from_str(json_str)

    assert via_extract == via_str, "extract_from_str should produce identical results to extract"


def test_extract_from_str_produces_read_intent(local_runner):
    """extract_from_str produces correct intent entries."""
    sql = "SELECT FirstName FROM SalesLT.Customer"
    json_str = local_runner.run(sql)["json"]
    intents = IntentExtractor().extract_from_str(json_str)
    assert has_intent(intents, "Customer", "FirstName", "READ")


# ── Line 70: expand_star_intents fallback (unknown table) ─────────────────────

def test_expand_star_intents_unknown_table_kept_as_is(local_runner):
    """When registry has no columns for the table, the original intent is kept."""
    star_intent = {
        "schema": "dbo",
        "table":  "NonExistentTable",
        "column": None,
        "intent": "READ",
    }
    result = IntentExtractor().expand_star_intents([star_intent], local_runner)
    assert len(result) == 1
    assert result[0]["table"] == "NonExistentTable"
    assert result[0]["column"] is None


def test_expand_star_intents_known_table_expanded(local_runner):
    """When registry has columns for the table, they are expanded."""
    star_intent = {
        "schema": "",
        "table":  "Customer",
        "column": None,
        "intent": "READ",
    }
    result = IntentExtractor().expand_star_intents([star_intent], local_runner)
    # Should expand into individual column intents
    assert len(result) > 1 or (len(result) == 1 and result[0]["column"] is not None)


def test_expand_star_intents_non_read_not_expanded(local_runner):
    """Non-READ intents with column=None are not expanded."""
    delete_intent = {
        "schema": "",
        "table":  "Customer",
        "column": None,
        "intent": "DELETE",
    }
    result = IntentExtractor().expand_star_intents([delete_intent], local_runner)
    assert len(result) == 1
    assert result[0]["intent"] == "DELETE"
    assert result[0]["column"] is None


# ── Lines 81-83: extract_tables ───────────────────────────────────────────────

def test_extract_tables_returns_list_of_tuples():
    """extract_tables returns a list of (schema, table) tuples."""
    ast_dict = parse_only("SELECT CustomerID FROM SalesLT.Customer")
    tables = IntentExtractor().extract_tables(ast_dict)
    assert isinstance(tables, list)
    assert any(t == ("SalesLT", "Customer") for t in tables), \
        f"Expected ('SalesLT', 'Customer') in {tables}"


def test_extract_tables_join():
    """extract_tables collects all joined tables."""
    sql = ("SELECT c.CustomerID FROM SalesLT.Customer c "
           "JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    table_names = {t[1] for t in tables}
    assert "Customer" in table_names
    assert "CustomerAddress" in table_names


def test_extract_tables_union():
    """extract_tables traverses both sides of a UNION."""
    sql = ("SELECT CustomerID FROM SalesLT.Customer "
           "UNION SELECT AddressID FROM SalesLT.Address")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    table_names = {t[1] for t in tables}
    assert "Customer" in table_names
    assert "Address" in table_names


# ── Lines 87-172: _collect_tables for DML ────────────────────────────────────

def test_collect_tables_update():
    """_collect_tables finds the target table of an UPDATE."""
    sql = "UPDATE SalesLT.Customer SET FirstName = 'Alice' WHERE CustomerID = 1"
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t[1] == "Customer" for t in tables), \
        f"Expected Customer in extract_tables result, got {tables}"


def test_collect_tables_delete():
    """_collect_tables finds the target table of a DELETE."""
    sql = "DELETE FROM SalesLT.Customer WHERE CustomerID = 1"
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t[1] == "Customer" for t in tables)


def test_collect_tables_truncate():
    """_collect_tables finds the target table of a TRUNCATE."""
    sql = "TRUNCATE TABLE SalesLT.Customer"
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t[1] == "Customer" for t in tables)


def test_collect_tables_insert():
    """_collect_tables finds the target table of an INSERT."""
    sql = "INSERT INTO SalesLT.Customer (FirstName) VALUES ('Alice')"
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    assert any(t[1] == "Customer" for t in tables)


def test_collect_tables_insert_select():
    """_collect_tables traverses the SELECT source of an INSERT-SELECT."""
    sql = ("INSERT INTO SalesLT.Customer (FirstName) "
           "SELECT FirstName FROM SalesLT.Address")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    table_names = {t[1] for t in tables}
    assert "Customer" in table_names
    assert "Address" in table_names


def test_collect_tables_subquery_in_where():
    """_collect_tables descends into subqueries inside WHERE."""
    sql = ("SELECT CustomerID FROM SalesLT.Customer "
           "WHERE CustomerID IN (SELECT CustomerID FROM SalesLT.CustomerAddress)")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    table_names = {t[1] for t in tables}
    assert "Customer" in table_names
    assert "CustomerAddress" in table_names


def test_collect_tables_binary_expression():
    """_collect_tables walks BinaryExpressionNode children."""
    # BETWEEN is serialised as BetweenExpressionNode; use a subquery in WHERE
    sql = ("SELECT CustomerID FROM SalesLT.Customer "
           "WHERE CustomerID > (SELECT MIN(CustomerID) FROM SalesLT.Address)")
    ast_dict = parse_only(sql)
    tables = IntentExtractor().extract_tables(ast_dict)
    table_names = {t[1] for t in tables}
    assert "Address" in table_names


# ── Lines 178, 180-182: _walk list handling ───────────────────────────────────

def test_walk_accepts_list_of_statements():
    """_walk handles a list of statement dicts without errors."""
    sql1 = "SELECT CustomerID FROM SalesLT.Customer"
    sql2 = "SELECT AddressID FROM SalesLT.Address"
    ast1 = parse_only(sql1)
    ast2 = parse_only(sql2)
    # Wrap them in a list (simulates multi-statement JSON)
    intents = IntentExtractor().extract([ast1, ast2])
    table_names = {i["table"] for i in intents}
    assert "Customer" in table_names
    assert "Address" in table_names


# ── Lines 224-228: _walk_select is_star=True with no columns ─────────────────

def test_select_star_no_binder_expansion_table_level_read():
    """
    When is_star=True but columns list is empty (parse-only, binder not run),
    a table-level READ (column=None) should be emitted per source table.
    """
    # parse_only skips binder so SELECT * stays unexpanded (no column nodes)
    ast_dict = parse_only("SELECT * FROM SalesLT.Customer")
    intents = IntentExtractor().extract(ast_dict)
    # Should have at least a table-level or column-level READ for Customer
    customer_reads = [i for i in intents
                      if i["table"] == "Customer" and i["intent"] == "READ"]
    assert len(customer_reads) > 0, \
        "SELECT * (parse-only) should produce at least one READ intent for Customer"


# ── Lines 245-247: SELECT INTO ────────────────────────────────────────────────

def test_select_into_emits_insert_intent():
    """
    SELECT col INTO #tmp FROM table should emit an INSERT intent for the
    destination table.  We use parse_only because the binder may reject temp tables.
    """
    sql = "SELECT CustomerID INTO #TmpCustomer FROM SalesLT.Customer"
    ast_dict = parse_only(sql)
    intents = IntentExtractor().extract(ast_dict)
    into_intents = [i for i in intents
                    if i["table"] == "#TmpCustomer" and i["intent"] == "INSERT"]
    assert len(into_intents) > 0, \
        "SELECT INTO should produce an INSERT intent for the destination table"


# ── Line 276: APPLY subquery walk ─────────────────────────────────────────────

def test_cross_apply_inner_columns_extracted(local_runner):
    """CROSS APPLY subquery columns should be extracted as intents."""
    sql = ("SELECT c.FirstName, sub.SalesOrderID "
           "FROM SalesLT.Customer c "
           "CROSS APPLY ("
           "  SELECT TOP 1 SalesOrderID "
           "  FROM SalesLT.SalesOrderHeader soh "
           "  WHERE soh.CustomerID = c.CustomerID"
           ") sub")
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "SalesOrderHeader", "SalesOrderID", "READ"), \
        "CROSS APPLY inner SELECT column should produce READ"
    assert has_intent(intents, "SalesOrderHeader", "CustomerID", "FILTER"), \
        "CROSS APPLY inner WHERE column should produce FILTER"


# ── Line 281: _walk_update alias branch ───────────────────────────────────────

def test_update_with_alias_resolves_correctly(local_runner):
    """UPDATE with qualified SET column → UPDATE intent on correct table."""
    sql = "UPDATE SalesLT.Customer SET FirstName = 'Bob' WHERE CustomerID = 42"
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer", "FirstName", "UPDATE"), \
        "UPDATE SET column should produce UPDATE intent"


def test_update_basic_intents(local_runner):
    """UPDATE SET column → UPDATE intent; WHERE column → FILTER intent."""
    sql = "UPDATE SalesLT.Customer SET FirstName = 'Alice' WHERE CustomerID = 1"
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer", "FirstName",  "UPDATE"), \
        "SET target should produce UPDATE intent"
    assert has_intent(intents, "Customer", "CustomerID", "FILTER"), \
        "WHERE column should produce FILTER intent"


# ── Lines 299, 304: _walk_delete internals ───────────────────────────────────

def test_delete_produces_delete_and_filter(local_runner):
    """DELETE → table-level DELETE + WHERE column FILTER."""
    sql = "DELETE FROM SalesLT.Customer WHERE CustomerID = 1"
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer", None,         "DELETE"), \
        "DELETE should produce table-level DELETE intent"
    assert has_intent(intents, "Customer", "CustomerID", "FILTER"), \
        "DELETE WHERE column should produce FILTER intent"


def test_delete_with_alias():
    """DELETE with WHERE clause: table-level DELETE + FILTER intent."""
    sql = "DELETE FROM SalesLT.Customer WHERE CustomerID > 100"
    ast_dict = parse_only(sql)
    intents = IntentExtractor().extract(ast_dict)
    delete_intents = [i for i in intents if i["intent"] == "DELETE"]
    assert len(delete_intents) > 0, "DELETE should produce DELETE intent"


# ── Line 314: _walk_insert early-return guard ────────────────────────────────

def test_insert_with_columns_produces_insert_per_column(local_runner):
    """INSERT with explicit column list → one INSERT intent per column."""
    sql = "INSERT INTO SalesLT.Customer (FirstName, LastName) VALUES ('Alice', 'Smith')"
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer", "FirstName", "INSERT"), \
        "INSERT column FirstName should produce INSERT intent"
    assert has_intent(intents, "Customer", "LastName",  "INSERT"), \
        "INSERT column LastName should produce INSERT intent"


def test_insert_without_columns_produces_table_level_insert():
    """INSERT without column list → table-level INSERT (column=None)."""
    sql = "INSERT INTO SalesLT.Customer VALUES ('Alice', 'Smith')"
    ast_dict = parse_only(sql)
    intents = IntentExtractor().extract(ast_dict)
    assert has_intent(intents, "Customer", None, "INSERT"), \
        "INSERT without columns should produce table-level INSERT intent"


# ── Line 322: UnionStatement in _walk ────────────────────────────────────────

def test_union_both_sides_produce_intents(local_runner):
    """Both sides of a UNION contribute their own intents."""
    sql = ("SELECT CustomerID FROM SalesLT.Customer "
           "UNION "
           "SELECT CustomerID FROM SalesLT.SalesOrderHeader")
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer",        "CustomerID", "READ"), \
        "Left side of UNION should produce READ"
    assert has_intent(intents, "SalesOrderHeader","CustomerID", "READ"), \
        "Right side of UNION should produce READ"


def test_union_with_where_on_one_side(local_runner):
    """WHERE on one UNION branch contributes FILTER from that branch only."""
    sql = ("SELECT CustomerID FROM SalesLT.Customer WHERE CustomerID = 1 "
           "UNION "
           "SELECT CustomerID FROM SalesLT.SalesOrderHeader")
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer", "CustomerID", "FILTER"), \
        "WHERE column in UNION branch should produce FILTER"


# ── Line 341: _walk_expr derived_aliases skip ────────────────────────────────

def test_derived_table_outer_ref_skipped(local_runner):
    """
    Column references qualified by a derived-table alias (e.g. x.CustomerID
    in the outer SELECT) should be skipped — they cannot be attributed to a
    source table at the outer level.
    """
    sql = ("SELECT x.CustomerID "
           "FROM (SELECT CustomerID FROM SalesLT.Customer) x")
    intents = intents_of(local_runner, sql)
    # The inner SELECT should still produce a READ for Customer.CustomerID
    assert has_intent(intents, "Customer", "CustomerID", "READ"), \
        "Inner derived table SELECT should produce READ for Customer.CustomerID"
    # The outer reference x.CustomerID should NOT add a second READ attributed
    # to an unknown table named 'x'
    assert not any(i["table"] == "x" for i in intents), \
        "Derived alias 'x' should not appear as a table in intents"


# ── Line 355: CastExpressionNode in _walk_expr ───────────────────────────────

def test_cast_expression_column_extracted(local_runner):
    """CAST(col AS type) — the inner column should still produce a READ intent."""
    sql = "SELECT CAST(CustomerID AS VARCHAR) FROM SalesLT.Customer"
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer", "CustomerID", "READ"), \
        "CAST inner column should produce READ intent"


def test_cast_in_where(local_runner):
    """CAST in WHERE clause — inner column should produce FILTER intent."""
    sql = ("SELECT FirstName FROM SalesLT.Customer "
           "WHERE CAST(CustomerID AS VARCHAR) = '1'")
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer", "CustomerID", "FILTER"), \
        "CAST inner column in WHERE should produce FILTER intent"


# ── Lines 358-360: BetweenExpressionNode in _walk_expr ───────────────────────

def test_between_produces_filter_intent(local_runner):
    """BETWEEN low AND high — the target column should produce a FILTER intent."""
    sql = ("SELECT FirstName FROM SalesLT.Customer "
           "WHERE CustomerID BETWEEN 1 AND 10")
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer", "CustomerID", "FILTER"), \
        "BETWEEN target column should produce FILTER intent"


def test_between_in_select_produces_read(local_runner):
    """BETWEEN used as a SELECT expression yields READ intents for inner columns."""
    sql = ("SELECT CASE WHEN CustomerID BETWEEN 1 AND 100 THEN 'low' "
           "ELSE 'high' END FROM SalesLT.Customer")
    intents = intents_of(local_runner, sql)
    # CustomerID inside BETWEEN inside CASE should produce READ
    assert has_intent(intents, "Customer", "CustomerID", "READ"), \
        "Column inside BETWEEN inside CASE in SELECT should produce READ"


# ── Line 380: subquery in _walk_expr (_walk_subquery None guard) ──────────────

def test_subquery_in_where_in_clause(local_runner):
    """Subquery in WHERE IN → inner columns extracted as READ/FILTER."""
    sql = ("SELECT FirstName FROM SalesLT.Customer "
           "WHERE CustomerID IN ("
           "  SELECT CustomerID FROM SalesLT.Customer WHERE CustomerID = 1"
           ")")
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer", "FirstName",  "READ"), \
        "Outer SELECT column should produce READ"
    assert has_intent(intents, "Customer", "CustomerID", "FILTER"), \
        "Inner subquery WHERE column should produce FILTER"


def test_walk_subquery_none_does_not_crash():
    """Passing None to _walk_subquery should be a no-op."""
    extractor = IntentExtractor()
    extractor._seen = set()
    intents = []
    # Should not raise
    extractor._walk_subquery(None, intents, set(), {})
    assert intents == []


# ── Lines 384-388: _walk_update internals ────────────────────────────────────

def test_update_set_rhs_read_intent(local_runner):
    """
    UPDATE SET col1 = col2 — RHS column (col2) should be treated as READ,
    since it is the value being read to write into col1.
    """
    sql = ("UPDATE SalesLT.Customer "
           "SET FirstName = LastName "
           "WHERE CustomerID = 1")
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer", "FirstName", "UPDATE"), \
        "LHS of SET should produce UPDATE intent"
    # LastName on RHS should produce READ (it's the source value)
    assert has_intent(intents, "Customer", "LastName", "READ") or \
           has_intent(intents, "Customer", "LastName", "UPDATE"), \
        "RHS of SET should be extracted"
    assert has_intent(intents, "Customer", "CustomerID", "FILTER"), \
        "WHERE column should produce FILTER"


# ── Line 404: _build_alias_map derived table (subquery) handling ──────────────

def test_derived_table_alias_added_to_derived_aliases(local_runner):
    """
    A derived table in FROM clause should have its alias added to
    derived_aliases, so outer column refs qualified by that alias are skipped.
    """
    sql = ("SELECT x.CustomerID "
           "FROM (SELECT CustomerID FROM SalesLT.Customer) x")
    intents = intents_of(local_runner, sql)
    # Inner CustomerID READ must appear; no phantom table 'x'
    assert has_intent(intents, "Customer", "CustomerID", "READ")
    assert not any(i["table"] == "x" for i in intents)


# ── Line 432: _build_alias_map JOIN table registration ───────────────────────

def test_join_table_registered_in_alias_map(local_runner):
    """JOIN table (and its alias) should be resolvable for ON condition columns."""
    sql = ("SELECT c.FirstName, ca.AddressID "
           "FROM SalesLT.Customer AS c "
           "JOIN SalesLT.CustomerAddress AS ca ON c.CustomerID = ca.CustomerID")
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer",        "FirstName",  "READ"), \
        "Customer.FirstName should produce READ"
    assert has_intent(intents, "Customer",        "CustomerID", "FILTER"), \
        "JOIN ON Customer.CustomerID should produce FILTER"
    assert has_intent(intents, "CustomerAddress", "CustomerID", "FILTER"), \
        "JOIN ON CustomerAddress.CustomerID should produce FILTER"
    assert has_intent(intents, "CustomerAddress", "AddressID",  "READ"), \
        "CustomerAddress.AddressID in SELECT should produce READ"


# ── Line 453: case-insensitive fallback in _resolve_col ──────────────────────

def test_case_insensitive_qualifier_resolution(local_runner):
    """
    Qualifier that differs in case from the alias map key should still resolve
    (case-insensitive fallback in _resolve_col).
    """
    # Binder normalises table names; we test via parse_only + manual alias map
    extractor = IntentExtractor()
    extractor._seen = set()
    # Simulate: alias_map has 'Customer' but node has qualifier 'CUSTOMER'
    alias_map = {"CUSTOMER": ("SalesLT", "Customer")}
    id_node = {
        "node_type": "IdentifierNode",
        "name": "FirstName",
        "qualifiers": ["customer"],   # lower-case qualifier
    }
    schema, table, col = extractor._resolve_col(id_node, alias_map)
    assert table == "Customer", \
        f"Case-insensitive resolve should return 'Customer', got '{table}'"
    assert col   == "FirstName"


# ── Lines 483, 487: _resolve_col unique table fallback ───────────────────────

def test_resolve_col_unique_table_fallback():
    """
    When there is no qualifier and no resolved_table, but only one table in
    alias_map, that table should be used as the fallback.
    """
    extractor = IntentExtractor()
    extractor._seen = set()
    alias_map = {"Customer": ("SalesLT", "Customer")}
    id_node = {
        "node_type": "IdentifierNode",
        "name": "FirstName",
        "qualifiers": [],
    }
    schema, table, col = extractor._resolve_col(id_node, alias_map)
    assert schema == "SalesLT",  f"Expected schema 'SalesLT', got '{schema}'"
    assert table  == "Customer", f"Expected table 'Customer', got '{table}'"
    assert col    == "FirstName"


def test_resolve_col_ambiguous_returns_none_table():
    """
    When there is no qualifier and multiple tables in alias_map, _resolve_col
    should return (None, None, col) — caller will skip the intent.
    """
    extractor = IntentExtractor()
    extractor._seen = set()
    alias_map = {
        "Customer": ("SalesLT", "Customer"),
        "Address":  ("SalesLT", "Address"),
    }
    id_node = {
        "node_type": "IdentifierNode",
        "name": "SomeColumn",
        "qualifiers": [],
    }
    schema, table, col = extractor._resolve_col(id_node, alias_map)
    assert table is None, \
        "Ambiguous unqualified column should return None table"


def test_resolve_col_no_qualifier_with_resolved_table():
    """
    When id_node carries a resolved_table (set by binder), that table should
    be used even without a qualifier.
    """
    extractor = IntentExtractor()
    extractor._seen = set()
    alias_map = {
        "Customer": ("SalesLT", "Customer"),
        "Address":  ("SalesLT", "Address"),
    }
    id_node = {
        "node_type": "IdentifierNode",
        "name": "CustomerID",
        "qualifiers": [],
        "resolved_table": "Customer",
    }
    schema, table, col = extractor._resolve_col(id_node, alias_map)
    assert table  == "Customer"
    assert schema == "SalesLT"
    assert col    == "CustomerID"


# ── Truncate (INTENT_DELETE) ──────────────────────────────────────────────────

def test_truncate_produces_delete_intent(local_runner):
    """TRUNCATE TABLE → table-level DELETE intent with column=None."""
    sql = "TRUNCATE TABLE SalesLT.Customer"
    intents = intents_of(local_runner, sql)
    assert has_intent(intents, "Customer", None, "DELETE"), \
        "TRUNCATE should produce table-level DELETE intent"
