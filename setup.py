import os
import json
import requests
from flask import Flask, request, redirect, session, render_template_string
from flask_session import Session
from msal import PublicClientApplication
from openai import OpenAI
from io import BytesIO
from PyPDF2 import PdfReader
from docx import Document
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

CONFIG_FILE = "config.json"

# Template HTML atualizado
HTML_TEMPLATE = '''
<!doctype html>
<html>
<head>
    <title>Configuração</title>
    <style>
        body { max-width: 800px; margin: 20px auto; padding: 20px; border: 1px solid #ddd; }
        .section { margin: 20px 0; padding: 20px; }
    </style>
</head>
<body>
    <h1>Configuração Inicial</h1>
    
    {% if not session.configured %}
    <div class="section">
        <h2>Escolha suas configurações</h2>
        <form method="post" action="/configure" enctype="multipart/form-data">
            <h3>Serviço de Armazenamento</h3>
            <label><input type="radio" name="cloud_service" value="onedrive" required> OneDrive</label>
            <label><input type="radio" name="cloud_service" value="googledrive" required> Google Drive</label>
            <label><input type="radio" name="cloud_service" value="upload" required> Anexar Arquivo</label>

            <h3>Provedor de IA</h3>
            <label><input type="radio" name="ai_provider" value="openai" required> OpenAI</label>
            <label><input type="radio" name="ai_provider" value="huggingface" required> Hugging Face</label>

            <h3>Chave de API</h3>
            <input type="password" name="api_key" placeholder="Chave API (OpenAI ou Hugging Face)" required>

            <h3>Anexar Arquivo (se escolhido)</h3>
            <input type="file" name="file">

            <button type="submit">Salvar Configuração</button>
        </form>
    </div>
    {% else %}
    <div class="section">
        <h2>Busca Inteligente</h2>
        <form action="/search" method="get">
            <input type="text" name="query" placeholder="Pesquisar documentos..." style="width: 300px;">
            <button type="submit">Buscar</button>
        </form>
    </div>
    {% endif %}
</body>
</html>
'''

# Helpers
def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except:
        return {"cloud_service": "", "ai_provider": "", "api_key": "", "token": "", "file_content": ""}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

def get_onedrive_client():
    return PublicClientApplication(
        client_id="d17e5e3d-cc13-4059-8eb7-ff1d4b4a8c6b",
        authority="https://login.microsoftonline.com/common"
    )

def get_google_drive_service(token):
    return build("drive", "v3", credentials=token)

def process_file(content, filename):
    try:
        if filename.endswith('.pdf'):
            reader = PdfReader(BytesIO(content))
            return " ".join([page.extract_text() for page in reader.pages])
        elif filename.endswith('.docx'):
            doc = Document(BytesIO(content))
            return " ".join([para.text for para in doc.paragraphs])
        return ""
    except Exception as e:
        print(f"Erro ao processar {filename}: {str(e)}")
        return ""

def generate_summary(text, config):
    if config["ai_provider"] == "openai":
        client = OpenAI(api_key=config["api_key"])
        response = client.Completion.create(
            engine="text-davinci-003",
            prompt="Resuma o seguinte texto:\n\n" + text,
            max_tokens=150
        )
        return response.choices[0].text.strip()

    elif config["ai_provider"] == "huggingface":
        API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
        headers = {"Authorization": f"Bearer {config['api_key']}"}

        payload = {"inputs": text, "parameters": {"max_length": 150, "min_length": 50, "do_sample": False}}
        response = requests.post(API_URL, headers=headers, json=payload)

        if response.status_code == 200:
            return response.json()[0]["summary_text"]
        else:
            return f"Erro na API do Hugging Face: {response.json()}"

    return "Resumo não gerado. Provedor de IA desconhecido."

# Rotas
@app.route("/")
def home():
    config = load_config()
    session["configured"] = bool(config.get("api_key"))
    return render_template_string(HTML_TEMPLATE)

@app.route("/configure", methods=["POST"])
def configure():
    config = load_config()
    config["cloud_service"] = request.form.get("cloud_service")
    config["ai_provider"] = request.form.get("ai_provider")
    config["api_key"] = request.form.get("api_key")

    if config["cloud_service"] == "upload" and "file" in request.files:
        file = request.files["file"]
        if file.filename:
            config["file_content"] = process_file(file.read(), file.filename)

    save_config(config)

    if config["cloud_service"] == "onedrive":
        return redirect("/connect_onedrive")
    elif config["cloud_service"] == "googledrive":
        return redirect("/connect_google")

    return redirect("/")

@app.route("/connect_google")
def connect_google():
    flow = Flow.from_client_secrets_file(
        "client_secret.json",
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
        redirect_uri=request.url_root + "callback_google"
    )
    auth_url, _ = flow.authorization_url(prompt="consent")
    session["google_flow"] = flow
    return redirect(auth_url)

@app.route("/callback_google")
def callback_google():
    flow = session.pop("google_flow", None)
    if not flow:
        return "Erro na autenticação", 400
    flow.fetch_token(code=request.args["code"])
    config = load_config()
    config["token"] = flow.credentials.token
    save_config(config)
    return redirect("/")

@app.route("/summary")
def summary():
    config = load_config()
    if config["cloud_service"] == "upload" and config["file_content"]:
        summary = generate_summary(config["file_content"], config)
        return f"<h1>Resumo:</h1><p>{summary}</p>"
    return "<h1>Nenhum arquivo anexado</h1>"

if __name__ == "__main__":
    app.run(debug=True)
