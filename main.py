import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from datetime import datetime, timezone, timedelta
import asyncio
import collections

# --- CONFIGURACIÓN E INICIALIZACIÓN DEL BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# Prefix configurado para comandos tradicionales (como .canales)
bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

# Sistema de memoria para la IA (límite de 20 mensajes por usuario)
# Los historiales durarán en memoria el tiempo que el bot esté activo (o se puede añadir lógica de expiración de 45 min)
memoria_ia = collections.defaultdict(lambda: collections.deque(maxlen=20))

@bot.event
async def on_ready():
    # Sincronizamos los comandos de barra (slash commands)
    await bot.tree.sync()
    # Establecemos el estado y descripción del bot
    actividad = discord.Game(name="creado o algo asi por Chanchito575")
    await bot.change_presence(status=discord.Status.online, activity=actividad)
    print(f"✅ Bot conectado como {bot.user}")

# =====================================================================
# 💬 1. INTELIGENCIA ARTIFICIAL (/ia)
# =====================================================================
@bot.tree.command(name="ia", description="Habla con la Inteligencia Artificial")
@app_commands.describe(mensaje="Mensaje o pregunta para la IA")
async def ia(interaction: discord.Interaction, mensaje: str):
    await interaction.response.defer()
    
    usuario_id = interaction.user.id
    # Guardamos el mensaje en la memoria (límite 20)
    memoria_ia[usuario_id].append({"role": "user", "content": mensaje})
    
    # Aquí iría la llamada a tu API de IA (Ej: Groq, OpenAI)
    respuesta_simulada = f"Procesando tu mensaje usando mis últimos {len(memoria_ia[usuario_id])} recuerdos de nuestra charla."
    
    memoria_ia[usuario_id].append({"role": "assistant", "content": respuesta_simulada})
    await interaction.followup.send(f"🤖 **Respuesta:** {respuesta_simulada}")

# =====================================================================
# 🧹 2. LIMPIAR MEMORIA (/limpiar)
# =====================================================================
@bot.tree.command(name="limpiar", description="Reinicia la memoria de la IA")
@app_commands.describe(modo="Tipo de limpieza")
@app_commands.choices(
    modo=[
        app_commands.Choice(name="personal - Borra tu historial", value="personal"),
        app_commands.Choice(name="todos - Borra el historial global (Solo Admins)", value="todos")
    ]
)
async def limpiar(interaction: discord.Interaction, modo: app_commands.Choice[str]):
    if modo.value == "todos":
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Requiere el permiso de **Administrador**.", ephemeral=True)
            return
        memoria_ia.clear()
        await interaction.response.send_message("🧹 Memoria global de la IA reiniciada con éxito.")
    else:
        usuario_id = interaction.user.id
        if usuario_id in memoria_ia:
            memoria_ia[usuario_id].clear()
        await interaction.response.send_message("🧹 Tu historial de conversación ha sido borrado.", ephemeral=True)

# =====================================================================
# 📊 3. RESUMEN INTELIGENTE (/resumen)
# =====================================================================
@bot.tree.command(name="resumen", description="Resumen inteligente del chat")
@app_commands.describe(
    modo="Filtro a aplicar", fecha="Fecha única (DD/MM)",
    inicio="Inicio (DD/MM)", fin="Fin (DD/MM)",
    cantidad="N° de mensajes (máx 1000)", tiempo="Minutos u horas"
)
@app_commands.choices(
    modo=[
        app_commands.Choice(name="defecto - Últimos 100 msgs", value="defecto"),
        app_commands.Choice(name="dia - Un día específico (fecha)", value="dia"),
        app_commands.Choice(name="fechas - Rango: inicio y fin", value="fechas"),
        app_commands.Choice(name="mensajes - N° de mensajes (cantidad)", value="mensajes"),
        app_commands.Choice(name="horas - Últimas N horas (tiempo)", value="horas"),
        app_commands.Choice(name="minutos - Últimos N minutos (tiempo)", value="minutos"),
        app_commands.Choice(name="hoy - Mensajes de hoy", value="hoy")
    ]
)
async def resumen(
    interaction: discord.Interaction,
    modo: Optional[app_commands.Choice[str]] = None,
    fecha: Optional[str] = None, inicio: Optional[str] = None, fin: Optional[str] = None,
    cantidad: Optional[int] = None, tiempo: Optional[int] = None
):
    await interaction.response.defer()
    selected_mode = modo.value if modo else "defecto"
    # Aquí integrarías la lógica de recolección de mensajes e IA que armamos antes
    await interaction.followup.send(f"📊 **Resumen generado** (Filtro: `{selected_mode}`)...")

# =====================================================================
# 🛠️ 4. GESTIÓN Y ORGANIZACIÓN (/gestionar)
# =====================================================================
@bot.tree.command(name="gestionar", description="Crea y organiza canales y categorías")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(
    modo="Acción a realizar", nombres="Nombres de canales separados por coma (máx 5)",
    categoria="Categoría donde crear canales", nombre="Nombre de la nueva categoría",
    canales="Canales existentes a mover (máx 10)"
)
@app_commands.choices(
    modo=[
        app_commands.Choice(name="crear_canales - Crear canales de texto", value="crear_canales"),
        app_commands.Choice(name="crear_categoria - Crear categoría y mover canales", value="crear_categoria")
    ]
)
async def gestionar(
    interaction: discord.Interaction,
    modo: app_commands.Choice[str],
    nombres: Optional[str] = None, categoria: Optional[discord.CategoryChannel] = None,
    nombre: Optional[str] = None, canales: Optional[str] = None
):
    await interaction.response.defer(ephemeral=True)
    if modo.value == "crear_canales":
        if not nombres:
            return await interaction.followup.send("❌ Debes especificar los `nombres`.")
        lista_nombres = [n.strip() for n in nombres.split(",")][:5] # Máximo 5
        for nom in lista_nombres:
            await interaction.guild.create_text_channel(name=nom, category=categoria)
        await interaction.followup.send(f"✅ Se crearon {len(lista_nombres)} canales.")

    elif modo.value == "crear_categoria":
        if not nombre:
            return await interaction.followup.send("❌ Debes especificar el `nombre` de la categoría.")
        nueva_cat = await interaction.guild.create_category(name=nombre)
        # La lógica de mover canales requeriría procesar el string 'canales' si se usa texto
        await interaction.followup.send(f"✅ Categoría **{nueva_cat.name}** creada.")

@gestionar.error
async def gestionar_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Requiere el permiso de **Gestionar Canales**.", ephemeral=True)

# =====================================================================
# 🗑️ 5. PURGA Y ELIMINACIÓN (/eliminar)
# =====================================================================
class ConfirmarEliminacion(discord.ui.View):
    def __init__(self, target_info):
        super().__init__(timeout=30)
        self.target_info = target_info

    @discord.ui.button(label="Seguro", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"🗑️ Acción confirmada. Procesando eliminación ({self.target_info})...", view=None)
        # Aquí va la lógica real de borrado de canales (interaction.channel.delete(), etc.)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Operación de eliminación cancelada.", view=None)

@bot.tree.command(name="eliminar", description="Sistema de borrado de canales")
@app_commands.describe(
    modo="Modo de eliminación", canales="Canales específicos a eliminar",
    filtro="Palabra clave para borrado masivo", cantidad="Cantidad límite (máx 500)"
)
@app_commands.choices(
    modo=[
        app_commands.Choice(name="actual - Borra este canal", value="actual"),
        app_commands.Choice(name="especificos - Selecciona canales de una lista", value="especificos"),
        app_commands.Choice(name="masivo - Borrado masivo anti-raid (Solo Admins)", value="masivo")
    ]
)
async def eliminar(
    interaction: discord.Interaction, modo: app_commands.Choice[str],
    canales: Optional[str] = None, filtro: Optional[str] = None, cantidad: Optional[int] = None
):
    perms = interaction.user.guild_permissions
    
    if modo.value in ["actual", "especificos"] and not (perms.manage_channels or perms.administrator):
        return await interaction.response.send_message("❌ Requiere el permiso de **Gestionar Canales**.", ephemeral=True)
    if modo.value == "masivo" and not perms.administrator:
        return await interaction.response.send_message("❌ El modo masivo requiere **Administrador**.", ephemeral=True)

    view = ConfirmarEliminacion(target_info=modo.value)
    await interaction.response.send_message(
        f"⚠️ **¿Seguro que quieres eliminar ({modo.value})? Esta acción no se puede revertir.**",
        view=view, ephemeral=True
    )

# =====================================================================
# ❓ 6. AYUDA GLOBAL (/help)
# =====================================================================
@bot.tree.command(name="help", description="Muestra la guía completa de comandos")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 CENTRO DE AYUDA — MANUAL DEL BOT",
        description="*Guía completa de comandos, parámetros y permisos.*",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="💬 INTELIGENCIA ARTIFICIAL",
        value="• **/ia** `mensaje:` — Conversa con la IA. *(🟢 Todos)*\n"
              "• **/limpiar** `modo:` — Borra historial (`personal` o `todos`).\n"
              "• **/resumen** `modo:` — Sintetiza el chat con filtros. *(🟢 Todos)*",
        inline=False
    )
    embed.add_field(
        name="🛠️ GESTIÓN Y ORGANIZACIÓN",
        value="• **/gestionar** `modo:` — Crea y mueve canales/categorías. *(⚙️ Gestionar Canales)*",
        inline=False
    )
    embed.add_field(
        name="🗑️ ELIMINACIÓN DE CANALES",
        value="• **/eliminar** `modo:` — `actual`, `especificos` o `masivo`. Requiere permisos.",
        inline=False
    )
    embed.add_field(
        name="📂 COMANDOS PRE-EXISTENTES",
        value="• **.canales** `Nombre, Nombre, Nombre` — Crea canales en lote.\n"
              "• **.categorias** — Lista las categorías del servidor.",
        inline=False
    )
    await interaction.response.send_message(embed=embed)

# =====================================================================
# 📁 7. COMANDOS PRE-EXISTENTES CLÁSICOS (Prefijo .)
# =====================================================================
@bot.command()
@commands.has_permissions(manage_channels=True)
async def canales(ctx, *, nombres: str = None):
    """Comando organizador clásico: .canales Nombre, Nombre, Nombre"""
    if not nombres:
        await ctx.send("⚠️ Por favor, aclara los nombres: `.canales Nombre, Nombre, Nombre`")
        return
    
    lista = [n.strip() for n in nombres.split(",")][:5]
    for nom in lista:
        await ctx.guild.create_text_channel(name=nom, category=ctx.channel.category)
    await ctx.send(f"✅ Se han creado {len(lista)} canales en esta categoría.")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def categorias(ctx):
    """Lista las categorías del servidor y sus canales"""
    lista_cat = [f"📁 **{cat.name}** ({len(cat.channels)} canales)" for cat in ctx.guild.categories]
    texto = "\n".join(lista_cat) if lista_cat else "No hay categorías."
    await ctx.send(f"📋 **Categorías del servidor:**\n{texto}")

# --- INICIO DEL BOT ---
if __name__ == "__main__":
    TOKEN = "DISCORD_TOKEN"
    bot.run(TOKEN)
