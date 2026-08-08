import os
import discord
from discord.ext import commands
from collections import deque
from openai import OpenAI

# ==========================================
# CONFIGURACIÓN DE GROQ
# ==========================================
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)
MODELO_GROQ = "llama-3.3-70b-versatile"

# ==========================================
# CONFIGURACIÓN DE DISCORD
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix='.', intents=intents, help_command=None)

# Memoria de la IA
LIMITE_MENSAJES = 20
historiales_usuarios = {}

@bot.event
async def on_ready():
    print(f'✅ Carek está conectado y listo como: {bot.user}')
    await bot.change_presence(activity=discord.Game(name="Usa .help para mis comandos"))

# ==========================================
# COMANDO: .help
# ==========================================
@bot.command(name="help", aliases=["ayuda"])
async def mostrar_ayuda(ctx):
    embed = discord.Embed(
        title="🤖 ¡Hola! Soy Carek",
        description="Tu asistente y compañero en el servidor.\nPuedo charlar contigo usando IA y ayudarte a organizar el servidor.",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🧠 Inteligencia Artificial",
        value=(
            "` .ia <pregunta> ` — Chatea conmigo (recuerdo el contexto).\n"
            "` .limpiar ` — Reinicia nuestro historial."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Organización y Moderación",
        value=(
            "` .canales <N1, N2> ` — Crea canales de texto.\n"
            "` .categorias <N1, N2> ` — Crea categorías.\n"
            "` .eliminar ` — Borra el canal actual con botones."
        ),
        inline=False
    )
    
    await ctx.send(embed=embed)

# ==========================================
# COMANDO: .ia (Usando Groq)
# ==========================================
@bot.command(name="IA", aliases=["ia"])
async def inteligencia_artificial(ctx, *, pregunta: str = None):
    if pregunta is None:
        await ctx.send("¡Hola! Escribe tu mensaje después de `.ia`. Ejemplo: `.ia Hola`")
        return

    async with ctx.typing():
        try:
            user_id = ctx.author.id

            if user_id not in historiales_usuarios:
                historiales_usuarios[user_id] = deque(maxlen=LIMITE_MENSAJES)

            historial = historiales_usuarios[user_id]
            
            mensajes_formato = [{"role": "system", "content": "Eres Carek, un asistente útil, amigable y divertido en Discord."}]
            
            for msg in historial:
                rol = "user" if msg["role"] == "user" else "assistant"
                texto_parte = msg["parts"][0] if isinstance(msg["parts"], list) else msg["parts"]
                mensajes_formato.append({"role": rol, "content": texto_parte})

            mensajes_formato.append({"role": "user", "content": pregunta})
            historial.append({"role": "user", "parts": [pregunta]})

            response = client.chat.completions.create(
                model=MODELO_GROQ,
                messages=mensajes_formato
            )
            
            respuesta_texto = response.choices[0].message.content
            historial.append({"role": "model", "parts": [respuesta_texto]})

            if len(respuesta_texto) > 2000:
                respuesta_texto = respuesta_texto[:1995] + "..."

            await ctx.send(respuesta_texto)

        except Exception as e:
            await ctx.send(f"⚠️ Ocurrió un error con Groq:\n```text\n{e}\n
