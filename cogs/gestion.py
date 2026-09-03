from typing import Optional, List
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

class ConfirmarBorradoCanales(discord.ui.View):
    def __init__(self, canales: List[discord.abc.GuildChannel], autor_id: int):
        super().__init__(timeout=45)
        self.canales = canales
        self.autor_id = autor_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Solo la persona que ejecutó el comando puede presionar estos botones.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔴 Seguro", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="🗑️ Eliminando canales...", view=None)
        
        eliminados = 0
        canal_actual_incluido = interaction.channel in self.canales
        
        for c in self.canales:
            if c != interaction.channel:
                try:
                    await c.delete()
                    eliminados += 1
                    await asyncio.sleep(0.3)
                except (discord.Forbidden, discord.HTTPException):
                    pass

        if canal_actual_incluido:
            try:
                await interaction.followup.send(f"✅ Se eliminaron {eliminados + 1} canales (incluyendo este).")
                await asyncio.sleep(1)
                await interaction.channel.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass
        else:
            await interaction.followup.send(f"✅ Se eliminaron {eliminados} canales.")

    @discord.ui.button(label="⚪ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Operación cancelada.", view=None)


class SelectEliminarView(discord.ui.View):
    def __init__(self, autor_id: int):
        super().__init__(timeout=60)
        self.autor_id = autor_id
        self.select = discord.ui.ChannelSelect(
            placeholder="Elige hasta 5 canales...", 
            max_values=5, 
            channel_types=[discord.ChannelType.text, discord.ChannelType.voice, discord.ChannelType.category]
        )
        self.select.callback = self.callback
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Solo la persona que ejecutó el comando puede usar este menú.", ephemeral=True)
            return False
        return True

    async def callback(self, inter: discord.Interaction):
        canales_obj = [inter.guild.get_channel(c.id) for c in self.select.values if inter.guild.get_channel(c.id)]
        if not canales_obj:
            return await inter.response.send_message("❌ No se encontraron los canales seleccionados.", ephemeral=True)
        
        nombres = ", ".join([c.name for c in canales_obj])
        view = ConfirmarBorradoCanales(canales_obj, self.autor_id)
        await inter.response.edit_message(content=f"⚠️ **¿Seguro que quieres eliminar estos canales?**\n`{nombres}`", view=view)


class Gestion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    grupo_gestionar = app_commands.Group(name="gestionar", description="Gestión del servidor")

    @grupo_gestionar.command(name="canales", description="Crea varios canales de texto separados por comas (Máx 5)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def crear_canales(self, interaction: discord.Interaction, nombres: str, categoria: Optional[discord.CategoryChannel] = None):
        await interaction.response.defer()
        nombres_list = [n.strip() for n in nombres.split(",") if n.strip()][:5]
        if not nombres_list:
            return await interaction.followup.send("❌ Debes ingresar al menos un nombre de canal válido.")

        creados = []
        for n in nombres_list:
            try:
                ch = await interaction.guild.create_text_channel(name=n, category=categoria)
                creados.append(ch.mention)
            except discord.Forbidden:
                return await interaction.followup.send("❌ El bot no tiene permisos suficientes para crear canales.")
            except discord.HTTPException as e:
                await interaction.followup.send(f"⚠️ Error al crear algunos canales: {e}")
                break

        if creados:
            await interaction.followup.send(f"✅ Canales creados con éxito: {', '.join(creados)}")

    @grupo_gestionar.command(name="categoria", description="Crea una categoría nueva en el servidor")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def crear_categoria(self, interaction: discord.Interaction, nombre: str):
        await interaction.response.defer()
        try:
            cat = await interaction.guild.create_category(name=nombre)
            await interaction.followup.send(f"✅ Categoría **{cat.name}** creada con éxito.")
        except discord.Forbidden:
            await interaction.followup.send("❌ El bot no tiene permisos para crear categorías.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al crear categoría: {e}")

    @grupo_gestionar.command(name="renombrar", description="Cambia el nombre de un canal específico")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def renombrar_canal(self, interaction: discord.Interaction, canal: discord.TextChannel, nuevo_nombre: str):
        await interaction.response.defer()
        try:
            nombre_formateado = nuevo_nombre.replace(" ", "-")
            await canal.edit(name=nombre_formateado)
            await interaction.followup.send(f"✅ Canal {canal.mention} renombrado con éxito a `{nombre_formateado}`.")
        except discord.HTTPException:
            await interaction.followup.send("❌ No se pudo renombrar el canal. Discord limita el cambio de nombres a 2 veces cada 10 minutos por canal.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al renombrar el canal: {e}")

    grupo_eliminar = app_commands.Group(name="eliminar", description="Opciones de eliminación de canales")

    @grupo_eliminar.command(name="actual", description="Borra el canal en el que te encuentras")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def elim_actual(self, interaction: discord.Interaction):
        view = ConfirmarBorradoCanales([interaction.channel], interaction.user.id)
        await interaction.response.send_message("⚠️ **¿Seguro que quieres eliminar ESTE canal? La acción es irreversible.**", view=view)

    @grupo_eliminar.command(name="especificos", description="Abre un menú interactivo para borrar hasta 5 canales")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def elim_especificos(self, interaction: discord.Interaction):
        view = SelectEliminarView(interaction.user.id)
        await interaction.response.send_message("🗑️ **Selecciona los canales a eliminar:**", view=view)

    @grupo_eliminar.command(name="masivo", description="Borra en lote los canales cuyo nombre contenga una palabra")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def elim_masivo(self, interaction: discord.Interaction, filtro: str, cantidad: int):
        if cantidad > 100:
            return await interaction.response.send_message("❌ Por seguridad el límite máximo para borrado masivo es de 100 canales.", ephemeral=True)
        
        canales_coincidentes = [c for c in interaction.guild.channels if filtro.lower() in c.name.lower()][:cantidad]
        
        if not canales_coincidentes:
            return await interaction.response.send_message(f"❌ No se encontró ningún canal cuyo nombre contenga `{filtro}`.", ephemeral=True)
            
        view = ConfirmarBorradoCanales(canales_coincidentes, interaction.user.id)
        await interaction.response.send_message(f"⚠️ **¿Seguro que quieres eliminar {len(canales_coincidentes)} canales que contienen `{filtro}` en su nombre?**", view=view)

async def setup(bot):
    await bot.add_cog(Gestion(bot))
