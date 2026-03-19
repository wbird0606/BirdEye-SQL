"""
BirdEye-SQL AST Nodes Definition
為 ZTA 零信任架構量身打造的抽象語法樹節點。
v1.6.7: 新增 CaseExpressionNode 以支援 CASE WHEN 邏輯分支。
"""

class Node:
    """所有 AST 節點的基類"""
    pass

class Statement(Node):
    """所有 SQL 語句的基類"""
    pass

# --- 1. DQL / DML 語句節點 ---

class SelectStatement(Statement):
    def __init__(self):
        self.columns = []          # 投影欄位列表 (包含 Identifier, Function, CaseNode)
        self.is_select_star = False # 是否為 SELECT *
        self.star_prefixes = []    # 限定星號列表 (如 Users.*)
        self.table = None          # 主表
        self.table_alias = None    # 主表別名 (Binder 核心)
        self.joins = []            # JoinNode 列表
        self.where_condition = None # 過濾條件
        self.top_count = None      # 💡 Issue #30: TOP N 的數量
        self.order_by_terms = []   # 💡 Issue #30: OrderByNode 列表
        self.group_by_cols = []    # 💡 Issue #31: 分組欄位
        self.having_condition = None # 💡 Issue #31: HAVING 條件

class UpdateStatement(Statement):
    def __init__(self):
        self.table = None
        self.table_alias = None    
        self.set_clauses = []      # AssignmentNode 列表
        self.where_condition = None # 🛡️ ZTA 強制性條件

class DeleteStatement(Statement):
    def __init__(self):
        self.table = None
        self.table_alias = None    
        self.where_condition = None # 🛡️ ZTA 強制性條件

class InsertStatement(Statement):
    def __init__(self):
        self.table = None
        self.table_alias = None    
        self.columns = []          # 指定寫入的欄位列表
        self.values = []           # 表達式列表 (VALUES 部分)

class SqlBulkCopyStatement(Statement):
    def __init__(self):
        self.table = None          
        self.table_alias = None    

# --- 2. 結構化輔助節點 ---

class JoinNode(Node):
    def __init__(self, type, table):
        self.type = type
        self.table = table
        self.alias = None
        self.on_condition = None 
        self.on_left = None 
        self.on_right = None

class OrderByNode(Node):
    """💡 Issue #30: 排序節點"""
    def __init__(self, column, direction="ASC"):
        self.column = column       # IdentifierNode 或 Expression
        self.direction = direction # ASC 或 DESC

class AssignmentNode(Node):
    """用於 UPDATE SET 語句的賦值節點"""
    def __init__(self, column, expression):
        self.column = column
        self.right = expression 

# --- 3. 表達式節點 ---

class IdentifierNode(Node):
    def __init__(self, name, token=None, qualifiers=None, alias=None):
        self.name = name
        self.token = token
        self.qualifiers = qualifiers or [] 
        self.alias = alias

    @property
    def qualifier(self):
        return ".".join(self.qualifiers) if self.qualifiers else None

class LiteralNode(Node):
    def __init__(self, value, type):
        self.value = value
        self.type = type           

class BinaryExpressionNode(Node):
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator   
        self.right = right

class FunctionCallNode(Node):
    def __init__(self, name, args=None, alias=None):
        self.name = name
        self.args = args or []     
        self.alias = alias

class CaseExpressionNode(Node):
    """
    💡 Issue #33: CASE WHEN 表達式節點。
    支援兩種模式：
    1. 簡單式 (Simple): CASE [input_expr] WHEN [val] THEN [res] ...
    2. 搜尋式 (Searched): CASE WHEN [condition] THEN [res] ...
    """
    def __init__(self, input_expr=None, alias=None):
        self.input_expr = input_expr  # 簡單式 CASE 的輸入表達式
        self.branches = []            # 列表儲存 (when_expr, then_expr) 元組
        self.else_expr = None         # ELSE 分支表達式
        self.alias = alias            # CASE 語句的別名