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
    # 💡 修正點：使用 .upper() 進行不分大小寫的比較
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
    # 這裡的 op 是關鍵字通常已經是全大寫，或是直接匹配 "="
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
    # 💡 修正點：同樣使用 .upper()
    assert func_node["name"].upper() == "LEN"
    assert isinstance(func_node["args"], list)
    assert func_node["args"][0]["name"].upper() == "USERNAME"