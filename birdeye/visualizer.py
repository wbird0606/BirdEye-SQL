from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement, 
    InsertStatement, SqlBulkCopyStatement,
    IdentifierNode, LiteralNode, BinaryExpressionNode, 
    FunctionCallNode, JoinNode, AssignmentNode,
    OrderByNode, CaseExpressionNode
)

class ASTVisualizer:
    """
    將 AST 轉換為樹狀文字結構，支援 DQL、DML 與條件分支語法。
    v1.6.9: 新增 CASE WHEN 節點視覺化支援。
    """

    def __init__(self):
        self.lines = []

    def dump(self, node) -> str:
        """主入口：傳入 AST 根節點，回傳格式化後的樹狀字串"""
        self.lines = []
        self._visit(node, 0, "ROOT")
        return "\n".join(self.lines)

    def _visit(self, node, indent: int, label: str):
        prefix = "  " * indent + "└── " if indent > 0 else ""
        current_indent = "  " * indent

        # --- 1. 語句類節點 (Statements) ---

        if isinstance(node, SelectStatement):
            self.lines.append(f"{prefix}SELECT_STATEMENT")
            
            if node.top_count is not None:
                self.lines.append(f"{current_indent}  ├── TOP: {node.top_count}")
            
            if node.is_select_star and not node.columns:
                self.lines.append(f"{current_indent}  ├── COLUMNS: *")
            else:
                self.lines.append(f"{current_indent}  ├── COLUMNS")
                for col in node.columns:
                    self._visit(col, indent + 2, "COL")
            
            if node.table:
                self.lines.append(f"{current_indent}  ├── FROM")
                self._visit(node.table, indent + 2, "TABLE")
                if node.table_alias:
                    self.lines.append(f"{current_indent}    └── ALIAS: {node.table_alias}")
            else:
                # 💡 v1.6.9: 支援 SELECT 常數 (無 FROM)
                self.lines.append(f"{current_indent}  ├── FROM: <NONE> (Literal SELECT)")

            if node.joins:
                self.lines.append(f"{current_indent}  ├── JOINS")
                for j in node.joins:
                    self._visit(j, indent + 2, "JOIN")
            
            if node.where_condition:
                self.lines.append(f"{current_indent}  ├── WHERE")
                self._visit(node.where_condition, indent + 2, "COND")
            
            if node.group_by_cols:
                self.lines.append(f"{current_indent}  ├── GROUP BY")
                for g_col in node.group_by_cols:
                    self._visit(g_col, indent + 2, "G_COL")

            if node.having_condition:
                self.lines.append(f"{current_indent}  ├── HAVING")
                self._visit(node.having_condition, indent + 2, "COND")

            if node.order_by_terms:
                self.lines.append(f"{current_indent}  └── ORDER BY")
                for order in node.order_by_terms:
                    self._visit(order, indent + 2, "ORDER")

        elif isinstance(node, UpdateStatement):
            self.lines.append(f"{prefix}UPDATE_STATEMENT")
            self.lines.append(f"{current_indent}  ├── TABLE: {node.table.name}")
            if node.table_alias:
                self.lines.append(f"{current_indent}  ├── ALIAS: {node.table_alias}")
            self.lines.append(f"{current_indent}  ├── SET")
            for clause in node.set_clauses:
                self._visit(clause, indent + 2, "CLAUSE")
            self.lines.append(f"{current_indent}  └── WHERE (MANDATORY)")
            self._visit(node.where_condition, indent + 2, "COND")

        elif isinstance(node, DeleteStatement):
            self.lines.append(f"{prefix}DELETE_STATEMENT")
            self.lines.append(f"{current_indent}  ├── FROM: {node.table.name}")
            if node.table_alias:
                self.lines.append(f"{current_indent}  ├── ALIAS: {node.table_alias}")
            self.lines.append(f"{current_indent}  └── WHERE (MANDATORY)")
            self._visit(node.where_condition, indent + 2, "COND")

        elif isinstance(node, InsertStatement):
            self.lines.append(f"{prefix}INSERT_STATEMENT")
            self.lines.append(f"{current_indent}  ├── INTO: {node.table.name}")
            if node.columns:
                self.lines.append(f"{current_indent}  ├── COLUMNS")
                for col in node.columns:
                    self.lines.append(f"{current_indent}  │   └── {col.name}")
            self.lines.append(f"{current_indent}  └── VALUES")
            for val in node.values:
                self._visit(val, indent + 2, "VAL")

        elif isinstance(node, SqlBulkCopyStatement):
            self.lines.append(f"{prefix}BULK_COPY_STATEMENT")
            self.lines.append(f"{current_indent}  └── TARGET TABLE: {node.table.name}")

        # --- 2. 結構化輔助節點 ---

        elif isinstance(node, JoinNode):
            self.lines.append(f"{prefix}{node.type}_JOIN")
            self._visit(node.table, indent + 1, "TABLE")
            if node.alias:
                self.lines.append(f"{current_indent}    └── ALIAS: {node.alias}")
            self.lines.append(f"{current_indent}    └── ON")
            if node.on_condition:
                self._visit(node.on_condition, indent + 3, "COND")

        elif isinstance(node, OrderByNode):
            self.lines.append(f"{prefix}SORT_BY: {node.direction}")
            self._visit(node.column, indent + 1, "COL")

        elif isinstance(node, AssignmentNode):
            self.lines.append(f"{prefix}EXPRESSION: =")
            self._visit(node.column, indent + 1, "LEFT")
            self._visit(node.right, indent + 1, "RIGHT")

        # --- 3. 基礎與複雜表達式節點 ---

        elif isinstance(node, CaseExpressionNode):
            # 💡 v1.6.9 新增：CASE 視覺化
            self.lines.append(f"{prefix}CASE_EXPRESSION")
            if node.input_expr:
                self._visit(node.input_expr, indent + 2, "INPUT_EXPR")
            
            for i, (when_expr, then_expr) in enumerate(node.branches):
                self.lines.append(f"{current_indent}  ├── BRANCH #{i+1}")
                self._visit(when_expr, indent + 3, "WHEN")
                self._visit(then_expr, indent + 3, "THEN")
            
            if node.else_expr:
                self.lines.append(f"{current_indent}  ├── ELSE")
                self._visit(node.else_expr, indent + 2, "RESULT")
            
            if node.alias:
                self.lines.append(f"{current_indent}  └── ALIAS: {node.alias}")

        elif isinstance(node, IdentifierNode):
            qual = f" (Qual: {node.qualifier})" if node.qualifiers else ""
            alias = f" AS {node.alias}" if node.alias else ""
            self.lines.append(f"{prefix}IDENTIFIER: {node.name}{qual}{alias}")

        elif isinstance(node, LiteralNode):
            type_str = f" ({node.type.name})" if hasattr(node.type, 'name') else ""
            self.lines.append(f"{prefix}LITERAL: {node.value}{type_str}")

        elif isinstance(node, BinaryExpressionNode):
            # 💡 遞迴顯示子查詢
            self.lines.append(f"{prefix}EXPRESSION: {node.operator}")
            self._visit(node.left, indent + 1, "LEFT")
            self._visit(node.right, indent + 1, "RIGHT")

        elif isinstance(node, FunctionCallNode):
            alias = f" AS {node.alias}" if node.alias else ""
            self.lines.append(f"{prefix}FUNCTION: {node.name}{alias}")
            for arg in node.args:
                self._visit(arg, indent + 1, "ARG")