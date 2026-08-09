import os
import asyncio
from datetime import datetime, timedelta, timezone
import discord
from discord import app_commands
from discord.ext import commands
from groq import Groq

# ==========================================
# 1. CONFIGURACIÓN E INICIALIZACIÓN
# ==========================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Memoria temporal de la IA por usuario: { user_id: {"messages": [...], "last_active": datetime} }
historiales_usuarios = {}

PROMPT_SISTEMA = (
    "Eres Carek, un asistente útil, amigable y directo para servidores de Discord. "
    "Tu creador es <@1122162289206902845>. Responde de forma clara, natural y sin formalidades innecesarias."
)

# ==========================================
# 2. FUNCIONES AUXILIARES
# ==========================================

def limpiar_historial_expirado(user_id: int):
    """Elimina la memoria del usuario si han pasado más de 45 minutos sin interactuar."""
    if user_id in historiales_usuarios:
        ultimo_uso = historiales_usuarios[user_id]["last_active"]
        if datetime.now(timezone.utc) - ultimo_uso > timedelta(minutes=45):
            del historiales_usuarios[user_id]

async def autocompletar_categorias(interaction: discord.Interaction, current: str):
    """Sugerencias autocompletadas para el parámetro categoría del comando /canales."""
    if not interaction.guild:
        return []
    
    current_lower = current.lower()
    return [
        app_commands.Choice(name=cat.name, value=cat.name)
        for cat in interaction.guild.categories
        if current_lower in cat.name.lower()
    ][:25]

async def enviar_mensaje_largo(interaction: discord.Interaction, texto: str):
    """Divide y envía respuestas extensas evitando superar el límite de caracteres de Discord."""
    limite = 1900
    if len(texto) <= limite:
        await interaction.followup.send(texto)
        return

    lineas = texto.split("\n")
    bloque = ""
    primer_envio = True

    for linea in lineas:
        if len(bloque) + len(linea) + 1 > limite:
            target = interaction.followup if primer_envio else interaction.channel
            await target.send(bloque)
            primer_envio = False
            bloque = linea + "\n"
        else:
            bloque += linea + "\n"

    if bloque.strip():
        target = interaction.followup if primer_envio else interaction.channel
        await target.send(bloque)

# ==========================================
# 3. EVENTOS DEL BOT
# ==========================================

@bot.event
async def on_ready():
    print(f"🤖 Bot iniciado como {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Se sincronizaron {len(synced)} comando(s) Slash correctamente.")
    except Exception as e:
        print(f"❌ Error al sincronizar los comandos Slash: {e}")

# ==========================================
# 4. COMANDOS SLASH
# ==========================================

# --- /ia ---
@bot.tree.command(name="ia", description="Habla o hazle una pregunta a la IA de Carek")
@app_commands.describe(mensaje="Mensaje o consulta para la IA")
async def ia(interaction: discord.Interaction, mensaje: str):
    await interaction.response.defer()
    
    if not groq_client:
        await interaction.followup.send("⚠️ No puedo responder porque la API de Groq no está configurada.")
        return

    user_id = interaction.user.id
    limpiar_historial_expirado(user_id)

    # Recuperar o inicializar sesión de usuario
    if user_id not in historiales_usuarios:
        historiales_usuarios[user_id] = {
            "messages": [{"role": "system", "content": PROMPT_SISTEMA}],
            "last_active": datetime.now(timezone.utc)
        }

    user_data = historiales_usuarios[user_id]
    user_data["messages"].append({"role": "user", "content": mensaje})

    # Limitar memoria a máximo 20 mensajes del usuario/asistente (+ 1 del sistema)
    if len(user_data["messages"]) > 21:
        user_data["messages"] = [user_data["messages"][0]] + user_data["messages"][-20:]

    user_data["last_active"] = datetime.now(timezone.utc)

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=user_data["messages"],
            temperature=0.7,
            max_tokens=1000
        )
        respuesta = completion.choices[0].message.content
        user_data["messages"].append({"role": "assistant", "content": respuesta})
        await enviar_mensaje_largo(interaction, respuesta)

    except Exception as e:
        await interaction.followup.send(f"❌ Ocurrió un problema al conectar con la IA: {e}")

# --- /limpiar ---
@bot.tree.command(name="limpiar", description="Borra tu historial actual con la IA")
async def limpiar(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id in historiales_usuarios:
        del historiales_usuarios[user_id]
        await interaction.response.send_message("🧹 Borré tu historial con la IA. Ya puedes empezar una conversación desde cero.", ephemeral=True)
    else:
        await interaction.response.send_message("ℹ️ No tenías ningún historial activo guardado.", ephemeral=True)

# --- /resumen ---
@bot.tree.command(name="resumen", description="Genera un resumen del chat ordenado por días (Máx 10 días)")
@app_commands.describe(
    fecha_inicio="Fecha inicial (Ejemplo: 09/05)",
    fecha_fin="Fecha final (Ejemplo: 11/05)"
)
async def resumen(interaction: discord.Interaction, fecha_inicio: str, fecha_fin: str):
    await interaction.response.defer()

    if not groq_client:
        await interaction.followup.send("⚠️ No se puede generar el resumen porque la API de Groq no está configurada.")
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
        await interaction.followup.send("❌ El formato de fecha no es correcto. Usa el formato `DD/MM` (por ejemplo: `09/05`).")
        return

    if dt_inicio > dt_fin:
        await interaction.followup.send("❌ La fecha de inicio no puede ser posterior a la fecha final.")
        return

    # Validar límite de 10 días máximo
    nota_ajuste = ""
    if (dt_fin - dt_inicio).days > 10:
        dt_fin = (dt_inicio + timedelta(days=10)).replace(hour=23, minute=59, second=59)
        nota_ajuste = f"\n⚠️ *Nota: El rango solicitado superaba el límite de 10 días, así que se ajustó del {dt_inicio.strftime('%d/%m')} al {dt_fin.strftime('%d/%m')}.*\n"

    # Lectura e índice de mensajes por día
    mensajes_por_dia = {}
    async for msg in interaction.channel.history(limit=1000, after=dt_inicio, before=dt_fin, oldest_first=True):
        if not msg.author.bot and msg.content.strip():
            fecha_clave = msg.created_at.strftime("%d/%m/%Y")
            mensajes_por_dia.setdefault(fecha_clave, []).append(f"{msg.author.display_name}: {msg.content}")

    if not mensajes_por_dia:
        await interaction.followup.send("ℹ️ No se encontraron mensajes en ese rango de fechas.")
        return

    texto_consulta = "Resume el contenido del chat separando los puntos principales por cada día con este formato:\n\n"
    for f_clave, msgs in mensajes_por_dia.items():
        texto_consulta += f"=== DÍA {f_clave} ===\n" + "\n".join(msgs[:50]) + "\n\n"

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Eres un asistente que redacta resúmenes claros, bien estructurados y ordenados día por día."},
                {"role": "user", "content": texto_consulta}
            ],
            temperature=0.5
        )
        resumen_respuesta = completion.choices[0].message.content
        encabezado = f"📊 **Resumen del chat ({dt_inicio.strftime('%d/%m')} al {dt_fin.strftime('%d/%m')})**\n{nota_ajuste}\n"
        await enviar_mensaje_largo(interaction, encabezado + resumen_respuesta)

    except Exception as e:
        await interaction.followup.send(f"❌ Ocurrió un error al procesar el resumen: {e}")

# --- /canales ---
@bot.tree.command(name="canales", description="Crea una lista de canales dentro de una categoría")
@app_commands.describe(
    nombres="Nombres de los canales separados por coma (Ej: general, dudas, fotos)",
    categoria="Categoría donde se crearán"
)
@app_commands.autocomplete(categoria=autocompletar_categorias)
async def canales(interaction: discord.Interaction, nombres: str, categoria: str):
    await interaction.response.defer()
    guild = interaction.guild

    cat_obj = discord.utils.get(guild.categories, name=categoria)
    if not cat_obj:
        cat_obj = await guild.create_category(categoria)

    lista_nombres = [n.strip() for n in nombres.split(",") if n.strip()]
    creados = []

    for nombre in lista_nombres:
        canal = await guild.create_text_channel(name=nombre, category=cat_obj)
        creados.append(canal.mention)

    await interaction.followup.send(
        f"✅ Se crearon {len(creados)} canal(es) en la categoría **{cat_obj.name}**:\n" + ", ".join(creados)
    )

# --- /categorias ---
@bot.tree.command(name="categorias", description="Muestra las categorías actuales del servidor")
async def categorias(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild.categories:
        await interaction.response.send_message("ℹ️ Este servidor no tiene categorías creadas.", ephemeral=True)
        return

    texto = "📁 **Categorías del servidor:**\n\n" + "\n".join(
        f"• **{cat.name}** ({len(cat.channels)} canales)" for cat in guild.categories
    )

    await interaction.response.send_message(texto)

# --- /eliminar ---
@bot.tree.command(name="eliminar", description="Elimina el canal de texto actual")
@app_commands.checks.has_permissions(manage_channels=True)
async def eliminar(interaction: discord.Interaction):
    canal = interaction.channel
    await interaction.response.send_message(f"⚠️ El canal **#{canal.name}** se eliminará en 5 segundos...")
    await asyncio.sleep(5)
    await canal.delete()

# --- /help ---
@bot.tree.command(name="help", description="Muestra la guía de comandos del bot")
@app_commands.describe(comando="Selecciona un comando para ver su explicación detallada")
@app_commands.choices(comando=[
    app_commands.Choice(name="ia", value="ia"),
    app_commands.Choice(name="limpiar", value="limpiar"),
    app_commands.Choice(name="resumen", value="resumen"),
    app_commands.Choice(name="canales", value="canales"),
    app_commands.Choice(name="categorias", value="categorias"),
    app_commands.Choice(name="eliminar", value="eliminar"),
])
async def help_command(interaction: discord.Interaction, comando: str = None):
    if comando is None:
        menu_general = (
            "🤖 **COMANDOS Y GUÍA RÁPIDA DE CAREK**\n\n"
            "💬 **/ia** `[mensaje]`\n"
            "   • **Función:** Habla con la IA del bot.\n"
            "   • **Memoria:** Guarda los últimos 20 mensajes de la charla.\n"
            "   • **Expiración:** El historial se borra automáticamente tras 45 minutos sin hablar.\n\n"
            "🧹 **/limpiar**\n"
            "   • **Función:** Borra tu historial con la IA de inmediato para empezar un tema nuevo.\n\n"
            "📊 **/resumen** `[fecha_inicio]` `[fecha_fin]`\n"
            "   • **Función:** Resume lo hablado en el canal desgloseado día por día.\n"
            "   • **Límites:** Lee hasta 1,000 mensajes y un rango máximo de 10 días.\n\n"
            "📋 **/canales** `[nombres]` `[categoria]`\n"
            "   • **Función:** Crea varios canales a la vez en la categoría seleccionada.\n\n"
            "📁 **/categorias**\n"
            "   • **Función:** Muestra la lista de categorías del servidor y cuántos canales tiene cada una.\n\n"
            "🗑️ **/eliminar**\n"
            "   • ⚠️ **ATENCIÓN:** Elimina por completo el **CANAL ACTUAL** (no borra mensajes individuales).\n\n"
            "💡 *Si quieres ver detalles o ejemplos de uso de algún comando, escribe `/help comando: [nombre]`.*"
        )
        await interaction.response.send_message(menu_general)
    else:
        guias = {
            "ia": (
                "📖 **Información del comando `/ia`**\n"
                "• **Uso:** Te permite hacerle preguntas o conversar con el bot.\n"
                "• **Límite de memoria:** Mantiene en contexto los últimos 20 mensajes que le envíes.\n"
                "• **Tiempo de inactividad:** Si dejas de usarlo por 45 minutos, la memoria se libera sola para no acumular datos en el servidor.\n"
                "• **Ejemplo:** `/ia Explícame cómo funciona un eclipse solar`"
            ),
            "limpiar": (
                "📖 **Información del comando `/limpiar`**\n"
                "• **Uso:** Elimina de forma inmediata tu historial de conversación guardado en `/ia` sin tener que esperar los 45 minutos de inactividad."
            ),
            "resumen": (
                "📖 **Información del comando `/resumen`**\n"
                "• **Uso:** Introduce las fechas con formato `DD/MM` (ejemplo: `/resumen fecha_inicio: 09/05 fecha_fin: 11/05`).\n"
                "• **Detalles:** Revisa hasta 1,000 mensajes y agrupa lo sucedido día por día. Si solicitas un rango mayor a 10 días, el bot lo reajustará automáticamente a 10 días."
            ),
            "canales": (
                "📖 **Información del comando `/canales`**\n"
                "• **Uso:** Escribe los nombres de los canales separados por comas y elige la categoría (ejemplo: `/canales nombres: general, media, comandos categoria: Texto`).\n"
                "• **Autocompletado:** El parámetro de categoría te mostrará la lista desplegable de categorías existentes en el servidor."
            ),
            "categorias": (
                "📖 **Información del comando `/categorias`**\n"
                "• **Uso:** Despliega un listado simple con los nombres de todas las categorías del servidor y el número de canales dentro de cada una."
            ),
            "eliminar": (
                "⚠️ **Información del comando `/eliminar`**\n"
                "• **ADVERTENCIA:** Borra de forma permanente el canal completo desde donde ejecutas el comando tras una cuenta regresiva de 5 segundos. Requiere permisos de gestión de canales."
            )
        }
        await interaction.response.send_message(guias.get(comando, "No se encontró información para ese comando."))

# ==========================================
# 5. EJECUCIÓN DEL BOT
# ==========================================

if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ No se encontró la variable de entorno DISCORD_TOKEN.")
