import os
import json
import asyncio
import unicodedata
import discord
from discord import app_commands
from discord.ext import commands
from firebase_admin import firestore
import openai

MODELO_MISTRAL = "mistral-small-latest"
MODELO_QWEN = "Qwen/Qwen2.5-Coder-32B-Instruct"

# --- BLOQUES UNICODE PARA EXTRAPOLACIÓN AUTOMÁTICA (0 MS) ---
RANGOS_UNICODE = [
    # (Nombre estilo, A_start, a_start, num_start)
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
    """Detecta el bloque Unicode de un carácter y reconstruye A-Z, a-z, 0-9."""
    code = ord(char_muestra)
    mapeo_completo = {}

    for _, a_start, a_low_start, num_start in RANGOS_UNICODE:
        # Verificar si pertenece al rango Mayúsculas
        if a_start and a_start <= code <= a_start + 25:
            shift_upper = code - a_start
            for i in range(26):
                mapeo_completo[chr(ord('A') + i)] = chr(a_start + i)
                if a_low_start:
                    mapeo_completo[chr(ord('a') + i)] = chr(a_low_start + i)
            if num_start:
                for i in range(10):
                    mapeo_completo[str(i)] = chr(num_start + i)
            return mapeo_completo

        # Verificar si pertenece al rango Minúsculas
        elif a_low_start and a_low_start <= code <= a_low_start + 25:
            for i in range(26):
                if a_start:
                    mapeo_completo[chr(ord('A') + i)] = chr(a_start + i)
                mapeo_completo[chr(ord('a') + i)] = chr(a_low_start + i)
            if num_start:
                for i in range(10):
                    mapeo_completo[str(i)] = chr(num_start + i)
            return mapeo_completo

    return {}


# --- VISTA INTERACTIVA DE MENÚ DESPLEGABLE PARA CATEGORÍAS ---

class VistaAplicarCategoria(discord.ui.View):
    def __init__(self, cog, guild_id: int, fuentes: dict):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.fuentes = fuentes
        self.categoria_seleccionada = None
        self.estilo_seleccionado = None

        # Selector de Estilos
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

        # Selector Nativo de Categorías de Discord
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
            return await interaction.followup.send("⚠️ Primero selecciona un estilo del menú.", ephemeral=True)

        canal_id = int(self.select_categoria.values[0].id)
        categoria = interaction.guild.get_channel(canal_id)

        if not categoria:
            return await interaction.followup.send("❌ No se encontró la categoría elegida.", ephemeral=True)

        # Aplicar transformación
        mapeo = self.fuentes[self.estilo_seleccionado]
        nombre_limpio = categoria.name.split("｜")[-1].split("│")[-1].strip()
        texto_transformado = self.cog.aplicar_mapeo(nombre_limpio, mapeo, es_categoria=True)
        nuevo_nombre = f"📁｜{texto_transformado}"

        try:
            await categoria.edit(name=nuevo_nombre)
            await interaction.followup.send(f"🎨 ¡Categoría rediseñada con éxito!: **{nuevo_nombre}**", ephemeral=True)
        except discord.Forbidden as e:
            if e.code == 50001:
                await interaction.followup.send("❌ Error de permisos (50001): El bot no tiene acceso o permisos para gestionar esa categoría.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Sin permisos para modificar la categoría: {e}", ephemeral=True)
        except discord.HTTPException as e:
            if e.status == 429:
                await interaction.followup.send("⏳ Discord limita la edición de canales/categorías a 2 veces cada 10 minutos.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Error al renombrar: {e}", ephemeral=True)


class Fuentes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Clientes API persistentes
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

    # --- BASE DE DATOS FIRESTORE ASÍNCRONA ---

    async def cargar_fuentes(self, guild_id: int) -> dict:
        if not self.bot.db or not guild_id:
            return {}
        
        def _read():
            doc = self.bot.db.collection("servidores").document(str(guild_id)).get()
            if doc and doc.exists:
                return doc.to_dict().get("fuentes", {})
            return {}

        try:
            return await asyncio.to_thread(_read)
        except Exception as e:
            print(f"Error cargando fuentes de Firebase: {e}")
            return {}

    async def guardar_fuente(self, guild_id: int, nombre: str, mapeo: dict) -> bool:
        if not self.bot.db or not guild_id or not mapeo:
            return False
        
        def _write():
            doc_ref = self.bot.db.collection("servidores").document(str(guild_id))
            doc_ref.set({"fuentes": {nombre.lower(): mapeo}}, merge=True)
            return True

        try:
            return await asyncio.to_thread(_write)
        except Exception as e:
            print(f"Error guardando fuente en Firebase: {e}")
            return False

    async def eliminar_fuente(self, guild_id: int, nombre: str) -> bool:
        if not self.bot.db or not guild_id:
            return False
        
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
            print(f"Error eliminando fuente de Firebase: {e}")
            return False

    # --- TRANSFORMACIÓN DE TEXTO ---

    def aplicar_mapeo(self, texto: str, mapeo: dict, es_categoria: bool = False) -> str:
        resultado = []
        for char in texto:
            if char in mapeo:
                resultado.append(mapeo[char])
            elif char.islower() and char.upper() in mapeo:
                resultado.append(mapeo[char.upper()])
            elif char.isupper() and char.lower() in mapeo:
                resultado.append(mapeo[char.lower()])
            else:
                resultado.append(char)
        
        texto_final = "".join(resultado)
        if not es_categoria:
            # Los canales de texto requieren guiones
            return texto_final.replace(" ", "-")
        # Las categorías permiten espacios y mayúsculas
        return texto_final

    async def estilo_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        opciones = []
        for nombre in fuentes.keys():
            if current.lower() in nombre.lower():
                opciones.append(app_commands.Choice(name=nombre.capitalize(), value=nombre.lower()))
        return opciones[:25]

    # --- ESCÁNER CON DEDUCCIÓN UNICODE E EXTRAPOLACIÓN POR IA ---

    async def extraer_mapeo_fuente(self, ejemplo_texto: str) -> dict:
        mapeo_detectado = {}

        # 1. Intentar reconstrucción matemática completa por rango Unicode
        for char in ejemplo_texto:
            mapa_extrapolado = generar_bloque_completo(char)
            if mapa_extrapolado:
                return mapa_extrapolado

            # Normalización directa para fuentes simples
            base_char = unicodedata.normalize("NFKD", char)
            if len(base_char) == 1 and base_char != char and base_char.isalnum():
                mapeo_detectado[base_char] = char
            elif char in SMALL_CAPS_MAP:
                mapeo_detectado[SMALL_CAPS_MAP[char]] = char

        # Si escaneó más de 15 caracteres aislados, los usa directamente
        if len(mapeo_detectado) >= 15:
            return mapeo_detectado

        # 2. Si es una fuente parcial o personalizada, solicitar a la IA completar el abecedario
        prompt = (
            f"El usuario proporcionó este texto/canal con una fuente especial: '{ejemplo_texto}'.\n"
            "Identifica el estilo tipográfico exacto y genera un JSON mapeando TODO el abecedario "
            "(a-z, A-Z) y los números (0-9) en ese mismo estilo estilizado.\n"
            "Responde ÚNICAMENTE el JSON sin bloques de código ni comentarios.\n"
            'Ejemplo: {"a": "𝗮", "b": "𝗯", ..., "A": "𝗔", "0": "𝟬"}'
        )

        if self.mistral_client:
            try:
                resp = await self.mistral_client.chat.completions.create(
                    model=MODELO_MISTRAL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=800
                )
                res = self._limpiar_json(resp.choices[0].message.content)
                if res: return res
            except Exception as e:
                print(f"Mistral fallo completando fuente: {e}")

        if self.hf_client:
            try:
                resp = await self.hf_client.chat.completions.create(
                    model=MODELO_QWEN,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=800
                )
                res = self._limpiar_json(resp.choices[0].message.content)
                if res: return res
            except Exception as e:
                print(f"Hugging Face fallo completando fuente: {e}")

        if mapeo_detectado:
            return mapeo_detectado

        raise Exception("No se pudo detectar o extrapolar la tipografía del texto proporcionado.")

    def _limpiar_json(self, texto: str) -> dict:
        try:
            texto_limpio = texto.strip()
            if "```json" in texto_limpio:
                texto_limpio = texto_limpio.split("```json")[1].split("```")[0].strip()
            elif "```" in texto_limpio:
                texto_limpio = texto_limpio.split("```")[1].split("```")[0].strip()
            return json.loads(texto_limpio)
        except Exception:
            return {}

    # --- COMANDOS SLASH: ESCANEAR ---

    @grupo_escanear.command(name="mensaje", description="Extrae y completa una fuente desde un mensaje o abecedario")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def escanear_mensaje(self, interaction: discord.Interaction, mensaje: str, nombre_guardar: str):
        await interaction.response.defer()
        if not self.bot.db:
            return await interaction.followup.send("❌ La base de datos Firebase no está disponible.")
        try:
            mapeo = await self.extraer_mapeo_fuente(mensaje)
            if await self.guardar_fuente(interaction.guild_id, nombre_guardar, mapeo):
                await interaction.followup.send(
                    f"🧠 Se analizó la muestra, la IA completó el abecedario (**{len(mapeo)}** caracteres) y se guardó la fuente **{nombre_guardar}** permanentemente."
                )
            else:
                await interaction.followup.send("❌ No se pudo guardar la fuente en Firebase.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al procesar la tipografía: {e}")

    @grupo_escanear.command(name="canal", description="Extrae e infiere la fuente completa a partir del nombre de un canal")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def escanear_canal(self, interaction: discord.Interaction, canal: discord.TextChannel, nombre_guardar: str):
        await interaction.response.defer()
        if not self.bot.db:
            return await interaction.followup.send("❌ La base de datos Firebase no está disponible.")
        try:
            mapeo = await self.extraer_mapeo_fuente(canal.name)
            if await self.guardar_fuente(interaction.guild_id, nombre_guardar, mapeo):
                await interaction.followup.send(
                    f"🧠 Se analizó {canal.mention}, se recreó el estilo completo (**{len(mapeo)}** caracteres) y se guardó como **{nombre_guardar}**."
                )
            else:
                await interaction.followup.send("❌ No se pudo guardar la fuente en Firebase.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al procesar la tipografía: {e}")

    @grupo_escanear.command(name="categoria", description="Extrae e infiere la fuente completa a partir de una categoría")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def escanear_categoria(self, interaction: discord.Interaction, categoria: discord.CategoryChannel, nombre_guardar: str):
        await interaction.response.defer()
        if not self.bot.db:
            return await interaction.followup.send("❌ La base de datos Firebase no está disponible.")
        try:
            mapeo = await self.extraer_mapeo_fuente(categoria.name)
            if await self.guardar_fuente(interaction.guild_id, nombre_guardar, mapeo):
                await interaction.followup.send(
                    f"🧠 Se analizó la categoría **{categoria.name}**, se recreó el estilo completo (**{len(mapeo)}** caracteres) y se guardó como **{nombre_guardar}**."
                )
            else:
                await interaction.followup.send("❌ No se pudo guardar la fuente en Firebase.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al procesar la tipografía: {e}")

    # --- COMANDOS SLASH: APLICAR Y GESTIONAR ---

    @grupo_fuente.command(name="aplicar_canal", description="Aplica una fuente guardada al nombre de un canal de texto")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def aplicar_canal_cmd(self, interaction: discord.Interaction, canal: discord.TextChannel, estilo: str, emoji: str = "💬"):
        await interaction.response.defer()
        if not self.bot.db:
            return await interaction.followup.send("❌ La base de datos Firebase no está disponible.")
        
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if estilo.lower() not in fuentes:
            return await interaction.followup.send(f"❌ Fuente **{estilo}** no encontrada en la base de datos.")
        
        nombre_limpio = canal.name.split("｜")[-1].split("│")[-1].replace("-", " ").strip()
        texto_transformado = self.aplicar_mapeo(nombre_limpio, fuentes[estilo.lower()], es_categoria=False)
        nuevo_nombre = f"{emoji}｜{texto_transformado}"
        
        try:
            await canal.edit(name=nuevo_nombre)
            await interaction.followup.send(f"🎨 Canal rediseñado: {canal.mention}")
        except discord.Forbidden as e:
            if e.code == 50001:
                await interaction.followup.send(f"❌ **Sin Acceso (50001):** El bot necesita permisos de **Ver Canal** y **Gestionar Canales** en {canal.mention}.")
            else:
                await interaction.followup.send(f"❌ Permisos insuficientes en {canal.mention}.")
        except discord.HTTPException as e:
            if e.status == 429:
                await interaction.followup.send("⏳ Discord limita el renombrado a 2 veces cada 10 minutos por canal.")
            else:
                await interaction.followup.send(f"❌ Error de Discord: {e}")

    @grupo_fuente.command(name="aplicar_categoria", description="Aplica una fuente guardada al nombre de una categoría")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def aplicar_categoria_cmd(self, interaction: discord.Interaction, categoria: discord.CategoryChannel, estilo: str, emoji: str = "📁"):
        await interaction.response.defer()
        if not self.bot.db:
            return await interaction.followup.send("❌ La base de datos Firebase no está disponible.")
        
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if estilo.lower() not in fuentes:
            return await interaction.followup.send(f"❌ Fuente **{estilo}** no encontrada en la base de datos.")
        
        nombre_limpio = categoria.name.split("｜")[-1].split("│")[-1].strip()
        texto_transformado = self.aplicar_mapeo(nombre_limpio, fuentes[estilo.lower()], es_categoria=True)
        nuevo_nombre = f"{emoji}｜{texto_transformado}"
        
        try:
            await categoria.edit(name=nuevo_nombre)
            await interaction.followup.send(f"🎨 Categoría rediseñada: **{nuevo_nombre}**")
        except discord.Forbidden as e:
            if e.code == 50001:
                await interaction.followup.send(f"❌ **Sin Acceso (50001):** El bot necesita permisos en la categoría **{categoria.name}**.")
            else:
                await interaction.followup.send(f"❌ Permisos insuficientes en la categoría **{categoria.name}**.")
        except discord.HTTPException as e:
            if e.status == 429:
                await interaction.followup.send("⏳ Discord limita la edición a 2 veces cada 10 minutos.")
            else:
                await interaction.followup.send(f"❌ Error de Discord: {e}")

    @grupo_fuente.command(name="menu_categoria", description="Despliega un menú interactivo de selección para personalizar categorías")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def menu_categoria_cmd(self, interaction: discord.Interaction):
        if not self.bot.db:
            return await interaction.response.send_message("❌ La base de datos Firebase no está disponible.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        
        if not fuentes:
            return await interaction.followup.send("📂 No hay tipografías guardadas en este servidor.", ephemeral=True)

        vista = VistaAplicarCategoria(self, interaction.guild_id, fuentes)
        embed = discord.Embed(
            title="🛠️ Panel de Rediseño de Categorías",
            description="Selecciona el estilo que deseas aplicar y la categoría que quieres personalizar en las listas desplegables de abajo.",
            color=discord.Color.blurple()
        )
        await interaction.followup.send(embed=embed, view=vista, ephemeral=True)

    @grupo_fuente.command(name="listar", description="Muestra las tipografías guardadas en el servidor")
    async def listar_fuentes(self, interaction: discord.Interaction):
        if not self.bot.db:
            return await interaction.response.send_message("❌ La base de datos Firebase no está disponible.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        
        if not fuentes:
            return await interaction.followup.send("📂 No hay tipografías guardadas en este servidor.", ephemeral=True)
        
        embed = discord.Embed(title="🎨 Tipografías Registradas", color=discord.Color.blue())
        for nombre, mapeo in fuentes.items():
            ejemplo_preview = self.aplicar_mapeo("canal-pruebas", mapeo, es_categoria=False)
            embed.add_field(name=f"📌 {nombre.capitalize()}", value=f"`{ejemplo_preview}` ({len(mapeo)} caracteres)", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @grupo_fuente.command(name="probar", description="Genera una vista previa de un texto con una fuente")
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def probar_fuente(self, interaction: discord.Interaction, texto: str, estilo: str, emoji: str = "💬"):
        if not self.bot.db:
            return await interaction.response.send_message("❌ La base de datos Firebase no está disponible.", ephemeral=True)
        
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if estilo.lower() not in fuentes:
            return await interaction.response.send_message("❌ Fuente inexistente.", ephemeral=True)
        
        resultado = f"{emoji}｜{self.aplicar_mapeo(texto, fuentes[estilo.lower()], es_categoria=False)}"
        await interaction.response.send_message(f"👁️ **Vista Previa:** `{resultado}`")

    @grupo_fuente.command(name="eliminar", description="Elimina una fuente del servidor")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.autocomplete(nombre=estilo_autocomplete)
    async def eliminar_fuente_cmd(self, interaction: discord.Interaction, nombre: str):
        if not self.bot.db:
            return await interaction.response.send_message("❌ La base de datos Firebase no me permite conectar.", ephemeral=True)
        
        if await self.eliminar_fuente(interaction.guild_id, nombre):
            await interaction.response.send_message(f"🗑️ Tipografía **{nombre}** eliminada de Firebase.")
        else:
            await interaction.response.send_message(f"❌ No se encontró la fuente **{nombre}**.")

async def setup(bot):
    await bot.add_cog(Fuentes(bot))
