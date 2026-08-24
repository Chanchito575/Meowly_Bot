import os
import json
import base64
import asyncio
import discord
from discord.ext import commands
from keep_alive import keep_alive

import firebase_admin
from firebase_admin import credentials, firestore

# =====================================================================
# 🔐 CONFIGURACIÓN Y FIREBASE
# =====================================================================
MI_DISCORD_ID = 1122162289206902845
b64_credentials = os.getenv("FIREBASE_CREDENTIALS_BASE64")

db = None
if b64_credentials:
    try:
        decoded_json = base64.b64decode(b64_credentials).decode("utf-8")
        cred_dict = json.loads(decoded_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("🔥 Firebase Firestore conectado con éxito.")
    except Exception as e:
        print(f"❌ Error al conectar con Firebase: {e}")

# =====================================================================
# ⚙️ INICIALIZACIÓN DEL BOT
# =====================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)
bot.db = db
bot.owner_id_custom = MI_DISCORD_ID

async def load_cogs():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            await bot.load_extension(f'cogs.{filename[:-3]}')

@bot.event
async def on_ready():
    await load_cogs()
    await bot.tree.sync()
    actividad = discord.Game(name="creado por <@1122162289206902845> | /help")
    await bot.change_presence(status=discord.Status.online, activity=actividad)
    print(f"✅ Bot conectado con éxito como {bot.user}")

if __name__ == "__main__":
    keep_alive()
    bot.run(os.getenv("DISCORD_TOKEN"))
