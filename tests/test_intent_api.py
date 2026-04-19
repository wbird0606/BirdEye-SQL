import pytest


def test_intent_returns_success(flask_client):
    resp = flask_client.post('/api/intent', json={
        "sql": "SELECT AddressID, City FROM SalesLT.Address WHERE City = 'Seattle'"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert isinstance(data["intents"], list)
    assert len(data["intents"]) > 0


def test_intent_address_table_in_intents(flask_client):
    resp = flask_client.post('/api/intent', json={
        "sql": "SELECT AddressID, City FROM SalesLT.Address WHERE City = 'Seattle'"
    })
    intents = resp.get_json()["intents"]
    assert any(i["table"] == "Address" for i in intents)


def test_intent_missing_sql_returns_400(flask_client):
    resp = flask_client.post('/api/intent', json={})
    assert resp.status_code == 400
