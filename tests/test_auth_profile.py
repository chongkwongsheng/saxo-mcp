# tests/test_auth_profile.py
import pytest

from saxo_mcp import auth


def test_default_token_path_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "TOKEN_DIR", tmp_path)
    monkeypatch.delenv("SAXO_PROFILE", raising=False)
    assert auth._token_file() == tmp_path / "tokens.json"


def test_profile_token_path(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "TOKEN_DIR", tmp_path)
    monkeypatch.setenv("SAXO_PROFILE", "aimbot")
    assert auth._token_file() == tmp_path / "tokens-aimbot.json"


@pytest.mark.parametrize("evil", ["../../tmp/x", "a/b", "..", "a\\b", "x.json"])
def test_profile_rejects_path_traversal(monkeypatch, tmp_path, evil):
    # H-1: a profile that escapes the slug charset must raise, never produce a
    # token path outside TOKEN_DIR.
    monkeypatch.setattr(auth, "TOKEN_DIR", tmp_path)
    monkeypatch.setenv("SAXO_PROFILE", evil)
    with pytest.raises(RuntimeError):
        auth._token_file()


def test_valid_profile_stays_in_token_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "TOKEN_DIR", tmp_path)
    monkeypatch.setenv("SAXO_PROFILE", "aimbot")
    path = auth._token_file()
    assert path == tmp_path / "tokens-aimbot.json"
    assert path.resolve().parent == tmp_path.resolve()


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
