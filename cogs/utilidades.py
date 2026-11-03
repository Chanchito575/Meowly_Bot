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

MODELO_GROQ = os.getenv("MODELO_GROQ", "openai/gpt-oss-120b")
MODELO_QWEN = os.getenv("MODELO_QWEN", "qwen/qwen3-coder:free")
MODELO_ZAI = os.getenv("MODELO_ZAI", "glm-4.7-flash")

PERMISOS_BOT = (
    ("view_channel", "Ver canal"),
    ("send_messages", "Enviar mensajes"),
    ("embed_links", "Insertar enlaces"),
    ("read_message_history", "Leer historial"),
    ("manage_channels", "Gestionar canales"),
)

PERMISOS_NOMBRE = {
    None: "Ninguno (cualquiera puede usarlo)",
    "manage_channels": "Gestionar canales",
    "administrator": "Administrador",
    "owner": "Ser el dueño del bot",
}

PAGINAS = {
    "ia": (
        "🐱", "Inteligencia Artificial",
        "Meowly usa 2 IAs con respaldo automático: **Groq → Qwen (OpenRouter)**. "
        "Recuerda tu conversación 40 minutos y consulta la web si preguntas por actualidad.",
        [
            ("/ia <mensaje>",
             "Conversa con Meowly. Mantiene memoria por usuario durante 40 min y busca en "
             "DuckDuckGo si detecta preguntas de actualidad (noticias, precios, clima, etc.).",
             None, "Enviar mensajes"),
        ],
    ),
    "fuentes": (
        "🎨", "Fuentes e identidad visual",
        "Paneles interactivos con botones para crear, aplicar y escanear tipografías. "
        "Las fuentes se guardan en Firebase (máximo 25 locales por servidor). "
        "El escaneo usa **Zai (GLM)** como mapeador y **Groq** como respaldo.",
        [
            ("/crear",
             "Abre un panel: `[Canal]` `[Categoría]` → `[Global]` `[Local]` → elegir fuente → "
             "escribir nombre → crea el canal/categoría con la fuente aplicada.",
             "manage_channels", "Gestionar canales"),
            ("/gestionar",
             "Abre un panel: `[Canal]` `[Categoría]` → `[Global]` `[Local]` → elegir fuente → "
             "elegir destino → aplica la fuente al nombre actual.",
             "manage_channels", "Gestionar canales"),
            ("/escanear",
             "Abre un panel: `[Canal]` `[Categoría]` → elegir elemento → escribir nombre local → "
             "detecta la tipografía (Zai → Groq) y la guarda en local + global.",
             "manage_channels", "Nada especial"),
        ],
    ),
    "utilidades": (
        "📖", "Utilidades",
        "",
        [
            ("/help", "Muestra esta guía con todos los comandos y sus permisos.", None, "Insertar enlaces"),
        ],
    ),
}

COMANDO_DUENO = (
    "/testear",
    "Diagnóstico privado: latencia, Firestore, búsqueda web, las 3 APIs de IA (Groq, Qwen/OpenRouter, Zai — prueba real), "
    "módulos cargados, permisos del bot e intent Message Content.",
    "owner", "Insertar enlaces",
)


def recortar(texto: str, limite: int = 1024) -> str:
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def describir_error(e: Exception) -> str:
    status = getattr(e, "status_code", None)
    cuerpo = getattr(e, "body", None) or getattr(e, "message", None) or str(e)
    return f"{type(e).__name__} | status={status} | {str(cuerpo)[:250]}"


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

    def construir_embed_help(self, interaction: discord.Interaction, es_dueno: bool) -> discord.Embed:
        embed = discord.Embed(
            title="📖 GUÍA DE COMANDOS — MEOWLY",
            description="Aquí tienes todos los comandos disponibles y los permisos que necesitan.",
            color=discord.Color.blue(),
        )

        for clave, (emoji, titulo, descripcion, cmds) in PAGINAS.items():
            cmds_list = list(cmds)
            if clave == "utilidades" and es_dueno:
                cmds_list.append(COMANDO_DUENO)

            if descripcion:
                embed.add_field(
                    name=f"{emoji} {titulo}",
                    value=recortar(descripcion, 1024),
                    inline=False,
                )

            for uso, que_hace, permiso, bot_necesita in cmds_list:
                marca = self._marca(interaction, permiso, es_dueno)
                valor = (
                    f"{que_hace}\n"
                    f"{marca} **Requiere:** {PERMISOS_NOMBRE[permiso]}\n"
                    f"🤖 **Bot necesita:** {bot_necesita}"
                )
                embed.add_field(name=f"`{uso}`"[:256], value=recortar(valor, 1024), inline=False)

        embed.add_field(
            name="ℹ️ Cómo leer esta guía",
            value=(
                "✅ Puedes usar ese comando aquí\n"
                "🔒 Te falta el permiso necesario\n"
                "**Requiere** = permiso tuyo · **Bot necesita** = permiso de Meowly\n\n"
                "**Permisos del bot:** Ver canales, Enviar mensajes, Insertar enlaces, "
                "Leer historial y Gestionar canales. "
                "El intent **Message Content** debe estar activado en el Developer Portal."
            ),
            inline=False,
        )
        embed.set_footer(text="Los comandos de servidor no funcionan en mensajes privados.")
        return embed

    async def _test_ia(self, nombre: str, cliente, modelo: str) -> str:
        if not cliente:
            return f"❌ **{nombre}** (`{modelo}`): llave NO detectada"
        try:
            resp = await asyncio.wait_for(
                cliente.chat.completions.create(
                    model=modelo,
                    messages=[{"role": "user", "content": "Responde solo: ok"}],
                    max_tokens=5,
                ),
                timeout=15,
            )
            if resp and resp.choices:
                return f"✅ **{nombre}** (`{modelo}`): funciona"
            return f"⚠️ **{nombre}** (`{modelo}`): respuesta vacía"
        except asyncio.TimeoutError:
            return f"⚠️ **{nombre}** (`{modelo}`): timeout 15s"
        except Exception as e:
            return f"❌ **{nombre}** (`{modelo}`): {describir_error(e)}"

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
        if res and res.strip():
            return "✅ Operativo (DuckDuckGo)"
        return "⚠️ Sin resultados o sin conexión"

    @app_commands.command(name="testear", description="Diagnóstico privado del estado del bot (solo el dueño)")
    async def testear(self, interaction: discord.Interaction):
        if not await self._es_dueno(interaction.user):
            return await interaction.response.send_message("❌ Comando no reconocido.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        lat = self.bot.latency
        latencia = f"{round(lat * 1000)} ms" if math.isfinite(lat) else "sin datos"

        estado_db, estado_web = await asyncio.gather(self._estado_db(), self._estado_web())

        ia_cog = self.bot.get_cog("IA")
        fuentes_cog = self.bot.get_cog("Fuentes")

        clientes_ia = []
        if ia_cog:
            clientes_ia.append(("Groq", ia_cog.groq_client, MODELO_GROQ))
            clientes_ia.append(("Qwen (OpenRouter)", ia_cog.hf_client, MODELO_QWEN))
        if fuentes_cog:
            clientes_ia.append(("Zai (GLM)", fuentes_cog.zai_client, MODELO_ZAI))

        if not clientes_ia:
            lineas_ia = ["❌ No se encontraron cogs de IA cargados"]
        else:
            resultados = await asyncio.gather(
                *(self._test_ia(nombre, cliente, modelo) for nombre, cliente, modelo in clientes_ia),
                return_exceptions=True,
            )
            lineas_ia = [r if isinstance(r, str) else f"❌ Error: {r}" for r in resultados]

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

        embed = discord.Embed(title="🕵️ Diagnóstico Privado — Meowly", color=discord.Color.dark_purple())
        embed.add_field(name="📶 Latencia Discord", value=f"`{latencia}`", inline=True)
        embed.add_field(name="🌐 Búsqueda Web", value=f"`{estado_web}`", inline=True)
        embed.add_field(name="🔥 Base de Datos", value=f"`{estado_db}`", inline=False)
        embed.add_field(name="🧠 APIs de IA (prueba real)", value=recortar("\n".join(lineas_ia), 1024), inline=False)
        embed.add_field(name="📦 Módulos", value=recortar(modulos, 1024), inline=False)
        embed.add_field(name="🛠️ Permisos del bot en este canal", value=recortar(estado_permisos, 1024), inline=False)
        embed.add_field(name="📨 Message Content Intent", value=intent, inline=True)
        embed.add_field(name="🏠 Servidores", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="⏱️ Cog cargado", value=discord.utils.format_dt(self.inicio, "R"), inline=True)
        embed.set_footer(text="Vista exclusiva del dueño · prueba real de cada API de IA")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Guía completa de comandos y permisos")
    async def help_command(self, interaction: discord.Interaction):
        es_dueno = await self._es_dueno(interaction.user)
        embed = self.construir_embed_help(interaction, es_dueno)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Utilidades(bot))
