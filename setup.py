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

# Template HTML atualizado com opção de upload
HTML_TEMPLATE = '''
<!doctype html>
<html>
<head>
    <title>Configuração</title>
    <style>
        body { max-width: 800px; margin: 20px auto; padding: 20px; border: 1px solid #ddd; }
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
            <label><input type="radio" name="cloud_service" value="upload" required> Upload de Arquivo</label>

            <h3>Provedor de IA</h3>
            <label><input type="radio" name="ai_provider" value="openai" required> OpenAI</label>
            <label><input type="radio" name="ai_provider" value="huggingface" required> Hugging Face</label>

            <h3>Chaves de API</h3>
            <input type="password" name="api_key" placeholder="Chave API (OpenAI ou Hugging Face)" required>

            <button type="submit">Salvar Configuração</button>
        </form>
    </div>

    {% else %}
    {% if session.cloud_service == 'upload' %}
    <div class="section">
        <h2>Fazer Upload de Arquivo</h2>
        <form action="/upload" method="post" enctype="multipart/form-data">
            <input type="file" name="file" required>
            <button type="submit">Enviar</button>
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

    {% if summary %}
    <div class="section">
        <h2>Resumo do Arquivo</h2>
        <p>{{ summary }}</p>
    </div>
    {% endif %}
    
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

def process_file(content, filename):
    try:
        if filename.endswith('.pdf'):
            reader = PdfReader(BytesIO(content))
            return " ".join([page.extract_text() for page in reader.pages if page.extract_text()])
        elif filename.endswith('.docx'):
            doc = Document(BytesIO(content))
            return " ".join([para.text for para in doc.paragraphs])
        return ""
    except Exception as e:
        print(f"Erro ao processar {filename}: {str(e)}")
        return ""

def generate_summary(text, ai_provider, api_key):
    if ai_provider == "openai":
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "system", "content": "Resuma o seguinte texto:"},
                      {"role": "user", "content": text}]
        )
        return response.choices[0].message.content.strip()
    
    elif ai_provider == "huggingface":
        headers = {"Authorization": f"Bearer {api_key}"}
        data = {"inputs": text}
        response = requests.post("https://api-inference.huggingface.co/models/facebook/bart-large-cnn", headers=headers, json=data)
        
        if response.status_code == 200:
            return response.json()[0]["summary_text"]
        else:
            return "Erro ao gerar resumo com Hugging Face"
    
    return "Resumo não gerado. Provedor de IA desconhecido."

# Rotas
@app.route("/")
def home():
    config = load_config()
    session["configured"] = bool(config.get("api_key"))
    session["cloud_service"] = config.get("cloud_service", "")
    return render_template_string(HTML_TEMPLATE)

@app.route("/configure", methods=["POST"])
def configure():
    config = {
        "cloud_service": request.form.get("cloud_service"),
        "ai_provider": request.form.get("ai_provider"),
        "api_key": request.form.get("api_key")
    }
    save_config(config)
    return redirect("/")

@app.route("/upload", methods=["POST"])
def upload():
    config = load_config()
    if "file" not in request.files:
        return redirect("/")
    
    file = request.files["file"]
    if file.filename == "":
        return redirect("/")
    
    content = file.read()
    text = process_file(content, file.filename)
    
    if text:
        summary = generate_summary(text, config["ai_provider"], config["api_key"])
    else:
        summary = "Erro ao processar o arquivo."

    return render_template_string(HTML_TEMPLATE, summary=summary)

if __name__ == "__main__":
    app.run()
