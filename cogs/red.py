"""
Cog: Red / Tokens
─────────────────
Gestión profesional de tokens OAuth2 y red de servidores.

━━━ Gestión de tokens ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /tokens-lista        Lista paginada con detalles completos
  /token-info          Info detallada de un usuario
  /tokens-stats        Estadísticas con barra de salud
  /tokens-limpiar      Elimina tokens expirados
  /revocar-token       Elimina token de un usuario

━━━ Unir a servidores ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /unir-usuario        Añade un usuario a un servidor
  /unir-todos          Añade todos los verificados (con confirmación)
  /unir-rol            Añade todos los de un rol (con confirmación)
  /unir-usuario-red    Añade un usuario a TODA la red
  /sincronizar-red     Sincroniza todos los tokens a todos los servidores

━━━ Mensajes entre servidores ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /mensaje-servidor    Mensaje de texto a otro servidor
  /anuncio-red         Embed a otro servidor
  /dm-tokens           DM masivo a todos con token válido
  /dm-servidor         DM a usuarios con token en un servidor concreto

━━━ Info de red ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /mis-servidores      Todos los servidores del bot
  /guilds-usuario      Servidores donde está un usuario (vía token)
  /mapa-tokens         Cuántos tokens hay por servidor
  /exportar-tokens     Exporta la lista a un fichero .txt
"""

import asyncio
import io
import logging
import time
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

import config
import token_store

log = logging.getLogger("bot.red")

# ─────────────────────────────────────────────────────────────────────────────
#  Utilidades de progreso y UI
# ─────────────────────────────────────────────────────────────────────────────

def _barra(done: int, total: int, ancho: int = 20) -> str:
    if total == 0:
        return "░" * ancho
    filled = int(done / total * ancho)
    return "█" * filled + "░" * (ancho - filled)


def _embed_progreso(done: int, total: int, titulo: str, detalle: str = "") -> discord.Embed:
    pct   = int(done / total * 100) if total else 100
    barra = _barra(done, total)
    embed = discord.Embed(title=titulo, color=discord.Color.blurple())
    embed.add_field(
        name=f"Progreso — {pct}%",
        value=f"`{barra}` {done}/{total}\n{detalle}",
        inline=False,
    )
    return embed


class ConfirmarView(discord.ui.View):
    """Botones Confirmar / Cancelar para operaciones peligrosas."""

    def __init__(self, autor_id: int):
        super().__init__(timeout=30)
        self.autor_id  = autor_id
        self.confirmed: bool | None = None

    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message(
                "Solo quien ejecutó el comando puede confirmar.", ephemeral=True
            )
            return False
        return True

    def _deshabilitar(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="⚠️ Confirmar", style=discord.ButtonStyle.danger)
    async def btn_confirmar(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        self.confirmed = True
        self._deshabilitar()
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="✖ Cancelar", style=discord.ButtonStyle.secondary)
    async def btn_cancelar(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        self.confirmed = False
        self._deshabilitar()
        await interaction.response.edit_message(
            content="❌ Operación cancelada.", embed=None, view=self
        )
        self.stop()

    async def on_timeout(self):
        self.confirmed = False
        self.stop()


class PaginaView(discord.ui.View):
    """Navegación paginada para listas largas."""

    def __init__(self, pages: list[discord.Embed], autor_id: int):
        super().__init__(timeout=120)
        self.pages    = pages
        self.current  = 0
        self.autor_id = autor_id
        self._sync()

    def _sync(self):
        self.btn_first.disabled = self.current == 0
        self.btn_prev.disabled  = self.current == 0
        self.btn_next.disabled  = self.current == len(self.pages) - 1
        self.btn_last.disabled  = self.current == len(self.pages) - 1

    async def _check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.autor_id:
            await i.response.send_message("Solo quien ejecutó el comando puede navegar.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.secondary)
    async def btn_first(self, i: discord.Interaction, _):
        if not await self._check(i): return
        self.current = 0; self._sync()
        await i.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.primary)
    async def btn_prev(self, i: discord.Interaction, _):
        if not await self._check(i): return
        self.current -= 1; self._sync()
        await i.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary)
    async def btn_next(self, i: discord.Interaction, _):
        if not await self._check(i): return
        self.current += 1; self._sync()
        await i.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary)
    async def btn_last(self, i: discord.Interaction, _):
        if not await self._check(i): return
        self.current = len(self.pages) - 1; self._sync()
        await i.response.edit_message(embed=self.pages[self.current], view=self)


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
        log.error(f"Error de red al refrescar token de {user_id}: {e}")
        return None


async def _valid_token(user_id: int) -> str | None:
    record = token_store.get_user(user_id)
    if not record:
        return None
    if time.time() >= record["expires_at"] - 300:
        return await _refresh(user_id)
    return record["access_token"]


async def add_to_guild(
    user_id: int,
    guild_id: int,
    *,
    session: aiohttp.ClientSession | None = None,
    max_retries: int = 3,
) -> tuple[bool, str]:
    """
    Añade user_id al servidor guild_id.
    Maneja rate limits automáticamente con reintentos.
    """
    access_token = await _valid_token(user_id)
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
                        log.warning(f"Rate limit en guild_add. Esperando {retry_wait:.1f}s")
                        await asyncio.sleep(retry_wait)
                        continue
                    if r.status == 201: return True,  "✅ Añadido correctamente."
                    if r.status == 204: return True,  "ℹ️ Ya era miembro."
                    if r.status == 403: return False, "❌ Sin permisos (¿está el bot en ese servidor?)."
                    if r.status == 401: return False, "❌ Token inválido. Debe reverificarse."
                    if r.status == 404: return False, "❌ Servidor no encontrado."
                    return False, f"❌ API error HTTP {r.status}."
            except aiohttp.ClientError as e:
                log.warning(f"Error de red en guild_add (intento {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        return False, "❌ Falló tras varios intentos (error de red)."
    finally:
        if own_session:
            await s.close()


async def get_user_guilds(access_token: str) -> list[dict]:
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


# ─────────────────────────────────────────────────────────────────────────────
#  Páginas de tokens
# ─────────────────────────────────────────────────────────────────────────────

def _token_pages(
    tokens: dict,
    guild: discord.Guild | None,
    titulo: str,
    color: discord.Color,
    por_pagina: int = 9,
) -> list[discord.Embed]:
    items = list(tokens.items())
    if not items:
        return [discord.Embed(title=titulo, description="No hay tokens.", color=color)]

    ahora  = time.time()
    chunks = [items[i:i + por_pagina] for i in range(0, len(items), por_pagina)]
    pages  = []

    for idx, chunk in enumerate(chunks):
        embed = discord.Embed(title=titulo, color=color, timestamp=datetime.now(timezone.utc))
        for uid, data in chunk:
            member   = guild.get_member(int(uid)) if guild else None
            mention  = member.mention if member else f"<@{uid}>"
            tag      = data.get("username", "Desconocido")
            valido   = data["expires_at"] > ahora
            exp_ts   = int(data["expires_at"])
            save_ts  = int(data.get("saved_at", data["expires_at"] - 604800))
            estado   = "✅" if valido else "⏰"
            embed.add_field(
                name=f"{estado} {tag}",
                value=(
                    f"{mention}\n"
                    f"🪪 `{uid}`\n"
                    f"💾 <t:{save_ts}:d>\n"
                    f"⏱ <t:{exp_ts}:R>"
                ),
                inline=True,
            )
        embed.set_footer(text=f"Página {idx+1}/{len(chunks)}  •  {len(items)} tokens en total")
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

    @app_commands.command(name="tokens-lista", description="[Admin] Lista paginada de todos los tokens.")
    @app_commands.describe(solo_validos="Mostrar solo tokens válidos.")
    @app_commands.checks.has_permissions(administrator=True)
    async def tokens_lista(self, interaction: discord.Interaction, solo_validos: bool = False):
        await interaction.response.defer(ephemeral=True)
        tokens = token_store.get_valid() if solo_validos else token_store.all_users()
        titulo = "🔑 Tokens válidos" if solo_validos else "🔑 Todos los tokens"
        color  = discord.Color.green() if solo_validos else discord.Color.blurple()
        pages  = _token_pages(tokens, interaction.guild, titulo, color)
        view   = PaginaView(pages, interaction.user.id) if len(pages) > 1 else None
        await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)

    @app_commands.command(name="token-info", description="[Admin] Info detallada del token de un usuario.")
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
        embed.add_field(name="Usuario",  value=f"{usuario.mention}\n`{usuario.id}`",     inline=True)
        embed.add_field(name="Tag",      value=record.get("username", "?"),               inline=True)
        embed.add_field(name="Estado",   value="✅ Válido" if valido else "⏰ Expirado",  inline=True)
        embed.add_field(name="Guardado", value=f"<t:{save_ts}:F>",                        inline=True)
        embed.add_field(name="Expira",   value=f"<t:{exp_ts}:F>\n<t:{exp_ts}:R>",        inline=True)
        embed.add_field(
            name="Access Token (oculto)",
            value=f"||`{record['access_token'][:35]}…`||",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="tokens-stats", description="[Admin] Estadísticas de todos los tokens.")
    @app_commands.checks.has_permissions(administrator=True)
    async def tokens_stats(self, interaction: discord.Interaction):
        total, validos, expirados = token_store.count()
        pct   = int(validos / total * 100) if total else 0
        barra = _barra(validos, total)

        embed = discord.Embed(
            title="📊 Estadísticas de tokens OAuth2",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Total",      value=f"**{total}**",     inline=True)
        embed.add_field(name="✅ Válidos",  value=f"**{validos}**",  inline=True)
        embed.add_field(name="⏰ Expirados", value=f"**{expirados}**", inline=True)
        embed.add_field(
            name=f"Salud de la red — {pct}%",
            value=f"`{barra}`",
            inline=False,
        )
        embed.set_footer(text="Los expirados se refrescan automáticamente al usarlos.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="tokens-limpiar", description="[Admin] Elimina todos los tokens expirados.")
    @app_commands.checks.has_permissions(administrator=True)
    async def tokens_limpiar(self, interaction: discord.Interaction):
        eliminados = token_store.clean_expired()
        total, validos, _ = token_store.count()
        color = discord.Color.green() if eliminados > 0 else discord.Color.greyple()
        embed = discord.Embed(
            title="🧹 Limpieza completada",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Eliminados",     value=str(eliminados), inline=True)
        embed.add_field(name="Quedan (total)",  value=str(total),      inline=True)
        embed.add_field(name="Quedan (válidos)", value=str(validos),   inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="revocar-token", description="[Admin] Elimina el token de un usuario.")
    @app_commands.describe(usuario="Usuario cuyo token eliminar.")
    @app_commands.checks.has_permissions(administrator=True)
    async def revocar_token(self, interaction: discord.Interaction, usuario: discord.Member):
        if token_store.remove_user(usuario.id):
            log.info(f"Token revocado: {usuario} ({usuario.id}) por {interaction.user}")
            await interaction.response.send_message(
                f"✅ Token de {usuario.mention} eliminado. Deberá reverificarse.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ {usuario.mention} no tiene token guardado.", ephemeral=True
            )

    @app_commands.command(name="exportar-tokens", description="[Admin] Exporta todos los tokens a un archivo .txt.")
    @app_commands.checks.has_permissions(administrator=True)
    async def exportar_tokens(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        tokens = token_store.all_users()
        if not tokens:
            await interaction.followup.send("⚠️ No hay tokens guardados.", ephemeral=True)
            return

        ahora  = time.time()
        lineas = [
            "═" * 60,
            f"  EXPORT DE TOKENS — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Total: {len(tokens)} tokens",
            "═" * 60,
            "",
        ]
        for uid, data in tokens.items():
            estado = "VÁLIDO" if data["expires_at"] > ahora else "EXPIRADO"
            exp    = datetime.fromtimestamp(data["expires_at"]).strftime("%Y-%m-%d %H:%M")
            saved  = datetime.fromtimestamp(data.get("saved_at", 0)).strftime("%Y-%m-%d %H:%M")
            lineas += [
                f"Usuario  : {data.get('username', '?')} (ID: {uid})",
                f"Estado   : {estado}",
                f"Guardado : {saved}",
                f"Expira   : {exp}",
                f"Token    : {data['access_token'][:40]}...",
                "─" * 60,
            ]

        contenido = "\n".join(lineas).encode("utf-8")
        archivo   = discord.File(io.BytesIO(contenido), filename="tokens_export.txt")
        await interaction.followup.send(
            f"📄 Export de **{len(tokens)}** tokens:", file=archivo, ephemeral=True
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  UNIR A SERVIDORES
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="unir-usuario", description="[Admin] Añade un usuario verificado a otro servidor.")
    @app_commands.describe(usuario="Usuario.", servidor_id="ID del servidor destino.")
    @app_commands.checks.has_permissions(administrator=True)
    async def unir_usuario(self, interaction: discord.Interaction, usuario: discord.Member, servidor_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(servidor_id)
        except ValueError:
            await interaction.followup.send("❌ ID de servidor inválido.", ephemeral=True)
            return

        ok, msg = await add_to_guild(usuario.id, gid)
        log.info(f"unir-usuario: {usuario} → {gid} — {'OK' if ok else 'FAIL'}: {msg}")
        embed = discord.Embed(
            title="✅ Éxito" if ok else "❌ Error",
            description=f"**Usuario:** {usuario.mention} (`{usuario.id}`)\n**Servidor:** `{gid}`\n\n{msg}",
            color=discord.Color.green() if ok else discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="unir-todos", description="[Admin] Añade todos los verificados a otro servidor.")
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
            await interaction.followup.send("❌ Rol verificado no encontrado.", ephemeral=True)
            return

        miembros = [m for m in role.members if not m.bot and token_store.get_user(m.id)]
        if not miembros:
            await interaction.followup.send("⚠️ Ningún verificado tiene token.", ephemeral=True)
            return

        # Confirmación
        embed_confirm = discord.Embed(
            title="⚠️ Confirmar operación masiva",
            description=(
                f"Se van a añadir **{len(miembros)} usuarios** al servidor `{gid}`.\n\n"
                "Esta acción no se puede deshacer."
            ),
            color=discord.Color.orange(),
        )
        view = ConfirmarView(interaction.user.id)
        await interaction.followup.send(embed=embed_confirm, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            return

        # Progreso
        progress = await interaction.followup.send(
            embed=_embed_progreso(0, len(miembros), "⏳ Añadiendo usuarios..."),
            ephemeral=True,
        )
        ok = fail = 0
        async with aiohttp.ClientSession() as session:
            for i, m in enumerate(miembros):
                exito, _ = await add_to_guild(m.id, gid, session=session)
                if exito: ok += 1
                else:     fail += 1
                if i % 5 == 0 or i == len(miembros) - 1:
                    await progress.edit(
                        embed=_embed_progreso(i + 1, len(miembros), "⏳ Añadiendo usuarios...",
                                             f"✅ {ok}  ❌ {fail}")
                    )
                await asyncio.sleep(0.5)

        log.info(f"unir-todos → {gid}: {ok} OK, {fail} errores")
        embed_res = discord.Embed(
            title="📊 Operación completada",
            color=discord.Color.green() if fail == 0 else discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed_res.add_field(name="✅ Añadidos", value=str(ok),   inline=True)
        embed_res.add_field(name="❌ Errores",  value=str(fail), inline=True)
        await interaction.followup.send(embed=embed_res, ephemeral=True)

    @app_commands.command(name="unir-rol", description="[Admin] Añade todos los de un rol a otro servidor.")
    @app_commands.describe(rol="Rol.", servidor_id="ID del servidor destino.")
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
                f"⚠️ Ningún miembro de {rol.mention} tiene token.", ephemeral=True
            )
            return

        embed_confirm = discord.Embed(
            title="⚠️ Confirmar operación masiva",
            description=f"Se van a añadir **{len(miembros)} miembros** de {rol.mention} al servidor `{gid}`.",
            color=discord.Color.orange(),
        )
        view = ConfirmarView(interaction.user.id)
        await interaction.followup.send(embed=embed_confirm, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            return

        progress = await interaction.followup.send(
            embed=_embed_progreso(0, len(miembros), f"⏳ Procesando rol @{rol.name}..."),
            ephemeral=True,
        )
        ok = fail = 0
        async with aiohttp.ClientSession() as session:
            for i, m in enumerate(miembros):
                exito, _ = await add_to_guild(m.id, gid, session=session)
                if exito: ok += 1
                else:     fail += 1
                if i % 5 == 0 or i == len(miembros) - 1:
                    await progress.edit(
                        embed=_embed_progreso(i + 1, len(miembros), f"⏳ Procesando rol @{rol.name}...",
                                             f"✅ {ok}  ❌ {fail}")
                    )
                await asyncio.sleep(0.5)

        await interaction.followup.send(
            embed=discord.Embed(
                title="📊 Completado",
                description=f"Rol: {rol.mention}\n✅ {ok} añadidos  ❌ {fail} errores",
                color=discord.Color.green() if fail == 0 else discord.Color.orange(),
                timestamp=datetime.now(timezone.utc),
            ),
            ephemeral=True,
        )

    @app_commands.command(name="unir-usuario-red", description="[Admin] Añade un usuario a TODOS los servidores del bot.")
    @app_commands.describe(usuario="Usuario.")
    @app_commands.checks.has_permissions(administrator=True)
    async def unir_usuario_red(self, interaction: discord.Interaction, usuario: discord.Member):
        await interaction.response.defer(ephemeral=True)
        if not token_store.get_user(usuario.id):
            await interaction.followup.send(f"❌ {usuario.mention} no tiene token.", ephemeral=True)
            return

        guilds = [g for g in self.bot.guilds if g.id != interaction.guild.id]
        if not guilds:
            await interaction.followup.send("⚠️ El bot no está en otros servidores.", ephemeral=True)
            return

        progress = await interaction.followup.send(
            embed=_embed_progreso(0, len(guilds), f"⏳ Añadiendo {usuario.display_name} a la red..."),
            ephemeral=True,
        )
        resultados = []
        async with aiohttp.ClientSession() as session:
            for i, g in enumerate(guilds):
                ok, msg = await add_to_guild(usuario.id, g.id, session=session)
                icon = "✅" if ok else "❌"
                resultados.append(f"{icon} **{g.name}** — {msg}")
                if i % 3 == 0 or i == len(guilds) - 1:
                    await progress.edit(
                        embed=_embed_progreso(i + 1, len(guilds),
                                             f"⏳ Añadiendo a la red...", f"{i+1}/{len(guilds)}")
                    )
                await asyncio.sleep(0.5)

        embed = discord.Embed(
            title=f"🌐 {usuario.display_name} — Resultado en red",
            description="\n".join(resultados),
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=usuario.display_avatar.url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="sincronizar-red", description="[Admin] Añade TODOS los tokens a TODOS los servidores del bot.")
    @app_commands.checks.has_permissions(administrator=True)
    async def sincronizar_red(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        tokens  = token_store.get_valid()
        guilds  = [g for g in self.bot.guilds if g.id != interaction.guild.id]

        if not tokens:
            await interaction.followup.send("⚠️ No hay tokens válidos.", ephemeral=True)
            return
        if not guilds:
            await interaction.followup.send("⚠️ El bot no está en otros servidores.", ephemeral=True)
            return

        total_ops = len(tokens) * len(guilds)
        embed_confirm = discord.Embed(
            title="⚠️ Operación masiva — SINCRONIZAR RED",
            description=(
                f"Se van a realizar **{total_ops} operaciones**:\n"
                f"• **{len(tokens)}** usuarios con token\n"
                f"• **{len(guilds)}** servidores destino\n\n"
                "⚠️ Esta es la operación más intensa. ¿Confirmar?"
            ),
            color=discord.Color.red(),
        )
        view = ConfirmarView(interaction.user.id)
        await interaction.followup.send(embed=embed_confirm, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            return

        progress = await interaction.followup.send(
            embed=_embed_progreso(0, total_ops, "⏳ Sincronizando red..."),
            ephemeral=True,
        )
        ok = fail = sin_token = done = 0
        async with aiohttp.ClientSession() as session:
            for uid in tokens:
                for g in guilds:
                    exito, _ = await add_to_guild(int(uid), g.id, session=session)
                    if exito: ok += 1
                    else:     fail += 1
                    done += 1
                    if done % 10 == 0 or done == total_ops:
                        await progress.edit(
                            embed=_embed_progreso(done, total_ops, "⏳ Sincronizando red...",
                                                 f"✅ {ok}  ❌ {fail}")
                        )
                    await asyncio.sleep(0.5)

        log.info(f"sincronizar-red: {ok} OK, {fail} errores, {total_ops} ops totales")
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Sincronización completada",
                description=(
                    f"**Operaciones:** {total_ops}\n"
                    f"✅ Exitosas: {ok}\n"
                    f"❌ Errores: {fail}"
                ),
                color=discord.Color.green() if fail == 0 else discord.Color.orange(),
                timestamp=datetime.now(timezone.utc),
            ),
            ephemeral=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  MENSAJES ENTRE SERVIDORES
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="mensaje-servidor", description="[Admin] Envía un mensaje a un canal de otro servidor.")
    @app_commands.describe(servidor_id="ID servidor.", canal_id="ID canal.", texto="Mensaje.")
    @app_commands.checks.has_permissions(administrator=True)
    async def mensaje_servidor(self, interaction: discord.Interaction,
                                servidor_id: str, canal_id: str, texto: str):
        await interaction.response.defer(ephemeral=True)
        try:
            guild = self.bot.get_guild(int(servidor_id))
            canal = guild.get_channel(int(canal_id)) if guild else None
        except ValueError:
            await interaction.followup.send("❌ IDs inválidos.", ephemeral=True)
            return

        if not guild:
            await interaction.followup.send("❌ El bot no está en ese servidor.", ephemeral=True)
            return
        if not canal or not isinstance(canal, discord.TextChannel):
            await interaction.followup.send("❌ Canal no encontrado o no es de texto.", ephemeral=True)
            return

        try:
            await canal.send(texto)
            await interaction.followup.send(
                f"✅ Mensaje enviado en **{guild.name}** → `#{canal.name}`", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Sin permisos para escribir en ese canal.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Error Discord: {e}", ephemeral=True)

    @app_commands.command(name="anuncio-red", description="[Admin] Envía un embed a un canal de otro servidor.")
    @app_commands.describe(servidor_id="ID servidor.", canal_id="ID canal.",
                           titulo="Título.", descripcion="Descripción.", color="Color hex (opcional).")
    @app_commands.checks.has_permissions(administrator=True)
    async def anuncio_red(self, interaction: discord.Interaction,
                          servidor_id: str, canal_id: str,
                          titulo: str, descripcion: str, color: str | None = None):
        await interaction.response.defer(ephemeral=True)
        try:
            guild = self.bot.get_guild(int(servidor_id))
            canal = guild.get_channel(int(canal_id)) if guild else None
        except ValueError:
            await interaction.followup.send("❌ IDs inválidos.", ephemeral=True)
            return

        if not guild:
            await interaction.followup.send("❌ Bot no está en ese servidor.", ephemeral=True)
            return
        if not canal or not isinstance(canal, discord.TextChannel):
            await interaction.followup.send("❌ Canal no encontrado.", ephemeral=True)
            return

        try:
            hex_c = int((color or "5865f2").lstrip("#"), 16)
        except ValueError:
            hex_c = 0x5865F2

        embed = discord.Embed(
            title=titulo, description=descripcion, color=hex_c,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Enviado desde {interaction.guild.name}")

        try:
            await canal.send(embed=embed)
            await interaction.followup.send(
                f"✅ Anuncio enviado en **{guild.name}** → `#{canal.name}`", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Sin permisos para escribir.", ephemeral=True)

    @app_commands.command(name="dm-tokens", description="[Admin] DM a todos los usuarios con token válido.")
    @app_commands.describe(mensaje="Mensaje.", titulo="Título del embed (opcional).")
    @app_commands.checks.has_permissions(administrator=True)
    async def dm_tokens(self, interaction: discord.Interaction, mensaje: str, titulo: str | None = None):
        await interaction.response.defer(ephemeral=True)
        validos = token_store.get_valid()
        if not validos:
            await interaction.followup.send("⚠️ No hay tokens válidos.", ephemeral=True)
            return

        view = ConfirmarView(interaction.user.id)
        await interaction.followup.send(
            embed=discord.Embed(
                title="⚠️ DM masivo",
                description=f"Se enviará un DM a **{len(validos)} usuarios**. ¿Confirmar?",
                color=discord.Color.orange(),
            ),
            view=view, ephemeral=True,
        )
        await view.wait()
        if not view.confirmed:
            return

        progress = await interaction.followup.send(
            embed=_embed_progreso(0, len(validos), "⏳ Enviando DMs..."),
            ephemeral=True,
        )
        enviados = fallidos = 0
        uids = list(validos.keys())
        for i, uid in enumerate(uids):
            try:
                user = await self.bot.fetch_user(int(uid))
                if titulo:
                    e = discord.Embed(title=titulo, description=mensaje,
                                      color=discord.Color.blurple(),
                                      timestamp=datetime.now(timezone.utc))
                    await user.send(embed=e)
                else:
                    await user.send(mensaje)
                enviados += 1
            except Exception as e:
                log.debug(f"DM fallido para {uid}: {e}")
                fallidos += 1
            if i % 5 == 0 or i == len(uids) - 1:
                await progress.edit(
                    embed=_embed_progreso(i + 1, len(uids), "⏳ Enviando DMs...",
                                         f"✅ {enviados}  ❌ {fallidos}")
                )
            await asyncio.sleep(0.5)

        await interaction.followup.send(
            embed=discord.Embed(
                title="📨 DM masivo completado",
                description=f"✅ Enviados: {enviados}\n❌ Fallidos: {fallidos}",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            ),
            ephemeral=True,
        )

    @app_commands.command(name="dm-servidor", description="[Admin] DM a usuarios con token en un servidor concreto.")
    @app_commands.describe(servidor_id="ID del servidor.", mensaje="Mensaje.")
    @app_commands.checks.has_permissions(administrator=True)
    async def dm_servidor(self, interaction: discord.Interaction, servidor_id: str, mensaje: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid   = int(servidor_id)
            guild = self.bot.get_guild(gid)
        except ValueError:
            await interaction.followup.send("❌ ID inválido.", ephemeral=True)
            return

        if not guild:
            await interaction.followup.send("❌ El bot no está en ese servidor.", ephemeral=True)
            return

        ids_servidor = {str(m.id) for m in guild.members if not m.bot}
        targets      = {k: v for k, v in token_store.get_valid().items() if k in ids_servidor}

        if not targets:
            await interaction.followup.send(
                f"⚠️ No hay usuarios con token en **{guild.name}**.", ephemeral=True
            )
            return

        progress = await interaction.followup.send(
            embed=_embed_progreso(0, len(targets), f"⏳ DMs en {guild.name}..."),
            ephemeral=True,
        )
        enviados = fallidos = 0
        for i, uid in enumerate(targets):
            try:
                user = await self.bot.fetch_user(int(uid))
                await user.send(mensaje)
                enviados += 1
            except Exception:
                fallidos += 1
            if i % 5 == 0 or i == len(targets) - 1:
                await progress.edit(
                    embed=_embed_progreso(i + 1, len(targets), f"⏳ DMs en {guild.name}...",
                                         f"✅ {enviados}  ❌ {fallidos}")
                )
            await asyncio.sleep(0.5)

        await interaction.followup.send(
            embed=discord.Embed(
                title=f"📨 DMs en {guild.name} — Completado",
                description=f"✅ {enviados} enviados  ❌ {fallidos} fallidos",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            ),
            ephemeral=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  INFO DE RED
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="mis-servidores", description="[Admin] Lista todos los servidores del bot.")
    @app_commands.checks.has_permissions(administrator=True)
    async def mis_servidores(self, interaction: discord.Interaction):
        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)
        embed  = discord.Embed(
            title=f"🌐 Servidores del bot — {len(guilds)}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        for g in guilds[:25]:
            embed.add_field(
                name=g.name,
                value=f"`{g.id}`\n👥 {g.member_count}",
                inline=True,
            )
        if len(guilds) > 25:
            embed.set_footer(text=f"Mostrando 25 de {len(guilds)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="guilds-usuario", description="[Admin] Servidores donde está un usuario (vía token).")
    @app_commands.describe(usuario="Usuario.")
    @app_commands.checks.has_permissions(administrator=True)
    async def guilds_usuario(self, interaction: discord.Interaction, usuario: discord.Member):
        await interaction.response.defer(ephemeral=True)
        token = await _valid_token(usuario.id)
        if not token:
            await interaction.followup.send(f"❌ {usuario.mention} no tiene token válido.", ephemeral=True)
            return

        guilds = await get_user_guilds(token)
        if not guilds:
            await interaction.followup.send(
                "⚠️ No se pudieron obtener los servidores. El token puede no tener scope `guilds`.",
                ephemeral=True,
            )
            return

        bot_ids = {g.id for g in self.bot.guilds}
        embed   = discord.Embed(
            title=f"🌐 Servidores de {usuario.display_name} ({len(guilds)})",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=usuario.display_avatar.url)
        for g in guilds[:24]:
            en_bot = " 🤖" if int(g["id"]) in bot_ids else ""
            embed.add_field(name=f"{g['name']}{en_bot}", value=f"`{g['id']}`", inline=True)
        if len(guilds) > 24:
            embed.set_footer(text=f"Mostrando 24/{len(guilds)} — 🤖 = bot también está ahí")
        else:
            embed.set_footer(text="🤖 = el bot también está en ese servidor")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="mapa-tokens", description="[Admin] Cuántos token-holders hay en cada servidor.")
    @app_commands.checks.has_permissions(administrator=True)
    async def mapa_tokens(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        token_ids = {int(k) for k in token_store.get_valid()}
        if not token_ids:
            await interaction.followup.send("⚠️ No hay tokens válidos.", ephemeral=True)
            return

        guilds  = sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)
        total   = len(token_ids)
        filas   = []
        for g in guilds:
            ids_en_g = {m.id for m in g.members if not m.bot}
            comunes  = len(token_ids & ids_en_g)
            pct      = int(comunes / total * 100) if total else 0
            barra    = _barra(comunes, total, 10)
            filas.append((g.name, comunes, pct, barra, g.id))

        filas.sort(key=lambda x: x[1], reverse=True)

        embed = discord.Embed(
            title="🗺️ Mapa de tokens por servidor",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        for nombre, n, pct, barra, gid in filas[:20]:
            embed.add_field(
                name=f"{nombre}",
                value=f"`{barra}` **{n}** ({pct}%)\n`{gid}`",
                inline=True,
            )
        embed.set_footer(text=f"Total tokens válidos: {total}")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Red(bot))
