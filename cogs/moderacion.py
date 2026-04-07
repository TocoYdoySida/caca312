"""
Cog: Moderacion
───────────────
Comandos: /kick  /ban  /unban  /timeout  /untimeout
          /warn  /warns  /borrar-warn  /clear-warns
          /clear  /lock  /unlock  /slowmode
"""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands
from discord import app_commands


# ── Almacenamiento de advertencias ───────────────────────────────────────────

WARNS_FILE = os.path.join("data", "warns.json")


def _load_warns() -> dict:
    if not os.path.exists(WARNS_FILE):
        return {}
    with open(WARNS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_warns(data: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(WARNS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add_warn(guild_id: int, user_id: int, reason: str, by_name: str, by_id: int) -> dict:
    data = _load_warns()
    gkey = str(guild_id)
    ukey = str(user_id)
    data.setdefault(gkey, {}).setdefault(ukey, [])
    warn = {
        "id":      str(uuid.uuid4())[:8],
        "reason":  reason,
        "by_id":   by_id,
        "by_name": by_name,
        "date":    datetime.now(timezone.utc).isoformat(),
    }
    data[gkey][ukey].append(warn)
    _save_warns(data)
    return warn


def get_warns(guild_id: int, user_id: int) -> list:
    data = _load_warns()
    return data.get(str(guild_id), {}).get(str(user_id), [])


def remove_warn(guild_id: int, user_id: int, warn_id: str) -> bool:
    data = _load_warns()
    gkey, ukey = str(guild_id), str(user_id)
    warns = data.get(gkey, {}).get(ukey, [])
    new   = [w for w in warns if w["id"] != warn_id]
    if len(new) == len(warns):
        return False
    data[gkey][ukey] = new
    _save_warns(data)
    return True


def clear_warns(guild_id: int, user_id: int) -> int:
    data  = _load_warns()
    gkey, ukey = str(guild_id), str(user_id)
    count = len(data.get(gkey, {}).get(ukey, []))
    if gkey in data:
        data[gkey][ukey] = []
    _save_warns(data)
    return count


# ── Cog ───────────────────────────────────────────────────────────────────────

class Moderacion(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /kick ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="kick", description="[Admin] Expulsa a un miembro del servidor.")
    @app_commands.describe(miembro="Miembro a expulsar.", razon="Razón de la expulsión.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def cmd_kick(
        self,
        interaction: discord.Interaction,
        miembro: discord.Member,
        razon: str = "Sin razón especificada",
    ):
        if miembro.top_role >= interaction.user.top_role:
            await interaction.response.send_message(
                "❌ No puedes expulsar a alguien con igual o mayor rango.", ephemeral=True
            )
            return
        try:
            await miembro.send(
                f"Has sido **expulsado** de **{interaction.guild.name}**.\n📋 Razón: {razon}"
            )
        except discord.Forbidden:
            pass
        await miembro.kick(reason=razon)
        embed = discord.Embed(
            title="👢 Miembro expulsado",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=f"{miembro} (`{miembro.id}`)", inline=True)
        embed.add_field(name="Razón",   value=razon,                          inline=True)
        embed.add_field(name="Por",     value=interaction.user.mention,       inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /ban ──────────────────────────────────────────────────────────────────
    @app_commands.command(name="ban", description="[Admin] Banea a un miembro del servidor.")
    @app_commands.describe(
        miembro="Miembro a banear.",
        razon="Razón del baneo.",
        borrar_mensajes="Días de mensajes a borrar (0-7).",
    )
    @app_commands.checks.has_permissions(ban_members=True)
    async def cmd_ban(
        self,
        interaction: discord.Interaction,
        miembro: discord.Member,
        razon: str = "Sin razón especificada",
        borrar_mensajes: app_commands.Range[int, 0, 7] = 0,
    ):
        if miembro.top_role >= interaction.user.top_role:
            await interaction.response.send_message(
                "❌ No puedes banear a alguien con igual o mayor rango.", ephemeral=True
            )
            return
        try:
            await miembro.send(
                f"Has sido **baneado** de **{interaction.guild.name}**.\n📋 Razón: {razon}"
            )
        except discord.Forbidden:
            pass
        await miembro.ban(reason=razon, delete_message_days=borrar_mensajes)
        embed = discord.Embed(
            title="🔨 Miembro baneado",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=f"{miembro} (`{miembro.id}`)", inline=True)
        embed.add_field(name="Razón",   value=razon,                          inline=True)
        embed.add_field(name="Por",     value=interaction.user.mention,       inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /unban ────────────────────────────────────────────────────────────────
    @app_commands.command(name="unban", description="[Admin] Desbanea un usuario por su ID.")
    @app_commands.describe(user_id="ID del usuario a desbanear.", razon="Razón.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def cmd_unban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        razon: str = "Sin razón especificada",
    ):
        await interaction.response.defer()
        try:
            uid  = int(user_id)
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=razon)
            embed = discord.Embed(
                title="✅ Usuario desbaneado",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Usuario", value=f"{user} (`{uid}`)",   inline=True)
            embed.add_field(name="Razón",   value=razon,                  inline=True)
            embed.add_field(name="Por",     value=interaction.user.mention, inline=True)
            await interaction.followup.send(embed=embed)
        except discord.NotFound:
            await interaction.followup.send("❌ Usuario no encontrado en la lista de baneo.")
        except ValueError:
            await interaction.followup.send("❌ ID inválido.")

    # ── /timeout ──────────────────────────────────────────────────────────────
    @app_commands.command(name="timeout", description="[Admin] Silencia a un miembro temporalmente.")
    @app_commands.describe(
        miembro="Miembro a silenciar.",
        minutos="Duración en minutos (máx. 40320 = 28 días).",
        razon="Razón.",
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def cmd_timeout(
        self,
        interaction: discord.Interaction,
        miembro: discord.Member,
        minutos: app_commands.Range[int, 1, 40320],
        razon: str = "Sin razón especificada",
    ):
        until = discord.utils.utcnow() + timedelta(minutes=minutos)
        await miembro.timeout(until, reason=razon)
        embed = discord.Embed(
            title="🔇 Timeout aplicado",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario",   value=miembro.mention,          inline=True)
        embed.add_field(name="Duración",  value=f"{minutos} min",          inline=True)
        embed.add_field(name="Razón",     value=razon,                     inline=True)
        embed.add_field(name="Expira",    value=f"<t:{int(until.timestamp())}:R>", inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /untimeout ────────────────────────────────────────────────────────────
    @app_commands.command(name="untimeout", description="[Admin] Elimina el timeout de un miembro.")
    @app_commands.describe(miembro="Miembro.", razon="Razón.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def cmd_untimeout(
        self,
        interaction: discord.Interaction,
        miembro: discord.Member,
        razon: str = "Sin razón especificada",
    ):
        await miembro.timeout(None, reason=razon)
        await interaction.response.send_message(
            f"✅ Timeout eliminado para {miembro.mention}.", ephemeral=True
        )

    # ── /warn ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="warn", description="[Admin] Advierte a un miembro.")
    @app_commands.describe(miembro="Miembro a advertir.", razon="Razón de la advertencia.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def cmd_warn(
        self,
        interaction: discord.Interaction,
        miembro: discord.Member,
        razon: str,
    ):
        warn = add_warn(interaction.guild.id, miembro.id, razon,
                        str(interaction.user), interaction.user.id)
        total = len(get_warns(interaction.guild.id, miembro.id))

        embed = discord.Embed(
            title="⚠️ Advertencia registrada",
            color=discord.Color.yellow(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario",  value=miembro.mention,      inline=True)
        embed.add_field(name="Razón",    value=razon,                 inline=True)
        embed.add_field(name="Por",      value=interaction.user.mention, inline=True)
        embed.add_field(name="ID warn",  value=f"`{warn['id']}`",     inline=True)
        embed.add_field(name="Total",    value=f"{total} advertencia(s)", inline=True)
        await interaction.response.send_message(embed=embed)

        try:
            await miembro.send(
                f"⚠️ Has recibido una advertencia en **{interaction.guild.name}**.\n"
                f"📋 Razón: {razon}\n"
                f"Total de advertencias: {total}"
            )
        except discord.Forbidden:
            pass

    # ── /warns ────────────────────────────────────────────────────────────────
    @app_commands.command(name="warns", description="Muestra las advertencias de un miembro.")
    @app_commands.describe(miembro="Miembro a consultar.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def cmd_warns(self, interaction: discord.Interaction, miembro: discord.Member):
        lista = get_warns(interaction.guild.id, miembro.id)
        if not lista:
            await interaction.response.send_message(
                f"✅ {miembro.mention} no tiene advertencias.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"⚠️ Advertencias de {miembro.display_name}",
            color=discord.Color.yellow(),
        )
        for w in lista:
            ts = datetime.fromisoformat(w["date"])
            embed.add_field(
                name=f"ID `{w['id']}` — {ts.strftime('%d/%m/%Y %H:%M')}",
                value=f"📋 {w['reason']}\n👮 Por: <@{w['by_id']}>",
                inline=False,
            )
        embed.set_footer(text=f"Total: {len(lista)} advertencia(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /borrar-warn ──────────────────────────────────────────────────────────
    @app_commands.command(name="borrar-warn", description="[Admin] Elimina una advertencia por su ID.")
    @app_commands.describe(miembro="Miembro.", warn_id="ID de la advertencia (ej: a1b2c3d4).")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def cmd_borrar_warn(
        self,
        interaction: discord.Interaction,
        miembro: discord.Member,
        warn_id: str,
    ):
        ok = remove_warn(interaction.guild.id, miembro.id, warn_id)
        if ok:
            await interaction.response.send_message(
                f"✅ Advertencia `{warn_id}` eliminada para {miembro.mention}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ No se encontró la advertencia `{warn_id}`.", ephemeral=True
            )

    # ── /clear-warns ──────────────────────────────────────────────────────────
    @app_commands.command(name="clear-warns", description="[Admin] Borra todas las advertencias de un miembro.")
    @app_commands.describe(miembro="Miembro.")
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_clear_warns(self, interaction: discord.Interaction, miembro: discord.Member):
        n = clear_warns(interaction.guild.id, miembro.id)
        await interaction.response.send_message(
            f"✅ Se eliminaron **{n}** advertencia(s) de {miembro.mention}.", ephemeral=True
        )

    # ── /clear ────────────────────────────────────────────────────────────────
    @app_commands.command(name="clear", description="[Admin] Borra mensajes del canal actual.")
    @app_commands.describe(
        cantidad="Número de mensajes a borrar (1-100).",
        usuario="Borrar solo mensajes de este usuario (opcional).",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def cmd_clear(
        self,
        interaction: discord.Interaction,
        cantidad: app_commands.Range[int, 1, 100],
        usuario: discord.Member | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        def check(m: discord.Message) -> bool:
            return usuario is None or m.author == usuario

        borrados = await interaction.channel.purge(limit=cantidad, check=check)
        await interaction.followup.send(
            f"🗑️ {len(borrados)} mensaje(s) eliminado(s){f' de {usuario.mention}' if usuario else ''}.",
            ephemeral=True,
        )

    # ── /lock ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="lock", description="[Admin] Bloquea el canal para @everyone.")
    @app_commands.describe(
        canal="Canal a bloquear (por defecto, el actual).",
        razon="Razón.",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def cmd_lock(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
        razon: str = "Sin razón especificada",
    ):
        target = canal or interaction.channel
        everyone = interaction.guild.default_role
        await target.set_permissions(everyone, send_messages=False, reason=razon)
        embed = discord.Embed(
            title="🔒 Canal bloqueado",
            description=f"{target.mention} ha sido bloqueado.\n📋 Razón: {razon}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        await interaction.response.send_message(embed=embed)

    # ── /unlock ───────────────────────────────────────────────────────────────
    @app_commands.command(name="unlock", description="[Admin] Desbloquea el canal para @everyone.")
    @app_commands.describe(
        canal="Canal a desbloquear (por defecto, el actual).",
        razon="Razón.",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def cmd_unlock(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
        razon: str = "Sin razón especificada",
    ):
        target = canal or interaction.channel
        everyone = interaction.guild.default_role
        await target.set_permissions(everyone, send_messages=True, reason=razon)
        embed = discord.Embed(
            title="🔓 Canal desbloqueado",
            description=f"{target.mention} ha sido desbloqueado.\n📋 Razón: {razon}",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        await interaction.response.send_message(embed=embed)

    # ── /slowmode ─────────────────────────────────────────────────────────────
    @app_commands.command(name="slowmode", description="[Admin] Activa o desactiva el modo lento en un canal.")
    @app_commands.describe(
        segundos="Segundos entre mensajes (0 = desactivar, máx. 21600).",
        canal="Canal (por defecto, el actual).",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def cmd_slowmode(
        self,
        interaction: discord.Interaction,
        segundos: app_commands.Range[int, 0, 21600],
        canal: discord.TextChannel | None = None,
    ):
        target = canal or interaction.channel
        await target.edit(slowmode_delay=segundos)
        if segundos == 0:
            msg = f"✅ Modo lento **desactivado** en {target.mention}."
        else:
            msg = f"🐢 Modo lento de **{segundos}s** activado en {target.mention}."
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderacion(bot))
