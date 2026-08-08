import os
import discord
from discord.ext import commands
from collections import deque
from google import genai

# Inicializamos el cliente de Gemini usando la variable de entorno
ai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Configuración de Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# Desactivamos el help por defecto de discord para crear nuestro propio .help amigable
bot = commands.Bot(command_prefix='.', intents=intents, help_command=None)

# Límite de memoria: 20 mensajes en total (10 del usuario y 10 de la IA)
LIMITE_MENSAJES = 20
historiales_usuarios = {}

@bot.event
async def on_ready():
    print(f'✅ Carek está conectado y listo como: {bot.user}')
    # Establece la actividad/estado de Carek en Discord
    await bot.change_presence(activity=discord.Game(name="Usa .help para mis comandos"))

# ==========================================
# COMANDO .help (Personalizado y amigable)
# ==========================================
@bot.command(name="help", aliases=["ayuda"])
async def mostrar_ayuda(ctx):
    embed = discord.Embed(
        title="🤖 ¡Hola! Soy Carek",
        description="Tu asistente y compañero en el servidor, creado por **Chanchito575**.\nPuedo charlar contigo usando IA, responder tus dudas y ayudarte a organizar la casa creando **canales y categorías**.",
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
# COMANDO DE IA (Carek con 20 de memoria)
# ==========================================
@bot.command(name="IA", aliases=["ia"])
async def inteligencia_artificial(ctx, *, pregunta: str = None):
    if pregunta is None:
        await ctx.send("¡Hola! Escribe tu mensaje después de `.ia`. Ejemplo: `.ia ¿Qué es la fotosíntesis?`")
        return

    async with ctx.typing():
        try:
            user_id = ctx.author.id

            # Si el usuario no tiene historial, le creamos una cola con límite de 20 mensajes
            if user_id not in historiales_usuarios:
                historiales_usuarios[user_id] = deque(maxlen=LIMITE_MENSAJES)

            historial = historiales_usuarios[user_id]

            # Agregamos la pregunta del usuario
            historial.append({"role": "user", "parts": [{"text": pregunta}]})

            # Enviamos el historial a Gemini 2.0 Flash
            response = ai_client.models.generate_content(
                model='gemini-1.5-flash',
                contents=list(historial)
            )

            respuesta_texto = response.text

            # Guardamos la respuesta del bot en el historial
            historial.append({"role": "model", "parts": [{"text": respuesta_texto}]})

            # Control de límite de 2000 caracteres de Discord
            if len(respuesta_texto) > 2000:
                respuesta_texto = respuesta_texto[:1995] + "..."

            await ctx.send(respuesta_texto)

        except Exception as e:
            await ctx.send(f"⚠️ Ocurrió un error con la IA: {e}")

# ==========================================
# COMANDO .limpiar (Borra la memoria del usuario)
# ==========================================
@bot.command(name="limpiar", aliases=["reset", "forget"])
async def borrar_historial(ctx):
    user_id = ctx.author.id
    if user_id in historiales_usuarios:
        del historiales_usuarios[user_id]
        await ctx.send(f"🧹 {ctx.author.mention}, he olvidado nuestra conversación anterior. ¡Empezamos de cero!")
    else:
        await ctx.send(f"🤖 {ctx.author.mention}, no teníamos ningún historial guardado.")

# ==========================================
# COMANDOS DE CANALES Y CATEGORÍAS MÚLTIPLES
# ==========================================
@bot.command(name="canales")
@commands.has_permissions(manage_channels=True)
async def crear_canales(ctx, *, nombres: str = None):
    if nombres is None:
        await ctx.send("Por favor, especifica los nombres separados por comas. Ejemplo: `.canales general, fotos, comandos`")
        return

    lista_nombres = [n.strip() for n in nombres.split(",") if n.strip()]
    creados = []
    
    guild = ctx.guild
    for nombre in lista_nombres:
        nuevo_canal = await guild.create_text_channel(name=nombre)
        creados.append(nuevo_canal.mention)

    await ctx.send(f"✅ ¡Canales creados con éxito: {', '.join(creados)}!")

@bot.command(name="categorias")
@commands.has_permissions(manage_channels=True)
async def crear_categorias(ctx, *, nombres: str = None):
    if nombres is None:
        await ctx.send("Por favor, especifica los nombres separados por comas. Ejemplo: `.categorias INFORMACIÓN, COMUNIDAD`")
        return

    lista_nombres = [n.strip() for n in nombres.split(",") if n.strip()]
    creados = []
    
    guild = ctx.guild
    for nombre in lista_nombres:
        nueva_cat = await guild.create_category(name=nombre)
        creados.append(f"**{nueva_cat.name}**")

    await ctx.send(f"✅ ¡Categorías creadas con éxito: {', '.join(creados)}!")

# Manejo de errores para cuando un usuario no tiene permisos de crear canales
@crear_canales.error
@crear_categorias.error
async def manejar_errores_permisos(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ No tienes permisos de `Gestionar Canales` para usar este comando.")

# Iniciar el bot con la variable de entorno
bot.run(os.environ.get("DISCORD_TOKEN"))
