from typing import Optional, List
import discord
from discord import app_commands
from discord.ext import commands

class ConfirmarBorradoCanales(discord.ui.View):
    def __init__(self, canales: List[discord.abc.GuildChannel]):
        super().__init__(timeout=45)
        self.canales = canales

    @discord.ui.button(label="🔴 Seguro", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="🗑️ Eliminando canales...", view=None)
        eliminados = 0
        for c in self.canales:
            try:
                await c.delete()
                eliminados += 1
            except: pass
        if interaction.channel in self.canales: return
        await interaction.followup.send(f"✅ Se eliminaron {eliminados} canales.")

    @discord.ui.button(label="⚪ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Operación cancelada.", view=None)

class Gestion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    grupo_gestionar = app_commands.Group(name="gestionar", description="Gestión del servidor")

    @grupo_gestionar.command(name="canales", description="Crea varios canales de texto separados por comas (Máx 5)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def crear_canales(self, interaction: discord.Interaction, nombres: str, categoria: Optional[discord.CategoryChannel] = None):
        await interaction.response.defer()
        nombres_list = [n.strip() for n in nombres.split(",") if n.strip()][:5]
        creados = []
        for n in nombres_list:
            ch = await interaction.guild.create_text_channel(name=n, category=categoria)
            creados.append(ch.mention)
        await interaction.followup.send(f"✅ Creados: {', '.join(creados)}")

    @grupo_gestionar.command(name="categoria", description="Crea una categoría nueva en el servidor")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def crear_categoria(self, interaction: discord.Interaction, nombre: str):
        await interaction.response.defer()
        cat = await interaction.guild.create_category(name=nombre)
        await interaction.followup.send(f"✅ Categoría **{cat.name}** creada.")

    @grupo_gestionar.command(name="renombrar", description="Cambia el nombre de un canal específico")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def renombrar_canal(self, interaction: discord.Interaction, canal: discord.TextChannel, nuevo_nombre: str):
        await canal.edit(name=nuevo_nombre.replace(" ", "-"))
        await interaction.response.send_message(f"✅ Canal renombrado a {canal.mention}.")

    grupo_eliminar = app_commands.Group(name="eliminar", description="Opciones de eliminación de canales")

    @grupo_eliminar.command(name="actual", description="Borra el canal en el que te encuentras")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def elim_actual(self, interaction: discord.Interaction):
        view = ConfirmarBorradoCanales([interaction.channel])
        await interaction.response.send_message("⚠️ **¿Seguro que quieres eliminar ESTE canal? La acción es irreversible.**", view=view)

    @grupo_eliminar.command(name="especificos", description="Abre un menú interactivo para borrar hasta 5 canales")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def elim_especificos(self, interaction: discord.Interaction):
        class SelectEliminar(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60)
                self.select = discord.ui.ChannelSelect(
                    placeholder="Elige hasta 5 canales...", 
                    max_values=5, 
                    channel_types=[discord.ChannelType.text, discord.ChannelType.voice]
                )
                self.select.callback = self.callback
                self.add_item(self.select)
                
            async def callback(self, inter: discord.Interaction):
                canales_obj = [inter.guild.get_channel(c.id) for c in self.select.values if inter.guild.get_channel(c.id)]
                nombres = ", ".join([c.name for c in canales_obj])
                view = ConfirmarBorradoCanales(canales_obj)
                await inter.response.edit_message(content=f"⚠️ **¿Seguro que quieres eliminar estos canales?**\n`{nombres}`", view=view)

        await interaction.response.send_message("🗑️ **Selecciona los canales a eliminar:**", view=SelectEliminar())

    @grupo_eliminar.command(name="masivo", description="Borra en lote los canales cuyo nombre contenga una palabra")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def elim_masivo(self, interaction: discord.Interaction, filtro: str, cantidad: int):
        if cantidad > 500: return await interaction.response.send_message("❌ El límite masivo es 500 canales.")
        canales_coincidentes = [c for c in interaction.guild.channels if filtro.lower() in c.name.lower()][:cantidad]
        
        if not canales_coincidentes:
            return await interaction.response.send_message(f"❌ No encontré ningún canal que contenga `{filtro}`.")
            
        view = ConfirmarBorradoCanales(canales_coincidentes)
        await interaction.response.send_message(f"⚠️ **¿Seguro que quieres eliminar {len(canales_coincidentes)} canales que contienen `{filtro}`?**", view=view)

async def setup(bot):
    await bot.add_cog(Gestion(bot))
