import os
import json
import asyncio
import re
import time
import traceback
import unicodedata
import discord
from discord import app_commands
from discord.ext import commands
import openai

try:
    from firebase_admin import firestore
except ImportError:
    firestore = None

MODELO_ZAI = os.getenv("MODELO_ZAI", "glm-4-flash")
MODELO_GROQ = os.getenv("MODELO_GROQ", "openai/gpt-oss-20b")
MODELO_QWEN = os.getenv("MODELO_QWEN", "Qwen/Qwen2.5-7B-Instruct")

MAX_FUENTES = 25
CACHE_TTL = 30.0
COLECCION_GLOBAL = "fuentes_globales"
DOC_GLOBAL = "mapa"


def leer_key(*nombres: str):
    for n in nombres:
        v = os.getenv(n)
        if v:
            v = v.strip().strip('"').strip("'").strip()
            if v:
                return v
    return None


def describir_error(e: Exception) -> str:
    status = getattr(e, "status_code", None)
    cuerpo = getattr(e, "body", None) or getattr(e, "message", None) or str(e)
    return f"{type(e).__name__} | status={status} | {str(cuerpo)[:300]}"


class ErrorFuente(Exception):
    pass


EMOJI_REGEX = re.compile(
    r"(<a?:\w+:\d+>|[\U00010000-\U0010ffff\u2600-\u27ff\u2300-\u23ff\u2B50\u200d]+)"
)
RANGOS_UNICODE = [
    ("sans-serif-bold", 0x1D5D4, 0x1D5EE, 0x1D7EC),
    ("sans-serif", 0x1D5A0, 0x1D5BA, 0x1D7E2),
    ("sans-serif-italic", 0x1D608, 0x1D622, None),
    ("sans-serif-bold-italic", 0x1D63C, 0x1D656, None),
    ("serif-bold", 0x1D400, 0x1D41A, 0x1D7CE),
    ("serif-italic", 0x1D434, 0x1D44E, None),
    ("serif-bold-italic", 0x1D468, 0x1D482, None),
    ("script-bold", 0x1D4D0, 0x1D4EA, None),
    ("fraktur-bold", 0x1D56C, 0x1D586, None),
    ("monospace", 0x1D670, 0x1D68A, 0x1D7F6),
    ("double-struck", 0x1D538, 0x1D552, 0x1D7D8),
    ("circled", 0x24B6, 0x24D0, None),
    ("fullwidth", 0xFF21, 0xFF41, 0xFF10),
]

EXCEPCIONES_GLIFOS = {
    "serif-italic": {"h": "ℎ"},
    "double-struck": {"C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ", "R": "ℝ", "Z": "ℤ"},
    "circled": {"0": "⓪", **{str(i): chr(0x2460 + i - 1) for i in range(1, 10)}},
}

SMALL_CAPS_MAP = {
    'ᴀ': 'a', 'ʙ': 'b', 'ᴄ': 'c', 'ᴅ': 'd', 'ᴇ': 'e', 'ꜰ': 'f', 'ɢ': 'g', 'ʜ': 'h', 'ɪ': 'i',
    'ᴊ': 'j', 'ᴋ': 'k', 'ʟ': 'l', 'ᴍ': 'm', 'ɴ': 'n', 'ᴏ': 'o', 'ᴘ': 'p', 'ǫ': 'q', 'ʀ': 'r',
    'ꜱ': 's', 'ᴛ': 't', 'ᴜ': 'u', 'ᴠ': 'v', 'ᴡ': 'w', 'x': 'x', 'ʏ': 'y', 'ᴢ': 'z'
}

TIPOS_EDITABLES = (
    discord.TextChannel,
    discord.VoiceChannel,
    discord.StageChannel,
    discord.CategoryChannel,
    discord.ForumChannel,
)


def generar_bloque_completo(char_muestra: str):
    code = ord(char_muestra)
    for nombre, a_start, a_low, num_start in RANGOS_UNICODE:
        en_mayus = bool(a_start) and a_start <= code <= a_start + 25
        en_minus = bool(a_low) and a_low <= code <= a_low + 25
        if en_mayus or en_minus:
            mapeo = {}
            for i in range(26):
                if a_start:
                    mapeo[chr(ord('A') + i)] = chr(a_start + i)
                if a_low:
                    mapeo[chr(ord('a') + i)] = chr(a_low + i)
            if num_start:
                for i in range(10):
                    mapeo[str(i)] = chr(num_start + i)
            mapeo.update(EXCEPCIONES_GLIFOS.get(nombre, {}))
            return nombre, mapeo
    return None, {}


def normalizar_nombre_fuente(nombre: str) -> str:
    nombre = " ".join(nombre.strip().lower().split())
    if not re.fullmatch(r"[\w\- ]{1,32}", nombre):
        raise ErrorFuente(
            "El nombre solo puede tener letras, números, espacios, guiones y guion bajo (máximo 32 caracteres)."
        )
    return nombre.replace(" ", "-")


class ModalNombre(discord.ui.Modal):
    def __init__(self, cog, tipo: str, elemento, autor_id: int):
        super().__init__(title=f"Guardar fuente desde {tipo}")
        self.cog = cog
        self.tipo = tipo
        self.elemento = elemento
        self.autor_id = autor_id
        self.nombre_input = discord.ui.TextInput(
            label="Nombre de la fuente (local)",
            placeholder="Ej: mi-fuente",
            min_length=1,
            max_length=32,
        )
        self.add_item(self.nombre_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.autor_id:
            return await interaction.response.send_message("❌ Este formulario no es tuyo.", ephemeral=True)
        nombre = self.nombre_input.value.strip()
        await interaction.response.defer(ephemeral=True)
        try:
            nombre = normalizar_nombre_fuente(nombre)
            mapeo, nombre_global, ya_global = await self.cog.extraer_mapeo(self.elemento.name, interaction.guild_id)
            await self.cog.guardar_local(interaction.guild_id, nombre, mapeo)

            if ya_global:
                texto_global = f"🌐 Ya existía en global como **{nombre_global}** (sin gastar tokens)."
            elif nombre_global:
                await self.cog.guardar_global(nombre_global, mapeo)
                texto_global = f"🌐 Guardada en global como **{nombre_global}**."
            else:
                rango, _ = generar_bloque_completo(self.elemento.name[0]) if self.elemento.name else (None, {})
                if rango:
                    await self.cog.guardar_global(rango, mapeo)
                    texto_global = f"🌐 Guardada en global como **{rango}**."
                else:
                    global_name = f"auto-{nombre}"
                    await self.cog.guardar_global(global_name, mapeo)
                    texto_global = f"🌐 Guardada en global como **{global_name}**."

            await interaction.followup.send(
                f"🧠 Fuente **{nombre}** guardada desde {self.tipo} **{self.elemento.name}** ({len(mapeo)} chars).\n{texto_global}",
                ephemeral=True,
            )
        except ErrorFuente as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
        except Exception as e:
            print(f"⚠️ Error en ModalNombre: {type(e).__name__}: {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Error al procesar la fuente.", ephemeral=True)


class ModalProbar(discord.ui.Modal):
    def __init__(self, cog, mapeo: dict, nombre: str, autor_id: int):
        super().__init__(title=f"Probar: {nombre[:40]}")
        self.cog = cog
        self.mapeo = mapeo
        self.autor_id = autor_id
        self.texto_input = discord.ui.TextInput(
            label="Texto de prueba",
            placeholder="Ej: hola mundo",
            min_length=1,
            max_length=100,
        )
        self.add_item(self.texto_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.autor_id:
            return await interaction.response.send_message("❌ Este formulario no es tuyo.", ephemeral=True)
        texto = self.texto_input.value.strip()
        resultado = self.cog.construir_nombre_inteligente(texto, None, self.mapeo, es_cat_o_voz=True)
        resultado = resultado.replace("`", "'")
        await interaction.response.send_message(f"👁️ **Vista Previa:** `{resultado}`", ephemeral=True)


class VistaEscanear(discord.ui.View):
    def __init__(self, cog, autor_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.autor_id = autor_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Este menú no es tuyo.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Desde canal", style=discord.ButtonStyle.primary, emoji="📁")
    async def btn_canal(self, interaction: discord.Interaction, button: discord.ui.Button):
        select = discord.ui.ChannelSelect(
            placeholder="Selecciona un canal de texto o voz",
            channel_types=[discord.ChannelType.text, discord.ChannelType.voice, discord.ChannelType.stage_voice, discord.ChannelType.forum],
        )
        view = discord.ui.View(timeout=120)

        async def callback(inter: discord.Interaction):
            if inter.user.id != self.autor_id:
                return await inter.response.send_message("❌ Este menú no es tuyo.", ephemeral=True)
            ch = inter.guild.get_channel(select.values[0].id)
            if ch is None:
                return await inter.response.send_message("❌ Canal no encontrado.", ephemeral=True)
            modal = ModalNombre(self.cog, "canal", ch, self.autor_id)
            await inter.response.send_modal(modal)

        select.callback = callback
        view.add_item(select)
        await interaction.response.send_message("📁 Selecciona el canal:", view=view, ephemeral=True)

    @discord.ui.button(label="Desde categoría", style=discord.ButtonStyle.primary, emoji="🗂️")
    async def btn_categoria(self, interaction: discord.Interaction, button: discord.ui.Button):
        select = discord.ui.ChannelSelect(
            placeholder="Selecciona una categoría",
            channel_types=[discord.ChannelType.category],
        )
        view = discord.ui.View(timeout=120)

        async def callback(inter: discord.Interaction):
            if inter.user.id != self.autor_id:
                return await inter.response.send_message("❌ Este menú no es tuyo.", ephemeral=True)
            cat = inter.guild.get_channel(select.values[0].id)
            if cat is None:
                return await inter.response.send_message("❌ Categoría no encontrada.", ephemeral=True)
            modal = ModalNombre(self.cog, "categoría", cat, self.autor_id)
            await inter.response.send_modal(modal)

        select.callback = callback
        view.add_item(select)
        await interaction.response.send_message("🗂️ Selecciona la categoría:", view=view, ephemeral=True)


class VistaAplicarGlobal(discord.ui.View):
    def __init__(self, cog, autor_id: int, fuentes: dict):
        super().__init__(timeout=120)
        self.cog = cog
        self.autor_id = autor_id
        if not fuentes:
            return
        opciones = [discord.SelectOption(label=n[:100], value=n[:100]) for n in list(fuentes.keys())[:25]]
        select = discord.ui.Select(placeholder="🌐 Selecciona una fuente global", options=opciones)
        select.callback = self.on_select
        self.fuentes = fuentes
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Este menú no es tuyo.", ephemeral=True)
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        nombre = interaction.data["values"][0]
        mapeo = self.fuentes.get(nombre)
        if not mapeo:
            return await interaction.response.send_message("❌ Fuente no encontrada.", ephemeral=True)
        select = discord.ui.ChannelSelect(
            placeholder="Selecciona canal o categoría a rediseñar",
            channel_types=[
                discord.ChannelType.text, discord.ChannelType.voice,
                discord.ChannelType.stage_voice, discord.ChannelType.forum,
                discord.ChannelType.category,
            ],
        )
        view = discord.ui.View(timeout=120)

        async def callback(inter: discord.Interaction):
            if inter.user.id != self.autor_id:
                return await inter.response.send_message("❌ Este menú no es tuyo.", ephemeral=True)
            target = inter.guild.get_channel(select.values[0].id)
            if target is None:
                return await inter.response.send_message("❌ Elemento no encontrado.", ephemeral=True)
            await inter.response.defer(ephemeral=True)
            nuevo_nombre = self.cog.construir_nombre_inteligente(
                target.name, None, mapeo, es_cat_o_voz=self.cog.es_categoria_o_voz(target)
            )
            _, msg = await self.cog.editar_nombre(inter, target, nuevo_nombre)
            await inter.followup.send(msg, ephemeral=True)

        select.callback = callback
        view.add_item(select)
        await interaction.response.send_message(f"🎨 Aplicando **{nombre}**. Elige el destino:", view=view, ephemeral=True)


class VistaAplicarLocal(discord.ui.View):
    def __init__(self, cog, autor_id: int, fuentes: dict):
        super().__init__(timeout=120)
        self.cog = cog
        self.autor_id = autor_id
        if not fuentes:
            return
        opciones = [discord.SelectOption(label=n[:100], value=n[:100]) for n in list(fuentes.keys())[:25]]
        select = discord.ui.Select(placeholder="📁 Selecciona una fuente local", options=opciones)
        select.callback = self.on_select
        self.fuentes = fuentes
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Este menú no es tuyo.", ephemeral=True)
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        nombre = interaction.data["values"][0]
        mapeo = self.fuentes.get(nombre)
        if not mapeo:
            return await interaction.response.send_message("❌ Fuente no encontrada.", ephemeral=True)
        select = discord.ui.ChannelSelect(
            placeholder="Selecciona canal o categoría a rediseñar",
            channel_types=[
                discord.ChannelType.text, discord.ChannelType.voice,
                discord.ChannelType.stage_voice, discord.ChannelType.forum,
                discord.ChannelType.category,
            ],
        )
        view = discord.ui.View(timeout=120)

        async def callback(inter: discord.Interaction):
            if inter.user.id != self.autor_id:
                return await inter.response.send_message("❌ Este menú no es tuyo.", ephemeral=True)
            target = inter.guild.get_channel(select.values[0].id)
            if target is None:
                return await inter.response.send_message("❌ Elemento no encontrado.", ephemeral=True)
            await inter.response.defer(ephemeral=True)
            nuevo_nombre = self.cog.construir_nombre_inteligente(
                target.name, None, mapeo, es_cat_o_voz=self.cog.es_categoria_o_voz(target)
            )
            _, msg = await self.cog.editar_nombre(inter, target, nuevo_nombre)
            await inter.followup.send(msg, ephemeral=True)

        select.callback = callback
        view.add_item(select)
        await interaction.response.send_message(f"🎨 Aplicando **{nombre}**. Elige el destino:", view=view, ephemeral=True)


class VistaAplicar(discord.ui.View):
    def __init__(self, cog, autor_id: int, locales: dict, globales: dict):
        super().__init__(timeout=120)
        self.cog = cog
        self.autor_id = autor_id
        self.locales = locales
        self.globales = globales

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Este menú no es tuyo.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Global", style=discord.ButtonStyle.success, emoji="🌐")
    async def btn_global(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.globales:
            return await interaction.response.send_message("📂 No hay fuentes globales guardadas.", ephemeral=True)
        view = VistaAplicarGlobal(self.cog, self.autor_id, self.globales)
        await interaction.response.send_message("🌐 Elige una fuente global:", view=view, ephemeral=True)

    @discord.ui.button(label="Local", style=discord.ButtonStyle.primary, emoji="📁")
    async def btn_local(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.locales:
            return await interaction.response.send_message(
                "📂 No hay fuentes locales en este servidor. Escanea una primero con 📥.", ephemeral=True
            )
        view = VistaAplicarLocal(self.cog, self.autor_id, self.locales)
        await interaction.response.send_message("📁 Elige una fuente local:", view=view, ephemeral=True)


class VistaEliminar(discord.ui.View):
    def __init__(self, cog, autor_id: int, fuentes: dict):
        super().__init__(timeout=120)
        self.cog = cog
        self.autor_id = autor_id
        if not fuentes:
            return
        opciones = [discord.SelectOption(label=n[:100], value=n[:100]) for n in list(fuentes.keys())[:25]]
        select = discord.ui.Select(placeholder="🗑️ Selecciona una fuente local para eliminar", options=opciones)
        select.callback = self.on_select
        self.fuentes = fuentes
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Este menú no es tuyo.", ephemeral=True)
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        nombre = interaction.data["values"][0]
        await interaction.response.defer(ephemeral=True)
        ok = await self.cog.eliminar_local(interaction.guild_id, nombre)
        if ok:
            await interaction.followup.send(f"🗑️ Fuente **{nombre}** eliminada del servidor.", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ No se encontró **{nombre}**.", ephemeral=True)


class VistaProbar(discord.ui.View):
    def __init__(self, cog, autor_id: int, fuentes: dict):
        super().__init__(timeout=120)
        self.cog = cog
        self.autor_id = autor_id
        if not fuentes:
            return
        opciones = [discord.SelectOption(label=n[:100], value=n[:100]) for n in list(fuentes.keys())[:25]]
        select = discord.ui.Select(placeholder="👁️ Selecciona una fuente para probar", options=opciones)
        select.callback = self.on_select
        self.fuentes = fuentes
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Este menú no es tuyo.", ephemeral=True)
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        nombre = interaction.data["values"][0]
        mapeo = self.fuentes.get(nombre)
        if not mapeo:
            return await interaction.response.send_message("❌ Fuente no encontrada.", ephemeral=True)
        modal = ModalProbar(self.cog, mapeo, nombre, self.autor_id)
        await interaction.response.send_modal(modal)


class VistaPanelFuente(discord.ui.View):
    def __init__(self, cog, autor_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.autor_id = autor_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Este panel no es tuyo.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Escanear", style=discord.ButtonStyle.primary, emoji="📥", row=0)
    async def btn_escanear(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = VistaEscanear(self.cog, self.autor_id)
        await interaction.response.send_message("📥 ¿Desde dónde quieres escanear?", view=view, ephemeral=True)

    @discord.ui.button(label="Aplicar", style=discord.ButtonStyle.success, emoji="🎨", row=0)
    async def btn_aplicar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        locales = await self.cog.cargar_locales(interaction.guild_id)
        globales = await self.cog.cargar_globales()
        if not locales and not globales:
            return await interaction.followup.send("📂 No hay fuentes guardadas. Escanea una primero.", ephemeral=True)
        view = VistaAplicar(self.cog, self.autor_id, locales, globales)
        await interaction.followup.send("🎨 ¿Qué tipo de fuente quieres aplicar?", view=view, ephemeral=True)

    @discord.ui.button(label="Listar", style=discord.ButtonStyle.secondary, emoji="📋", row=0)
    async def btn_listar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        locales = await self.cog.cargar_locales(interaction.guild_id)
        globales = await self.cog.cargar_globales()
        if not locales and not globales:
            return await interaction.followup.send("📂 No hay fuentes guardadas.", ephemeral=True)
        embed = discord.Embed(title="🎨 Tipografías Registradas", color=discord.Color.blue())
        if locales:
            lineas = []
            for n, m in list(locales.items())[:15]:
                ejemplo = self.cog.construir_nombre_inteligente("canal-pruebas", None, m, False)
                lineas.append(f"📁 **{n}** → `{ejemplo}` ({len(m)} chars)")
            embed.add_field(name="Locales del servidor", value="\n".join(lineas)[:1024], inline=False)
        if globales:
            lineas = []
            for n, m in list(globales.items())[:15]:
                ejemplo = self.cog.construir_nombre_inteligente("canal-pruebas", None, m, False)
                lineas.append(f"🌐 **{n}** → `{ejemplo}` ({len(m)} chars)")
            embed.add_field(name="Globales", value="\n".join(lineas)[:1024], inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Probar", style=discord.ButtonStyle.secondary, emoji="👁️", row=1)
    async def btn_probar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        locales = await self.cog.cargar_locales(interaction.guild_id)
        globales = await self.cog.cargar_globales()
        todas = {**globales, **locales}
        if not todas:
            return await interaction.followup.send("📂 No hay fuentes guardadas.", ephemeral=True)
        view = VistaProbar(self.cog, self.autor_id, todas)
        await interaction.followup.send("👁️ Elige una fuente para probar:", view=view, ephemeral=True)

    @discord.ui.button(label="Eliminar", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def btn_eliminar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        locales = await self.cog.cargar_locales(interaction.guild_id)
        if not locales:
            return await interaction.followup.send(
                "📂 No hay fuentes locales para eliminar. Las globales solo se borran desde Firestore.", ephemeral=True
            )
        view = VistaEliminar(self.cog, self.autor_id, locales)
        await interaction.followup.send(
            "🗑️ Elige una fuente local para eliminar (las globales no se pueden eliminar desde aquí):",
            view=view, ephemeral=True,
        )


class Fuentes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cache_local = {}
        self._cache_global = (0.0, {})

        def crear(base_url, key, timeout=25.0):
            if not key:
                return None
            return openai.AsyncOpenAI(base_url=base_url, api_key=key, timeout=timeout, max_retries=1)

        self.zai_client = crear("https://api.z.ai/api/coding/paas/v4", leer_key("ZAI_API_KEY", "ZHIPUAI_API_KEY"))
        self.groq_client = crear("https://api.groq.com/openai/v1", leer_key("GROQ_API_KEY", "GROQ_KEY"))
        self.hf_client = crear("https://router.huggingface.co/v1/", leer_key("HF_TOKEN", "HUGGINGFACE_API_KEY", "HF_API_KEY", "QWEN_API_KEY"))

    async def cog_unload(self):
        for cliente in (self.zai_client, self.groq_client, self.hf_client):
            if cliente:
                try:
                    await cliente.close()
                except Exception:
                    pass

    async def cargar_locales(self, guild_id: int, usar_cache: bool = True) -> dict:
        if not self.bot.db or not guild_id:
            return {}
        guardado = self._cache_local.get(guild_id)
        if usar_cache and guardado and time.monotonic() - guardado[0] < CACHE_TTL:
            return guardado[1]

        def _read():
            doc = self.bot.db.collection("servidores").document(str(guild_id)).get()
            if doc and doc.exists:
                data = doc.to_dict() or {}
                return data.get("fuentes", {})
            return {}

        try:
            fuentes = await asyncio.to_thread(_read)
            self._cache_local[guild_id] = (time.monotonic(), fuentes)
            return fuentes
        except Exception as e:
            print(f"⚠️ Error cargando locales: {type(e).__name__}: {e}")
            return guardado[1] if guardado else {}

    async def cargar_globales(self, usar_cache: bool = True) -> dict:
        if not self.bot.db:
            return {}
        ts, datos = self._cache_global
        if usar_cache and time.monotonic() - ts < CACHE_TTL and datos:
            return datos

        def _read():
            doc = self.bot.db.collection(COLECCION_GLOBAL).document(DOC_GLOBAL).get()
            if doc and doc.exists:
                return doc.to_dict() or {}
            return {}

        try:
            datos = await asyncio.to_thread(_read)
            self._cache_global = (time.monotonic(), datos)
            return datos
        except Exception as e:
            print(f"⚠️ Error cargando globales: {type(e).__name__}: {e}")
            return datos or {}

    async def guardar_local(self, guild_id: int, nombre: str, mapeo: dict) -> None:
        if not self.bot.db or not guild_id or not mapeo:
            raise ErrorFuente("Firebase no disponible.")
        if firestore is None:
            raise ErrorFuente("firebase-admin no instalado.")

        existentes = await self.cargar_locales(guild_id, usar_cache=False)
        if nombre not in existentes and len(existentes) >= MAX_FUENTES:
            raise ErrorFuente(f"Máximo {MAX_FUENTES} fuentes por servidor.")

        def _write():
            ref = self.bot.db.collection("servidores").document(str(guild_id))
            ref.set({"fuentes": {nombre: firestore.DELETE_FIELD}}, merge=True)
            ref.set({"fuentes": {nombre: mapeo}}, merge=True)

        try:
            await asyncio.to_thread(_write)
        except Exception as e:
            print(f"⚠️ Error guardando local: {type(e).__name__}: {e}")
            raise ErrorFuente("Error al guardar en Firebase.")
        finally:
            self._cache_local.pop(guild_id, None)

    async def guardar_global(self, nombre: str, mapeo: dict) -> None:
        if not self.bot.db or not mapeo or firestore is None:
            return

        def _write():
            ref = self.bot.db.collection(COLECCION_GLOBAL).document(DOC_GLOBAL)
            ref.set({nombre: firestore.DELETE_FIELD}, merge=True)
            ref.set({nombre: mapeo}, merge=True)

        try:
            await asyncio.to_thread(_write)
        except Exception as e:
            print(f"⚠️ Error guardando global: {type(e).__name__}: {e}")
        finally:
            self._cache_global = (0.0, {})

    async def eliminar_local(self, guild_id: int, nombre: str) -> bool:
        if not self.bot.db or not guild_id or firestore is None:
            return False

        def _delete():
            ref = self.bot.db.collection("servidores").document(str(guild_id))
            doc = ref.get()
            if doc.exists:
                data = doc.to_dict() or {}
                if nombre in data.get("fuentes", {}):
                    ref.set({"fuentes": {nombre: firestore.DELETE_FIELD}}, merge=True)
                    return True
            return False

        try:
            return await asyncio.to_thread(_delete)
        except Exception as e:
            print(f"⚠️ Error eliminando local: {type(e).__name__}: {e}")
            return False
        finally:
            self._cache_local.pop(guild_id, None)

    def desestilizar_texto(self, texto: str) -> str:
        resultado = []
        for char in texto:
            base = unicodedata.normalize("NFKD", char)
            if len(base) == 1 and base.isalnum():
                resultado.append(base)
                continue
            if char in SMALL_CAPS_MAP:
                resultado.append(SMALL_CAPS_MAP[char])
                continue
            resultado.append(char)
        return "".join(resultado)

    def aplicar_mapeo(self, texto: str, mapeo: dict) -> str:
        res = []
        for char in texto:
            if char in mapeo:
                res.append(mapeo[char])
            elif char.islower() and char.upper() in mapeo:
                res.append(mapeo[char.upper()])
            elif char.isupper() and char.lower() in mapeo:
                res.append(mapeo[char.lower()])
            else:
                res.append(char)
        return "".join(res)

    def construir_nombre_inteligente(self, texto_original: str, texto_nuevo, mapeo: dict, es_cat_o_voz: bool = False) -> str:
        base = texto_nuevo if texto_nuevo else texto_original
        limpio = self.desestilizar_texto(base)
        resultado, pos = [], 0
        for match in EMOJI_REGEX.finditer(limpio):
            start, end = match.span()
            if start > pos:
                resultado.append(self.aplicar_mapeo(limpio[pos:start], mapeo))
            resultado.append(match.group(0))
            pos = end
        if pos < len(limpio):
            resultado.append(self.aplicar_mapeo(limpio[pos:], mapeo))
        nombre_final = "".join(resultado)
        return nombre_final if es_cat_o_voz else nombre_final.replace(" ", "-")

    @staticmethod
    def es_categoria_o_voz(canal) -> bool:
        return isinstance(canal, (discord.CategoryChannel, discord.VoiceChannel, discord.StageChannel))

    async def editar_nombre(self, interaction: discord.Interaction, target, nuevo_nombre: str):
        if not isinstance(target, TIPOS_EDITABLES):
            return False, "❌ Ese tipo no se puede rediseñar."
        nuevo_nombre = nuevo_nombre.strip()[:100]
        if not nuevo_nombre:
            return False, "❌ El nombre quedó vacío."
        if not target.permissions_for(interaction.user).manage_channels:
            return False, f"❌ No tienes 'Gestionar canales' en **{target.name}**."
        yo = interaction.guild.me if interaction.guild else None
        if yo is not None and not target.permissions_for(yo).manage_channels:
            return False, f"❌ No tengo 'Gestionar canales' en **{target.name}**."
        if target.name == nuevo_nombre:
            return False, "ℹ️ Ya tiene ese nombre."
        try:
            await asyncio.wait_for(target.edit(name=nuevo_nombre, reason=f"Fuente por {interaction.user}"), timeout=20)
            return True, f"🎨 Rediseñado: **{nuevo_nombre}**"
        except asyncio.TimeoutError:
            return False, "⏳ Discord limita los cambios de nombre."
        except discord.Forbidden:
            return False, "❌ Sin permisos para renombrar."
        except discord.HTTPException as e:
            if e.status == 429:
                return False, "⏳ Límite de Discord (2 cambios/10 min)."
            if e.status == 400:
                return False, "❌ Nombre inválido."
            return False, "❌ Error de Discord."

    def _limpiar_json(self, texto: str) -> dict:
        try:
            t = (texto or "").strip()
            inicio, fin = t.find("{"), t.rfind("}")
            if inicio == -1 or fin == -1 or fin <= inicio:
                return {}
            datos = json.loads(t[inicio:fin + 1])
            return datos if isinstance(datos, dict) else {}
        except Exception:
            return {}

    def _validar_mapeo(self, datos: dict) -> dict:
        limpio = {}
        for k, v in datos.items():
            if isinstance(k, str) and len(k) == 1 and isinstance(v, str) and 0 < len(v) <= 2 and not v.isspace():
                limpio[k] = v
        letras = sum(1 for k in limpio if k.isalpha())
        cambiadas = sum(1 for k, v in limpio.items() if k != v)
        return limpio if letras >= 20 and cambiadas >= 15 else {}

    async def _mapear_con_zai(self, ejemplo: str) -> dict:
        if not self.zai_client:
            return {}
        prompt = (
            f"Analiza la fuente en: '{ejemplo}'. Genera un JSON mapeando todo el abecedario "
            "(a-z, A-Z) y números (0-9) en este estilo tipográfico.\n"
            "Responde ÚNICAMENTE el JSON sin bloques de código ni explicaciones.\n"
            'Ejemplo: {"a": "𝗮", "A": "𝗔"}'
        )
        try:
            resp = await self.zai_client.chat.completions.create(
                model=MODELO_ZAI, messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=3000
            )
            mapeo = self._validar_mapeo(self._limpiar_json(resp.choices[0].message.content))
            if mapeo:
                print(f"🧠 Zai generó un mapeo de {len(mapeo)} caracteres.")
                return mapeo
        except Exception as e:
            print(f"⚠️ Zai falló: {describir_error(e)}")
        return {}

    async def _mapear_con_qwen(self, ejemplo: str) -> dict:
        if not self.hf_client:
            return {}
        prompt = (
            f"Analiza la fuente en: '{ejemplo}'. Genera un JSON mapeando todo el abecedario "
            "(a-z, A-Z) y números (0-9) en este estilo tipográfico.\n"
            "Responde ÚNICAMENTE el JSON sin bloques de código ni explicaciones.\n"
            'Ejemplo: {"a": "𝗮", "A": "𝗔"}'
        )
        try:
            resp = await self.hf_client.chat.completions.create(
                model=MODELO_QWEN, messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=3000
            )
            mapeo = self._validar_mapeo(self._limpiar_json(resp.choices[0].message.content))
            if mapeo:
                print(f"🧠 Qwen generó un mapeo de {len(mapeo)} caracteres.")
                return mapeo
        except Exception as e:
            print(f"⚠️ Qwen falló: {describir_error(e)}")
        return {}

    async def _comparar_con_groq(self, mapeo_nuevo: dict, globales: dict):
        if not self.groq_client or not globales:
            return None
        for nombre, mapeo_viejo in globales.items():
            if mapeo_nuevo == mapeo_viejo:
                return nombre
        prompt = (
            "Compara el mapeo NUEVO con los EXISTENTES. Si el NUEVO es esencialmente igual a alguno, "
            "responde solo el nombre. Si no, responde NINGUNA.\n"
            f"NUEVO:\n{json.dumps(mapeo_nuevo, ensure_ascii=False)}\n"
            f"EXISTENTES:\n{json.dumps(globales, ensure_ascii=False)}"
        )
        try:
            resp = await self.groq_client.chat.completions.create(
                model=MODELO_GROQ, messages=[{"role": "user", "content": prompt}], temperature=0.0, max_tokens=200
            )
            texto = resp.choices[0].message.content.strip()
            for nombre in globales:
                if nombre.lower() in texto.lower():
                    return nombre
        except Exception as e:
            print(f"⚠️ Groq falló: {describir_error(e)}")
        return None

    async def extraer_mapeo(self, ejemplo: str, guild_id: int):
        mapeo_detectado = {}
        for char in ejemplo:
            nombre_rango, mapa = generar_bloque_completo(char)
            if mapa:
                return mapa, nombre_rango, True
            base = unicodedata.normalize("NFKD", char)
            if len(base) == 1 and base != char and base.isalnum():
                mapeo_detectado[base] = char
            elif char in SMALL_CAPS_MAP:
                mapeo_detectado[SMALL_CAPS_MAP[char]] = char

        if len(mapeo_detectado) >= 15:
            globales = await self.cargar_globales()
            for nombre, mapeo in globales.items():
                if mapeo == mapeo_detectado:
                    return mapeo, nombre, True

        hay_raras = any(c.isalpha() and not c.isascii() for c in ejemplo)
        if not mapeo_detectado and not hay_raras:
            raise ErrorFuente(
                "No detecté tipografía especial. Escribe algo como 𝗠𝗲𝗼𝘄𝗹𝘆 o ᴍᴇᴏᴡʟʏ."
            )

        mapeo_zai = await self._mapear_con_zai(ejemplo)
        if mapeo_zai:
            nombre_global = await self._comparar_con_groq(mapeo_zai, await self.cargar_globales())
            if nombre_global:
                return mapeo_zai, nombre_global, True
            return mapeo_zai, None, False

        mapeo_qwen = await self._mapear_con_qwen(ejemplo)
        if mapeo_qwen:
            return mapeo_qwen, None, False

        if mapeo_detectado:
            return mapeo_detectado, None, False
        raise ErrorFuente("No se pudo detectar ni extrapolar la tipografía.")

    @app_commands.command(name="fuente", description="Panel de gestión de tipografías para canales y categorías")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_channels=True)
    async def fuente_cmd(self, interaction: discord.Interaction):
        if not self.bot.db:
            return await interaction.response.send_message("❌ Firebase no disponible.", ephemeral=True)

        embed = discord.Embed(
            title="🎨 Panel de Tipografías — Meowly",
            description=(
                "**📥 Escanear**: detecta la tipografía de un canal/categoría y la guarda (local + global).\n"
                "**🎨 Aplicar**: aplica una fuente global o local a un canal/categoría existente.\n"
                "**📋 Listar**: muestra las fuentes locales y globales.\n"
                "**👁️ Probar**: vista previa de un texto con una fuente.\n"
                "**🗑️ Eliminar**: borra una fuente local (las globales solo desde Firestore)."
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Solo quien ejecutó el comando puede usar este panel.")
        view = VistaPanelFuente(self, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Fuentes(bot))
