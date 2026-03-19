from birdeye.parser import IdentifierNode, BinaryExpressionNode, FunctionCallNode, LiteralNode

class SemanticError(Exception): pass

class Binder:
    # ZTA 函數沙箱白名單
    FUNCTION_WHITELIST = {"COUNT", "SUM", "UPPER", "LOWER", "GETDATE", "AVG"}

    def __init__(self, registry):
        self.registry = registry
        self.active_scopes = {}
        self._forbidden_originals = {}
        # Issue #26: 追蹤在 Outer Join 中可能產生 NULL 的表作用域
        self.nullable_scopes = set()

    def bind(self, stmt):
        """執行 ZTA 語意綁定與安全性審查"""
        self.active_scopes = {}
        self._forbidden_originals = {}
        self.nullable_scopes = set()

        # 1. 註冊主表 (依據 ZTA 最小權限原則，先註冊主表)
        self._register_scope(stmt.table, stmt.table_alias)

        # 2. 處理 JOIN 邏輯：落實「增量註冊」與「Nullability 覺知」
        for j in stmt.joins:
            # A. 處理 Outer Join 的語意傳遞 (Issue #26)
            current_join_key = (j.alias.upper() if j.alias else j.table.name.upper())
            
            if j.type == "LEFT":
                # LEFT JOIN: 右側表的所有欄位變為可空 (Nullable)
                self.nullable_scopes.add(current_join_key)
            elif j.type == "RIGHT":
                # RIGHT JOIN: 目前左側所有的表欄位變為可空
                self.nullable_scopes.update(self.active_scopes.keys())

            # B. 註冊新表並立即驗證 ON 條件 (防止 Issue #25 提到的前瞻引用)
            self._register_scope(j.table, j.alias)
            self._validate_node(j.on_left)
            self._validate_node(j.on_right)

        # 3. 處理星號展開 (Issue #24)
        self._handle_star_expansion(stmt)

        # 4. 驗證最終投影欄位 (Projection Columns)
        for col in stmt.columns:
            self._validate_node(col)

        return stmt

    def _register_scope(self, table_node, alias):
        """實作 ZTA 別名強制失效原則"""
        real_t = table_node.name.upper()
        if not self.registry.has_table(real_t):
            raise SemanticError(f"Table '{table_node.name}' not found")
        
        # 處理多層級路徑 (DB.dbo.Table)
        full_path = (table_node.qualifier.upper() + "." if table_node.qualifiers else "") + real_t
        
        if alias:
            alias_upper = alias.upper()
            self.active_scopes[alias_upper] = real_t
            # 關鍵防禦：定義別名後，原名立即加入禁止清單
            self._forbidden_originals[real_t] = alias
            self._forbidden_originals[full_path] = alias
        else:
            self.active_scopes[real_t] = real_t
            if full_path != real_t:
                self.active_scopes[full_path] = real_t

    def _validate_node(self, node):
        """遞迴審查 AST 節點，執行白名單與存在性檢查"""
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
        """執行 ZTA 欄位級防禦：包含歧義攔截與路徑校驗"""
        if col.name == "*":
            return 

        if col.qualifiers:
            q_upper = col.qualifier.upper()
            # 1. 別名強制失效檢查
            if q_upper in self._forbidden_originals:
                alias = self._forbidden_originals[q_upper]
                raise SemanticError(f"Original table name '{col.qualifier}' cannot be used when alias '{alias}' is defined")

            # 2. 作用域可見性檢查
            target_table = self.active_scopes.get(q_upper)
            if not target_table:
                # 支援多層級路徑對齊
                for k, v in self.active_scopes.items():
                    if q_upper.endswith(k):
                        target_table = v
                        break

            if not target_table:
                raise SemanticError(f"Unknown qualifier '{col.qualifier}'")

            # 3. 欄位存在性檢查
            if not self.registry.has_column(target_table, col.name):
                raise SemanticError(f"Column '{col.name}' not found in '{target_table.capitalize()}'")
        else:
            # 4. 歧義攔截 (Ambiguity Defense)
            found = [t for t in self.active_scopes.values() if self.registry.has_column(t, col.name)]
            if len(found) > 1:
                # 這裡會標註出所有包含該欄位的表，利於資安審計
                raise SemanticError(f"Column '{col.name}' is ambiguous. Found in: {', '.join(found)}")
            
            if not found:
                unique = set(self.active_scopes.values())
                if len(unique) == 1:
                    raise SemanticError(f"Column '{col.name}' not found in '{list(unique)[0].capitalize()}'")
                raise SemanticError(f"Column '{col.name}' not found in any active table scope")

    def _handle_star_expansion(self, stmt):
        """根據元數據自動展開星號，防止隱式欄位洩漏"""
        if stmt.is_select_star:
            # 預設展開主表的欄位
            main_t = list(self.active_scopes.values())[0]
            for c in self.registry.get_columns_for_table(main_t):
                stmt.columns.append(IdentifierNode(name=c, token=None))
        
        for prefix in stmt.star_prefixes:
            pre_upper = prefix.upper()
            if pre_upper in self._forbidden_originals:
                alias = self._forbidden_originals[pre_upper]
                raise SemanticError(f"Original table name '{prefix}' cannot be used for star expansion when alias '{alias}' is defined")
            
            target = self.active_scopes.get(pre_upper)
            if not target:
                raise SemanticError(f"Unknown table prefix '{prefix}'")
            
            for c in self.registry.get_columns_for_table(target):
                stmt.columns.append(IdentifierNode(name=c, token=None, qualifiers=[prefix]))