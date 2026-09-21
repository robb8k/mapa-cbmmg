import json
import random
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

TERMO_BUSCA = '("bombeiros" OR "CBMMG") "Minas Gerais" (incêndio OR resgate OR salvamento OR acidente OR capotamento OR colisão)'
URL_ENCODED = urllib.parse.quote(TERMO_BUSCA)
FEED_URL = f"https://news.google.com/rss/search?q={URL_ENCODED}&hl=pt-BR&gl=BR&ceid=BR:pt-419"

HEADERS = {'User-Agent': 'Mozilla/5.0'}

CACHE_GEO = {}

# Relação com municípios frequentes em eixos rodoviários e ocorrências de MG
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

def buscar_coordenadas(termo_busca):
    if termo_busca in CACHE_GEO:
        return CACHE_GEO[termo_busca]
        
    try:
        query = f"{termo_busca}, Minas Gerais, Brasil"
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'CBMMGMonitorApp/2.5'})
        
        with urllib.request.urlopen(req, timeout=5) as resp:
            dados = json.loads(resp.read().decode('utf-8'))
            if dados:
                lat = float(dados[0]['lat'])
                lng = float(dados[0]['lon'])
                CACHE_GEO[termo_busca] = (lat, lng)
                return lat, lng
    except Exception as e:
        print(f"Erro na busca de '{termo_busca}': {e}")
        
    return None, None

def extrair_detalhes_localizacao(texto):
    texto_limpo = texto.replace("\n", " ")
    
    # 1. Procura rodovia (BR-xxx, MG-xxx, MGC-xxx)
    match_rodovia = re.search(r'\b(br[-\s]?\d{3}|mg[-\s]?\d{3}|mgc[-\s]?\d{3})\b', texto_limpo, re.IGNORECASE)
    rodovia = match_rodovia.group(0).upper().replace(" ", "-") if match_rodovia else None

    # 2. Varre o texto procurando cidades da lista de referência
    cidade_detectada = None
    for cidade in CIDADES_MG_REFERENCIA:
        padrao = r'\b' + re.escape(cidade) + r'\b'
        if re.search(padrao, texto_limpo, re.IGNORECASE):
            cidade_detectada = cidade
            break

    # 3. Se não achou na lista, tenta capturar por preposição ("em", "próximo a", "altura de", "perto de")
    if not cidade_detectada:
        match_prep = re.search(r'\b(?:em|próximo a|proximo a|altura de|perto de|sentido)\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)*)', texto_limpo)
        if match_prep:
            candidata = match_prep.group(1).strip()
            descartes = ["Minas", "Minas Gerais", "MG", "Carreta", "Caminhão", "Carro", "Pista", "Rodovia"]
            if candidata not in descartes:
                cidade_detectada = candidata

    # Monta estratégia de geocodificação
    if rodovia and cidade_detectada:
        rotulo = f"{rodovia} • {cidade_detectada}"
        termo_geo = f"{rodovia}, {cidade_detectada}"
    elif cidade_detectada:
        rotulo = cidade_detectada
        termo_geo = cidade_detectada
    elif rodovia:
        rotulo = f"Trecho {rodovia}"
        termo_geo = f"{rodovia}, Minas Gerais"
    else:
        rotulo = "Minas Gerais"
        termo_geo = "Belo Horizonte"

    return rotulo, termo_geo, cidade_detectada

print("Iniciando coleta CBMMG com georreferenciamento avançado...\n")

req = urllib.request.Request(FEED_URL, headers=HEADERS)
dados_finais = []

try:
    with urllib.request.urlopen(req) as resp:
        conteudo = resp.read()

    raiz = ET.fromstring(conteudo)
    itens = raiz.find("channel").findall("item")

    for i, item in enumerate(itens[:15], start=1):
        titulo = item.find("title").text
        link = item.find("link").text
        descricao = item.find("description").text if item.find("description") is not None else ""
        
        texto_completo = f"{titulo} {descricao}"
        rotulo, termo_geo, cidade_ancora = extrair_detalhes_localizacao(texto_completo)

        print(f"[{i}] {rotulo} -> consultando '{termo_geo}'...")
        lat, lng = buscar_coordenadas(termo_geo)
        time.sleep(1)

        # Se a busca combinada falhar (ex: rodovia específica dentro do município sem match direto), usa a cidade
        if (not lat or not lng) and cidade_ancora:
            lat, lng = buscar_coordenadas(cidade_ancora)
            time.sleep(1)

        # Fallback para BH caso nada seja encontrado
        if not lat or not lng:
            lat, lng = -19.9167, -43.9345

        # Dispersão sutil (evita sobreposição no exato centróide)
        lat += random.uniform(-0.003, 0.003)
        lng += random.uniform(-0.003, 0.003)

        dados_finais.append({
            "id": i,
            "titulo": titulo,
            "link": link,
            "local": rotulo,
            "lat": round(lat, 5),
            "lng": round(lng, 5),
            "hora": "Recente"
        })

    with open("ocorrencias.json", "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=2)

    print(f"\nSucesso! {len(dados_finais)} ocorrências processadas.")

except Exception as erro:
    print(f"Erro na execução: {erro}")