import os
import sys
import json
import base64
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    firebase_admin = None
    print("⚠️ firebase-admin no está instalado. El bot funcionará sin base de datos.")

def limpiar_env(valor):
    """Quita espacios, saltos de línea y comillas que se cuelan al pegar variables en Render."""
    if valor is None:
        return None
    valor = valor.strip().strip('"').strip("'").strip()
    return valor or None


def leer_entero_env(nombre, defecto):
    valor = limpiar_env(os.getenv(nombre))
    if valor is None:
        return defecto
    try:
        return int(valor)
    except ValueError:
        print(f"⚠️ {nombre} no es un número válido ('{valor}'). Se usa el valor por defecto.")
        return defecto


MI_DISCORD_ID = leer_entero_env("OWNER_ID", 1481047586457518141)

CLAVES_IA = {
    "Groq": ("GROQ_API_KEY", "GROQ_KEY"),
    "Mistral": ("MISTRAL_API_KEY", "MISTRAL_KEY"),
    "Qwen (HF)": ("HF_TOKEN", "HUGGINGFACE_API_KEY", "HF_API_KEY", "QWEN_API_KEY"),
}


def mostrar_estado_claves():
    partes = []
    for nombre, variables in CLAVES_IA.items():
        hay = any(limpiar_env(os.getenv(v)) for v in variables)
        partes.append(f"{nombre} {'✅' if hay else '❌'}")
    print("🔑 Llaves de IA detectadas: " + " | ".join(partes))

def conectar_firebase():
    if firebase_admin is None:
        return None

    b64_credentials = limpiar_env(os.getenv("FIREBASE_CREDENTIALS_BASE64"))
    if not b64_credentials:
        print("⚠️ Advertencia: No se encontró FIREBASE_CREDENTIALS_BASE64.")
        return None

    try:
        b64_credentials += "=" * (-len(b64_credentials) % 4)  
        decoded_json = base64.b64decode(b64_credentials).decode("utf-8")
        cred_dict = json.loads(decoded_json)

        if isinstance(cred_dict.get("private_key"), str):
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")

        cred = credentials.Certificate(cred_dict)

        if not firebase_admin._apps:
            app = firebase_admin.initialize_app(cred)
        else:
            app = firebase_admin.get_app()

        cliente = firestore.client(app=app)
        print("🔥 Firebase Firestore conectado con éxito.")
        return cliente
    except Exception as e:
        print(f"❌ Error al conectar con Firebase: {type(e).__name__}: {e}")
        return None


db = conectar_firebase()

intents = discord.Intents.default()
intents.message_content = True
intents.members = limpiar_env(os.getenv("INTENT_MEMBERS")) == "1"

class MiBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=".",
            intents=intents,
            help_command=None,
            owner_id=MI_DISCORD_ID,  
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=True
            ),
        )
        self.db = db
        self.owner_id_custom = MI_DISCORD_ID
        self.cogs_cargados = []
        self.cogs_fallidos = []

    async def setup_hook(self):
        carpeta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cogs")

        if os.path.isdir(carpeta):
            for filename in sorted(os.listdir(carpeta)):
                if (
                    not filename.endswith(".py")
                    or filename.startswith("_")
                    or filename.endswith("_2.py")
                ):
                    continue
                nombre = filename[:-3]
                try:
                    await self.load_extension(f"cogs.{nombre}")
                    self.cogs_cargados.append(nombre)
                    print(f"📦 Cog cargado: {nombre}")
                except Exception as e:
                    self.cogs_fallidos.append(nombre)
                    print(f"❌ Error al cargar el cog {filename}: {type(e).__name__}: {e}")
                    traceback.print_exc()
        else:
            print("❌ No se encontró la carpeta 'cogs'.")

        if self.cogs_fallidos:
            print(f"⚠️ Cogs con error: {', '.join(self.cogs_fallidos)}")

        try:
            synced = await self.tree.sync()
            print(f"🔁 {len(synced)} comandos Slash sincronizados.")
        except Exception as e:
            print(f"❌ Error al sincronizar comandos Slash: {type(e).__name__}: {e}")

bot = MiBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = error.original if isinstance(error, app_commands.CommandInvokeError) else error

    if isinstance(error, app_commands.MissingPermissions):
        faltan = ", ".join(p.replace("_", " ") for p in error.missing_permissions)
        msg = f"❌ No tienes los permisos requeridos para ejecutar este comando ({faltan})."
    elif isinstance(error, app_commands.BotMissingPermissions):
        faltan = ", ".join(p.replace("_", " ") for p in error.missing_permissions)
        msg = f"❌ El bot no tiene permisos suficientes en este canal/servidor ({faltan})."
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "❌ Este comando solo se puede usar dentro de un servidor."
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ Espera {error.retry_after:.1f}s antes de volver a usar este comando."
    elif isinstance(error, app_commands.CheckFailure):
        msg = "❌ No tienes autorización para usar este comando."
    elif isinstance(original, discord.Forbidden):
        msg = (
            "❌ Discord no me dejó hacer eso: revisa que el rol del bot tenga los permisos "
            "necesarios y esté por encima de los roles/canales involucrados."
        )
        print(f"⚠️ Forbidden en '{interaction.command.name if interaction.command else '?'}': {original}")
    else:
        msg = "❌ Ocurrió un error inesperado al procesar el comando."
        nombre = interaction.command.name if interaction.command else "desconocido"
        print(f"⚠️ Error en comando '{nombre}': {type(original).__name__}: {original}")
        traceback.print_exception(type(original), original, original.__traceback__)

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException as e:
        print(f"⚠️ No se pudo enviar el mensaje de error: {e}")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"⚠️ Error en comando de prefijo: {type(error).__name__}: {error}")

@bot.event
async def on_ready():
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game(name="/ia | Sistema seguro"),
    )
    print(f"✅ Bot conectado con éxito como {bot.user} en {len(bot.guilds)} servidor(es)")
    print(f"👑 Propietario configurado (ID): {bot.owner_id_custom}")
    print(f"🗄️ Base de datos: {'conectada' if bot.db else 'NO disponible'}")
    mostrar_estado_claves()

def main():
    token = limpiar_env(os.getenv("DISCORD_TOKEN"))
    if not token:
        print("❌ Error crítico: La variable DISCORD_TOKEN no está configurada.")
        sys.exit(1)

    keep_alive()

    codigo_salida = 0
    try:
        bot.run(token)
    except discord.PrivilegedIntentsRequired:
        print("❌ Faltan intents privilegiados. Activa 'Message Content Intent' en "
              "discord.com/developers > tu app > Bot.")
        codigo_salida = 1
    except discord.LoginFailure:
        print("❌ DISCORD_TOKEN inválido. Genera uno nuevo en Developer Portal > Bot > Reset Token.")
        codigo_salida = 1
    except Exception as e:
        print(f"❌ El bot se detuvo por un error: {type(e).__name__}: {e}")
        traceback.print_exc()
        codigo_salida = 1

    os._exit(codigo_salida)


if __name__ == "__main__":
    main()
