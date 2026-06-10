# tests/test_fake_client.py
import pytest


def test_fake_client_pops_in_order_and_records_calls(fake_client):
    fake_client.queue("GET", "/x", {"a": 1}, {"a": 2})
    assert fake_client.get("/x") == {"a": 1}
    assert fake_client.get("/x") == {"a": 2}
    assert fake_client.calls == [("GET", "/x", None), ("GET", "/x", None)]


def test_fake_client_raises_on_error_status_like_saxoclient(fake_client):
    fake_client.queue("POST", "/y", (400, {"Message": "bad"}))
    with pytest.raises(RuntimeError):
        fake_client.post("/y", json={})


def test_request_raw_returns_status_without_raising(fake_client):
    fake_client.queue("POST", "/z", (409, {"Message": "dup"}))
    status, body = fake_client.request_raw("POST", "/z", json={})
    assert status == 409 and body["Message"] == "dup"
