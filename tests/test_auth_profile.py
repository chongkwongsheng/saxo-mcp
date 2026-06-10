# tests/test_auth_profile.py
from saxo_mcp import auth


def test_default_token_path_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "TOKEN_DIR", tmp_path)
    monkeypatch.delenv("SAXO_PROFILE", raising=False)
    assert auth._token_file() == tmp_path / "tokens.json"


def test_profile_token_path(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "TOKEN_DIR", tmp_path)
    monkeypatch.setenv("SAXO_PROFILE", "aimbot")
    assert auth._token_file() == tmp_path / "tokens-aimbot.json"


def test_profiles_are_isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "TOKEN_DIR", tmp_path)
    monkeypatch.setenv("SAXO_PROFILE", "aimbot")
    auth._save_tokens({"access_token": "B", "expires_in": 1200})
    monkeypatch.delenv("SAXO_PROFILE")
    auth._save_tokens({"access_token": "A", "expires_in": 1200})
    monkeypatch.setenv("SAXO_PROFILE", "aimbot")
    assert auth._load_tokens()["access_token"] == "B"
    monkeypatch.delenv("SAXO_PROFILE")
    assert auth._load_tokens()["access_token"] == "A"
