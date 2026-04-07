"""
Cog: Mensajes
─────────────
Comandos: /dm  /dm-rol  /anuncio  /mensaje  /encuesta  /embed
"""

import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord import app_commands


# ── Modal para /embed ─────────────────────────────────────────────────────────

class EmbedModal(discord.ui.Modal, title="Crear Embed personalizado"):
    titulo_f = discord.ui.TextInput(
        label="Título", max_length=256
    )
    desc_f = discord.ui.TextInput(
        label="Descripción", style=discord.TextStyle.paragraph, max_length=4000
    )
    color_f = discord.ui.TextInput(
        label="Color hex (ej: ff0000)", required=False,
        placeholder="5865f2", max_length=7
    )
    imagen_f = discord.ui.TextInput(
        label="URL de imagen grande (opcional)", required=False
    )
    footer_f = discord.ui.TextInput(
        label="Footer (opcional)", required=False, max_length=2048
    )

    def __init__(self, canal: discord.TextChannel):
        super().__init__()
        self.canal = canal

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color = int((self.color_f.value or "5865f2").lstrip("#"), 16)
        except ValueError:
            color = 0x5865F2

        embed = discord.Embed(
            title=self.titulo_f.value,
            description=self.desc_f.value,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        if self.imagen_f.value:
            embed.set_image(url=self.imagen_f.value)
        if self.footer_f.value:
            embed.set_footer(text=self.footer_f.value)

        await self.canal.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Embed enviado en {self.canal.mention}.", ephemeral=True
        )


# ── Cog ───────────────────────────────────────────────────────────────────────

NUMEROS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]


class Mensajes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /dm ───────────────────────────────────────────────────────────────────
    @app_commands.command(name="dm", description="[Admin] Envía un DM a un usuario.")
    @app_commands.describe(
        usuario="Usuario destinatario.",
        mensaje="Contenido del mensaje.",
        titulo="Título del embed (si se omite, se envía texto plano).",
        color="Color hex del embed, ej: ff0000 (opcional).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_dm(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        mensaje: str,
        titulo: str | None = None,
        color: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            if titulo:
                hex_c = int((color or "5865f2").lstrip("#"), 16)
                embed = discord.Embed(
                    title=titulo, description=mensaje, color=hex_c,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_footer(text=f"Mensaje de {interaction.guild.name}")
                await usuario.send(embed=embed)
            else:
                await usuario.send(mensaje)
            await interaction.followup.send(f"✅ DM enviado a {usuario.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ {usuario.mention} tiene los DMs cerrados.", ephemeral=True
            )

    # ── /dm-rol ───────────────────────────────────────────────────────────────
    @app_commands.command(name="dm-rol", description="[Admin] Envía un DM a todos los miembros de un rol.")
    @app_commands.describe(
        rol="Rol cuyos miembros recibirán el mensaje.",
        mensaje="Contenido del mensaje.",
        titulo="Título del embed (opcional).",
        color="Color hex del embed (opcional).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_dm_rol(
        self,
        interaction: discord.Interaction,
        rol: discord.Role,
        mensaje: str,
        titulo: str | None = None,
        color: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        miembros = [m for m in rol.members if not m.bot]
        if not miembros:
            await interaction.followup.send("⚠️ Ese rol no tiene miembros.", ephemeral=True)
            return

        enviados = fallidos = 0
        for m in miembros:
            try:
                if titulo:
                    hex_c = int((color or "5865f2").lstrip("#"), 16)
                    embed = discord.Embed(
                        title=titulo, description=mensaje, color=hex_c,
                        timestamp=datetime.now(timezone.utc),
                    )
                    embed.set_footer(text=f"Mensaje de {interaction.guild.name}")
                    await m.send(embed=embed)
                else:
                    await m.send(mensaje)
                enviados += 1
            except discord.Forbidden:
                fallidos += 1
            await asyncio.sleep(0.5)  # evitar rate-limit

        embed_res = discord.Embed(
            title="📨 DM masivo completado",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed_res.add_field(name="Rol",      value=rol.mention,    inline=True)
        embed_res.add_field(name="✅ Enviados", value=str(enviados), inline=True)
        embed_res.add_field(name="❌ Fallidos", value=str(fallidos), inline=True)
        await interaction.followup.send(embed=embed_res, ephemeral=True)

    # ── /anuncio ──────────────────────────────────────────────────────────────
    @app_commands.command(name="anuncio", description="[Admin] Publica un embed de anuncio en un canal.")
    @app_commands.describe(
        canal="Canal destino.",
        titulo="Título del anuncio.",
        descripcion="Cuerpo del anuncio (soporta markdown).",
        color="Color hex, ej: ff0000 (por defecto azul).",
        imagen="URL de imagen grande al pie (opcional).",
        miniatura="URL de imagen pequeña en la esquina (opcional).",
        mencionar_rol="Rol a mencionar junto al anuncio (opcional).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_anuncio(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        titulo: str,
        descripcion: str,
        color: str | None = None,
        imagen: str | None = None,
        miniatura: str | None = None,
        mencionar_rol: discord.Role | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
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
        if interaction.guild.icon:
            embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
        if imagen:
            embed.set_image(url=imagen)
        if miniatura:
            embed.set_thumbnail(url=miniatura)
        embed.set_footer(text=f"Publicado por {interaction.user.display_name}")

        contenido = mencionar_rol.mention if mencionar_rol else None
        await canal.send(content=contenido, embed=embed)
        await interaction.followup.send(f"✅ Anuncio publicado en {canal.mention}.", ephemeral=True)

    # ── /mensaje ──────────────────────────────────────────────────────────────
    @app_commands.command(name="mensaje", description="[Admin] Envía texto plano a un canal.")
    @app_commands.describe(
        canal="Canal destino.",
        texto="Texto del mensaje (soporta markdown de Discord).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_mensaje(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        texto: str,
    ):
        await canal.send(texto)
        await interaction.response.send_message(
            f"✅ Mensaje enviado en {canal.mention}.", ephemeral=True
        )

    # ── /embed ────────────────────────────────────────────────────────────────
    @app_commands.command(name="embed", description="[Admin] Abre un formulario para crear un embed personalizado.")
    @app_commands.describe(canal="Canal donde publicar el embed.")
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_embed(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
    ):
        await interaction.response.send_modal(EmbedModal(canal))

    # ── /encuesta ─────────────────────────────────────────────────────────────
    @app_commands.command(name="encuesta", description="[Admin] Crea una encuesta con reacciones.")
    @app_commands.describe(
        canal="Canal donde publicar la encuesta.",
        pregunta="Pregunta de la encuesta.",
        opciones="Opciones separadas por coma (máx. 9), ej: Rojo,Azul,Verde",
        mencionar_rol="Rol a mencionar (opcional).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_encuesta(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        pregunta: str,
        opciones: str,
        mencionar_rol: discord.Role | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        lista = [o.strip() for o in opciones.split(",") if o.strip()][:9]
        if len(lista) < 2:
            await interaction.followup.send("❌ Necesitas al menos 2 opciones.", ephemeral=True)
            return

        descripcion = "\n".join(f"{NUMEROS[i]} {op}" for i, op in enumerate(lista))
        embed = discord.Embed(
            title=f"📊 {pregunta}",
            description=descripcion,
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Encuesta creada por {interaction.user.display_name}")

        contenido = mencionar_rol.mention if mencionar_rol else None
        msg = await canal.send(content=contenido, embed=embed)
        for i in range(len(lista)):
            await msg.add_reaction(NUMEROS[i])

        await interaction.followup.send(
            f"✅ Encuesta publicada en {canal.mention}.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Mensajes(bot))
