import os
import json
import base64
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive

import firebase_admin
from firebase_admin import credentials, firestore

MI_DISCORD_ID = int(os.getenv("OWNER_ID", "1122162289206902845"))

db = None
b64_credentials = os.getenv("FIREBASE_CREDENTIALS_BASE64")

if b64_credentials:
    try:
        decoded_json = base64.b64decode(b64_credentials).decode("utf-8")
        cred_dict = json.loads(decoded_json)
        cred = credentials.Certificate(cred_dict)
        app = firebase_admin.initialize_app(cred)
        db = firestore.client(app=app)
        print("🔥 Firebase Firestore conectado con éxito.")
    except Exception as e:
        print(f"❌ Error al conectar con Firebase: {e}")
else:
    print("⚠️ Advertencia: No se encontró FIREBASE_CREDENTIALS_BASE64.")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)
bot.db = db
bot.owner_id_custom = MI_DISCORD_ID

async def custom_setup():
    if os.path.exists('./cogs'):
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await bot.load_extension(f'cogs.{filename[:-3]}')
                    print(f"📦 Cog cargado: {filename[:-3]}")
                except Exception as e:
                    print(f"❌ Error al cargar el cog {filename}: {e}")

    def aplicar_bypass_dueno(cmd):
        if hasattr(cmd, "checks") and cmd.checks:
            nuevos_checks = []
            for chk in cmd.checks:
                def crear_wrapper(c):
                    async def wrapper(interaction: discord.Interaction):
                        if interaction.user.id == MI_DISCORD_ID:
                            return True
                        res = c(interaction)
                        return await res if asyncio.iscoroutine(res) else res
                    return wrapper
                nuevos_checks.append(crear_wrapper(chk))
            cmd.checks = nuevos_checks

        if isinstance(cmd, app_commands.Group):
            for sub_cmd in cmd.commands:
                aplicar_bypass_dueno(sub_cmd)

    for cmd in bot.tree.get_commands():
        aplicar_bypass_dueno(cmd)

    try:
        synced = await bot.tree.sync()
        print(f"🔁 {len(synced)} comandos Slash sincronizados.")
    except Exception as e:
        print(f"❌ Error al sincronizar comandos Slash: {e}")

bot.setup_hook = custom_setup

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ No tienes los permisos requeridos para ejecutar este comando."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "❌ El bot no tiene los permisos suficientes en este canal/servidor."
    else:
        msg = "❌ Ocurrió un error inesperado al procesar el comando."
        print(f"⚠️ Error en comando '{interaction.command.name if interaction.command else 'desconocido'}': {error}")

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)

@bot.event
async def on_ready():
    actividad = discord.Game(name=f"creado por <@{bot.owner_id_custom}> | /ia")
    await bot.change_presence(status=discord.Status.online, activity=actividad)
    print(f"✅ Bot conectado con éxito como {bot.user}")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ Error crítico: La variable DISCORD_TOKEN no está configurada.")
    else:
        keep_alive()
        bot.run(token)
