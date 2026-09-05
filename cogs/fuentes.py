import os
import json
import asyncio
import unicodedata
import discord
from discord import app_commands
from discord.ext import commands
from firebase_admin import firestore
import openai

MODELO_MISTRAL = "mistral-small-latest"
MODELO_QWEN = "Qwen/Qwen2.5-Coder-32B-Instruct"

class Fuentes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Clientes de API persistentes para evitar fugas de RAM y conexiones colgadas
        mistral_key = os.getenv("MISTRAL_API_KEY")
        self.mistral_client = openai.AsyncOpenAI(
            base_url="https://api.mistral.ai/v1/", 
            api_key=mistral_key, 
            timeout=12.0
        ) if mistral_key else None

        hf_key = os.getenv("HF_TOKEN")
        self.hf_client = openai.AsyncOpenAI(
            base_url="https://router.huggingface.co/v1/", 
            api_key=hf_key, 
            timeout=12.0
        ) if hf_key else None

    grupo_fuente = app_commands.Group(name="fuente", description="Gestión de tipografías")
    grupo_escanear = app_commands.Group(name="escanear", description="Escanear y guardar tipografías", parent=grupo_fuente)

    # --- MÉTODOS DE BASE DE DATOS ASÍNCRONOS (NON-BLOCKING) ---

    async def cargar_fuentes(self, guild_id: int) -> dict:
        if not self.bot.db or not guild_id:
            return {}
        
        def _read():
            doc = self.bot.db.collection("servidores").document(str(guild_id)).get()
            if doc and doc.exists:
                return doc.to_dict().get("fuentes", {})
            return {}

        try:
            return await asyncio.to_thread(_read)
        except Exception as e:
            print(f"Error al cargar fuentes de Firestore: {e}")
            return {}

    async def guardar_fuente(self, guild_id: int, nombre: str, mapeo: dict) -> bool:
        if not self.bot.db or not guild_id or not mapeo:
            return False
        
        def _write():
            doc_ref = self.bot.db.collection("servidores").document(str(guild_id))
            # Estructura de merge limpia para Firestore evitando llaves mal compuestas
            doc_ref.set({"fuentes": {nombre.lower(): mapeo}}, merge=True)
            return True

        try:
            return await asyncio.to_thread(_write)
        except Exception as e:
            print(f"Error al guardar fuente en Firestore: {e}")
            return False

    async def eliminar_fuente(self, guild_id: int, nombre: str) -> bool:
        if not self.bot.db or not guild_id:
            return False
        
        def _delete():
            doc_ref = self.bot.db.collection("servidores").document(str(guild_id))
            doc = doc_ref.get()
            if doc.exists and nombre.lower() in doc.to_dict().get("fuentes", {}):
                doc_ref.update({f"fuentes.{nombre.lower()}": firestore.DELETE_FIELD})
                return True
            return False

        try:
            return await asyncio.to_thread(_delete)
        except Exception as e:
            print(f"Error al eliminar fuente en Firestore: {e}")
            return False

    # --- TRANSFORMACIÓN CON RESPALDO DE MAYÚSCULAS/MINÚSCULAS ---

    def aplicar_mapeo(self, texto: str, mapeo: dict) -> str:
        resultado = []
        for char in texto:
            if char in mapeo:
                resultado.append(mapeo[char])
            # Respaldo: si busca minúscula y la fuente solo tiene mayúscula guardada
            elif char.islower() and char.upper() in mapeo:
                resultado.append(mapeo[char.upper()])
            # Respaldo: si busca mayúscula y la fuente solo tiene minúscula
            elif char.isupper() and char.lower() in mapeo:
                resultado.append(mapeo[char.lower()])
            else:
                resultado.append(char)
        return "".join(resultado)

    async def estilo_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []
        
        # Lectura asíncrona para no congelar el autocompletado del cliente
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        opciones = []
        for nombre in fuentes.keys():
            if current.lower() in nombre.lower():
                opciones.append(app_commands.Choice(name=nombre.capitalize(), value=nombre.lower()))
        return opciones[:25]

    # --- EXTRACCIÓN HÍBRIDA DE MAPEO (UNICODEDATA + IA) ---

    async def extraer_mapeo_fuente(self, ejemplo_texto: str) -> dict:
        # 1. Análisis directo instantáneo (0 ms) mediante normalización Unicode
        mapeo_directo = {}
        for char in ejemplo_texto:
            base_char = unicodedata.normalize("NFKD", char)
            if len(base_char) == 1 and base_char != char and base_char.isalnum():
                mapeo_directo[base_char] = char

        if len(mapeo_directo) >= 3:
            return mapeo_directo

        # 2. Si no es un estilo Unicode estándar, se recurre al modelo de IA
        prompt = (
            f"Analiza la tipografía del texto: '{ejemplo_texto}'. Extrae los caracteres especiales "
            "y genera un JSON mapeando cada letra normal con su carácter tipográfico especial.\n"
            "Responde ÚNICAMENTE el JSON sin bloques de código ni explicación adicional.\n"
            'Ejemplo de salida: {"a": "ⓐ", "b": "ⓑ", "A": "Ⓐ"}'
        )

        if self.mistral_client:
            try:
                resp = await self.mistral_client.chat.completions.create(
                    model=MODELO_MISTRAL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=500
                )
                return self._limpiar_json(resp.choices[0].message.content)
            except Exception as e:
                print(f"Mistral falló procesando fuente: {e}")

        if self.hf_client:
            try:
                resp = await self.hf_client.chat.completions.create(
                    model=MODELO_QWEN,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=500
                )
                return self._limpiar_json(resp.choices[0].message.content)
            except Exception as e:
                print(f"Hugging Face falló procesando fuente: {e}")

        if mapeo_directo:
            return mapeo_directo

        raise Exception("No se detectaron caracteres estilizados válidos en la entrada.")

    def _limpiar_json(self, texto: str) -> dict:
        texto_limpio = texto.strip()
        if "```json" in texto_limpio:
            texto_limpio = texto_limpio.split("```json")[1].split("```")[0].strip()
        elif "```" in texto_limpio:
            texto_limpio = texto_limpio.split("```")[1].split("```")[0].strip()
        return json.loads(texto_limpio)

    # --- COMANDOS SLASH ---

    @grupo_escanear.command(name="mensaje", description="Extrae una fuente directamente desde un texto o abecedario")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def escanear_mensaje(self, interaction: discord.Interaction, mensaje: str, nombre_guardar: str):
        await interaction.response.defer()
        if not self.bot.db:
            return await interaction.followup.send("❌ La base de datos Firebase no está disponible.")
        try:
            mapeo = await self.extraer_mapeo_fuente(mensaje)
            if await self.guardar_fuente(interaction.guild_id, nombre_guardar, mapeo):
                await interaction.followup.send(
                    f"🧠 Se analizó el texto (**{len(mapeo)}** caracteres) y se guardó la fuente **{nombre_guardar}** permanentemente."
                )
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
            mapeo = await self.extraer_mapeo_fuente(canal.name)
            if await self.guardar_fuente(interaction.guild_id, nombre_guardar, mapeo):
                await interaction.followup.send(
                    f"🧠 Se analizó {canal.mention} (**{len(mapeo)}** caracteres) y se guardó la fuente **{nombre_guardar}** permanentemente."
                )
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
        
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        if estilo.lower() not in fuentes:
            return await interaction.followup.send(f"❌ Fuente **{estilo}** no encontrada en la base de datos.")
        
        nombre_limpio = canal.name.split("｜")[-1].split("│")[-1].replace("-", " ").strip()
        texto_transformado = self.aplicar_mapeo(nombre_limpio, fuentes[estilo.lower()])
        nuevo_nombre = f"{emoji}｜{texto_transformado}".replace(" ", "-")
        
        try:
            await canal.edit(name=nuevo_nombre)
            await interaction.followup.send(f"🎨 Canal rediseñado: {canal.mention}")
        except discord.HTTPException as e:
            if e.status == 429:
                await interaction.followup.send("⏳ Discord limita el renombrado de un canal a 2 veces cada 10 minutos.")
            else:
                await interaction.followup.send(f"❌ No se pudo renombrar el canal: {e}")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al cambiar el nombre del canal: {e}")

    @grupo_fuente.command(name="listar", description="Muestra las tipografías guardadas en el servidor")
    async def listar_fuentes(self, interaction: discord.Interaction):
        if not self.bot.db:
            return await interaction.response.send_message("❌ La base de datos Firebase no está disponible.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        fuentes = await self.cargar_fuentes(interaction.guild_id)
        
        if not fuentes:
            return await interaction.followup.send("📂 No hay tipografías guardadas en este servidor.", ephemeral=True)
        
        embed = discord.Embed(title="🎨 Tipografías Registradas", color=discord.Color.blue())
        for nombre, mapeo in fuentes.items():
            ejemplo_preview = self.aplicar_mapeo("Ejemplo", mapeo)
            embed.add_field(name=f"📌 {nombre.capitalize()}", value=f"`{ejemplo_preview}` ({len(mapeo)} caracteres)", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @grupo_fuente.command(name="probar", description="Genera una vista previa de un texto con una fuente")
    @app_commands.autocomplete(estilo=estilo_autocomplete)
    async def probar_fuente(self, interaction: discord.Interaction, texto: str, estilo: str, emoji: str = "💬"):
        if not self.bot.db:
            return await interaction.response.send_message("❌ La base de datos Firebase no está disponible.", ephemeral=True)
        
        fuentes = await self.cargar_fuentes(interaction.guild_id)
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
        
        if await self.eliminar_fuente(interaction.guild_id, nombre):
            await interaction.response.send_message(f"🗑️ Tipografía **{nombre}** eliminada de Firebase.")
        else:
            await interaction.response.send_message(f"❌ No se encontró la fuente **{nombre}**.")

async def setup(bot):
    await bot.add_cog(Fuentes(bot))
