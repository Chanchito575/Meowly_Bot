from typing import Optional, List
import asyncio
import traceback
import unicodedata
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands

TIPOS_CANAL = (
    discord.TextChannel,
    discord.VoiceChannel,
    discord.StageChannel,
    discord.CategoryChannel,
    discord.ForumChannel,
)
_TABLA_SMALL_CAPS = str.maketrans("ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡʏᴢ", "abcdefghijklmnopqrstuvwyz")

def limpiar_md(texto: str) -> str:
    return texto.replace("`", "'")


def recortar(texto: str, limite: int = 1900) -> str:
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def normalizar_busqueda(texto: str) -> str:
    """Hace que 'Canal', 'cánal' y '𝗰𝗮𝗻𝗮𝗹' (fuentes de /fuente) coincidan al filtrar por nombre."""
    t = unicodedata.normalize("NFKD", texto.translate(_TABLA_SMALL_CAPS))
    return "".join(c for c in t if not unicodedata.combining(c)).casefold()


def ids_protegidos(guild) -> set:
    """Canales que Discord no deja borrar en servidores de comunidad."""
    return {c.id for c in (guild.rules_channel, guild.public_updates_channel) if c}


def motivo_no_gestionable(interaction: discord.Interaction, canal, para_borrar: bool = False) -> Optional[str]:
    """Devuelve el motivo por el que NO se puede gestionar ese canal, o None si sí se puede."""
    if not isinstance(canal, TIPOS_CANAL):
        return "ese tipo de elemento no está soportado"
    if para_borrar and canal.id in ids_protegidos(interaction.guild):
        return "es un canal requerido por la comunidad del servidor"
    if not canal.permissions_for(interaction.user).manage_channels:
        return "no tienes 'Gestionar canales' en él"
    yo = interaction.guild.me if interaction.guild else None
    if yo is not None and not canal.permissions_for(yo).manage_channels:
        return "no tengo 'Gestionar canales' en él"
    return None


async def renombrar_seguro(interaction: discord.Interaction, canal, nuevo_nombre: str):
    """Renombra comprobando permisos y límites de Discord. Devuelve (ok, mensaje)."""
    motivo = motivo_no_gestionable(interaction, canal)
    if motivo:
        return False, f"❌ No se puede renombrar **{limpiar_md(canal.name)}**: {motivo}."

    nuevo_nombre = nuevo_nombre.strip()[:100]
    if not nuevo_nombre:
        return False, "❌ El nombre resultante quedó vacío."
    if canal.name == nuevo_nombre:
        return False, "ℹ️ Ese elemento ya tiene ese nombre, no hay nada que cambiar."

    try:
        await asyncio.wait_for(
            canal.edit(name=nuevo_nombre, reason=f"Renombrado por {interaction.user} ({interaction.user.id})"),
            timeout=20,
        )
        mencion = canal.mention if hasattr(canal, "mention") else f"**{limpiar_md(canal.name)}**"
        return True, f"✅ Elemento {mencion} renombrado con éxito a `{limpiar_md(nuevo_nombre)}`."
    except asyncio.TimeoutError:
        return False, "⏳ Discord limita los cambios de nombre de un mismo canal (2 cada 10 minutos). Inténtalo más tarde."
    except discord.Forbidden:
        return False, "❌ Discord no me dejó hacer ese cambio: revisa los permisos y la posición del rol del bot."
    except discord.HTTPException as e:
        if e.status == 429:
            return False, "⏳ Límite de Discord alcanzado (2 cambios cada 10 minutos por canal)."
        if e.status == 400:
            return False, "❌ Discord rechazó ese nombre (puede ser inválido)."
        print(f"⚠️ Error de Discord al renombrar: {e}")
        return False, "❌ Error de Discord al renombrar."


def texto_confirmacion(canales: list, omitidos: Optional[list] = None, pregunta: str = "") -> str:
    lineas = [pregunta or f"⚠️ **¿Seguro que quieres eliminar {len(canales)} elemento(s)? La acción es irreversible.**"]
    lineas += [f"• {c.mention}" for c in canales[:20]]
    if any(isinstance(c, discord.CategoryChannel) for c in canales):
        lineas.append("ℹ️ Al eliminar una categoría, los canales dentro de ella **no** se borran: solo quedan sin categoría.")
    if omitidos:
        lineas.append("⏭️ **Omitidos:**")
        lineas += [f"• {o}" for o in omitidos[:10]]
    return recortar("\n".join(lineas))
class VistaBase(discord.ui.View):
    """Vista que solo puede usar quien ejecutó el comando y que se limpia sola al expirar."""

    def __init__(self, autor_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.autor_id = autor_id
        self.origen = None  
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message(
                "❌ Solo la persona que ejecutó el comando puede usar este menú.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        if self.origen is not None:
            try:
                await self.origen.edit_original_response(
                    content="⌛ Tiempo agotado. Vuelve a ejecutar el comando.", view=None
                )
            except discord.HTTPException:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        print(f"⚠️ Error en un menú de gestión: {type(error).__name__}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        msg = "❌ Ocurrió un error inesperado en el menú."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass


class PurgeModal(discord.ui.Modal, title="Cantidad de Mensajes"):
    cantidad_input = discord.ui.TextInput(
        label="Mensajes a revisar (Máximo 100)",
        placeholder="Ejemplo: 25",
        min_length=1,
        max_length=3,
        required=True
    )

    def __init__(self, tipo_purge: str, autor_id: int):
        super().__init__()
        self.tipo_purge = tipo_purge
        self.autor_id = autor_id

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        print(f"⚠️ Error en el formulario de purga: {type(error).__name__}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ocurrió un error inesperado.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ocurrió un error inesperado.", ephemeral=True)
        except discord.HTTPException:
            pass

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.autor_id:
            return await interaction.response.send_message("❌ No estás autorizado para enviar este formulario.", ephemeral=True)

        try:
            cantidad = int(self.cantidad_input.value.strip())
        except ValueError:
            return await interaction.response.send_message("❌ Ingresa un número entero válido.", ephemeral=True)
        if cantidad < 1 or cantidad > 100:
            return await interaction.response.send_message("❌ La cantidad debe estar entre 1 y 100.", ephemeral=True)

        canal = interaction.channel
        if interaction.guild is None or canal is None or not hasattr(canal, "purge"):
            return await interaction.response.send_message("❌ Este canal no admite la eliminación masiva de mensajes.", ephemeral=True)
        if not canal.permissions_for(interaction.user).manage_messages:
            return await interaction.response.send_message("❌ Ya no tienes el permiso 'Gestionar mensajes' en este canal.", ephemeral=True)
        yo = interaction.guild.me
        if yo is not None:
            pb = canal.permissions_for(yo)
            faltan = [n for n, ok in (("Gestionar mensajes", pb.manage_messages),
                                      ("Leer el historial de mensajes", pb.read_message_history)) if not ok]
            if faltan:
                return await interaction.response.send_message(
                    f"❌ Me falta en este canal: {', '.join(faltan)}.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        limite_antiguedad = discord.utils.utcnow() - timedelta(days=14) + timedelta(minutes=10)
        solo_bots = self.tipo_purge == "bots"

        def check(m) -> bool:
            if m.pinned or m.created_at < limite_antiguedad:
                return False
            return m.author.bot if solo_bots else True

        try:
            borrados = await canal.purge(
                limit=cantidad, check=check,
                reason=f"Purga ({self.tipo_purge}) por {interaction.user} ({interaction.user.id})",
            )
        except discord.Forbidden:
            return await interaction.followup.send("❌ No tengo el permiso 'Gestionar Mensajes' en este canal.", ephemeral=True)
        except discord.HTTPException as e:
            print(f"⚠️ Error en purga: {e}")
            return await interaction.followup.send("❌ Discord devolvió un error al eliminar los mensajes.", ephemeral=True)

        msg = f"✅ Se eliminaron **{len(borrados)}** mensaje(s) entre los últimos {cantidad} revisados."
        if len(borrados) < cantidad:
            msg += "\nℹ️ No se borran los mensajes fijados ni los de más de 14 días."
        await interaction.followup.send(msg, ephemeral=True)


class PurgeSelectView(VistaBase):
    def __init__(self, autor_id: int):
        super().__init__(autor_id, timeout=60)

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


class ConfirmarBorradoCanales(VistaBase):
    def __init__(self, canales: List[discord.abc.GuildChannel], autor_id: int):
        super().__init__(autor_id, timeout=45)
        self.canales = canales

    @discord.ui.button(label="🔴 Seguro (Eliminar)", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="🗑️ Ejecutando eliminación segura de canales...", view=None)

        actual = None
        eliminados, fallidos = [], []

        for c in self.canales:
            if interaction.channel is not None and c.id == interaction.channel.id:
                actual = c  
                continue
            motivo = motivo_no_gestionable(interaction, c, para_borrar=True)
            if motivo:
                fallidos.append(f"`{limpiar_md(c.name)}`: {motivo}")
                continue
            try:
                await c.delete(reason=f"Eliminado por {interaction.user} ({interaction.user.id})")
                eliminados.append(limpiar_md(c.name))
                await asyncio.sleep(0.5)
            except discord.Forbidden:
                fallidos.append(f"`{limpiar_md(c.name)}`: Discord no me dejó eliminarlo")
            except discord.HTTPException as e:
                fallidos.append(f"`{limpiar_md(c.name)}`: error de Discord ({e.status})")

        borrar_actual = False
        if actual is not None:
            motivo = motivo_no_gestionable(interaction, actual, para_borrar=True)
            if motivo:
                fallidos.append(f"`{limpiar_md(actual.name)}`: {motivo}")
            else:
                borrar_actual = True

        partes = []
        if eliminados:
            partes.append(f"✅ Eliminados ({len(eliminados)}): " + ", ".join(f"`{n}`" for n in eliminados))
        if fallidos:
            partes.append("⚠️ **No se pudo eliminar:**\n" + "\n".join(f"• {f}" for f in fallidos))
        if borrar_actual:
            partes.append("🗑️ Eliminando este canal…")
        if not partes:
            partes.append("ℹ️ No se eliminó ningún canal.")
        await interaction.followup.send(recortar("\n".join(partes)), ephemeral=True)

        if borrar_actual:
            await asyncio.sleep(1)
            try:
                await actual.delete(reason=f"Eliminado por {interaction.user} ({interaction.user.id})")
            except (discord.Forbidden, discord.HTTPException) as e:
                print(f"⚠️ No se pudo eliminar el canal actual: {e}")
                try:
                    await interaction.followup.send("⚠️ No pude eliminar este canal.", ephemeral=True)
                except discord.HTTPException:
                    pass

    @discord.ui.button(label="⚪ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Operación de borrado cancelada.", view=None)


class SelectEliminarView(VistaBase):
    def __init__(self, autor_id: int):
        super().__init__(autor_id, timeout=60)
        self.select = discord.ui.ChannelSelect(
            placeholder="Elige hasta 5 canales...",
            max_values=5,
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.voice,
                discord.ChannelType.stage_voice,
                discord.ChannelType.forum,
                discord.ChannelType.category,
            ],
        )
        self.select.callback = self.callback
        self.add_item(self.select)

    async def callback(self, inter: discord.Interaction):
        if not inter.guild:
            return await inter.response.send_message("❌ Este comando solo funciona en servidores.", ephemeral=True)

        validos, omitidos = [], []
        for c in self.select.values:
            ch = inter.guild.get_channel(c.id)
            if ch is None:
                omitidos.append(f"`{limpiar_md(c.name)}`: ya no existe")
                continue
            motivo = motivo_no_gestionable(inter, ch, para_borrar=True)
            if motivo:
                omitidos.append(f"{ch.mention}: {motivo}")
            else:
                validos.append(ch)

        if not validos:
            detalle = "\n".join(f"• {o}" for o in omitidos)
            return await inter.response.send_message(
                recortar(f"❌ No se puede eliminar ninguno de los canales elegidos:\n{detalle}"), ephemeral=True
            )

        view = ConfirmarBorradoCanales(validos, self.autor_id)
        view.origen = inter
        self.stop()  
        await inter.response.edit_message(content=texto_confirmacion(validos, omitidos), view=view)

class Gestion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    grupo_gestionar = app_commands.Group(name="gestionar", description="Gestión del servidor", guild_only=True)
    grupo_eliminar = app_commands.Group(
        name="eliminar", description="Opciones de eliminación de canales", parent=grupo_gestionar
    )

    @app_commands.command(name="purge", description="Elimina mensajes del canal mediante un menú interactivo")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(self, interaction: discord.Interaction):
        view = PurgeSelectView(autor_id=interaction.user.id)
        await interaction.response.send_message("🧹 **Control de Purga:** Selecciona una opción del menú:", view=view, ephemeral=True)
        view.origen = interaction

    @grupo_gestionar.command(name="canales", description="Crea varios canales de texto separados por comas (Máx 5)")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(nombres="Nombres separados por comas (máximo 5)",
                           categoria="Categoría donde se crearán (opcional)")
    async def crear_canales(self, interaction: discord.Interaction,
                            nombres: app_commands.Range[str, 1, 500],
                            categoria: Optional[discord.CategoryChannel] = None):
        await interaction.response.defer(ephemeral=True)

        permisos_usuario = categoria.permissions_for(interaction.user) if categoria else interaction.user.guild_permissions
        if not permisos_usuario.manage_channels:
            return await interaction.followup.send("❌ No tienes 'Gestionar canales' en ese lugar.", ephemeral=True)
        yo = interaction.guild.me
        if yo is not None:
            permisos_bot = categoria.permissions_for(yo) if categoria else yo.guild_permissions
            if not permisos_bot.manage_channels:
                return await interaction.followup.send("❌ No tengo 'Gestionar canales' en ese lugar.", ephemeral=True)

        pedidos = [n.strip() for n in nombres.split(",") if n.strip()]
        if not pedidos:
            return await interaction.followup.send("❌ Debes ingresar al menos un nombre de canal válido.", ephemeral=True)

        creados, errores = [], []
        for n in pedidos[:5]:
            nombre = n.replace(" ", "-")[:100]
            try:
                ch = await interaction.guild.create_text_channel(
                    name=nombre, category=categoria,
                    reason=f"Creado por {interaction.user} ({interaction.user.id})",
                )
                creados.append(ch.mention)
            except discord.Forbidden:
                errores.append("El bot perdió permisos para continuar creando canales.")
                break
            except discord.HTTPException as e:
                errores.append(f"Error al crear `{limpiar_md(nombre)}`: {str(getattr(e, 'text', e))[:150]}")
                break

        partes = []
        if creados:
            partes.append(f"✅ Canales creados con éxito: {', '.join(creados)}")
        partes += [f"⚠️ {e}" for e in errores]
        if len(pedidos) > 5:
            partes.append("ℹ️ Solo se crean 5 canales por comando; el resto se ignoró.")
        await interaction.followup.send(recortar("\n".join(partes)), ephemeral=True)

    @grupo_gestionar.command(name="categoria", description="Crea una categoría nueva en el servidor")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(nombre="Nombre de la categoría")
    async def crear_categoria(self, interaction: discord.Interaction, nombre: app_commands.Range[str, 1, 100]):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.followup.send("❌ No tienes 'Gestionar canales' en este servidor.", ephemeral=True)

        try:
            cat = await interaction.guild.create_category(
                name=nombre.strip(), reason=f"Creada por {interaction.user} ({interaction.user.id})"
            )
            await interaction.followup.send(f"✅ Categoría **{limpiar_md(cat.name)}** creada con éxito.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ El bot no tiene permisos para crear categorías.", ephemeral=True)
        except discord.HTTPException as e:
            print(f"⚠️ Error al crear categoría: {e}")
            await interaction.followup.send(
                f"❌ Discord no pudo crear la categoría: {str(getattr(e, 'text', e))[:150]}", ephemeral=True)

    @grupo_gestionar.command(name="renombrar", description="Cambia el nombre de un canal o categoría")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(canal="Canal o categoría a renombrar", nuevo_nombre="Nuevo nombre")
    async def renombrar_canal(self, interaction: discord.Interaction, canal: discord.abc.GuildChannel,
                              nuevo_nombre: app_commands.Range[str, 1, 100]):
        await interaction.response.defer(ephemeral=True)

        es_cat_o_voz = isinstance(canal, (discord.CategoryChannel, discord.VoiceChannel, discord.StageChannel))
        nombre_formateado = nuevo_nombre if es_cat_o_voz else nuevo_nombre.replace(" ", "-")

        _, msg = await renombrar_seguro(interaction, canal, nombre_formateado)
        await interaction.followup.send(msg, ephemeral=True)

    @grupo_eliminar.command(name="actual", description="Borra el canal en el que te encuentras")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def elim_actual(self, interaction: discord.Interaction):
        canal = interaction.channel
        if canal is None or not isinstance(canal, TIPOS_CANAL):
            return await interaction.response.send_message(
                "❌ Este tipo de canal (por ejemplo, un hilo) no se puede eliminar con este comando.", ephemeral=True)

        motivo = motivo_no_gestionable(interaction, canal, para_borrar=True)
        if motivo:
            return await interaction.response.send_message(f"❌ No se puede eliminar este canal: {motivo}.", ephemeral=True)

        view = ConfirmarBorradoCanales([canal], interaction.user.id)
        await interaction.response.send_message(
            texto_confirmacion([canal], pregunta="⚠️ **¿Seguro que quieres eliminar ESTE canal? La acción es irreversible.**"),
            view=view, ephemeral=True)
        view.origen = interaction

    @grupo_eliminar.command(name="especificos", description="Abre un menú interactivo para borrar hasta 5 canales")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def elim_especificos(self, interaction: discord.Interaction):
        view = SelectEliminarView(interaction.user.id)
        await interaction.response.send_message("🗑️ **Selecciona los canales a eliminar:**", view=view, ephemeral=True)
        view.origen = interaction

    @grupo_eliminar.command(name="masivo", description="Borra en lote los canales cuyo nombre contenga una palabra")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(filtro="Palabra que debe contener el nombre (mínimo 2 letras)",
                           cantidad="Máximo de canales a borrar (1 a 20)")
    async def elim_masivo(self, interaction: discord.Interaction,
                          filtro: app_commands.Range[str, 2, 50],
                          cantidad: app_commands.Range[int, 1, 20]):
        patron = normalizar_busqueda(filtro.strip())
        if len(patron) < 2:
            return await interaction.response.send_message("❌ El filtro debe tener al menos 2 caracteres.", ephemeral=True)

        coincidentes = sorted(
            (c for c in interaction.guild.channels if patron in normalizar_busqueda(c.name)),
            key=lambda c: c.name,
        )[:cantidad]

        if not coincidentes:
            return await interaction.response.send_message(
                f"❌ No se encontró ningún canal cuyo nombre contenga `{limpiar_md(filtro)}`.", ephemeral=True)

        validos, omitidos = [], []
        for c in coincidentes:
            motivo = motivo_no_gestionable(interaction, c, para_borrar=True)
            if motivo:
                omitidos.append(f"{c.mention}: {motivo}")
            else:
                validos.append(c)

        if not validos:
            detalle = "\n".join(f"• {o}" for o in omitidos)
            return await interaction.response.send_message(
                recortar(f"❌ Ninguno de los canales encontrados se puede eliminar:\n{detalle}"), ephemeral=True)

        view = ConfirmarBorradoCanales(validos, interaction.user.id)
        pregunta = (f"⚠️ **¿Seguro que quieres eliminar {len(validos)} elemento(s) que contienen "
                    f"`{limpiar_md(filtro)}` en su nombre?**")
        await interaction.response.send_message(
            texto_confirmacion(validos, omitidos, pregunta=pregunta), view=view, ephemeral=True)
        view.origen = interaction


async def setup(bot):
    await bot.add_cog(Gestion(bot))
