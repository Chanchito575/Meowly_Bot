import os
import discord
from discord.ext import commands
from collections import deque
import google.generativeai as genai

# ==========================================
# CONFIGURACIÓN DE GEMINI
# ==========================================
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Definimos el modelo por defecto. Si esto falla, usaremos el comando .modelos 
# para ver cuál debemos poner aquí realmente.
model = genai.GenerativeModel('models/gemini-3.5-flash')

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
            "` .limpiar ` — Reinicia nuestro historial.\n"
            "` .modelos ` — Muestra qué versiones de IA admite tu API Key."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Organización",
        value=(
            "` .canales <N1, N2> ` — Crea canales de texto.\n"
            "` .categorias <N1, N2> ` — Crea categorías."
        ),
        inline=False
    )
    
    await ctx.send(embed=embed)

# ==========================================
# COMANDO: .modelos (Para diagnosticar tu API KEY)
# ==========================================
@bot.command(name="modelos")
async def ver_modelos(ctx):
    await ctx.send("🔍 Consultando con Google los modelos habilitados para tu API Key, un momento...")
    try:
        modelos_disponibles = []
        for m in genai.list_models():
            # Filtramos solo los modelos que sirven para generar texto
            if 'generateContent' in m.supported_generation_methods:
                modelos_disponibles.append(m.name)
        
        if modelos_disponibles:
            texto = "\n".join(modelos_disponibles)
            await ctx.send(f"✅ **Estos son los nombres EXACTOS que tu API Key tiene permitidos:**\n```text\n{texto}\n```")
        else:
            await ctx.send("⚠️ Tu API Key es válida, pero Google no le ha habilitado ningún modelo de texto (podría ser un bloqueo regional o de cuenta nueva).")
            
    except Exception as e:
        await ctx.send(f"⚠️ Error crítico al consultar Google: {e}")

# ==========================================
# COMANDO: .ia
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
            historial.append({"role": "user", "parts": [pregunta]})

            response = model.generate_content(list(historial))
            respuesta_texto = response.text

            historial.append({"role": "model", "parts": [respuesta_texto]})

            if len(respuesta_texto) > 2000:
                respuesta_texto = respuesta_texto[:1995] + "..."

            await ctx.send(respuesta_texto)

        except Exception as e:
            await ctx.send(f"⚠️ Ocurrió un error con la IA:\n```text\n{e}\n```\n👉 **Intenta usar `.modelos` para ver si el modelo 'gemini-1.5-flash' está disponible para ti.**")

# ==========================================
# COMANDO: .limpiar
# ==========================================
@bot.command(name="limpiar")
async def borrar_historial(ctx):
    user_id = ctx.author.id
    if user_id in historiales_usuarios:
        del historiales_usuarios[user_id]
        await ctx.send(f"🧹 {ctx.author.mention}, he olvidado nuestra conversación anterior.")
    else:
        await ctx.send(f"🤖 {ctx.author.mention}, no teníamos ningún historial.")

# ==========================================
# COMANDOS: Canales y Categorías
# ==========================================
@bot.command(name="canales")
@commands.has_permissions(manage_channels=True)
async def crear_canales(ctx, *, nombres: str = None):
    if nombres is None:
        await ctx.send("Especifica los nombres separados por comas.")
        return

    lista_nombres = [n.strip() for n in nombres.split(",") if n.strip()]
    creados = []
    
    for nombre in lista_nombres:
        nuevo_canal = await ctx.guild.create_text_channel(name=nombre)
        creados.append(nuevo_canal.mention)

    await ctx.send(f"✅ Canales creados: {', '.join(creados)}")

@bot.command(name="categorias")
@commands.has_permissions(manage_channels=True)
async def crear_categorias(ctx, *, nombres: str = None):
    if nombres is None:
        await ctx.send("Especifica los nombres separados por comas.")
        return

    lista_nombres = [n.strip() for n in nombres.split(",") if n.strip()]
    creados = []
    
    for nombre in lista_nombres:
        nueva_cat = await ctx.guild.create_category(name=nombre)
        creados.append(f"**{nueva_cat.name}**")

    await ctx.send(f"✅ Categorías creadas: {', '.join(creados)}")

@crear_canales.error
@crear_categorias.error
async def manejar_errores_permisos(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ No tienes permisos para gestionar canales.")

# ==========================================
# INICIO DEL BOT
# ==========================================
bot.run(os.environ.get("DISCORD_TOKEN"))
