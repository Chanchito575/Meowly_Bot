import os
import asyncio
from threading import Thread
from datetime import datetime, timedelta, timezone
from flask import Flask
import discord
from discord import app_commands
from groq import Groq

# ==========================================
# 0. SERVIDOR WEB PARA RENDER (Anti-Crash)
# ==========================================

app = Flask('')

@app.route('/')
def home():
    return "🤖 Carek Bot está en línea y el puerto está abierto."

def run_flask():
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

class CarekBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("✅ Slash commands sincronizados correctamente.")

bot = CarekBot()

historiales_usuarios = {}

PROMPT_SISTEMA = (
    "Eres Carek, un asistente útil, amigable y directo para servidores de Discord. "
    "Tu creador es <@1122162289206902845>. Responde de forma clara, natural y sin formalidades innecesarias."
)

# ==========================================
# 2. FUNCIONES AUXILIARES
# ==========================================

def limpiar_historial_expirado(user_id: int):
    if user_id in historiales_usuarios:
        ultimo_uso = historiales_usuarios[user_id]["last_active"]
        if datetime.now(timezone.utc) - ultimo_uso > timedelta(minutes=45):
            del historiales_usuarios[user_id]

async def enviar_mensaje_largo(interaction: discord.Interaction, texto: str):
    limite = 1900
    if len(texto) <= limite:
        await interaction.followup.send(texto)
        return

    lineas = texto.split("\n")
    bloque = ""
    for linea in lineas:
        if len(bloque) + len(linea) + 1 > limite:
            await interaction.followup.send(bloque)
            bloque = linea + "\n"
        else:
            bloque += linea + "\n"

    if bloque.strip():
        await interaction.followup.send(bloque)

# ==========================================
# 3. MANEJO DE ERRORES GLOBALES
# ==========================================

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        mensaje = "🚫 **Acceso Denegado:** Necesitas el permiso de `Gestionar Canales` para usar este comando."
        if interaction.response.is_done():
            await interaction.followup.send(mensaje, ephemeral=True)
        else:
            await interaction.response.send_message(mensaje, ephemeral=True)
    else:
        print(f"Error detectado: {error}")

# ==========================================
# 4. SLASH COMMANDS
# ==========================================

# --- /ia ---
@bot.tree.command(name="ia", description="Habla con la IA de Carek")
@app_commands.describe(mensaje="El mensaje que quieres enviarle a la IA")
async def ia(interaction: discord.Interaction, mensaje: str):
    if not groq_client:
        await interaction.response.send_message("⚠️ La API de Groq no está configurada.", ephemeral=True)
        return

    await interaction.response.defer()
    user_id = interaction.user.id
    limpiar_historial_expirado(user_id)

    if user_id not in historiales_usuarios:
        historiales_usuarios[user_id] = {
            "messages": [{"role": "system", "content": PROMPT_SISTEMA}],
            "last_active": datetime.now(timezone.utc)
        }

    user_data = historiales_usuarios[user_id]
    user_data["messages"].append({"role": "user", "content": mensaje})

    # Límite de memoria establecido a 20
    if len(user_data["messages"]) > 20:
        user_data["messages"] = [user_data["messages"][0]] + user_data["messages"][-19:]

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
        await enviar_mensaje_largo(interaction, respuesta)
    except Exception as e:
        await interaction.followup.send(f"❌ Ocurrió un error al conectar con la IA: {e}")


# --- GRUPO: /limpiar ---
grupo_limpiar = app_commands.Group(name="limpiar", description="Opciones para limpiar el historial de la IA")
bot.tree.add_command(grupo_limpiar)

@grupo_limpiar.command(name="historial", description="Borra tu historial personal con la IA")
async def limpiar_historial(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id in historiales_usuarios:
        del historiales_usuarios[user_id]
        await interaction.response.send_message("🧹 Borré tu historial con la IA. Puedes empezar una nueva conversación.")
    else:
        await interaction.response.send_message("ℹ️ No tenías ningún historial activo guardado.", ephemeral=True)

@grupo_limpiar.command(name="all", description="[Admin] Borra la memoria global de todos los usuarios")
@app_commands.checks.has_permissions(manage_channels=True)
async def limpiar_all(interaction: discord.Interaction):
    global historiales_usuarios
    historiales_usuarios.clear()
    await interaction.response.send_message("🧹 **Memoria global reiniciada:** Se han borrado los historiales de todos.")


# --- GRUPO: /eliminar ---
grupo_eliminar = app_commands.Group(name="eliminar", description="Opciones de eliminación de canales")
bot.tree.add_command(grupo_eliminar)

@grupo_eliminar.command(name="actual", description="[Admin] Elimina el canal donde ejecutas el comando")
@app_commands.checks.has_permissions(manage_channels=True)
async def eliminar_actual(interaction: discord.Interaction):
    await interaction.response.send_message(f"⚠️ El canal **#{interaction.channel.name}** se eliminará en 5 segundos...")
    await asyncio.sleep(5)
    await interaction.channel.delete()

@grupo_eliminar.command(name="all", description="[Admin] Elimina masivamente canales buscando por nombre")
@app_commands.describe(nombre="El nombre exacto de los canales a borrar", cantidad="Máximo de canales a borrar")
@app_commands.checks.has_permissions(manage_channels=True)
async def eliminar_all(interaction: discord.Interaction, nombre: str, cantidad: int = 10):
    guild = interaction.guild
    coincidencias = [c for c in guild.channels if c.name == nombre]
    canales_a_borrar = coincidencias[:cantidad]

    if not canales_a_borrar:
        await interaction.response.send_message(f"ℹ️ No encontré ningún canal que se llame **{nombre}**.", ephemeral=True)
        return

    await interaction.response.send_message(f"💣 **Eliminación masiva:** Borrando {len(canales_a_borrar)} canal(es) llamados **#{nombre}**...")
    await asyncio.sleep(2)

    for canal in canales_a_borrar:
        try:
            await canal.delete()
            await asyncio.sleep(1) # Pausa para no saturar la API de Discord
        except Exception:
            pass


# --- /canales ---
@bot.tree.command(name="canales", description="[Admin] Organizador de canales (Máx. 5). Aclara lo de: Nombre, Nombre, Nombre")
@app_commands.describe(
    categoria="Categoría donde se crearán",
    nombres="Nombres de los canales (Ej: general, dudas, fotos)"
)
@app_commands.checks.has_permissions(manage_channels=True)
async def canales_cmd(interaction: discord.Interaction, categoria: str, nombres: str):
    await interaction.response.defer()
    guild = interaction.guild
    lista_nombres = [n.strip() for n in nombres.split(",") if n.strip()]

    LIMITE_MAXIMO = 5
    if len(lista_nombres) > LIMITE_MAXIMO:
        await interaction.followup.send(f"⚠️ **Seguridad:** Solo puedes crear un máximo de **{LIMITE_MAXIMO} canales** a la vez.")
        return

    cat_obj = discord.utils.get(guild.categories, name=categoria)
    if not cat_obj:
        cat_obj = await guild.create_category(categoria)

    creados = []
    for nombre in lista_nombres:
        canal = await guild.create_text_channel(name=nombre, category=cat_obj)
        creados.append(canal.mention)

    await interaction.followup.send(f"✅ Se crearon {len(creados)} canal(es) en **{cat_obj.name}**:\n" + ", ".join(creados))


# --- /categorias ---
@bot.tree.command(name="categorias", description="[Admin] Organizador: Lista las categorías del servidor")
@app_commands.checks.has_permissions(manage_channels=True)
async def categorias_cmd(interaction: discord.Interaction):
    if not interaction.guild.categories:
        await interaction.response.send_message("ℹ️ Este servidor no tiene categorías.", ephemeral=True)
        return
    texto = "📁 **Categorías del servidor:**\n\n" + "\n".join(
        f"• **{cat.name}** ({len(cat.channels)} canales)" for cat in interaction.guild.categories
    )
    await interaction.response.send_message(texto)


# --- /resumen ---
@bot.tree.command(name="resumen", description="Genera un resumen del chat entre dos fechas")
@app_commands.describe(fecha_inicio="Formato DD/MM", fecha_fin="Formato DD/MM")
async def resumen(interaction: discord.Interaction, fecha_inicio: str, fecha_fin: str):
    if not groq_client:
        await interaction.response.send_message("⚠️ La API de Groq no está configurada.", ephemeral=True)
        return

    await interaction.response.defer()
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
        await interaction.followup.send("❌ Formato de fecha inválido. Usa `DD/MM` (Ej: `09/05`).")
        return

    if dt_inicio > dt_fin:
        await interaction.followup.send("❌ La fecha inicial no puede ser posterior a la fecha final.")
        return

    if (dt_fin - dt_inicio).days > 10:
        dt_fin = (dt_inicio + timedelta(days=10)).replace(hour=23, minute=59, second=59)

    mensajes_por_dia = {}
    async for msg in interaction.channel.history(limit=1000, after=dt_inicio, before=dt_fin, oldest_first=True):
        if not msg.author.bot and msg.content.strip():
            fecha_clave = msg.created_at.strftime("%d/%m/%Y")
            mensajes_por_dia.setdefault(fecha_clave, []).append(f"{msg.author.display_name}: {msg.content}")

    if not mensajes_por_dia:
        await interaction.followup.send("ℹ️ No hay mensajes en ese rango de fechas.")
        return

    texto_consulta = "Resume el contenido del chat separando por cada día:\n\n"
    for f_clave, msgs in mensajes_por_dia.items():
        texto_consulta += f"=== DÍA {f_clave} ===\n" + "\n".join(msgs[:50]) + "\n\n"

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
        await enviar_mensaje_largo(interaction, f"📊 **Resumen del chat:**\n\n{resumen_respuesta}")
    except Exception as e:
        await interaction.followup.send(f"❌ Error al procesar el resumen: {e}")


# --- /help ---
@bot.tree.command(name="help", description="Muestra la guía completa de comandos de Carek")
async def help_cmd(interaction: discord.Interaction):
    guia = (
        "🤖 **GUÍA DE COMANDOS CAREK**\n\n"
        "💬 `/ia [mensaje]` ➔ Habla con la IA (recuerda hasta 20 mensajes por 45 min).\n"
        "🧹 `/limpiar historial` ➔ Borra tu memoria con la IA.\n"
        "🧹 `/limpiar all` ➔ *(Admin)* Reinicia la memoria de todos los usuarios.\n"
        "📊 `/resumen [fecha_inicio] [fecha_fin]` ➔ Resume el chat por fechas.\n"
        "📋 `/canales [categoria] [nombres]` ➔ *(Admin)* Organizador: Crea canales (Aclara lo de .canales Nombre, Nombre, Nombre).\n"
        "📁 `/categorias` ➔ *(Admin)* Organizador: Lista las categorías del servidor.\n"
        "🗑️ `/eliminar actual` ➔ *(Admin)* Elimina el canal actual tras 5 seg.\n"
        "🗑️ `/eliminar all [nombre] [cantidad]` ➔ *(Admin)* Elimina canales duplicados buscando por nombre (Ej: `/eliminar all general 15`)."
    )
    await interaction.response.send_message(guia)

# ==========================================
# 5. EJECUCIÓN
# ==========================================

@bot.event
async def on_ready():
    print(f"🤖 Bot iniciado como {bot.user}")

if __name__ == "__main__":
    if DISCORD_TOKEN:
        keep_alive() # Previene error de puertos de Render
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ No se encontró DISCORD_TOKEN.")
