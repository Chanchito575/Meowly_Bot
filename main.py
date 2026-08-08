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
    print(f"✅ Carek está conectado y listo como: {bot.user}")
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
            await ctx.send(f"⚠️ Ocurrió un error con Groq:\n```text\n{e}\n```")

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

# ==========================================
# CLASE Y COMANDO: .eliminar (Con Botones)
# ==========================================
class ConfirmarEliminar(discord.ui.View):
    def __init__(self, autor_id):
        super().__init__(timeout=30)
        self.autor_id = autor_id
        self.valor = None

    @discord.ui.button(label="Sí, borrar", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("No puedes usar este botón.", ephemeral=True)
            return
        
        self.valor = True
        self.stop()
        await interaction.response.edit_message(content="🗑️ Eliminando canal...", view=None)
        await interaction.channel.delete(reason=f"Eliminado por {interaction.user}")

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("No puedes usar este botón.", ephemeral=True)
            return
        
        self.valor = False
        self.stop()
        await interaction.response.edit_message(content="❌ Acción cancelada.", view=None)

@bot.command(name="eliminar")
@commands.has_permissions(manage_channels=True)
async def eliminar_canal(ctx):
    view = ConfirmarEliminar(ctx.author.id)
    mensaje = await ctx.send(f"⚠️ {ctx.author.mention}, ¿seguro que quieres borrar este canal?", view=view)
    
    await view.wait()
    
    if view.valor is None:
        try:
            await mensaje.edit(content="⏱️ Tiempo agotado. El canal no fue eliminado.", view=None)
        except:
            pass

# ==========================================
# MANEJO DE ERRORES DE PERMISOS
# ==========================================
@crear_canales.error
@crear_categorias.error
@eliminar_canal.error
async def manejar_errores_permisos(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ No tienes permisos para gestionar canales.")

# ==========================================
# INICIO DEL BOT
# ==========================================
bot.run(os.environ.get("DISCORD_TOKEN"))
