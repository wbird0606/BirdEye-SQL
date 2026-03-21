"""
Issue #54: 擴充進階資料型別 (XML, JSON, Spatial, UUID)
TDD 測試套件

測試分層：
  1. 型別家族相容性  - SPATIAL / BINARY / XML 家族邊界
  2. 型別家族修正    - GEOGRAPHY 從 STRS 移除
  3. UUID 函數       - NEWID() 回傳 UNIQUEIDENTIFIER
  4. JSON 函數       - JSON_VALUE / JSON_QUERY / ISJSON / JSON_MODIFY
  5. 整合查詢        - 使用真實資料欄位驗證完整管道
"""
import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.binder import Binder, SemanticError
from birdeye.lexer import Lexer
from birdeye.parser import Parser


# ─────────────────────────────────────────────
# 工具函式
# ─────────────────────────────────────────────

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
        bind("SELECT geo_col FROM T WHERE geo_col = geo_col", b)  # 不應拋出

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
    sql = "SELECT JSON_VALUE(Demographics, '$.CustomerStyle') FROM Person"
    ast = global_runner.run(sql)["ast"]
    assert ast.columns[0].inferred_type == "NVARCHAR"

def test_isjson_returns_bit(global_runner):
    """ISJSON(col) 應回傳 BIT"""
    sql = "SELECT ISJSON(Demographics) FROM Person"
    ast = global_runner.run(sql)["ast"]
    assert ast.columns[0].inferred_type == "BIT"

def test_json_query_returns_nvarchar(global_runner):
    """JSON_QUERY(col, path) 應回傳 NVARCHAR"""
    sql = "SELECT JSON_QUERY(Demographics, '$.key') FROM Person"
    ast = global_runner.run(sql)["ast"]
    assert ast.columns[0].inferred_type == "NVARCHAR"

def test_json_modify_returns_nvarchar(global_runner):
    """JSON_MODIFY(col, path, value) 應回傳 NVARCHAR"""
    sql = "SELECT JSON_MODIFY(Demographics, '$.key', 'val') FROM Person"
    ast = global_runner.run(sql)["ast"]
    assert ast.columns[0].inferred_type == "NVARCHAR"


# ─────────────────────────────────────────────
# 4. 整合查詢 - 真實資料欄位
# ─────────────────────────────────────────────

def test_select_geography_column(global_runner):
    """SELECT Address.SpatialLocation (geography) 不應拋出錯誤"""
    result = global_runner.run("SELECT SpatialLocation FROM Address")
    assert result["status"] == "success"

def test_select_xml_column(global_runner):
    """SELECT DatabaseLog.XmlEvent (xml) 不應拋出錯誤"""
    result = global_runner.run("SELECT XmlEvent FROM DatabaseLog")
    assert result["status"] == "success"

def test_select_varbinary_column(global_runner):
    """SELECT Document.Document (varbinary) 不應拋出錯誤"""
    result = global_runner.run("SELECT Document FROM Document")
    assert result["status"] == "success"

def test_geography_where_cross_type_raises(global_runner):
    """SpatialLocation (geography) 與 NVARCHAR 欄位比較應拋出 SemanticError"""
    with pytest.raises(SemanticError):
        global_runner.run(
            "SELECT AddressID FROM Address WHERE SpatialLocation = AddressLine1"
        )
