import json
import os
import time

TOKENS_FILE = "tokens.json"


def _load() -> dict:
    if not os.path.exists(TOKENS_FILE):
        return {}
    with open(TOKENS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_user(user_id: int, token_data: dict, username: str = "") -> None:
    data = _load()
    data[str(user_id)] = {
        "access_token":  token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "expires_at":    time.time() + token_data.get("expires_in", 604800),
        "username":      username,
        "saved_at":      time.time(),
    }
    _save(data)


def get_user(user_id: int) -> dict | None:
    return _load().get(str(user_id))


def remove_user(user_id: int) -> bool:
    data = _load()
    if str(user_id) in data:
        del data[str(user_id)]
        _save(data)
        return True
    return False


def all_users() -> dict:
    return _load()


def get_valid() -> dict:
    ahora = time.time()
    return {k: v for k, v in _load().items() if v["expires_at"] > ahora}


def get_expired() -> dict:
    ahora = time.time()
    return {k: v for k, v in _load().items() if v["expires_at"] <= ahora}


def clean_expired() -> int:
    data  = _load()
    ahora = time.time()
    antes = len(data)
    data  = {k: v for k, v in data.items() if v["expires_at"] > ahora}
    _save(data)
    return antes - len(data)


def count() -> tuple[int, int, int]:
    """Devuelve (total, validos, expirados)."""
    data  = _load()
    ahora = time.time()
    val   = sum(1 for v in data.values() if v["expires_at"] > ahora)
    return len(data), val, len(data) - val
