"""
MSSQL 特定功能測試套件
合併了 DECLARE/GO、臨時表、APPLY 及進階型別的測試。
"""
import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.binder import Binder, SemanticError
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.ast import DeclareStatement, ApplyNode, SelectStatement


def tokenize(sql):
    return Lexer(sql).tokenize()

def parse(sql):
    tokens = Lexer(sql).tokenize()
    return Parser(tokens, sql).parse()


# --- (from test_declare_go_suite.py) ---

# ─────────────────────────────────────────────
# 1. Lexer 測試
# ─────────────────────────────────────────────

def test_lexer_declare_is_keyword():
    """DECLARE 應被識別為 KEYWORD_DECLARE，不是普通 IDENTIFIER"""
    tokens = tokenize("DECLARE @var INT")
    assert tokens[0].type == TokenType.KEYWORD_DECLARE

def test_lexer_at_prefix_is_identifier():
    """@varname 應被識別為 IDENTIFIER，且 value 含 @ 前綴"""
    tokens = tokenize("@myVar")
    assert tokens[0].type == TokenType.IDENTIFIER
    assert tokens[0].value == "@myVar"

def test_lexer_go_is_keyword():
    """GO (單獨出現) 應被識別為 KEYWORD_GO"""
    tokens = tokenize("GO")
    assert tokens[0].type == TokenType.KEYWORD_GO

def test_lexer_go_case_insensitive():
    """go / Go 也應被識別為 KEYWORD_GO"""
    for sql in ("go", "Go", "gO"):
        tokens = tokenize(sql)
        assert tokens[0].type == TokenType.KEYWORD_GO, f"Failed for: {sql!r}"


# ─────────────────────────────────────────────
# 2. Parser 測試
# ─────────────────────────────────────────────

def test_parser_declare_simple():
    """DECLARE @counter INT → DeclareStatement with var_name / var_type"""
    ast = parse("DECLARE @counter INT")
    assert isinstance(ast, DeclareStatement)
    assert ast.var_name == "@counter"
    assert ast.var_type == "INT"

def test_parser_declare_with_size():
    """DECLARE @name NVARCHAR(50) → var_type 為 NVARCHAR，括號內長度被吃掉"""
    ast = parse("DECLARE @name NVARCHAR(50)")
    assert isinstance(ast, DeclareStatement)
    assert ast.var_name == "@name"
    assert ast.var_type == "NVARCHAR"

def test_parser_declare_with_default_value():
    """DECLARE @count INT = 0 → default_value 不為 None"""
    ast = parse("DECLARE @count INT = 0")
    assert isinstance(ast, DeclareStatement)
    assert ast.var_name == "@count"
    assert ast.var_type == "INT"
    assert ast.default_value is not None

def test_parser_declare_with_trailing_semicolon():
    """DECLARE @x INT; 尾端分號不應造成 SyntaxError"""
    ast = parse("DECLARE @x INT;")
    assert isinstance(ast, DeclareStatement)


# ─────────────────────────────────────────────
# 3. Binder / 語意分析測試
# ─────────────────────────────────────────────

def test_binder_declare_registers_variable(global_runner):
    """run_script('DECLARE @id INT') 應成功，不拋出語意錯誤"""
    result = global_runner.run_script("DECLARE @id INT")
    assert result["status"] == "success"

def test_variable_usable_in_where_after_declare(global_runner):
    """
    DECLARE @id INT
    SELECT AddressID FROM Address WHERE AddressID = @id

    @id 已宣告，WHERE 中使用不應拋出 'Column not found'
    """
    script = (
        "DECLARE @id INT\n"
        "SELECT AddressID FROM Address WHERE AddressID = @id"
    )
    result = global_runner.run_script(script)
    assert result["status"] == "success"

def test_undeclared_variable_treated_as_external_param(global_runner):
    """未宣告的 @param 視為外部輸入參數（parameterized query placeholder），不報錯。
    應用程式層以 @CustomerId、@Amount 等方式傳入參數值，無需 DECLARE。"""
    result = global_runner.run("SELECT AddressID FROM Address WHERE AddressID = @undeclared")
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# 4. Runner.run_script() 整合測試
# ─────────────────────────────────────────────

def test_run_script_go_splits_batches(global_runner):
    """GO 應將腳本分成兩個獨立批次"""
    script = (
        "SELECT AddressID FROM Address\n"
        "GO\n"
        "SELECT City FROM Address"
    )
    result = global_runner.run_script(script)
    assert result["status"] == "success"
    assert len(result["batches"]) == 2

def test_run_script_semicolon_splits_statements(global_runner):
    """分號應分隔同一批次內的多個語句"""
    script = "DECLARE @id INT; SELECT AddressID FROM Address WHERE AddressID = @id"
    result = global_runner.run_script(script)
    assert result["status"] == "success"
    assert len(result["batches"][0]) == 2

def test_variable_scope_persists_across_go_batches(global_runner):
    """
    第一批次 DECLARE @id INT
    GO
    第二批次 SELECT ... WHERE AddressID = @id
    變數作用域應跨批次保留
    """
    script = (
        "DECLARE @id INT\n"
        "GO\n"
        "SELECT AddressID FROM Address WHERE AddressID = @id"
    )
    result = global_runner.run_script(script)
    assert result["status"] == "success"


# --- (from test_temp_table_suite.py) ---

def run_bind_with_runner(sql, runner):
    """輔助函式：執行完整流水線並回傳 AST"""
    return runner.run(sql)["ast"]

# --- 1. SELECT INTO 語法解析測試 ---

def test_select_into_temp_table_parsing(global_runner):
    """驗證 SELECT ... INTO #Temp 語法解析"""
    sql = "SELECT AddressID, City INTO #MyTemp FROM Address"
    ast = run_bind_with_runner(sql, global_runner)

    assert ast.into_table is not None
    assert ast.into_table.name == "#MyTemp"
    assert ast.table.name == "Address"

# --- 2. 標識符 # 前綴支援測試 ---

def test_lexer_supports_hash_prefix(global_runner):
    """驗證 Lexer 是否允許標識符以 # 開頭 (臨時表規範)"""
    sql = "SELECT * FROM #TempTable"
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.table.name == "#TempTable"

# --- 3. 語意註冊測試 (進階) ---

def test_temp_table_scope_registration(global_runner):
    """
    驗證 SELECT INTO 之後，臨時表是否被註冊進作用域。
    這模擬了連續語句的行為。
    """
    sql1 = "SELECT AddressID, City INTO #T1 FROM Address"
    global_runner.run(sql1)

    sql2 = "SELECT AddressID FROM #T1"
    result = global_runner.run(sql2)
    assert result["status"] == "success"


# --- (from test_apply_suite.py) ---

# ─────────────────────────────────────────────
# 1. Lexer 測試
# ─────────────────────────────────────────────

def test_lexer_cross_is_keyword():
    """CROSS 應被識別為 KEYWORD_CROSS"""
    tokens = tokenize("CROSS APPLY")
    assert tokens[0].type == TokenType.KEYWORD_CROSS

def test_lexer_apply_is_keyword():
    """APPLY 應被識別為 KEYWORD_APPLY"""
    tokens = tokenize("CROSS APPLY")
    assert tokens[1].type == TokenType.KEYWORD_APPLY

def test_lexer_outer_is_keyword():
    """OUTER 應被識別為 KEYWORD_OUTER"""
    tokens = tokenize("OUTER APPLY")
    assert tokens[0].type == TokenType.KEYWORD_OUTER


# ─────────────────────────────────────────────
# 2. Parser 測試
# ─────────────────────────────────────────────

def test_parser_cross_apply_produces_apply_node():
    """CROSS APPLY 應在 stmt.applies 中產生 ApplyNode(type='CROSS')"""
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    ast = parse(sql)
    assert isinstance(ast, SelectStatement)
    assert len(ast.applies) == 1
    apply = ast.applies[0]
    assert isinstance(apply, ApplyNode)
    assert apply.type == "CROSS"
    assert apply.alias == "sub"

def test_parser_outer_apply_produces_apply_node():
    """OUTER APPLY 應產生 ApplyNode(type='OUTER')"""
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "OUTER APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    ast = parse(sql)
    assert len(ast.applies) == 1
    assert ast.applies[0].type == "OUTER"

def test_parser_apply_subquery_is_select_statement():
    """ApplyNode.subquery 應為 SelectStatement"""
    sql = (
        "SELECT a.AddressID "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    ast = parse(sql)
    assert isinstance(ast.applies[0].subquery, SelectStatement)

def test_parser_apply_can_coexist_with_join():
    """JOIN 與 APPLY 可同時出現在同一查詢"""
    sql = (
        "SELECT a.AddressID, b.City, sub.City "
        "FROM Address a "
        "INNER JOIN Address b ON a.AddressID = b.AddressID "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    ast = parse(sql)
    assert len(ast.joins) == 1
    assert len(ast.applies) == 1


# ─────────────────────────────────────────────
# 3. Binder / 語意分析測試
# ─────────────────────────────────────────────

def test_cross_apply_lateral_scope(global_runner):
    """
    CROSS APPLY 子查詢應能參照外側表欄位 (橫向作用域)。
    WHERE AddressID = a.AddressID 中的 a.AddressID 來自外側 FROM Address a。
    """
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"

def test_outer_apply_marks_columns_nullable(global_runner):
    """OUTER APPLY 的結果集欄位應被標記為 nullable (類似 LEFT JOIN)"""
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "OUTER APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"
    binder_nullables = global_runner._binder.nullable_scopes
    assert "SUB" in binder_nullables

def test_apply_result_columns_accessible_in_outer_select(global_runner):
    """
    APPLY 子查詢投影的欄位 (City) 應能在外側 SELECT 中解析，
    且 sub.City 的型別應被正確推導。
    """
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    result = global_runner.run(sql)
    col_names = [c.name.upper() if not hasattr(c, 'alias') or not c.alias
                 else c.alias.upper()
                 for c in result["ast"].columns]
    assert "CITY" in col_names

def test_unknown_column_in_apply_raises_error(global_runner):
    """APPLY 子查詢中使用不存在的欄位應拋出 SemanticError"""
    sql = (
        "SELECT a.AddressID "
        "FROM Address a "
        "CROSS APPLY (SELECT NonExistentCol FROM Address WHERE AddressID = a.AddressID) sub"
    )
    with pytest.raises(SemanticError):
        global_runner.run(sql)


# --- (from test_advanced_types_suite.py) ---

def make_binder(extra_csv=""):
    """建立含進階型別欄位的隔離 Binder"""
    reg = MetadataRegistry()
    csv = (
        "table_name,column_name,data_type\n"
        "T,geo_col,geography\n"
        "T,uid_col,uniqueidentifier\n"
        "T,bin_col,varbinary\n"
        "T,img_col,image\n"
        "T,xml_col,xml\n"
        "T,str_col,nvarchar\n"
        "T,int_col,int\n"
        + extra_csv
    )
    reg.load_from_csv(io.StringIO(csv))
    return Binder(reg)

def bind(sql, binder):
    tokens = Lexer(sql).tokenize()
    ast = Parser(tokens, sql).parse()
    return binder.bind(ast)


# ─────────────────────────────────────────────
# 1. 型別家族相容性
# ─────────────────────────────────────────────

class TestSpatialFamily:
    def test_geography_compatible_with_geography(self):
        """GEOGRAPHY = GEOGRAPHY 應通過型別檢查"""
        b = make_binder()
        bind("SELECT geo_col FROM T WHERE geo_col = geo_col", b)

    def test_geography_incompatible_with_nvarchar(self):
        """GEOGRAPHY ≠ NVARCHAR：修正原本錯誤地將 GEOGRAPHY 放入 STRS 的 bug"""
        b = make_binder()
        with pytest.raises(SemanticError):
            bind("SELECT geo_col FROM T WHERE geo_col = str_col", b)

    def test_geography_incompatible_with_int(self):
        """GEOGRAPHY ≠ INT"""
        b = make_binder()
        with pytest.raises(SemanticError):
            bind("SELECT geo_col FROM T WHERE geo_col = int_col", b)


class TestBinaryFamily:
    def test_varbinary_compatible_with_varbinary(self):
        """VARBINARY = VARBINARY 應通過"""
        b = make_binder()
        bind("SELECT bin_col FROM T WHERE bin_col = bin_col", b)

    def test_image_compatible_with_varbinary(self):
        """IMAGE 與 VARBINARY 同屬 BINARY 家族，應相容"""
        b = make_binder()
        bind("SELECT bin_col FROM T WHERE bin_col = img_col", b)

    def test_varbinary_incompatible_with_nvarchar(self):
        """VARBINARY ≠ NVARCHAR"""
        b = make_binder()
        with pytest.raises(SemanticError):
            bind("SELECT bin_col FROM T WHERE bin_col = str_col", b)


class TestXmlFamily:
    def test_xml_compatible_with_xml(self):
        """XML = XML 應通過"""
        b = make_binder()
        bind("SELECT xml_col FROM T WHERE xml_col = xml_col", b)

    def test_xml_incompatible_with_nvarchar(self):
        """XML ≠ NVARCHAR"""
        b = make_binder()
        with pytest.raises(SemanticError):
            bind("SELECT xml_col FROM T WHERE xml_col = str_col", b)


class TestUniqueIdentifierFamily:
    def test_uniqueidentifier_compatible_with_uniqueidentifier(self):
        """UNIQUEIDENTIFIER = UNIQUEIDENTIFIER 應通過"""
        b = make_binder()
        bind("SELECT uid_col FROM T WHERE uid_col = uid_col", b)

    def test_uniqueidentifier_compatible_with_nvarchar(self):
        """UNIQUEIDENTIFIER 與 NVARCHAR 相容 (GUID 常以字串形式傳入)"""
        b = make_binder()
        bind("SELECT uid_col FROM T WHERE uid_col = str_col", b)

    def test_uniqueidentifier_incompatible_with_int(self):
        """UNIQUEIDENTIFIER ≠ INT"""
        b = make_binder()
        with pytest.raises(SemanticError):
            bind("SELECT uid_col FROM T WHERE uid_col = int_col", b)


# ─────────────────────────────────────────────
# 2. UUID 函數型別推導
# ─────────────────────────────────────────────

def test_newid_returns_uniqueidentifier(global_runner):
    """NEWID() 應回傳 UNIQUEIDENTIFIER 型別"""
    sql = "SELECT NEWID() FROM Address"
    ast = global_runner.run(sql)["ast"]
    assert ast.columns[0].inferred_type == "UNIQUEIDENTIFIER"

def test_newid_comparable_with_uniqueidentifier_column(global_runner):
    """NEWID() 可與 UNIQUEIDENTIFIER 欄位比較，不應拋出型別錯誤"""
    sql = "SELECT rowguid FROM Address WHERE rowguid = NEWID()"
    result = global_runner.run(sql)
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# 3. JSON 函數型別推導
# ─────────────────────────────────────────────

def test_json_value_returns_nvarchar(global_runner):
    """JSON_VALUE(col, path) 應回傳 NVARCHAR"""
    sql = "SELECT JSON_VALUE(Name, '$.key') FROM ProductModel"
    ast = global_runner.run(sql)["ast"]
    assert ast.columns[0].inferred_type == "NVARCHAR"

def test_isjson_returns_bit(global_runner):
    """ISJSON(col) 應回傳 BIT"""
    sql = "SELECT ISJSON(Name) FROM ProductModel"
    ast = global_runner.run(sql)["ast"]
    assert ast.columns[0].inferred_type == "BIT"

def test_json_query_returns_nvarchar(global_runner):
    """JSON_QUERY(col, path) 應回傳 NVARCHAR"""
    sql = "SELECT JSON_QUERY(Name, '$.key') FROM ProductModel"
    ast = global_runner.run(sql)["ast"]
    assert ast.columns[0].inferred_type == "NVARCHAR"

def test_json_modify_returns_nvarchar(global_runner):
    """JSON_MODIFY(col, path, value) 應回傳 NVARCHAR"""
    sql = "SELECT JSON_MODIFY(Name, '$.key', 'val') FROM ProductModel"
    ast = global_runner.run(sql)["ast"]
    assert ast.columns[0].inferred_type == "NVARCHAR"


# ─────────────────────────────────────────────
# 4. 整合查詢 - 真實資料欄位
# ─────────────────────────────────────────────

def test_select_geography_column(global_runner):
    """SELECT ProductModel.CatalogDescription (xml) 不應拋出錯誤"""
    result = global_runner.run("SELECT CatalogDescription FROM ProductModel")
    assert result["status"] == "success"

def test_select_xml_column(global_runner):
    """SELECT ProductModel.CatalogDescription (xml) 不應拋出錯誤"""
    result = global_runner.run("SELECT CatalogDescription FROM ProductModel")
    assert result["status"] == "success"

def test_select_varbinary_column(global_runner):
    """SELECT Product.ThumbNailPhoto (varbinary) 不應拋出錯誤"""
    result = global_runner.run("SELECT ThumbNailPhoto FROM Product")
    assert result["status"] == "success"

def test_geography_where_cross_type_raises(global_runner):
    """SpatialLocation (geography) 與 NVARCHAR 欄位比較應拋出 SemanticError"""
    with pytest.raises(SemanticError):
        global_runner.run(
            "SELECT AddressID FROM Address WHERE SpatialLocation = AddressLine1"
        )
