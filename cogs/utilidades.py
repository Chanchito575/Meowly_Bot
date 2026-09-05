from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands
from cogs.ia import buscar_en_web

class Utilidades(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="testear", description="Diagnóstico privado del estado del bot")
    async def testear(self, interaction: discord.Interaction):
        owner_id = getattr(self.bot, "owner_id_custom", None)
        
        if (owner_id and interaction.user.id != owner_id) or (not owner_id and not await self.bot.is_owner(interaction.user)):
            return await interaction.response.send_message("❌ Comando no reconocido.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        latencia = round(self.bot.latency * 1000)
        
        estado_db = "❌ Desconectado"
        db = getattr(self.bot, "db", None)
        if db:
            try:
                db.collection("test").document("ping").set(
                    {"last_ping": datetime.now(timezone.utc).isoformat()}
                )
                estado_db = "✅ Operativo (Firebase Firestore)"
            except Exception as e:
                estado_db = f"❌ Error: {e}"

        try:
            res_web = await buscar_en_web("Python")
            estado_web = "✅ Operativo (DuckDuckGo)" if res_web and "No se pudo" not in res_web else "⚠️ Sin conexión"
        except Exception as e:
            estado_web = f"❌ Falla: {e}"

        permisos = interaction.app_permissions
        estado_permisos = "✅ Ok (Gestionar Canales)" if permisos and permisos.manage_channels else "❌ Faltan permisos requeridos"

        embed = discord.Embed(title="🕵️ Diagnóstico Privado - Meowly", color=discord.Color.dark_purple())
        embed.add_field(name="📶 Latencia Discord", value=f"`{latencia} ms`", inline=True)
        embed.add_field(name="🌐 Búsqueda Web", value=f"`{estado_web}`", inline=True)
        embed.add_field(name="🔥 Base de Datos Cloud", value=f"`{estado_db}`", inline=False)
        embed.add_field(name="🛠️ Permisos en Canal", value=f"`{estado_permisos}`", inline=False)
        embed.set_footer(text="Vista exclusiva del Administrador/Creador")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Muestra la guía explicativa completa de todos los comandos")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 GUÍA COMPLETA DE COMANDOS - MEOWLY",
            description="Lista detallada de todos los comandos y módulos disponibles.",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="🐱 Inteligencia Artificial",
            value="• `/ia <mensaje>`: Conversa con Meowly. Responde preguntas, realiza análisis y consulta la web en tiempo real.",
            inline=False
        )
        
        embed.add_field(
            name="🧹 Memoria del Bot",
            value=(
                "• `/limpiar mi_historial`: Borra tu contexto de charla individual con la IA.\n"
                "• `/limpiar todo`: (Admins) Reinicia el historial global de la IA."
            ),
            inline=False
        )

        embed.add_field(
            name="🎨 Gestor de Fuentes e Identidad Visual (Firebase Cloud)",
            value=(
                "• `/fuente escanear mensaje <mensaje> <nombre>`: Extrae y guarda una fuente desde un texto.\n"
                "• `/fuente escanear canal <canal> <nombre>`: Extrae la fuente usada en un canal.\n"
                "• `/fuente escanear categoria <categoria> <nombre>`: Extrae la fuente de una categoría.\n"
                "• `/fuente aplicar_canal <canal> <estilo> [emoji]`: Aplica una fuente al canal respetando su texto.\n"
                "• `/fuente aplicar_renombrar <canal> <estilo> <nuevo_nombre> [emoji]`: Rediseña un canal definiendo texto nuevo en **mayúsculas**.\n"
                "• `/fuente aplicar_categoria <categoria> <estilo> [emoji]`: Aplica estilo a una categoría.\n"
                "• `/fuente menu_categoria`: Menú interactivo desplegable para editar categorías.\n"
                "• `/fuente listar`: Lista las fuentes registradas en la nube del servidor.\n"
                "• `/fuente probar <texto> <estilo> [emoji]`: Genera vista previa de una fuente.\n"
                "• `/fuente eliminar <nombre>`: Elimina una fuente registrada."
            ),
            inline=False
        )

        embed.add_field(
            name="📊 Resúmenes de Chat con IA",
            value=(
                "• `/resumen defecto`: Resume los últimos 100 mensajes.\n"
                "• `/resumen hoy`: Resume la actividad global del día de hoy.\n"
                "• `/resumen dia <DD/MM>`: Resume los chats de una fecha específica.\n"
                "• `/resumen rango <inicio> <fin>`: Resumen comprendido entre dos fechas.\n"
                "• `/resumen mensajes <cantidad>`: Resume de 1 a 1000 mensajes.\n"
                "• `/resumen tiempo <horas>`: Resume las últimas N horas de chat.\n"
                "• `/resumen persona <usuario> <DD/MM>`: Resume la participación de un usuario específico."
            ),
            inline=False
        )

        embed.add_field(
            name="🛠️ Gestión Administrativa de Servidor",
            value=(
                "• `/gestionar canales <nombres>`: Crea múltiples canales de texto en lote (separados por comas).\n"
                "• `/gestionar categoria <nombre>`: Crea una nueva categoría de canales.\n"
                "• `/gestionar renombrar <canal> <nuevo_nombre>`: Cambia el nombre de un canal."
            ),
            inline=False
        )

        embed.add_field(
            name="🗑️ Limpieza y Purga de Canales",
            value=(
                "• `/eliminar actual`: Elimina el canal donde ejecutas el comando.\n"
                "• `/eliminar especificos`: Despliega un menú interactivo para seleccionar hasta 5 canales.\n"
                "• `/eliminar masivo <filtro> <cantidad>`: Purga masiva de canales por coincidencia de nombre (Máx 100)."
            ),
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ No tienes los permisos necesarios para ejecutar este comando."
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = "❌ El bot no tiene los permisos requeridos para realizar esta acción."
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ Comando en enfriamiento. Inténtalo de nuevo en {error.retry_after:.1f} segundos."
        else:
            msg = "❌ Ocurrió un error inesperado al procesar el comando."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

async def setup(bot):
    await bot.add_cog(Utilidades(bot))
