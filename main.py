import asyncio
import logging
import discord
from discord.ext import commands
from discord import app_commands

import config

# ─────────────────────────────────────────────────────────────────────────────
#  Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-8s]  %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Silenciar logs muy verbosos de librerías externas
logging.getLogger("discord.http").setLevel(logging.WARNING)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

log = logging.getLogger("bot")

# ─────────────────────────────────────────────────────────────────────────────
#  Cogs
# ─────────────────────────────────────────────────────────────────────────────
COGS = [
    "cogs.verificacion",
    "cogs.red",
    "cogs.diversion",
]

# ─────────────────────────────────────────────────────────────────────────────
#  Clase Bot
# ─────────────────────────────────────────────────────────────────────────────
class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members         = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="la red de servidores 🌐",
            ),
            status=discord.Status.online,
        )

    async def setup_hook(self):
        ok = fail = 0
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info(f"✓ Cog cargado: {cog}")
                ok += 1
            except Exception as e:
                log.error(f"✗ Error cargando {cog}: {e}", exc_info=True)
                fail += 1
        log.info(f"Cogs: {ok} OK — {fail} errores")

    async def on_ready(self):
        try:
            synced = await self.tree.sync()
            log.info(f"✓ {len(synced)} comandos sincronizados")
        except Exception as e:
            log.error(f"Error sincronizando comandos: {e}")

        guilds  = len(self.guilds)
        members = sum(g.member_count for g in self.guilds)
        log.info(f"✓ Bot listo → {self.user} ({self.user.id})")
        log.info(f"  Servidores: {guilds}  |  Usuarios: {members}")

    async def on_guild_join(self, guild: discord.Guild):
        log.info(f"↗ Unido a: {guild.name} ({guild.id}) — {guild.member_count} miembros")

    async def on_guild_remove(self, guild: discord.Guild):
        log.info(f"↙ Expulsado de: {guild.name} ({guild.id})")

    async def on_error(self, event: str, *args, **kwargs):
        log.exception(f"Error en evento '{event}'")


# ─────────────────────────────────────────────────────────────────────────────
#  Error global de slash commands
# ─────────────────────────────────────────────────────────────────────────────
bot = Bot()


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ No tienes permisos para usar este comando."
    elif isinstance(error, app_commands.BotMissingPermissions):
        perms = ", ".join(error.missing_permissions)
        msg = f"❌ El bot no tiene permisos suficientes: `{perms}`"
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ Espera **{error.retry_after:.1f}s** antes de volver a usar este comando."
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "❌ Este comando solo puede usarse en servidores."
    elif isinstance(error, app_commands.CheckFailure):
        msg = "❌ No cumples los requisitos para usar este comando."
    else:
        cmd = interaction.command.name if interaction.command else "desconocido"
        log.error(f"Error en /{cmd} por {interaction.user}: {error}", exc_info=True)
        msg = f"❌ Error inesperado: `{error}`\nSi persiste, contacta al administrador."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass  # No podemos hacer nada más


# ─────────────────────────────────────────────────────────────────────────────
#  Arranque
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot detenido manualmente.")
