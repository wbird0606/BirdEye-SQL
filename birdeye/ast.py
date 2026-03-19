"""
BirdEye-SQL AST Nodes Definition
為 ZTA 零信任架構量身打造的抽象語法樹節點。
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
        self.columns = []          # 投影欄位列表
        self.is_select_star = False # 是否為 SELECT *
        self.star_prefixes = []    # 限定星號列表 (如 Users.*)
        self.table = None          # 主表
        self.table_alias = None    # 主表別名 (Binder 核心)
        self.joins = []            # JoinNode 列表
        self.where_condition = None # 過濾條件

class UpdateStatement(Statement):
    def __init__(self):
        self.table = None
        self.table_alias = None    # 💡 修復：解決 Binder 存取 AttributeError
        self.set_clauses = []      # AssignmentNode 列表
        self.where_condition = None # 🛡️ ZTA 強制性條件

class DeleteStatement(Statement):
    def __init__(self):
        self.table = None
        self.table_alias = None    # 💡 修復：解決 Binder 存取 AttributeError
        self.where_condition = None # 🛡️ ZTA 強制性條件

class InsertStatement(Statement):
    def __init__(self):
        self.table = None
        self.table_alias = None    # 💡 修復：解決 Binder 存取 AttributeError
        self.columns = []          # 指定寫入的欄位列表
        self.values = []           # 表達式列表 (VALUES 部分)

class SqlBulkCopyStatement(Statement):
    def __init__(self):
        self.table = None          # 針對高效能批次寫入的映射節點
        self.table_alias = None    # 💡 修復：確保 DML 屬性一致性

# --- 2. 結構化輔助節點 ---

class JoinNode(Node):
    def __init__(self, type, table):
        self.type = type
        self.table = table
        self.alias = None
        self.on_condition = None 
        # 💡 下向相容：讓測試案例能找到屬性
        self.on_left = None 
        self.on_right = None

class AssignmentNode(Node):
    """用於 UPDATE SET 語句的賦值節點"""
    def __init__(self, column, expression):
        self.column = column
        # 💡 修復：更名為 .right 以對齊 Expression Suite 的測試需求
        self.right = expression 

# --- 3. 表達式節點 ---

class IdentifierNode(Node):
    def __init__(self, name, token=None, qualifiers=None, alias=None):
        self.name = name
        self.token = token
        self.qualifiers = qualifiers or [] # 支援多層級路徑 (如 dbo.Users)
        self.alias = alias

    @property
    def qualifier(self):
        """為了相容語意分析測試案例的輔助屬性"""
        return ".".join(self.qualifiers) if self.qualifiers else None

class LiteralNode(Node):
    def __init__(self, value, type):
        self.value = value
        self.type = type           # TokenType (STRING_LITERAL, NUMERIC_LITERAL)

class BinaryExpressionNode(Node):
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator   # +, *, =, AND, OR
        self.right = right

class FunctionCallNode(Node):
    def __init__(self, name, args=None, alias=None):
        self.name = name
        self.args = args or []     # 支援多參數函數
        self.alias = alias