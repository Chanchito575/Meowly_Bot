import os
import re
import asyncio
import collections
from typing import Optional, List
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

import openai
from groq import AsyncGroq

MAX_USUARIOS_MEMORIA = 100
MAX_MENSAJES_HISTORIAL = 12
MAX_CARACTERES_HISTORIAL = 6000
MINUTOS_EXPIRACION_MEMORIA = 40

MODELO_GROQ = os.getenv("MODELO_GROQ", "openai/gpt-oss-120b")
MODELO_GROQ_RESPALDO = os.getenv("MODELO_GROQ_RESPALDO", "openai/gpt-oss-20b")
MODELO_QWEN = os.getenv("MODELO_QWEN", "qwen/qwen3.6-plus:free")

USAR_ENSAMBLE = os.getenv("MODO_ENSAMBLE", "0") == "1"
COOLDOWN_429_SEG = 60

LIMITE_CARACTERES_RESPUESTA = 3800
LIMITE_CARACTERES_PARTE = 1900

SYSTEM_PROMPT_BASE = (
    "Eres Meowly, un asistente inteligente, amigable y carismático integrado en Discord. "
    "Tu objetivo es dar respuestas **claras, útiles y bien razonadas**.\n\n"
    "## Reglas de razonamiento\n"
    "1. Antes de responder, piensa internamente paso a paso: identifica qué se pregunta, "
    "qué información tienes y qué información falta.\n"
    "2. Si la pregunta es ambigua, responde con la interpretación más razonable y ofrece "
    "una breve aclaración al final.\n"
    "3. Si no sabes algo con certeza, dilo claramente en lugar de inventar.\n"
    "4. Usa el contexto de la conversación si es relevante, pero no repitas lo ya dicho.\n"
    "5. Si hay información web disponible, úsala como fuente prioritaria y menciónala.\n\n"
    "## Formato\n"
    "- Usa Markdown de Discord: **negrita**, *cursiva*, `código`, listas y bloques de código.\n"
    "- Sé conciso por defecto. Si el tema lo requiere, extiéndete con estructura clara.\n"
    "- No uses tablas (Discord no las renderiza bien).\n"
    "- Emojis con moderación, solo si aportan.\n\n"
    "## Identidad\n"
    "Si te preguntan quién te creó o quién es tu creador, responde que te creó <@{owner_id}>."
)


def leer_key(*nombres: str) -> Optional[str]:
    for n in nombres:
        v = os.getenv(n)
        if v:
            v = v.strip().strip('"').strip("'").strip()
            if v:
                return v
    return None


def describir_error(e: Exception) -> str:
    status = getattr(e, "status_code", None)
    cuerpo = getattr(e, "body", None) or getattr(e, "message", None) or str(e)
    return f"{type(e).__name__} | status={status} | {str(cuerpo)[:300]}"


def normalizar_mensajes(messages: list) -> list:
    system = [m["content"] for m in messages if m["role"] == "system"]
    resto = [m for m in messages if m["role"] != "system"]
    while resto and resto[0]["role"] != "user":
        resto.pop(0)
    fusion = []
    for m in resto:
        if fusion and fusion[-1]["role"] == m["role"]:
            fusion[-1]["content"] += "\n\n" + m["content"]
        else:
            fusion.append({"role": m["role"], "content": m["content"]})
    salida = []
    if system:
        salida.append({"role": "system", "content": "\n\n".join(system)})
    return salida + fusion


def truncar_historial(mensajes: list, max_caracteres: int = MAX_CARACTERES_HISTORIAL) -> list:
    total = sum(len(m.get("content", "")) for m in mensajes)
    if total <= max_caracteres:
        return mensajes
    recortado = []
    acumulado = 0
    for m in reversed(mensajes):
        c = len(m.get("content", ""))
        if acumulado + c > max_caracteres:
            break
        recortado.insert(0, m)
        acumulado += c
    while recortado and recortado[0]["role"] != "user":
        recortado.pop(0)
    return recortado


class HistorialIA:
    def __init__(self):
        self.mensajes = collections.deque(maxlen=MAX_MENSAJES_HISTORIAL)
        self.ultimo_uso = datetime.now(timezone.utc)
        self.lock = asyncio.Lock()

    async def actualizar_y_obtener(self) -> List[dict]:
        async with self.lock:
            ahora = datetime.now(timezone.utc)
            if (ahora - self.ultimo_uso) > timedelta(minutes=MINUTOS_EXPIRACION_MEMORIA):
                self.mensajes.clear()
            self.ultimo_uso = ahora
            return list(self.mensajes)

    async def agregar(self, rol: str, contenido: str):
        async with self.lock:
            self.mensajes.append({"role": rol, "content": contenido})
            self.ultimo_uso = datetime.now(timezone.utc)


memoria_ia: dict[int, HistorialIA] = {}
memoria_lock = asyncio.Lock()


async def obtener_historial_usuario(usuario_id: int) -> HistorialIA:
    async with memoria_lock:
        if len(memoria_ia) > MAX_USUARIOS_MEMORIA:
            ahora = datetime.now(timezone.utc)
            inactivos = [
                uid for uid, h in memoria_ia.items()
                if (ahora - h.ultimo_uso) > timedelta(minutes=MINUTOS_EXPIRACION_MEMORIA)
            ]
            for uid in inactivos:
                del memoria_ia[uid]
        if usuario_id not in memoria_ia:
            memoria_ia[usuario_id] = HistorialIA()
        return memoria_ia[usuario_id]


PATRONES_BUSQUEDA = [
    r"\bnoticia", r"\bnoticias\b", r"\bhoy\b", r"\bayer\b", r"\bmañana\b",
    r"\bactual\b", r"\bactualmente\b", r"\breciente\b",
    r"\bquién es\b", r"\bquien es\b", r"\bqué es\b", r"\bque es\b",
    r"\bcuánto\b", r"\bcuanto\b", r"\bprecio", r"\bcuesta\b",
    r"\bclima\b", r"\btiempo\b", r"\btemperatura\b",
    r"\bresultado", r"\bmarcador\b", r"\bpartido\b",
    r"\binvestiga\b", r"\bbusca\b", r"\bencuentra\b",
    r"\b2025\b", r"\b2026\b", r"\b2027\b",
    r"\bdónde\b", r"\bdonde\b", r"\bcómo llegar\b",
]


def necesita_busqueda(mensaje: str) -> bool:
    msg_lower = mensaje.lower()
    return any(re.search(p, msg_lower) for p in PATRONES_BUSQUEDA)


def _ejecutar_busqueda_ddg(consulta: str, max_reintentos: int = 2) -> str:
    for intento in range(max_reintentos):
        try:
            with DDGS() as ddgs:
                resp = ddgs.text(consulta, region="wt-wt", max_results=4, backend="auto")
                if resp:
                    resultados = list(resp)
                    partes = []
                    for i, res in enumerate(resultados, 1):
                        titulo = res.get("title", "").strip()
                        cuerpo = res.get("body", "").strip()
                        if titulo or cuerpo:
                            partes.append(f"[{i}] {titulo}\n{cuerpo}")
                    if partes:
                        return "\n\n".join(partes)
        except Exception as e:
            print(f"⚠️ Error en búsqueda web (intento {intento + 1}/{max_reintentos}): {e}")
            if intento < max_reintentos - 1:
                time.sleep(2 ** intento)
    return ""


async def buscar_en_web(consulta: str) -> str:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _ejecutar_busqueda_ddg, consulta)
    except Exception:
        return ""


def fragmentar_texto_inteligente(texto: str) -> List[str]:
    if len(texto) <= LIMITE_CARACTERES_RESPUESTA:
        return [texto]

    texto = texto[:LIMITE_CARACTERES_RESPUESTA]

    corte = texto.rfind("\n\n", 0, LIMITE_CARACTERES_PARTE)
    if corte == -1:
        corte = texto.rfind("\n", 0, LIMITE_CARACTERES_PARTE)
    if corte == -1:
        corte = texto.rfind(". ", 0, LIMITE_CARACTERES_PARTE)
        if corte != -1:
            corte += 1
    if corte == -1:
        corte = texto.rfind(" ", 0, LIMITE_CARACTERES_PARTE)
    if corte == -1:
        corte = LIMITE_CARACTERES_PARTE

    parte1 = texto[:corte].strip()
    parte2 = texto[corte:].strip()

    if len(parte2) < 50:
        return [parte1 + " " + parte2]

    return [parte1, parte2]


async def enviar_respuesta_larga(interaction: discord.Interaction, texto: str, prefijo: str = ""):
    contenido = f"{prefijo}{texto}" if prefijo else texto
    partes = fragmentar_texto_inteligente(contenido)
    await interaction.followup.send(partes[0])
    for parte in partes[1:]:
        if parte.strip():
            await interaction.followup.send(parte)


class IA(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ultimos_errores = {}
        self.pausa_hasta = {}

        groq_key = leer_key("GROQ_API_KEY", "GROQ_KEY")
        openrouter_key = leer_key("OPENROUTER_API_KEY", "HF_TOKEN")

        print(f"🔑 Groq: {'✅' if groq_key else '❌'} | Qwen/OpenRouter: {'✅' if openrouter_key else '❌'}")

        self.groq_client = AsyncGroq(api_key=groq_key, timeout=30.0) if groq_key else None
        self.hf_client = openai.AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_key,
            timeout=30.0,
        ) if openrouter_key else None
        self.mistral_client = None

    def _system_prompt(self, info_web: str = "") -> str:
        owner_id = getattr(self.bot, "owner_id_custom", 1481047586457518141)
        prompt = SYSTEM_PROMPT_BASE.format(owner_id=owner_id)
        if info_web:
            prompt += (
                "\n\n## Contexto web reciente\n"
                "Usa esta información como fuente prioritaria si responde a la pregunta del usuario. "
                "No la menciones si no es relevante.\n\n"
                f"{info_web}"
            )
        return prompt

    async def _consultar_groq(self, messages: list, modelo: str) -> Optional[str]:
        if not self.groq_client:
            return None
        try:
            resp = await self.groq_client.chat.completions.create(
                model=modelo,
                messages=normalizar_mensajes(messages),
                temperature=0.6,
                max_tokens=2500,
            )
            return resp.choices[0].message.content
        except Exception as e:
            self.ultimos_errores["groq"] = describir_error(e)
            print(f"⚠️ Groq ({modelo}) falló: {self.ultimos_errores['groq']}")
            return None

    async def _consultar_qwen(self, messages: list) -> Optional[str]:
        if not self.hf_client:
            return None
        try:
            resp = await self.hf_client.chat.completions.create(
                model=MODELO_QWEN,
                messages=normalizar_mensajes(messages),
                temperature=0.6,
                max_tokens=2000,
            )
            return resp.choices[0].message.content
        except Exception as e:
            self.ultimos_errores["qwen"] = describir_error(e)
            print(f"⚠️ Qwen falló: {self.ultimos_errores['qwen']}")
            return None

    async def _cadena_respaldo(self, messages: list) -> str:
        ahora = asyncio.get_running_loop().time()
        intentos = []
        if self.groq_client:
            intentos.append(("groq", MODELO_GROQ, self._consultar_groq))
            intentos.append(("groq", MODELO_GROQ_RESPALDO, self._consultar_groq))
        if self.hf_client:
            intentos.append(("qwen", MODELO_QWEN, self._consultar_qwen))

        for nombre, modelo, fn in intentos:
            clave = f"{nombre}:{modelo}"
            if self.pausa_hasta.get(clave, 0) > ahora:
                continue
            try:
                if nombre == "groq":
                    texto = await fn(messages, modelo)
                else:
                    texto = await fn(messages)
                if texto and texto.strip():
                    return texto
            except Exception as e:
                if getattr(e, "status_code", None) == 429:
                    self.pausa_hasta[clave] = ahora + COOLDOWN_429_SEG

        return "❌ No pude contactar con ningún servicio de IA. Inténtalo de nuevo en un momento."

    async def _ensamble(self, messages: list) -> str:
        resultados = await asyncio.gather(
            self._consultar_groq(messages, MODELO_GROQ),
            self._consultar_qwen(messages),
            return_exceptions=True,
        )
        texto_groq = resultados[0] if isinstance(resultados[0], str) else None
        texto_qwen = resultados[1] if isinstance(resultados[1], str) else None

        if not texto_groq and not texto_qwen:
            return await self._cadena_respaldo(messages)
        if texto_groq and not texto_qwen:
            return texto_groq
        if texto_qwen and not texto_groq:
            return texto_qwen

        if not self.groq_client:
            return texto_groq or texto_qwen

        prompt_juez = [
            {"role": "system", "content": (
                "Eres un juez experto. Recibirás dos respuestas (A y B) a la misma pregunta. "
                "Genera la respuesta final óptima combinando lo mejor de ambas: "
                "la precisión y datos de una, la claridad y fluidez de la otra. "
                "No menciones que hubo dos opciones. Responde directamente como Meowly, "
                "en Markdown, con tono amigable y conciso."
            )},
            {"role": "user", "content": (
                f"Pregunta original:\n{messages[-1]['content']}\n\n"
                f"Opción A (Groq):\n{texto_groq}\n\n"
                f"Opción B (Qwen):\n{texto_qwen}\n\n"
                "Respuesta final óptima:"
            )},
        ]
        try:
            resp = await self.groq_client.chat.completions.create(
                model=MODELO_GROQ,
                messages=prompt_juez,
                temperature=0.5,
                max_tokens=2500,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"⚠️ Juez Groq falló: {describir_error(e)}")
            return texto_groq or texto_qwen

    async def consultar(self, historial: list, info_web: str = "") -> str:
        system = self._system_prompt(info_web)
        mensajes = [{"role": "system", "content": system}] + truncar_historial(historial)

        if USAR_ENSAMBLE:
            return await self._ensamble(mensajes)
        return await self._cadena_respaldo(mensajes)

    @app_commands.command(name="ia", description="Habla con Meowly (Groq → Qwen con respaldo)")
    @app_commands.describe(mensaje="Tu pregunta o consulta")
    async def ia(self, interaction: discord.Interaction, mensaje: str):
        await interaction.response.defer()

        info_web = ""
        if necesita_busqueda(mensaje):
            info_web = await buscar_en_web(mensaje)

        historial = await obtener_historial_usuario(interaction.user.id)
        await historial.agregar("user", mensaje)
        contexto = await historial.actualizar_y_obtener()

        respuesta = await self.consultar(contexto, info_web=info_web)

        if not respuesta.startswith("❌"):
            await historial.agregar("assistant", respuesta)

        await enviar_respuesta_larga(interaction, respuesta, prefijo="🐱 ")


async def setup(bot):
    await bot.add_cog(IA(bot))
