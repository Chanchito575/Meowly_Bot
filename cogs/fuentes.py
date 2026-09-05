import os
import json
import asyncio
import re
import unicodedata
import discord
from discord import app_commands
from discord.ext import commands
from firebase_admin import firestore
import openai

MODELO_MISTRAL = "mistral-small-latest"
MODELO_QWEN = "Qwen/Qwen2.5-Coder-32B-Instruct"

EMOJI_REGEX = re.compile(
    r"(<a?:\w+:\d+>|[\U00010000-\U0010ffff\u2600-\u27ff\u2300-\u23ff\u2B50\u200d]+)"
)

RANGOS_UNICODE = [
    ("Sans-Serif Bold", 0x1D5D4, 0x1D5EE, 0x1D7EC),
    ("Sans-Serif Regular", 0x1D5A0, 0x1D5BA, 0x1D7E2),
    ("Serif Bold", 0x1D400, 0x1D41A, 0x1D7CE),
    ("Serif Italic", 0x1D434, 0x1D44E, None),
    ("Serif Bold Italic", 0x1D468, 0x1D482, None),
    ("Script Bold", 0x1D4D0, 0x1D4EA, None),
    ("Fraktur Bold", 0x1D56C, 0x1D586, None),
    ("Monospace", 0x1D670, 0x1D68A, 0x1D7F6),
    ("Double-Struck", 0x1D538, 0x1D552, 0x1D7D8),
    ("Circled", 0x24B6, 0x24D0, 0x2460),
    ("Fullwidth", 0xFF21, 0xFF41, 0xFF10),
]

SMALL_CAPS_MAP = {
    'ᴀ':'a','ʙ':'b','ᴄ':'c','ᴅ':'d','ᴇ':'e','ꜰ':'f','ɢ':'g','ʜ':'h','ɪ':'i',
    'ᴊ':'j','ᴋ':'k','ʟ':'l','ᴍ':'m','ɴ':'n','ᴏ':'o','ᴘ':'p','ǫ':'q','ʀ':'r',
    'ꜱ':'s','ᴛ':'t','ᴜ':'u','ᴠ':'v','ᴡ':'w','x':'x','ʏ':'y','ᴢ':'z'
}


def generar_bloque_completo(char_muestra: str) -> dict:
    code = ord(char_muestra)
    mapeo = {}
    for _, a_start, a_low, num_start in RANGOS_UNICODE:
        if a_start and a_start <= code <= a_start + 25:
            for i in range(26):
                mapeo[chr(ord('A') + i)] = chr(a_start + i)
                if a_low: mapeo[chr(ord('a') + i)] = chr(a_low + i)
            if num_start:
                for i in range(10): mapeo[str(i)] = chr(num_start + i)
            return mapeo
        elif a_low and a_low <= code <= a_low + 25:
            for i in range(26):
                if a_start: mapeo[chr(ord('A') + i)] = chr(a_start + i)
                mapeo[chr(ord('a') + i)] = chr(a_low + i)
            if num_start:
                for i in range(10): mapeo[str(i)] = chr(num_start + i)
            return mapeo
    return {}


class VistaAplicarCategoria(discord.ui.View):
    def __init__(self, cog, guild_id: int, fuentes: dict):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.fuentes = fuentes
        self.estilo_seleccionado = None

        opciones_estilos = [
            discord.SelectOption(label=nombre.capitalize(), value=nombre.lower())
            for nombre in list(fuentes.keys())[:25]
        ]
        self.select_estilo = discord.ui.Select(
            placeholder="🎨 Selecciona un estilo registrado",
            options=opciones_estilos,
            custom_id="select_estilo"
        )
        self.select_estilo.callback = self.callback_estilo
        self.add_item(self.select_estilo)

        self.select_categoria = discord.ui.ChannelSelect(
            placeholder="📁 Selecciona la categoría a modificar",
            channel_types=[discord.ChannelType.category],
            custom_id="select_categoria"
        )
        self.select_categoria.callback = self.callback_categoria
        self.add_item(self.select_categoria)

    async def callback_estilo(self, interaction: discord.Interaction):
        self.estilo_seleccionado = self.select_estilo.values[0]
        await interaction.response.defer()

    async def callback_categoria(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.estilo_seleccionado:
            return await interaction.followup.send("⚠️ Primero selecciona un estilo.", ephemeral=True)

        canal_id = int(self.select_categoria.values[0].id)
        categoria = interaction.guild.get_channel(canal_id)

        if not categoria:
            return await interaction.followup.send("❌ Categoría no encontrada.", ephemeral=True)

        nuevo_nombre = self.cog.construir_nombre_inteligente(
            texto_original=categoria.name,
            texto_nuevo=None,
            mapeo_fuente=self.fuentes[self.estilo_seleccionado],
            es_categoria=True
        )

        try:
            await categoria.edit(name=nuevo_nombre)
            await interaction.followup.send(f"🎨 Categoría rediseñada: **{nuevo_nombre}**", ephemeral=True)
        except discord.Forbidden as e:
            msg = "❌ Sin acceso (50001)." if e.code == 50001 else f"❌ Error de permisos: {e}"
            await interaction.followup.send(msg, ephemeral=True)
        except discord.HTTPException as e:
            msg = "⏳ Límite de Discord alcanzado (2 cambios cada 10 min)." if e.status == 429 else f"❌ Error: {e}"
            await interaction.followup.send(msg, ephemeral=True)


class Fuentes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        mistral_key = os.getenv("MISTRAL_API_KEY")
        self.mistral_client = openai.AsyncOpenAI(
            base_url="https://api.mistral.ai/v1/", 
            api_key=mistral_key, 
            timeout=15.0
        ) if mistral_key else None

        hf_key = os.getenv("HF_TOKEN")
        self.hf_client = openai.AsyncOpenAI(
            base_url="https://router.huggingface.co/v1/", 
            api_key=hf_key, 
            timeout=15.0
        ) if hf_key else None

    grupo_fuente = app_commands.Group(name="fuente", description="Gestión de tipografías")
    grupo_escanear = app_commands.Group(name="escanear", description="Escanear y guardar tipografías", parent=grupo_fuente)

    async def cargar_fuentes(self, guild_id: int) -> dict:
        if not self.bot.db or not guild_id: return {}
        def _read():
            doc = self.bot.db.collection("servidores").document(str(guild_id)).get()
            return doc.to_dict().get("fuentes", {}) if doc and doc.exists else {}
        try:
            return await asyncio.to_thread(_read)
        except Exception as e:
            print(f"Error cargando fuentes: {e}")
            return {}

    async def guardar_fuente(self, guild_id: int, nombre: str, mapeo: dict) -> bool:
        if not self.bot.db or not guild_id or not mapeo: return False
        def _write():
            self.bot.db.collection("servidores").document(str(guild_id)).set({"fuentes": {nombre.lower(): mapeo}}, merge=True)
            return True
        try:
            return await asyncio.to_thread(_write)
        except Exception as e:
            print(f"Error guardando fuente: {e}")
            return False

    async def eliminar_fuente(self, guild_id: int, nombre: str) -> bool:
        if not self.bot.db or not guild_id: return False
        def _delete():
            doc_ref = self.bot.db.collection("servidores").document(str(guild_id))
            doc = doc_ref.get()
            if doc.exists and nombre.lower() in doc.to_dict().get("fuentes", {}):
                doc_ref.update({f"fuentes.{nombre.lower()}": firestore.DELETE_FIELD})
                return True
            return False
        try:
            return await asyncio.to_thread(_delete)
        except Exception as e:
            print(f"Error eliminando fuente: {e}")
            return False
            
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
            
            code = ord(char)
            encontrado = False
            for _, a_start, a_low, num_start in RANGOS_UNICODE:
                if a_start and a_start <= code <= a_start + 25:
                    resultado.append(chr(ord('A') + (code - a_start)))
                    encontrado = True; break
                elif a_low and a_low <= code <= a_low + 25:
                    resultado.append(chr(ord('a') + (code - a_low)))
                    encontrado = True; break
                elif num_start and num_start <= code <= num_start + 9:
                    resultado.append(str(code - num_start))
                    encontrado = True; break
            if not encontrado:
                resultado.append(char)
        return "".join(resultado)

    def aplicar_mapeo(self, texto: str, mapeo: dict) -> str:
        res = []
        for char in texto:
            if char in mapeo: res.append(mapeo[char])
            elif char.islower() and char.upper() in mapeo: res.append(mapeo[char.upper()])
            elif char.isupper() and char.lower() in mapeo: res.append(mapeo[char.lower()])
            else: res.append(char)
        return "".join(res)

    def construir_nombre_inteligente(self, texto_original: str, texto_nuevo: str, mapeo_fuente: dict, emoji_opcional: str = None, es_categoria: bool = False) -> str:
        base_texto = texto_nuevo if texto_nuevo else texto_original
        texto_limpio = self.desestilizar_texto(base_texto)
        
        emojis_encontrados = EMOJI_REGEX.findall(texto_limpio)
        texto_sin_emojis = EMOJI_REGEX.sub("", texto_limpio)

        for sep in ["｜", "│", "|"]:
            if sep in texto_sin_emojis:
                texto_sin_emojis = texto_sin_emojis.split(sep)[-1]

        texto_sin_emojis = texto_sin_emojis.replace("-", " ").strip()
        texto_transformado = self.aplicar_mapeo(texto_sin_emojis, mapeo_fuente)

        if emojis_encontrados:
            emoji_usar = emojis_encontrados[0]
            resultado = f"{emoji_usar}｜{texto_transformado}"
        elif emoji_opcional:
            resultado = f"{texto_transformado} {emoji_opcional}"
        else:
            resultado = texto_transformado

        return resultado if es_categoria else resultado.replace(" ", "-")

    async def estilo_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id: return []
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        return [
            app_commands.Choice(name=n.capitalize(), value=n.lower())
            for n in fuentes.keys() if current.lower() in n.lower()
        ][:25]

    async def extraer_mapeo_fuente(self, ejemplo_texto: str) -> dict:
        mapeo_detectado = {}
        for char in ejemplo_texto:
            mapa_extrapolado = generar_bloque_completo(char)
            if mapa_extrapolado: return mapa_extrapolado
            base_char = unicodedata.normalize("NFKD", char)
            if len(base_char) == 1 and base_char != char and base_char.isalnum():
                mapeo_detectado[base_char] = char
            elif char in SMALL_CAPS_MAP:
                mapeo_detectado[SMALL_CAPS_MAP[char]] = char

        if len(mapeo_detectado) >= 15: return mapeo_detectado

        prompt = (
            f"Analiza la fuente en: '{ejemplo_texto}'. Genera un JSON mapeando todo el abecedario "
            "(a-z, A-Z) y números (0-9) en este estilo tipográfico.\n"
            "Responde ÚNICAMENTE el JSON sin bloques de código ni explicaciones.\n"
            'Ejemplo: {"a": "𝗮", "A": "𝗔"}'
        )

        if self.mistral_client:
            try:
                resp = await self.mistral_client.chat.completions.create(
                    model=MODELO_MISTRAL, messages=[{"role": "user", "content": prompt}], temperature=0.1
                )
                res = self._limpiar_json(resp.choices[0].message.content)
                if res: return res
            except Exception: pass

        if self.hf_client:
            try:
                resp = await self.hf_client.chat.completions.create(
                    model=MODELO_QWEN, messages=[{"role": "user", "content": prompt}], temperature=0.1
                )
                res = self._limpiar_json(resp.choices[0].message.content)
                if res: return res
            except Exception: pass

        if mapeo_detectado: return mapeo_detectado
        raise Exception("No se pudo detectar ni extrapolar la tipografía.")

    def _limpiar_json(self, texto: str) -> dict:
        try:
            t = texto.strip()
            if "```json" in t: t = t.split("```json")[1].split("```")[0].strip()
            elif "```" in t: t = t.split("```")[1].split("```")[0].strip()
            return json.loads(t)
        except Exception: return {}

    @grupo_escanear.command(name="mensaje", description="Extrae y completa una fuente desde un mensaje")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def escanear_mensaje(self, interaction: discord.Interaction, mensaje: str, nombre_guardar: str):
        await interaction.response.defer()
        if not self.bot.db: return await interaction.followup.send("❌ Firebase no disponible.")
        try:
            mapeo = await self.extraer_mapeo_fuente(mensaje)
            if await self.guardar_fuente(interaction.guild_id, nombre_guardar, mapeo):
                await interaction.followup.send(f"🧠 Fuente **{nombre_guardar}** guardada permanentemente ({len(mapeo)} caracteres).")
            else:
                await interaction.followup.send("❌ Error al guardar en Firebase.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al procesar: {e}")

    @grupo_escanear.command(name="canal", description="Extrae e infiere la fuente completa a partir de un canal")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def escanear_canal(self, interaction: discord.Interaction, canal: discord.TextChannel, nombre_guardar: str):
        await interaction.response.defer()
        if not self.bot.db: return await interaction.followup.send("❌ Firebase no disponible.")
        try:
            mapeo = await self.extraer_mapeo_fuente(canal.name)
            if await self.guardar_fuente(interaction.guild_id, nombre_guardar, mapeo):
                await interaction.followup.send(f"🧠 Fuente guardada desde {canal.mention} como **{nombre_guardar}** ({len(mapeo)} caracteres).")
            else:
                await interaction.followup.send("❌ Error al guardar en Firebase.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al procesar: {e}")

    @grupo_escanear.command(name="categoria", description="Extrae e infiere la fuente completa a partir de una categoría")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def escanear_categoria(self, interaction: discord.Interaction, categoria: discord.CategoryChannel, nombre_guardar: str):
        await interaction.response.defer()
        if not self.bot.db: return await interaction.followup.send("❌ Firebase no disponible.")
        try:
            mapeo = await self.extraer_mapeo_fuente(categoria.name)
            if await self.guardar_fuente(interaction.guild_id, nombre_guardar, mapeo):
                await interaction.followup.send(f"🧠 Fuente guardada desde la categoría **{categoria.name}** como **{nombre_guardar}**.")
            else:
                await interaction.followup.send("❌ Error al guardar en Firebase.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al procesar: {e}")

    @grupo_fuente.command(name="aplicar_canal", description="Aplica una fuente a un canal manteniendo su texto actual")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def aplicar_canal_cmd(self, interaction: discord.Interaction, canal: discord.TextChannel, estilo: str, emoji: str = None):
        await interaction.response.defer()
        if not self.bot.db: return await interaction.followup.send("❌ Firebase no disponible.")
        
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if estilo.lower() not in fuentes:
            return await interaction.followup.send(f"❌ Fuente **{estilo}** no encontrada.")
        
        nuevo_nombre = self.construir_nombre_inteligente(canal.name, None, fuentes[estilo.lower()], emoji, es_categoria=False)
        
        try:
            await canal.edit(name=nuevo_nombre)
            await interaction.followup.send(f"🎨 Canal rediseñado: {canal.mention}")
        except discord.Forbidden as e:
            msg = f"❌ **Sin Acceso (50001):** Revisa permisos en {canal.mention}." if e.code == 50001 else f"❌ Sin permisos: {e}"
            await interaction.followup.send(msg)
        except discord.HTTPException as e:
            msg = "⏳ Límite de Discord (2 cambios cada 10 min)." if e.status == 429 else f"❌ Error de Discord: {e}"
            await interaction.followup.send(msg)

    @grupo_fuente.command(name="aplicar_renombrar", description="Aplica una fuente y cambia el nombre del canal permitiendo mayúsculas")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def aplicar_renombrar_cmd(self, interaction: discord.Interaction, canal: discord.TextChannel, estilo: str, nuevo_nombre: str, emoji: str = None):
        await interaction.response.defer()
        if not self.bot.db: return await interaction.followup.send("❌ Firebase no disponible.")

        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if estilo.lower() not in fuentes:
            return await interaction.followup.send(f"❌ Fuente **{estilo}** no encontrada.")

        nombre_final = self.construir_nombre_inteligente(canal.name, nuevo_nombre, fuentes[estilo.lower()], emoji, es_categoria=False)

        try:
            await canal.edit(name=nombre_final)
            await interaction.followup.send(f"🎨 Canal renombrado y rediseñado: {canal.mention} (`{nombre_final}`)")
        except discord.Forbidden as e:
            msg = f"❌ **Sin Acceso (50001):** Revisa permisos en {canal.mention}." if e.code == 50001 else f"❌ Sin permisos: {e}"
            await interaction.followup.send(msg)
        except discord.HTTPException as e:
            msg = "⏳ Límite de Discord (2 cambios cada 10 min)." if e.status == 429 else f"❌ Error de Discord: {e}"
            await interaction.followup.send(msg)

    @grupo_fuente.command(name="aplicar_categoria", description="Aplica una fuente a una categoría")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def aplicar_categoria_cmd(self, interaction: discord.Interaction, categoria: discord.CategoryChannel, estilo: str, emoji: str = None):
        await interaction.response.defer()
        if not self.bot.db: return await interaction.followup.send("❌ Firebase no disponible.")
        
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if estilo.lower() not in fuentes:
            return await interaction.followup.send(f"❌ Fuente **{estilo}** no encontrada.")
        
        nuevo_nombre = self.construir_nombre_inteligente(categoria.name, None, fuentes[estilo.lower()], emoji, es_categoria=True)
        
        try:
            await categoria.edit(name=nuevo_nombre)
            await interaction.followup.send(f"🎨 Categoría rediseñada: **{nuevo_nombre}**")
        except discord.Forbidden as e:
            msg = f"❌ Sin acceso a **{categoria.name}**." if e.code == 50001 else f"❌ Permisos insuficientes: {e}"
            await interaction.followup.send(msg)
        except discord.HTTPException as e:
            msg = "⏳ Límite de Discord (2 cambios cada 10 min)." if e.status == 429 else f"❌ Error de Discord: {e}"
            await interaction.followup.send(msg)

    @grupo_fuente.command(name="menu_categoria", description="Menú interactivo desplegable para editar categorías")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def menu_categoria_cmd(self, interaction: discord.Interaction):
        if not self.bot.db: return await interaction.response.send_message("❌ Firebase no disponible.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if not fuentes:
            return await interaction.followup.send("📂 No hay tipografías guardadas.", ephemeral=True)

        vista = VistaAplicarCategoria(self, interaction.guild_id, fuentes)
        embed = discord.Embed(
            title="🛠️ Panel de Rediseño de Categorías",
            description="Elige un estilo y selecciona la categoría en los menús desplegables.",
            color=discord.Color.blurple()
        )
        await interaction.followup.send(embed=embed, view=vista, ephemeral=True)

    @grupo_fuente.command(name="listar", description="Muestra las tipografías guardadas en el servidor")
    async def listar_fuentes(self, interaction: discord.Interaction):
        if not self.bot.db: return await interaction.response.send_message("❌ Firebase no disponible.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if not fuentes:
            return await interaction.followup.send("📂 No hay tipografías guardadas.", ephemeral=True)
        
        embed = discord.Embed(title="🎨 Tipografías Registradas", color=discord.Color.blue())
        for nombre, mapeo in fuentes.items():
            ejemplo = self.construir_nombre_inteligente("canal-pruebas", None, mapeo, es_categoria=False)
            embed.add_field(name=f"📌 {nombre.capitalize()}", value=f"`{ejemplo}` ({len(mapeo)} chars)", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @grupo_fuente.command(name="probar", description="Muestra una vista previa de una fuente")
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def probar_fuente(self, interaction: discord.Interaction, texto: str, estilo: str, emoji: str = None):
        if not self.bot.db: return await interaction.response.send_message("❌ Firebase no disponible.", ephemeral=True)
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if estilo.lower() not in fuentes:
            return await interaction.response.send_message("❌ Fuente inexistente.", ephemeral=True)
        
        resultado = self.construir_nombre_inteligente(texto, None, fuentes[estilo.lower()], emoji, es_categoria=False)
        await interaction.response.send_message(f"👁️ **Vista Previa:** `{resultado}`")

    @grupo_fuente.command(name="eliminar", description="Elimina una fuente guardada")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.autocomplete(nombre=estilo_autocomplete)
    async def eliminar_fuente_cmd(self, interaction: discord.Interaction, nombre: str):
        if not self.bot.db: return await interaction.response.send_message("❌ Firebase no disponible.", ephemeral=True)
        if await self.eliminar_fuente(interaction.guild_id, nombre):
            await interaction.response.send_message(f"🗑️ Tipografía **{nombre}** eliminada de Firebase.")
        else:
            await interaction.response.send_message(f"❌ No se encontró la fuente **{nombre}**.")


async def setup(bot):
    await bot.add_cog(Fuentes(bot))
