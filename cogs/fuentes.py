import os
import json
import openai
import discord
from discord import app_commands
from discord.ext import commands
from firebase_admin import firestore

MODELO_MISTRAL = "mistral-small-latest"
MODELO_QWEN = "Qwen/Qwen2.5-Coder-32B-Instruct"

class Fuentes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def cargar_fuentes(self, guild_id: int) -> dict:
        if not self.bot.db or not guild_id:
            return {}
        try:
            doc = self.bot.db.collection("servidores").document(str(guild_id)).get()
            return doc.to_dict().get("fuentes", {}) if doc and doc.exists else {}
        except Exception:
            return {}

    def guardar_fuente(self, guild_id: int, nombre: str, mapeo: dict) -> bool:
        if not self.bot.db or not guild_id:
            return False
        try:
            doc_ref = self.bot.db.collection("servidores").document(str(guild_id))
            doc_ref.set({f"fuentes.{nombre.lower()}": mapeo}, merge=True)
            return True
        except Exception:
            return False

    def eliminar_fuente(self, guild_id: int, nombre: str) -> bool:
        if not self.bot.db or not guild_id:
            return False
        try:
            doc_ref = self.bot.db.collection("servidores").document(str(guild_id))
            doc = doc_ref.get()
            if doc.exists and nombre.lower() in doc.to_dict().get("fuentes", {}):
                doc_ref.update({f"fuentes.{nombre.lower()}": firestore.DELETE_FIELD})
                return True
            return False
        except Exception:
            return False

    def aplicar_mapeo(self, texto: str, mapeo: dict) -> str:
        return "".join(mapeo.get(c, c) for c in texto)

    async def estilo_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []
        fuentes = self.cargar_fuentes(interaction.guild_id)
        opciones = []
        for nombre in fuentes.keys():
            if current.lower() in nombre.lower():
                opciones.append(app_commands.Choice(name=nombre.capitalize(), value=nombre.lower()))
        return opciones[:25]

    async def ia_extraer_mapeo_fuente(self, ejemplo_texto: str) -> dict:
        prompt = (
            f"Analiza la tipografía del texto: '{ejemplo_texto}'. Extrae los caracteres especiales "
            "y genera un JSON mapeando cada letra normal con su carácter tipográfico especial.\n"
            "Responde ÚNICAMENTE el JSON sin bloques de código ni explicación adicional.\n"
            'Ejemplo de salida: {"a": "ⓐ", "b": "ⓑ", "A": "Ⓐ"}'
        )
        
        mistral_key = os.getenv("MISTRAL_API_KEY")
        if mistral_key:
            try:
                mistral_client = openai.AsyncOpenAI(base_url="https://api.mistral.ai/v1/", api_key=mistral_key, timeout=15.0)
                resp = await mistral_client.chat.completions.create(model=MODELO_MISTRAL, messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=500)
                contenido = resp.choices[0].message.content.strip()
                if "```json" in contenido:
                    contenido = contenido.split("```json")[1].split("```")[0].strip()
                elif "```" in contenido:
                    contenido = contenido.split("```")[1].split("```")[0].strip()
                return json.loads(contenido)
            except Exception as e:
                print(f"Mistral falló procesando fuente: {e}")

        hf_key = os.getenv("HF_TOKEN")
        if hf_key:
            try:
                hf_client = openai.AsyncOpenAI(base_url="https://router.huggingface.co/v1/", api_key=hf_key, timeout=15.0)
                resp = await hf_client.chat.completions.create(model=MODELO_QWEN, messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=500)
                contenido = resp.choices[0].message.content.strip()
                if "```json" in contenido:
                    contenido = contenido.split("```json")[1].split("```")[0].strip()
                elif "```" in contenido:
                    contenido = contenido.split("```")[1].split("```")[0].strip()
                return json.loads(contenido)
            except Exception as e:
                print(f"Hugging Face falló procesando fuente: {e}")

        raise Exception("No se pudo procesar la fuente. Revisa las API Keys o la estructura del texto.")

    grupo_fuente = app_commands.Group(name="fuente", description="Gestión de tipografías")
    grupo_escanear = app_commands.Group(name="escanear", description="Escanear y guardar tipografías", parent=grupo_fuente)

    @grupo_escanear.command(name="mensaje", description="Extrae una fuente directamente desde un texto o abecedario")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def escanear_mensaje(self, interaction: discord.Interaction, mensaje: str, nombre_guardar: str):
        await interaction.response.defer()
        if not self.bot.db:
            return await interaction.followup.send("❌ La base de datos Firebase no está disponible.")
        try:
            mapeo = await self.ia_extraer_mapeo_fuente(mensaje)
            if self.guardar_fuente(interaction.guild_id, nombre_guardar, mapeo):
                await interaction.followup.send(f"🧠 Se analizó el texto y se guardó la fuente **{nombre_guardar}** permanentemente.")
            else:
                await interaction.followup.send("❌ No se pudo guardar la fuente en Firebase.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al procesar la tipografía: {e}")

    @grupo_escanear.command(name="canal", description="Extrae la fuente del nombre de un canal existente")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def escanear_canal(self, interaction: discord.Interaction, canal: discord.TextChannel, nombre_guardar: str):
        await interaction.response.defer()
        if not self.bot.db:
            return await interaction.followup.send("❌ La base de datos Firebase no está disponible.")
        try:
            mapeo = await self.ia_extraer_mapeo_fuente(canal.name)
            if self.guardar_fuente(interaction.guild_id, nombre_guardar, mapeo):
                await interaction.followup.send(f"🧠 Se analizó {canal.mention} y se guardó la fuente **{nombre_guardar}** permanentemente.")
            else:
                await interaction.followup.send("❌ No se pudo guardar la fuente en Firebase.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al procesar la tipografía: {e}")

    @grupo_fuente.command(name="aplicar", description="Aplica una fuente guardada al nombre de un canal")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def aplicar_fuente_cmd(self, interaction: discord.Interaction, canal: discord.TextChannel, estilo: str, emoji: str = "💬"):
        await interaction.response.defer()
        if not self.bot.db:
            return await interaction.followup.send("❌ La base de datos Firebase no está disponible.")
        fuentes = self.cargar_fuentes(interaction.guild_id)
        if estilo.lower() not in fuentes:
            return await interaction.followup.send(f"❌ Fuente **{estilo}** no encontrada en la base de datos.")
        
        nombre_limpio = canal.name.split("｜")[-1].replace("-", " ").strip()
        nuevo_nombre = f"{emoji}｜{self.aplicar_mapeo(nombre_limpio, fuentes[estilo.lower()])}".replace(" ", "-")
        
        try:
            await canal.edit(name=nuevo_nombre)
            await interaction.followup.send(f"🎨 Canal rediseñado: {canal.mention}")
        except discord.HTTPException:
            await interaction.followup.send("❌ No se pudo renombrar el canal. Discord limita el cambio de nombres a 2 veces cada 10 minutos por canal.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al cambiar el nombre del canal: {e}")

    @grupo_fuente.command(name="listar", description="Muestra las tipografías guardadas en el servidor")
    async def listar_fuentes(self, interaction: discord.Interaction):
        if not self.bot.db:
            return await interaction.response.send_message("❌ La base de datos Firebase no está disponible.", ephemeral=True)
        fuentes = self.cargar_fuentes(interaction.guild_id)
        if not fuentes:
            return await interaction.response.send_message("📂 No hay tipografías guardadas.", ephemeral=True)
        embed = discord.Embed(title="🎨 Tipografías Registradas", color=discord.Color.blue())
        for nombre, mapeo in fuentes.items():
            embed.add_field(name=f"📌 {nombre.capitalize()}", value=f"`{self.aplicar_mapeo('Ejemplo', mapeo)}`", inline=False)
        await interaction.response.send_message(embed=embed)

    @grupo_fuente.command(name="probar", description="Genera una vista previa de un texto con una fuente")
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def probar_fuente(self, interaction: discord.Interaction, texto: str, estilo: str, emoji: str = "💬"):
        if not self.bot.db:
            return await interaction.response.send_message("❌ La base de datos Firebase no está disponible.", ephemeral=True)
        fuentes = self.cargar_fuentes(interaction.guild_id)
        if estilo.lower() not in fuentes:
            return await interaction.response.send_message("❌ Fuente inexistente.", ephemeral=True)
        resultado = f"{emoji}｜{self.aplicar_mapeo(texto, fuentes[estilo.lower()])}".replace(" ", "-")
        await interaction.response.send_message(f"👁️ **Vista Previa:** `{resultado}`")

    @grupo_fuente.command(name="eliminar", description="Elimina una fuente del servidor")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.autocomplete(nombre=estilo_autocomplete)
    async def eliminar_fuente_cmd(self, interaction: discord.Interaction, nombre: str):
        if not self.bot.db:
            return await interaction.response.send_message("❌ La base de datos Firebase no me permite conectar.", ephemeral=True)
        if self.eliminar_fuente(interaction.guild_id, nombre):
            await interaction.response.send_message(f"🗑️ Tipografía **{nombre}** eliminada de Firebase.")
        else:
            await interaction.response.send_message(f"❌ No se encontró la fuente **{nombre}**.")

async def setup(bot):
    await bot.add_cog(Fuentes(bot))
