import os
import asyncio
from threading import Thread
from datetime import datetime, timedelta, timezone
from flask import Flask
import discord
from discord.ext import commands
from groq import Groq

# ==========================================
# 0. SERVIDOR WEB PARA RENDER (Puntero de Puerto)
# ==========================================

app = Flask('')

@app.route('/')
def home():
    return "🤖 Carek Bot está en línea y funcionando."

def run_flask():
    # Render asigna automáticamente la variable de entorno PORT
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# ==========================================
# 1. CONFIGURACIÓN E INICIALIZACIÓN
# ==========================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

# Historial de la IA
historiales_usuarios = {}

PROMPT_SISTEMA = (
    "Eres Carek, un asistente útil, amigable y directo para servidores de Discord. "
    "Tu creador es <@1122162289206902845>. Responde de forma clara, natural y sin formalidades innecesarias."
)

# ==========================================
# 2. FUNCIONES AUXILIARES
# ==========================================

def limpiar_historial_expirado(user_id: int):
    """Elimina la memoria del usuario si pasaron más de 45 minutos sin hablar."""
    if user_id in historiales_usuarios:
        ultimo_uso = historiales_usuarios[user_id]["last_active"]
        if datetime.now(timezone.utc) - ultimo_uso > timedelta(minutes=45):
            del historiales_usuarios[user_id]

async def enviar_mensaje_largo(ctx, texto: str):
    """Divide y envía respuestas extensas para no superar los 2000 caracteres de Discord."""
    limite = 1900
    if len(texto) <= limite:
        await ctx.send(texto)
        return

    lineas = texto.split("\n")
    bloque = ""
    for linea in lineas:
        if len(bloque) + len(linea) + 1 > limite:
            await ctx.send(bloque)
            bloque = linea + "\n"
        else:
            bloque += linea + "\n"

    if bloque.strip():
        await ctx.send(bloque)

# ==========================================
# 3. EVENTOS DEL BOT Y MANEJO DE ERRORES
# ==========================================

@bot.event
async def on_ready():
    print(f"🤖 Bot Carek iniciado correctamente como {bot.user}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 **Sin permisos:** Necesitas permisos de administración o gestión de canales para usar este comando.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("⚠️ **Faltan argumentos:** Revisa la sintaxis del comando con `.help`.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"Error detectado: {error}")

# ==========================================
# 4. COMANDOS PRINCIPALES CON PREFIJO '.'
# ==========================================

# --- .ia ---
@bot.command(name="ia")
async def ia(ctx, *, mensaje: str):
    if not groq_client:
        await ctx.send("⚠️ La API de Groq no está configurada.")
        return

    async with ctx.typing():
        user_id = ctx.author.id
        limpiar_historial_expirado(user_id)

        if user_id not in historiales_usuarios:
            historiales_usuarios[user_id] = {
                "messages": [{"role": "system", "content": PROMPT_SISTEMA}],
                "last_active": datetime.now(timezone.utc)
            }

        user_data = historiales_usuarios[user_id]
        user_data["messages"].append({"role": "user", "content": mensaje})

        if len(user_data["messages"]) > 21:
            user_data["messages"] = [user_data["messages"][0]] + user_data["messages"][-20:]

        user_data["last_active"] = datetime.now(timezone.utc)

        try:
            loop = asyncio.get_event_loop()
            completion = await loop.run_in_executor(
                None,
                lambda: groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=user_data["messages"],
                    temperature=0.7,
                    max_tokens=1000
                )
            )
            respuesta = completion.choices[0].message.content
            user_data["messages"].append({"role": "assistant", "content": respuesta})
            await enviar_mensaje_largo(ctx, respuesta)

        except Exception as e:
            await ctx.send(f"❌ Ocurrió un error al conectar con la IA: {e}")

# --- .limpiar Y SUBCOMANDO .limpiar all ---
@bot.group(name="limpiar", invoke_without_command=True)
async def limpiar(ctx):
    """Borra el historial del usuario actual."""
    user_id = ctx.author.id
    if user_id in historiales_usuarios:
        del historiales_usuarios[user_id]
        await ctx.send("🧹 Borré tu historial con la IA. Puedes empezar una nueva conversación.")
    else:
        await ctx.send("ℹ️ No tenías ningún historial activo guardado.")

@limpiar.command(name="all")
@commands.has_permissions(manage_channels=True)
async def limpiar_all(ctx):
    """Subcomando .limpiar all: Borra la memoria global de todos los usuarios."""
    global historiales_usuarios
    historiales_usuarios.clear()
    await ctx.send("🧹 **Memoria global reiniciada:** Se han borrado los historiales de todos los usuarios.")

# --- .canales (CON RESTRICCIONES Y LÍMITE) ---
@bot.command(name="canales")
@commands.has_permissions(manage_channels=True)
async def canales(ctx, *, args: str):
    """Uso: .canales Categoria | Nombre1, Nombre2, Nombre3"""
    partes = args.split("|")
    
    if len(partes) < 2:
        await ctx.send("⚠️ **Formato incorrecto.** Usa: `.canales NombreCategoría | Nombre1, Nombre2, Nombre3`")
        return

    nombre_categoria = partes[0].strip()
    nombres_canales = [n.strip() for n in partes[1].split(",") if n.strip()]

    LIMITE_MAXIMO = 5
    if len(nombres_canales) > LIMITE_MAXIMO:
        await ctx.send(f"⚠️ **Seguridad:** Solo puedes crear hasta **{LIMITE_MAXIMO} canales** a la vez para evitar spam.")
        return

    guild = ctx.guild
    categoria = discord.utils.get(guild.categories, name=nombre_categoria)
    if not categoria:
        categoria = await guild.create_category(nombre_categoria)

    creados = []
    for nombre in nombres_canales:
        canal = await guild.create_text_channel(name=nombre, category=categoria)
        creados.append(canal.mention)

    await ctx.send(f"✅ Se crearon {len(creados)} canal(es) en **{categoria.name}**:\n" + ", ".join(creados))

# --- .categorias ---
@bot.command(name="categorias")
@commands.has_permissions(manage_channels=True)
async def categorias(ctx):
    if not ctx.guild.categories:
        await ctx.send("ℹ️ Este servidor no tiene categorías.")
        return

    texto = "📁 **Categorías del servidor:**\n\n" + "\n".join(
        f"• **{cat.name}** ({len(cat.channels)} canales)" for cat in ctx.guild.categories
    )
    await ctx.send(texto)

# --- .eliminar Y SUBCOMANDO .eliminar all [cantidad] ---
@bot.group(name="eliminar", invoke_without_command=True)
@commands.has_permissions(manage_channels=True)
async def eliminar(ctx):
    """Borra el canal de texto actual."""
    await ctx.send(f"⚠️ El canal **#{ctx.channel.name}** se eliminará en 5 segundos...")
    await asyncio.sleep(5)
    await ctx.channel.delete()

@eliminar.command(name="all")
@commands.has_permissions(manage_channels=True)
async def eliminar_all(ctx, cantidad: int = 10):
    """Subcomando .eliminar all [cantidad]: Elimina todos los canales con el mismo nombre que este."""
    nombre_objetivo = ctx.channel.name
    guild = ctx.guild

    coincidencias = [c for c in guild.channels if c.name == nombre_objetivo]
    canales_a_borrar = coincidencias[:cantidad]

    if not canales_a_borrar:
        await ctx.send("ℹ️ No se encontraron otros canales con este mismo nombre.")
        return

    await ctx.send(f"💣 **Eliminación masiva:** Borrando {len(canales_a_borrar)} canal(es) con el nombre **#{nombre_objetivo}**...")
    await asyncio.sleep(2)

    for canal in canales_a_borrar:
        try:
            await canal.delete()
            await asyncio.sleep(1)
        except Exception:
            pass

# --- .resumen ---
@bot.command(name="resumen")
async def resumen(ctx, fecha_inicio: str, fecha_fin: str):
    if not groq_client:
        await ctx.send("⚠️ La API de Groq no está configurada.")
        return

    año_actual = datetime.now().year

    def parse_fecha(f_str):
        partes = f_str.split("/")
        if len(partes) == 2:
            f_str += f"/{año_actual}"
        return datetime.strptime(f_str, "%d/%m/%Y")

    try:
        dt_inicio = parse_fecha(fecha_inicio).replace(tzinfo=timezone.utc)
        dt_fin = parse_fecha(fecha_fin).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    except ValueError:
        await ctx.send("❌ Formato de fecha inválido. Usa `DD/MM` (Ej: `09/05`).")
        return

    if dt_inicio > dt_fin:
        await ctx.send("❌ La fecha inicial no puede ser posterior a la fecha final.")
        return

    if (dt_fin - dt_inicio).days > 10:
        dt_fin = (dt_inicio + timedelta(days=10)).replace(hour=23, minute=59, second=59)

    mensajes_por_dia = {}
    async for msg in ctx.channel.history(limit=1000, after=dt_inicio, before=dt_fin, oldest_first=True):
        if not msg.author.bot and msg.content.strip():
            fecha_clave = msg.created_at.strftime("%d/%m/%Y")
            mensajes_por_dia.setdefault(fecha_clave, []).append(f"{msg.author.display_name}: {msg.content}")

    if not mensajes_por_dia:
        await ctx.send("ℹ️ No hay mensajes en ese rango de fechas.")
        return

    texto_consulta = "Resume el contenido del chat separando por cada día:\n\n"
    for f_clave, msgs in mensajes_por_dia.items():
        texto_consulta += f"=== DÍA {f_clave} ===\n" + "\n".join(msgs[:50]) + "\n\n"

    async with ctx.typing():
        try:
            loop = asyncio.get_event_loop()
            completion = await loop.run_in_executor(
                None,
                lambda: groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "Eres un asistente que redacta resúmenes claros e informativos día por día."},
                        {"role": "user", "content": texto_consulta}
                    ],
                    temperature=0.5
                )
            )
            resumen_respuesta = completion.choices[0].message.content
            await enviar_mensaje_largo(ctx, f"📊 **Resumen del chat:**\n\n" + resumen_respuesta)
        except Exception as e:
            await ctx.send(f"❌ Error al procesar el resumen: {e}")

# --- .help ---
@bot.command(name="help")
async def help_command(ctx):
    guia = (
        "🤖 **COMANDOS DE CAREK**\n\n"
        "💬 `.ia [mensaje]` ➔ Habla con la IA (recuerda 20 mensajes por 45 min).\n"
        "🧹 `.limpiar` ➔ Borra tu historial con la IA.\n"
        "🧹 `.limpiar all` ➔ *(Admin)* Reinicia la memoria de todos los usuarios.\n"
        "📊 `.resumen [DD/MM] [DD/MM]` ➔ Resume el chat por fechas.\n"
        "📋 `.canales Categoría | canal1, canal2` ➔ *(Admin)* Crea hasta 5 canales.\n"
        "📁 `.categorias` ➔ *(Admin)* Lista las categorías del servidor.\n"
        "🗑️ `.eliminar` ➔ *(Admin)* Elimina el canal actual tras 5 seg.\n"
        "🗑️ `.eliminar all [cantidad]` ➔ *(Admin)* Elimina todos los canales duplicados que compartan el mismo nombre."
    )
    await ctx.send(guia)

# ==========================================
# 5. EJECUCIÓN
# ==========================================

if __name__ == "__main__":
    if DISCORD_TOKEN:
        # Iniciar servidor Flask para responder a los escaneos de puerto de Render
        keep_alive()
        # Iniciar bot de Discord
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ No se encontró DISCORD_TOKEN.")
