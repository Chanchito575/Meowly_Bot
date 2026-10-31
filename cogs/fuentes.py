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

MODELO_MISTRAL = os.getenv("MODELO_MISTRAL", "mistral-small-latest")
MODELO_QWEN = os.getenv("MODELO_QWEN", "Qwen/Qwen2.5-72B-Instruct")
MODELO_GROQ = os.getenv("MODELO_GROQ", "openai/gpt-oss-120b")

MAX_FUENTES = 25       
CACHE_TTL = 30.0      


def leer_key(*nombres: str):
    """Lee la primera variable de entorno que exista, limpiando espacios, saltos de línea y comillas."""
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
    """Error con un mensaje seguro para mostrárselo al usuario."""

EMOJI_REGEX = re.compile(
    r"(<a?:\w+:\d+>|[\U00010000-\U0010ffff\u2600-\u27ff\u2300-\u23ff\u2B50\u200d]+)"
)
RANGOS_UNICODE = [
    ("Sans-Serif Bold", 0x1D5D4, 0x1D5EE, 0x1D7EC),
    ("Sans-Serif Regular", 0x1D5A0, 0x1D5BA, 0x1D7E2),
    ("Sans-Serif Italic", 0x1D608, 0x1D622, None),
    ("Sans-Serif Bold Italic", 0x1D63C, 0x1D656, None),
    ("Serif Bold", 0x1D400, 0x1D41A, 0x1D7CE),
    ("Serif Italic", 0x1D434, 0x1D44E, None),
    ("Serif Bold Italic", 0x1D468, 0x1D482, None),
    ("Script Bold", 0x1D4D0, 0x1D4EA, None),
    ("Fraktur Bold", 0x1D56C, 0x1D586, None),
    ("Monospace", 0x1D670, 0x1D68A, 0x1D7F6),
    ("Double-Struck", 0x1D538, 0x1D552, 0x1D7D8),
    ("Circled", 0x24B6, 0x24D0, None),
    ("Fullwidth", 0xFF21, 0xFF41, 0xFF10),
]

EXCEPCIONES_GLIFOS = {
    "Serif Italic": {"h": "ℎ"},
    "Double-Struck": {"C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ", "R": "ℝ", "Z": "ℤ"},
    "Circled": {"0": "⓪", **{str(i): chr(0x2460 + i - 1) for i in range(1, 10)}},
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


def generar_bloque_completo(char_muestra: str) -> dict:
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
            return mapeo
    return {}


def normalizar_nombre_fuente(nombre: str) -> str:
    nombre = " ".join(nombre.strip().lower().split())
    if not re.fullmatch(r"[\w\- ]{1,32}", nombre):
        raise ErrorFuente(
            "El nombre solo puede tener letras, números, espacios, guiones y guion bajo (máximo 32 caracteres)."
        )
    return nombre

class VistaAplicarElemento(discord.ui.View):
    def __init__(self, cog, guild_id: int, fuentes: dict, autor_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.fuentes = fuentes
        self.autor_id = autor_id
        self.estilo_seleccionado = None

        nombres = [n for n in fuentes.keys() if 0 < len(n) <= 100][:MAX_FUENTES]
        opciones_estilos = [
            discord.SelectOption(label=n.capitalize()[:100], value=n)
            for n in nombres
        ]
        self.select_estilo = discord.ui.Select(
            placeholder="🎨 Selecciona un estilo registrado",
            options=opciones_estilos,
        )
        self.select_estilo.callback = self.callback_estilo
        self.add_item(self.select_estilo)

        self.select_canal = discord.ui.ChannelSelect(
            placeholder="📁 Selecciona canal (Texto, Voz o Categoría)",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.voice,
                discord.ChannelType.stage_voice,
                discord.ChannelType.forum,
                discord.ChannelType.category,
            ],
        )
        self.select_canal.callback = self.callback_canal
        self.add_item(self.select_canal)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Este menú solo funciona en un servidor.", ephemeral=True)
            return False
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Este menú pertenece a otra persona.", ephemeral=True)
            return False
        if not (interaction.user.guild_permissions.manage_channels or interaction.permissions.manage_channels):
            await interaction.response.send_message(
                "❌ No tienes permisos de 'Gestionar canales' para usar este menú.", ephemeral=True
            )
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        print(f"⚠️ Error en el menú de fuentes: {type(error).__name__}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        msg = "❌ Ocurrió un error inesperado en el menú."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    async def callback_estilo(self, interaction: discord.Interaction):
        self.estilo_seleccionado = self.select_estilo.values[0]
        for opcion in self.select_estilo.options:
            opcion.default = opcion.value == self.estilo_seleccionado
        await interaction.response.edit_message(view=self)

    async def callback_canal(self, interaction: discord.Interaction):
        if not self.estilo_seleccionado:
            return await interaction.response.send_message(
                "⚠️ Primero selecciona un estilo en el menú superior.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        target = interaction.guild.get_channel(self.select_canal.values[0].id)
        if target is None:
            return await interaction.followup.send("❌ Elemento no encontrado.", ephemeral=True)

        mapeo = self.fuentes.get(self.estilo_seleccionado)
        if not mapeo:
            return await interaction.followup.send("❌ Ese estilo ya no existe.", ephemeral=True)

        nuevo_nombre = self.cog.construir_nombre_inteligente(
            texto_original=target.name,
            texto_nuevo=None,
            mapeo_fuente=mapeo,
            es_categoria_o_voz=self.cog.es_categoria_o_voz(target),
        )
        _, msg = await self.cog.editar_nombre(interaction, target, nuevo_nombre)
        await interaction.followup.send(msg, ephemeral=True)
        try:
            await interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass

class Fuentes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cache = {}

        def crear(base_url, key):
            if not key:
                return None
            return openai.AsyncOpenAI(base_url=base_url, api_key=key, timeout=25.0, max_retries=1)

        self.groq_client = crear("https://api.groq.com/openai/v1", leer_key("GROQ_API_KEY", "GROQ_KEY"))
        self.mistral_client = crear("https://api.mistral.ai/v1/", leer_key("MISTRAL_API_KEY", "MISTRAL_KEY"))
        self.hf_client = crear(
            "https://router.huggingface.co/v1/",
            leer_key("HF_TOKEN", "HUGGINGFACE_API_KEY", "HF_API_KEY", "QWEN_API_KEY"),
        )

    async def cog_unload(self):
        for cliente in (self.groq_client, self.mistral_client, self.hf_client):
            if cliente:
                try:
                    await cliente.close()
                except Exception:
                    pass

    grupo_fuente = app_commands.Group(name="fuente", description="Gestión de tipografías", guild_only=True)
    grupo_escanear = app_commands.Group(
        name="escanear", description="Escanear y guardar tipografías", parent=grupo_fuente
    )
    async def cargar_fuentes(self, guild_id: int, usar_cache: bool = True) -> dict:
        if not self.bot.db or not guild_id:
            return {}

        guardado = self._cache.get(guild_id)
        if usar_cache and guardado and time.monotonic() - guardado[0] < CACHE_TTL:
            return guardado[1]

        def _read():
            doc = self.bot.db.collection("servidores").document(str(guild_id)).get()
            if doc and doc.exists:
                data = doc.to_dict()
                return data.get("fuentes", {}) if data else {}
            return {}

        try:
            fuentes = await asyncio.to_thread(_read)
            self._cache[guild_id] = (time.monotonic(), fuentes)
            return fuentes
        except Exception as e:
            print(f"⚠️ Error cargando fuentes: {type(e).__name__}: {e}")
            return guardado[1] if guardado else {}

    async def guardar_fuente(self, guild_id: int, nombre: str, mapeo: dict) -> None:
        if not self.bot.db or not guild_id or not mapeo:
            raise ErrorFuente("No se pudo guardar: Firebase no está disponible.")

        existentes = await self.cargar_fuentes(guild_id, usar_cache=False)
        if nombre not in existentes and len(existentes) >= MAX_FUENTES:
            raise ErrorFuente(
                f"Este servidor ya tiene {MAX_FUENTES} fuentes (el máximo). Elimina alguna con `/fuente eliminar`."
            )

        def _write():
            ref = self.bot.db.collection("servidores").document(str(guild_id))
            ref.set({"fuentes": {nombre: firestore.DELETE_FIELD}}, merge=True)
            ref.set({"fuentes": {nombre: mapeo}}, merge=True)

        try:
            await asyncio.to_thread(_write)
        except Exception as e:
            print(f"⚠️ Error guardando fuente: {type(e).__name__}: {e}")
            raise ErrorFuente("Error al guardar en Firebase.")
        finally:
            self._cache.pop(guild_id, None)

    async def eliminar_fuente(self, guild_id: int, nombre: str) -> bool:
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
            print(f"⚠️ Error eliminando fuente: {type(e).__name__}: {e}")
            return False
        finally:
            self._cache.pop(guild_id, None)

    async def _sin_db(self, interaction: discord.Interaction) -> bool:
        if self.bot.db:
            return False
        await interaction.response.send_message("❌ Firebase no disponible.", ephemeral=True)
        return True

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

    def construir_nombre_inteligente(self, texto_original: str, texto_nuevo, mapeo_fuente: dict,
                                     es_categoria_o_voz: bool = False) -> str:
        base_texto = texto_nuevo if texto_nuevo else texto_original
        texto_limpio = self.desestilizar_texto(base_texto)

        resultado = []
        pos = 0
        for match in EMOJI_REGEX.finditer(texto_limpio):
            start, end = match.span()
            if start > pos:
                resultado.append(self.aplicar_mapeo(texto_limpio[pos:start], mapeo_fuente))
            resultado.append(match.group(0))
            pos = end
        if pos < len(texto_limpio):
            resultado.append(self.aplicar_mapeo(texto_limpio[pos:], mapeo_fuente))

        nombre_final = "".join(resultado)
        return nombre_final if es_categoria_o_voz else nombre_final.replace(" ", "-")

    @staticmethod
    def es_categoria_o_voz(canal) -> bool:
        return isinstance(canal, (discord.CategoryChannel, discord.VoiceChannel, discord.StageChannel))

    async def estilo_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []
        try:
            fuentes = await self.cargar_fuentes(interaction.guild_id)
        except Exception:
            return []
        return [
            app_commands.Choice(name=n.capitalize()[:100], value=n[:100])
            for n in fuentes.keys() if current.lower() in n.lower()
        ][:25]

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

    async def _pedir_mapeo_a_ia(self, ejemplo_texto: str) -> dict:
        prompt = (
            f"Analiza la fuente en: '{ejemplo_texto}'. Genera un JSON mapeando todo el abecedario "
            "(a-z, A-Z) y números (0-9) en este estilo tipográfico.\n"
            "Responde ÚNICAMENTE el JSON sin bloques de código ni explicaciones.\n"
            'Ejemplo: {"a": "𝗮", "A": "𝗔"}'
        )
        proveedores = (
            ("Groq", self.groq_client, MODELO_GROQ),
            ("Mistral", self.mistral_client, MODELO_MISTRAL),
            ("Qwen", self.hf_client, MODELO_QWEN),
        )
        for nombre, cliente, modelo in proveedores:
            if not cliente:
                continue
            try:
                resp = await cliente.chat.completions.create(
                    model=modelo,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=3000,
                )
                res = self._validar_mapeo(self._limpiar_json(resp.choices[0].message.content))
                if res:
                    return res
                print(f"⚠️ Fuentes/{nombre}: la respuesta no trajo un mapeo válido.")
            except Exception as e:
                print(f"⚠️ Fuentes/{nombre} falló: {describir_error(e)}")
        return {}

    async def extraer_mapeo_fuente(self, ejemplo_texto: str) -> dict:
        mapeo_detectado = {}
        for char in ejemplo_texto:
            mapa_extrapolado = generar_bloque_completo(char)
            if mapa_extrapolado:
                return mapa_extrapolado
            base_char = unicodedata.normalize("NFKD", char)
            if len(base_char) == 1 and base_char != char and base_char.isalnum():
                mapeo_detectado[base_char] = char
            elif char in SMALL_CAPS_MAP:
                mapeo_detectado[SMALL_CAPS_MAP[char]] = char

        if len(mapeo_detectado) >= 15:
            return mapeo_detectado

        hay_letras_raras = any(
            c.isalpha() and not c.isascii() and not unicodedata.normalize("NFD", c)[0].isascii()
            for c in ejemplo_texto
        )
        if not mapeo_detectado and not hay_letras_raras:
            raise ErrorFuente(
                "No detecté ninguna tipografía especial en ese texto. "
                "Escribe algo con la fuente que quieres guardar, por ejemplo 𝗠𝗲𝗼𝘄𝗹𝘆 o ᴍᴇᴏᴡʟʏ."
            )

        res = await self._pedir_mapeo_a_ia(ejemplo_texto)
        if res:
            return res
        if mapeo_detectado:
            return mapeo_detectado
        raise ErrorFuente("No se pudo detectar ni extrapolar la tipografía.")

    async def editar_nombre(self, interaction: discord.Interaction, target, nuevo_nombre: str):
        """Renombra un canal/categoría comprobando permisos. Devuelve (ok, mensaje)."""
        if not isinstance(target, TIPOS_EDITABLES):
            return False, "❌ Ese tipo de elemento no se puede rediseñar (solo canales, foros, escenarios y categorías)."

        nuevo_nombre = nuevo_nombre.strip()[:100]
        if not nuevo_nombre:
            return False, "❌ El nombre resultante quedó vacío."

        if not target.permissions_for(interaction.user).manage_channels:
            return False, f"❌ No tienes permiso de 'Gestionar canales' en **{target.name}**."

        yo = interaction.guild.me if interaction.guild else None
        if yo is not None and not target.permissions_for(yo).manage_channels:
            return False, (
                f"❌ No tengo permiso de 'Gestionar canales' en **{target.name}**. "
                "Revisa el rol del bot y los permisos de ese canal."
            )

        if target.name == nuevo_nombre:
            return False, "ℹ️ Ese elemento ya tiene ese estilo, no hay nada que cambiar."

        try:
            await asyncio.wait_for(
                target.edit(name=nuevo_nombre, reason=f"Fuente aplicada por {interaction.user} ({interaction.user.id})"),
                timeout=20,
            )
            return True, f"🎨 Elemento rediseñado con éxito: **{nuevo_nombre}**"
        except asyncio.TimeoutError:
            return False, "⏳ Discord limita los cambios de nombre de un mismo canal (2 cada 10 minutos). Inténtalo más tarde."
        except discord.Forbidden as e:
            if getattr(e, "code", None) == 50001:
                return False, f"❌ **Sin acceso (50001):** revisa los permisos en **{target.name}**."
            return False, "❌ Discord no me dejó hacer ese cambio: revisa los permisos y la posición del rol del bot."
        except discord.HTTPException as e:
            if e.status == 429:
                return False, "⏳ Límite de Discord alcanzado (2 cambios cada 10 minutos). Inténtalo más tarde."
            if e.status == 400:
                return False, "❌ Discord rechazó el nombre resultante (puede ser inválido o demasiado largo)."
            print(f"⚠️ Error de Discord al renombrar: {e}")
            return False, "❌ Error de Discord al cambiar el nombre."

    async def _escanear_y_guardar(self, interaction: discord.Interaction, muestra: str,
                                  nombre_guardar: str, origen: str):
        if await self._sin_db(interaction):
            return
        await interaction.response.defer()
        try:
            nombre = normalizar_nombre_fuente(nombre_guardar)
            mapeo = await self.extraer_mapeo_fuente(muestra)
            await self.guardar_fuente(interaction.guild_id, nombre, mapeo)
            await interaction.followup.send(f"🧠 Fuente **{nombre}** guardada{origen} ({len(mapeo)} caracteres).")
        except ErrorFuente as e:
            await interaction.followup.send(f"❌ {e}")
        except Exception as e:
            print(f"⚠️ Error al escanear fuente: {type(e).__name__}: {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Ocurrió un error al procesar la fuente. Inténtalo de nuevo.")

    async def _aplicar(self, interaction: discord.Interaction, elemento, estilo: str, texto_nuevo):
        if await self._sin_db(interaction):
            return
        await interaction.response.defer()

        estilo = estilo.strip().lower()
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if estilo not in fuentes:
            return await interaction.followup.send(f"❌ Fuente **{estilo}** no encontrada.")

        nombre_final = self.construir_nombre_inteligente(
            elemento.name, texto_nuevo, fuentes[estilo], es_categoria_o_voz=self.es_categoria_o_voz(elemento)
        )
        _, msg = await self.editar_nombre(interaction, elemento, nombre_final)
        await interaction.followup.send(msg)

    @grupo_escanear.command(name="mensaje", description="Extrae y completa una fuente desde un mensaje")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(mensaje="Texto escrito con la tipografía que quieres guardar",
                           nombre_guardar="Nombre con el que se guardará la fuente")
    async def escanear_mensaje(self, interaction: discord.Interaction,
                               mensaje: app_commands.Range[str, 1, 100],
                               nombre_guardar: app_commands.Range[str, 1, 32]):
        await self._escanear_y_guardar(interaction, mensaje, nombre_guardar, "")

    @grupo_escanear.command(name="canal", description="Extrae e infiere la fuente completa a partir de un canal de texto o voz")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(canal="Canal cuyo nombre usa la tipografía",
                           nombre_guardar="Nombre con el que se guardará la fuente")
    async def escanear_canal(self, interaction: discord.Interaction, canal: discord.abc.GuildChannel,
                             nombre_guardar: app_commands.Range[str, 1, 32]):
        await self._escanear_y_guardar(interaction, canal.name, nombre_guardar, f" desde **{canal.name}**")

    @grupo_escanear.command(name="categoria", description="Extrae e infiere la fuente completa a partir de una categoría")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(categoria="Categoría cuyo nombre usa la tipografía",
                           nombre_guardar="Nombre con el que se guardará la fuente")
    async def escanear_categoria(self, interaction: discord.Interaction, categoria: discord.CategoryChannel,
                                 nombre_guardar: app_commands.Range[str, 1, 32]):
        await self._escanear_y_guardar(interaction, categoria.name, nombre_guardar,
                                       f" desde la categoría **{categoria.name}**")

    @grupo_fuente.command(name="aplicar_canal", description="Aplica una fuente a un canal (texto o voz) manteniendo su nombre actual")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(canal="Canal o categoría a rediseñar", estilo="Fuente guardada que quieres aplicar")
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def aplicar_canal_cmd(self, interaction: discord.Interaction, canal: discord.abc.GuildChannel, estilo: str):
        await self._aplicar(interaction, canal, estilo, None)

    @grupo_fuente.command(name="aplicar_renombrar", description="Aplica una fuente y renombra un canal de texto, voz o categoría")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(elemento="Canal o categoría a rediseñar", estilo="Fuente guardada que quieres aplicar",
                           nuevo_nombre="Nuevo nombre (escríbelo normal, el bot le pone la fuente)")
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def aplicar_renombrar_cmd(self, interaction: discord.Interaction, elemento: discord.abc.GuildChannel,
                                    estilo: str, nuevo_nombre: app_commands.Range[str, 1, 100]):
        await self._aplicar(interaction, elemento, estilo, nuevo_nombre)

    @grupo_fuente.command(name="menu_interactivo", description="Menú interactivo desplegable para rediseñar canales y categorías")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def menu_interactivo_cmd(self, interaction: discord.Interaction):
        if await self._sin_db(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if not fuentes:
            return await interaction.followup.send("📂 No hay tipografías guardadas.", ephemeral=True)

        vista = VistaAplicarElemento(self, interaction.guild_id, fuentes, interaction.user.id)
        embed = discord.Embed(
            title="🛠️ Panel de Rediseño de Canales y Categorías",
            description="Selecciona un estilo y el canal/categoría a modificar mediante los menús desplegables.",
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(embed=embed, view=vista, ephemeral=True)

    @grupo_fuente.command(name="listar", description="Muestra las tipografías guardadas en el servidor")
    async def listar_fuentes(self, interaction: discord.Interaction):
        if await self._sin_db(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if not fuentes:
            return await interaction.followup.send("📂 No hay tipografías guardadas.", ephemeral=False)

        embed = discord.Embed(title="🎨 Tipografías Registradas", color=discord.Color.blue())
        for nombre, mapeo in list(fuentes.items())[:25]:
            ejemplo = self.construir_nombre_inteligente("canal-pruebas", None, mapeo, es_categoria_o_voz=False)
            embed.add_field(name=f"📌 {nombre.capitalize()}"[:256],
                            value=f"`{ejemplo}` ({len(mapeo)} chars)"[:1024], inline=False)

        await interaction.followup.send(embed=embed, ephemeral=False)

    @grupo_fuente.command(name="probar", description="Muestra una vista previa de una fuente")
    @app_commands.describe(texto="Texto de prueba", estilo="Fuente guardada que quieres probar")
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def probar_fuente(self, interaction: discord.Interaction,
                            texto: app_commands.Range[str, 1, 100], estilo: str):
        if await self._sin_db(interaction):
            return
        await interaction.response.defer()

        fuentes = await self.cargar_fuentes(interaction.guild_id)
        estilo = estilo.strip().lower()
        if estilo not in fuentes:
            return await interaction.followup.send("❌ Fuente inexistente.")

        resultado = self.construir_nombre_inteligente(texto, None, fuentes[estilo], es_categoria_o_voz=True)
        resultado = resultado.replace("`", "'")
        await interaction.followup.send(f"👁️ **Vista Previa:** `{resultado}`")

    @grupo_fuente.command(name="eliminar", description="Elimina una fuente guardada")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(nombre="Fuente guardada que quieres eliminar")
    @app_commands.autocomplete(nombre=estilo_autocomplete)
    async def eliminar_fuente_cmd(self, interaction: discord.Interaction, nombre: str):
        if await self._sin_db(interaction):
            return
        await interaction.response.defer()

        nombre = nombre.strip().lower()
        if await self.eliminar_fuente(interaction.guild_id, nombre):
            await interaction.followup.send(f"🗑️ Tipografía **{nombre}** eliminada de Firebase.")
        else:
            await interaction.followup.send(f"❌ No se encontró la fuente **{nombre}**.")


async def setup(bot):
    await bot.add_cog(Fuentes(bot))
