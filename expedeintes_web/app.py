from flask import Flask, render_template_string, request, redirect, url_for
import pandas as pd
import os
from datetime import datetime
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import qrcode
from io import BytesIO
import base64

app = Flask(__name__)

# Archivo Excel
RUTA_EXCEL = "registrodatos.xlsx"

# Crear Excel vacío si no existe
if not os.path.exists(RUTA_EXCEL):
    df_vacio = pd.DataFrame(columns=["Matricula", "Nombre", "Nota"])
    df_vacio.to_excel(RUTA_EXCEL, index=False)

# Configuración de tokens para QR
SECRET_KEY = os.environ.get("SECRET_KEY", "clave_super_secreta_cambiar_en_produccion")
s = URLSafeTimedSerializer(SECRET_KEY)

# Tiempo MUY largo (token no expira en hosting gratuito)
TOKEN_MAX_AGE = 999999999

# HTML de búsqueda de expediente
BUSCAR_HTML = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Búsqueda de Expediente</title>
<style>
body { font-family: Arial; background-color: #f4f4f4; padding: 20px; }
form { background: white; padding: 20px; border-radius: 10px; width: 400px; margin: auto; }
input, textarea { width: 100%; padding: 10px; margin: 5px 0; }
button { background: #007bff; color: white; padding: 10px; border: none; border-radius: 5px; cursor: pointer; }
button:hover { background: #0056b3; }
table { border-collapse: collapse; margin-top: 20px; width: 100%; background: white; }
th, td { border: 1px solid #ccc; padding: 8px; text-align: center; }
.note-form { background: #e9ecef; padding: 10px; border-radius: 8px; margin-top: 10px; }
pre { background: #fff; padding: 10px; border-radius: 6px; white-space: pre-wrap; }
h2 { text-align: center; }
</style>
</head>
<body>
<h2>📘 Búsqueda y Actualización de Expediente</h2>
<form method="POST">
    <label>Matrícula:</label>
    <input type="text" name="matricula" placeholder="Ej. A12345">
    <label>Nombre:</label>
    <input type="text" name="nombre" placeholder="Ej. Juan Pérez">
    <button type="submit">Buscar</button>
</form>

{% if resultados is not none %}
    {% if resultados.empty %}
        <p align="center"><b>No se encontró ningún registro.</b></p>
    {% else %}
        <table>
            <tr>{% for col in resultados.columns %}<th>{{ col }}</th>{% endfor %}<th>QR</th></tr>
            {% for _, fila in resultados.iterrows() %}
            <tr>
                {% for valor in fila %}<td><pre>{{ valor }}</pre></td>{% endfor %}
                <td><a href="{{ url_for('generar_qr', matricula=fila['Matricula'], nombre=fila['Nombre']) }}" target="_blank">Generar QR</a></td>
            </tr>
            {% endfor %}
        </table>

        <div class="note-form">
            <form method="POST" action="{{ url_for('agregar_nota') }}">
                <h4>📝 Agregar nueva nota</h4>
                <input type="hidden" name="matricula" value="{{ resultados.iloc[0]['Matricula'] }}">
                <label>Autor de la nota:</label>
                <input type="text" name="autor" placeholder="Ej. Prof. Ramírez" required>
                <label>Contenido de la nota:</label>
                <textarea name="nota" rows="3" placeholder="Escribe la nueva nota aquí..." required></textarea>
                <button type="submit">Añadir Nota</button>
            </form>
        </div>
    {% endif %}
{% endif %}
</body>
</html>
"""

# HTML para mostrar el QR
QR_HTML = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>QR de Acceso</title>
<style>body{text-align:center;font-family:Arial;background:#f4f4f4;padding:20px;} img{margin:20px 0;}</style>
</head>
<body>
<h3>QR de acceso para {{ matricula }} {{ nombre }}</h3>
<img src="data:image/png;base64,{{ img_b64 }}">
<p>URL: <a href="{{ url }}">{{ url }}</a></p>
</body>
</html>
"""

@app.route("/")
def inicio():
    return redirect(url_for("buscar"))

# Página de búsqueda / expediente
@app.route("/buscar", methods=["GET", "POST"])
def buscar():
    resultados = None

    matricula_prefill = request.args.get("matricula", "").strip()

    if request.method == "POST" or matricula_prefill:
        matricula = matricula_prefill.lower() if matricula_prefill else request.form.get("matricula", "").strip().lower()
        nombre = request.form.get("nombre", "").strip().lower() if request.method == "POST" else ""

        df = pd.read_excel(RUTA_EXCEL)
        df.columns = [c.strip() for c in df.columns]

        filtro = pd.Series([True] * len(df))
        if matricula:
            filtro &= df["Matricula"].astype(str).str.lower().str.contains(matricula)
        if nombre:
            filtro &= df["Nombre"].astype(str).str.lower().str.contains(nombre)

        resultados = df[filtro]

    return render_template_string(BUSCAR_HTML, resultados=resultados)

# Agregar nota
@app.route("/agregar_nota", methods=["POST"])
def agregar_nota():
    matricula = request.form.get("matricula")
    autor = request.form.get("autor", "").strip()
    nueva_nota = request.form.get("nota", "").strip()

    if not nueva_nota or not autor:
        return "❌ Debes escribir una nota y un autor."

    df = pd.read_excel(RUTA_EXCEL)

    if "Nota" not in df.columns:
        df["Nota"] = ""

    indice = df.index[df["Matricula"].astype(str) == matricula].tolist()

    if not indice:
        return "❌ No se encontró la matrícula en el archivo."

    i = indice[0]

    fecha = datetime.now().strftime("[%Y-%m-%d %H:%M]")
    nota_anterior = str(df.loc[i, "Nota"]) if pd.notna(df.loc[i, "Nota"]) else ""
    nueva_linea = f"{fecha} ({autor}): {nueva_nota}"

    df.loc[i, "Nota"] = (nota_anterior.strip() + "\n" + nueva_linea) if nota_anterior.strip() else nueva_linea

    df.to_excel(RUTA_EXCEL, index=False)

    return redirect(url_for("buscar"))

# Generar QR con matrícula y nombre
@app.route("/generar_qr")
def generar_qr():
    matricula = request.args.get("matricula", "").strip()
    nombre = request.args.get("nombre", "").strip()

    if not matricula:
        return "Falta matrícula", 400

    payload = {"matricula": matricula, "nombre": nombre}
    token = s.dumps(payload)

    url = url_for("autologin", token=token, _external=True)

    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image()

    buffer = BytesIO()
    img.save(buffer, format="PNG")

    img_b64 = base64.b64encode(buffer.getvalue()).decode()

    return render_template_string(QR_HTML, img_b64=img_b64, url=url, matricula=matricula, nombre=nombre)

# Autologin usando token del QR
@app.route("/autologin")
def autologin():
    token = request.args.get("token", "")

    if not token:
        return "Token no proporcionado.", 400

    try:
        payload = s.loads(token, max_age=TOKEN_MAX_AGE)
        matricula = payload.get("matricula", "")
        return redirect(url_for("buscar", matricula=matricula))
    except BadSignature:
        return "<h3>Token inválido.</h3>"

# *** IMPORTANTE PARA SERVIDORES ***
def create_app():
    return app

# Ejecutar localmente
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
