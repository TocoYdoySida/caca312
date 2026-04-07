"""
Cog: Red
────────
Gestión de tokens OAuth2 y unión a servidores.
Comandos: /unir-usuario  /unir-todos  /tokens-info  /revocar-token

Función pública `add_to_guild` usada también por cogs/verificacion.py.
"""

import asyncio
import time
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

import config
import token_store


# ── Helpers de token ──────────────────────────────────────────────────────────

async def _refresh(user_id: int) -> str | None:
    record = token_store.get_user(user_id)
    if not record:
        return None
    data = {
        "client_id":     config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
        "grant_type":    "refresh_token",
        "refresh_token": record["refresh_token"],
    }
    async with aiohttp.ClientSession() as s:
        async with s.post("https://discord.com/api/v10/oauth2/token", data=data) as r:
            td = await r.json()
    if "access_token" not in td:
        print(f"[✗] No se pudo refrescar token de {user_id}: {td}")
        return None
    token_store.save_user(user_id, td, record.get("username", ""))
    return td["access_token"]


async def _valid_token(user_id: int) -> str | None:
    record = token_store.get_user(user_id)
    if not record:
        return None
    if time.time() >= record["expires_at"] - 300:
        return await _refresh(user_id)
    return record["access_token"]


# ── Función pública: añadir usuario a un servidor ────────────────────────────

async def add_to_guild(user_id: int, guild_id: int) -> tuple[bool, str]:
    """
    Añade `user_id` al servidor `guild_id` usando su token OAuth2 guardado.
    El bot debe ser miembro de `guild_id`.
    Devuelve (éxito: bool, mensaje: str).
    """
    access_token = await _valid_token(user_id)
    if not access_token:
        return False, "Sin token válido. El usuario debe verificarse primero."

    headers = {
        "Authorization": f"Bot {config.TOKEN}",
        "Content-Type":  "application/json",
    }
    async with aiohttp.ClientSession() as s:
        async with s.put(
            f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}",
            headers=headers,
            json={"access_token": access_token},
        ) as r:
            status = r.status

    if status == 201:   return True,  "Usuario añadido correctamente."
    if status == 204:   return True,  "El usuario ya era miembro."
    if status == 403:   return False, "Sin permisos en ese servidor (¿está el bot ahí?)."
    if status == 401:   return False, "Token inválido. El usuario debe reverificarse."
    return False, f"Error de la API de Discord (HTTP {status})."


# ── Cog ───────────────────────────────────────────────────────────────────────

class Red(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /unir-usuario ─────────────────────────────────────────────────────────
    @app_commands.command(
        name="unir-usuario",
        description="[Admin] Añade un usuario verificado a otro servidor de la red.",
    )
    @app_commands.describe(
        usuario="Usuario a añadir.",
        servidor_id="ID del servidor destino.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def unir_usuario(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        servidor_id: str,
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(servidor_id)
        except ValueError:
            await interaction.followup.send("❌ ID de servidor inválido.", ephemeral=True)
            return

        ok, msg = await add_to_guild(usuario.id, gid)
        embed = discord.Embed(
            title="✅ Éxito" if ok else "❌ Error",
            description=f"**Usuario:** {usuario.mention}\n**Servidor:** `{gid}`\n\n{msg}",
            color=discord.Color.green() if ok else discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /unir-todos ───────────────────────────────────────────────────────────
    @app_commands.command(
        name="unir-todos",
        description="[Admin] Añade a todos los miembros verificados a otro servidor.",
    )
    @app_commands.describe(servidor_id="ID del servidor destino.")
    @app_commands.checks.has_permissions(administrator=True)
    async def unir_todos(self, interaction: discord.Interaction, servidor_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(servidor_id)
        except ValueError:
            await interaction.followup.send("❌ ID de servidor inválido.", ephemeral=True)
            return

        guild = self.bot.get_guild(config.GUILD_ID)
        role  = guild.get_role(config.VERIFIED_ROLE_ID) if guild else None
        if not role:
            await interaction.followup.send("❌ No se encontró el rol verificado.", ephemeral=True)
            return

        miembros = [m for m in role.members if not m.bot]
        if not miembros:
            await interaction.followup.send("⚠️ No hay miembros verificados.", ephemeral=True)
            return

        await interaction.followup.send(
            f"⏳ Procesando **{len(miembros)}** miembros...", ephemeral=True
        )

        ok = fail = sin_token = 0
        for m in miembros:
            if not token_store.get_user(m.id):
                sin_token += 1
                continue
            exito, _ = await add_to_guild(m.id, gid)
            if exito:
                ok += 1
            else:
                fail += 1
            await asyncio.sleep(0.5)   # evitar rate-limit

        embed = discord.Embed(
            title="📊 Resumen — Unir todos",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="✅ Añadidos",    value=str(ok),        inline=True)
        embed.add_field(name="❌ Errores",     value=str(fail),      inline=True)
        embed.add_field(name="⚠️ Sin token",  value=str(sin_token), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /tokens-info ──────────────────────────────────────────────────────────
    @app_commands.command(name="tokens-info", description="[Admin] Estadísticas de tokens guardados.")
    @app_commands.checks.has_permissions(administrator=True)
    async def tokens_info(self, interaction: discord.Interaction):
        todos     = token_store.all_users()
        ahora     = time.time()
        total     = len(todos)
        validos   = sum(1 for v in todos.values() if v["expires_at"] > ahora)
        expirados = total - validos

        embed = discord.Embed(
            title="🔑 Estadísticas de tokens OAuth2",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Total guardados", value=str(total),     inline=True)
        embed.add_field(name="✅ Válidos",       value=str(validos),   inline=True)
        embed.add_field(name="⏰ Expirados",     value=str(expirados), inline=True)
        embed.set_footer(text="Los tokens expirados se refrescan automáticamente al usarlos.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /revocar-token ────────────────────────────────────────────────────────
    @app_commands.command(
        name="revocar-token",
        description="[Admin] Elimina el token OAuth2 guardado de un usuario.",
    )
    @app_commands.describe(usuario="Usuario cuyo token eliminar.")
    @app_commands.checks.has_permissions(administrator=True)
    async def revocar_token(self, interaction: discord.Interaction, usuario: discord.Member):
        removed = token_store.remove_user(usuario.id)
        if removed:
            await interaction.response.send_message(
                f"✅ Token de {usuario.mention} eliminado. Deberá reverificarse.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ {usuario.mention} no tenía token guardado.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Red(bot))
