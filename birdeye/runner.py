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
        binder = Binder(self.registry)
        bound_ast = binder.bind(ast)

        # 4. Generate Outputs
        tree_text = self.visualizer.dump(bound_ast)
        ast_json = self.serializer.to_json(bound_ast)
        mermaid_code = self.exporter.export(json.loads(ast_json))

        return {
            "ast": bound_ast,
            "tree": tree_text,
            "json": ast_json,
            "mermaid": mermaid_code
        }
