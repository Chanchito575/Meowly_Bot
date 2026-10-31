import logging
import os
from html import escape
from threading import Thread

from flask import Flask, Response, jsonify

app = Flask(__name__)

logging.getLogger("werkzeug").setLevel(logging.ERROR)

ENLACE_INVITACION = (
    "https://discord.com/oauth2/authorize?client_id=1562977823340372029"
    "&permissions=93200&integration_type=0&scope=bot+applications.commands"
)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#08070b">
    <meta name="description" content="Meowly: bot de Discord con IA (Groq, Mistral y Qwen), búsqueda web, resúmenes de chat, tipografías para canales y gestión del servidor.">
    <meta property="og:title" content="Meowly Bot">
    <meta property="og:description" content="IA, resúmenes de chat, búsqueda web, tipografías y gestión de canales para tu servidor de Discord.">
    <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%90%B1%3C/text%3E%3C/svg%3E">
    <title>Meowly Bot · Asistente con IA para Discord</title>
    <style>
        :root {
            --bg: #08070b;
            --texto: #f4f4f5;
            --suave: #a1a1aa;
            --borde: rgba(255, 255, 255, 0.09);
            --cristal: rgba(20, 18, 30, 0.62);
            --morado: #a855f7;
            --indigo: #6366f1;
            --rosa: #ec4899;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html { scroll-behavior: smooth; }
        body {
            font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--texto);
            min-height: 100vh;
            padding: 48px 20px 40px;
            overflow-x: hidden;
            -webkit-font-smoothing: antialiased;
        }

        /* Orbes de luz de fondo */
        .orb { position: fixed; border-radius: 50%; filter: blur(100px); pointer-events: none; z-index: 0;
               animation: flotar 9s ease-in-out infinite alternate; }
        .orb-1 { width: 340px; height: 340px; background: var(--morado); top: -8%; left: -8%; opacity: .45; }
        .orb-2 { width: 380px; height: 380px; background: var(--indigo); bottom: -10%; right: -8%; opacity: .4; animation-delay: -4s; }
        .orb-3 { width: 260px; height: 260px; background: var(--rosa); top: 45%; right: 18%; opacity: .22; animation-delay: -2s; }
        @keyframes flotar { from { transform: translate(0, 0) scale(1); } to { transform: translate(30px, 40px) scale(1.12); } }

        .contenedor { position: relative; z-index: 1; max-width: 860px; margin: 0 auto; }

        .cristal {
            background: var(--cristal);
            -webkit-backdrop-filter: blur(22px);
            backdrop-filter: blur(22px);
            border: 1px solid var(--borde);
            border-radius: 24px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, .55), inset 0 1px 0 rgba(255, 255, 255, .08);
        }

        /* Encabezado */
        .hero { text-align: center; padding: 48px 28px 40px; }
        .logo {
            width: 96px; height: 96px; margin: 0 auto 20px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center; font-size: 52px;
            background: linear-gradient(135deg, rgba(168, 85, 247, .22), rgba(99, 102, 241, .22));
            border: 1px solid rgba(168, 85, 247, .45);
            box-shadow: 0 0 36px rgba(168, 85, 247, .35);
        }
        h1 {
            font-size: clamp(2.2rem, 6vw, 3.1rem); font-weight: 800; letter-spacing: -1px; margin-bottom: 12px;
            background: linear-gradient(135deg, #fff 30%, #c084fc 100%);
            -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
        }
        .estado {
            display: inline-flex; align-items: center; gap: 8px; margin-bottom: 20px;
            background: rgba(34, 197, 94, .12); border: 1px solid rgba(34, 197, 94, .32);
            color: #4ade80; padding: 6px 16px; border-radius: 30px; font-size: .82rem; font-weight: 600;
        }
        .punto { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 10px #22c55e;
                 animation: pulso 2s infinite; }
        @keyframes pulso { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .5; transform: scale(1.25); } }
        .lema { color: var(--suave); font-size: 1.05rem; line-height: 1.65; max-width: 560px; margin: 0 auto 30px; }

        .boton {
            display: inline-flex; align-items: center; justify-content: center; gap: 10px;
            background: linear-gradient(135deg, var(--morado), var(--indigo)); color: #fff; text-decoration: none;
            font-weight: 700; font-size: 1.08rem; padding: 16px 34px; border-radius: 16px;
            box-shadow: 0 8px 26px rgba(168, 85, 247, .42); transition: transform .25s ease, box-shadow .25s ease;
        }
        .boton:hover, .boton:focus-visible { transform: translateY(-3px); box-shadow: 0 14px 36px rgba(168, 85, 247, .6); outline: none; }
        .boton:active { transform: translateY(-1px); }
        .nota { margin-top: 14px; font-size: .8rem; color: #71717a; }

        /* Secciones */
        section { margin-top: 22px; padding: 30px 28px; }
        h2 { font-size: 1.15rem; font-weight: 700; margin-bottom: 18px; display: flex; align-items: center; gap: 10px; }
        h2 small { font-weight: 500; color: var(--suave); font-size: .82rem; }

        .rejilla { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }
        .tarjeta {
            background: rgba(255, 255, 255, .035); border: 1px solid rgba(255, 255, 255, .06);
            border-radius: 16px; padding: 18px; transition: border-color .25s ease, transform .25s ease;
        }
        .tarjeta:hover { border-color: rgba(168, 85, 247, .45); transform: translateY(-2px); }
        .tarjeta .icono { font-size: 1.6rem; display: block; margin-bottom: 10px; }
        .tarjeta h3 { font-size: .98rem; font-weight: 650; margin-bottom: 6px; }
        .tarjeta p { color: var(--suave); font-size: .88rem; line-height: 1.55; }

        /* Comandos */
        .comandos { display: grid; gap: 10px; }
        .comando {
            display: flex; gap: 14px; align-items: baseline; flex-wrap: wrap;
            background: rgba(255, 255, 255, .03); border: 1px solid rgba(255, 255, 255, .05);
            border-radius: 12px; padding: 12px 16px;
        }
        code {
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .86rem;
            color: #d8b4fe; background: rgba(168, 85, 247, .12); border-radius: 8px; padding: 3px 9px; white-space: nowrap;
        }
        .comando span { color: var(--suave); font-size: .88rem; flex: 1 1 220px; }

        /* Permisos */
        .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
        .chip { font-size: .8rem; padding: 6px 12px; border-radius: 20px; color: #e4e4e7;
                background: rgba(99, 102, 241, .14); border: 1px solid rgba(99, 102, 241, .32); }
        .aviso { color: var(--suave); font-size: .86rem; line-height: 1.6; }
        .aviso b { color: #e4e4e7; font-weight: 600; }

        footer { text-align: center; color: #52525b; font-size: .8rem; margin-top: 26px; }

        @media (max-width: 520px) {
            body { padding: 28px 14px 30px; }
            .hero { padding: 36px 18px 32px; }
            section { padding: 24px 18px; }
            .boton { width: 100%; }
        }
        @media (prefers-reduced-motion: reduce) {
            .orb, .punto { animation: none; }
            .boton, .tarjeta { transition: none; }
        }
    </style>
</head>
<body>
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="orb orb-3"></div>

    <main class="contenedor">
        <header class="cristal hero">
            <div class="logo" aria-hidden="true">🐱</div>
            <h1>Meowly Bot</h1>
            <div class="estado"><span class="punto"></span> Servidor activo</div>
            <p class="lema">
                Un asistente para Discord que conversa con IA, resume tus chats, busca en la web
                y te ayuda a ordenar y decorar tu servidor.
            </p>
            <a class="boton" href="__ENLACE__" target="_blank" rel="noopener noreferrer">✨ Añadir Meowly a tu servidor</a>
            <p class="nota">Se te pedirá elegir el servidor y confirmar los permisos en Discord.</p>
        </header>

        <section class="cristal" aria-labelledby="t-funciones">
            <h2 id="t-funciones">⚡ ¿Qué puede hacer?</h2>
            <div class="rejilla">
                <article class="tarjeta">
                    <span class="icono">🧠</span>
                    <h3>IA con respaldo automático</h3>
                    <p>Usa Groq, Mistral y Qwen: si una falla, prueba la siguiente. Recuerda tu conversación.</p>
                </article>
                <article class="tarjeta">
                    <span class="icono">🌐</span>
                    <h3>Búsqueda en la web</h3>
                    <p>Consulta DuckDuckGo cuando preguntas por noticias, precios, clima o algo de actualidad.</p>
                </article>
                <article class="tarjeta">
                    <span class="icono">📊</span>
                    <h3>Resúmenes de chat</h3>
                    <p>Resume los últimos mensajes, el día de hoy, una fecha, un rango de horas o a una persona.</p>
                </article>
                <article class="tarjeta">
                    <span class="icono">🎨</span>
                    <h3>Tipografías para canales</h3>
                    <p>Detecta y guarda fuentes especiales (𝗠𝗲𝗼𝘄𝗹𝘆, ᴍᴇᴏᴡʟʏ…) y las aplica a los nombres de tus canales.</p>
                </article>
                <article class="tarjeta">
                    <span class="icono">🛠️</span>
                    <h3>Gestión de canales</h3>
                    <p>Crea, renombra y elimina canales y categorías, siempre con confirmación antes de borrar.</p>
                </article>
                <article class="tarjeta">
                    <span class="icono">🧹</span>
                    <h3>Limpieza de mensajes</h3>
                    <p>Purga mensajes de bots o de todos con un menú seguro. Respeta los mensajes fijados.</p>
                </article>
            </div>
        </section>

        <section class="cristal" aria-labelledby="t-comandos">
            <h2 id="t-comandos">💬 Comandos principales <small>escribe / en Discord</small></h2>
            <div class="comandos">
                <div class="comando"><code>/ia</code><span>Conversa con Meowly y hazle cualquier pregunta.</span></div>
                <div class="comando"><code>/resumen</code><span>Resume la actividad del canal (por mensajes, tiempo, fecha o persona).</span></div>
                <div class="comando"><code>/fuente</code><span>Escanea, guarda y aplica tipografías a canales y categorías.</span></div>
                <div class="comando"><code>/gestionar</code><span>Crea, renombra y elimina canales y categorías.</span></div>
                <div class="comando"><code>/purge</code><span>Elimina mensajes del canal con un menú interactivo.</span></div>
                <div class="comando"><code>/help</code><span>Guía completa: qué hace cada comando y qué permisos necesita.</span></div>
            </div>
        </section>

        <section class="cristal" aria-labelledby="t-permisos">
            <h2 id="t-permisos">🔐 Permisos que solicita</h2>
            <div class="chips">
                <span class="chip">Ver canales</span>
                <span class="chip">Enviar mensajes</span>
                <span class="chip">Insertar enlaces</span>
                <span class="chip">Leer historial de mensajes</span>
                <span class="chip">Gestionar mensajes</span>
                <span class="chip">Gestionar canales</span>
            </div>
            <p class="aviso">
                No pide permisos de administrador, ni de expulsar o banear. Los comandos de gestión solo los puede usar
                quien tenga <b>Gestionar canales</b> o <b>Gestionar mensajes</b> en tu servidor.
            </p>
        </section>

        <footer>Meowly Bot · hecho con 💜 y muchos maullidos</footer>
    </main>
</body>
</html>
"""

PAGINA = HTML_TEMPLATE.replace("__ENLACE__", escape(ENLACE_INVITACION, quote=True))


@app.route("/")
def home():
    return Response(PAGINA, mimetype="text/html")


@app.route("/health")
@app.route("/ping")
def health():
    """Ruta ligera para monitores de uptime y health checks de Render."""
    respuesta = jsonify(status="ok")
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


def run():
    puerto = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=puerto)


def keep_alive():
    Thread(target=run, daemon=True).start()
