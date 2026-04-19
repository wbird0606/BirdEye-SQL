"""
sqlmap_test_server.py — BirdEye-SQL SQLmap 相容測試伺服器 v4（真實 DB + ZTA Proxy）

架構：三個端點對比測試，連接真實 SQL Server

  /query/unsafe?name=<value>   脆弱 AP（直接字串拼接）
    - BirdEye PASS → 執行真實 SQL → 回傳真實 DB 結果
    - BirdEye BLOCK → HTTP 400

  /query/safe?name=<value>     安全 AP（pyodbc ? 參數化執行）
    - BirdEye 分析（_bind_params 邏輯）PASS → 執行真實 SQL
    - 注入語法成為字串字面值，DB 找不到對應列 → 空回應

  /query/zta?name=<value>      完整 ZTA Proxy（BirdEye + IBAC + db_role）
    - AP 以 ? 參數化 SQL 透過 ZTA SDK 送至 ZTA Proxy
    - ZTA Proxy：BirdEye 語意分析 + Permission API IBAC + db_role 最小權限執行
    - IBAC 拒絕 → HTTP 403；BirdEye 拒絕 → HTTP 400

執行（需先啟動 ZTA Proxy + Keycloak）：
    cd D:/1150322/birdeye
    python sqlmap_test_server.py
    # 啟動時會自動開啟瀏覽器進行 PKCE 登入

SQLmap 測試指令：
    sqlmap -u "http://192.168.150.1:5001/query/unsafe?name=Orlando" ^
      --dbms=mssql --level=5 --risk=3 --batch --technique=BEUSTQ ^
      --output-dir=sqlmap_unsafe

    sqlmap -u "http://192.168.150.1:5001/query/safe?name=Orlando" ^
      --dbms=mssql --level=5 --risk=3 --batch --technique=BEUSTQ ^
      --output-dir=sqlmap_safe

    sqlmap -u "http://192.168.150.1:5001/query/zta?name=Orlando" ^
      --dbms=mssql --level=5 --risk=3 --batch --technique=BEUSTQ ^
      --output-dir=sqlmap_zta
"""

import base64
import hashlib
import http.server
import secrets
import socketserver
import threading
import time
import urllib.parse
import webbrowser
import re
import sys
import os
import logging
import json

sys.path.insert(0, os.path.dirname(__file__))

# ZTA SDK 路徑（append 確保本地 birdeye 套件優先）
_ZTA_PROXY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "zta-proxy-docker"))
if _ZTA_PROXY_DIR not in sys.path:
    sys.path.append(_ZTA_PROXY_DIR)

import pyodbc
import requests as _requests
from flask import Flask, request, jsonify
import zta_sdk

try:
    from birdeye.runner import BirdEyeRunner
    from birdeye.binder import SemanticError
    _BIRDEYE_OK = True
except ImportError:
    _BIRDEYE_OK = False
    BirdEyeRunner = None
    SemanticError = Exception

# ── Logger ────────────────────────────────────────────────────────────────────
_LOG_PATH = os.path.join(os.path.dirname(__file__), "sqlmap_test.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("birdeye")

# ── SQL Server 連線 ───────────────────────────────────────────────────────────
_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=192.168.150.133;"
    "DATABASE=AdventureWorksLT2022;"
    "UID=sa;"
    "PWD=1qaz@WSX3edc;"
    "TrustServerCertificate=yes;"
)

def _exec_sql(sql: str, params: tuple = ()) -> list:
    """對真實 SQL Server 執行查詢，回傳列字典清單。"""
    with pyodbc.connect(_CONN_STR, timeout=5) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

# ── BirdEye Runner ────────────────────────────────────────────────────────────
_runner = None
if _BIRDEYE_OK:
    _runner = BirdEyeRunner()
    _csv_path = os.path.join(os.path.dirname(__file__), "data", "output.csv")
    if os.path.exists(_csv_path):
        with open(_csv_path, encoding="utf-8") as f:
            _runner.load_metadata_from_csv(f)
        print(f"[BirdEye] Schema loaded from {_csv_path}")
    else:
        print(f"[BirdEye] WARNING: {_csv_path} not found, running without schema")
else:
    print("[BirdEye] Not available — /query/unsafe and /query/safe will return 503")

# ── ZTA 設定（從 zta-proxy-docker/test_config.json 讀取）────────────────────
_ZTA_CFG_PATH = os.path.join(_ZTA_PROXY_DIR, "test_config.json")
_ZTA_JWT = None   # 啟動時 PKCE 取得，供 /query/zta 使用
_ZTA_CFG: dict = {}           # 啟動時載入一次，避免每次請求重複讀檔


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in params:
            self.server.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h1>登入成功，可關閉此視窗</h1>".encode("utf-8"))
    def log_message(self, *args): pass


class KeycloakTokenManager:
    """PKCE 流程取 JWT，401 時自動重新登入。Thread-safe。"""

    def __init__(self, cfg: dict):
        self._jwt  = ""
        self._lock = threading.Lock()
        kc    = cfg["keycloak_url"].rstrip("/")
        realm = cfg["realm"]
        self._token_url   = f"{kc}/realms/{realm}/protocol/openid-connect/token"
        self._auth_url    = f"{kc}/realms/{realm}/protocol/openid-connect/auth"
        self._client_id   = cfg["client_id"]
        self._port        = int(cfg.get("callback_port", 9090))
        self._redirect_uri = f"{cfg['redirect_host']}:{self._port}/callback"

    def get(self) -> str:
        with self._lock:
            if not self._jwt:
                self._jwt = self._pkce_login()
            return self._jwt

    def refresh(self) -> str:
        with self._lock:
            print("\n[ZTA] JWT expired, re-logging in via PKCE...")
            self._jwt = self._pkce_login()
            return self._jwt

    def _pkce_login(self) -> str:
        cv = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        cc = base64.urlsafe_b64encode(
            hashlib.sha256(cv.encode()).digest()
        ).decode().rstrip("=")

        socketserver.TCPServer.allow_reuse_address = True
        httpd = None
        for _ in range(10):
            try:
                httpd = socketserver.TCPServer(("", self._port), _OAuthCallbackHandler)
                break
            except OSError:
                time.sleep(1)
        if httpd is None:
            raise OSError(f"[ZTA] Port {self._port} unavailable after retries")

        httpd.auth_code = None
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        auth_url = (
            f"{self._auth_url}?response_type=code"
            f"&client_id={self._client_id}"
            f"&redirect_uri={urllib.parse.quote(self._redirect_uri)}"
            f"&scope=openid+profile"
            f"&code_challenge={cc}&code_challenge_method=S256"
        )
        print(f"[ZTA] Opening browser for Keycloak login...")
        webbrowser.open(auth_url)

        while httpd.auth_code is None:
            time.sleep(0.3)
        code = httpd.auth_code
        httpd.shutdown()

        resp = _requests.post(self._token_url, data={
            "grant_type":    "authorization_code",
            "client_id":     self._client_id,
            "code":          code,
            "redirect_uri":  self._redirect_uri,
            "code_verifier": cv,
        }, timeout=10)
        resp.raise_for_status()
        print("[ZTA] JWT 取得成功")
        return resp.json()["access_token"]


# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)


@app.route("/query/unsafe", methods=["GET"])
def query_unsafe():
    """
    脆弱 AP：直接字串拼接。
    BirdEye PASS → 執行真實 SQL（OR 1=1 回傳全部列，AND 假條件回傳空）
    BirdEye BLOCK → HTTP 400
    """
    if not _BIRDEYE_OK:
        return jsonify({"status": "error", "error": "BirdEye not available"}), 503

    name = request.args.get("name", "Orlando")
    sql = (
        f"SELECT TOP 20 CustomerID, FirstName, LastName "
        f"FROM SalesLT.Customer "
        f"WHERE FirstName='{name}'"
    )

    try:
        _runner.run_multi(sql)
    except (SyntaxError, ValueError) as e:
        log.info("[BLOCK 400] [UNSAFE] name=%-50r layer=parser  err=%s", name, e)
        return jsonify({"status": "blocked", "layer": "parser", "error": str(e)}), 400
    except SemanticError as e:
        log.info("[BLOCK 400] [UNSAFE] name=%-50r layer=binder  err=%s", name, e)
        return jsonify({"status": "blocked", "layer": "binder", "error": str(e)}), 400
    except Exception as e:
        log.info("[BLOCK 400] [UNSAFE] name=%-50r layer=unknown err=%s", name, e)
        return jsonify({"status": "blocked", "layer": "unknown", "error": str(e)}), 400

    # BirdEye 通過 → 執行真實 SQL
    try:
        rows = _exec_sql(sql)
        log.info("[PASS  200] [UNSAFE] name=%-50r rows=%d", name, len(rows))
        return jsonify({"status": "ok", "rowcount": len(rows), "rows": rows}), 200
    except Exception as e:
        log.info("[DB ERROR] [UNSAFE] name=%-50r err=%s", name, e)
        return jsonify({"status": "db_error", "error": str(e)}), 500


@app.route("/query/safe", methods=["GET"])
def query_safe():
    """
    安全 AP：模擬 AP 使用 PreparedStatement（pyodbc ? 參數化執行）。

    BirdEye 分析：同 ZTA Proxy _bind_params，將 ? 替換為 T-SQL escaped 字串字面值，
                  供語意分析引擎解析 AST（注入語法被包覆為字串字面值 → 仍可解析）。
    DB 執行：使用 pyodbc ? 參數化 SQL + 原始 name 值，注入語法無法改變 SQL 結構。
    """
    if not _BIRDEYE_OK:
        return jsonify({"status": "error", "error": "BirdEye not available"}), 503

    name = request.args.get("name", "Orlando")

    # BirdEye 分析用 SQL（同 _bind_params：' → ''，嵌入為字串字面值）
    safe_name = name.replace("'", "''")
    analysis_sql = (
        f"SELECT TOP 20 CustomerID, FirstName, LastName "
        f"FROM SalesLT.Customer "
        f"WHERE FirstName='{safe_name}'"
    )

    try:
        _runner.run_multi(analysis_sql)
    except (SyntaxError, ValueError) as e:
        log.info("[BLOCK 400] [SAFE]   name=%-50r layer=parser  err=%s", name, e)
        return jsonify({"status": "blocked", "layer": "parser", "error": str(e)}), 400
    except SemanticError as e:
        log.info("[BLOCK 400] [SAFE]   name=%-50r layer=binder  err=%s", name, e)
        return jsonify({"status": "blocked", "layer": "binder", "error": str(e)}), 400
    except Exception as e:
        log.info("[BLOCK 400] [SAFE]   name=%-50r layer=unknown err=%s", name, e)
        return jsonify({"status": "blocked", "layer": "unknown", "error": str(e)}), 400

    # DB 執行用 SQL：? 參數化，注入語法作為純字串值傳遞，無法改變 SQL 結構
    exec_sql = (
        "SELECT TOP 20 CustomerID, FirstName, LastName "
        "FROM SalesLT.Customer "
        "WHERE FirstName=?"
    )
    try:
        rows = _exec_sql(exec_sql, (name,))
        log.info("[PASS  200] [SAFE]   name=%-50r rows=%d", name, len(rows))
        return jsonify({"status": "ok", "rowcount": len(rows), "rows": rows}), 200
    except Exception as e:
        log.info("[DB ERROR] [SAFE]   name=%-50r err=%s", name, e)
        return jsonify({"status": "db_error", "error": str(e)}), 500


@app.route("/query/zta_unsafe", methods=["GET"])
def query_zta_unsafe():
    """
    未參數化 AP 透過 ZTA Proxy 場景：AP 直接字串拼接後送至 ZTA Proxy（無 ? 參數）。

    ZTA Proxy 流程：
      1. JWT → /auth → ticket
      2. _bind_params：無 ? → analysis_sql = 原始拼接 SQL（含注入語法）
      3. BirdEye 分析拼接 SQL：語法結構完整的 boolean-blind payload 可通過
      4. Permission API IBAC：欄位授權比對
      5. db_role 執行原始拼接 SQL → 注入語法影響 WHERE 條件 → 真假條件回傳不同列數

    預期結果：INJECTABLE（BirdEye + IBAC 不足以單獨防止 boolean-blind 注入）
    """
    if _ZTA_JWT is None:
        return jsonify({"status": "error", "error": "ZTA JWT not initialized"}), 503

    name = request.args.get("name", "Orlando")
    cfg  = _ZTA_CFG

    # AP 直接拼接 SQL，不使用 ? 參數化
    concat_sql = (
        f"SELECT TOP 20 CustomerID, FirstName, LastName "
        f"FROM SalesLT.Customer "
        f"WHERE FirstName='{name}'"
    )

    try:
        conn = zta_sdk.connect(
            f"ZTAProxy={cfg['proxy_url']};"
            f"Token={_ZTA_JWT};"
            f"DbId={cfg['db_id']}"
        )
        cursor = conn.cursor()
        cursor.execute(concat_sql)  # 無 params，拼接 SQL 直送 Proxy
        cols = [d[0] for d in cursor.description] if cursor.description else []
        rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close()
        log.info("[PASS  200] [ZTA_U]  name=%-50r rows=%d", name, len(rows))
        return jsonify({"status": "ok", "rowcount": len(rows), "rows": rows}), 200
    except PermissionError as e:
        log.info("[BLOCK 403] [ZTA_U]  name=%-50r layer=ibac    err=%s", name, e)
        return jsonify({"status": "forbidden", "layer": "ibac", "error": str(e)}), 403
    except RuntimeError as e:
        log.info("[BLOCK 400] [ZTA_U]  name=%-50r layer=birdeye err=%s", name, e)
        return jsonify({"status": "blocked", "layer": "birdeye", "error": str(e)}), 400
    except Exception as e:
        log.info("[ERROR    ] [ZTA_U]  name=%-50r err=%s", name, e)
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/query/zta", methods=["GET"])
def query_zta():
    """
    完整 ZTA Proxy 場景：AP 透過 ZTA SDK 以 ? 參數化 SQL 送至 ZTA Proxy。

    ZTA Proxy 流程：
      1. JWT → /auth → ticket
      2. _bind_params：? 替換為 escaped 字串字面值，供 BirdEye 語意分析
      3. BirdEye 拒絕 → RuntimeError → HTTP 400
      4. Permission API IBAC：欄位授權比對，拒絕 → PermissionError → HTTP 403
      5. db_role 最小權限執行（非 sa）→ 回傳結果
    """
    if _ZTA_JWT is None:
        return jsonify({"status": "error", "error": "ZTA JWT not initialized"}), 503

    name = request.args.get("name", "Orlando")
    cfg  = _ZTA_CFG

    exec_sql = (
        "SELECT TOP 20 CustomerID, FirstName, LastName "
        "FROM SalesLT.Customer "
        "WHERE FirstName=?"
    )

    try:
        conn = zta_sdk.connect(
            f"ZTAProxy={cfg['proxy_url']};"
            f"Token={_ZTA_JWT};"
            f"DbId={cfg['db_id']}"
        )
        cursor = conn.cursor()
        cursor.execute(exec_sql, [name])
        cols = [d[0] for d in cursor.description] if cursor.description else []
        rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close()
        log.info("[PASS  200] [ZTA]    name=%-50r rows=%d", name, len(rows))
        return jsonify({"status": "ok", "rowcount": len(rows), "rows": rows}), 200
    except PermissionError as e:
        log.info("[BLOCK 403] [ZTA]    name=%-50r layer=ibac    err=%s", name, e)
        return jsonify({"status": "forbidden", "layer": "ibac", "error": str(e)}), 403
    except RuntimeError as e:
        log.info("[BLOCK 400] [ZTA]    name=%-50r layer=birdeye err=%s", name, e)
        return jsonify({"status": "blocked", "layer": "birdeye", "error": str(e)}), 400
    except Exception as e:
        log.info("[ERROR    ] [ZTA]    name=%-50r err=%s", name, e)
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    try:
        _exec_sql("SELECT 1 AS ok")
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"
    return jsonify({"status": "ok", "engine": "BirdEye-SQL", "db": db_status}), 200


if __name__ == "__main__":
    print("=" * 60)
    print("BirdEye-SQL SQLmap Test Server v4（真實 DB + ZTA Proxy）")
    print("  DB: 192.168.150.133 / AdventureWorksLT2022")
    print("  /query/unsafe?name=      脆弱 AP（直接拼接，BirdEye 嵌入）")
    print("  /query/safe?name=        安全 AP（? 參數化，BirdEye 嵌入）")
    print("  /query/zta_unsafe?name=  脆弱 AP（直接拼接）透過 ZTA Proxy")
    print("  /query/zta?name=         安全 AP（? 參數化）透過 ZTA Proxy")
    print("=" * 60)

    # ZTA PKCE 登入（若 test_config.json 存在）
    if os.path.exists(_ZTA_CFG_PATH):
        try:
            with open(_ZTA_CFG_PATH, encoding="utf-8") as f:
                _ZTA_CFG.update(json.load(f))
            _ZTA_JWT = KeycloakTokenManager(_ZTA_CFG).get()
            print(f"[ZTA] 登入完成，/query/zta 端點已就緒")
        except Exception as e:
            print(f"[ZTA] 登入失敗，/query/zta 端點不可用：{e}")
    else:
        print(f"[ZTA] {_ZTA_CFG_PATH} 不存在，/query/zta 端點停用")

    app.run(host="0.0.0.0", port=5001, debug=False)
