import os
import threading
from flask import Flask
import discord
from discord.ext import commands

# --- SERVIDOR WEB ---
app = Flask('')

@app.route('/')
def home():
    return "Bot activo 24/7"

def run_flask():
    # Render asigna el puerto mediante la variable de entorno PORT (por defecto 8080)
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

# --- CONFIGURACIÓN DEL BOT ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.', intents=intents)

@bot.command(name="canales")
@commands.has_permissions(manage_channels=True)
async def crear_canales(ctx, *, nombres: str):
    lista_canales = [n.strip() for n in nombres.split(",") if n.strip()]
    if not lista_canales:
        await ctx.send("❌ Escribe al menos un nombre: `.canales general, memes`")
        return

    creados = 0
    for nombre in lista_canales:
        await ctx.guild.create_text_channel(nombre)
        creados += 1

    await ctx.send(f"✅ ¡Se crearon **{creados}** canales!")

@bot.command(name="categorias")
@commands.has_permissions(manage_channels=True)
async def crear_categorias(ctx, *, nombres: str):
    lista_categorias = [n.strip() for n in nombres.split(",") if n.strip()]
    if not lista_categorias:
        await ctx.send("❌ Escribe al menos un nombre: `.categorias CHAT, BOTS`")
        return

    creadas = 0
    for nombre in lista_categorias:
        await ctx.guild.create_category(nombre)
        creadas += 1

    await ctx.send(f"✅ ¡Se crearon **{creadas}** categorías!")

# --- INICIO DEL BOT ---
if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if token:
        keep_alive()
        bot.run(token)
    else:
        print("❌ Error: No se encontró la variable DISCORD_TOKEN en Render.")
