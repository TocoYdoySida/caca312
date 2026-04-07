import os
import json


def _load() -> dict:
    if os.getenv("DISCORD_TOKEN"):
        return {
            "token":            os.environ["DISCORD_TOKEN"],
            "client_id":        os.environ["CLIENT_ID"],
            "client_secret":    os.environ["CLIENT_SECRET"],
            "redirect_uri":     os.environ["REDIRECT_URI"],
            "verified_role_id": int(os.environ["VERIFIED_ROLE_ID"]),
            "guild_id":         int(os.environ["GUILD_ID"]),
            "log_channel_id":   int(os.environ["LOG_CHANNEL_ID"]) if os.getenv("LOG_CHANNEL_ID") else None,
            "port":             int(os.getenv("PORT", 5000)),
        }
    with open("config.json", encoding="utf-8") as f:
        return json.load(f)


_cfg = _load()

TOKEN            = _cfg["token"]
CLIENT_ID        = _cfg["client_id"]
CLIENT_SECRET    = _cfg["client_secret"]
REDIRECT_URI     = _cfg["redirect_uri"]
VERIFIED_ROLE_ID = _cfg["verified_role_id"]
GUILD_ID         = _cfg["guild_id"]
LOG_CHANNEL_ID   = _cfg.get("log_channel_id")
PORT             = _cfg.get("port", 5000)
