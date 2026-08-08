import os
import discord
import datetime
from keep_alive import keep_alive
from discord.ext import commands
from collections import deque
from openai import OpenAI

# ==========================================
# CONFIGURACIÓN
# ==========================================
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)
MODELO_GROQ = "llama-3.3-70b-versatile"

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix='.', intents=intents, help_command=None)

LIMITE_MENSAJES = 30
historiales_usuarios = {}

@bot.event
async def on_ready():
    print(f"✅ Carek está conectado como: {bot.user}")
    await bot.change_presence(activity=discord.Game(name="Usa .help para mis comandos"))

# ==========================================
# COMANDO: .help
# ==========================================
@bot.command(name="help", aliases=["ayuda"])
async def mostrar_ayuda(ctx):
    embed = discord.Embed(title="🤖 ¡Hola! Soy Carek", color=discord.Color.blue())
    
    embed.add_field(
        name="🧠 Inteligencia Artificial",
        value=(
            "` .ia <pregunta> ` — Chatea con contexto.\n"
            "` .resumen [filtro] ` — Resume el canal (ej: `.resumen 50mss`, `.resumen 2d`, `.resumen 30m`).\n"
            "` .limpiar ` — Reinicia tu historial personal.\n"
            "` .limpiar all ` — Borra toda la memoria global (Solo Admins)."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Organización y Moderación",
        value=(
            "` .canales <N1, N2> ` — Crea canales.\n"
            "` .categorias <N1, N2> ` — Crea categorías.\n"
            "` .eliminar ` — Borra el canal actual (requiere gestión)."
        ),
        inline=False
    )
    await ctx.send(embed=embed)

# ==========================================
# COMANDO: .ia
# ==========================================
@bot.command(name="IA", aliases=["ia"])
async def inteligencia_artificial(ctx, *, pregunta: str = None):
    if pregunta is None: return await ctx.send("¡Hola! Escribe tu mensaje después de `.ia`.")
    async with ctx.typing():
        try:
            user_id = ctx.author.id
            if user_id not in historiales_usuarios: historiales_usuarios[user_id] = deque(maxlen=LIMITE_MENSAJES)
            historial = historiales_usuarios[user_id]
            mensajes_formato = [{"role": "system", "content": "Eres Carek, un asistente amigable."}]
            for msg in historial:
                rol = "user" if msg["role"] == "user" else "assistant"
                mensajes_formato.append({"role": rol, "content": msg["parts"][0]})
            mensajes_formato.append({"role": "user", "content": pregunta})
            
            response = client.chat.completions.create(model=MODELO_GROQ, messages=mensajes_formato)
            resp = response.choices[0].message.content
            historial.append({"role": "user", "parts": [pregunta]})
            historial.append({"role": "model", "parts": [resp]})
            await ctx.send(resp[:2000])
        except Exception as e: await ctx.send(f"⚠️ Error: {e}")

# ==========================================
# COMANDO: .resumen (Canal actual)
# ==========================================
@bot.command(name="resumen")
async def resumir_chat(ctx, *, argumento: str = "50"):
    canal = ctx.channel
    async with ctx.typing():
        try:
            mensajes_texto = []
            arg_limpio = argumento.strip().lower()
            if arg_limpio.endswith("d") or arg_limpio.endswith("m") or arg_limpio == "hoy":
                if arg_limpio.endswith("d"):
                    dias = int(arg_limpio[:-1])
                    if dias > 15: return await ctx.send("⚠️ Máximo 15d.")
                    tiempo = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=dias)
                elif arg_limpio.endswith("m"):
                    minutos = int(arg_limpio[:-1])
                    tiempo = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutos)
                else:
                    tiempo = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0)
                
                async for m in canal.history(limit=None, after=tiempo):
                    if not m.author.bot and m.content: mensajes_texto.append(f"{m.author.name}: {m.content}")
            else:
                limpio_num = "".join([c for c in arg_limpio if c.isdigit()])
                cantidad = int(limpio_num) if limpio_num else 50
                if cantidad > 500: return await ctx.send("⚠️ Máximo 500 mensajes.")
                async for m in canal.history(limit=cantidad + 1):
                    if m.id != ctx.message.id and not m.author.bot and m.content: mensajes_texto.append(f"{m.author.name}: {m.content}")
                mensajes_texto.reverse()

            if not mensajes_texto: return await ctx.send("⚠️ No hay mensajes.")
            
            resp = client.chat.completions.create(model=MODELO_GROQ, messages=[{"role": "user", "content": f"Resume estos mensajes de #{canal.name}:\n" + "\n".join(mensajes_texto)}])
            await ctx.send(embed=discord.Embed(title=f"📜 Resumen de #{canal.name}", description=resp.choices[0].message.content, color=discord.Color.purple()))
        except: await ctx.send("⚠️ Formato incorrecto. Ej: `.resumen 50mss`, `.resumen 2d`, `.resumen 30m`")

# ==========================================
# COMANDO: .limpiar
# ==========================================
@bot.command(name="limpiar")
async def borrar_historial(ctx, opcion: str = None):
    if opcion == "all":
        if not ctx.author.guild_permissions.administrator: return await ctx.send("⚠️ Solo administradores.")
        historiales_usuarios.clear()
        await ctx.send("🧹 Memoria global borrada.")
    else:
        if ctx.author.id in historiales_usuarios:
            del historiales_usuarios[ctx.author.id]
            await ctx.send("🧹 Historial olvidado.")

# ==========================================
# MODERACIÓN Y BOTONES
# ==========================================
@bot.command(name="canales")
@commands.has_permissions(manage_channels=True)
async def crear_canales(ctx, *, nombres: str):
    for n in nombres.split(","): await ctx.guild.create_text_channel(name=n.strip())
    await ctx.send("✅ Canales creados.")

class ConfirmarEliminar(discord.ui.View):
    def __init__(self, autor_id):
        super().__init__(timeout=30)
        self.autor_id = autor_id
        self.valor = None
    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.autor_id: return
        await interaction.channel.delete()

@bot.command(name="eliminar")
@commands.has_permissions(manage_channels=True)
async def eliminar_canal(ctx):
    await ctx.send("⚠️ ¿Borrar este canal?", view=ConfirmarEliminar(ctx.author.id))

keep_alive()
bot.run(os.environ.get("DISCORD_TOKEN"))
