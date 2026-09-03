from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands
from cogs.ia import buscar_en_web

class Utilidades(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="testear", description="Diagnóstico privado del bot")
    async def testear(self, interaction: discord.Interaction):
        owner_id = getattr(self.bot, "owner_id_custom", None)
        
        # Validación segura del propietario del bot
        if owner_id and interaction.user.id != owner_id:
            return await interaction.response.send_message("❌ Comando no reconocido.", ephemeral=True)
        elif not owner_id and not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ Comando no reconocido.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        latencia = round(self.bot.latency * 1000)
        
        # Verificación segura de conexión con la Base de Datos
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

        # Prueba de conectividad con la API de búsqueda web
        try:
            res_web = await buscar_en_web("Python")
            estado_web = "✅ Operativo (DuckDuckGo)" if res_web and "No se pudo" not in res_web else "⚠️ Sin conexión"
        except Exception as e:
            estado_web = f"❌ Falla: {e}"

        permisos = interaction.app_permissions
        estado_permisos = "✅ Ok (Gestionar Canales)" if permisos and permisos.manage_channels else "❌ Faltan permisos requeridos"

        embed = discord.Embed(title="🕵️ Diagnóstico Privado - Meowly", color=discord.Color.dark_purple())
        embed.add_field(name="📶 Latencia de Discord", value=f"`{latencia} ms`", inline=True)
        embed.add_field(name="🌐 Búsqueda Web", value=f"`{estado_web}`", inline=True)
        embed.add_field(name="🔥 Base de Datos Cloud", value=f"`{estado_db}`", inline=False)
        embed.add_field(name="🛠️ Permisos en Canal", value=f"`{estado_permisos}`", inline=False)
        embed.set_footer(text="Vista exclusiva del Creador")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Muestra la guía explicativa completa de todos los comandos")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 GUÍA COMPLETA DE COMANDOS - MEOWLY BOT",
            description="A continuación tienes la explicación detallada de cada grupo de comandos y sus funciones.",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="🐱 Inteligencia Artificial",
            value="• `/ia <mensaje>`: Conversa con Meowly (combina Qwen 2.5, Mistral y Groq Llama 3.1). Busca información en la web si detecta preguntas de temas actuales.",
            inline=False
        )
        
        embed.add_field(
            name="🧹 Memoria del Bot",
            value=(
                "• `/limpiar mi_historial`: Borra únicamente el contexto y la memoria de tus charlas con la IA.\n"
                "• `/limpiar todo`: (Solo Admins) Reinicia la memoria global de todos los usuarios."
            ),
            inline=False
        )

        embed.add_field(
            name="🎨 Gestión de Fuentes y Estilos (Firebase Cloud)",
            value=(
                "• `/fuente escanear mensaje <mensaje> <nombre>`: Analiza un texto o abecedario que le envíes directamente y guarda su tipografía.\n"
                "• `/fuente escanear canal <canal> <nombre>`: Analiza el tipo de letra del nombre de un canal existente.\n"
                "• `/fuente aplicar <canal> <estilo> [emoji]`: Aplica una fuente guardada al nombre de un canal.\n"
                "• `/fuente listar`: Lista las fuentes registradas en Firebase para este servidor.\n"
                "• `/fuente probar <texto> <estilo> [emoji]`: Muestra una vista previa de cómo quedaría un texto.\n"
                "• `/fuente eliminar <nombre>`: Borra una fuente de la nube del servidor."
            ),
            inline=False
        )

        embed.add_field(
            name="📊 Resúmenes con IA",
            value=(
                "• `/resumen defecto`: Resume los últimos 100 mensajes enviados.\n"
                "• `/resumen hoy`: Resume todo lo conversado en el día de hoy.\n"
                "• `/resumen dia <DD/MM>`: Extrae y resume la actividad de una fecha específica.\n"
                "• `/resumen rango <inicio> <fin>`: Resumen entre dos fechas.\n"
                "• `/resumen mensajes <cantidad>`: Resume de 1 a 1000 mensajes.\n"
                "• `/resumen tiempo <horas>`: Resume las últimas N horas de chat.\n"
                "• `/resumen persona <usuario> <DD/MM>`: Resume la actividad de un usuario en un día."
            ),
            inline=False
        )

        embed.add_field(
            name="🛠️ Gestión Administrativa",
            value=(
                "• `/gestionar canales <nombres>`: Crea múltiples canales de texto separados por comas (Máx 5).\n"
                "• `/gestionar categoria <nombre>`: Crea una nueva categoría.\n"
                "• `/gestionar renombrar <canal> <nuevo_nombre>`: Cambia el nombre de un canal."
            ),
            inline=False
        )

        embed.add_field(
            name="🗑️ Eliminación de Canales",
            value=(
                "• `/eliminar actual`: Elimina el canal actual.\n"
                "• `/eliminar especificos`: Menú desplegable para borrar hasta 5 canales.\n"
                "• `/eliminar masivo <filtro> <cantidad>`: Elimina canales en lote por nombre (Máx 100)."
            ),
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
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
