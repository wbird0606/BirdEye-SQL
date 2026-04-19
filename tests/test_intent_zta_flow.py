import socket
import pytest
import requests as _requests


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


ZTA_AVAILABLE = _port_open("127.0.0.1", 80)


def test_intent_extraction_address(flask_client):
    resp = flask_client.post('/api/intent', json={
        "sql": "SELECT AddressID, City FROM SalesLT.Address WHERE City = 'Seattle'"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    intents = data["intents"]
    assert any(i["table"] == "Address" for i in intents)
    assert all(i["intent"] == "READ" for i in intents)


@pytest.mark.skipif(not ZTA_AVAILABLE, reason="ZTA Proxy not reachable at 127.0.0.1:80")
def test_zta_permission_check_allowed(flask_client):
    resp = flask_client.post('/api/intent', json={
        "sql": "SELECT AddressID, City FROM SalesLT.Address WHERE City = 'Seattle'"
    })
    intents = resp.get_json()["intents"]

    perm_resp = _requests.post(
        "http://127.0.0.1:80/api/zta/check",
        json={"role": "sales_user", "DbId": 2, "intents": intents},
        timeout=5,
    )
    assert perm_resp.status_code == 200
    result = perm_resp.json()
    assert result.get("success") is True
