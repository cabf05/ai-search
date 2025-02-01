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
        body { max-width: 800px; margin: 20px auto; padding: 20px; }
        .section { margin: 20px 0; padding: 20px; border: 1px solid #ddd; }
    </style>
</head>
<body>
    <h1>Configuração Inicial</h1>
    
    {% if not session.configured %}
    <div class="section">
        <h2>Escolha suas configurações</h2>
        <form method="post" action="/configure">
            <h3>Serviço de Armazenamento</h3>
            <label><input type="radio" name="cloud_service" value="onedrive" required> OneDrive</label>
            <label><input type="radio" name="cloud_service" value="googledrive" required> Google Drive</label>

            <h3>Provedor de IA</h3>
            <label><input type="radio" name="ai_provider" value="openai" required> OpenAI</label>
            <label><input type="radio" name="ai_provider" value="huggingface" required> Hugging Face</label>

            <h3>Chaves de API</h3>
            <input type="password" name="api_key" placeholder="Chave API (OpenAI ou Hugging Face)" required>

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
        
        {% if results %}
        <h3>Resultados:</h3>
        <ul>
            {% for result in results %}
            <li>{{ result.name }}<br>
                <small>Confiança: {{ "%.0f"|format(result.score*100) }}%</small>
            </li>
            {% endfor %}
        </ul>
        {% endif %}
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
        return {"cloud_service": "", "ai_provider": "", "api_key": "", "token": ""}

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

# Rotas
@app.route("/")
def home():
    config = load_config()
    session["configured"] = bool(config.get("api_key") and config.get("token"))
    return render_template_string(HTML_TEMPLATE, results=request.args.get("results"))

@app.route("/configure", methods=["POST"])
def configure():
    config = load_config()
    config["cloud_service"] = request.form.get("cloud_service")
    config["ai_provider"] = request.form.get("ai_provider")
    config["api_key"] = request.form.get("api_key")
    save_config(config)

    if config["cloud_service"] == "onedrive":
        return redirect("/connect_onedrive")
    elif config["cloud_service"] == "googledrive":
        return redirect("/connect_google")

    return redirect("/")

@app.route("/connect_onedrive")
def connect_onedrive():
    msal = get_onedrive_client()
    auth_url = msal.get_authorization_request_url(
        scopes=["Files.Read.All"],
        redirect_uri=request.url_root + "callback_onedrive"
    )
    return redirect(auth_url)

@app.route("/callback_onedrive")
def callback_onedrive():
    msal = get_onedrive_client()
    result = msal.acquire_token_by_authorization_code(
        code=request.args["code"],
        scopes=["Files.Read.All"],
        redirect_uri=request.url_root + "callback_onedrive"
    )
    config = load_config()
    config["token"] = result.get("access_token")
    save_config(config)
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

@app.route("/search")
def search():
    config = load_config()
    documents = []

    if config["cloud_service"] == "onedrive":
        headers = {"Authorization": f"Bearer {config['token']}"}
        files = requests.get(
            "https://graph.microsoft.com/v1.0/me/drive/root/search(q='')",
            headers=headers
        ).json().get("value", [])

    elif config["cloud_service"] == "googledrive":
        service = get_google_drive_service(config["token"])
        results = service.files().list(q="mimeType='application/pdf' or mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'").execute()
        files = results.get("files", [])

    for file in files[:50]:
        content = requests.get(file["@microsoft.graph.downloadUrl"]).content
        text = process_file(content, file["name"])
        documents.append({"name": file["name"], "content": text})

    query = request.args.get("query")

    if config["ai_provider"] == "openai":
        client = OpenAI(api_key=config["api_key"])
        embeddings = client.embeddings.create(input=[doc["content"] for doc in documents] + [query], model="text-embedding-3-small")
    else:
        embeddings = []  # Implementar Hugging Face

    return render_template_string(HTML_TEMPLATE, results=documents[:5])

if __name__ == "__main__":
    app.run()
