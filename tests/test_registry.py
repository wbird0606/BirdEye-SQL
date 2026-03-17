import pytest
import io
# 假設我們的套件名稱叫做 birdeye
from birdeye.registry import MetadataRegistry 

# 模擬的 Schema CSV 內容
MOCK_CSV_DATA = """table_name,column_name,data_type
Users,UserID,INT
Users,UserName,VARCHAR
Orders,OrderID,INT
"""

@pytest.fixture
def registry():
    """初始化並加載模擬資料的 Registry"""
    # 使用 StringIO 模擬檔案讀取，保持測試的輕量與高速
    csv_file = io.StringIO(MOCK_CSV_DATA)
    reg = MetadataRegistry()
    reg.load_from_csv(csv_file)
    return reg

def test_registry_case_insensitive_table_lookup(registry):
    """測試：資料表名稱不分大小寫皆可 $O(1)$ 命中"""
    assert registry.has_table("users") is True
    assert registry.has_table("USERS") is True
    assert registry.has_table("Orders") is True
    assert registry.has_table("InvalidTable") is False

def test_registry_case_insensitive_column_lookup(registry):
    """測試：特定資料表下的欄位名稱不分大小寫皆可命中"""
    assert registry.has_column("users", "userid") is True
    assert registry.has_column("USERS", "USERNAME") is True
    assert registry.has_column("orders", "OrderID") is True

def test_registry_column_lookup_invalid_cases(registry):
    """測試：異常狀況防禦（表不存在或欄位不存在）"""
    assert registry.has_column("users", "password") is False
    assert registry.has_column("InvalidTable", "userid") is False

def test_registry_get_column_type(registry):
    """測試：能夠正確回傳型態（這對後續 Binder 處理型態轉換與語意檢查很重要）"""
    assert registry.get_column_type("users", "userid") == "INT"
    assert registry.get_column_type("USERS", "USERNAME") == "VARCHAR"