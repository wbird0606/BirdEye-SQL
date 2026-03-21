# --- 1. 基礎語句節點 (Statements) ---

class SelectStatement:
    def __init__(self):
        self.is_select_star = False
        self.star_prefixes = []
        self.top_count = None
        self.columns = []       # List of ExpressionNodes
        self.table = None       # IdentifierNode
        self.table_alias = None
        self.joins = []         # List of JoinNodes
        self.where_condition = None
        self.group_by_cols = []
        self.having_condition = None
        self.order_by_terms = [] # List of OrderByNodes

class UpdateStatement:
    def __init__(self):
        self.table = None
        self.table_alias = None
        self.set_clauses = []   # List of AssignmentNodes
        self.where_condition = None

class DeleteStatement:
    def __init__(self):
        self.table = None
        self.table_alias = None
        self.where_condition = None

class InsertStatement:
    def __init__(self):
        self.table = None
        self.columns = []       # List of IdentifierNodes
        self.values = []        # List of ExpressionNodes

class SqlBulkCopyStatement:
    """針對 MSSQL 特化的大批次寫入語句"""
    def __init__(self):
        self.table = None

# --- 2. 表達式基類與推導屬性 ---

class ExpressionNode:
    """💡 Issue #35: 所有表達式節點的基類，支援類型推導"""
    def __init__(self):
        self.alias = None
        # 初始類型為 UNKNOWN，由 Binder 在語意分析階段更新
        self.inferred_type = "UNKNOWN"

# --- 3. 具體表達式節點 ---

class IdentifierNode(ExpressionNode):
    def __init__(self, name, qualifiers=None):
        super().__init__()
        self.name = name
        self.qualifiers = qualifiers or []

    @property
    def qualifier(self):
        return ".".join(self.qualifiers) if self.qualifiers else None

class LiteralNode(ExpressionNode):
    def __init__(self, value, type):
        super().__init__()
        self.value = value
        self.type = type  # Lexer 標記的 TokenType (NUMERIC_LITERAL / STRING_LITERAL)
        
        # 💡 基礎類型預映射
        from birdeye.lexer import TokenType
        if type == TokenType.NUMERIC_LITERAL:
            self.inferred_type = "INT"
        elif type == TokenType.STRING_LITERAL:
            self.inferred_type = "NVARCHAR"

class BinaryExpressionNode(ExpressionNode):
    def __init__(self, left, operator, right):
        super().__init__()
        self.left = left
        self.operator = operator
        self.right = right

class FunctionCallNode(ExpressionNode):
    def __init__(self, name, args=None):
        super().__init__()
        self.name = name
        self.args = args or []

class CaseExpressionNode(ExpressionNode):
    def __init__(self, input_expr=None):
        super().__init__()
        self.input_expr = input_expr
        self.branches = []  # List of (when_expr, then_expr)
        self.else_expr = None

class BetweenExpressionNode(ExpressionNode):
    """用於 expr [NOT] BETWEEN low AND high"""
    def __init__(self, expr, low, high, is_not=False):
        super().__init__()
        self.expr = expr
        self.low = low
        self.high = high
        self.is_not = is_not

class CastExpressionNode(ExpressionNode):
    """用於 CAST(expr AS type) 或 CONVERT(type, expr)"""
    def __init__(self, expr, target_type, is_convert=False):
        super().__init__()
        self.expr = expr
        self.target_type = target_type
        self.is_convert = is_convert

# --- 4. 結構輔助節點 ---

class JoinNode:
    def __init__(self, type, table):
        self.type = type        # INNER, LEFT, RIGHT
        self.table = table      # IdentifierNode
        self.alias = None
        self.on_condition = None
        # 用於 Join 最佳化的快取屬性
        self.on_left = None
        self.on_right = None

class OrderByNode:
    def __init__(self, column, direction="ASC"):
        self.column = column    # ExpressionNode
        self.direction = direction

class AssignmentNode:
    """用於 UPDATE SET 語句"""
    def __init__(self, column, expression):
        self.column = column    # IdentifierNode
        self.right = expression # ExpressionNode
