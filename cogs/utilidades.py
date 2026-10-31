import asyncio
import math
import os
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands

try:
    from cogs import ia as ia_mod
    from cogs.ia import buscar_en_web
except Exception as _e:
    print(f"⚠️ utilidades: no se pudo importar cogs.ia ({type(_e).__name__}: {_e})")
    ia_mod = None
    buscar_en_web = None

OWNER_ID_POR_DEFECTO = 1481047586457518141
CLAVES_IA = (
    ("Groq", ("GROQ_API_KEY", "GROQ_KEY"), "MODELO_JUEZ"),
    ("Mistral", ("MISTRAL_API_KEY", "MISTRAL_KEY"), "MODELO_MISTRAL"),
    ("Qwen (HF)", ("HF_TOKEN", "HUGGINGFACE_API_KEY", "HF_API_KEY", "QWEN_API_KEY"), "MODELO_QWEN"),
)

PERMISOS_BOT = (
    ("view_channel", "Ver canal"),
    ("send_messages", "Enviar mensajes"),
    ("embed_links", "Insertar enlaces"),
    ("read_message_history", "Leer historial"),
    ("manage_messages", "Gestionar mensajes"),
    ("manage_channels", "Gestionar canales"),
)


def hay_key(*nombres: str) -> bool:
    for n in nombres:
        v = os.getenv(n)
        if v and v.strip().strip('"').strip("'").strip():
            return True
    return False


def recortar(texto: str, limite: int = 1000) -> str:
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"

PERMISOS_NOMBRE = {
    None: "Ninguno (cualquiera puede usarlo)",
    "manage_messages": "Gestionar mensajes",
    "manage_channels": "Gestionar canales",
    "administrator": "Administrador",
    "owner": "Ser el dueño del bot",
}

PAGINAS = {
    "ia": (
        "🐱", "Inteligencia Artificial y memoria",
        "Meowly usa varias IAs (Groq, Mistral, Qwen) con respaldo automático: si una falla, prueba la siguiente.",
        [
            ("/ia <mensaje>",
             "Conversa con Meowly. Recuerda tu conversación y, si preguntas por algo actual "
             "(noticias, precios, clima…), consulta la web.", None, "Enviar mensajes"),
            ("/limpiar mi_historial",
             "Borra tu conversación personal guardada con la IA.", None, "Enviar mensajes"),
            ("/limpiar todo",
             "Reinicia la memoria de la IA de TODOS los usuarios.", "administrator", "Enviar mensajes"),
            ("/ia_estado",
             "Prueba cada API de IA y muestra cuál falla y por qué. Solo lo ves tú.", "administrator", "Enviar mensajes"),
        ],
    ),
    "resumen": (
        "📊", "Resúmenes de chat con IA",
        "Leen el canal donde los uses (ignoran bots y mensajes vacíos). Cualquiera puede usarlos; "
        "el bot necesita poder leer el historial y tener activado el intent Message Content.",
        [
            ("/resumen defecto", "Resume los últimos 100 mensajes del canal.", None, "Ver canal + Leer historial"),
            ("/resumen hoy", "Resume lo hablado hoy en el canal.", None, "Ver canal + Leer historial"),
            ("/resumen dia <DD/MM>", "Resume la conversación de una fecha exacta.", None, "Ver canal + Leer historial"),
            ("/resumen rango <inicio> <fin>", "Resume entre dos fechas (formato DD/MM).", None, "Ver canal + Leer historial"),
            ("/resumen mensajes <cantidad>", "Resume una cantidad de mensajes (1 a 1000).", None, "Ver canal + Leer historial"),
            ("/resumen tiempo <horas>", "Resume las últimas N horas del chat (1 a 168).", None, "Ver canal + Leer historial"),
            ("/resumen persona <usuario> <DD/MM>",
             "Resume lo que dijo un usuario concreto en un día.", None, "Ver canal + Leer historial"),
        ],
    ),
    "moderacion": (
        "🧹", "Moderación de mensajes", "",
        [
            ("/purge",
             "Abre un menú: eliges borrar solo mensajes de bots o todos, e indicas cuántos de los últimos "
             "mensajes revisar (1 a 100). No borra mensajes fijados ni de más de 14 días.",
             "manage_messages", "Gestionar mensajes + Leer historial"),
        ],
    ),
    "fuentes": (
        "🎨", "Fuentes e identidad visual",
        "Las fuentes se guardan por servidor en Firebase (máximo 25). Discord permite renombrar un mismo canal "
        "solo 2 veces cada 10 minutos. Para editar un canal necesitas Gestionar canales en ese canal.",
        [
            ("/fuente escanear mensaje <mensaje> <nombre>",
             "Detecta la tipografía de un texto (ej. 𝗠𝗲𝗼𝘄𝗹𝘆) y la guarda con ese nombre. "
             "En fuentes raras, la IA ayuda a completarla.", "manage_channels", "Nada especial"),
            ("/fuente escanear canal <canal> <nombre>",
             "Guarda la tipografía que usa el nombre de un canal.", "manage_channels", "Nada especial"),
            ("/fuente escanear categoria <categoria> <nombre>",
             "Guarda la tipografía que usa el nombre de una categoría.", "manage_channels", "Nada especial"),
            ("/fuente aplicar_canal <canal> <estilo>",
             "Aplica una fuente guardada a un canal o categoría manteniendo su nombre.",
             "manage_channels", "Gestionar canales"),
            ("/fuente aplicar_renombrar <elemento> <estilo> <nuevo_nombre>",
             "Renombra un canal o categoría y le aplica la fuente a la vez.", "manage_channels", "Gestionar canales"),
            ("/fuente menu_interactivo",
             "Menú con desplegables para elegir estilo y canal; puedes aplicar varios seguidos.",
             "manage_channels", "Gestionar canales"),
            ("/fuente listar", "Muestra las fuentes guardadas del servidor con un ejemplo.", None, "Insertar enlaces"),
            ("/fuente probar <texto> <estilo>", "Vista previa de cómo se vería un texto con una fuente.", None, "Nada especial"),
            ("/fuente eliminar <nombre>", "Elimina una fuente guardada.", "manage_channels", "Nada especial"),
        ],
    ),
    "gestion": (
        "🛠️", "Gestión del servidor",
        "Solo funcionan dentro de un servidor.",
        [
            ("/gestionar canales <nombres> [categoria]",
             "Crea hasta 5 canales de texto a la vez (separados por comas), opcionalmente dentro de una categoría.",
             "manage_channels", "Gestionar canales"),
            ("/gestionar categoria <nombre>", "Crea una categoría nueva.", "manage_channels", "Gestionar canales"),
            ("/gestionar renombrar <canal> <nuevo_nombre>",
             "Cambia el nombre de un canal o categoría. Debes poder gestionar ese canal.",
             "manage_channels", "Gestionar canales"),
        ],
    ),
    "eliminar": (
        "🗑️", "Eliminación de canales",
        "Todas piden confirmación con botones (solo quien ejecuta el comando puede confirmar). "
        "No se pueden borrar los canales de reglas y actualizaciones de servidores Comunidad. "
        "Cada borrado queda en el registro de auditoría.",
        [
            ("/gestionar eliminar actual",
             "Elimina el canal donde ejecutas el comando.", "manage_channels", "Gestionar canales"),
            ("/gestionar eliminar especificos",
             "Menú para elegir hasta 5 canales o categorías y eliminarlos.", "manage_channels", "Gestionar canales"),
            ("/gestionar eliminar masivo <filtro> <cantidad>",
             "Elimina canales cuyo nombre contenga una palabra (mínimo 2 letras; de 1 a 20 canales). "
             "Te muestra la lista antes de confirmar y encuentra también nombres con tipografías especiales.",
             "manage_channels", "Gestionar canales"),
        ],
    ),
    "utilidades": (
        "📖", "Utilidades", "",
        [("/help", "Muestra esta guía.", None, "Insertar enlaces")],
    ),
}

COMANDO_DUENO = (
    "/testear",
    "Diagnóstico privado: latencia, base de datos, búsqueda web, llaves de IA, módulos cargados y permisos del bot.",
    "owner", "Insertar enlaces",
)


class AyudaView(discord.ui.View):
    def __init__(self, cog, autor_id: int, es_dueno: bool):
        super().__init__(timeout=180)
        self.cog = cog
        self.autor_id = autor_id
        self.es_dueno = es_dueno
        self.origen = None

        opciones = [discord.SelectOption(label="Inicio", value="inicio", emoji="📖",
                                         description="Cómo leer esta guía y permisos del bot", default=True)]
        for clave, (emoji, titulo, _, cmds) in PAGINAS.items():
            n = len(cmds) + (1 if clave == "utilidades" and es_dueno else 0)
            opciones.append(discord.SelectOption(label=titulo[:100], value=clave, emoji=emoji,
                                                 description=f"{n} comando(s)"))
        self.select = discord.ui.Select(placeholder="📚 Elige una categoría", options=opciones)
        self.select.callback = self.callback
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Este menú pertenece a otra persona.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.origen is not None:
            try:
                await self.origen.edit_original_response(view=None)
            except discord.HTTPException:
                pass

    async def callback(self, interaction: discord.Interaction):
        clave = self.select.values[0]
        for opcion in self.select.options:
            opcion.default = opcion.value == clave
        await interaction.response.edit_message(
            embed=self.cog.construir_embed(clave, interaction, self.es_dueno), view=self
        )
class Utilidades(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.inicio = discord.utils.utcnow()
    async def _es_dueno(self, user) -> bool:
        try:
            owner_id = int(getattr(self.bot, "owner_id_custom", OWNER_ID_POR_DEFECTO))
        except (TypeError, ValueError):
            owner_id = OWNER_ID_POR_DEFECTO
        if user.id == owner_id:
            return True
        try:
            return await self.bot.is_owner(user)
        except Exception:
            return False

    @staticmethod
    def _marca(interaction: discord.Interaction, permiso, es_dueno: bool) -> str:
        if permiso is None:
            return "✅"
        if permiso == "owner":
            return "✅" if es_dueno else "🔒"
        try:
            p = interaction.permissions
            return "✅" if (p.administrator or getattr(p, permiso, False)) else "🔒"
        except AttributeError:
            return "❔"

    def construir_embed(self, clave: str, interaction: discord.Interaction, es_dueno: bool) -> discord.Embed:
        if clave == "inicio":
            embed = discord.Embed(
                title="📖 GUÍA DE COMANDOS - MEOWLY",
                description="Elige una categoría en el menú de abajo para ver qué hace cada comando y qué permisos necesita.",
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="📌 Cómo leer la guía",
                value=("✅ Puedes usar ese comando en este canal.\n"
                       "🔒 Te falta el permiso que necesita.\n"
                       "**Requiere** = permiso que necesitas tú. **Bot necesita** = permiso que debe tener Meowly."),
                inline=False,
            )
            embed.add_field(
                name="🤖 Permisos que debe tener el bot",
                value=("Ver canales, Enviar mensajes, Insertar enlaces, Leer el historial de mensajes, "
                       "Gestionar mensajes y Gestionar canales. Además, el intent **Message Content** debe estar "
                       "activado en el Developer Portal. El rol del bot debe estar por encima de los roles que gestione."),
                inline=False,
            )
            resumen = []
            for k, (emoji, titulo, _, cmds) in PAGINAS.items():
                n = len(cmds) + (1 if k == "utilidades" and es_dueno else 0)
                resumen.append(f"{emoji} **{titulo}** — {n} comando(s)")
            embed.add_field(name="📚 Categorías", value="\n".join(resumen), inline=False)
            embed.set_footer(text="Los comandos de servidor no funcionan en mensajes privados.")
            return embed

        emoji, titulo, descripcion, cmds = PAGINAS[clave]
        cmds = list(cmds)
        if clave == "utilidades" and es_dueno:
            cmds.append(COMANDO_DUENO)

        embed = discord.Embed(title=f"{emoji} {titulo}", description=descripcion or None, color=discord.Color.blue())
        for uso, que_hace, permiso, bot_necesita in cmds:
            marca = self._marca(interaction, permiso, es_dueno)
            valor = (f"{que_hace}\n"
                     f"{marca} **Requiere:** {PERMISOS_NOMBRE[permiso]}\n"
                     f"🤖 **Bot necesita:** {bot_necesita}")
            embed.add_field(name=uso[:256], value=recortar(valor), inline=False)
        embed.set_footer(text="✅ lo puedes usar aquí · 🔒 te falta permiso")
        return embed
    @app_commands.command(name="testear", description="Diagnóstico privado del estado del bot (solo el dueño)")
    async def testear(self, interaction: discord.Interaction):
        if not await self._es_dueno(interaction.user):
            return await interaction.response.send_message("❌ Comando no reconocido.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        lat = self.bot.latency
        latencia = f"{round(lat * 1000)} ms" if math.isfinite(lat) else "sin datos"

        estado_db, estado_web = await asyncio.gather(self._estado_db(), self._estado_web())
        lineas_ia = []
        for nombre, variables, atributo_modelo in CLAVES_IA:
            modelo = getattr(ia_mod, atributo_modelo, "?") if ia_mod else "?"
            if hay_key(*variables):
                lineas_ia.append(f"✅ {nombre} · `{modelo}`")
            else:
                lineas_ia.append(f"❌ {nombre} · llave no detectada")
        ensamble = bool(getattr(ia_mod, "USAR_ENSAMBLE", False)) if ia_mod else False
        lineas_ia.append("Modo: " + ("ensamble (3 llamadas por mensaje)" if ensamble
                                      else "cadena de respaldo (1 llamada por mensaje)"))

        cargados = getattr(self.bot, "cogs_cargados", None)
        fallidos = getattr(self.bot, "cogs_fallidos", None) or []
        if cargados is None:
            cargados = [n.lower() for n in self.bot.cogs.keys()]
        modulos = "✅ " + (", ".join(cargados) if cargados else "ninguno")
        if fallidos:
            modulos += "\n❌ Con error: " + ", ".join(fallidos)

        permisos = interaction.app_permissions
        if permisos is None:
            estado_permisos = "❔ No disponible"
        elif permisos.administrator:
            estado_permisos = "✅ Administrador (todos los permisos)"
        else:
            faltan = [n for attr, n in PERMISOS_BOT if not getattr(permisos, attr, False)]
            estado_permisos = "✅ Todos los necesarios" if not faltan else "❌ Faltan: " + ", ".join(faltan)

        intent = "✅ Activado" if self.bot.intents.message_content else "❌ Desactivado"

        embed = discord.Embed(title="🕵️ Diagnóstico Privado - Meowly", color=discord.Color.dark_purple())
        embed.add_field(name="📶 Latencia Discord", value=f"`{latencia}`", inline=True)
        embed.add_field(name="🌐 Búsqueda Web", value=f"`{estado_web}`", inline=True)
        embed.add_field(name="🔥 Base de Datos Cloud", value=f"`{estado_db}`", inline=False)
        embed.add_field(name="🧠 Llaves de IA", value=recortar("\n".join(lineas_ia)), inline=False)
        embed.add_field(name="📦 Módulos", value=recortar(modulos), inline=False)
        embed.add_field(name="🛠️ Permisos del bot en este canal", value=recortar(estado_permisos), inline=False)
        embed.add_field(name="📨 Message Content Intent", value=intent, inline=True)
        embed.add_field(name="🏠 Servidores", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="⏱️ Cog cargado", value=discord.utils.format_dt(self.inicio, "R"), inline=True)
        embed.set_footer(text="Vista exclusiva del dueño · /ia_estado prueba cada API de IA")

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _estado_db(self) -> str:
        db = getattr(self.bot, "db", None)
        if not db:
            return "❌ Desconectado (revisa FIREBASE_CREDENTIALS_BASE64)"

        def _ping_db():
            db.collection("test").document("ping").set(
                {"last_ping": datetime.now(timezone.utc).isoformat()}
            )

        try:
            await asyncio.wait_for(asyncio.to_thread(_ping_db), timeout=10)
            return "✅ Operativo (Firestore, escritura OK)"
        except asyncio.TimeoutError:
            return "⚠️ Sin respuesta en 10 s"
        except Exception as e:
            return f"❌ Error: {type(e).__name__}: {str(e)[:120]}"

    async def _estado_web(self) -> str:
        if buscar_en_web is None:
            return "❌ No disponible (cogs.ia no cargó)"
        try:
            res = await asyncio.wait_for(buscar_en_web("Python"), timeout=15)
        except asyncio.TimeoutError:
            return "⚠️ Sin respuesta en 15 s"
        except Exception as e:
            return f"❌ Falla: {type(e).__name__}"
        if res and res.startswith("Fuente"):
            return "✅ Operativo (DuckDuckGo)"
        return "⚠️ Sin resultados o sin conexión"

    @app_commands.command(name="help", description="Guía de comandos: qué hace cada uno y qué permisos necesita")
    async def help_command(self, interaction: discord.Interaction):
        es_dueno = await self._es_dueno(interaction.user)
        view = AyudaView(self, interaction.user.id, es_dueno)
        await interaction.response.send_message(
            embed=self.construir_embed("inicio", interaction, es_dueno), view=view, ephemeral=True
        )
        view.origen = interaction


async def setup(bot):
    await bot.add_cog(Utilidades(bot))
