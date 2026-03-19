from birdeye.parser import (
    SelectStatement, IdentifierNode, LiteralNode, 
    BinaryExpressionNode, FunctionCallNode, JoinNode
)

class ASTVisualizer:
    """將 AST 轉換為易讀的樹狀文字結構"""

    def __init__(self):
        self.lines = []

    def dump(self, node) -> str:
        """主入口：傳入 AST 根節點，回傳格式化字串"""
        self.lines = []
        self._visit(node, 0, "ROOT")
        return "\n".join(self.lines)

    def _visit(self, node, indent: int, label: str):
        prefix = "  " * indent + "└── " if indent > 0 else ""
        current_indent = "  " * indent

        if isinstance(node, SelectStatement):
            self.lines.append(f"{prefix}SELECT_STATEMENT")
            # 支援顯示 SELECT *
            if node.is_select_star and not node.columns:
                self.lines.append(f"{current_indent}  ├── COLUMNS: *")
            else:
                self.lines.append(f"{current_indent}  ├── COLUMNS")
                for col in node.columns:
                    self._visit(col, indent + 2, "COL")
            
            # 2. 處理來源表格 (From)
            self.lines.append(f"{current_indent}  ├── FROM")
            self._visit(node.table, indent + 2, "TABLE")
            if node.table_alias:
                self.lines.append(f"{current_indent}    └── ALIAS: {node.table_alias}")

            # 3. 處理連接 (Joins)
            if node.joins:
                self.lines.append(f"{current_indent}  └── JOINS")
                for j in node.joins:
                    self._visit(j, indent + 2, "JOIN")

        elif isinstance(node, IdentifierNode):
            qual = f" (Qual: {node.qualifier})" if node.qualifiers else ""
            alias = f" AS {node.alias}" if node.alias else ""
            self.lines.append(f"{prefix}IDENTIFIER: {node.name}{qual}{alias}")

        elif isinstance(node, LiteralNode):
            self.lines.append(f"{prefix}LITERAL: {node.value} ({node.type.name})")

        elif isinstance(node, BinaryExpressionNode):
            self.lines.append(f"{prefix}EXPRESSION: {node.operator}")
            self._visit(node.left, indent + 1, "LEFT")
            self._visit(node.right, indent + 1, "RIGHT")

        elif isinstance(node, FunctionCallNode):
            alias = f" AS {node.alias}" if node.alias else ""
            self.lines.append(f"{prefix}FUNCTION: {node.name}{alias}")
            for arg in node.args:
                self._visit(arg, indent + 1, "ARG")

        elif isinstance(node, JoinNode):
            self.lines.append(f"{prefix}{node.type}_JOIN")
            self._visit(node.table, indent + 1, "TABLE")
            if node.alias:
                self.lines.append(f"{current_indent}    └── ALIAS: {node.alias}")
            self.lines.append(f"{current_indent}    └── ON")
            self._visit(node.on_left, indent + 3, "L")
            self._visit(node.on_right, indent + 3, "R")