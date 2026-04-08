"""
config.py — Configuración local
Lee config.json de la misma carpeta. Sin variables de entorno.
"""
import json
from pathlib import Path

_cfg = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))

TOKEN            = str(_cfg["token"])
CLIENT_ID        = str(_cfg["client_id"])
CLIENT_SECRET    = str(_cfg["client_secret"])
REDIRECT_URI     = str(_cfg["redirect_uri"])          # http://localhost:5000/callback
GUILD_ID         = int(_cfg["guild_id"])
VERIFIED_ROLE_ID = int(_cfg["verified_role_id"])
LOG_CHANNEL_ID   = _cfg.get("log_channel_id")         # None si no está definido
PORT             = int(_cfg.get("port", 5000))
