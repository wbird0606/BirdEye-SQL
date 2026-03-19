import json
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.serializer import ASTSerializer
from birdeye.mermaid_exporter import MermaidExporter

sql = """
SELECT UserName, 
       CASE WHEN Salary > 5000 THEN 'High' ELSE 'Low' END as Level
FROM Employees 
WHERE DeptID = 1
"""

# 1. 解析與序列化
lexer = Lexer(sql)
parser = Parser(lexer.tokenize(), sql)
ast = parser.parse()
serializer = ASTSerializer()
ast_dict = json.loads(serializer.to_json(ast))

# 2. 轉換為 Mermaid
exporter = MermaidExporter()
mermaid_code = exporter.export(ast_dict)

print("--- Mermaid Code Start ---")
print(mermaid_code)
print("--- Mermaid Code End ---")