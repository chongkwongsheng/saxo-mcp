# tests/test_auth_save.py
from saxo_mcp import auth


def test_save_tokens_does_not_mutate_argument(monkeypatch, tmp_path):
    # M-4: _save_tokens must persist obtained_at WITHOUT mutating the caller's
    # dict (it shares the same object the caller may keep using).
    monkeypatch.setattr(auth, "TOKEN_DIR", tmp_path)
    monkeypatch.delenv("SAXO_PROFILE", raising=False)
    original = {"access_token": "A", "expires_in": 1200}
    auth._save_tokens(original)
    assert "obtained_at" not in original          # argument untouched
    assert original == {"access_token": "A", "expires_in": 1200}
    # ...but the persisted copy carries obtained_at.
    persisted = auth._load_tokens()
    assert persisted["access_token"] == "A"
    assert "obtained_at" in persisted
