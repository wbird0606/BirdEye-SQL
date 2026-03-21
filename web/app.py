import os
import io
import json
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from birdeye.runner import BirdEyeRunner
from birdeye.binder import SemanticError
from birdeye.registry import MetadataRegistry
from birdeye.reconstructor import ASTReconstructor

# 初始化 Flask 應用
app = Flask(__name__)
CORS(app) # 允許跨域請求，方便前端整合

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
            sql = ASTReconstructor().from_json_str(ast_input)
        else:
            sql = ASTReconstructor().to_sql(ast_input)
        return jsonify({"status": "success", "sql": sql}), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "error_type": "Reconstruct Error",
            "message": str(e)
        }), 400


if __name__ == '__main__':
    # 提供預設啟動腳本
    app.run(host='0.0.0.0', port=5000, debug=True)
