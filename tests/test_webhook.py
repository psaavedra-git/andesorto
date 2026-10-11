import hashlib
import hmac
import json

from fastapi.testclient import TestClient


def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("WA_VERIFY_TOKEN", "vt")
    monkeypatch.setenv("WA_APP_SECRET", "secret")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "w.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    from app import config

    config.get_settings.cache_clear()
    import importlib

    import app.main as main

    importlib.reload(main)
    handled = []
    monkeypatch.setattr(main.bot, "handle", lambda m: handled.append(m))
    return TestClient(main.app), handled


def test_verify_endpoint(monkeypatch, tmp_path):
    c, _ = make_client(monkeypatch, tmp_path)
    ok = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "123"})
    assert ok.status_code == 200 and ok.text == "123"
    bad = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "123"})
    assert bad.status_code == 403


def test_post_requires_signature_and_dispatches(monkeypatch, tmp_path):
    c, handled = make_client(monkeypatch, tmp_path)
    body = json.dumps(
        {"entry": [{"changes": [{"value": {"messages": [{"id": "z", "from": "519", "type": "text", "text": {"body": "hola"}}]}}]}]}
    ).encode()
    assert c.post("/webhook", content=body).status_code == 401
    sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    r = c.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})
    assert r.status_code == 200
    assert [m.text for m in handled] == ["hola"]
