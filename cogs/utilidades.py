"""
Cog: Utilidades
───────────────
Comandos: /ping  /botinfo  /userinfo  /serverinfo
          /avatar  /banner  /roleinfo  /snipe
"""

from datetime import datetime, timezone
from collections import defaultdict

import discord
from discord.ext import commands
from discord import app_commands


class Utilidades(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Guarda el último mensaje borrado por canal: channel_id → Message
        self._snipe_cache: dict[int, discord.Message] = {}

    # ── Evento: cachear mensajes borrados ─────────────────────────────────────
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot:
            return
        self._snipe_cache[message.channel.id] = message

    # ── /ping ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="ping", description="Muestra la latencia del bot.")
    async def cmd_ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        color = (
            discord.Color.green()  if latency < 100 else
            discord.Color.orange() if latency < 200 else
            discord.Color.red()
        )
        embed = discord.Embed(title="🏓 Pong!", color=color)
        embed.add_field(name="Latencia WebSocket", value=f"`{latency} ms`")
        await interaction.response.send_message(embed=embed)

    # ── /botinfo ──────────────────────────────────────────────────────────────
    @app_commands.command(name="botinfo", description="Información sobre el bot.")
    async def cmd_botinfo(self, interaction: discord.Interaction):
        bot    = self.bot
        guilds = len(bot.guilds)
        users  = sum(g.member_count for g in bot.guilds)
        cmds   = len(bot.tree.get_commands())

        uptime_ts = int(bot.user.created_at.timestamp())

        embed = discord.Embed(
            title=f"🤖 {bot.user.name}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.add_field(name="ID",           value=f"`{bot.user.id}`",    inline=True)
        embed.add_field(name="Servidores",   value=str(guilds),            inline=True)
        embed.add_field(name="Usuarios",     value=str(users),             inline=True)
        embed.add_field(name="Comandos",     value=str(cmds),              inline=True)
        embed.add_field(name="Creado",       value=f"<t:{uptime_ts}:R>",   inline=True)
        embed.add_field(name="Latencia",     value=f"`{round(bot.latency*1000)} ms`", inline=True)
        embed.set_footer(text="discord.py 2.x")
        await interaction.response.send_message(embed=embed)

    # ── /userinfo ─────────────────────────────────────────────────────────────
    @app_commands.command(name="userinfo", description="Información de un usuario.")
    @app_commands.describe(miembro="Usuario a consultar (por defecto, tú mismo).")
    async def cmd_userinfo(
        self,
        interaction: discord.Interaction,
        miembro: discord.Member | None = None,
    ):
        m = miembro or interaction.user
        roles = [r.mention for r in reversed(m.roles) if r != interaction.guild.default_role]

        created_ts = int(m.created_at.timestamp())
        joined_ts  = int(m.joined_at.timestamp()) if m.joined_at else 0

        badges = []
        if m.bot:
            badges.append("🤖 Bot")
        if m.premium_since:
            badges.append("💎 Nitro Booster")

        embed = discord.Embed(
            title=f"👤 {m}",
            color=m.color if m.color != discord.Color.default() else discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=m.display_avatar.url)
        embed.add_field(name="ID",            value=f"`{m.id}`",                       inline=True)
        embed.add_field(name="Apodo",         value=m.display_name,                    inline=True)
        embed.add_field(name="Cuenta creada", value=f"<t:{created_ts}:R>",             inline=True)
        embed.add_field(name="Se unió",       value=f"<t:{joined_ts}:R>" if joined_ts else "?", inline=True)
        embed.add_field(name="Estado",        value=str(m.status).title(),             inline=True)
        embed.add_field(name="Insignias",     value=", ".join(badges) or "Ninguna",    inline=True)
        if roles:
            embed.add_field(
                name=f"Roles ({len(roles)})",
                value=" ".join(roles[:20]) + ("…" if len(roles) > 20 else ""),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    # ── /serverinfo ───────────────────────────────────────────────────────────
    @app_commands.command(name="serverinfo", description="Información del servidor.")
    async def cmd_serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        created_ts = int(g.created_at.timestamp())

        humanos = sum(1 for m in g.members if not m.bot)
        bots    = g.member_count - humanos

        embed = discord.Embed(
            title=f"🏠 {g.name}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        if g.banner:
            embed.set_image(url=g.banner.url)

        embed.add_field(name="ID",           value=f"`{g.id}`",           inline=True)
        embed.add_field(name="Dueño",        value=g.owner.mention,        inline=True)
        embed.add_field(name="Creado",       value=f"<t:{created_ts}:R>",  inline=True)
        embed.add_field(name="Miembros",     value=str(g.member_count),    inline=True)
        embed.add_field(name="Humanos",      value=str(humanos),            inline=True)
        embed.add_field(name="Bots",         value=str(bots),               inline=True)
        embed.add_field(name="Canales",      value=str(len(g.channels)),   inline=True)
        embed.add_field(name="Roles",        value=str(len(g.roles)),       inline=True)
        embed.add_field(name="Emojis",       value=str(len(g.emojis)),      inline=True)
        embed.add_field(name="Nivel boost",  value=f"Nivel {g.premium_tier} ({g.premium_subscription_count} boosts)", inline=True)
        embed.add_field(name="Verificación", value=str(g.verification_level).title(), inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /avatar ───────────────────────────────────────────────────────────────
    @app_commands.command(name="avatar", description="Muestra el avatar de un usuario.")
    @app_commands.describe(miembro="Usuario (por defecto, tú mismo).")
    async def cmd_avatar(
        self,
        interaction: discord.Interaction,
        miembro: discord.Member | None = None,
    ):
        m = miembro or interaction.user
        embed = discord.Embed(
            title=f"🖼️ Avatar de {m.display_name}",
            color=discord.Color.blurple(),
        )
        embed.set_image(url=m.display_avatar.url)
        embed.add_field(
            name="Descargar",
            value=f"[PNG]({m.display_avatar.replace(format='png', size=1024).url}) · "
                  f"[JPG]({m.display_avatar.replace(format='jpg', size=1024).url}) · "
                  f"[WEBP]({m.display_avatar.replace(format='webp', size=1024).url})",
        )
        await interaction.response.send_message(embed=embed)

    # ── /banner ───────────────────────────────────────────────────────────────
    @app_commands.command(name="banner", description="Muestra el banner de un usuario.")
    @app_commands.describe(miembro="Usuario (por defecto, tú mismo).")
    async def cmd_banner(
        self,
        interaction: discord.Interaction,
        miembro: discord.Member | None = None,
    ):
        await interaction.response.defer()
        target = miembro or interaction.user
        # Necesitamos fetch_user para obtener el banner
        user = await self.bot.fetch_user(target.id)
        if not user.banner:
            await interaction.followup.send(
                f"❌ {target.display_name} no tiene banner configurado.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title=f"🎨 Banner de {target.display_name}",
            color=discord.Color.blurple(),
        )
        embed.set_image(url=user.banner.url)
        await interaction.followup.send(embed=embed)

    # ── /roleinfo ─────────────────────────────────────────────────────────────
    @app_commands.command(name="roleinfo", description="Información sobre un rol.")
    @app_commands.describe(rol="Rol a consultar.")
    async def cmd_roleinfo(self, interaction: discord.Interaction, rol: discord.Role):
        created_ts = int(rol.created_at.timestamp())
        perms_list = [p.replace("_", " ").title() for p, v in rol.permissions if v]

        embed = discord.Embed(
            title=f"🎭 {rol.name}",
            color=rol.color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="ID",          value=f"`{rol.id}`",             inline=True)
        embed.add_field(name="Color",       value=str(rol.color),             inline=True)
        embed.add_field(name="Miembros",    value=str(len(rol.members)),      inline=True)
        embed.add_field(name="Creado",      value=f"<t:{created_ts}:R>",      inline=True)
        embed.add_field(name="Mencionable", value="✅" if rol.mentionable else "❌", inline=True)
        embed.add_field(name="Separado",    value="✅" if rol.hoist else "❌", inline=True)
        if perms_list:
            embed.add_field(
                name=f"Permisos clave ({len(perms_list)})",
                value=", ".join(perms_list[:15]) + ("…" if len(perms_list) > 15 else ""),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    # ── /snipe ────────────────────────────────────────────────────────────────
    @app_commands.command(name="snipe", description="Muestra el último mensaje borrado en este canal.")
    async def cmd_snipe(self, interaction: discord.Interaction):
        msg = self._snipe_cache.get(interaction.channel.id)
        if not msg:
            await interaction.response.send_message(
                "🔍 No hay mensajes recientes borrados en este canal.", ephemeral=True
            )
            return

        embed = discord.Embed(
            description=msg.content or "*[sin texto — puede ser un embed o adjunto]*",
            color=discord.Color.orange(),
            timestamp=msg.created_at,
        )
        embed.set_author(name=str(msg.author), icon_url=msg.author.display_avatar.url)
        embed.set_footer(text=f"Borrado en #{interaction.channel.name}")
        if msg.attachments:
            embed.set_image(url=msg.attachments[0].url)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utilidades(bot))
