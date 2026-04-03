import os
import io
import json
import functools
import sys
from flask import Flask, request, jsonify, render_template


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import requests as http_requests
    _REQUESTS_AVAILABLE = True
    _http_session = http_requests.Session()  # TCP keep-alive 重用
except ImportError:
    _REQUESTS_AVAILABLE = False
    _http_session = None
from flask_cors import CORS
from birdeye.runner import BirdEyeRunner
from birdeye.binder import SemanticError
from birdeye.registry import MetadataRegistry
from birdeye.reconstructor import ASTReconstructor
from birdeye.intent_extractor import IntentExtractor

# ── 模組層級 singleton（無狀態，無需每次重建）──────────────────────────────
_reconstructor   = ASTReconstructor()
_intent_extractor = IntentExtractor()

# 初始化 Flask 應用
app = Flask(__name__)
CORS(app) # 允許跨域請求，方便前端整合


@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# 全域的 Runner，預設載入 data/output.csv
# 💡 改為動態重新初始化以支援上傳
def init_default_runner():
    r = BirdEyeRunner()
    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "output.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            r.load_metadata_from_csv(f)
    return r

global_runner = init_default_runner()

@functools.lru_cache(maxsize=32)
def _get_runner_for_schema(metadata_csv: str) -> BirdEyeRunner:
    """同一份 schema CSV 字串只建一次 runner，後續請求直接重用。"""
    r = BirdEyeRunner()
    r.load_metadata_from_csv(io.StringIO(metadata_csv))
    return r

# DbRolePermissionMapping API 設定（可透過環境變數覆寫）
PERMISSION_API_URL = os.environ.get('PERMISSION_API_URL', '')   # e.g. http://localhost:50010
PERMISSION_API_KEY = os.environ.get('ZTA_API_KEY', '')


def _fetch_schema_for_tables(db_id, tables):
    """
    向 DbRolePermissionMapping 的 GET /api/zta/columns 查詢每個資料表的欄位清單，
    回傳 metadata CSV 字串（table_schema,table_name,column_name,data_type）。
    若 API 未設定或所有查詢均失敗，回傳 None（caller 改用預設 metadata）。
    schema 欄位來自 SQL AST 的 extract_tables()，即使權限系統未儲存 schema
    資訊，BirdEye 仍可建構出 schema-qualified 的 registry key。
    """
    if not _REQUESTS_AVAILABLE or not PERMISSION_API_URL or not tables:
        return None

    headers = {'X-ZTA-ApiKey': PERMISSION_API_KEY} if PERMISSION_API_KEY else {}
    rows = ['table_schema,table_name,column_name,data_type']

    for schema, table in tables:
        try:
            resp = _http_session.get(
                f'{PERMISSION_API_URL}/api/zta/columns',
                params={'dbId': db_id, 'schema': schema or 'dbo', 'table': table},
                headers=headers,
                timeout=5,
            )
            if resp.status_code == 200:
                payload = resp.json()
                if payload.get('success'):
                    effective_schema = schema or 'dbo'
                    for col in (payload.get('data') or []):
                        rows.append(f"{effective_schema},{table},{col['ColumnName']},{col['DataType']}")
        except Exception:
            pass  # 單一資料表查詢失敗不影響其他資料表

    return '\n'.join(rows) if len(rows) > 1 else None

@app.route('/')
def index():
    """渲染 Web UI 首頁"""
    return render_template('index.html')

@app.route('/api/upload_csv', methods=['POST'])
def upload_csv():
    """
    接收前端上傳的 CSV 檔案或內容，並重新初始化全域的 Runner
    """
    global global_runner
    
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400

    if file and file.filename.endswith('.csv'):
        try:
            # 讀取 CSV 內容為字串
            csv_content = file.read().decode('utf-8')
            
            # 建立全新的 Runner
            new_runner = BirdEyeRunner()
            # 載入使用者上傳的 CSV 內容
            new_runner.load_metadata_from_csv(io.StringIO(csv_content))
            
            # 取代全域的 runner
            global_runner = new_runner
            
            return jsonify({
                "status": "success", 
                "message": f"Successfully loaded metadata from {file.filename}."
            }), 200
        except Exception as e:
            return jsonify({"status": "error", "message": f"Failed to parse CSV: {str(e)}"}), 400
    else:
        return jsonify({"status": "error", "message": "File must be a .csv"}), 400

@app.route('/api/parse', methods=['POST'])
def parse_sql():
    """
    接收前端的 SQL 查詢並回傳解析結果
    """
    data = request.get_json()
    if not data or 'sql' not in data:
        return jsonify({"status": "error", "error_type": "Request Error", "message": "Missing 'sql' in payload"}), 400

    sql = data['sql']
    
    try:
        # 使用當前的全域 runner 進行解析
        result = global_runner.run(sql)
        
        return jsonify({
            "status": "success",
            "result": {
                "tree": result["tree"],
                "mermaid": result["mermaid"],
                "json": result["json"]
            }
        }), 200
        
    except (SyntaxError, ValueError) as e:
        return jsonify({
            "status": "error",
            "error_type": "Syntax Error",
            "message": str(e)
        }), 400
        
    except SemanticError as e:
        return jsonify({
            "status": "error",
            "error_type": "Semantic Error",
            "message": str(e)
        }), 400
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error_type": "System Error",
            "message": str(e)
        }), 500

@app.route('/api/reconstruct', methods=['POST'])
def reconstruct_sql():
    """
    接收 AST JSON，回傳重建後的 SQL 字串。
    Payload: { "ast": <dict 或 JSON string> }
    """
    data = request.get_json()
    if not data or 'ast' not in data:
        return jsonify({"status": "error", "error_type": "Request Error", "message": "Missing 'ast' in payload"}), 400

    ast_input = data['ast']
    try:
        # 支援 dict 或 JSON string 兩種格式
        if isinstance(ast_input, str):
            sql = _reconstructor.from_json_str(ast_input)
        else:
            sql = _reconstructor.to_sql(ast_input)
        return jsonify({"status": "success", "sql": sql}), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "error_type": "Reconstruct Error",
            "message": str(e)
        }), 400


@app.route('/api/intent', methods=['POST'])
def extract_intent():
    """
    接收 SQL + db_id，向 DbRolePermissionMapping 取得 schema，
    完整執行 pipeline（含 binder），回傳欄位層級操作意圖清單。

    Payload:
      { "sql": "SELECT ...", "db_id": 1 }

    db_id 為 optional：
      - 有提供 → 向 PERMISSION_API_URL 查詢實際 schema metadata
      - 未提供 → 使用預設 data/output.csv metadata

    Response:
      { "status": "success", "intents": [
          {"schema": "SalesLT", "table": "Customer", "column": "FirstName", "intent": "READ"},
          ...
      ]}
    """
    data = request.get_json()
    if not data or 'sql' not in data:
        return jsonify({"status": "error", "error_type": "Request Error", "message": "Missing 'sql' in payload"}), 400

    sql      = data['sql']
    db_id    = data.get('db_id')
    trace_id = request.headers.get('X-Trace-Id', '')  # Fix 5: 接收 ZTA trace_id

    try:
        # Step 1: parse_only → 拿 table 清單（不跑 binder，避免 chicken-and-egg）
        raw     = global_runner.parse_only(sql)
        raw_ast = json.loads(global_runner.serializer.to_json(raw['ast']))
        tables  = IntentExtractor().extract_tables(raw_ast)

        # Step 2: 向 DbRolePermissionMapping 取得實際 schema
        runner = global_runner
        if db_id is not None:
            metadata_csv = _fetch_schema_for_tables(db_id, tables)
            if metadata_csv:
                runner = _get_runner_for_schema(metadata_csv)

        # Step 3: 完整 pipeline（含 binder 型別推導）
        result   = runner.run(sql)
        ast_dict = json.loads(result['json'])
        intents  = _intent_extractor.extract(ast_dict)
        # #74: 展開 SELECT * / COUNT(*) 的 table-level READ 為逐欄 intent
        intents  = _intent_extractor.expand_star_intents(intents, runner)
        reconstructed = _reconstructor.from_json_str(result['json'])
        return jsonify({
            "status": "success",
            "trace_id": trace_id or None,  # Fix 5: 回傳供 BirdEye 自身 log 使用
            "intents": intents,
            "reconstructed_sql": reconstructed,
        }), 200

    except (SyntaxError, ValueError) as e:
        return jsonify({"status": "error", "error_type": "Syntax Error",   "message": str(e)}), 400
    except SemanticError as e:
        return jsonify({"status": "error", "error_type": "Semantic Error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "error_type": "System Error",   "message": str(e)}), 500


if __name__ == '__main__':
    # 提供預設啟動腳本
    app.run(host='0.0.0.0', port=5000, debug=False)
