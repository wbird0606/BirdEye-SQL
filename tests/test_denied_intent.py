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

_DENIED_SQL = "SELECT CustomerID, EmailAddress, Phone FROM SalesLT.Customer WHERE CustomerID = 1"


def test_denied_intent_extraction(flask_client):
    resp = flask_client.post('/api/intent', json={"sql": _DENIED_SQL})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    intents = data["intents"]
    assert any(i["table"] == "Customer" for i in intents)
    columns = {i["column"] for i in intents}
    assert {"EmailAddress", "Phone"} & columns


@pytest.mark.skipif(not ZTA_AVAILABLE, reason="ZTA Proxy not reachable at 127.0.0.1:80")
def test_denied_columns_rejected_by_zta(flask_client):
    resp = flask_client.post('/api/intent', json={"sql": _DENIED_SQL})
    intents = resp.get_json()["intents"]

    perm_resp = _requests.post(
        "http://127.0.0.1:80/api/zta/check",
        json={"role": "sales_user", "DbId": 2, "intents": intents},
        headers={"Content-Type": "application/json"},
        timeout=5,
    )
    assert perm_resp.status_code == 200
    result = perm_resp.json()
    assert result.get("success") is True
    assert result["data"]["Allowed"] is False
    denied_columns = {d["Column"] for d in result["data"]["Denied"]}
    assert {"EmailAddress", "Phone"} & denied_columns
