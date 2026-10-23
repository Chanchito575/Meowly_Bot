from flask import Flask
from threading import Thread

app = Flask('')

ENLACE_INVITACION = "https://discord.com/oauth2/authorize?client_id=1533280031672107028&permissions=2264411382103287&integration_type=0&scope=bot+applications.commands"

HTML_TEMPLATE = f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Meowly Bot - Servidor Web</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
        }}
        body {{
            background-color: #08070b;
            color: #ffffff;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
            overflow: hidden;
            position: relative;
        }}
        
        /* 🌟 ORBES DE LUZ ANIMADOS EN EL FONDO */
        .orb {{
            position: absolute;
            border-radius: 50%;
            filter: blur(90px);
            opacity: 0.5;
            animation: float 8s ease-in-out infinite alternate;
        }}
        .orb-1 {{
            width: 320px;
            height: 320px;
            background: #a855f7;
            top: -10%;
            left: -10%;
        }}
        .orb-2 {{
            width: 350px;
            height: 350px;
            background: #6366f1;
            bottom: -10%;
            right: -10%;
            animation-delay: -4s;
        }}
        .orb-3 {{
            width: 250px;
            height: 250px;
            background: #ec4899;
            top: 40%;
            right: 20%;
            opacity: 0.3;
            animation-delay: -2s;
        }}

        @keyframes float {{
            0% {{ transform: translate(0, 0) scale(1); }}
            100% {{ transform: translate(30px, 40px) scale(1.1); }}
        }}

        /* 🔮 TARJETA CON EFECTO CRISTAL (GLASSMORPHISM) */
        .card {{
            position: relative;
            z-index: 10;
            background: rgba(18, 16, 26, 0.65);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 24px;
            padding: 45px 35px;
            max-width: 460px;
            width: 100%;
            text-align: center;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6),
                        inset 0 1px 0 rgba(255, 255, 255, 0.1);
        }}

        /* 🐱 LOGO CON GLOW Y PULSO */
        .avatar-wrapper {{
            position: relative;
            width: 90px;
            height: 90px;
            margin: 0 auto 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, rgba(168, 85, 247, 0.2), rgba(99, 102, 241, 0.2));
            border: 1px solid rgba(168, 85, 247, 0.4);
            border-radius: 50%;
            font-size: 48px;
            box-shadow: 0 0 30px rgba(168, 85, 247, 0.3);
        }}

        h1 {{
            font-size: 2.3rem;
            font-weight: 800;
            background: linear-gradient(135deg, #ffffff 30%, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
            letter-spacing: -0.5px;
        }}

        /* 🟢 BADGE DE ESTADO CON PULSO */
        .status-badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(34, 197, 94, 0.12);
            border: 1px solid rgba(34, 197, 94, 0.3);
            color: #4ade80;
            padding: 6px 16px;
            border-radius: 30px;
            font-size: 0.82rem;
            font-weight: 600;
            margin-bottom: 22px;
        }}
        .status-dot {{
            width: 8px;
            height: 8px;
            background-color: #22c55e;
            border-radius: 50%;
            box-shadow: 0 0 10px #22c55e;
            animation: pulse 2s infinite;
        }}

        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.5; transform: scale(1.2); }}
        }}

        p {{
            color: #a1a1aa;
            font-size: 0.95rem;
            line-height: 1.6;
            margin-bottom: 28px;
        }}

        /* 🚀 BOTÓN SHINY / GLOW */
        .btn {{
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            width: 100%;
            background: linear-gradient(135deg, #a855f7, #6366f1);
            color: #ffffff;
            text-decoration: none;
            font-weight: 700;
            padding: 16px;
            border-radius: 14px;
            font-size: 1.05rem;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 8px 25px rgba(168, 85, 247, 0.4);
            overflow: hidden;
        }}
        .btn:hover {{
            transform: translateY(-3px);
            box-shadow: 0 12px 35px rgba(168, 85, 247, 0.6);
        }}

        /* 🛠️ CONTENEDOR DE CARACTERÍSTICAS */
        .features {{
            margin-top: 30px;
            padding-top: 22px;
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .feature-box {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.05);
            padding: 12px 16px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 0.88rem;
            color: #e4e4e7;
            text-align: left;
        }}
        .feature-icon {{
            font-size: 1.2rem;
        }}
    </style>
</head>
<body>
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="orb orb-3"></div>

    <div class="card">
        <div class="avatar-wrapper">
            🐱
        </div>
        <h1>Meowly Bot</h1>
        <div class="status-badge">
            <div class="status-dot"></div> Sistema Activo
        </div>
        <p>Asistente virtual avanzado para Discord impulsado por Ensamble de IA, resúmenes de chat y búsquedas web en tiempo real.</p>
        
        <a href="{ENLACE_INVITACION}" target="_blank" class="btn">
            <span>✨ Añadir a Discord</span>
        </a>

        <div class="features">
            <div class="feature-box">
                <span class="feature-icon">🧠</span>
                <span>Ensamble IA (Qwen + Mistral + Llama)</span>
            </div>
            <div class="feature-box">
                <span class="feature-icon">📊</span>
                <span>Resúmenes inteligentes de chat</span>
            </div>
            <div class="feature-box">
                <span class="feature-icon">🌐</span>
                <span>Búsqueda en vivo con DuckDuckGo</span>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    return HTML_TEMPLATE

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
