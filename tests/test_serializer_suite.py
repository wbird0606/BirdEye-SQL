import pytest
import json
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.serializer import ASTSerializer

def get_ast(sql):
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    return parser.parse()

def test_basic_select_serialization():
    """驗證基礎 SELECT 語句的 JSON 結構"""
    sql = "SELECT UserID FROM Users"
    ast = get_ast(sql)
    serializer = ASTSerializer()
    
    data = json.loads(serializer.to_json(ast))
    
    assert data["node_type"] == "SelectStatement"
    assert data["table"]["name"].upper() == "USERS"
    assert len(data["columns"]) == 1
    assert data["columns"][0]["name"].upper() == "USERID"

def test_case_when_serialization():
    """驗證複雜的 CASE WHEN 嵌套序列化"""
    sql = "SELECT CASE WHEN A=1 THEN 'Y' ELSE 'N' END FROM T"
    ast = get_ast(sql)
    serializer = ASTSerializer()
    
    data = json.loads(serializer.to_json(ast))
    case_node = data["columns"][0]
    
    assert case_node["node_type"] == "CaseExpressionNode"
    assert len(case_node["branches"]) == 1
    assert case_node["branches"][0]["when"]["op"] == "="
    assert case_node["else"]["value"] == "N"

def test_null_handling_serialization():
    """驗證當某些子句為空時，JSON 應為 null"""
    sql = "SELECT 1"
    ast = get_ast(sql)
    serializer = ASTSerializer()
    
    data = json.loads(serializer.to_json(ast))
    assert data["where"] is None
    assert data["table"] is None

def test_function_call_serialization():
    """驗證函數呼叫的參數清單序列化"""
    sql = "SELECT LEN(UserName) FROM Users"
    ast = get_ast(sql)
    serializer = ASTSerializer()
    
    data = json.loads(serializer.to_json(ast))
    func_node = data["columns"][0]
    
    assert func_node["node_type"] == "FunctionCallNode"
    assert func_node["name"].upper() == "LEN"
    assert isinstance(func_node["args"], list)
    assert func_node["args"][0]["name"].upper() == "USERNAME"

# --- 💡 TDD New: 進階語法序列化測試 ---

def test_cte_serialization():
    """驗證 CTE (WITH) 的 JSON 結構"""
    sql = "WITH CTE1 AS (SELECT 1 AS A) SELECT A FROM CTE1"
    ast = get_ast(sql)
    serializer = ASTSerializer()
    data = json.loads(serializer.to_json(ast))
    
    assert "ctes" in data
    assert len(data["ctes"]) == 1
    assert data["ctes"][0]["name"] == "CTE1"
    assert data["ctes"][0]["query"]["node_type"] == "SelectStatement"

def test_union_serialization():
    """驗證 UNION 的 JSON 結構"""
    sql = "SELECT 1 UNION SELECT 2"
    ast = get_ast(sql)
    serializer = ASTSerializer()
    data = json.loads(serializer.to_json(ast))
    
    assert data["node_type"] == "UnionStatement"
    assert data["op"] == "UNION"
    assert data["left"]["node_type"] == "SelectStatement"
    assert data["right"]["node_type"] == "SelectStatement"

def test_between_cast_serialization():
    """驗證 BETWEEN 與 CAST 的 JSON 結構"""
    sql = "SELECT CAST(Price AS INT) FROM T WHERE Price BETWEEN 1 AND 10"
    ast = get_ast(sql)
    serializer = ASTSerializer()
    data = json.loads(serializer.to_json(ast))

    # 檢查 CAST
    cast_node = data["columns"][0]
    assert cast_node["node_type"] == "CastExpressionNode"
    assert cast_node["target"] == "INT"

    # 檢查 BETWEEN
    between_node = data["where"]
    assert between_node["node_type"] == "BetweenExpressionNode"
    assert between_node["low"]["value"] == "1"
    assert between_node["high"]["value"] == "10"

# --- Issue #51/#52/#53: 新語句序列化測試 ---

def test_declare_serialization():
    """DECLARE 語句應序列化為含 var_name / var_type / default_value 的 JSON"""
    ast = get_ast("DECLARE @counter INT")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["node_type"] == "DeclareStatement"
    assert data["var_name"] == "@counter"
    assert data["var_type"] == "INT"
    assert data["default_value"] is None

def test_declare_with_default_serialization():
    """DECLARE @x INT = 0 的 default_value 應序列化為 LiteralNode"""
    ast = get_ast("DECLARE @x INT = 0")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["default_value"] is not None
    assert data["default_value"]["node_type"] == "LiteralNode"
    assert data["default_value"]["value"] == "0"

def test_select_into_serialization():
    """SELECT INTO #table 應在 JSON 中包含 into_table 欄位"""
    ast = get_ast("SELECT A INTO #Temp FROM T")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["node_type"] == "SelectStatement"
    assert data["into_table"] is not None
    assert data["into_table"]["name"] == "#Temp"

def test_select_without_into_has_null_into_table():
    """一般 SELECT 的 into_table 應為 null"""
    ast = get_ast("SELECT A FROM T")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["into_table"] is None

def test_apply_node_serialization():
    """CROSS APPLY 應序列化為含 apply_type / subquery / alias 的 JSON"""
    sql = "SELECT A FROM T CROSS APPLY (SELECT B FROM T2) sub"
    ast = get_ast(sql)
    data = json.loads(ASTSerializer().to_json(ast))
    assert "applies" in data
    assert len(data["applies"]) == 1
    apply = data["applies"][0]
    assert apply["node_type"] == "ApplyNode"
    assert apply["apply_type"] == "CROSS"
    assert apply["alias"] == "sub"
    assert apply["subquery"]["node_type"] == "SelectStatement"

def test_outer_apply_node_serialization():
    """OUTER APPLY 的 apply_type 應為 OUTER"""
    sql = "SELECT A FROM T OUTER APPLY (SELECT B FROM T2) sub"
    ast = get_ast(sql)
    data = json.loads(ASTSerializer().to_json(ast))
    apply = data["applies"][0]
    assert apply["apply_type"] == "OUTER"
