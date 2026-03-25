import re
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder
from birdeye.visualizer import ASTVisualizer
from birdeye.serializer import ASTSerializer
from birdeye.mermaid_exporter import MermaidExporter
from birdeye.registry import MetadataRegistry
import io
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

    def run(self, sql):
        """
        執行完整 Pipeline 並回傳結果物件。
        包含原始 AST, 樹狀圖與 Mermaid 代碼。
        """
        # 1. Lexical Analysis
        lexer = Lexer(sql)
        tokens = lexer.tokenize()

        # 2. Syntactic Analysis
        parser = Parser(tokens, sql)
        ast = parser.parse()

        # 3. Semantic Analysis (ZTA Enforcement & Type Inference)
        bound_ast = self._binder.bind(ast)

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

    def parse_only(self, sql):
        """
        僅執行 Lexer + Parser，跳過 Binder。
        適合 intent extraction：不需要 schema 驗證，任何欄位名稱都接受。
        回傳 {"ast": <parsed AST>}
        """
        lexer = Lexer(sql)
        tokens = lexer.tokenize()
        parser = Parser(tokens, sql)
        ast = parser.parse()
        return {"ast": ast}

    def run_script(self, sql):
        """
        Issue #51: 執行多語句腳本。
        - 以 GO (單獨成行) 分隔批次
        - 批次內以 ; 分隔語句
        - 同一個 Binder 實例貫穿整個腳本，variable_scope 跨批次保留
        """
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
                binder.bind(ast)
                batch_asts.append(ast)
            all_batches.append(batch_asts)

        return {"status": "success", "batches": all_batches}
