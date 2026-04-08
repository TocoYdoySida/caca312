"""
utils.py — Helpers OAuth2 compartidos
Usados por cogs/verificacion.py y cogs/tokens.py
"""
import asyncio
import logging

import aiohttp

import config
import token_store

log = logging.getLogger("bot.utils")


async def refresh_token(user_id: int) -> str | None:
    """Refresca el access token usando el refresh token. Devuelve el nuevo token o None."""
    record = token_store.get_user(user_id)
    if not record or not record.get("refresh_token"):
        return None

    data = {
        "client_id":     config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
        "grant_type":    "refresh_token",
        "refresh_token": record["refresh_token"],
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://discord.com/api/v10/oauth2/token", data=data) as r:
                td = await r.json()
        if "access_token" not in td:
            log.warning(f"Refresh fallido para {user_id}: {td.get('error')}")
            return None
        token_store.save_user(user_id, td, record.get("username", ""))
        log.debug(f"Token refrescado para {user_id}")
        return td["access_token"]
    except aiohttp.ClientError as e:
        log.error(f"Error de red al refrescar {user_id}: {e}")
        return None


async def valid_token(user_id: int) -> str | None:
    """Devuelve un access token válido, refrescándolo si está a punto de expirar."""
    import time
    record = token_store.get_user(user_id)
    if not record:
        return None
    if time.time() >= record["expires_at"] - 300:
        return await refresh_token(user_id)
    return record["access_token"]


async def add_to_guild(
    user_id: int,
    guild_id: int,
    *,
    session: aiohttp.ClientSession | None = None,
    max_retries: int = 3,
) -> tuple[bool, str]:
    """
    Añade user_id al servidor guild_id usando su OAuth2 token.
    Maneja rate limits con reintentos automáticos.
    """
    access_token = await valid_token(user_id)
    if not access_token:
        return False, "Sin token válido."

    url     = f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}"
    headers = {"Authorization": f"Bot {config.TOKEN}", "Content-Type": "application/json"}
    payload = {"access_token": access_token}

    own_session = session is None
    s = session or aiohttp.ClientSession()

    try:
        for attempt in range(max_retries):
            try:
                async with s.put(url, headers=headers, json=payload) as r:
                    if r.status == 429:
                        data       = await r.json()
                        retry_wait = data.get("retry_after", 1.0) + 0.1
                        log.warning(f"Rate limit en add_to_guild. Esperando {retry_wait:.1f}s")
                        await asyncio.sleep(retry_wait)
                        continue
                    if r.status == 201: return True,  "Añadido correctamente."
                    if r.status == 204: return True,  "Ya era miembro."
                    if r.status == 403: return False, "Sin permisos (¿está el bot en ese servidor?)."
                    if r.status == 401: return False, "Token inválido. El usuario debe reverificarse."
                    if r.status == 404: return False, "Servidor no encontrado."
                    return False, f"HTTP {r.status}."
            except aiohttp.ClientError as e:
                log.warning(f"Error de red en add_to_guild (intento {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        return False, "Falló tras varios intentos."
    finally:
        if own_session:
            await s.close()


async def get_user_guilds(access_token: str) -> list[dict]:
    """Obtiene los servidores del usuario usando su access token."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://discord.com/api/v10/users/@me/guilds",
                headers={"Authorization": f"Bearer {access_token}"},
            ) as r:
                if r.status == 200:
                    return await r.json()
                log.warning(f"get_user_guilds retornó HTTP {r.status}")
                return []
    except aiohttp.ClientError as e:
        log.error(f"Error de red en get_user_guilds: {e}")
        return []
