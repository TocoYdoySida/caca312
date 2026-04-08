"""
Cog: Red / Tokens
─────────────────
Todos los comandos relacionados con tokens OAuth2 y gestión de red.

━━━ Gestión de tokens ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /tokens-lista        Lista paginada de todos los tokens
  /token-info          Info detallada del token de un usuario
  /tokens-stats        Estadísticas globales
  /tokens-limpiar      Elimina tokens expirados
  /revocar-token       Elimina el token de un usuario concreto

━━━ Unir usuarios a servidores ━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /unir-usuario        Añade un usuario a un servidor
  /unir-todos          Añade todos los verificados a un servidor
  /unir-rol            Añade todos los miembros de un rol a un servidor
  /unir-usuario-red    Añade un usuario a TODOS los servidores del bot

━━━ Mensajes entre servidores ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /mensaje-servidor    Envía un mensaje a un canal de otro servidor
  /anuncio-red         Envía un embed a un canal de otro servidor
  /dm-tokens           DM a todos los usuarios con token válido
  /dm-servidor         DM a usuarios con token que están en un servidor

━━━ Info de red ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /mis-servidores      Lista todos los servidores donde está el bot
  /guilds-usuario      Servidores donde está un usuario (via token)
"""

import asyncio
import math
import time
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

import config
import token_store


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers OAuth2
# ─────────────────────────────────────────────────────────────────────────────

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


async def add_to_guild(user_id: int, guild_id: int) -> tuple[bool, str]:
    """Añade user_id al servidor guild_id usando su token OAuth2."""
    access_token = await _valid_token(user_id)
    if not access_token:
        return False, "Sin token válido."

    headers = {"Authorization": f"Bot {config.TOKEN}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as s:
        async with s.put(
            f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}",
            headers=headers,
            json={"access_token": access_token},
        ) as r:
            status = r.status

    if status == 201: return True,  "✅ Añadido correctamente."
    if status == 204: return True,  "ℹ️ Ya era miembro."
    if status == 403: return False, "❌ Sin permisos (¿está el bot en ese servidor?)."
    if status == 401: return False, "❌ Token inválido. Debe reverificarse."
    return False, f"❌ Error API (HTTP {status})."


async def get_user_guilds(access_token: str) -> list[dict]:
    """Obtiene la lista de servidores de un usuario via su token OAuth2."""
    async with aiohttp.ClientSession() as s:
        async with s.get(
            "https://discord.com/api/v10/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as r:
            if r.status == 200:
                return await r.json()
            return []


# ─────────────────────────────────────────────────────────────────────────────
#  Vista paginada para /tokens-lista
# ─────────────────────────────────────────────────────────────────────────────

class PaginaView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], autor_id: int):
        super().__init__(timeout=120)
        self.pages    = pages
        self.current  = 0
        self.autor_id = autor_id
        self._sync_buttons()

    def _sync_buttons(self):
        self.btn_prev.disabled  = self.current == 0
        self.btn_next.disabled  = self.current == len(self.pages) - 1
        self.btn_first.disabled = self.current == 0
        self.btn_last.disabled  = self.current == len(self.pages) - 1

    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message(
                "Solo quien ejecutó el comando puede navegar.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.gray)
    async def btn_first(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        self.current = 0
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.blurple)
    async def btn_prev(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        self.current -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.blurple)
    async def btn_next(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        self.current += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.gray)
    async def btn_last(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        self.current = len(self.pages) - 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)


def _build_token_pages(
    tokens: dict,
    guild: discord.Guild | None,
    titulo: str,
    color: discord.Color,
    por_pagina: int = 10,
) -> list[discord.Embed]:
    """Convierte el diccionario de tokens en páginas de embed."""
    items = list(tokens.items())
    if not items:
        e = discord.Embed(title=titulo, description="No hay tokens.", color=color)
        return [e]

    ahora  = time.time()
    chunks = [items[i:i + por_pagina] for i in range(0, len(items), por_pagina)]
    pages  = []

    for idx, chunk in enumerate(chunks):
        embed = discord.Embed(
            title=titulo,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        for uid, data in chunk:
            member  = guild.get_member(int(uid)) if guild else None
            mention = member.mention if member else f"<@{uid}>"
            tag     = data.get("username", "Desconocido")
            expira  = data["expires_at"]
            valido  = expira > ahora
            guardado_ts = int(data.get("saved_at", expira - 604800))

            estado = "✅ Válido" if valido else "⏰ Expirado"
            exp_str = f"<t:{int(expira)}:R>"

            embed.add_field(
                name=f"{mention}  •  {tag}",
                value=(
                    f"🪪 ID: `{uid}`\n"
                    f"📅 Guardado: <t:{guardado_ts}:d>\n"
                    f"⏱ Expira: {exp_str}\n"
                    f"Estado: {estado}"
                ),
                inline=True,
            )
        embed.set_footer(text=f"Página {idx + 1}/{len(chunks)}  •  Total: {len(items)} tokens")
        pages.append(embed)

    return pages


# ─────────────────────────────────────────────────────────────────────────────
#  Cog
# ─────────────────────────────────────────────────────────────────────────────

class Red(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ══════════════════════════════════════════════════════════════════════════
    #  GESTIÓN DE TOKENS
    # ══════════════════════════════════════════════════════════════════════════

    # ── /tokens-lista ─────────────────────────────────────────────────────────
    @app_commands.command(name="tokens-lista", description="[Admin] Lista paginada de todos los tokens guardados.")
    @app_commands.describe(solo_validos="Mostrar solo tokens válidos (por defecto muestra todos).")
    @app_commands.checks.has_permissions(administrator=True)
    async def tokens_lista(self, interaction: discord.Interaction, solo_validos: bool = False):
        await interaction.response.defer(ephemeral=True)

        tokens = token_store.get_valid() if solo_validos else token_store.all_users()
        titulo = "🔑 Tokens válidos" if solo_validos else "🔑 Todos los tokens"
        color  = discord.Color.green() if solo_validos else discord.Color.blurple()

        pages = _build_token_pages(tokens, interaction.guild, titulo, color)
        view  = PaginaView(pages, interaction.user.id) if len(pages) > 1 else None
        await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)

    # ── /token-info ───────────────────────────────────────────────────────────
    @app_commands.command(name="token-info", description="[Admin] Información detallada del token de un usuario.")
    @app_commands.describe(usuario="Usuario a consultar.")
    @app_commands.checks.has_permissions(administrator=True)
    async def token_info(self, interaction: discord.Interaction, usuario: discord.Member):
        record = token_store.get_user(usuario.id)
        if not record:
            await interaction.response.send_message(
                f"❌ {usuario.mention} no tiene token guardado.", ephemeral=True
            )
            return

        ahora   = time.time()
        valido  = record["expires_at"] > ahora
        exp_ts  = int(record["expires_at"])
        save_ts = int(record.get("saved_at", record["expires_at"] - 604800))

        embed = discord.Embed(
            title=f"🔑 Token de {usuario.display_name}",
            color=discord.Color.green() if valido else discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.add_field(name="Usuario",    value=f"{usuario.mention}\n`{usuario.id}`",  inline=True)
        embed.add_field(name="Tag",        value=record.get("username", "?"),            inline=True)
        embed.add_field(name="Estado",     value="✅ Válido" if valido else "⏰ Expirado", inline=True)
        embed.add_field(name="Guardado",   value=f"<t:{save_ts}:F>",                    inline=True)
        embed.add_field(name="Expira",     value=f"<t:{exp_ts}:F>\n(<t:{exp_ts}:R>)",  inline=True)
        embed.add_field(
            name="Access Token",
            value=f"||`{record['access_token'][:30]}…`||",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /tokens-stats ─────────────────────────────────────────────────────────
    @app_commands.command(name="tokens-stats", description="[Admin] Estadísticas de todos los tokens.")
    @app_commands.checks.has_permissions(administrator=True)
    async def tokens_stats(self, interaction: discord.Interaction):
        total, validos, expirados = token_store.count()
        pct = round((validos / total * 100) if total else 0)

        barra = "█" * (pct // 10) + "░" * (10 - pct // 10)

        embed = discord.Embed(
            title="📊 Estadísticas de tokens OAuth2",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Total guardados", value=f"**{total}**",    inline=True)
        embed.add_field(name="✅ Válidos",       value=f"**{validos}**",  inline=True)
        embed.add_field(name="⏰ Expirados",     value=f"**{expirados}**", inline=True)
        embed.add_field(
            name=f"Salud  {pct}%",
            value=f"`{barra}`",
            inline=False,
        )
        embed.set_footer(text="Los expirados se refrescan automáticamente al usarlos.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /tokens-limpiar ───────────────────────────────────────────────────────
    @app_commands.command(name="tokens-limpiar", description="[Admin] Elimina todos los tokens expirados.")
    @app_commands.checks.has_permissions(administrator=True)
    async def tokens_limpiar(self, interaction: discord.Interaction):
        eliminados = token_store.clean_expired()
        total, validos, _ = token_store.count()
        await interaction.response.send_message(
            f"🧹 Se eliminaron **{eliminados}** token(s) expirado(s).\n"
            f"Quedan **{total}** tokens (**{validos}** válidos).",
            ephemeral=True,
        )

    # ── /revocar-token ────────────────────────────────────────────────────────
    @app_commands.command(name="revocar-token", description="[Admin] Elimina el token de un usuario.")
    @app_commands.describe(usuario="Usuario cuyo token eliminar.")
    @app_commands.checks.has_permissions(administrator=True)
    async def revocar_token(self, interaction: discord.Interaction, usuario: discord.Member):
        if token_store.remove_user(usuario.id):
            await interaction.response.send_message(
                f"✅ Token de {usuario.mention} eliminado. Deberá reverificarse.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ {usuario.mention} no tiene token guardado.", ephemeral=True
            )

    # ══════════════════════════════════════════════════════════════════════════
    #  UNIR USUARIOS A SERVIDORES
    # ══════════════════════════════════════════════════════════════════════════

    # ── /unir-usuario ─────────────────────────────────────────────────────────
    @app_commands.command(name="unir-usuario", description="[Admin] Añade un usuario verificado a otro servidor.")
    @app_commands.describe(
        usuario="Usuario a añadir.",
        servidor_id="ID del servidor destino.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def unir_usuario(self, interaction: discord.Interaction, usuario: discord.Member, servidor_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(servidor_id)
        except ValueError:
            await interaction.followup.send("❌ ID inválido.", ephemeral=True)
            return

        ok, msg = await add_to_guild(usuario.id, gid)
        embed = discord.Embed(
            title="✅ Éxito" if ok else "❌ Error",
            description=f"**Usuario:** {usuario.mention} (`{usuario.id}`)\n**Servidor:** `{gid}`\n\n{msg}",
            color=discord.Color.green() if ok else discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /unir-todos ───────────────────────────────────────────────────────────
    @app_commands.command(name="unir-todos", description="[Admin] Añade todos los miembros verificados a otro servidor.")
    @app_commands.describe(servidor_id="ID del servidor destino.")
    @app_commands.checks.has_permissions(administrator=True)
    async def unir_todos(self, interaction: discord.Interaction, servidor_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(servidor_id)
        except ValueError:
            await interaction.followup.send("❌ ID inválido.", ephemeral=True)
            return

        guild = self.bot.get_guild(config.GUILD_ID)
        role  = guild.get_role(config.VERIFIED_ROLE_ID) if guild else None
        if not role:
            await interaction.followup.send("❌ Rol verificado no encontrado.", ephemeral=True)
            return

        miembros = [m for m in role.members if not m.bot and token_store.get_user(m.id)]
        if not miembros:
            await interaction.followup.send("⚠️ No hay verificados con token.", ephemeral=True)
            return

        await interaction.followup.send(f"⏳ Procesando **{len(miembros)}** miembros...", ephemeral=True)

        ok = fail = 0
        for m in miembros:
            exito, _ = await add_to_guild(m.id, gid)
            if exito: ok += 1
            else:     fail += 1
            await asyncio.sleep(0.5)

        embed = discord.Embed(
            title="📊 Unir todos — Resumen",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="✅ Añadidos", value=str(ok),   inline=True)
        embed.add_field(name="❌ Errores",  value=str(fail), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /unir-rol ─────────────────────────────────────────────────────────────
    @app_commands.command(name="unir-rol", description="[Admin] Añade todos los miembros de un rol a otro servidor.")
    @app_commands.describe(
        rol="Rol cuyos miembros añadir.",
        servidor_id="ID del servidor destino.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def unir_rol(self, interaction: discord.Interaction, rol: discord.Role, servidor_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(servidor_id)
        except ValueError:
            await interaction.followup.send("❌ ID inválido.", ephemeral=True)
            return

        miembros = [m for m in rol.members if not m.bot and token_store.get_user(m.id)]
        if not miembros:
            await interaction.followup.send(
                f"⚠️ Ningún miembro de {rol.mention} tiene token guardado.", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"⏳ Procesando **{len(miembros)}** miembros de {rol.mention}...", ephemeral=True
        )

        ok = fail = 0
        for m in miembros:
            exito, _ = await add_to_guild(m.id, gid)
            if exito: ok += 1
            else:     fail += 1
            await asyncio.sleep(0.5)

        embed = discord.Embed(
            title=f"📊 Unir rol @{rol.name} — Resumen",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Rol",        value=rol.mention, inline=True)
        embed.add_field(name="✅ Añadidos", value=str(ok),     inline=True)
        embed.add_field(name="❌ Errores",  value=str(fail),   inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /unir-usuario-red ─────────────────────────────────────────────────────
    @app_commands.command(name="unir-usuario-red", description="[Admin] Añade un usuario a TODOS los servidores donde está el bot.")
    @app_commands.describe(usuario="Usuario a añadir en toda la red.")
    @app_commands.checks.has_permissions(administrator=True)
    async def unir_usuario_red(self, interaction: discord.Interaction, usuario: discord.Member):
        await interaction.response.defer(ephemeral=True)

        if not token_store.get_user(usuario.id):
            await interaction.followup.send(
                f"❌ {usuario.mention} no tiene token guardado.", ephemeral=True
            )
            return

        guilds = [g for g in self.bot.guilds if g.id != interaction.guild.id]
        if not guilds:
            await interaction.followup.send("⚠️ El bot no está en ningún otro servidor.", ephemeral=True)
            return

        await interaction.followup.send(
            f"⏳ Añadiendo a **{len(guilds)}** servidores...", ephemeral=True
        )

        resultados = []
        for g in guilds:
            ok, msg = await add_to_guild(usuario.id, g.id)
            resultados.append(f"{'✅' if ok else '❌'} **{g.name}** (`{g.id}`) — {msg}")
            await asyncio.sleep(0.5)

        embed = discord.Embed(
            title=f"🌐 Unir en red — {usuario.display_name}",
            description="\n".join(resultados),
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=usuario.display_avatar.url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ══════════════════════════════════════════════════════════════════════════
    #  MENSAJES ENTRE SERVIDORES
    # ══════════════════════════════════════════════════════════════════════════

    # ── /mensaje-servidor ─────────────────────────────────────────────────────
    @app_commands.command(name="mensaje-servidor", description="[Admin] Envía un mensaje a un canal de otro servidor.")
    @app_commands.describe(
        servidor_id="ID del servidor destino.",
        canal_id="ID del canal destino.",
        texto="Mensaje a enviar (soporta markdown).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def mensaje_servidor(
        self,
        interaction: discord.Interaction,
        servidor_id: str,
        canal_id: str,
        texto: str,
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(servidor_id)
            cid = int(canal_id)
        except ValueError:
            await interaction.followup.send("❌ IDs inválidos.", ephemeral=True)
            return

        guild = self.bot.get_guild(gid)
        if not guild:
            await interaction.followup.send("❌ El bot no está en ese servidor.", ephemeral=True)
            return

        canal = guild.get_channel(cid)
        if not canal or not isinstance(canal, discord.TextChannel):
            await interaction.followup.send("❌ Canal no encontrado o no es de texto.", ephemeral=True)
            return

        try:
            await canal.send(texto)
            await interaction.followup.send(
                f"✅ Mensaje enviado en **{guild.name}** → #{canal.name}", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Sin permisos para escribir en ese canal.", ephemeral=True)

    # ── /anuncio-red ──────────────────────────────────────────────────────────
    @app_commands.command(name="anuncio-red", description="[Admin] Envía un embed de anuncio a un canal de otro servidor.")
    @app_commands.describe(
        servidor_id="ID del servidor destino.",
        canal_id="ID del canal destino.",
        titulo="Título del embed.",
        descripcion="Cuerpo del anuncio.",
        color="Color hex (ej: ff0000). Por defecto azul.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def anuncio_red(
        self,
        interaction: discord.Interaction,
        servidor_id: str,
        canal_id: str,
        titulo: str,
        descripcion: str,
        color: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(servidor_id)
            cid = int(canal_id)
        except ValueError:
            await interaction.followup.send("❌ IDs inválidos.", ephemeral=True)
            return

        guild = self.bot.get_guild(gid)
        if not guild:
            await interaction.followup.send("❌ El bot no está en ese servidor.", ephemeral=True)
            return
        canal = guild.get_channel(cid)
        if not canal or not isinstance(canal, discord.TextChannel):
            await interaction.followup.send("❌ Canal no encontrado.", ephemeral=True)
            return

        try:
            hex_c = int((color or "5865f2").lstrip("#"), 16)
        except ValueError:
            hex_c = 0x5865F2

        embed = discord.Embed(
            title=titulo,
            description=descripcion,
            color=hex_c,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Enviado desde {interaction.guild.name}")

        try:
            await canal.send(embed=embed)
            await interaction.followup.send(
                f"✅ Anuncio enviado en **{guild.name}** → #{canal.name}", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Sin permisos para escribir en ese canal.", ephemeral=True)

    # ── /dm-tokens ────────────────────────────────────────────────────────────
    @app_commands.command(name="dm-tokens", description="[Admin] Envía un DM a todos los usuarios con token válido.")
    @app_commands.describe(
        mensaje="Mensaje a enviar.",
        titulo="Título del embed (opcional, si se omite va como texto).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def dm_tokens(self, interaction: discord.Interaction, mensaje: str, titulo: str | None = None):
        await interaction.response.defer(ephemeral=True)

        validos = token_store.get_valid()
        if not validos:
            await interaction.followup.send("⚠️ No hay tokens válidos.", ephemeral=True)
            return

        await interaction.followup.send(
            f"⏳ Enviando DM a **{len(validos)}** usuarios...", ephemeral=True
        )

        enviados = fallidos = 0
        for uid in validos:
            try:
                user = await self.bot.fetch_user(int(uid))
                if titulo:
                    embed = discord.Embed(
                        title=titulo, description=mensaje,
                        color=discord.Color.blurple(),
                        timestamp=datetime.now(timezone.utc),
                    )
                    await user.send(embed=embed)
                else:
                    await user.send(mensaje)
                enviados += 1
            except Exception:
                fallidos += 1
            await asyncio.sleep(0.5)

        embed_res = discord.Embed(
            title="📨 DM masivo completado",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed_res.add_field(name="✅ Enviados", value=str(enviados), inline=True)
        embed_res.add_field(name="❌ Fallidos", value=str(fallidos), inline=True)
        await interaction.followup.send(embed=embed_res, ephemeral=True)

    # ── /dm-servidor ──────────────────────────────────────────────────────────
    @app_commands.command(name="dm-servidor", description="[Admin] DM a usuarios con token que están en un servidor específico.")
    @app_commands.describe(
        servidor_id="ID del servidor.",
        mensaje="Mensaje a enviar.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def dm_servidor(self, interaction: discord.Interaction, servidor_id: str, mensaje: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(servidor_id)
        except ValueError:
            await interaction.followup.send("❌ ID inválido.", ephemeral=True)
            return

        guild = self.bot.get_guild(gid)
        if not guild:
            await interaction.followup.send("❌ El bot no está en ese servidor.", ephemeral=True)
            return

        # Usuarios con token que están en ese servidor
        ids_en_servidor = {str(m.id) for m in guild.members if not m.bot}
        tokens_validos  = {k: v for k, v in token_store.get_valid().items() if k in ids_en_servidor}

        if not tokens_validos:
            await interaction.followup.send(
                f"⚠️ No hay usuarios con token en **{guild.name}**.", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"⏳ Enviando DM a **{len(tokens_validos)}** usuarios de **{guild.name}**...", ephemeral=True
        )

        enviados = fallidos = 0
        for uid in tokens_validos:
            try:
                user = await self.bot.fetch_user(int(uid))
                await user.send(mensaje)
                enviados += 1
            except Exception:
                fallidos += 1
            await asyncio.sleep(0.5)

        embed = discord.Embed(
            title=f"📨 DM a {guild.name} — Resumen",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="✅ Enviados", value=str(enviados), inline=True)
        embed.add_field(name="❌ Fallidos", value=str(fallidos), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ══════════════════════════════════════════════════════════════════════════
    #  INFO DE RED
    # ══════════════════════════════════════════════════════════════════════════

    # ── /mis-servidores ───────────────────────────────────────────────────────
    @app_commands.command(name="mis-servidores", description="[Admin] Lista todos los servidores donde está el bot.")
    @app_commands.checks.has_permissions(administrator=True)
    async def mis_servidores(self, interaction: discord.Interaction):
        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)

        embed = discord.Embed(
            title=f"🌐 Servidores del bot ({len(guilds)})",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        for g in guilds[:25]:
            embed.add_field(
                name=g.name,
                value=f"🪪 `{g.id}`\n👥 {g.member_count} miembros",
                inline=True,
            )
        if len(guilds) > 25:
            embed.set_footer(text=f"Mostrando 25 de {len(guilds)} servidores.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /guilds-usuario ───────────────────────────────────────────────────────
    @app_commands.command(name="guilds-usuario", description="[Admin] Muestra los servidores donde está un usuario (via su token OAuth2).")
    @app_commands.describe(usuario="Usuario a consultar.")
    @app_commands.checks.has_permissions(administrator=True)
    async def guilds_usuario(self, interaction: discord.Interaction, usuario: discord.Member):
        await interaction.response.defer(ephemeral=True)

        token = await _valid_token(usuario.id)
        if not token:
            await interaction.followup.send(
                f"❌ {usuario.mention} no tiene token válido.", ephemeral=True
            )
            return

        guilds = await get_user_guilds(token)
        if not guilds:
            await interaction.followup.send(
                "⚠️ No se pudieron obtener los servidores (token sin scope `guilds`).", ephemeral=True
            )
            return

        # Marcar cuáles coinciden con servidores donde el bot también está
        bot_guild_ids = {g.id for g in self.bot.guilds}

        embed = discord.Embed(
            title=f"🌐 Servidores de {usuario.display_name} ({len(guilds)})",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=usuario.display_avatar.url)

        for g in guilds[:24]:
            en_bot = "🤖" if int(g["id"]) in bot_guild_ids else ""
            embed.add_field(
                name=f"{g['name']} {en_bot}",
                value=f"`{g['id']}`",
                inline=True,
            )
        if len(guilds) > 24:
            embed.set_footer(text=f"Mostrando 24 de {len(guilds)}. 🤖 = bot también está ahí.")
        else:
            embed.set_footer(text="🤖 = el bot también está en ese servidor.")

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Red(bot))
