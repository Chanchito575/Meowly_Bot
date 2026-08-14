import os
import re
import collections
import threading
from typing import Optional
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import TCPServer

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

# =====================================================================
# 🌐 SERVIDOR DUMMY ROBUSTO (Evita el error de puerto en Render)
# =====================================================================
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot activo de Chanchito575")

    def log_message(self, format, *args):
        pass 

class ReusableTCPServer(TCPServer):
    allow_reuse_address = True

def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    server = ReusableTCPServer(("0.0.0.0", port), DummyServer)
    server.serve_forever()

threading.Thread(target=keep_alive, daemon=True).start()

# =====================================================================
# ⚙️ CONFIGURACIÓN E INICIALIZACIÓN
# =====================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

# Memoria conversación IA (Límite 20 msgs por usuario)
memoria_ia = collections.defaultdict(lambda: collections.deque(maxlen=20))

@bot.event
async def on_ready():
    await bot.tree.sync()
    actividad = discord.Game(name="creado o algo asi por Chanchito575")
    await bot.change_presence(status=discord.Status.online, activity=actividad)
    print(f"✅ Bot conectado con éxito como {bot.user}")

# Función auxiliar para consultar a Groq
async def consultar_groq(prompt_o_mensajes, es_resumen=False):
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        return "❌ Error: La variable `GROQ_API_KEY` no está configurada en Render."

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }

    if es_resumen:
        payload_messages = [
            {"role": "system", "content": "Eres un asistente que resume conversaciones de Discord de forma clara, breve y organizada en viñetas."},
            {"role": "user", "content": f"Por favor resume las siguientes conversaciones del chat:\n\n{prompt_o_mensajes}"}
        ]
    else:
        payload_messages = list(prompt_o_mensajes)

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": payload_messages
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    return f"❌ Error API Groq (Status {resp.status})"
    except Exception as e:
        return f"❌ Error de conexión: {e}"

# =====================================================================
# 💬 1. INTELIGENCIA ARTIFICIAL (/ia)
# =====================================================================
@bot.tree.command(name="ia", description="Habla con la Inteligencia Artificial")
@app_commands.describe(mensaje="Mensaje o pregunta para la IA")
async def ia(interaction: discord.Interaction, mensaje: str):
    await interaction.response.defer()
    
    usuario_id = interaction.user.id
    memoria_ia[usuario_id].append({"role": "user", "content": mensaje})
    
    respuesta = await consultar_groq(memoria_ia[usuario_id], es_resumen=False)
    
    if not respuesta.startswith("❌"):
        memoria_ia[usuario_id].append({"role": "assistant", "content": respuesta})
    
    if len(respuesta) > 2000:
        respuesta = respuesta[:1990] + "..."
        
    await interaction.followup.send(f"🤖 {respuesta}")

# =====================================================================
# 🧹 2. LIMPIAR MEMORIA (/limpiar)
# =====================================================================
@bot.tree.command(name="limpiar", description="Reinicia la memoria de la IA")
@app_commands.describe(modo="Tipo de limpieza")
@app_commands.choices(
    modo=[
        app_commands.Choice(name="personal - Borra tu historial", value="personal"),
        app_commands.Choice(name="todos - Borra la memoria global (Solo Admins)", value="todos")
    ]
)
async def limpiar(interaction: discord.Interaction, modo: app_commands.Choice[str]):
    if modo.value == "todos":
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Requiere el permiso de **Administrador**.", ephemeral=True)
            return
        memoria_ia.clear()
        await interaction.response.send_message("🧹 Memoria global de la IA reiniciada.")
    else:
        memoria_ia[interaction.user.id].clear()
        await interaction.response.send_message("🧹 Tu historial de conversación ha sido borrado.", ephemeral=True)

# =====================================================================
# 📊 3. RESUMEN INTELIGENTE FUNCIONAL (/resumen)
# =====================================================================
def parsear_fecha(txt: str) -> Optional[datetime]:
    txt = txt.strip()
    partes = txt.split("/")
    anio_actual = datetime.now(timezone.utc).year
    try:
        if len(partes) == 2:
            d, m = int(partes[0]), int(partes[1])
            return datetime(anio_actual, m, d, tzinfo=timezone.utc)
        elif len(partes) == 3:
            d, m, a = int(partes[0]), int(partes[1]), int(partes[2])
            if a < 100: a += 2000
            return datetime(a, m, d, tzinfo=timezone.utc)
    except ValueError:
        return None
    return None

@bot.tree.command(name="resumen", description="Genera un resumen del chat procesado por la IA")
@app_commands.describe(
    modo="Filtro a aplicar", fecha="Fecha (DD/MM o DD/MM/AAAA)",
    inicio="Inicio (DD/MM)", fin="Fin (DD/MM)",
    cantidad="N° de mensajes (máx 500)", tiempo="Minutos u horas (N)"
)
@app_commands.choices(
    modo=[
        app_commands.Choice(name="defecto - Últimos 100 msgs", value="defecto"),
        app_commands.Choice(name="dia - Un día específico", value="dia"),
        app_commands.Choice(name="fechas - Rango inicio y fin (máx 10 días)", value="fechas"),
        app_commands.Choice(name="mensajes - N° de mensajes", value="mensajes"),
        app_commands.Choice(name="horas - Últimas N horas", value="horas"),
        app_commands.Choice(name="minutos - Últimos N minutos", value="minutos"),
        app_commands.Choice(name="hoy - Mensajes de hoy", value="hoy")
    ]
)
async def resumen(
    interaction: discord.Interaction,
    modo: Optional[app_commands.Choice[str]] = None,
    fecha: Optional[str] = None, inicio: Optional[str] = None, fin: Optional[str] = None,
    cantidad: Optional[int] = None, tiempo: Optional[int] = None
):
    await interaction.response.defer()
    opcion = modo.value if modo else "defecto"
    
    ahora = datetime.now(timezone.utc)
    limite_mensajes = 200
    after_dt = None
    before_dt = None

    # Lógica de cálculo de rango/fechas
    if opcion == "defecto":
        limite_mensajes = 100
    elif opcion == "hoy":
        after_dt = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    elif opcion == "minutos" and tiempo:
        after_dt = ahora - timedelta(minutes=tiempo)
    elif opcion == "horas" and tiempo:
        after_dt = ahora - timedelta(hours=tiempo)
    elif opcion == "mensajes" and cantidad:
        limite_mensajes = min(cantidad, 500)
    elif opcion == "dia" and fecha:
        f_inicio = parsear_fecha(fecha)
        if not f_inicio:
            return await interaction.followup.send("❌ Formato de fecha inválido. Usa `DD/MM` o `DD/MM/AAAA`.")
        after_dt = f_inicio
        before_dt = f_inicio + timedelta(days=1)
    elif opcion == "fechas" and inicio and fin:
        f_i = parsear_fecha(inicio)
        f_f = parsear_fecha(fin)
        if not f_i or not f_f:
            return await interaction.followup.send("❌ Formato de fechas inválido.")
        if (f_f - f_i).days > 10:
            return await interaction.followup.send("❌ El rango entre fechas no puede superar los **10 días**.")
        after_dt = f_i
        before_dt = f_f + timedelta(days=1)

    # Recopilar mensajes reales del canal
    mensajes_texto = []
    async for msg in interaction.channel.history(limit=limite_mensajes, after=after_dt, before=before_dt, oldest_first=False):
        if not msg.author.bot and msg.content.strip():
            mensajes_texto.append(f"{msg.author.display_name}: {msg.content}")

    if not mensajes_texto:
        return await interaction.followup.send("⚠️ No se encontraron mensajes en el rango especificado para resumir.")

    mensajes_texto.reverse() # Orden cronológico
    bloque_chat = "\n".join(mensajes_texto[:300]) # Límite razonable para la API

    resumen_generado = await consultar_groq(bloque_chat, es_resumen=True)
    
    if len(resumen_generado) > 2000:
        resumen_generado = resumen_generado[:1990] + "..."

    await interaction.followup.send(f"📊 **Resumen del chat:**\n\n{resumen_generado}")

# =====================================================================
# 🛠️ 4. GESTIÓN REAL DE CANALES Y CATEGORÍAS (/gestionar)
# =====================================================================
@bot.tree.command(name="gestionar", description="Crea y organiza canales y categorías en el servidor")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(
    modo="Acción a realizar",
    nombres="Nombres de canales separados por coma (ej: general, memes)",
    categoria="Categoría destino donde ubicar los canales",
    nombre="Nombre para crear una nueva categoría"
)
@app_commands.choices(
    modo=[
        app_commands.Choice(name="crear_canales - Crear canales de texto", value="crear_canales"),
        app_commands.Choice(name="crear_categoria - Crear categoría nueva", value="crear_categoria")
    ]
)
async def gestionar(
    interaction: discord.Interaction,
    modo: app_commands.Choice[str],
    nombres: Optional[str] = None,
    categoria: Optional[discord.CategoryChannel] = None,
    nombre: Optional[str] = None
):
    await interaction.response.defer(ephemeral=True)

    if modo.value == "crear_canales":
        if not nombres:
            return await interaction.followup.send("❌ Especifica el parámetro `nombres` separados por comas.")
        
        lista_nombres = [n.strip() for n in nombres.split(",") if n.strip()][:5]
        creados = []
        for nom in lista_nombres:
            ch = await interaction.guild.create_text_channel(name=nom, category=categoria)
            creados.append(ch.mention)
        
        cat_txt = f" en la categoría **{categoria.name}**" if categoria else ""
        await interaction.followup.send(f"✅ Canales creados con éxito{cat_txt}: {', '.join(creados)}")

    elif modo.value == "crear_categoria":
        if not nombre:
            return await interaction.followup.send("❌ Debes indicar el parámetro `nombre` para la nueva categoría.")
        
        nueva_cat = await interaction.guild.create_category(name=nombre)
        await interaction.followup.send(f"✅ Categoría **{nueva_cat.name}** creada correctamente.")

@gestionar.error
async def gestionar_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Requieres el permiso de **Gestionar Canales**.", ephemeral=True)

# =====================================================================
# 🗑️ 5. PURGA Y ELIMINACIÓN (/eliminar)
# =====================================================================
class ConfirmarEliminacion(discord.ui.View):
    def __init__(self, accion, canal=None):
        super().__init__(timeout=30)
        self.accion = accion
        self.canal = canal

    @discord.ui.button(label="Sí, borrar", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.accion == "actual":
            await interaction.response.send_message("🗑️ Borrando canal...")
            await interaction.channel.delete()
        elif self.accion == "limpiar_msgs":
            await interaction.response.defer(ephemeral=True)
            deleted = await interaction.channel.purge(limit=100)
            await interaction.followup.send(f"🧹 Se borraron {len(deleted)} mensajes.", ephemeral=True)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Operación cancelada.", view=None)

@bot.tree.command(name="eliminar", description="Eliminación de canal o purga de mensajes")
@app_commands.describe(modo="Acción a realizar")
@app_commands.choices(
    modo=[
        app_commands.Choice(name="canal_actual - Elimina por completo este canal", value="actual"),
        app_commands.Choice(name="mensajes - Borra los últimos 100 mensajes de este canal", value="limpiar_msgs")
    ]
)
async def eliminar(interaction: discord.Interaction, modo: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.manage_channels:
        return await interaction.response.send_message("❌ Requieres el permiso de **Gestionar Canales**.", ephemeral=True)

    view = ConfirmarEliminacion(accion=modo.value)
    await interaction.response.send_message(
        f"⚠️ **¿Confirmas la acción `{modo.name}`? Esta acción no se puede deshacer.**",
        view=view, ephemeral=True
    )

# =====================================================================
# ❓ 6. AYUDA Y COMANDOS TRADICIONALES
# =====================================================================
@bot.tree.command(name="help", description="Muestra la guía completa de comandos")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 MANUAL DE COMANDOS",
        description="Bot configurado con IA y herramientas de administración.",
        color=discord.Color.blue()
    )
    embed.add_field(name="💬 IA & Resumen", value="`/ia` • `/resumen` • `/limpiar`", inline=False)
    embed.add_field(name="🛠️ Gestión", value="`/gestionar` • `/eliminar`", inline=False)
    embed.add_field(name="📁 Texto directo", value="`.canales Nombre1, Nombre2`\n`.categorias`", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.command()
@commands.has_permissions(manage_channels=True)
async def canales(ctx, *, nombres: str = None):
    if not nombres:
        return await ctx.send("⚠️ Uso: `.canales Nombre1, Nombre2, Nombre3`")
    lista = [n.strip() for n in nombres.split(",") if n.strip()][:5]
    for nom in lista:
        await ctx.guild.create_text_channel(name=nom, category=ctx.channel.category)
    await ctx.send(f"✅ Se crearon {len(lista)} canal(es).")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def categorias(ctx):
    lista_cat = [f"📁 **{cat.name}** ({len(cat.channels)} canales)" for cat in ctx.guild.categories]
    texto = "\n".join(lista_cat) if lista_cat else "No hay categorías."
    await ctx.send(f"📋 **Categorías del servidor:**\n{texto}")

# =====================================================================
# 🚀 EJECUCIÓN
# =====================================================================
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ ERROR: Falta la variable DISCORD_TOKEN.")
    else:
        bot.run(TOKEN)
