"""
Cog: Verificacion
──────────────────
Flujo OAuth2:
  1. Admin usa /setup-verificacion → embed con botón en el canal
  2. Usuario pulsa el botón → link efímero a la URL de autorización
  3. Usuario autoriza la app en Discord
  4. Discord redirige a http://localhost:5000/callback
  5. Servidor web intercambia código por token
  6. Token guardado, rol verificado asignado, mensaje de éxito

Comandos:
  /setup-verificacion   Envía el panel de verificación al canal actual
"""

import asyncio
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands

import config
import token_store
import utils


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
    """Botón persistente de verificación. Se recrea al reiniciar el bot."""

    def __init__(self, pending: dict):
        super().__init__(timeout=None)
        self._pending = pending

    @discord.ui.button(
        label="Verificarme",
        emoji="🔐",
        style=discord.ButtonStyle.green,
        custom_id="btn_verificar_oauth",
    )
    async def verificar(self, interaction: discord.Interaction, _: discord.ui.Button):
        # Si ya tiene el rol, no hace falta verificar
        role = interaction.guild.get_role(config.VERIFIED_ROLE_ID)
        if role and role in interaction.user.roles:
            await interaction.response.send_message("✅ Ya estás verificado.", ephemeral=True)
            return

        state = secrets.token_urlsafe(24)
        self._pending[state] = interaction.user.id

        params = {
            "client_id":     config.CLIENT_ID,
            "redirect_uri":  config.REDIRECT_URI,
            "response_type": "code",
            "scope":         "identify email guilds guilds.join",
            "state":         state,
            "prompt":        "consent",
        }
        url = "https://discord.com/oauth2/authorize?" + urlencode(params)

        embed = discord.Embed(
            title="🔗 Autorizar aplicación",
            description=(
                "Pulsa el botón para ir a la pantalla oficial de Discord.\n\n"
                "**¿Qué estás autorizando?**\n"
                "• Ver tu perfil y email\n"
                "• Ver tus servidores\n"
                "• Permitir que el bot te añada a servidores\n\n"
                "Al aceptar quedarás verificado automáticamente. ✅"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="El enlace expira en 10 minutos.")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Autorizar en Discord",
            emoji="🌐",
            style=discord.ButtonStyle.link,
            url=url,
        ))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # Expirar el state después de 10 minutos
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
        # Registrar la view persistente (para botones que sobreviven al reinicio)
        self.bot.add_view(VerificacionView(self.pending))

        # Iniciar servidor web OAuth2
        app = web.Application()
        app.router.add_get("/callback", self._handle_callback)
        app.router.add_get("/",         self._handle_home)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, "0.0.0.0", config.PORT).start()
        print(f"[✓] Servidor OAuth2 en http://localhost:{config.PORT}/callback")

    async def cog_unload(self):
        if self._runner:
            await self._runner.cleanup()

    # ── Endpoints web ─────────────────────────────────────────────────────────

    async def _handle_home(self, _: web.Request) -> web.Response:
        return _html("Bot activo", "#57f287", "✅", "El servidor de verificación está funcionando.")

    async def _handle_callback(self, request: web.Request) -> web.Response:
        # Usuario canceló la autorización
        if request.rel_url.query.get("error"):
            return _html("Autorización denegada", "#ed4245", "❌",
                         "Has cancelado la autorización. Vuelve a Discord y pulsa el botón cuando quieras.")

        code  = request.rel_url.query.get("code")
        state = request.rel_url.query.get("state")

        if not code or not state:
            return _html("Solicitud inválida", "#ed4245", "⚠️", "Parámetros incompletos.")

        user_id = self.pending.pop(state, None)
        if user_id is None:
            return _html("Enlace caducado", "#faa61a", "⏰",
                         "Este enlace ya fue usado o caducó. Genera uno nuevo desde Discord.")

        # Intercambiar código por token
        token_data = await self._exchange_code(code)
        if not token_data or "access_token" not in token_data:
            return _html("Error de autenticación", "#ed4245", "❌",
                         "No se pudo obtener el token. Inténtalo de nuevo.")

        # Verificar identidad del usuario
        user_info  = await self._get_user_info(token_data["access_token"])
        discord_id = int(user_info.get("id", 0)) if user_info else 0

        if discord_id != user_id:
            return _html("Error de identidad", "#ed4245", "🚫",
                         "El usuario que autorizó no coincide con quien inició la verificación.")

        username = user_info.get("username", "Desconocido")
        token_store.save_user(discord_id, token_data, username)

        # Añadir al servidor principal y asignar rol
        await utils.add_to_guild(discord_id, config.GUILD_ID)
        await self._assign_role(discord_id)
        await self._log(discord_id, username)

        return _html(
            "¡Verificación completada!", "#57f287", "✅",
            f"Bienvenido/a, <b>{username}</b>.<br>Ya tienes acceso completo. Puedes cerrar esta ventana.",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _exchange_code(self, code: str) -> dict | None:
        import aiohttp
        data = {
            "client_id":     config.CLIENT_ID,
            "client_secret": config.CLIENT_SECRET,
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  config.REDIRECT_URI,
        }
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post("https://discord.com/api/v10/oauth2/token", data=data) as r:
                    return await r.json()
        except Exception:
            return None

    async def _get_user_info(self, access_token: str) -> dict | None:
        import aiohttp
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bearer {access_token}"},
                ) as r:
                    return await r.json() if r.status == 200 else None
        except Exception:
            return None

    async def _assign_role(self, user_id: int):
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return
        try:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            role   = guild.get_role(config.VERIFIED_ROLE_ID)
            if member and role and role not in member.roles:
                await member.add_roles(role, reason="Verificación OAuth2")
        except Exception:
            pass

    async def _log(self, user_id: int, username: str):
        if not config.LOG_CHANNEL_ID:
            return
        guild = self.bot.get_guild(config.GUILD_ID)
        canal = guild.get_channel(config.LOG_CHANNEL_ID) if guild else None
        if not canal:
            return
        try:
            await canal.send(embed=discord.Embed(
                title="📝 Nueva verificación",
                description=f"<@{user_id}> (`{username}`) completó la verificación OAuth2.",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            ))
        except Exception:
            pass

    # ── Comando ───────────────────────────────────────────────────────────────

    @app_commands.command(
        name="setup-verificacion",
        description="[Admin] Envía el panel de verificación a este canal.",
    )
    @app_commands.describe(canal="Canal donde enviar el panel. Por defecto: canal actual.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_verificacion(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
    ):
        destino = canal or interaction.channel

        embed = discord.Embed(
            title="🔐 Verificación de miembro",
            description=(
                f"Bienvenido/a a **{interaction.guild.name}**.\n\n"
                "Para acceder al servidor completo debes **verificar tu cuenta**.\n"
                "Solo tienes que pulsar el botón y aceptar los permisos en Discord. ⬇️"
            ),
            color=discord.Color.blurple(),
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text=f"{interaction.guild.name} • Verificación OAuth2")

        await destino.send(embed=embed, view=VerificacionView(self.pending))
        await interaction.response.send_message(
            f"✅ Panel de verificación enviado en {destino.mention}.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Verificacion(bot))
