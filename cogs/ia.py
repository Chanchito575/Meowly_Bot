import os
import re
import asyncio
import collections
from typing import Optional
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from duckduckgo_search import DDGS

import openai
from groq import AsyncGroq

# ---------------------------------------------------------
# 🤖 MEMORIA Y CLIENTES DE IA
# ---------------------------------------------------------
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

# ---------------------------------------------------------
# 🔍 HELPERS BÚSQUEDA Y ENSAMBLE
# ---------------------------------------------------------
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
                model=MODELO_MISTRAL, messages=messages, temperature=0.5, max_tokens=1500
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
            model=MODELO_QWEN, messages=messages, temperature=0.5, max_tokens=1500
        )
        texto_qwen = resp_qwen.choices[0].message.content
    except Exception as e:
        print(f"⚠️ Fallo Qwen: {e}")

    try:
        resp_mistral = await mistral_client.chat.completions.create(
            model=MODELO_MISTRAL, messages=messages, temperature=0.7, max_tokens=1500
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
            model=MODELO_JUEZ, messages=prompt_juez, temperature=0.7, max_tokens=1500
        )
        return resp_final.choices[0].message.content
    except Exception as e:
        return texto_qwen

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

# ---------------------------------------------------------
# 🧩 COG INTELIGENCIA ARTIFICIAL Y RESÚMENES
# ---------------------------------------------------------
class IA(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ia", description="Habla con Meowly (Ensamble de IAs)")
    @app_commands.describe(mensaje="Tu pregunta o consulta")
    async def ia(self, interaction: discord.Interaction, mensaje: str):
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
        
        if len(respuesta) <= 1900:
            await interaction.followup.send(f"🐱 {respuesta}")
        else:
            await interaction.followup.send(f"🐱 {respuesta[:1900]}")
            for i in range(1900, len(respuesta), 1900):
                await interaction.channel.send(respuesta[i:i+1900])

    # Grupo Limpiar
    grupo_limpiar = app_commands.Group(name="limpiar", description="Borra la memoria del bot")

    @grupo_limpiar.command(name="mi_historial", description="Borra tu conversación personal guardada con la IA")
    async def limpiar_mi_historial(self, interaction: discord.Interaction):
        memoria_ia[interaction.user.id].limpiar()
        await interaction.response.send_message(f"🧹 El historial de IA de {interaction.user.mention} ha sido borrado.")

    @grupo_limpiar.command(name="todo", description="Borra todo el historial de la IA de todos los usuarios")
    @app_commands.checks.has_permissions(administrator=True)
    async def limpiar_todo(self, interaction: discord.Interaction):
        memoria_ia.clear()
        await interaction.response.send_message("🧹 Memoria global de la IA reiniciada para todos los usuarios.")

    # Grupo Resumen
    grupo_resumen = app_commands.Group(name="resumen", description="Resúmenes inteligentes del chat")

    async def obtener_resumen(self, interaction: discord.Interaction, titulo: str, limit: int = 1000, after=None, before=None, autor=None):
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

        if len(resultado) <= 1900:
            await interaction.followup.send(resultado)
        else:
            await interaction.followup.send(resultado[:1900])
            for i in range(1900, len(resultado), 1900):
                await interaction.channel.send(resultado[i:i+1900])

    @grupo_resumen.command(name="defecto", description="Resume los últimos 100 mensajes enviados")
    async def res_defecto(self, interaction: discord.Interaction):
        await self.obtener_resumen(interaction, "Resumen (Últimos 100 mensajes)", limit=100)

    @grupo_resumen.command(name="hoy", description="Resume los mensajes enviados el día de hoy")
    async def res_hoy(self, interaction: discord.Interaction):
        inicio_hoy = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        await self.obtener_resumen(interaction, "Resumen de Hoy", after=inicio_hoy)

    @grupo_resumen.command(name="dia", description="Resume la conversación de una fecha exacta (DD/MM)")
    async def res_dia(self, interaction: discord.Interaction, fecha: str):
        dt = parsear_fecha(fecha)
        if not dt: return await interaction.response.send_message("❌ Fecha inválida. Usa `DD/MM`.")
        dt_fin = dt.replace(hour=23, minute=59, second=59)
        await self.obtener_resumen(interaction, f"Resumen del Día ({fecha})", after=dt, before=dt_fin)

    @grupo_resumen.command(name="rango", description="Resume la actividad entre dos fechas (DD/MM a DD/MM)")
    async def res_rango(self, interaction: discord.Interaction, fecha_inicio: str, fecha_fin: str):
        dt_ini = parsear_fecha(fecha_inicio)
        dt_fin = parsear_fecha(fecha_fin)
        if not dt_ini or not dt_fin: return await interaction.response.send_message("❌ Formato inválido.")
        dt_fin = dt_fin.replace(hour=23, minute=59, second=59)
        await self.obtener_resumen(interaction, f"Resumen entre {fecha_inicio} y {fecha_fin}", after=dt_ini, before=dt_fin)

    @grupo_resumen.command(name="mensajes", description="Resume una cantidad específica de mensajes (hasta 1000)")
    async def res_mensajes(self, interaction: discord.Interaction, cantidad: int):
        if cantidad < 1 or cantidad > 1000: return await interaction.response.send_message("❌ La cantidad debe estar entre 1 y 1000.")
        await self.obtener_resumen(interaction, f"Resumen de {cantidad} mensajes", limit=cantidad)

    @grupo_resumen.command(name="tiempo", description="Resume la actividad del chat de las últimas N horas")
    async def res_tiempo(self, interaction: discord.Interaction, horas: int):
        after_dt = datetime.now(timezone.utc) - timedelta(hours=horas)
        await self.obtener_resumen(interaction, f"Resumen de las últimas {horas} horas", after=after_dt)

    @grupo_resumen.command(name="persona", description="Resume la actividad de un usuario en un día específico")
    async def res_persona(self, interaction: discord.Interaction, usuario: discord.Member, fecha: str):
        dt = parsear_fecha(fecha)
        if not dt: return await interaction.response.send_message("❌ Fecha inválida.")
        dt_fin = dt.replace(hour=23, minute=59, second=59)
        await self.obtener_resumen(interaction, f"Actividad de {usuario.display_name} el {fecha}", after=dt, before=dt_fin, autor=usuario)

async def setup(bot):
    await bot.add_cog(IA(bot))
