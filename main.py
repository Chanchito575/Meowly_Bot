import os
import re
import discord
import datetime
from keep_alive import keep_alive
from discord.ext import commands
from discord import app_commands
from collections import deque
from openai import OpenAI

# ==========================================
# CONFIGURACIÓN DE IA Y DISCORD
# ==========================================
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)
MODELO_GROQ = "llama-3.3-70b-versatile"

PROMPT_SISTEMA_CAREK = (
    "Eres Carek, un asistente para un servidor de Discord. Tu tono es natural, relajado, fresco y auténtico. "
    "Habla como un compañero más del grupo, directo al grano y con un toque ligero de ingenio cuando encaje. "
    "Evita sonar como un libro de texto, un robot rígido o un ejecutivo formal. "
    "REGLA DE IDENTIDAD Y CREADOR: Si te preguntan quién te creó, quién te hizo o de dónde saliste, "
    "aclara siempre de forma natural que eres un asistente de IA impulsado por la tecnología de tu empresa base, "
    "pero que el bot de Discord (el script, la integración y quien te dio vida en este servidor) fue creado por <@1122162289206902845>."
)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

class MiBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='.', intents=intents, help_command=None)

    async def setup_hook(self):
        await self.tree.sync()
        print("⚡ Comandos / (Slash) sincronizados con Discord.")

bot = MiBot()

LIMITE_MENSAJES = 30
historiales_usuarios = {}

@bot.event
async def on_ready():
    print(f"✅ Carek está conectado como: {bot.user}")
    await bot.change_presence(activity=discord.Game(name="Escribe / para ver mis comandos"))

# ==========================================
# FUNCIÓN AUXILIAR PARA PARSEAR FECHAS
# ==========================================
def parsear_fecha(texto_fecha: str) -> datetime.datetime:
    partes = [p.strip() for p in texto_fecha.split('/') if p.strip()]
    anio_actual = datetime.datetime.now().year
    
    if len(partes) == 2:
        dia, mes = int(partes[0]), int(partes[1])
        anio = anio_actual
    elif len(partes) == 3:
        dia, mes, anio = int(partes[0]), int(partes[1]), int(partes[2])
    else:
        raise ValueError("Formato de fecha inválido")

    return datetime.datetime(anio, mes, dia, tzinfo=datetime.timezone.utc)

# ==========================================
# COMANDO: /help
# ==========================================
@bot.tree.command(name="help", description="Muestra la lista de comandos disponibles de Carek")
async def mostrar_ayuda(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 ¡Hola! Soy Carek", color=discord.Color.blue())
    
    embed.add_field(
        name="🧠 Inteligencia Artificial",
        value=(
            "` /ia ` — Chatea con contexto.\n"
            "` /resumen ` — Resume los mensajes (Ej: `50mss`, `2d`, `08/09`, `01/07 - 05/07`).\n"
            "` /limpiar ` — Reinicia tu historial personal o la memoria global."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Organización y Moderación",
        value=(
            "` /canales ` — Crea nuevos canales de texto.\n"
            "` /categorias ` — Crea nuevas categorías.\n"
            "` /eliminar ` — Borra un canal específico o el canal actual."
        ),
        inline=False
    )
    await interaction.response.send_message(embed=embed)

# ==========================================
# COMANDO: /ia
# ==========================================
@bot.tree.command(name="ia", description="Hazle una pregunta a la Inteligencia Artificial")
@app_commands.describe(pregunta="Escribe lo que quieres preguntarle a Carek")
async def inteligencia_artificial(interaction: discord.Interaction, pregunta: str):
    await interaction.response.defer()
    try:
        user_id = interaction.user.id
        if user_id not in historiales_usuarios:
            historiales_usuarios[user_id] = deque(maxlen=LIMITE_MENSAJES)
        
        historial = historiales_usuarios[user_id]
        
        mensajes_formato = [{"role": "system", "content": PROMPT_SISTEMA_CAREK}]
        
        for msg in historial:
            rol = "user" if msg["role"] == "user" else "assistant"
            mensajes_formato.append({"role": rol, "content": msg["parts"][0]})
            
        mensajes_formato.append({"role": "user", "content": pregunta})
        
        response = client.chat.completions.create(model=MODELO_GROQ, messages=mensajes_formato)
        resp = response.choices[0].message.content
        
        historial.append({"role": "user", "parts": [pregunta]})
        historial.append({"role": "model", "parts": [resp]})
        
        await interaction.followup.send(resp[:2000])
    except Exception as e:
        await interaction.followup.send(f"⚠️ Error: {e}")

# ==========================================
# COMANDO: /resumen
# ==========================================
@bot.tree.command(name="resumen", description="Resume la actividad reciente de este canal")
@app_commands.describe(filtro="Ej: 50mss, 2d, 30m, 08/09/2026 o rango 01/07 - 05/07 (Máx. 10 días)")
async def resumir_chat(interaction: discord.Interaction, filtro: str = "50mss"):
    await interaction.response.defer()
    canal = interaction.channel
    try:
        mensajes_texto = []
        arg_limpio = filtro.strip().lower()
        
        tiempo_inicio = None
        tiempo_fin = None

        if "-" in arg_limpio and not arg_limpio.startswith("-"):
            partes = arg_limpio.split("-")
            tiempo_inicio = parsear_fecha(partes[0])
            tiempo_fin = parsear_fecha(partes[1]) + datetime.timedelta(days=1) - datetime.timedelta(seconds=1)

            if tiempo_fin < tiempo_inicio:
                return await interaction.followup.send("⚠️ La fecha final no puede ser anterior a la fecha inicial.")

            dias_diferencia = (tiempo_fin - tiempo_inicio).days
            if dias_diferencia > 10:
                return await interaction.followup.send("⚠️ El rango máximo de fechas permitido es de **10 días**.")

        elif "/" in arg_limpio:
            tiempo_inicio = parsear_fecha(arg_limpio)
            tiempo_fin = tiempo_inicio + datetime.timedelta(days=1) - datetime.timedelta(seconds=1)

        elif arg_limpio.endswith("d") or arg_limpio.endswith("m") or arg_limpio == "hoy":
            if arg_limpio.endswith("d"):
                dias = int(arg_limpio[:-1])
                if dias > 10:
                    return await interaction.followup.send("⚠️ El máximo permitido son **10 días**.")
                tiempo_inicio = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=dias)
            elif arg_limpio.endswith("m"):
                minutos = int(arg_limpio[:-1])
                tiempo_inicio = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutos)
            else:
                tiempo_inicio = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        if tiempo_inicio:
            async for m in canal.history(limit=None, after=tiempo_inicio, before=tiempo_fin):
                if not m.author.bot and m.content:
                    mensajes_texto.append(f"{m.author.name}: {m.content}")

        else:
            limpio_num = "".join([c for c in arg_limpio if c.isdigit()])
            cantidad = int(limpio_num) if limpio_num else 50
            if cantidad > 500:
                return await interaction.followup.send("⚠️ El máximo permitido son **500 mensajes**.")
            
            async for m in canal.history(limit=cantidad):
                if not m.author.bot and m.content:
                    mensajes_texto.append(f"{m.author.name}: {m.content}")
            mensajes_texto.reverse()

        if not mensajes_texto:
            return await interaction.followup.send("⚠️ No se encontraron mensajes en este canal para el período seleccionado.")

        resp = client.chat.completions.create(
            model=MODELO_GROQ,
            messages=[{"role": "user", "content": f"Resume estos mensajes del canal #{canal.name}:\n" + "\n".join(mensajes_texto)}]
        )
        
        embed = discord.Embed(
            title=f"📜 Resumen de #{canal.name}",
            description=resp.choices[0].message.content,
            color=discord.Color.purple()
        )
        embed.set_footer(text=f"Procesados {len(mensajes_texto)} mensajes.")
        await interaction.followup.send(embed=embed)
    except Exception:
        await interaction.followup.send("⚠️ Formato incorrecto. Ejemplos válidos:\n• `50mss` | `2d` | `30m`\n• `08/09` o `08/09/2026`\n• `01/07 - 05/07` (Máx 10 días)")

# ==========================================
# COMANDO: /limpiar
# ==========================================
@bot.tree.command(name="limpiar", description="Limpia la memoria del bot")
@app_commands.choices(modo=[
    app_commands.Choice(name="Mi historial personal", value="user"),
    app_commands.Choice(name="Toda la memoria global (Solo Admins)", value="all")
])
async def borrar_historial(interaction: discord.Interaction, modo: app_commands.Choice[str]):
    if modo.value == "all":
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⚠️ Se requieren permisos de Administrador para borrar la memoria global.", ephemeral=True)
        historiales_usuarios.clear()
        await interaction.response.send_message("🧹 Memoria global borrada con éxito.")
    else:
        if interaction.user.id in historiales_usuarios:
            del historiales_usuarios[interaction.user.id]
            await interaction.response.send_message("🧹 Tu historial de conversación ha sido olvidado.", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ No tienes historial guardado.", ephemeral=True)

# ==========================================
# COMANDOS DE MODERACIÓN
# ==========================================
@bot.tree.command(name="canales", description="Crea uno o varios canales de texto separándolos por comas")
@app_commands.describe(nombres="Ejemplo: general, anuncios, fotos")
@app_commands.default_permissions(manage_channels=True)
async def crear_canales(interaction: discord.Interaction, nombres: str):
    await interaction.response.defer()
    for n in nombres.split(","):
        await interaction.guild.create_text_channel(name=n.strip())
    await interaction.followup.send("✅ Canales creados con éxito.")

@bot.tree.command(name="categorias", description="Crea una o varias categorías separándolas por comas")
@app_commands.describe(nombres="Ejemplo: INFO, CHAT, JUEGOS")
@app_commands.default_permissions(manage_channels=True)
async def crear_categorias(interaction: discord.Interaction, nombres: str):
    await interaction.response.defer()
    for n in nombres.split(","):
        await interaction.guild.create_category(name=n.strip())
    await interaction.followup.send("✅ Categorías creadas con éxito.")

class ConfirmarEliminar(discord.ui.View):
    def __init__(self, autor_id, canal_a_eliminar):
        super().__init__(timeout=30)
        self.autor_id = autor_id
        self.canal_a_eliminar = canal_a_eliminar

    @discord.ui.button(label="Confirmar borrado", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.autor_id:
            return await interaction.response.send_message("No puedes usar este botón.", ephemeral=True)
        
        await interaction.response.send_message(f"🗑️ Eliminando #{self.canal_a_eliminar.name}...")
        await self.canal_a_eliminar.delete()

@bot.tree.command(name="eliminar", description="Elimina un canal específico o el canal actual si no pones ninguno")
@app_commands.describe(canal="Menciona el canal a eliminar (Opcional, ej: #jijijaja)")
@app_commands.default_permissions(manage_channels=True)
async def eliminar_canal(interaction: discord.Interaction, canal: discord.TextChannel = None):
    canal_objetivo = canal or interaction.channel
    
    await interaction.response.send_message(
        f"⚠️ ¿Estás seguro de que deseas eliminar el canal **#{canal_objetivo.name}**?",
        view=ConfirmarEliminar(interaction.user.id, canal_objetivo)
    )

keep_alive()
bot.run(os.environ.get("DISCORD_TOKEN"))
