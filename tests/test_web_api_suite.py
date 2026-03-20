import pytest
import json
# 預期我們會實作一個名為 web.app 的 Flask 應用
try:
    from web.app import app
except ImportError:
    # 為了讓 pytest 能夠收集測試 (Red Phase)，給予一個假的 app
    from flask import Flask
    app = Flask(__name__)

@pytest.fixture
def client():
    """建立 Flask 測試客戶端"""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

# --- 1. TDD Red Phase: Web API 驗證 ---

def test_api_parse_success(client):
    """驗證 /api/parse 端點能否成功解析合法的 SQL，並回傳 200 與結果"""
    # 這是非常基礎的 SELECT，對應 Address 表
    payload = {"sql": "SELECT AddressID, City FROM Address"}
    response = client.post('/api/parse', 
                           data=json.dumps(payload), 
                           content_type='application/json')
    
    # 目前 web/app.py 尚未實作，這理應會回傳 404 (Not Found)
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data["status"] == "success"
    assert "tree" in data["result"]
    assert "mermaid" in data["result"]
    assert "SELECT_STATEMENT" in data["result"]["tree"]
    assert "graph TD" in data["result"]["mermaid"]

def test_api_parse_semantic_error(client):
    """驗證 /api/parse 端點遇到 ZTA 攔截時，回傳 400 與明確的錯誤訊息"""
    # 嘗試查詢不存在的表
    payload = {"sql": "SELECT * FROM GhostTable"}
    response = client.post('/api/parse', 
                           data=json.dumps(payload), 
                           content_type='application/json')
    
    assert response.status_code == 400
    
    data = json.loads(response.data)
    assert data["status"] == "error"
    assert "Semantic Error" in data["error_type"]
    assert "Table 'GhostTable' not found" in data["message"]

def test_api_parse_syntax_error(client):
    """驗證 /api/parse 端點遇到語法錯誤時的處理"""
    payload = {"sql": "SELECT FROM Users"} # 故意漏掉欄位
    response = client.post('/api/parse', 
                           data=json.dumps(payload), 
                           content_type='application/json')
    
    assert response.status_code == 400
    data = json.loads(response.data)
    assert data["status"] == "error"
    assert "Syntax Error" in data["error_type"]
