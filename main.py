import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import config

COGS = [
    "cogs.verificacion",
    "cogs.red",
]

intents = discord.Intents.default()
intents.members        = True
intents.message_content = True   # necesario para /snipe

bot = commands.Bot(command_prefix="!", intents=intents)


async def setup_hook():
    for cog in COGS:
        await bot.load_extension(cog)
    print(f"[✓] {len(COGS)} cogs cargados")

bot.setup_hook = setup_hook


# ── Error global (permisos insuficientes) ─────────────────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ Necesitas ser **Administrador** para usar este comando."
        try:
            await interaction.response.send_message(msg, ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send(msg, ephemeral=True)
    else:
        raise error


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"[✓] {len(synced)} comando(s) sincronizado(s)")
    except Exception as e:
        print(f"[✗] Error al sincronizar: {e}")
    print(f"[✓] Bot listo → {bot.user} ({bot.user.id})")


async def main():
    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
