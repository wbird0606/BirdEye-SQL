from birdeye.parser import (
    IdentifierNode, BinaryExpressionNode, FunctionCallNode, LiteralNode,
    SelectStatement, UpdateStatement, DeleteStatement, InsertStatement, SqlBulkCopyStatement
)

class SemanticError(Exception): pass

class Binder:
    # ZTA 函數沙箱白名單：預設拒絕所有未授權調用
    FUNCTION_WHITELIST = {"COUNT", "SUM", "UPPER", "LOWER", "GETDATE", "AVG"}

    def __init__(self, registry):
        self.registry = registry
        self.active_scopes = {}
        self._forbidden_originals = {}
        # Issue #26: 追蹤在 Outer Join 中可能產生 NULL 的表作用域
        self.nullable_scopes = set()

    def bind(self, stmt):
        """執行 ZTA 語意綁定與全語法安全性審查"""
        self.active_scopes = {}
        self._forbidden_originals = {}
        self.nullable_scopes = set()

        # 根據語句類型進行路由校驗
        if isinstance(stmt, SelectStatement):
            self._bind_select(stmt)
        elif isinstance(stmt, UpdateStatement):
            self._bind_update(stmt)
        elif isinstance(stmt, DeleteStatement):
            self._bind_delete(stmt)
        elif isinstance(stmt, InsertStatement):
            self._bind_insert(stmt)
        elif isinstance(stmt, SqlBulkCopyStatement):
            self._bind_bulk_copy(stmt)
            
        return stmt

    # --- 專屬綁定邏輯 ---

    def _bind_select(self, stmt):
        """處理 SELECT 語句：包含多表 Join 與作用域隔離"""
        self._register_scope(stmt.table, stmt.table_alias)
        
        for j in stmt.joins:
            # 處理 Nullability 覺知
            current_join_key = (j.alias.upper() if j.alias else j.table.name.upper())
            if j.type == "LEFT":
                self.nullable_scopes.add(current_join_key)
            elif j.type == "RIGHT":
                self.nullable_scopes.update(self.active_scopes.keys())

            # 增量註冊與即時驗證：防止 Issue #25 的前瞻引用
            self._register_scope(j.table, j.alias)
            self._validate_node(j.on_left)
            self._validate_node(j.on_right)

        self._handle_star_expansion(stmt)
        for col in stmt.columns:
            self._validate_node(col)
            
        if stmt.where_condition:
            self._validate_node(stmt.where_condition)

    def _bind_update(self, stmt):
        """處理 UPDATE：驗證賦值子句與強制 WHERE 條件"""
        self._register_scope(stmt.table, stmt.table_alias)
        for clause in stmt.set_clauses:
            self._validate_node(clause)
        self._validate_node(stmt.where_condition)

    def _bind_delete(self, stmt):
        """處理 DELETE：驗證目標表與強制 WHERE 條件"""
        self._register_scope(stmt.table, stmt.table_alias)
        self._validate_node(stmt.where_condition)

    def _bind_insert(self, stmt):
        """處理 INSERT：實作 ZTA 欄位對齊與元數據校驗"""
        self._register_scope(stmt.table, stmt.table_alias)
        table_name = stmt.table.name.upper()
        
        # 1. 驗證指定的欄位是否存在
        for col in stmt.columns:
            self._validate_identifier(col)
            
        # 2. 欄位數量對齊檢查：防止不對稱寫入
        expected_count = len(stmt.columns) if stmt.columns else len(self.registry.get_columns_for_table(table_name))
        if len(stmt.values) != expected_count:
            raise SemanticError(f"Column count mismatch: Expected {expected_count}, got {len(stmt.values)}")
            
        # 3. 驗證寫入的值
        for val in stmt.values:
            self._validate_node(val)

    def _bind_bulk_copy(self, stmt):
        """處理 SqlBulkCopy 語義映射"""
        self._register_scope(stmt.table, stmt.table_alias)

    # --- 核心工具方法 ---

    def _register_scope(self, table_node, alias):
        """實作別名強制失效原則：定義別名後禁止存取原表名"""
        real_t = table_node.name.upper()
        if not self.registry.has_table(real_t):
            raise SemanticError(f"Table '{table_node.name}' not found")
        
        full_path = (table_node.qualifier.upper() + "." if table_node.qualifiers else "") + real_t
        
        if alias:
            alias_upper = alias.upper()
            self.active_scopes[alias_upper] = real_t
            # 關鍵防禦：標記原名不可使用
            self._forbidden_originals[real_t] = alias
            self._forbidden_originals[full_path] = alias
        else:
            self.active_scopes[real_t] = real_t
            if full_path != real_t:
                self.active_scopes[full_path] = real_t

    def _validate_node(self, node):
        """遞迴審查節點類型與合法性"""
        if isinstance(node, IdentifierNode):
            self._validate_identifier(node)
        elif isinstance(node, BinaryExpressionNode):
            self._validate_node(node.left)
            self._validate_node(node.right)
        elif isinstance(node, FunctionCallNode):
            if node.name.upper() not in self.FUNCTION_WHITELIST:
                raise SemanticError(f"Unauthorized function call: {node.name}")
            for arg in node.args:
                self._validate_node(arg)
        elif isinstance(node, LiteralNode):
            pass

    def _validate_identifier(self, col):
        """欄位級安全防禦：歧義攔截與作用域驗證"""
        if col.name == "*":
            return 

        if col.qualifiers:
            q_upper = col.qualifier.upper()
            # 別名失效檢查
            if q_upper in self._forbidden_originals:
                alias = self._forbidden_originals[q_upper]
                raise SemanticError(f"Original table name '{col.qualifier}' cannot be used when alias '{alias}' is defined")

            # 作用域檢查
            target_table = self.active_scopes.get(q_upper)
            if not target_table:
                # 支援多層級路徑對齊 (如 dbo.Users)
                for k, v in self.active_scopes.items():
                    if q_upper.endswith(k):
                        target_table = v
                        break

            if not target_table:
                raise SemanticError(f"Unknown qualifier '{col.qualifier}'")

            if not self.registry.has_column(target_table, col.name):
                raise SemanticError(f"Column '{col.name}' not found in '{target_table.capitalize()}'")
        else:
            # 歧義攔截：多表環境下強制要求限定符
            found = [t for t in self.active_scopes.values() if self.registry.has_column(t, col.name)]
            if len(found) > 1:
                raise SemanticError(f"Column '{col.name}' is ambiguous. Found in: {', '.join(found)}")
            
            if not found:
                unique = set(self.active_scopes.values())
                if len(unique) == 1:
                    raise SemanticError(f"Column '{col.name}' not found in '{list(unique)[0].capitalize()}'")
                raise SemanticError(f"Column '{col.name}' not found in any active table scope")

    def _handle_star_expansion(self, stmt):
        """根據元數據自動展開星號，支援全域星號與限定星號"""
        # 1. 處理全域星號 SELECT *
        if hasattr(stmt, 'is_select_star') and stmt.is_select_star:
            if not stmt.columns and self.active_scopes:
                main_t = list(self.active_scopes.values())[0]
                for c in self.registry.get_columns_for_table(main_t):
                    stmt.columns.append(IdentifierNode(name=c, token=None))
        
        # 2. 處理限定星號 SELECT Table.* (Issue #26 修正)
        if hasattr(stmt, 'star_prefixes'):
            for prefix in stmt.star_prefixes:
                pre_upper = prefix.upper()
                target = self.active_scopes.get(pre_upper)
                if not target:
                    raise SemanticError(f"Unknown table prefix '{prefix}'")
                for c in self.registry.get_columns_for_table(target):
                    stmt.columns.append(IdentifierNode(name=c, token=None, qualifiers=[prefix]))