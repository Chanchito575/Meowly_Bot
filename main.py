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

MI_DISCORD_ID = int(os.getenv("OWNER_ID", "1481047586457518141"))

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

class MiBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=".",
            intents=intents,
            help_command=None
        )
        self.db = db
        self.owner_id_custom = MI_DISCORD_ID

    async def setup_hook(self):
        if os.path.exists('./cogs'):
            for filename in os.listdir('./cogs'):
                if filename.endswith('.py'):
                    try:
                        await self.load_extension(f'cogs.{filename[:-3]}')
                        print(f"📦 Cog cargado: {filename[:-3]}")
                    except Exception as e:
                        print(f"❌ Error al cargar el cog {filename}: {e}")

        try:
            synced = await self.tree.sync()
            print(f"🔁 {len(synced)} comandos Slash sincronizados.")
        except Exception as e:
            print(f"❌ Error al sincronizar comandos Slash: {e}")

bot = MiBot()

def es_dueno(interaction: discord.Interaction) -> bool:
    return interaction.user.id == MI_DISCORD_ID

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ No tienes los permisos requeridos para ejecutar este comando."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "❌ El bot no tiene los permisos suficientes en este canal/servidor para hacer esto."
    elif isinstance(error, app_commands.CheckFailure):
        msg = "❌ No tienes autorización para usar este comando."
    else:
        msg = "❌ Ocurrió un error inesperado al procesar el comando."
        print(f"⚠️ Error en comando '{interaction.command.name if interaction.command else 'desconocido'}': {error}")

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)

@bot.event
async def on_ready():
    await bot.change_presence(status=discord.Status.online, activity=discord.Game(name="/ia | Sistema seguro"))
    print(f"✅ Bot conectado con éxito como {bot.user}")
    print(f"👑 Propietario configurado (ID): {bot.owner_id_custom}")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ Error crítico: La variable DISCORD_TOKEN no está configurada en Render.")
    else:
        keep_alive()
        bot.run(token)
