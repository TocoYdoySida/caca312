"""
Cog: Diversion
──────────────
Comandos de bromas y diversión (todos via DM, nadie es baneado/kickeado realmente).

  /fake-ban          DM de ban falso
  /fake-kick         DM de kick falso
  /fake-warn         DM de advertencia falsa
  /fake-nitro        DM de regalo de Nitro falso
  /fake-boost        DM de boost falso
  /fake-mensaje      DM con un mensaje falso "del sistema"
  /webhook           Envía un mensaje con nombre y avatar personalizados
  /ghostping         Menciona a alguien y borra el mensaje al instante
  /contar-regresiva  Cuenta atrás en un canal (3, 2, 1...)
"""

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord import app_commands

log = logging.getLogger("bot.diversion")

# ─────────────────────────────────────────────────────────────────────────────
#  Embeds de notificaciones falsas
# ─────────────────────────────────────────────────────────────────────────────

def _embed_fake_ban(guild_name: str, razon: str, revelar: bool) -> discord.Embed:
    embed = discord.Embed(
        title="🔨 Has sido baneado",
        description=(
            f"Has sido **baneado permanentemente** de **{guild_name}**.\n\n"
            f"📋 **Razón:** {razon}\n\n"
            "Si crees que esto es un error, contacta a un administrador."
        ),
        color=0xED4245,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Discord · Sistema de moderación")
    if revelar:
        embed.add_field(
            name="​",
            value="||😂 Era una broma, no fuiste baneado. Tranquilo.||",
            inline=False,
        )
    return embed


def _embed_fake_kick(guild_name: str, razon: str, revelar: bool) -> discord.Embed:
    embed = discord.Embed(
        title="👢 Has sido expulsado",
        description=(
            f"Has sido **expulsado** de **{guild_name}**.\n\n"
            f"📋 **Razón:** {razon}\n\n"
            "Puedes volver al servidor con una nueva invitación."
        ),
        color=0xFAA61A,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Discord · Sistema de moderación")
    if revelar:
        embed.add_field(
            name="​",
            value="||😂 Era una broma, no fuiste expulsado. Sigue en el server.||",
            inline=False,
        )
    return embed


def _embed_fake_warn(guild_name: str, razon: str, total: int) -> discord.Embed:
    embed = discord.Embed(
        title="⚠️ Has recibido una advertencia",
        description=(
            f"El equipo de moderación de **{guild_name}** te ha enviado una advertencia.\n\n"
            f"📋 **Razón:** {razon}\n"
            f"📊 **Advertencias totales:** {total}\n\n"
            "Por favor, revisa las reglas del servidor para evitar futuras sanciones."
        ),
        color=0xFEE75C,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Discord · Sistema de moderación")
    return embed


def _embed_fake_nitro(revelar: bool) -> discord.Embed:
    embed = discord.Embed(
        title="🎁 ¡Has recibido Discord Nitro!",
        description=(
            "Un usuario te ha regalado **Discord Nitro** por 1 mes.\n\n"
            "Haz clic en el botón de abajo para reclamarlo antes de que expire.\n"
            "⏰ Este regalo expira en **24 horas**."
        ),
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url="https://i.imgur.com/w9aiD6F.png")
    embed.set_footer(text="Discord Nitro · gifts.discord.gg")
    if revelar:
        embed.add_field(
            name="​",
            value="||😂 Jajaja era broma, no hay ningún Nitro. Te pillé.||",
            inline=False,
        )
    return embed


def _embed_fake_boost(guild_name: str, revelar: bool) -> discord.Embed:
    embed = discord.Embed(
        title="🚀 ¡Has boosteado el servidor!",
        description=(
            f"¡Gracias por hacer boost en **{guild_name}**! 💜\n\n"
            "Gracias a ti el servidor ha desbloqueado nuevas ventajas.\n"
            "Tu boost estará activo durante **30 días**."
        ),
        color=0xFF73FA,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Discord · Server Boosting")
    if revelar:
        embed.add_field(
            name="​",
            value="||😂 Mentira, no boosteaste nada. Pero gracias igualmente.||",
            inline=False,
        )
    return embed


# ─────────────────────────────────────────────────────────────────────────────
#  Cog
# ─────────────────────────────────────────────────────────────────────────────

class Diversion(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /fake-ban ─────────────────────────────────────────────────────────────
    @app_commands.command(name="fake-ban", description="[Admin] Envía un DM de ban falso (broma).")
    @app_commands.describe(
        usuario="Usuario al que enviar la broma.",
        razon="Razón del 'ban'.",
        revelar="Revelar al final que es broma (por defecto: No).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def fake_ban(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Violación de las normas del servidor.",
        revelar: bool = False,
    ):
        if usuario.bot:
            await interaction.response.send_message("❌ No puedes bromear con bots.", ephemeral=True)
            return
        try:
            await usuario.send(embed=_embed_fake_ban(interaction.guild.name, razon, revelar))
            log.info(f"fake-ban enviado a {usuario} por {interaction.user}")
            await interaction.response.send_message(
                f"✅ Broma de ban enviada a {usuario.mention}. 😂", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {usuario.mention} tiene los DMs cerrados.", ephemeral=True
            )

    # ── /fake-kick ────────────────────────────────────────────────────────────
    @app_commands.command(name="fake-kick", description="[Admin] Envía un DM de kick falso (broma).")
    @app_commands.describe(
        usuario="Usuario al que enviar la broma.",
        razon="Razón del 'kick'.",
        revelar="Revelar al final que es broma.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def fake_kick(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Comportamiento inadecuado.",
        revelar: bool = False,
    ):
        if usuario.bot:
            await interaction.response.send_message("❌ No puedes bromear con bots.", ephemeral=True)
            return
        try:
            await usuario.send(embed=_embed_fake_kick(interaction.guild.name, razon, revelar))
            log.info(f"fake-kick enviado a {usuario} por {interaction.user}")
            await interaction.response.send_message(
                f"✅ Broma de kick enviada a {usuario.mention}. 😂", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {usuario.mention} tiene los DMs cerrados.", ephemeral=True
            )

    # ── /fake-warn ────────────────────────────────────────────────────────────
    @app_commands.command(name="fake-warn", description="[Admin] Envía un DM de advertencia falsa (broma).")
    @app_commands.describe(
        usuario="Usuario.",
        razon="Razón de la 'advertencia'.",
        total_warns="Número de advertencias que aparecerá (para asustar más).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def fake_warn(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Comportamiento sospechoso detectado.",
        total_warns: app_commands.Range[int, 1, 10] = 3,
    ):
        if usuario.bot:
            await interaction.response.send_message("❌ No puedes bromear con bots.", ephemeral=True)
            return
        try:
            await usuario.send(embed=_embed_fake_warn(interaction.guild.name, razon, total_warns))
            await interaction.response.send_message(
                f"✅ Advertencia falsa enviada a {usuario.mention}. 😈", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {usuario.mention} tiene los DMs cerrados.", ephemeral=True
            )

    # ── /fake-nitro ───────────────────────────────────────────────────────────
    @app_commands.command(name="fake-nitro", description="[Admin] Envía un DM de regalo de Nitro falso (broma).")
    @app_commands.describe(
        usuario="Usuario.",
        revelar="Revelar al final que es broma.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def fake_nitro(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        revelar: bool = False,
    ):
        if usuario.bot:
            await interaction.response.send_message("❌ No puedes bromear con bots.", ephemeral=True)
            return
        try:
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label="Reclamar Nitro",
                emoji="🎁",
                style=discord.ButtonStyle.blurple,
                url="https://discord.com/nitro",  # URL real de nitro para más realismo
            ))
            await usuario.send(embed=_embed_fake_nitro(revelar), view=view)
            await interaction.response.send_message(
                f"✅ Falso Nitro enviado a {usuario.mention}. 😂", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {usuario.mention} tiene los DMs cerrados.", ephemeral=True
            )

    # ── /fake-boost ───────────────────────────────────────────────────────────
    @app_commands.command(name="fake-boost", description="[Admin] Envía un DM de boost falso (broma).")
    @app_commands.describe(
        usuario="Usuario.",
        revelar="Revelar al final que es broma.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def fake_boost(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        revelar: bool = False,
    ):
        if usuario.bot:
            await interaction.response.send_message("❌ No puedes bromear con bots.", ephemeral=True)
            return
        try:
            await usuario.send(embed=_embed_fake_boost(interaction.guild.name, revelar))
            await interaction.response.send_message(
                f"✅ Falso boost enviado a {usuario.mention}. 💜", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {usuario.mention} tiene los DMs cerrados.", ephemeral=True
            )

    # ── /fake-mensaje ─────────────────────────────────────────────────────────
    @app_commands.command(name="fake-mensaje", description="[Admin] Envía un DM con un mensaje personalizado que parece oficial.")
    @app_commands.describe(
        usuario="Usuario.",
        titulo="Título del mensaje.",
        descripcion="Cuerpo del mensaje.",
        color="Color hex (por defecto rojo para asustar).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def fake_mensaje(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        titulo: str,
        descripcion: str,
        color: str = "ed4245",
    ):
        if usuario.bot:
            await interaction.response.send_message("❌ No puedes bromear con bots.", ephemeral=True)
            return
        try:
            hex_c = int(color.lstrip("#"), 16)
        except ValueError:
            hex_c = 0xED4245

        embed = discord.Embed(
            title=titulo,
            description=descripcion,
            color=hex_c,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Discord · Notificación del sistema")

        try:
            await usuario.send(embed=embed)
            await interaction.response.send_message(
                f"✅ Mensaje enviado a {usuario.mention}.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {usuario.mention} tiene los DMs cerrados.", ephemeral=True
            )

    # ── /webhook ──────────────────────────────────────────────────────────────
    @app_commands.command(name="webhook", description="[Admin] Envía un mensaje con nombre y avatar personalizados.")
    @app_commands.describe(
        canal="Canal donde enviar el mensaje.",
        nombre="Nombre que aparecerá como autor.",
        mensaje="Mensaje a enviar.",
        avatar_url="URL de avatar (opcional).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_webhook(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        nombre: str,
        mensaje: str,
        avatar_url: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        # Verificar permisos del bot en el canal
        perms = canal.permissions_for(interaction.guild.me)
        if not perms.manage_webhooks:
            await interaction.followup.send(
                "❌ El bot necesita el permiso **Gestionar Webhooks** en ese canal.",
                ephemeral=True,
            )
            return

        webhook = None
        try:
            webhook = await canal.create_webhook(name="Bot Temp")
            kwargs  = {"username": nombre[:80], "content": mensaje}
            if avatar_url:
                kwargs["avatar_url"] = avatar_url
            await webhook.send(**kwargs)
            log.info(f"webhook enviado en #{canal.name} ({interaction.guild.name}) por {interaction.user}")
            await interaction.followup.send(
                f"✅ Mensaje enviado en {canal.mention} como **{nombre}**.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Sin permisos para enviar en ese canal.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
        finally:
            if webhook:
                try:
                    await webhook.delete()
                except Exception:
                    pass

    # ── /ghostping ────────────────────────────────────────────────────────────
    @app_commands.command(name="ghostping", description="[Admin] Menciona a alguien y borra el mensaje instantáneamente.")
    @app_commands.describe(
        canal="Canal donde hacer el ghostping.",
        usuario="Usuario a mencionar.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ghostping(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        usuario: discord.Member,
    ):
        await interaction.response.defer(ephemeral=True)

        perms = canal.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.manage_messages:
            await interaction.followup.send(
                "❌ El bot necesita **Enviar Mensajes** y **Gestionar Mensajes** en ese canal.",
                ephemeral=True,
            )
            return

        try:
            msg = await canal.send(usuario.mention)
            await msg.delete()
            log.info(f"ghostping a {usuario} en #{canal.name} por {interaction.user}")
            await interaction.followup.send(
                f"👻 Ghostping enviado a {usuario.mention} en {canal.mention}.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Sin permisos.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    # ── /contar-regresiva ─────────────────────────────────────────────────────
    @app_commands.command(name="contar-regresiva", description="[Admin] Hace una cuenta atrás en el canal.")
    @app_commands.describe(
        canal="Canal donde hacer la cuenta atrás.",
        desde="Número desde el que empezar (máx. 10).",
        mensaje_final="Mensaje al llegar a 0 (opcional).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def contar_regresiva(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        desde: app_commands.Range[int, 2, 10] = 5,
        mensaje_final: str = "🚀 ¡Ya!",
    ):
        await interaction.response.defer(ephemeral=True)

        perms = canal.permissions_for(interaction.guild.me)
        if not perms.send_messages:
            await interaction.followup.send("❌ Sin permisos para enviar en ese canal.", ephemeral=True)
            return

        try:
            for n in range(desde, 0, -1):
                await canal.send(f"**{n}**...")
                await asyncio.sleep(1)
            await canal.send(f"**{mensaje_final}**")
            await interaction.followup.send(
                f"✅ Cuenta atrás completada en {canal.mention}.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Sin permisos.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Diversion(bot))
