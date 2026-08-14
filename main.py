import os
import collections
from typing import Optional
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
from duckduckgo_search import DDGS

# =====================================================================
# ⚙️ CONFIGURACIÓN DEL BOT
# =====================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)
memoria_ia = collections.defaultdict(lambda: collections.deque(maxlen=20))

MODELO_IA = "llama-3.3-70b-versatile"

@bot.event
async def on_ready():
    await bot.tree.sync()
    actividad = discord.Game(name="creado por Chanchito575")
    await bot.change_presence(status=discord.Status.online, activity=actividad)
    print(f"✅ Bot conectado con éxito como {bot.user}")

# =====================================================================
# 🔍 BÚSQUEDA WEB GRATUITA (DUCKDUCKGO)
# =====================================================================
def buscar_en_web(consulta: str) -> str:
    """Realiza una búsqueda en DuckDuckGo y devuelve los titulares más recientes."""
    try:
        with DDGS() as ddgs:
            resultados = list(ddgs.text(consulta, max_results=3))
            if not resultados:
                return "No se encontraron resultados recientes en la web."
            
            texto_busqueda = ""
            for i, res in enumerate(resultados, 1):
                texto_busqueda += f"Fuente {i}: {res.get('title', '')}\n{res.get('body', '')}\n\n"
            return texto_busqueda
    except Exception as e:
        print(f"Error en búsqueda web: {e}")
        return "No se pudo realizar la búsqueda web en este momento."

# =====================================================================
# 🤖 CONSULTA A GROQ (LLAMA 3.3)
# =====================================================================
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
            {
                "role": "system",
                "content": (
                    "Eres Carek, un asistente de Discord analítico y claro. "
                    "Resumes conversaciones estructurando las ideas en listas ordenadas con viñetas."
                )
            },
            {"role": "user", "content": f"Por favor resume las siguientes conversaciones del chat:\n\n{prompt_o_mensajes}"}
        ]
    else:
        payload_messages = [
            {
                "role": "system",
                "content": "Eres Carek, un asistente virtual útil, fluido y moderno para comunidades de Discord."
            }
        ] + list(prompt_o_mensajes)

    payload = {
        "model": MODELO_IA,
        "messages": payload_messages,
        "temperature": 0.7,
        "max_tokens": 1024
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

# =====================================================================
# 💬 1. INTELIGENCIA ARTIFICIAL CON BÚSQUEDA WEB (/ia)
# =====================================================================
@bot.tree.command(name="ia", description="Habla con la IA (con acceso a información en tiempo real)")
@app_commands.describe(mensaje="Tu pregunta o consulta")
async def ia(interaction: discord.Interaction, mensaje: str):
    await interaction.response.defer()
    
    # 1. Busca información fresca en DuckDuckGo
    info_web = buscar_en_web(mensaje)
    
    # 2. Prepara la consulta para la IA
    prompt_con_web = (
        f"Información obtenida de la web en tiempo real:\n{info_web}\n\n"
        f"Pregunta del usuario: {mensaje}\n\n"
        "Responde a la pregunta del usuario utilizando la información de la web si es relevante."
    )
    
    usuario_id = interaction.user.id
    memoria_ia[usuario_id].append({"role": "user", "content": prompt_con_web})
    
    # 3. Llama a Groq
    respuesta = await consultar_groq(memoria_ia[usuario_id], es_resumen=False)
    
    if not respuesta.startswith("❌"):
        memoria_ia[usuario_id].append({"role": "assistant", "content": respuesta})
    
    if len(respuesta) > 2000:
        respuesta = respuesta[:1990] + "..."
        
    await interaction.followup.send(f"🤖 {respuesta}")

# =====================================================================
# 🧹 2. LIMPIAR MEMORIA (/limpiar)
# =====================================================================
grupo_limpiar = app_commands.Group(name="limpiar", description="Borra la memoria del bot")

@grupo_limpiar.command(name="mi_historial", description="Borra únicamente tu historial con la IA")
async def limpiar_mi_historial(interaction: discord.Interaction):
    memoria_ia[interaction.user.id].clear()
    await interaction.response.send_message("🧹 Tu historial ha sido borrado.", ephemeral=True)

@grupo_limpiar.command(name="todo", description="Borra la memoria global de todos (Admins)")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def limpiar_todo(interaction: discord.Interaction):
    memoria_ia.clear()
    await interaction.response.send_message("🧹 Memoria global de la IA reiniciada.")

bot.tree.add_command(grupo_limpiar)

# =====================================================================
# 📊 3. RESUMEN (/resumen)
# =====================================================================
grupo_resumen = app_commands.Group(name="resumen", description="Resúmenes inteligentes del chat")

async def obtener_resumen_de_rango(channel, after_dt, before_dt) -> Optional[str]:
    mensajes_texto = []
    async for msg in channel.history(limit=500, after=after_dt, before=before_dt, oldest_first=True):
        if not msg.author.bot and msg.content.strip():
            mensajes_texto.append(f"{msg.author.display_name}: {msg.content}")

    if not mensajes_texto:
        return None

    texto_completo = "\n".join(mensajes_texto)
    palabras = texto_completo.split()

    if len(palabras) > 2000:
        texto_recortado = " ".join(palabras[:2000])
    else:
        texto_recortado = texto_completo

    return await consultar_groq(texto_recortado, es_resumen=True)

async def procesar_resumen_unificado(interaction: discord.Interaction, titulo: str, limite: int = 200, after_dt=None, before_dt=None):
    await interaction.response.defer()
    resumen_txt = await obtener_resumen_de_rango(interaction.channel, after_dt, before_dt)
    
    if not resumen_txt:
        return await interaction.followup.send(f"📌 **{titulo}**\n*Sin actividad/mensajes registrados.*")

    resultado = f"📌 **{titulo}**\n{resumen_txt}"
    if len(resultado) > 2000:
        resultado = resultado[:1990] + "..."
    await interaction.followup.send(resultado)

@grupo_resumen.command(name="defecto", description="Resumen de los últimos 100 mensajes")
async def resumen_defecto(interaction: discord.Interaction):
    await procesar_resumen_unificado(interaction, titulo="Resumen de los últimos 100 mensajes", limite=100)

@grupo_resumen.command(name="hoy", description="Resumen de los mensajes de hoy")
async def resumen_hoy(interaction: discord.Interaction):
    ahora = datetime.now(timezone.utc)
    inicio_hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    fecha_hoy = ahora.strftime("%d/%m")
    await procesar_resumen_unificado(interaction, titulo=f"Resumen de hoy ({fecha_hoy})", after_dt=inicio_hoy)

@grupo_resumen.command(name="dia", description="Resumen de un día específico")
@app_commands.describe(fecha="DD/MM o DD/MM/AAAA")
async def resumen_dia(interaction: discord.Interaction, fecha: str):
    f_inicio = parsear_fecha(fecha)
    if not f_inicio:
        return await interaction.response.send_message("❌ Fecha inválida. Usa `DD/MM`.", ephemeral=True)
    f_fin = f_inicio + timedelta(days=1)
    await procesar_resumen_unificado(interaction, titulo=f"Resumen de {f_inicio.strftime('%d/%m')}", after_dt=f_inicio, before_dt=f_fin)

@grupo_resumen.command(name="rango", description="Resumen día por día en un rango (máx 10 días)")
@app_commands.describe(inicio="Inicio (DD/MM)", fin="Fin (DD/MM)")
async def resumen_rango(interaction: discord.Interaction, inicio: str, fin: str):
    f_i = parsear_fecha(inicio)
    f_f = parsear_fecha(fin)
    
    if not f_i or not f_f:
        return await interaction.response.send_message("❌ Fecha inválida.", ephemeral=True)
    if f_i > f_f:
        return await interaction.response.send_message("❌ La fecha de inicio debe ser anterior a la de fin.", ephemeral=True)
    if (f_f - f_i).days > 10:
        return await interaction.response.send_message("❌ El rango no puede superar los 10 días.", ephemeral=True)

    await interaction.response.defer()
    respuestas_dias = []
    dia_actual = f_i

    while dia_actual <= f_f:
        siguiente_dia = dia_actual + timedelta(days=1)
        resumen_dia_txt = await obtener_resumen_de_rango(interaction.channel, dia_actual, siguiente_dia)
        etiqueta_fecha = dia_actual.strftime("%d/%m")
        
        if resumen_dia_txt:
            respuestas_dias.append(f"📌 **Resumen de {etiqueta_fecha}**\n{resumen_dia_txt}")
        else:
            respuestas_dias.append(f"📌 **Resumen de {etiqueta_fecha}**\n*Sin actividad/mensajes registrados.*")
        dia_actual = siguiente_dia

    resultado_final = "\n\n".join(respuestas_dias)
    if len(resultado_final) > 2000:
        resultado_final = resultado_final[:1990] + "..."
    await interaction.followup.send(resultado_final)

@grupo_resumen.command(name="mensajes", description="Resumen por cantidad de mensajes")
@app_commands.describe(cantidad="Cantidad de mensajes (máx 500)")
async def resumen_mensajes(interaction: discord.Interaction, cantidad: int):
    limite = min(cantidad, 500)
    await procesar_resumen_unificado(interaction, titulo=f"Resumen de los últimos {limite} mensajes", limite=limite)

@grupo_resumen.command(name="tiempo", description="Resumen por horas o minutos transcurridos")
@app_commands.describe(unidad="Horas o Minutos", valor="Cantidad de tiempo")
@app_commands.choices(unidad=[app_commands.Choice(name="Horas", value="horas"), app_commands.Choice(name="Minutos", value="minutos")])
async def resumen_tiempo(interaction: discord.Interaction, unidad: app_commands.Choice[str], valor: int):
    ahora = datetime.now(timezone.utc)
    if unidad.value == "horas":
        after_dt = ahora - timedelta(hours=valor)
        titulo_txt = f"Resumen de las últimas {valor} hora(s)"
    else:
        after_dt = ahora - timedelta(minutes=valor)
        titulo_txt = f"Resumen de los últimos {valor} minuto(s)"
    await procesar_resumen_unificado(interaction, titulo=titulo_txt, after_dt=after_dt)

bot.tree.add_command(grupo_resumen)

# =====================================================================
# 🛠️ 4. GESTIÓN DE CANALES Y CATEGORÍAS (/gestionar)
# =====================================================================
grupo_gestionar = app_commands.Group(name="gestionar", description="Crea, renombra y organiza canales y categorías")

@grupo_gestionar.command(name="canales", description="Crea hasta 5 canales de texto")
@app_commands.default_permissions(manage_channels=True)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(nombres="Nombres separados por comas", categoria="Categoría donde ubicarlos (opcional)")
async def crear_canales(interaction: discord.Interaction, nombres: str, categoria: Optional[discord.CategoryChannel] = None):
    await interaction.response.defer(ephemeral=True)
    lista_nombres = [n.strip() for n in nombres.split(",") if n.strip()][:5]
    creados = []
    
    for nom in lista_nombres:
        ch = await interaction.guild.create_text_channel(name=nom, category=categoria)
        creados.append(ch.mention)
    
    cat_txt = f" en **{categoria.name}**" if categoria else ""
    await interaction.followup.send(f"✅ Canales creados{cat_txt}: {', '.join(creados)}")

@grupo_gestionar.command(name="categoria", description="Crea una categoría nueva")
@app_commands.default_permissions(manage_channels=True)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(nombre="Nombre de la nueva categoría")
async def crear_categoria(interaction: discord.Interaction, nombre: str):
    await interaction.response.defer(ephemeral=True)
    nueva_cat = await interaction.guild.create_category(name=nombre)
    await interaction.followup.send(f"✅ Categoría **{nueva_cat.name}** creada con éxito.")

@grupo_gestionar.command(name="renombrar", description="Cambia el nombre de un canal existente")
@app_commands.default_permissions(manage_channels=True)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(canal="Canal que deseas renombrar", nuevo_nombre="Nuevo nombre para el canal")
async def renombrar_canal(interaction: discord.Interaction, canal: discord.abc.GuildChannel, nuevo_nombre: str):
    await interaction.response.defer(ephemeral=True)
    nombre_antiguo = canal.name
    try:
        await canal.edit(name=nuevo_nombre)
        await interaction.followup.send(f"✏️ El canal **#{nombre_antiguo}** ahora se llama {canal.mention}.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error al renombrar el canal: {e}")

bot.tree.add_command(grupo_gestionar)

# =====================================================================
# 🗑️ 5. ELIMINACIÓN Y BORRADO (/eliminar)
# =====================================================================
grupo_eliminar = app_commands.Group(name="eliminar", description="Opciones de borrado y purga")

class ConfirmarEliminacion(discord.ui.View):
    def __init__(self, accion):
        super().__init__(timeout=30)
        self.accion = accion

    @discord.ui.button(label="Sí, confirmar", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.accion == "canal":
            await interaction.response.send_message("🗑️ Borrando canal...")
            await interaction.channel.delete()
        elif self.accion == "mensajes":
            await interaction.response.defer(ephemeral=True)
            deleted = await interaction.channel.purge(limit=100)
            await interaction.followup.send(f"🧹 Se borraron {len(deleted)} mensajes.", ephemeral=True)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Operación cancelada.", view=None)

@grupo_eliminar.command(name="canal", description="Borra por completo este canal")
@app_commands.default_permissions(manage_channels=True)
@app_commands.checks.has_permissions(manage_channels=True)
async def borrar_canal(interaction: discord.Interaction):
    view = ConfirmarEliminacion(accion="canal")
    await interaction.response.send_message("⚠️ **¿Estás seguro de eliminar este canal por completo?**", view=view, ephemeral=True)

@grupo_eliminar.command(name="mensajes", description="Limpia los últimos 100 mensajes de este canal")
@app_commands.default_permissions(manage_messages=True)
@app_commands.checks.has_permissions(manage_messages=True)
async def purgar_mensajes(interaction: discord.Interaction):
    view = ConfirmarEliminacion(accion="mensajes")
    await interaction.response.send_message("⚠️ **¿Confirmas borrar los últimos 100 mensajes?**", view=view, ephemeral=True)

bot.tree.add_command(grupo_eliminar)

# =====================================================================
# 📌 MANEJO DE ERRORES DE PERMISOS
# =====================================================================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        mensaje_error = "❌ No tienes los permisos necesarios para usar este comando."
        if interaction.response.is_done():
            await interaction.followup.send(mensaje_error, ephemeral=True)
        else:
            await interaction.response.send_message(mensaje_error, ephemeral=True)
    else:
        print(f"Error no controlado: {error}")

# =====================================================================
# 📬 6. DETECCIÓN DE MENSAJES DE CHAT
# =====================================================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    contenido_lc = message.content.lower()

    if "se define en el dashboard" in contenido_lc or "dashboard" in contenido_lc:
        await message.channel.send("📌 **Carek:** La información y configuraciones generales del bot se definen desde el panel de administración.")

    await bot.process_commands(message)

# =====================================================================
# ❓ 7. AYUDA (/help)
# =====================================================================
@bot.tree.command(name="help", description="Guía de uso del bot")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 MANUAL DE COMANDOS",
        description="Bot con IA conectada a la web en tiempo real:",
        color=discord.Color.blue()
    )
    embed.add_field(name="💬 IA", value="`/ia` (con búsqueda en vivo) • `/limpiar mi_historial` • `/limpiar todo`", inline=False)
    embed.add_field(name="📊 Resumen", value="`/resumen defecto` • `/resumen hoy` • `/resumen dia`\n`/resumen rango` • `/resumen mensajes` • `/resumen tiempo`", inline=False)
    embed.add_field(name="🛠️ Gestión", value="`/gestionar canales` • `/gestionar categoria` • `/gestionar renombrar`", inline=False)
    embed.add_field(name="🗑️ Eliminación", value="`/eliminar canal` • `/eliminar mensajes`", inline=False)
    await interaction.response.send_message(embed=embed)

# =====================================================================
# 🚀 EJECUCIÓN
# =====================================================================
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ ERROR: Falta la variable DISCORD_TOKEN.")
    else:
        bot.run(TOKEN)
