import os
import json
import base64
import asyncio
import discord
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
    
    try:
        synced = await bot.tree.sync()
        print(f"🔁 {len(synced)} comandos Slash sincronizados.")
    except Exception as e:
        print(f"❌ Error al sincronizar comandos Slash: {e}")

bot.setup_hook = custom_setup

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
