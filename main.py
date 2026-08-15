import os
import json
import asyncio
import collections
import re
from typing import Optional, List
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
from groq import Groq
from duckduckgo_search import DDGS
from keep_alive import keep_alive  # Servidor web Flask para Render

# =====================================================================
# ⚙️ CONFIGURACIÓN DEL BOT Y CLIENTES
# =====================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

# Memoria inteligente: 20 mensajes de tope y caducidad tras 45 mins de inactividad
class HistorialIA:
    def __init__(self):
        self.mensajes = collections.deque(maxlen=20)
        self.ultimo_uso = datetime.now(timezone.utc)

    def actualizar_y_obtener(self):
        ahora = datetime.now(timezone.utc)
        if (ahora - self.ultimo_uso) > timedelta(minutes=45):
            self.mensajes.clear()
        self.ultimo_uso = ahora
        return list(self.mensajes)

    def agregar(self, rol, contenido):
        self.mensajes.append({"role": rol, "content": contenido})
        self.ultimo_uso = datetime.now(timezone.utc)

    def limpiar(self):
        self.mensajes.clear()

memoria_ia = collections.defaultdict(HistorialIA)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Modelos del Ensamble
MODELO_LLAMA = "llama-3.1-8b-instant"
MODELO_GEMMA = "llama-3.3-70b-versatile"
MODELO_MIXTRAL = "mixtral-8x7b-32768"

@bot.event
async def on_ready():
    await bot.tree.sync()
    actividad = discord.Game(name="creado por Chanchito575 | /help")
    await bot.change_presence(status=discord.Status.online, activity=actividad)
    print(f"✅ Bot conectado con éxito como {bot.user}")

# =====================================================================
# 📁 SISTEMA DE FUENTES
# =====================================================================
def cargar_fuentes(guild_id: int) -> dict:
    archivo = f"fuentes_{guild_id}.json"
    if not os.path.exists(archivo): return {}
    with open(archivo, "r", encoding="utf-8") as f: return json.load(f)

def guardar_fuente(guild_id: int, nombre: str, mapeo: dict):
    data = cargar_fuentes(guild_id)
    data[nombre.lower()] = mapeo
    with open(f"fuentes_{guild_id}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def eliminar_fuente(guild_id: int, nombre: str) -> bool:
    data = cargar_fuentes(guild_id)
    if nombre.lower() in data:
        del data[nombre.lower()]
        with open(f"fuentes_{guild_id}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return True
    return False

def aplicar_mapeo(texto: str, mapeo: dict) -> str:
    return "".join(mapeo.get(c, c) for c in texto)

# =====================================================================
# 🔍 BÚSQUEDA WEB CONDICIONAL
# =====================================================================
def necesita_busqueda(mensaje: str) -> bool:
    """Heurística para decidir si vale la pena buscar en la web."""
    palabras_clave = [
        r"\bnoticia", r"\bhoy\b", r"\bactual", r"quién\b", r"qué es\b", 
        r"cuánto\b", r"\bprecio", r"\bclima", r"\bresultado", r"\binvestiga\b", 
        r"\b2024\b", r"\b2025\b", r"\b2026\b"
    ]
    msg_lower = mensaje.lower()
    return any(re.search(p, msg_lower) for p in palabras_clave)

def _ejecutar_busqueda_ddg(consulta: str) -> str:
    try:
        results = []
        with DDGS() as ddgs:
            resp = ddgs.text(consulta, region="wt-wt", max_results=3)
            if resp: results = list(resp)
        if not results: return "No se encontraron resultados en la web."

        texto_busqueda = ""
        for i, res in enumerate(results, 1):
            texto_busqueda += f"Fuente {i}: {res.get('title', '')}\n{res.get('body', '')}\n\n"
        return texto_busqueda
    except Exception as e:
        return "No se pudo realizar la búsqueda web en este momento."

async def buscar_en_web(consulta: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _ejecutar_busqueda_ddg, consulta)

# =====================================================================
# 🧠 ENSAMBLE DE IAS
# =====================================================================
async def consultar_groq_ensamble(prompt_o_mensajes, es_resumen=False, info_web="") -> str:
    loop = asyncio.get_event_loop()

    if es_resumen:
        system_prompt = (
            "Eres Carek, un asistente analítico. Resume la conversación desglosando "
            "los puntos clave exactos. Usa un formato claro con viñetas y emojis."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Resume lo siguiente:\n\n{prompt_o_mensajes}"}
        ]
        comp = await loop.run_in_executor(
            None, lambda: groq_client.chat.completions.create(
                model=MODELO_MIXTRAL, messages=messages, temperature=0.5, max_tokens=1024
            )
        )
        return comp.choices[0].message.content

    base_messages = [{"role": "system", "content": "Eres Carek, un asistente amigable, moderno y carismático para Discord."}]
    if info_web:
        base_messages.append({"role": "user", "content": f"Información web reciente para usar de contexto si es necesario:\n{info_web}\n\n"})
    
    messages = base_messages + list(prompt_o_mensajes)

    try:
        tarea_gemma = loop.run_in_executor(
            None, lambda: groq_client.chat.completions.create(
                model=MODELO_GEMMA, messages=messages, temperature=0.5, max_tokens=600
            )
        )
        tarea_mixtral = loop.run_in_executor(
            None, lambda: groq_client.chat.completions.create(
                model=MODELO_MIXTRAL, messages=messages, temperature=0.7, max_tokens=600
            )
        )

        resp_gemma, resp_mixtral = await asyncio.gather(tarea_gemma, tarea_mixtral)
        texto_gemma = resp_gemma.choices[0].message.content
        texto_mixtral = resp_mixtral.choices[0].message.content

        prompt_juez = [
            {"role": "system", "content": "Eres Carek. Combina los datos exactos y lógica de la Opción A con la fluidez de la Opción B. Usa Markdown."},
            {"role": "user", "content": f"Opción A:\n{texto_gemma}\n\nOpción B:\n{texto_mixtral}\n\nGenera la respuesta final ideal:"}
        ]
        resp_final = await loop.run_in_executor(
            None, lambda: groq_client.chat.completions.create(
                model=MODELO_LLAMA, messages=prompt_juez, temperature=0.7, max_tokens=1000
            )
        )
        return resp_final.choices[0].message.content
    except Exception as e:
        return f"❌ Error en la consulta IA: {e}"

async def ia_extraer_mapeo_fuente(ejemplo_texto: str) -> dict:
    prompt = (
        f"Analiza la tipografía: '{ejemplo_texto}'. Extrae las letras especiales y genera "
        "un JSON con el mapeo del abecedario. Responde ÚNICAMENTE el JSON.\n"
        'Estructura: {"a": "...", "A": "..."}'
    )
    loop = asyncio.get_event_loop()
    completion = await loop.run_in_executor(
        None, lambda: groq_client.chat.completions.create(
            model=MODELO_GEMMA, messages=[{"role": "user", "content": prompt}], temperature=0.1
        )
    )
    return json.loads(completion.choices[0].message.content.strip())

# =====================================================================
# 💬 1. COMANDO /IA
# =====================================================================
@bot.tree.command(name="ia", description="Habla con Carek (Ensamble de IAs)")
@app_commands.describe(mensaje="Tu pregunta o consulta")
async def ia(interaction: discord.Interaction, mensaje: str):
    await interaction.response.defer()
    
    info_web = ""
    # Búsqueda web condicional (ahorra recursos y latencia)
    if necesita_busqueda(mensaje):
        info_web = await buscar_en_web(mensaje)
        
    usuario_id = interaction.user.id
    historial = memoria_ia[usuario_id]
    
    # Agregar mensaje del usuario y obtener contexto actualizado (expira a los 45 min)
    historial.agregar("user", mensaje)
    contexto = historial.actualizar_y_obtener()
    
    respuesta = await consultar_groq_ensamble(contexto, es_resumen=False, info_web=info_web)
    
    if not respuesta.startswith("❌"):
        historial.agregar("assistant", respuesta)
    
    if len(respuesta) > 2000:
        respuesta = respuesta[:1990] + "..."
        
    await interaction.followup.send(f"🤖 {respuesta}")

# =====================================================================
# 🎨 2. GESTIÓN DE TIPOGRAFÍAS (/fuente)
# =====================================================================
grupo_fuente = app_commands.Group(name="fuente", description="Gestión de tipografías")

@grupo_fuente.command(name="escanear")
@app_commands.checks.has_permissions(manage_channels=True)
async def escanear_fuente(interaction: discord.Interaction, nombre_guardar: str):
    canales_texto = [c for c in interaction.guild.channels if isinstance(c, discord.TextChannel)]
    class SelectCanalView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.select = discord.ui.Select(options=[discord.SelectOption(label=f"#{c.name}", value=str(c.id)) for c in canales_texto[:25]])
            self.select.callback = self.callback
            self.add_item(self.select)

        async def callback(self, inter: discord.Interaction):
            await inter.response.defer(ephemeral=True)
            canal = inter.guild.get_channel(int(self.select.values[0]))
            try:
                mapeo = await ia_extraer_mapeo_fuente(canal.name)
                guardar_fuente(inter.guild_id, nombre_guardar, mapeo)
                await inter.followup.send(f"🧠 Se analizó {canal.mention} y se guardó la fuente **{nombre_guardar}**.")
            except Exception as e:
                await inter.followup.send(f"❌ Error: {e}")

    await interaction.response.send_message("📋 **Selecciona el canal para escanear:**", view=SelectCanalView(), ephemeral=True)

@grupo_fuente.command(name="aplicar")
@app_commands.checks.has_permissions(manage_channels=True)
async def aplicar_fuente_cmd(interaction: discord.Interaction, canal: discord.TextChannel, estilo: str, emoji: str = "💬"):
    await interaction.response.defer(ephemeral=True)
    fuentes = cargar_fuentes(interaction.guild_id)
    if estilo.lower() not in fuentes:
        return await interaction.followup.send(f"❌ Fuente **{estilo}** no encontrada.")
    nombre_limpio = canal.name.split("｜")[-1].replace("-", " ").strip()
    nuevo_nombre = f"{emoji}｜{aplicar_mapeo(nombre_limpio, fuentes[estilo.lower()])}".replace(" ", "-")
    await canal.edit(name=nuevo_nombre)
    await interaction.followup.send(f"🎨 Canal rediseñado: {canal.mention}")

@grupo_fuente.command(name="listar")
async def listar_fuentes(interaction: discord.Interaction):
    fuentes = cargar_fuentes(interaction.guild_id)
    if not fuentes: return await interaction.response.send_message("📂 No hay tipografías guardadas.", ephemeral=True)
    embed = discord.Embed(title="🎨 Tipografías", color=discord.Color.blue())
    for nombre, mapeo in fuentes.items():
        embed.add_field(name=f"📌 {nombre.capitalize()}", value=f"`{aplicar_mapeo('Ejemplo', mapeo)}`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@grupo_fuente.command(name="probar")
async def probar_fuente(interaction: discord.Interaction, texto: str, estilo: str, emoji: str = "💬"):
    fuentes = cargar_fuentes(interaction.guild_id)
    if estilo.lower() not in fuentes: return await interaction.response.send_message(f"❌ Fuente inexistente.", ephemeral=True)
    resultado = f"{emoji}｜{aplicar_mapeo(texto, fuentes[estilo.lower()])}".replace(" ", "-")
    await interaction.response.send_message(f"👁️ **Vista Previa:** `{resultado}`", ephemeral=True)

@grupo_fuente.command(name="eliminar")
@app_commands.checks.has_permissions(manage_channels=True)
async def eliminar_fuente_cmd(interaction: discord.Interaction, nombre: str):
    if eliminar_fuente(interaction.guild_id, nombre):
        await interaction.response.send_message(f"🗑️ Tipografía **{nombre}** eliminada.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ No se encontró **{nombre}**.", ephemeral=True)

bot.tree.add_command(grupo_fuente)

# =====================================================================
# 🧹 3. LIMPIAR MEMORIA (/limpiar)
# =====================================================================
grupo_limpiar = app_commands.Group(name="limpiar", description="Borra la memoria del bot")

@grupo_limpiar.command(name="mi_historial")
async def limpiar_mi_historial(interaction: discord.Interaction):
    memoria_ia[interaction.user.id].limpiar()
    await interaction.response.send_message("🧹 Tu historial de IA ha sido borrado y reiniciado.", ephemeral=True)

@grupo_limpiar.command(name="todo")
@app_commands.checks.has_permissions(administrator=True)
async def limpiar_todo(interaction: discord.Interaction):
    memoria_ia.clear()
    await interaction.response.send_message("🧹 Memoria global de la IA reiniciada para todos los usuarios.")

bot.tree.add_command(grupo_limpiar)

# =====================================================================
# 📊 4. RESÚMENES DE CHAT (/resumen)
# =====================================================================
grupo_resumen = app_commands.Group(name="resumen", description="Resúmenes inteligentes del chat")

def parsear_fecha(txt: str) -> Optional[datetime]:
    partes = txt.strip().split("/")
    anio_actual = datetime.now(timezone.utc).year
    try:
        if len(partes) == 2: return datetime(anio_actual, int(partes[1]), int(partes[0]), tzinfo=timezone.utc)
        elif len(partes) == 3:
            a = int(partes[2])
            if a < 100: a += 2000
            return datetime(a, int(partes[1]), int(partes[0]), tzinfo=timezone.utc)
    except: return None
    return None

async def obtener_resumen(interaction: discord.Interaction, titulo: str, limit: int = 1000, after=None, before=None, autor=None):
    await interaction.response.defer()
    mensajes_texto = []
    
    async for msg in interaction.channel.history(limit=limit, after=after, before=before, oldest_first=True):
        if msg.author.bot or not msg.content.strip(): continue
        if autor and msg.author != autor: continue
        
        fecha_str = msg.created_at.strftime("%d/%m")
        mensajes_texto.append(f"[{fecha_str}] {msg.author.display_name}: {msg.content}")

    if not mensajes_texto:
        return await interaction.followup.send(f"📌 **{titulo}**\n*Sin actividad o mensajes registrados que coincidan.*")

    texto_completo = "\n".join(mensajes_texto)
    palabras = texto_completo.split()
    if len(palabras) > 2000: texto_completo = " ".join(palabras[:2000])

    resumen_txt = await consultar_groq_ensamble(texto_completo, es_resumen=True)
    resultado = f"📊 **{titulo}**\n\n{resumen_txt}"
    await interaction.followup.send(resultado[:1990] + "..." if len(resultado) > 2000 else resultado)

@grupo_resumen.command(name="defecto")
async def res_defecto(interaction: discord.Interaction):
    await obtener_resumen(interaction, "Resumen (Últimos 100 mensajes)", limit=100)

@grupo_resumen.command(name="hoy")
async def res_hoy(interaction: discord.Interaction):
    inicio_hoy = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    await obtener_resumen(interaction, "Resumen de Hoy", after=inicio_hoy)

@grupo_resumen.command(name="dia")
async def res_dia(interaction: discord.Interaction, fecha: str):
    dt = parsear_fecha(fecha)
    if not dt: return await interaction.response.send_message("❌ Fecha inválida. Usa `DD/MM`.", ephemeral=True)
    dt_fin = dt.replace(hour=23, minute=59, second=59)
    await obtener_resumen(interaction, f"Resumen del Día ({fecha})", after=dt, before=dt_fin)

@grupo_resumen.command(name="rango")
async def res_rango(interaction: discord.Interaction, fecha_inicio: str, fecha_fin: str):
    dt_ini = parsear_fecha(fecha_inicio)
    dt_fin = parsear_fecha(fecha_fin)
    if not dt_ini or not dt_fin: return await interaction.response.send_message("❌ Formato inválido.", ephemeral=True)
    dt_fin = dt_fin.replace(hour=23, minute=59, second=59)
    await obtener_resumen(interaction, f"Resumen entre {fecha_inicio} y {fecha_fin}", after=dt_ini, before=dt_fin)

@grupo_resumen.command(name="mensajes")
async def res_mensajes(interaction: discord.Interaction, cantidad: int):
    if cantidad < 1 or cantidad > 1000: return await interaction.response.send_message("❌ La cantidad debe estar entre 1 y 1000.", ephemeral=True)
    await obtener_resumen(interaction, f"Resumen de {cantidad} mensajes", limit=cantidad)

@grupo_resumen.command(name="tiempo")
async def res_tiempo(interaction: discord.Interaction, horas: int):
    after_dt = datetime.now(timezone.utc) - timedelta(hours=horas)
    await obtener_resumen(interaction, f"Resumen de las últimas {horas} horas", after=after_dt)

@grupo_resumen.command(name="persona")
async def res_persona(interaction: discord.Interaction, usuario: discord.Member, fecha: str):
    dt = parsear_fecha(fecha)
    if not dt: return await interaction.response.send_message("❌ Fecha inválida.", ephemeral=True)
    dt_fin = dt.replace(hour=23, minute=59, second=59)
    await obtener_resumen(interaction, f"Actividad de {usuario.display_name} el {fecha}", after=dt, before=dt_fin, autor=usuario)

bot.tree.add_command(grupo_resumen)

# =====================================================================
# 🛠️ 5. GESTIÓN ADMINISTRATIVA (/gestionar)
# =====================================================================
grupo_gestionar = app_commands.Group(name="gestionar", description="Gestión del servidor")

@grupo_gestionar.command(name="canales")
@app_commands.checks.has_permissions(manage_channels=True)
async def crear_canales(interaction: discord.Interaction, nombres: str, categoria: Optional[discord.CategoryChannel] = None):
    await interaction.response.defer(ephemeral=True)
    nombres_list = [n.strip() for n in nombres.split(",") if n.strip()][:5]
    creados = []
    for n in nombres_list:
        ch = await interaction.guild.create_text_channel(name=n, category=categoria)
        creados.append(ch.mention)
    await interaction.followup.send(f"✅ Creados: {', '.join(creados)}")

@grupo_gestionar.command(name="categoria")
@app_commands.checks.has_permissions(manage_channels=True)
async def crear_categoria(interaction: discord.Interaction, nombre: str):
    await interaction.response.defer(ephemeral=True)
    cat = await interaction.guild.create_category(name=nombre)
    await interaction.followup.send(f"✅ Categoría **{cat.name}** creada.")

@grupo_gestionar.command(name="renombrar")
@app_commands.checks.has_permissions(manage_channels=True)
async def renombrar_canal(interaction: discord.Interaction, canal: discord.TextChannel, nuevo_nombre: str):
    await canal.edit(name=nuevo_nombre.replace(" ", "-"))
    await interaction.response.send_message(f"✅ Canal renombrado a {canal.mention}.", ephemeral=True)

bot.tree.add_command(grupo_gestionar)

# =====================================================================
# 🗑️ 6. ELIMINACIÓN DE CANALES (/eliminar)
# =====================================================================
grupo_eliminar = app_commands.Group(name="eliminar", description="Opciones de eliminación de canales")

class ConfirmarBorradoCanales(discord.ui.View):
    def __init__(self, canales: List[discord.abc.GuildChannel]):
        super().__init__(timeout=45)
        self.canales = canales

    @discord.ui.button(label="🔴 Seguro", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="🗑️ Eliminando canales...", view=None)
        eliminados = 0
        for c in self.canales:
            try:
                await c.delete()
                eliminados += 1
            except: pass
        if interaction.channel in self.canales: return # Si el canal actual fue borrado, no seguimos respondiendo
        await interaction.followup.send(f"✅ Se eliminaron {eliminados} canales.", ephemeral=True)

    @discord.ui.button(label="⚪ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Operación cancelada.", view=None)

@grupo_eliminar.command(name="actual", description="Borra el canal actual")
@app_commands.checks.has_permissions(manage_channels=True)
async def elim_actual(interaction: discord.Interaction):
    view = ConfirmarBorradoCanales([interaction.channel])
    await interaction.response.send_message("⚠️ **¿Seguro que quieres eliminar ESTE canal? La acción es irreversible.**", view=view, ephemeral=True)

@grupo_eliminar.command(name="especificos", description="Selecciona hasta 5 canales para borrar")
@app_commands.checks.has_permissions(manage_channels=True)
async def elim_especificos(interaction: discord.Interaction):
    class SelectEliminar(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.select = discord.ui.ChannelSelect(
                placeholder="Elige hasta 5 canales...", 
                max_values=5, 
                channel_types=[discord.ChannelType.text, discord.ChannelType.voice]
            )
            self.select.callback = self.callback
            self.add_item(self.select)
            
        async def callback(self, inter: discord.Interaction):
            canales_obj = [inter.guild.get_channel(c.id) for c in self.select.values if inter.guild.get_channel(c.id)]
            nombres = ", ".join([c.name for c in canales_obj])
            view = ConfirmarBorradoCanales(canales_obj)
            await inter.response.edit_message(content=f"⚠️ **¿Seguro que quieres eliminar estos canales?**\n`{nombres}`", view=view)

    await interaction.response.send_message("🗑️ **Selecciona los canales a eliminar:**", view=SelectEliminar(), ephemeral=True)

@grupo_eliminar.command(name="masivo", description="Borra en lote canales que contengan una palabra")
@app_commands.checks.has_permissions(manage_channels=True)
async def elim_masivo(interaction: discord.Interaction, filtro: str, cantidad: int):
    if cantidad > 500: return await interaction.response.send_message("❌ El límite masivo es 500 canales.", ephemeral=True)
    canales_coincidentes = [c for c in interaction.guild.channels if filtro.lower() in c.name.lower()][:cantidad]
    
    if not canales_coincidentes:
        return await interaction.response.send_message(f"❌ No encontré ningún canal que contenga `{filtro}`.", ephemeral=True)
        
    view = ConfirmarBorradoCanales(canales_coincidentes)
    await interaction.response.send_message(f"⚠️ **¿Seguro que quieres eliminar {len(canales_coincidentes)} canales que contienen `{filtro}`?**", view=view, ephemeral=True)

bot.tree.add_command(grupo_eliminar)

# =====================================================================
# 📌 MANEJO DE ERRORES DE PERMISOS
# =====================================================================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ No tienes los permisos necesarios para ejecutar este comando."
        if interaction.response.is_done(): await interaction.followup.send(msg, ephemeral=True)
        else: await interaction.response.send_message(msg, ephemeral=True)

# =====================================================================
# ❓ 7. AYUDA (/help)
# =====================================================================
@bot.tree.command(name="help", description="Guía completa de comandos de Carek")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 MANUAL DE COMANDOS CAREK", color=discord.Color.blue())
    embed.add_field(name="💬 IA y Limpieza", value="`/ia` • `/limpiar mi_historial` • `/limpiar todo`", inline=False)
    embed.add_field(name="🎨 Tipografías", value="`/fuente escanear` • `/fuente aplicar` • `/fuente listar`\n`/fuente probar` • `/fuente eliminar`", inline=False)
    embed.add_field(name="📊 Resúmenes", value="`/resumen defecto` • `/resumen hoy` • `/resumen dia`\n`/resumen rango` • `/resumen mensajes`\n`/resumen tiempo` • `/resumen persona`", inline=False)
    embed.add_field(name="🛠️ Gestión", value="`/gestionar canales` • `/gestionar categoria` • `/gestionar renombrar`", inline=False)
    embed.add_field(name="🗑️ Purga de Canales", value="`/eliminar actual` • `/eliminar especificos` • `/eliminar masivo`", inline=False)
    await interaction.response.send_message(embed=embed)

# =====================================================================
# 🚀 EJECUCIÓN
# =====================================================================
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ ERROR: Falta la variable DISCORD_TOKEN.")
    else:
        keep_alive()
        bot.run(TOKEN)
