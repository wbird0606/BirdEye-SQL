from birdeye.parser import (
    IdentifierNode, BinaryExpressionNode, FunctionCallNode, LiteralNode,
    SelectStatement, UpdateStatement, DeleteStatement
)

class SemanticError(Exception): pass

class Binder:
    FUNCTION_WHITELIST = {"COUNT", "SUM", "UPPER", "LOWER", "GETDATE", "AVG"}

    def __init__(self, registry):
        self.registry = registry; self.active_scopes = {}
        self._forbidden_originals = {}; self.nullable_scopes = set()

    def bind(self, stmt):
        """ZTA 語意路由機制"""
        self.active_scopes = {}; self._forbidden_originals = {}; self.nullable_scopes = set()
        if isinstance(stmt, SelectStatement): self._bind_select(stmt)
        elif isinstance(stmt, UpdateStatement): self._bind_update(stmt)
        elif isinstance(stmt, DeleteStatement): self._bind_delete(stmt)
        return stmt

    def _bind_select(self, stmt):
        self._register_scope(stmt.table, stmt.table_alias)
        for j in stmt.joins:
            current_join_key = (j.alias.upper() if j.alias else j.table.name.upper())
            if j.type == "LEFT": self.nullable_scopes.add(current_join_key)
            elif j.type == "RIGHT": self.nullable_scopes.update(self.active_scopes.keys())
            self._register_scope(j.table, j.alias)
            self._validate_node(j.on_left); self._validate_node(j.on_right)
        self._handle_star_expansion(stmt)
        for col in stmt.columns: self._validate_node(col)
        if stmt.where_condition: self._validate_node(stmt.where_condition)

    def _bind_update(self, stmt):
        """實作 UPDATE 欄位與 WHERE 子句校驗"""
        self._register_scope(stmt.table, stmt.table_alias)
        for clause in stmt.set_clauses: self._validate_node(clause)
        self._validate_node(stmt.where_condition)

    def _bind_delete(self, stmt):
        """實作 DELETE 作用域校驗"""
        self._register_scope(stmt.table, stmt.table_alias)
        self._validate_node(stmt.where_condition)

    def _register_scope(self, table_node, alias):
        real_t = table_node.name.upper()
        if not self.registry.has_table(real_t): raise SemanticError(f"Table '{table_node.name}' not found")
        full_path = (table_node.qualifier.upper() + "." if table_node.qualifiers else "") + real_t
        if alias:
            alias_upper = alias.upper(); self.active_scopes[alias_upper] = real_t
            self._forbidden_originals[real_t] = alias; self._forbidden_originals[full_path] = alias
        else:
            self.active_scopes[real_t] = real_t
            if full_path != real_t: self.active_scopes[full_path] = real_t

    def _validate_node(self, node):
        if isinstance(node, IdentifierNode): self._validate_identifier(node)
        elif isinstance(node, BinaryExpressionNode):
            self._validate_node(node.left); self._validate_node(node.right)
        elif isinstance(node, FunctionCallNode):
            if node.name.upper() not in self.FUNCTION_WHITELIST: raise SemanticError(f"Unauthorized function call: {node.name}")
            for arg in node.args: self._validate_node(arg)
        elif isinstance(node, LiteralNode): pass

    def _validate_identifier(self, col):
        if col.name == "*": return 
        if col.qualifiers:
            q_upper = col.qualifier.upper()
            if q_upper in self._forbidden_originals:
                alias = self._forbidden_originals[q_upper]
                raise SemanticError(f"Original table name '{col.qualifier}' cannot be used when alias '{alias}' is defined")
            target_table = self.active_scopes.get(q_upper)
            if not target_table:
                for k, v in self.active_scopes.items():
                    if q_upper.endswith(k): target_table = v; break
            if not target_table: raise SemanticError(f"Unknown qualifier '{col.qualifier}'")
            if not self.registry.has_column(target_table, col.name):
                raise SemanticError(f"Column '{col.name}' not found in '{target_table.capitalize()}'")
        else:
            found = [t for t in self.active_scopes.values() if self.registry.has_column(t, col.name)]
            if len(found) > 1: raise SemanticError(f"Column '{col.name}' is ambiguous. Found in: {', '.join(found)}")
            if not found:
                unique = set(self.active_scopes.values())
                if len(unique) == 1: raise SemanticError(f"Column '{col.name}' not found in '{list(unique)[0].capitalize()}'")
                raise SemanticError(f"Column '{col.name}' not found in any active table scope")

    def _handle_star_expansion(self, stmt):
        if stmt.is_select_star:
            main_t = list(self.active_scopes.values())[0]
            for c in self.registry.get_columns_for_table(main_t): stmt.columns.append(IdentifierNode(name=c, token=None))
        for prefix in stmt.star_prefixes:
            pre_upper = prefix.upper()
            if pre_upper in self._forbidden_originals:
                alias = self._forbidden_originals[pre_upper]
                raise SemanticError(f"Original table name '{prefix}' cannot be used for star expansion when alias '{alias}' is defined")
            target = self.active_scopes.get(pre_upper)
            if not target: raise SemanticError(f"Unknown table prefix '{prefix}'")
            for c in self.registry.get_columns_for_table(target):
                stmt.columns.append(IdentifierNode(name=c, token=None, qualifiers=[prefix]))