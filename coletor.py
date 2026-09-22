import json
import os
import random
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# Termo abrangente de emergências em Minas Gerais
TERMO_BUSCA = '"Minas Gerais" (bombeiros OR "defesa civil" OR "polícia rodoviária") (incêndio OR resgate OR salvamento OR acidente OR capotamento OR colisão OR afogamento OR desabamento)'
URL_ENCODED = urllib.parse.quote(TERMO_BUSCA)
FEED_URL = f"https://news.google.com/rss/search?q={URL_ENCODED}&hl=pt-BR&gl=BR&ceid=BR:pt-419"

HEADERS = {'User-Agent': 'Mozilla/5.0'}
ARQUIVO_JSON = "ocorrencias.json"
CACHE_GEO = {}

CIDADES_MG_REFERENCIA = [
    "Francisco Sá", "Montes Claros", "Salinas", "Teófilo Otoni", "Governador Valadares",
    "Ipatinga", "Caratinga", "Manhuaçu", "Coronel Fabriciano", "Belo Horizonte", "Betim",
    "Contagem", "Nova Lima", "Sabará", "Caeté", "Ouro Preto", "Mariana", "Sete Lagoas",
    "Curvelo", "Diamantina", "Juiz de Fora", "Barbacena", "São João del-Rei", "Lavras",
    "Pouso Alegre", "Varginha", "Poços de Caldas", "Alfenas", "Itajubá", "Passos",
    "Divinópolis", "Formiga", "Bom Despacho", "Patos de Minas", "Uberlândia", "Uberaba",
    "Araguari", "Ituiutaba", "Unaí", "Paracatu", "Pirapora", "Januária", "Almenara",
    "Itaobim", "Catuji", "Padre Paraíso", "Ponto dos Volantes", "Capelinha"
]

def classificar_categoria(texto):
    texto_l = texto.lower()
    if any(p in texto_l for p in ["incêndio", "fogo", "chamas", "queimada"]):
        return "incendio", "🔥 Incêndio"
    if any(p in texto_l for p in ["acidente", "colisão", "capotamento", "carreta", "caminhão", "atropelamento", "tombamento"]):
        return "acidente", "🚗 Acidente / Trânsito"
    if any(p in texto_l for p in ["afogamento", "rio", "lagoa", "enchente", "inundação", "tromba d'água"]):
        return "aquatico", "🌊 Emergência Aquática"
    if any(p in texto_l for p in ["ouriço", "cão", "cavalo", "cobra", "serpente", "animal", "tamanduá", "onça"]):
        return "animal", "🐾 Resgate Animal"
    return "geral", "⚠️ Emergência Geral"

def buscar_coordenadas(termo_busca):
    if termo_busca in CACHE_GEO:
        return CACHE_GEO[termo_busca]
    try:
        query = f"{termo_busca}, Minas Gerais, Brasil"
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'MinasAlertaBot/3.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            dados = json.loads(resp.read().decode('utf-8'))
            if dados:
                lat = float(dados[0]['lat'])
                lng = float(dados[0]['lon'])
                CACHE_GEO[termo_busca] = (lat, lng)
                return lat, lng
    except Exception as e:
        print(f"Erro ao geocodificar '{termo_busca}': {e}")
    return None, None

def extrair_detalhes_localizacao(texto):
    texto_limpo = texto.replace("\n", " ")
    match_rodovia = re.search(r'\b(br[-\s]?\d{3}|mg[-\s]?\d{3}|mgc[-\s]?\d{3})\b', texto_limpo, re.IGNORECASE)
    rodovia = match_rodovia.group(0).upper().replace(" ", "-") if match_rodovia else None

    cidade_detectada = None
    for cidade in CIDADES_MG_REFERENCIA:
        padrao = r'\b' + re.escape(cidade) + r'\b'
        if re.search(padrao, texto_limpo, re.IGNORECASE):
            cidade_detectada = cidade
            break

    if not cidade_detectada:
        match_prep = re.search(r'\b(?:em|próximo a|proximo a|altura de|perto de|sentido)\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)*)', texto_limpo)
        if match_prep:
            candidata = match_prep.group(1).strip()
            descartes = ["Minas", "Minas Gerais", "MG", "Carreta", "Caminhão", "Carro", "Pista", "Rodovia"]
            if candidata not in descartes:
                cidade_detectada = candidata

    if rodovia and cidade_detectada:
        return f"{rodovia} • {cidade_detectada}", f"{rodovia}, {cidade_detectada}", cidade_detectada
    elif cidade_detectada:
        return cidade_detectada, cidade_detectada, cidade_detectada
    elif rodovia:
        return f"Trecho {rodovia}", f"{rodovia}, Minas Gerais", None
    return "Minas Gerais", "Belo Horizonte", "Belo Horizonte"

# 1. Carregar histórico anterior (para acumular ocorrências)
historico = []
links_existentes = set()
if os.path.exists(ARQUIVO_JSON):
    try:
        with open(ARQUIVO_JSON, "r", encoding="utf-8") as f:
            historico = json.load(f)
            links_existentes = {item.get("link") for item in historico if "link" in item}
    except Exception as e:
        print(f"Aviso ao ler histórico: {e}")
        historico = []

print(f"Histórico existente: {len(historico)} ocorrências.")

novas_ocorrencias = []
req = urllib.request.Request(FEED_URL, headers=HEADERS)

try:
    with urllib.request.urlopen(req) as resp:
        conteudo = resp.read()

    raiz = ET.fromstring(conteudo)
    itens = raiz.find("channel").findall("item")

    for item in itens:
        titulo = item.find("title").text
        link = item.find("link").text
        descricao = item.find("description").text if item.find("description") is not None else ""
        
        # Ignora se já estiver no histórico
        if link in links_existentes:
            continue

        texto_completo = f"{titulo} {descricao}"
        cat_id, cat_nome = classificar_categoria(texto_completo)
        rotulo, termo_geo, cidade_ancora = extrair_detalhes_localizacao(texto_completo)

        print(f"Geocodificando nova ocorrência: {rotulo} ({termo_geo})...")
        lat, lng = buscar_coordenadas(termo_geo)
        time.sleep(1)

        if (not lat or not lng) and cidade_ancora:
            lat, lng = buscar_coordenadas(cidade_ancora)
            time.sleep(1)

        if not lat or not lng:
            lat, lng = -19.9167, -43.9345

        lat += random.uniform(-0.003, 0.003)
        lng += random.uniform(-0.003, 0.003)

        nova = {
            "id": len(historico) + len(novas_ocorrencias) + 1,
            "titulo": titulo,
            "link": link,
            "local": rotulo,
            "categoria": cat_id,
            "categoria_label": cat_nome,
            "lat": round(lat, 5),
            "lng": round(lng, 5),
            "hora": "Recente"
        }
        novas_ocorrencias.append(nova)
        links_existentes.add(link)

        if len(novas_ocorrencias) >= 10:  # Limite de novos por ciclo para preservar limites de API
            break

    # Combina mantendo as mais recentes primeiro, limitando ao histórico de 100 registros
    dados_finais = (novas_ocorrencias + historico)[:100]

    with open(ARQUIVO_JSON, "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print(f"\nSucesso: {len(novas_ocorrencias)} novas adicionadas. Total no arquivo: {len(dados_finais)}.")

except Exception as erro:
    print(f"Erro no coletor: {erro}")
