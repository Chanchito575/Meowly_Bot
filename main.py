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
from duckduckgo_search import DDGS
from keep_alive import keep_alive  # Servidor web Flask para Render

import openai
from groq import AsyncGroq # Librería oficial de Groq

import firebase_admin
from firebase_admin import credentials, firestore

# =====================================================================
# 🔐 CONFIGURACIÓN DE PROPIETARIO Y FIREBASE
# =====================================================================
MI_DISCORD_ID = 1122162289206902845  # Tu ID exclusivo para comandos secretos
b64_credentials = os.getenv("FIREBASE_CREDENTIALS_BASE64")

if b64_credentials:
    try:
        decoded_json = base64.b64decode(b64_credentials).decode("utf-8")
        cred_dict = json.loads(decoded_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("🔥 Firebase Firestore conectado con éxito.")
    except Exception as e:
        print(f"❌ Error al conectar con Firebase: {e}")
        db = None

=======================================================================
# ⚙️ CONFIGURACIÓN DEL BOT Y CLIENTES
# =====================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

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

# ---------------------------------------------------------
# 🤖 CONFIGURACIÓN DE LOS CLIENTES DE IA
# ---------------------------------------------------------
hf_client = openai.AsyncOpenAI(
    base_url="https://router.huggingface.co/v1/",
    api_key=os.getenv("HF_TOKEN"),
    timeout=15.0
)

mistral_client = openai.AsyncOpenAI(
    base_url="https://api.mistral.ai/v1/",
    api_key=os.getenv("MISTRAL_API_KEY"),
    timeout=15.0
)

groq_client = AsyncGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    timeout=15.0
)

MODELO_QWEN = "Qwen/Qwen2.5-Coder-32B-Instruct" 
MODELO_MISTRAL = "mistral-small-latest"         
MODELO_JUEZ = "llama-3.1-8b-instant"         

@bot.event
async def on_ready():
    await bot.tree.sync()
    actividad = discord.Game(name="creado por <@1122162289206902845> | /help")
    await bot.change_presence(status=discord.Status.online, activity=actividad)
    print(f"✅ Bot conectado con éxito como {bot.user}")

# =====================================================================
# 📁 SISTEMA DE FUENTES (FIREBASE FIRESTORE)
# =====================================================================
def cargar_fuentes(guild_id: int) -> dict:
    if not db: return {}
    doc = db.collection("servidores").document(str(guild_id)).get()
    return doc.to_dict().get("fuentes", {}) if doc.exists else {}

def guardar_fuente(guild_id: int, nombre: str, mapeo: dict):
    if not db: return
    doc_ref = db.collection("servidores").document(str(guild_id))
    doc_ref.set({"fuentes": {nombre.lower(): mapeo}}, merge=True)

def eliminar_fuente(guild_id: int, nombre: str) -> bool:
    if not db: return False
    doc_ref = db.collection("servidores").document(str(guild_id))
    doc = doc_ref.get()
    if doc.exists and nombre.lower() in doc.to_dict().get("fuentes", {}):
        doc_ref.update({f"fuentes.{nombre.lower()}": firestore.DELETE_FIELD})
        return True
    return False

def aplicar_mapeo(texto: str, mapeo: dict) -> str:
    return "".join(mapeo.get(c, c) for c in texto)

# =====================================================================
# 🔍 BÚSQUEDA WEB CONDICIONAL
# =====================================================================
def necesita_busqueda(mensaje: str) -> bool:
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
# 🧠 ENSAMBLE DE IAS (Multicliente)
# =====================================================================
async def consultar_ensamble(prompt_o_mensajes, es_resumen=False, info_web="") -> str:
    if es_resumen:
        system_prompt = (
            "Eres Meowly, un asistente analítico. Resume la conversación desglosando "
            "los puntos clave exactos. Usa un formato claro con viñetas y emojis."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Resume lo siguiente:\n\n{prompt_o_mensajes}"}
        ]
        try:
            resp = await mistral_client.chat.completions.create(
                model=MODELO_MISTRAL, messages=messages, temperature=0.5, max_tokens=1024
            )
            return resp.choices[0].message.content
        except Exception as e:
            return f"❌ Error en Mistral (Resumen): {e}"

    system_instrucciones = (
        "Eres Meowly, un asistente amigable, moderno y carismático para Discord. "
        "Si los usuarios te preguntan quién te creó o quién es tu creador, debes responder algo similar a esto: 'me creó <@1122162289206902845>'."
    )
    
    base_messages = [{"role": "system", "content": system_instrucciones}]
    if info_web:
        base_messages.append({"role": "user", "content": f"Información web reciente para usar de contexto si es necesario:\n{info_web}\n\n"})
    
    messages = base_messages + list(prompt_o_mensajes)

    texto_qwen = None
    texto_mistral = None

    try:
        resp_qwen = await hf_client.chat.completions.create(
            model=MODELO_QWEN, messages=messages, temperature=0.5, max_tokens=600
        )
        texto_qwen = resp_qwen.choices[0].message.content
    except Exception as e:
        print(f"⚠️ Fallo Qwen: {e}")

    try:
        resp_mistral = await mistral_client.chat.completions.create(
            model=MODELO_MISTRAL, messages=messages, temperature=0.7, max_tokens=600
        )
        texto_mistral = resp_mistral.choices[0].message.content
    except Exception as e:
        print(f"⚠️ Fallo Mistral: {e}")

    if not texto_qwen and not texto_mistral:
        return "❌ Error de conexión con los servicios de IA."

    if texto_qwen and not texto_mistral: return texto_qwen
    if texto_mistral and not texto_qwen: return texto_mistral

    try:
        prompt_juez = [
            {"role": "system", "content": "Eres Meowly. Combina los datos exactos y lógica de la Opción A con la fluidez de la Opción B. Si te preguntan sobre quién te creó, asegúrate de mantener la respuesta: 'me creó <@1122162289206902845>'. Usa Markdown."},
            {"role": "user", "content": f"Opción A:\n{texto_qwen}\n\nOpción B:\n{texto_mistral}\n\nGenera la respuesta final ideal:"}
        ]
        resp_final = await groq_client.chat.completions.create(
            model=MODELO_JUEZ, messages=prompt_juez, temperature=0.7, max_tokens=1000
        )
        return resp_final.choices[0].message.content
    except Exception as e:
        return texto_qwen
async def ia_extraer_mapeo_fuente(ejemplo_texto: str) -> dict:
    prompt = (
        f"Analiza la tipografía del texto: '{ejemplo_texto}'. Extrae los caracteres especiales "
        "y genera un JSON mapeando cada letra normal con su carácter tipográfico especial.\n"
        "Responde ÚNICAMENTE el JSON sin bloques de código ni explicación adicional.\n"
        'Ejemplo de salida: {"a": "ⓐ", "b": "ⓑ", "A": "Ⓐ"}'
    )
    
    # 1. Intento principal con Mistral (Muy estable)
    try:
        resp = await mistral_client.chat.completions.create(
            model=MODELO_MISTRAL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500
        )
        contenido = resp.choices[0].message.content.strip()
        if "```json" in contenido:
            contenido = contenido.split("```json")[1].split("```")[0].strip()
        elif "```" in contenido:
            contenido = contenido.split("```")[1].split("```")[0].strip()
        return json.loads(contenido)
    except Exception as e:
        print(f"⚠️ Mistral falló procesando fuente: {e}. Probando respaldo...")

    # 2. Respaldo secundario con Hugging Face (Qwen)
    try:
        resp = await hf_client.chat.completions.create(
            model=MODELO_QWEN,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500
        )
        contenido = resp.choices[0].message.content.strip()
        if "```json" in contenido:
            contenido = contenido.split("```json")[1].split("```")[0].strip()
        elif "```" in contenido:
            contenido = contenido.split("```")[1].split("```")[0].strip()
        return json.loads(contenido)
    except Exception as e:
        print(f"⚠️ Hugging Face también falló: {e}")

    raise Exception("No se pudo procesar el formato JSON de la fuente.")

# =====================================================================
# 🕵️ COMANDO SECRETOS Y DIAGNÓSTICO PRIVADO (/testear)
# =====================================================================
@bot.tree.command(name="testear", description="Diagnóstico privado del bot")
async def testear(interaction: discord.Interaction):
    if interaction.user.id != MI_DISCORD_ID:
        return await interaction.response.send_message("❌ Comando no reconocido.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    
    latencia = round(bot.latency * 1000)
    
    # Pruebas internas
    estado_db = "❌ Desconectado"
    if db:
        try:
            db.collection("test").document("ping").set({"last_ping": datetime.now(timezone.utc).isoformat()})
            estado_db = "✅ Operativo (Firebase Firestore)"
        except Exception as e:
            estado_db = f"❌ Error: {e}"

    try:
        res_web = await buscar_en_web("Python")
        estado_web = "✅ Operativo (DuckDuckGo)" if res_web and "No se pudo" not in res_web else "⚠️ Sin conexión"
    except Exception as e:
        estado_web = f"❌ Falla: {e}"

    permisos = interaction.app_permissions
    estado_permisos = "✅ Ok (Gestionar Canales)" if permisos.manage_channels else "❌ Faltan permisos de Administración"

    embed = discord.Embed(title="🕵️ Diagnóstico Privado - Meowly", color=discord.Color.dark_purple())
    embed.add_field(name="📶 Latencia de Discord", value=f"`{latencia} ms`", inline=True)
    embed.add_field(name="🌐 Búsqueda Web", value=f"`{estado_web}`", inline=True)
    embed.add_field(name="🔥 Base de Datos Cloud", value=f"`{estado_db}`", inline=False)
    embed.add_field(name="🛠️ Permisos en Canal", value=f"`{estado_permisos}`", inline=False)
    embed.set_footer(text="Vista exclusiva del Creador")

    await interaction.followup.send(embed=embed, ephemeral=True)

# =====================================================================
# 💬 1. COMANDO /IA
# =====================================================================
@bot.tree.command(name="ia", description="Habla con Meowly (Ensamble de IAs)")
@app_commands.describe(mensaje="Tu pregunta o consulta")
async def ia(interaction: discord.Interaction, mensaje: str):
    await interaction.response.defer()
    
    info_web = ""
    if necesita_busqueda(mensaje):
        info_web = await buscar_en_web(mensaje)
        
    usuario_id = interaction.user.id
    historial = memoria_ia[usuario_id]
    
    historial.agregar("user", mensaje)
    contexto = historial.actualizar_y_obtener()
    
    respuesta = await consultar_ensamble(contexto, es_resumen=False, info_web=info_web)
    
    if not respuesta.startswith("❌"):
        historial.agregar("assistant", respuesta)
    
    if len(respuesta) > 2000:
        respuesta = respuesta[:1990] + "..."
        
    await interaction.followup.send(f"🐱 {respuesta}")

# =====================================================================
# 🎨 2. GESTIÓN DE TIPOGRAFÍAS (/fuente)
# =====================================================================
grupo_fuente = app_commands.Group(name="fuente", description="Gestión de tipografías")
grupo_escanear = app_commands.Group(name="escanear", description="Escanear y guardar tipografías", parent=grupo_fuente)

@grupo_escanear.command(name="mensaje", description="Extrae una fuente directamente desde un texto o abecedario")
@app_commands.checks.has_permissions(manage_channels=True)
async def escanear_mensaje(interaction: discord.Interaction, mensaje: str, nombre_guardar: str):
    await interaction.response.defer()
    try:
        mapeo = await ia_extraer_mapeo_fuente(mensaje)
        guardar_fuente(interaction.guild_id, nombre_guardar, mapeo)
        await interaction.followup.send(f"🧠 Se analizó el texto ingresado y se guardó la fuente **{nombre_guardar}** permanentemente en Firebase.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error al procesar la tipografía: {e}")

@grupo_escanear.command(name="canal", description="Extrae la fuente del nombre de un canal existente")
@app_commands.checks.has_permissions(manage_channels=True)
async def escanear_canal(interaction: discord.Interaction, canal: discord.TextChannel, nombre_guardar: str):
    await interaction.response.defer()
    try:
        mapeo = await ia_extraer_mapeo_fuente(canal.name)
        guardar_fuente(interaction.guild_id, nombre_guardar, mapeo)
        await interaction.followup.send(f"🧠 Se analizó {canal.mention} y se guardó la fuente **{nombre_guardar}** permanentemente en Firebase.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error al procesar la tipografía: {e}")

@grupo_fuente.command(name="aplicar", description="Aplica una fuente guardada al nombre de un canal")
@app_commands.checks.has_permissions(manage_channels=True)
async def aplicar_fuente_cmd(interaction: discord.Interaction, canal: discord.TextChannel, estilo: str, emoji: str = "💬"):
    await interaction.response.defer()
    fuentes = cargar_fuentes(interaction.guild_id)
    if estilo.lower() not in fuentes:
        return await interaction.followup.send(f"❌ Fuente **{estilo}** no encontrada en la base de datos.")
    nombre_limpio = canal.name.split("｜")[-1].replace("-", " ").strip()
    nuevo_nombre = f"{emoji}｜{aplicar_mapeo(nombre_limpio, fuentes[estilo.lower()])}".replace(" ", "-")
    await canal.edit(name=nuevo_nombre)
    await interaction.followup.send(f"🎨 Canal rediseñado: {canal.mention}")

@grupo_fuente.command(name="listar", description="Muestra las tipografías guardadas en el servidor")
async def listar_fuentes(interaction: discord.Interaction):
    fuentes = cargar_fuentes(interaction.guild_id)
    if not fuentes: return await interaction.response.send_message("📂 No hay tipografías guardadas.")
    embed = discord.Embed(title="🎨 Tipografías Registradas en Firebase", color=discord.Color.blue())
    for nombre, mapeo in fuentes.items():
        embed.add_field(name=f"📌 {nombre.capitalize()}", value=f"`{aplicar_mapeo('Ejemplo', mapeo)}`", inline=False)
    await interaction.response.send_message(embed=embed)

@grupo_fuente.command(name="probar", description="Genera una vista previa de un texto con una fuente")
async def probar_fuente(interaction: discord.Interaction, texto: str, estilo: str, emoji: str = "💬"):
    fuentes = cargar_fuentes(interaction.guild_id)
    if estilo.lower() not in fuentes: return await interaction.response.send_message("❌ Fuente inexistente.")
    resultado = f"{emoji}｜{aplicar_mapeo(texto, fuentes[estilo.lower()])}".replace(" ", "-")
    await interaction.response.send_message(f"👁️ **Vista Previa:** `{resultado}`")

@grupo_fuente.command(name="eliminar", description="Elimina una fuente del servidor")
@app_commands.checks.has_permissions(manage_channels=True)
async def eliminar_fuente_cmd(interaction: discord.Interaction, nombre: str):
    if eliminar_fuente(interaction.guild_id, nombre):
        await interaction.response.send_message(f"🗑️ Tipografía **{nombre}** eliminada de Firebase.")
    else:
        await interaction.response.send_message(f"❌ No se encontró la fuente **{nombre}**.")

bot.tree.add_command(grupo_fuente)

# =====================================================================
# 🧹 3. LIMPIAR MEMORIA (/limpiar)
# =====================================================================
grupo_limpiar = app_commands.Group(name="limpiar", description="Borra la memoria del bot")

@grupo_limpiar.command(name="mi_historial", description="Borra tu conversación personal guardada con la IA")
async def limpiar_mi_historial(interaction: discord.Interaction):
    memoria_ia[interaction.user.id].limpiar()
    await interaction.response.send_message(f"🧹 El historial de IA de {interaction.user.mention} ha sido borrado.")

@grupo_limpiar.command(name="todo", description="Borra todo el historial de la IA de todos los usuarios")
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

    resumen_txt = await consultar_ensamble(texto_completo, es_resumen=True)
    resultado = f"📊 **{titulo}**\n\n{resumen_txt}"
    await interaction.followup.send(resultado[:1990] + "..." if len(resultado) > 2000 else resultado)

@grupo_resumen.command(name="defecto", description="Resume los últimos 100 mensajes enviados")
async def res_defecto(interaction: discord.Interaction):
    await obtener_resumen(interaction, "Resumen (Últimos 100 mensajes)", limit=100)

@grupo_resumen.command(name="hoy", description="Resume los mensajes enviados el día de hoy")
async def res_hoy(interaction: discord.Interaction):
    inicio_hoy = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    await obtener_resumen(interaction, "Resumen de Hoy", after=inicio_hoy)

@grupo_resumen.command(name="dia", description="Resume la conversación de una fecha exacta (DD/MM)")
async def res_dia(interaction: discord.Interaction, fecha: str):
    dt = parsear_fecha(fecha)
    if not dt: return await interaction.response.send_message("❌ Fecha inválida. Usa `DD/MM`.")
    dt_fin = dt.replace(hour=23, minute=59, second=59)
    await obtener_resumen(interaction, f"Resumen del Día ({fecha})", after=dt, before=dt_fin)

@grupo_resumen.command(name="rango", description="Resume la actividad entre dos fechas (DD/MM a DD/MM)")
async def res_rango(interaction: discord.Interaction, fecha_inicio: str, fecha_fin: str):
    dt_ini = parsear_fecha(fecha_inicio)
    dt_fin = parsear_fecha(fecha_fin)
    if not dt_ini or not dt_fin: return await interaction.response.send_message("❌ Formato inválido.")
    dt_fin = dt_fin.replace(hour=23, minute=59, second=59)
    await obtener_resumen(interaction, f"Resumen entre {fecha_inicio} y {fecha_fin}", after=dt_ini, before=dt_fin)

@grupo_resumen.command(name="mensajes", description="Resume una cantidad específica de mensajes (hasta 1000)")
async def res_mensajes(interaction: discord.Interaction, cantidad: int):
    if cantidad < 1 or cantidad > 1000: return await interaction.response.send_message("❌ La cantidad debe estar entre 1 y 1000.")
    await obtener_resumen(interaction, f"Resumen de {cantidad} mensajes", limit=cantidad)

@grupo_resumen.command(name="tiempo", description="Resume la actividad del chat de las últimas N horas")
async def res_tiempo(interaction: discord.Interaction, horas: int):
    after_dt = datetime.now(timezone.utc) - timedelta(hours=horas)
    await obtener_resumen(interaction, f"Resumen de las últimas {horas} horas", after=after_dt)

@grupo_resumen.command(name="persona", description="Resume la actividad de un usuario en un día específico")
async def res_persona(interaction: discord.Interaction, usuario: discord.Member, fecha: str):
    dt = parsear_fecha(fecha)
    if not dt: return await interaction.response.send_message("❌ Fecha inválida.")
    dt_fin = dt.replace(hour=23, minute=59, second=59)
    await obtener_resumen(interaction, f"Actividad de {usuario.display_name} el {fecha}", after=dt, before=dt_fin, autor=usuario)

bot.tree.add_command(grupo_resumen)

# =====================================================================
# 🛠️ 5. GESTIÓN ADMINISTRATIVA (/gestionar)
# =====================================================================
grupo_gestionar = app_commands.Group(name="gestionar", description="Gestión del servidor")

@grupo_gestionar.command(name="canales", description="Crea varios canales de texto separados por comas (Máx 5)")
@app_commands.checks.has_permissions(manage_channels=True)
async def crear_canales(interaction: discord.Interaction, nombres: str, categoria: Optional[discord.CategoryChannel] = None):
    await interaction.response.defer()
    nombres_list = [n.strip() for n in nombres.split(",") if n.strip()][:5]
    creados = []
    for n in nombres_list:
        ch = await interaction.guild.create_text_channel(name=n, category=categoria)
        creados.append(ch.mention)
    await interaction.followup.send(f"✅ Creados: {', '.join(creados)}")

@grupo_gestionar.command(name="categoria", description="Crea una categoría nueva en el servidor")
@app_commands.checks.has_permissions(manage_channels=True)
async def crear_categoria(interaction: discord.Interaction, nombre: str):
    await interaction.response.defer()
    cat = await interaction.guild.create_category(name=nombre)
    await interaction.followup.send(f"✅ Categoría **{cat.name}** creada.")

@grupo_gestionar.command(name="renombrar", description="Cambia el nombre de un canal específico")
@app_commands.checks.has_permissions(manage_channels=True)
async def renombrar_canal(interaction: discord.Interaction, canal: discord.TextChannel, nuevo_nombre: str):
    await canal.edit(name=nuevo_nombre.replace(" ", "-"))
    await interaction.response.send_message(f"✅ Canal renombrado a {canal.mention}.")

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
        if interaction.channel in self.canales: return
        await interaction.followup.send(f"✅ Se eliminaron {eliminados} canales.")

    @discord.ui.button(label="⚪ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Operación cancelada.", view=None)

@grupo_eliminar.command(name="actual", description="Borra el canal en el que te encuentras")
@app_commands.checks.has_permissions(manage_channels=True)
async def elim_actual(interaction: discord.Interaction):
    view = ConfirmarBorradoCanales([interaction.channel])
    await interaction.response.send_message("⚠️ **¿Seguro que quieres eliminar ESTE canal? La acción es irreversible.**", view=view)

@grupo_eliminar.command(name="especificos", description="Abre un menú interactivo para borrar hasta 5 canales")
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

    await interaction.response.send_message("🗑️ **Selecciona los canales a eliminar:**", view=SelectEliminar())

@grupo_eliminar.command(name="masivo", description="Borra en lote los canales cuyo nombre contenga una palabra")
@app_commands.checks.has_permissions(manage_channels=True)
async def elim_masivo(interaction: discord.Interaction, filtro: str, cantidad: int):
    if cantidad > 500: return await interaction.response.send_message("❌ El límite masivo es 500 canales.")
    canales_coincidentes = [c for c in interaction.guild.channels if filtro.lower() in c.name.lower()][:cantidad]
    
    if not canales_coincidentes:
        return await interaction.response.send_message(f"❌ No encontré ningún canal que contenga `{filtro}`.")
        
    view = ConfirmarBorradoCanales(canales_coincidentes)
    await interaction.response.send_message(f"⚠️ **¿Seguro que quieres eliminar {len(canales_coincidentes)} canales que contienen `{filtro}`?**", view=view)

bot.tree.add_command(grupo_eliminar)

# =====================================================================
# 📌 MANEJO DE ERRORES DE PERMISOS
# =====================================================================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ No tienes los permisos necesarios para ejecutar este comando."
        if interaction.response.is_done(): await interaction.followup.send(msg)
        else: await interaction.response.send_message(msg)

# =====================================================================
# ❓ 7. GUÍA COMPLETA Y AYUDA (/help)
# =====================================================================
@bot.tree.command(name="help", description="Muestra la guía explicativa completa de todos los comandos")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 GUÍA COMPLETA DE COMANDOS - MEOWLY BOT",
        description="A continuación tienes la explicación detallada de cada grupo de comandos y sus funciones.",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="🐱 Inteligencia Artificial",
        value="• `/ia <mensaje>`: Conversa con Meowly (combina Qwen 2.5, Mistral y Groq Llama 3.3). Busca información en la web si detecta preguntas de temas actuales.",
        inline=False
    )
    
    embed.add_field(
        name="🧹 Memoria del Bot",
        value=(
            "• `/limpiar mi_historial`: Borra únicamente el contexto y la memoria de tus charlas con la IA.\n"
            "• `/limpiar todo`: (Solo Admins) Reinicia la memoria global de todos los usuarios."
        ),
        inline=False
    )

    embed.add_field(
        name="🎨 Gestión de Fuentes y Estilos (Firebase Cloud)",
        value=(
            "• `/fuente escanear mensaje <mensaje> <nombre>`: Analiza un texto o abecedario que le envíes directamente y guarda su tipografía.\n"
            "• `/fuente escanear canal <canal> <nombre>`: Analiza el tipo de letra del nombre de un canal existente.\n"
            "• `/fuente aplicar <canal> <estilo> [emoji]`: Aplica una fuente guardada al nombre de un canal.\n"
            "• `/fuente listar`: Lista las fuentes registradas en Firebase para este servidor.\n"
            "• `/fuente probar <texto> <estilo> [emoji]`: Muestra una vista previa de cómo quedaría un texto.\n"
            "• `/fuente eliminar <nombre>`: Borra una fuente de la nube del servidor."
        ),
        inline=False
    )

    embed.add_field(
        name="📊 Resúmenes con IA",
        value=(
            "• `/resumen defecto`: Resume los últimos 100 mensajes enviados.\n"
            "• `/resumen hoy`: Resume todo lo conversado en el día de hoy.\n"
            "• `/resumen dia <DD/MM>`: Extrae y resume la actividad de una fecha específica.\n"
            "• `/resumen rango <DD/MM_inicio> <DD/MM_fin>`: Genera un resumen en un periodo de fechas.\n"
            "• `/resumen mensajes <cantidad>`: Procesa exactamente la cantidad de mensajes indicada (hasta 1000).\n"
            "• `/resumen tiempo <horas>`: Resume la actividad de las últimas N horas.\n"
            "• `/resumen persona <usuario> <DD/MM>`: Sintetiza los mensajes de un usuario particular en un día concreto."
        ),
        inline=False
    )

    embed.add_field(
        name="🛠️ Gestión de Servidor",
        value=(
            "• `/gestionar canales <nombres>`: Crea hasta 5 canales de texto (separa los nombres por coma).\n"
            "• `/gestionar categoria <nombre>`: Crea una nueva categoría.\n"
            "• `/gestionar renombrar <canal> <nuevo_nombre>`: Renombra el canal elegido."
        ),
        inline=False
    )

    embed.add_field(
        name="🗑️ Purga y Borrado de Canales",
        value=(
            "• `/eliminar actual`: Muestra un menú de confirmación para eliminar el canal en el que te encuentras.\n"
            "• `/eliminar especificos`: Abre un menú desplegable para elegir hasta 5 canales a borrar a la vez.\n"
            "• `/eliminar masivo <filtro> <cantidad>`: Busca y elimina en lote los canales cuyo nombre coincida con la palabra clave especificada."
        ),
        inline=False
    )

    embed.set_footer(text="Bot programado por <@1122162289206902845>")
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
