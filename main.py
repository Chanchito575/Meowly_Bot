import os
import discord
from discord.ext import commands

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

token = os.environ.get("DISCORD_TOKEN")
bot.run(token)
