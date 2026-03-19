import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

@pytest.fixture
def type_reg():
    reg = MetadataRegistry()
    csv_data = "table_name,column_name,data_type\nUsers,UserID,INT\nUsers,UserName,NVARCHAR\n"
    reg.load_from_csv(io.StringIO(csv_data))
    # 💡 必須註冊參數預期類型為 ["NVARCHAR"] 才能觸發校驗
    reg.register_function("UPPER", "SCALAR", 1, 1, ["NVARCHAR"], "NVARCHAR")
    reg.register_function("LEN", "SCALAR", 1, 1, ["NVARCHAR"], "INT")
    return reg

def run_bind(sql, registry):
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

def test_function_parameter_type_mismatch(type_reg):
    sql = "SELECT UPPER(UserID) FROM Users"
    with pytest.raises(SemanticError, match="Function 'UPPER' expects NVARCHAR, but got INT"):
        run_bind(sql, type_reg)

def test_binary_op_type_mismatch(type_reg):
    sql = "SELECT UserName + 100 FROM Users"
    with pytest.raises(SemanticError, match=r"Operator '\+' cannot be applied to NVARCHAR and INT"):
        run_bind(sql, type_reg)

def test_case_result_consistency(type_reg):
    sql = "SELECT CASE WHEN UserID = 1 THEN 'Admin' ELSE 999 END FROM Users"
    with pytest.raises(SemanticError, match="CASE branches have incompatible types: NVARCHAR and INT"):
        run_bind(sql, type_reg)