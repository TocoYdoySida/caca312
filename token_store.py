"""
token_store.py — Almacenamiento de tokens OAuth2
Guarda los datos en tokens.json.
"""
import json
import time
from pathlib import Path
from threading import Lock

_PATH = Path(__file__).parent / "tokens.json"
_lock = Lock()


def _load() -> dict:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    with _lock:
        _PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_user(user_id: int, token_data: dict, username: str = "") -> None:
    """Guarda o actualiza el token de un usuario."""
    data = _load()
    data[str(user_id)] = {
        "access_token":  token_data["access_token"],
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_at":    time.time() + token_data.get("expires_in", 604800),
        "username":      username,
        "saved_at":      time.time(),
    }
    _save(data)


def get_user(user_id: int) -> dict | None:
    """Devuelve el registro del usuario o None si no existe."""
    return _load().get(str(user_id))


def remove_user(user_id: int) -> bool:
    """Elimina el token del usuario. Devuelve True si existía."""
    data = _load()
    if str(user_id) not in data:
        return False
    del data[str(user_id)]
    _save(data)
    return True


def all_users() -> dict:
    """Devuelve todos los registros."""
    return _load()


def get_valid() -> dict:
    """Devuelve solo los tokens que no han expirado."""
    ahora = time.time()
    return {k: v for k, v in _load().items() if v["expires_at"] > ahora}


def get_expired() -> dict:
    """Devuelve solo los tokens expirados."""
    ahora = time.time()
    return {k: v for k, v in _load().items() if v["expires_at"] <= ahora}


def clean_expired() -> int:
    """Elimina tokens expirados. Devuelve cuántos se eliminaron."""
    data  = _load()
    ahora = time.time()
    antes = len(data)
    data  = {k: v for k, v in data.items() if v["expires_at"] > ahora}
    _save(data)
    return antes - len(data)


def count() -> tuple[int, int, int]:
    """Devuelve (total, válidos, expirados)."""
    data  = _load()
    ahora = time.time()
    val   = sum(1 for v in data.values() if v["expires_at"] > ahora)
    return len(data), val, len(data) - val
