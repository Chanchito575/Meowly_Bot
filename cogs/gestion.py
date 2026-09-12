from typing import Optional, List
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

class PurgeModal(discord.ui.Modal, title="Cantidad de Mensajes"):
    cantidad_input = discord.ui.TextInput(
        label="Cantidad a eliminar (Máximo 100)",
        placeholder="Ejemplo: 25",
        min_length=1,
        max_length=3,
        required=True
    )

    def __init__(self, tipo_purge: str, autor_id: int):
        super().__init__()
        self.tipo_purge = tipo_purge
        self.autor_id = autor_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cantidad = int(self.cantidad_input.value)
            if cantidad < 1 or cantidad > 100:
                return await interaction.response.send_message("❌ La cantidad debe estar entre 1 y 100.", ephemeral=True)
        except ValueError:
            return await interaction.response.send_message("❌ Ingresa un número entero válido.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        if not hasattr(interaction.channel, "purge"):
            return await interaction.followup.send("❌ Este canal no admite la eliminación masiva de mensajes.", ephemeral=True)

        check_func = (lambda m: m.author.bot) if self.tipo_purge == "bots" else None

        try:
            await interaction.channel.purge(limit=cantidad, check=check_func)
            await interaction.followup.send("✅ Mensajes eliminados con éxito.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo el permiso 'Gestionar Mensajes' en este canal.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Error al eliminar mensajes: {e}", ephemeral=True)


class PurgeSelectView(discord.ui.View):
    def __init__(self, autor_id: int):
        super().__init__(timeout=60)
        self.autor_id = autor_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Solo la persona que ejecutó el comando puede usar este menú.", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        placeholder="🧹 Selecciona qué tipo de mensajes borrar",
        options=[
            discord.SelectOption(
                label="Mensajes de Bots", 
                value="bots", 
                description="Elimina únicamente los mensajes enviados por bots", 
                emoji="🤖"
            ),
            discord.SelectOption(
                label="Todos los Mensajes", 
                value="todos", 
                description="Elimina mensajes de usuarios y bots", 
                emoji="💬"
            )
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        modal = PurgeModal(tipo_purge=select.values[0], autor_id=self.autor_id)
        await interaction.response.send_modal(modal)


class ConfirmarBorradoCanales(discord.ui.View):
    def __init__(self, canales: List[discord.abc.GuildChannel], autor_id: int):
        super().__init__(timeout=45)
        self.canales = canales
        self.autor_id = autor_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("❌ Solo la persona que ejecutó el comando puede usar estos botones.", ephemeral=True)
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
        if not inter.guild:
            return await inter.response.send_message("❌ Este comando solo funciona en servidores.", ephemeral=True)

        canales_obj = []
        for c in self.select.values:
            ch = inter.guild.get_channel(c.id) or inter.guild.get_channel_or_thread(c.id)
            if ch:
                canales_obj.append(ch)

        if not canales_obj:
            return await inter.response.send_message("❌ No se encontraron los canales seleccionados.", ephemeral=True)
        
        nombres = ", ".join([c.name for c in canales_obj])
        view = ConfirmarBorradoCanales(canales_obj, self.autor_id)
        await inter.response.edit_message(content=f"⚠️ **¿Seguro que quieres eliminar estos canales?**\n`{nombres}`", view=view)


class Gestion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    grupo_gestionar = app_commands.Group(name="gestionar", description="Gestión del servidor")
    grupo_eliminar = app_commands.Group(name="eliminar", description="Opciones de eliminación de canales", parent=grupo_gestionar)

    @app_commands.command(name="purge", description="Elimina mensajes del canal mediante un menú interactivo")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction):
        view = PurgeSelectView(autor_id=interaction.user.id)
        await interaction.response.send_message("🧹 **Control de Purga:** Selecciona una opción del menú:", view=view, ephemeral=True)

    @grupo_gestionar.command(name="canales", description="Crea varios canales de texto separados por comas (Máx 5)")
    @app_commands.guild_only()
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
                await interaction.followup.send("❌ El bot perdió permisos para continuar creando canales.")
                break
            except discord.HTTPException as e:
                await interaction.followup.send(f"⚠️ Error al crear el canal `{n}`: {e}")
                break

        if creados:
            await interaction.followup.send(f"✅ Canales creados con éxito: {', '.join(creados)}")

    @grupo_gestionar.command(name="categoria", description="Crea una categoría nueva en el servidor")
    @app_commands.guild_only()
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

    @grupo_gestionar.command(name="renombrar", description="Cambia el nombre de un canal o categoría")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_channels=True)
    async def renombrar_canal(self, interaction: discord.Interaction, canal: discord.abc.GuildChannel, nuevo_nombre: str):
        await interaction.response.defer()
        try:
            es_cat_o_voz = isinstance(canal, (discord.CategoryChannel, discord.VoiceChannel))
            nombre_formateado = nuevo_nombre if es_cat_o_voz else nuevo_nombre.replace(" ", "-")
            await canal.edit(name=nombre_formateado)
            
            mencion = canal.mention if hasattr(canal, "mention") else f"**{canal.name}**"
            await interaction.followup.send(f"✅ Elemento {mencion} renombrado con éxito a `{nombre_formateado}`.")
        except discord.HTTPException as e:
            if e.status == 429:
                await interaction.followup.send("⏳ Límite de Discord alcanzado (2 cambios cada 10 minutos por canal).")
            else:
                await interaction.followup.send(f"❌ Error de Discord al renombrar: {e}")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al renombrar: {e}")

    @grupo_eliminar.command(name="actual", description="Borra el canal en el que te encuentras")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_channels=True)
    async def elim_actual(self, interaction: discord.Interaction):
        view = ConfirmarBorradoCanales([interaction.channel], interaction.user.id)
        await interaction.response.send_message("⚠️ **¿Seguro que quieres eliminar ESTE canal? La acción es irreversible.**", view=view)

    @grupo_eliminar.command(name="especificos", description="Abre un menú interactivo para borrar hasta 5 canales")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_channels=True)
    async def elim_especificos(self, interaction: discord.Interaction):
        view = SelectEliminarView(interaction.user.id)
        await interaction.response.send_message("🗑️ **Selecciona los canales a eliminar:**", view=view)

    @grupo_eliminar.command(name="masivo", description="Borra en lote los canales cuyo nombre contenga una palabra")
    @app_commands.guild_only()
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
