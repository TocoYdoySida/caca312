"""
Cog: Verificacion
─────────────────
Gestiona el panel de verificación OAuth2 y el servidor web de callback.
"""

import asyncio
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

import aiohttp
from aiohttp import web
import discord
from discord.ext import commands
from discord import app_commands

import config
import token_store


# ── Helpers OAuth2 ────────────────────────────────────────────────────────────

SCOPES = "identify email guilds guilds.join"


def build_oauth_url(state: str) -> str:
    params = {
        "client_id":     config.CLIENT_ID,
        "redirect_uri":  config.REDIRECT_URI,
        "response_type": "code",
        "scope":         SCOPES,
        "state":         state,
        "prompt":        "consent",
    }
    return "https://discord.com/oauth2/authorize?" + urlencode(params)


async def exchange_code(code: str) -> dict:
    data = {
        "client_id":     config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  config.REDIRECT_URI,
    }
    async with aiohttp.ClientSession() as s:
        async with s.post("https://discord.com/api/v10/oauth2/token", data=data) as r:
            return await r.json()


async def get_user_info(access_token: str) -> dict:
    async with aiohttp.ClientSession() as s:
        async with s.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as r:
            return await r.json()


# ── HTML de respuesta ─────────────────────────────────────────────────────────

def _html(title: str, color: str, emoji: str, body: str) -> web.Response:
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>{title}</title>
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{min-height:100vh;display:flex;align-items:center;justify-content:center;
         background:#23272a;font-family:'Segoe UI',sans-serif;color:#fff}}
    .card{{background:#2c2f33;border-radius:12px;padding:40px 50px;text-align:center;
           max-width:480px;box-shadow:0 8px 32px #0008;border-top:4px solid {color}}}
    .emoji{{font-size:3rem;margin-bottom:16px}}
    h1{{font-size:1.6rem;margin-bottom:12px;color:{color}}}
    p{{color:#b9bbbe;line-height:1.6}}
  </style>
</head>
<body>
  <div class="card">
    <div class="emoji">{emoji}</div>
    <h1>{title}</h1>
    <p>{body}</p>
  </div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


# ── Vista del botón de verificación (persistente) ────────────────────────────

class VerificacionView(discord.ui.View):
    def __init__(self, pending: dict):
        super().__init__(timeout=None)
        self._pending = pending

    @discord.ui.button(
        label="Verificarme",
        emoji="🔐",
        style=discord.ButtonStyle.green,
        custom_id="btn_verificar_oauth",
    )
    async def verificar(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(config.VERIFIED_ROLE_ID)
        if role and role in interaction.user.roles:
            await interaction.response.send_message("✅ Ya estás verificado.", ephemeral=True)
            return

        state = secrets.token_urlsafe(24)
        self._pending[state] = interaction.user.id

        embed = discord.Embed(
            title="🔗 Autorizar aplicación",
            description=(
                "Pulsa el botón para ir a la pantalla oficial de Discord.\n\n"
                "Al aceptar quedarás verificado automáticamente. ✅"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="El enlace caduca en 10 minutos.")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Autorizar en Discord",
            emoji="🌐",
            style=discord.ButtonStyle.link,
            url=build_oauth_url(state),
        ))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        async def _expire():
            await asyncio.sleep(600)
            self._pending.pop(state, None)
        asyncio.create_task(_expire())


# ── Cog ───────────────────────────────────────────────────────────────────────

class Verificacion(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot     = bot
        self.pending: dict[str, int] = {}
        self._runner = None

    async def cog_load(self):
        self.bot.add_view(VerificacionView(self.pending))
        app = web.Application()
        app.router.add_get("/callback", self.handle_callback)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, "0.0.0.0", config.PORT).start()
        print(f"[✓] Servidor web en http://0.0.0.0:{config.PORT}")

    async def cog_unload(self):
        if self._runner:
            await self._runner.cleanup()

    # ── Callback OAuth2 ───────────────────────────────────────────────────────

    async def handle_callback(self, request: web.Request) -> web.Response:
        code  = request.rel_url.query.get("code")
        state = request.rel_url.query.get("state")

        if request.rel_url.query.get("error"):
            return _html("Autorización denegada", "#ed4245", "❌",
                         "Has cancelado. Vuelve y pulsa <b>🔐 Verificarme</b> cuando quieras.")

        if not code or not state:
            return _html("Solicitud inválida", "#ed4245", "⚠️", "Parámetros incompletos.")

        user_id = self.pending.pop(state, None)
        if user_id is None:
            return _html("Enlace caducado", "#faa61a", "⏰",
                         "Este enlace ya fue usado o caducó. Genera uno nuevo.")

        token_data = await exchange_code(code)
        if "access_token" not in token_data:
            return _html("Error de autenticación", "#ed4245", "❌",
                         "No se pudo obtener el token. Inténtalo de nuevo.")

        user_info  = await get_user_info(token_data["access_token"])
        discord_id = int(user_info.get("id", 0))

        if discord_id != user_id:
            return _html("Error de identidad", "#ed4245", "🚫",
                         "El usuario que autorizó no coincide con el que inició la verificación.")

        username = user_info.get("username", "")
        token_store.save_user(discord_id, token_data, username)

        # Añadir al servidor principal (si no está ya)
        from cogs.red import add_to_guild
        await add_to_guild(discord_id, config.GUILD_ID)

        # Asignar rol verificado
        guild  = self.bot.get_guild(config.GUILD_ID)
        member = guild.get_member(discord_id) if guild else None
        if not member and guild:
            try:
                member = await guild.fetch_member(discord_id)
            except Exception:
                pass

        role_assigned = False
        if member and guild:
            role = guild.get_role(config.VERIFIED_ROLE_ID)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Verificación OAuth2")
                    role_assigned = True
                except discord.Forbidden:
                    pass

        # Log
        if config.LOG_CHANNEL_ID and guild:
            canal = guild.get_channel(config.LOG_CHANNEL_ID)
            if canal:
                e = discord.Embed(
                    title="📝 Nueva verificación",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc),
                )
                e.add_field(name="Usuario",       value=f"<@{discord_id}> (`{discord_id}`)", inline=False)
                e.add_field(name="Tag",            value=username,                            inline=True)
                e.add_field(name="Rol asignado",   value="✅ Sí" if role_assigned else "⚠️ No", inline=True)
                await canal.send(embed=e)

        return _html("¡Verificación completada!", "#57f287", "✅",
                     f"Bienvenido/a, <b>{username}</b>.<br>Ya tienes acceso. Puedes cerrar esta ventana.")

    # ── Comando /setup-verificacion ───────────────────────────────────────────

    @app_commands.command(
        name="setup-verificacion",
        description="[Admin] Envía el panel de verificación a este canal.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_verificacion(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔐 Verificación de miembro",
            description=(
                f"Bienvenido/a a **{interaction.guild.name}**.\n\n"
                "Para acceder debes **verificarte** y **autorizar la aplicación**.\n"
                "Solo tienes que aceptar los permisos en Discord. ⬇️"
            ),
            color=discord.Color.blurple(),
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text=f"{interaction.guild.name} · Verificación")
        await interaction.channel.send(embed=embed, view=VerificacionView(self.pending))
        await interaction.response.send_message("✅ Panel enviado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Verificacion(bot))
