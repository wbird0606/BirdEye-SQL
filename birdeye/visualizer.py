from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement, 
    InsertStatement, SqlBulkCopyStatement,
    IdentifierNode, LiteralNode, BinaryExpressionNode, 
    FunctionCallNode, JoinNode, AssignmentNode
)

class ASTVisualizer:
    """
    將 AST 轉換為樹狀文字結構，支援 DQL 與 DML 語法。
    修復重點：補齊 JOIN 別名顯示，對齊 AssignmentNode 屬性名稱。
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
            
            # 處理投影欄位
            if node.is_select_star and not node.columns:
                self.lines.append(f"{current_indent}  ├── COLUMNS: *")
            else:
                self.lines.append(f"{current_indent}  ├── COLUMNS")
                for col in node.columns:
                    self._visit(col, indent + 2, "COL")
            
            # 處理主表與別名
            self.lines.append(f"{current_indent}  ├── FROM")
            self._visit(node.table, indent + 2, "TABLE")
            if node.table_alias:
                self.lines.append(f"{current_indent}    └── ALIAS: {node.table_alias}")

            # 處理 JOIN 列表
            if node.joins:
                self.lines.append(f"{current_indent}  ├── JOINS")
                for j in node.joins:
                    self._visit(j, indent + 2, "JOIN")
            
            # 處理 WHERE 條件
            if node.where_condition:
                self.lines.append(f"{current_indent}  └── WHERE")
                self._visit(node.where_condition, indent + 2, "COND")

        elif isinstance(node, UpdateStatement):
            self.lines.append(f"{prefix}UPDATE_STATEMENT")
            self.lines.append(f"{current_indent}  ├── TABLE: {node.table.name}")
            if node.table_alias:
                self.lines.append(f"{current_indent}  ├── ALIAS: {node.table_alias}")
            
            self.lines.append(f"{current_indent}  ├── SET")
            for clause in node.set_clauses:
                self._visit(clause, indent + 2, "CLAUSE")
            
            # 🛡️ ZTA 特性：強制性 WHERE 標籤
            self.lines.append(f"{current_indent}  └── WHERE (MANDATORY)")
            self._visit(node.where_condition, indent + 2, "COND")

        elif isinstance(node, DeleteStatement):
            self.lines.append(f"{prefix}DELETE_STATEMENT")
            self.lines.append(f"{current_indent}  ├── FROM: {node.table.name}")
            if node.table_alias:
                self.lines.append(f"{current_indent}  ├── ALIAS: {node.table_alias}")
            
            # 🛡️ ZTA 特性：強制性 WHERE 標籤
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
            
            # ✨ 修復：解決測試中找不到 ALIAS: o 的問題
            if node.alias:
                self.lines.append(f"{current_indent}    └── ALIAS: {node.alias}")
                
            self.lines.append(f"{current_indent}    └── ON")
            # 💡 對齊：使用單一的 on_condition 表達式渲染
            if node.on_condition:
                self._visit(node.on_condition, indent + 3, "COND")

        elif isinstance(node, AssignmentNode):
            # 用於 UPDATE SET 子句
            self.lines.append(f"{prefix}EXPRESSION: =")
            self._visit(node.column, indent + 1, "LEFT")
            # 💡 對齊：使用屬性名稱 .right 解決 AttributeError
            self._visit(node.right, indent + 1, "RIGHT")

        # --- 3. 基礎表達式節點 ---

        elif isinstance(node, IdentifierNode):
            qual = f" (Qual: {node.qualifier})" if node.qualifiers else ""
            alias = f" AS {node.alias}" if node.alias else ""
            self.lines.append(f"{prefix}IDENTIFIER: {node.name}{qual}{alias}")

        elif isinstance(node, LiteralNode):
            # 顯示數值或字串及其類型
            type_str = f" ({node.type.name})" if hasattr(node.type, 'name') else ""
            self.lines.append(f"{prefix}LITERAL: {node.value}{type_str}")

        elif isinstance(node, BinaryExpressionNode):
            self.lines.append(f"{prefix}EXPRESSION: {node.operator}")
            self._visit(node.left, indent + 1, "LEFT")
            self._visit(node.right, indent + 1, "RIGHT")

        elif isinstance(node, FunctionCallNode):
            alias = f" AS {node.alias}" if node.alias else ""
            self.lines.append(f"{prefix}FUNCTION: {node.name}{alias}")
            for arg in node.args:
                self._visit(arg, indent + 1, "ARG")