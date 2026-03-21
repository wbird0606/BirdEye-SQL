# --- 1. 基礎語句節點 (Statements) ---

class SelectStatement:
    def __init__(self):
        self.is_select_star = False
        self.is_distinct = False    # Issue #55
        self.star_prefixes = []
        self.top_count = None
        self.top_percent = False    # Issue #59
        self.offset_count = None    # Issue #64
        self.fetch_count = None     # Issue #64
        self.columns = []       # List of ExpressionNodes
        self.table = None       # IdentifierNode
        self.table_alias = None
        self.joins = []         # List of JoinNodes
        self.where_condition = None
        self.group_by_cols = []
        self.having_condition = None
        self.order_by_terms = [] # List of OrderByNodes
        self.ctes = []          # List of CTENodes
        self.into_table = None  # 💡 TDD New: 用於 SELECT ... INTO #Table
        self.applies = []       # List of ApplyNodes (Issue #53)

class CTENode:
    """用於 WITH Name AS (query)"""
    def __init__(self, name, query):
        self.name = name
        self.query = query      # SelectStatement or UnionStatement

class UpdateStatement:
    def __init__(self):
        self.table = None
        self.table_alias = None
        self.set_clauses = []   # List of AssignmentNodes
        self.ctes = []          # CTE support (Issue #5)
        self.where_condition = None

class DeleteStatement:
    def __init__(self):
        self.table = None
        self.table_alias = None
        self.where_condition = None
        self.ctes = []          # CTE support (Issue #5)

class InsertStatement:
    def __init__(self):
        self.table = None
        self.columns = []       # List of IdentifierNodes
        self.values = []        # List of ExpressionNodes (single-row, backward compat)
        self.value_rows = []    # Issue #58: List of List[ExpressionNode] (multi-row)
        self.source = None      # Issue #57: SelectStatement (INSERT-SELECT)

class TruncateStatement:
    """用於 TRUNCATE TABLE 語句"""
    def __init__(self, table):
        self.table = table      # IdentifierNode

class DeclareStatement:
    """用於 DECLARE @var TYPE [= default_value] 語句 (Issue #51)"""
    def __init__(self, var_name, var_type, default_value=None):
        self.var_name = var_name          # str, e.g. "@counter"
        self.var_type = var_type          # str, e.g. "INT"
        self.default_value = default_value  # ExpressionNode or None

class SqlBulkCopyStatement:
    """針對 MSSQL 特化的大批次寫入語句"""
    def __init__(self):
        self.table = None

class UnionStatement:
    """用於 SELECT ... UNION [ALL] SELECT ..."""
    def __init__(self, left, operator, right):
        self.left = left      # SelectStatement or UnionStatement
        self.operator = operator # UNION, UNION ALL
        self.right = right    # SelectStatement or UnionStatement
        self.columns = []     # 由 Binder 合併後的虛擬投影欄位


# --- 2. 表達式基類與推導屬性 ---

class ExpressionNode:
    """所有表達式節點的基類，支援類型推導"""
    def __init__(self):
        self.alias = None
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
        self.type = type
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
        self.branches = []
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
        self.type = type
        self.table = table
        self.alias = None
        self.on_condition = None
        self.on_left = None
        self.on_right = None

class ApplyNode:
    """用於 CROSS APPLY / OUTER APPLY 關聯子查詢 (Issue #53)"""
    def __init__(self, type, subquery, alias=None):
        self.type = type        # "CROSS" or "OUTER"
        self.subquery = subquery  # SelectStatement or UnionStatement
        self.alias = alias      # str or None
        self.columns = []       # 由 Binder 填入的投影欄位

class OrderByNode:
    def __init__(self, column, direction="ASC"):
        self.column = column
        self.direction = direction

class AssignmentNode:
    def __init__(self, column, expression):
        self.column = column
        self.right = expression
