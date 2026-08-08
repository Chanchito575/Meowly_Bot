import os
import discord
from discord.ext import commands
from collections import deque
import google.generativeai as genai

# Configurar la API Key de Gemini
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Configuración del modelo (Gemini 1.5 Flash funciona gratis y sin problemas en Bolivia)
model = genai.GenerativeModel('gemini-1.5-flash')

# Configuración de Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix='.', intents=intents, help_command=None)

LIMITE_MENSAJES = 20
historiales_usuarios = {}

@bot.event
async def on_ready():
    print(f'✅ Carek está conectado y listo como: {bot.user}')
    await bot.change_presence(activity=discord.Game(name="Usa .help para mis comandos"))

# ==========================================
# COMANDO .help
# ==========================================
@bot.command(name="help", aliases=["ayuda"])
async def mostrar_ayuda(ctx):
    embed = discord.Embed(
        title="🤖 ¡Hola! Soy Carek",
        description="Tu asistente y compañero en el servidor, creado por **Chanchito575**.\nPuedo charlar contigo usando IA, responder tus dudas y ayudarte a organizar el servidor creando **canales y categorías**.",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🧠 Inteligencia Artificial",
        value=(
            "` .ia <pregunta> ` — Chatea conmigo (recuerdo tus últimos 10 mensajes).\n"
            "` .limpiar ` — Reinicia nuestro historial para empezar una charla desde cero."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Organización del Servidor",
        value=(
            "` .canales <Nombre1, Nombre2, ...> ` — Crea uno o varios canales de texto (separados por comas).\n"
            "` .categorias <Nombre1, Nombre2, ...> ` — Crea una o varias categorías para ordenar los canales."
        ),
        inline=False
    )
    
    embed.set_footer(text="Carek • Creado por Chanchito575")
    await ctx.send(embed=embed)

# ==========================================
# COMANDO .ia
# ==========================================
@bot.command(name="IA", aliases=["ia"])
async def inteligencia_artificial(ctx, *, pregunta: str = None):
    if pregunta is None:
        await ctx.send("¡Hola! Escribe tu mensaje después de `.ia`. Ejemplo: `.ia ¿Qué es la fotosíntesis?`")
        return

    async with ctx.typing():
        try:
            user_id = ctx.author.id

            if user_id not in historiales_usuarios:
                historiales_usuarios[user_id] = deque(maxlen=LIMITE_MENSAJES)

            historial = historiales_usuarios[user_id]

            # Formato de historial compatible con google-generativeai
            historial.append({"role": "user", "parts": [pregunta]})

            response = model.generate_content(list(historial))
            respuesta_texto = response.text

            historial.append({"role": "model", "parts": [respuesta_texto]})

            if len(respuesta_texto) > 2000:
                respuesta_texto = respuesta_texto[:1995] + "..."

            await ctx.send(respuesta_texto)

        except Exception as e:
            await ctx.send(f"⚠️ Ocurrió un error con la IA: {e}")

# ==========================================
# COMANDO .limpiar
# ==========================================
@bot.command(name="limpiar", aliases=["reset", "forget"])
async def borrar_historial(ctx):
    user_id = ctx.author.id
    if user_id in historiales_usuarios:
        del historiales_usuarios[user_id]
        await ctx.send(f"🧹 {ctx.author.mention}, he olvidado nuestra conversación anterior.")
    else:
        await ctx.send(f"🤖 {ctx.author.mention}, no teníamos ningún historial guardado.")

# ==========================================
# COMANDOS DE CANALES Y CATEGORÍAS
# ==========================================
@bot.command(name="canales")
@commands.has_permissions(manage_channels=True)
async def crear_canales(ctx, *, nombres: str = None):
    if nombres is None:
        await ctx.send("Especifica los nombres separados por comas. Ejemplo: `.canales general, fotos, comandos`")
        return

    lista_nombres = [n.strip() for n in nombres.split(",") if n.strip()]
    creados = []
    
    for nombre in lista_nombres:
        nuevo_canal = await ctx.guild.create_text_channel(name=nombre)
        creados.append(nuevo_canal.mention)

    await ctx.send(f"✅ ¡Canales creados con éxito: {', '.join(creados)}!")

@bot.command(name="categorias")
@commands.has_permissions(manage_channels=True)
async def crear_categorias(ctx, *, nombres: str = None):
    if nombres is None:
        await ctx.send("Especifica los nombres separados por comas. Ejemplo: `.categorias INFORMACIÓN, COMUNIDAD`")
        return

    lista_nombres = [n.strip() for n in nombres.split(",") if n.strip()]
    creados = []
    
    for nombre in lista_nombres:
        nueva_cat = await ctx.guild.create_category(name=nombre)
        creados.append(f"**{nueva_cat.name}**")

    await ctx.send(f"✅ ¡Categorías creadas con éxito: {', '.join(creados)}!")

@crear_canales.error
@crear_categorias.error
async def manejar_errores_permisos(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ No tienes permisos de `Gestionar Canales` para usar este comando.")

bot.run(os.environ.get("DISCORD_TOKEN"))
