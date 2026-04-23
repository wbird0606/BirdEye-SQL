import re
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder
from birdeye.visualizer import ASTVisualizer
from birdeye.serializer import ASTSerializer
from birdeye.mermaid_exporter import MermaidExporter
from birdeye.registry import MetadataRegistry
import io
try:
    import ujson as json
except ImportError:
    import json

class BirdEyeRunner:
    """
    BirdEye-SQL 核心整合引擎 (Library API)。
    串接 Lexer -> Parser -> Binder -> (Visualizer/Exporter) 的完整流水線。
    """
    def __init__(self, registry=None):
        self.registry = registry or MetadataRegistry()
        self.visualizer = ASTVisualizer()
        self.serializer = ASTSerializer()
        self.exporter = MermaidExporter()
        # Issue #52: 持久化 Binder，temp_schemas 跨 run() 呼叫保留
        self._binder = Binder(self.registry)

    def load_metadata_from_csv(self, csv_content):
        """從 CSV 字串或檔案載入元數據"""
        if isinstance(csv_content, str):
            f = io.StringIO(csv_content)
        else:
            f = csv_content
        self.registry.load_from_csv(f)

    @staticmethod
    def _rewrite_qmark_sql(sql: str):
        """
        將 SQL 中的 ? 位置參數（排除字串/註解內）改寫為 @P1, @P2 ...。
        回傳 (rewritten_sql, qmark_count)。
        """
        out = []
        i = 0
        p_idx = 0
        n = len(sql)
        in_string = False
        in_line_comment = False
        in_block_comment = False

        while i < n:
            ch = sql[i]
            nx = sql[i + 1] if i + 1 < n else ""

            if in_line_comment:
                out.append(ch)
                if ch == "\n":
                    in_line_comment = False
                i += 1
                continue

            if in_block_comment:
                out.append(ch)
                if ch == "*" and nx == "/":
                    out.append(nx)
                    i += 2
                    in_block_comment = False
                else:
                    i += 1
                continue

            if in_string:
                out.append(ch)
                if ch == "'":
                    # T-SQL 單引號跳脫: ''
                    if nx == "'":
                        out.append(nx)
                        i += 2
                        continue
                    in_string = False
                i += 1
                continue

            if ch == "-" and nx == "-":
                out.append(ch)
                out.append(nx)
                i += 2
                in_line_comment = True
                continue

            if ch == "/" and nx == "*":
                out.append(ch)
                out.append(nx)
                i += 2
                in_block_comment = True
                continue

            if ch == "'":
                out.append(ch)
                i += 1
                in_string = True
                continue

            if ch == "?":
                p_idx += 1
                out.append(f"@P{p_idx}")
                i += 1
                continue

            out.append(ch)
            i += 1

        return "".join(out), p_idx

    def _prepare_sql_and_params(self, sql, params):
        """
        支援雙模式輸入：
        - 命名參數：@name + dict
        - 位置參數：? + list/tuple（轉換為 @P1..@Pn + dict）
        """
        rewritten_sql, qmark_count = self._rewrite_qmark_sql(sql)

        if isinstance(params, (list, tuple)):
            if qmark_count != len(params):
                raise ValueError(
                    f"PARAM_COUNT_MISMATCH: SQL has {qmark_count} '?' placeholders, "
                    f"but params has {len(params)} values"
                )
            mapped = {f"@P{i + 1}": v for i, v in enumerate(params)}
            return rewritten_sql, mapped, "qmark"

        if isinstance(params, dict):
            if qmark_count > 0:
                raise ValueError("PARAM_MODE_MIXED: SQL uses '?' placeholders but params is an object")
            return sql, params, "named"

        if params is None:
            if qmark_count > 0:
                raise ValueError(
                    f"PARAM_MISSING: SQL has {qmark_count} '?' placeholders but no params were provided"
                )
            return sql, params, "none"

        raise ValueError("PARAM_FORMAT_INVALID: params must be object, array, or null")

    def run(self, sql, params=None):
        """
        執行完整 Pipeline 並回傳結果物件。
        包含原始 AST, 樹狀圖與 Mermaid 代碼。
        """
        sql, params, param_input_mode = self._prepare_sql_and_params(sql, params)

        # 1. Lexical Analysis
        lexer = Lexer(sql)
        tokens = lexer.tokenize()

        # 2. Syntactic Analysis
        parser = Parser(tokens, sql)
        ast = parser.parse()

        # 3. Semantic Analysis (ZTA Enforcement & Type Inference)
        bound_ast = self._binder.bind(ast, external_params=params)
        setattr(bound_ast, "param_input_mode", param_input_mode)

        # 4. Generate Outputs
        tree_text = self.visualizer.dump(bound_ast)
        ast_json = self.serializer.to_json(bound_ast)
        mermaid_code = self.exporter.export(json.loads(ast_json))

        return {
            "status": "success",
            "ast": bound_ast,
            "tree": tree_text,
            "json": ast_json,
            "mermaid": mermaid_code
        }

    def run_multi(self, sql, params=None):
        """
        多語句入口：以分號分隔多條 T-SQL 語句，回傳與 run() 相同格式的結果。
        ScriptNode 作為根節點貫穿整個 pipeline，Binder 共享 temp_schemas / variable_scope。
        """
        sql, params, param_input_mode = self._prepare_sql_and_params(sql, params)

        lexer = Lexer(sql)
        tokens = lexer.tokenize()
        parser = Parser(tokens, sql)
        script = parser.parse_script()
        self._binder.bind(script, external_params=params)
        setattr(script, "param_input_mode", param_input_mode)
        tree_text = self.visualizer.dump(script)
        ast_json = self.serializer.to_json(script)
        mermaid_code = self.exporter.export(json.loads(ast_json))
        return {
            "status": "success",
            "ast": script,
            "tree": tree_text,
            "json": ast_json,
            "mermaid": mermaid_code,
        }

    def parse_only(self, sql, params=None):
        """
        僅執行 Lexer + Parser，跳過 Binder。
        適合 intent extraction：不需要 schema 驗證，任何欄位名稱都接受。
        回傳 {"ast": <parsed AST>}
        """
        sql, _, _ = self._prepare_sql_and_params(sql, params)

        lexer = Lexer(sql)
        tokens = lexer.tokenize()
        parser = Parser(tokens, sql)
        ast = parser.parse()
        return {"ast": ast}

    def parse_only_multi(self, sql, params=None):
        """
        多語句版 parse_only：Lexer + parse_script()，跳過 Binder。
        適合多語句 first-pass table discovery。
        回傳 {"ast": <ScriptNode>}
        """
        sql, _, _ = self._prepare_sql_and_params(sql, params)

        lexer = Lexer(sql)
        tokens = lexer.tokenize()
        parser = Parser(tokens, sql)
        script = parser.parse_script()
        return {"ast": script}

    def run_script(self, sql, params=None):
        """
        Issue #51: 執行多語句腳本。
        - 以 GO (單獨成行) 分隔批次
        - 批次內以 ; 分隔語句
        - 同一個 Binder 實例貫穿整個腳本，variable_scope 跨批次保留
        """
        sql, params, _ = self._prepare_sql_and_params(sql, params)

        batches_sql = re.split(r'^\s*GO\s*$', sql, flags=re.IGNORECASE | re.MULTILINE)
        binder = Binder(self.registry)
        all_batches = []

        # 新語句起始關鍵字 pattern，用於按換行分割語句
        _stmt_start = re.compile(
            r'(?=^\s*(?:SELECT|INSERT|UPDATE|DELETE|TRUNCATE|DECLARE|WITH|IF|BEGIN|EXEC|EXECUTE|CREATE|DROP|ALTER|MERGE|PRINT|SET)\b)',
            re.IGNORECASE | re.MULTILINE
        )

        for batch_sql in batches_sql:
            batch_sql = batch_sql.strip()
            if not batch_sql:
                continue
            # 先以分號分割，再對每段以語句起始關鍵字進一步分割
            raw_parts = batch_sql.split(';')
            stmts_sql = []
            for part in raw_parts:
                sub = [s.strip() for s in _stmt_start.split(part) if s.strip()]
                stmts_sql.extend(sub)
            batch_asts = []
            for stmt_sql in stmts_sql:
                lexer = Lexer(stmt_sql)
                tokens = lexer.tokenize()
                parser = Parser(tokens, stmt_sql)
                ast = parser.parse()
                binder.bind(ast, external_params=params)
                batch_asts.append(ast)
            all_batches.append(batch_asts)

        return {"status": "success", "batches": all_batches}
