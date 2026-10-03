# ============================================================
# SCRAPER DE PESQUISAS ELEITORAIS - WIKIPÉDIA
# Projeto Eleições 2026
#
# O que este script faz:
#   1. Baixa a página da Wikipédia com as pesquisas de 2026
#   2. Extrai as tabelas de "Primeiro turno" dos meses de 2026
#      (e, se INCLUIR_SEGUNDO_TURNO = True, as de "Segundo turno")
#   3. Transforma tudo em formato longo (1 linha = 1 candidato
#      em 1 cenário de 1 pesquisa)
#   4. Valida os dados e salva um CSV local (utf-8, sem BOM)
#   5. (Opcional) Envia o CSV para o S3, particionado por
#      data de coleta
# ============================================================

from io import StringIO
from pathlib import Path
from datetime import datetime, timezone, date
import hashlib
import re

import pandas as pd
import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURAÇÕES
# ============================================================

# Página da Wikipédia usada como fonte
URL = (
    "https://pt.wikipedia.org/wiki/"
    "Pesquisas_de_opini%C3%A3o_para_a_elei%C3%A7%C3%A3o_presidencial_no_Brasil_em_2026"
)

# Identificação educada do nosso script para a Wikipédia
HEADERS = {
    "User-Agent": (
        "projeto-eleicoes-2026/1.0 "
        "(uso educacional/portfolio pessoal)"
    )
}

# Pasta e nome do arquivo de saída local
OUT_DIR = Path("dados_processados")
OUT_DIR.mkdir(exist_ok=True)
ARQUIVO_SAIDA = OUT_DIR / "pesquisa_eleitoral_2026_raw.csv"

# Configuração do S3
# Deixe ENVIAR_PARA_S3 = False para apenas gerar o CSV local
ENVIAR_PARA_S3 = True
BUCKET = "joaopedro-eleicoes2026-raw"

# Escopo da coleta
# False = só as pesquisas de PRIMEIRO turno (padrão)
# True  = inclui também as simulações de SEGUNDO turno
INCLUIR_SEGUNDO_TURNO = False

# Nomes das partições do S3 (ano=..., data_coleta=...).
# Nenhuma coluna do CSV pode usar esses nomes
COLUNAS_RESERVADAS_PARTICAO = {"ano", "data_coleta"}


# ============================================================
# ESCOPO
# Títulos h4 da Wikipédia que correspondem aos meses de 2026
# ============================================================

MESES_2026 = {
    "Outubro",
    "Setembro",
    "Agosto",
    "Julho",
    "Junho",
    "Maio",
    "Abril",
    "Março",
    "Janeiro - Fevereiro",
}


# ============================================================
# COLUNAS QUE NÃO SÃO CANDIDATOS
# "vantagem" / "lead" / "diferença" são a diferença entre 1º e
# 2º colocado e NÃO podem virar candidato
# ============================================================

COLUNAS_NAO_CANDIDATO = {
    "outros",
    "indecisos",
    "indecisos e ausentes",
    "indecisos e absentos",
    "brancos",
    "nulos",
    "brancos/nulos",
    "não sabe",
    "não respondeu",
    "nenhum",
    "nenhuma",
    "vantagem",
    "lead",
    "diferença",
}


# ============================================================
# PARTIDOS (nome como aparece na Wikipédia -> nome padronizado)
# ============================================================

PARTIDOS_CANONICOS = {
    "AGIR": "AGIR",
    "AVANTE": "AVANTE",
    "CIDADANIA": "CIDADANIA",
    "DC": "DC",
    "DEMOCRACIA CRISTÃ": "DC",
    "DEMOCRATA": "DEMOCRATA",
    "MDB": "MDB",
    "MISSÃO": "MISSÃO",
    "MOBILIZA": "MOBILIZA",
    "NOVO": "NOVO",
    "PCB": "PCB",
    "PCDOB": "PCdoB",
    "PCdoB": "PCdoB",
    "PDT": "PDT",
    "PL": "PL",
    "PMB": "PMB",
    "PMN": "PMN",
    "PODE": "PODE",
    "PP": "PP",
    "PCO": "PCO",
    "PRD": "PRD",
    "PRTB": "PRTB",
    "PSB": "PSB",
    "PSC": "PSC",
    "PSD": "PSD",
    "PSDB": "PSDB",
    "PSOL": "PSOL",
    "PSTU": "PSTU",
    "PT": "PT",
    "PV": "PV",
    "REDE": "REDE",
    "REPUBLICANOS": "REPUBLICANOS",
    "SOLIDARIEDADE": "SOLIDARIEDADE",
    "UNIÃO": "UNIÃO",
    "UNIÃO BRASIL": "UNIÃO",
    "UP": "UP",
}


# ============================================================
# PADRONIZAÇÃO DOS CONTRATANTES (chave em minúsculas)
# ============================================================

PADRONIZACAO_CONTRATANTES = {
    "datafolha": "Datafolha",
    "data folha": "Datafolha",
    "atlasintel": "AtlasIntel",
    "atlasinstel": "AtlasIntel",
    "quaest": "Quaest",
    "futura": "Futura",
    "apex/futura": "Apex/Futura",
    "futura/apex": "Apex/Futura",
    "vox": "Vox Brasil",
    "vox brasil": "Vox Brasil",
    "nexus/btg": "Nexus/BTG",
    "nexus/btg pactual": "Nexus/BTG",
    "veritá": "Veritá",
    "gerp": "Gerp",
    "indexa": "Indexa",
    "indexa/broadcast": "Indexa/Broadcast",
    "paraná pesquisas": "Paraná Pesquisas",
    "poderdata/aya": "PoderData/Aya",
    "real time big data": "Real Time Big Data",
    "cnt/mda": "CNT/MDA",
    "genial/quaest": "Genial/Quaest",
    "meio/ideia": "Meio/Ideia",
    "vetor/arrow": "Vetor/Arrow",
    "alfa inteligência": "Alfa Inteligência",
    "alfa/tmc": "Alfa/TMC",
    "american analytics": "American Analytics",
    "data povo": "Data Povo",
    "datatrends": "DataTrends",
    "palver": "Palver",
}


# ============================================================
# DOWNLOAD
# ============================================================

def baixar_html() -> str:
    """Baixa o HTML da página da Wikipédia."""
    resposta = requests.get(URL, headers=HEADERS, timeout=30)
    resposta.raise_for_status()
    return resposta.text


# ============================================================
# LIMPEZA DE TEXTO
# ============================================================

def limpar_texto(valor) -> str:
    """Remove notas de rodapé [1], espaços duplicados e nulos."""
    if pd.isna(valor):
        return ""

    texto = str(valor).strip()
    texto = re.sub(r"\[[^\]]+\]", "", texto)
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


# ============================================================
# LIMPEZA DE NÚMEROS
# ============================================================

def limpar_numero(valor):
    """
    Converte textos como '47,5%' ou '2 004' em float.
    Retorna None quando não for possível converter.
    """
    if pd.isna(valor):
        return None

    texto = str(valor).strip()

    if texto.lower() in {"", "-", "—", "nan", "n/a", "não informado"}:
        return None

    texto = (
        texto
        .replace("%", "")
        .replace("\xa0", "")
        .replace(" ", "")
    )

    # Formato brasileiro: 1.234,5 -> 1234.5
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")

    try:
        return float(texto)
    except (ValueError, TypeError):
        return None


# ============================================================
# EXTRAÇÃO DAS TABELAS (guardando os títulos h2/h3/h4)
# ============================================================

def extrair_tabelas_com_contexto(html: str):
    """
    Percorre a página em ordem e devolve uma lista de
    (contexto, tabela), onde contexto guarda o h2/h3/h4 em que
    cada tabela está (ex.: h2='Primeiro turno', h4='Agosto').
    """
    soup = BeautifulSoup(html, "lxml")

    contexto = {"h2": None, "h3": None, "h4": None}
    resultado = []

    elementos = soup.find_all(["h2", "h3", "h4", "table"])

    for elemento in elementos:

        # Atualiza o contexto atual quando encontra um título
        if elemento.name in {"h2", "h3", "h4"}:
            texto = limpar_texto(elemento.get_text(" ", strip=True))
            contexto[elemento.name] = texto

            # Ao trocar de nível superior, zera os inferiores
            if elemento.name == "h2":
                contexto["h3"] = None
                contexto["h4"] = None
            elif elemento.name == "h3":
                contexto["h4"] = None

        # Quando encontra tabela, tenta ler com o pandas
        elif elemento.name == "table":
            classes = elemento.get("class", [])

            if "wikitable" not in classes:
                continue

            try:
                tabelas = pd.read_html(StringIO(str(elemento)), flavor="bs4")
                if not tabelas:
                    continue
                tabela = tabelas[0]
            except ValueError:
                continue

            resultado.append((dict(contexto), tabela))

    return resultado


# ============================================================
# IDENTIFICAR TABELA DE PESQUISA
# ============================================================

def eh_tabela_de_pesquisa(df: pd.DataFrame) -> bool:
    """Tabela de pesquisa tem colunas contratante, amostra e margem."""
    colunas = " ".join(str(c).lower() for c in df.columns)
    indicadores = ["contratante", "amostra", "margem"]
    return all(i in colunas for i in indicadores)


# ============================================================
# ESCOPO: PRIMEIRO E SEGUNDO TURNO
# ============================================================

def esta_no_escopo(contexto: dict) -> bool:
    """
    Decide se a tabela entra no scraper, olhando os títulos da página.

    - Primeiro turno: só os meses de 2026 (h4 em MESES_2026)
    - Segundo turno: o h3 é o confronto (ex.: 'Lula e Zema') e o
      h4 pode ser '2026' ou não existir. A tabela 'Agregação de
      pesquisas' é descartada porque reúne médias de OUTROS
      agregadores (UOL, BBC...), não pesquisas, e contaria em dobro.
    """
    h2 = contexto["h2"]
    h4 = contexto["h4"]

    if h2 == "Primeiro turno":
        return h4 in MESES_2026

    if h2 == "Segundo turno":
        # Só entra se a chave de configuração estiver ligada
        return INCLUIR_SEGUNDO_TURNO and h4 != "Agregação de pesquisas"

    return False


# ============================================================
# ACHATAR COLUNAS (cabeçalhos com vários níveis)
# ============================================================

def achatar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    """Transforma cabeçalhos MultiIndex em nomes simples."""
    df = df.copy()
    novos_nomes = []

    if isinstance(df.columns, pd.MultiIndex):
        for camadas in df.columns:
            nome = None

            # Pega a primeira camada que não seja 'Unnamed'
            for camada in camadas:
                texto = str(camada).strip()
                if texto and not texto.startswith("Unnamed"):
                    nome = texto
                    break

            if nome is None:
                nome = str(camadas[-1]).strip()

            novos_nomes.append(nome)
    else:
        novos_nomes = [str(c).strip() for c in df.columns]

    df.columns = novos_nomes
    return df


# ============================================================
# LOCALIZAR COLUNAS DE METADADOS
# ============================================================

def localizar_colunas_metadado(colunas: list[str]) -> dict:
    """Descobre quais colunas são contratante, data, amostra e margem."""

    def buscar(inicios):
        if isinstance(inicios, str):
            inicios = [inicios]

        for coluna in colunas:
            coluna_lower = coluna.lower().strip()
            for inicio in inicios:
                if coluna_lower.startswith(inicio):
                    return coluna
        return None

    return {
        "contratante": buscar("contratante"),
        "data": buscar("data"),
        "amostra": buscar(["tamanho", "amostra"]),
        "margem": buscar("margem"),
    }


# ============================================================
# VERIFICAR SE A COLUNA É DE CANDIDATO
# ============================================================

def eh_coluna_de_candidato(coluna: str, metadado: dict) -> bool:
    """False para metadados, 'Unnamed' e colunas não-candidato."""
    coluna_normalizada = limpar_texto(coluna).lower()

    if coluna in metadado.values():
        return False

    if coluna_normalizada.startswith("unnamed"):
        return False

    if coluna_normalizada in COLUNAS_NAO_CANDIDATO:
        return False

    return True


# ============================================================
# SEPARAR CANDIDATO / PARTIDO
# ============================================================

def separar_candidato_partido(valor: str) -> tuple[str, str | None]:
    """
    Separa 'Lula PT' em ('Lula', 'PT').
    Testa os partidos do maior nome para o menor, para que
    'UNIÃO BRASIL' seja reconhecido antes de 'UNIÃO'.
    """
    texto = limpar_texto(valor)

    if not texto:
        return "", None

    partidos = sorted(PARTIDOS_CANONICOS.keys(), key=len, reverse=True)

    for partido in partidos:
        padrao = r"^(.*?)\s+" + re.escape(partido) + r"$"
        resultado = re.match(padrao, texto, flags=re.IGNORECASE)

        if resultado:
            candidato = resultado.group(1).strip()
            return candidato, PARTIDOS_CANONICOS[partido]

    return texto, None


# ============================================================
# PADRONIZAR CONTRATANTE
# ============================================================

def padronizar_contratante(contratante: str) -> str:
    """Unifica grafias do mesmo instituto."""
    texto = limpar_texto(contratante)
    return PADRONIZACAO_CONTRATANTES.get(texto.lower(), texto)


# ============================================================
# IDS ESTÁVEIS (hash) DE PESQUISA E CENÁRIO
# ============================================================

def normalizar_para_hash(valor) -> str:
    return limpar_texto(valor).lower()


def gerar_id_pesquisa(
    mes_referencia: str,
    contratante: str,
    data_pesquisa: str,
    tamanho_amostra: float,
    margem_erro: float | None,
    contexto: dict,
) -> str:
    """ID da pesquisa: mesmo conteúdo sempre gera o mesmo ID."""
    partes = [
        normalizar_para_hash(mes_referencia),
        normalizar_para_hash(contratante),
        normalizar_para_hash(data_pesquisa),
        str(tamanho_amostra),
        str(margem_erro),
        normalizar_para_hash(contexto.get("h2")),
        normalizar_para_hash(contexto.get("h3")),
        normalizar_para_hash(contexto.get("h4")),
    ]

    texto = "|".join(partes)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def gerar_id_cenario(id_pesquisa: str, valores_cenario: list) -> str:
    """ID do cenário: pesquisa + candidatos e percentuais."""
    partes = [
        f"{normalizar_para_hash(candidato)}={percentual}"
        for candidato, percentual in valores_cenario
    ]
    partes.sort()

    texto = id_pesquisa + "|" + "|".join(partes)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


# ============================================================
# PROCESSAR UMA TABELA
# ============================================================

def processar_tabela(
    tabela: pd.DataFrame,
    mes: str,
    contexto: dict,
) -> pd.DataFrame:
    """Converte uma tabela da Wikipédia para formato longo."""

    achatada = achatar_colunas(tabela)
    metadado = localizar_colunas_metadado(list(achatada.columns))

    # Sem todos os metadados a tabela não serve
    if not all(metadado[c] is not None
               for c in ["contratante", "data", "amostra", "margem"]):
        return pd.DataFrame()

    colunas_candidato = [
        c for c in achatada.columns
        if eh_coluna_de_candidato(c, metadado)
    ]

    registros = []

    for numero_linha, (_, linha) in enumerate(achatada.iterrows(), start=1):

        tamanho_amostra = limpar_numero(linha[metadado["amostra"]])

        # Linhas sem amostra são cabeçalhos repetidos ou ruído
        if tamanho_amostra is None:
            continue

        contratante = limpar_texto(linha[metadado["contratante"]])
        data_pesquisa = limpar_texto(linha[metadado["data"]])
        margem_erro = limpar_numero(linha[metadado["margem"]])

        id_pesquisa = gerar_id_pesquisa(
            mes_referencia=mes,
            contratante=contratante,
            data_pesquisa=data_pesquisa,
            tamanho_amostra=tamanho_amostra,
            margem_erro=margem_erro,
            contexto=contexto,
        )

        # Primeiro coletamos os resultados do cenário
        valores_cenario = []
        dados_candidatos = []

        for coluna in colunas_candidato:
            percentual = limpar_numero(linha[coluna])

            if percentual is None:
                continue

            candidato, partido = separar_candidato_partido(coluna)

            if not candidato:
                continue

            valores_cenario.append((candidato, percentual))
            dados_candidatos.append((candidato, partido, percentual))

        # Linhas sem nenhum candidato são ignoradas
        if not dados_candidatos:
            continue

        id_cenario = gerar_id_cenario(id_pesquisa, valores_cenario)

        for candidato, partido, percentual in dados_candidatos:
            registros.append({
                "id_pesquisa": id_pesquisa,
                "id_cenario": id_cenario,
                "numero_linha_origem": numero_linha,
                "mes_referencia": mes,
                "data_pesquisa": data_pesquisa,
                "contratante_pesquisa": contratante,
                "contratante_padronizado": padronizar_contratante(contratante),
                "tamanho_amostra": tamanho_amostra,
                "margem_erro": margem_erro,
                "candidato": candidato,
                "partido": partido,
                "percentual": percentual,
                "fonte": "Wikipedia",
                "url_fonte": URL,
                "seccao_h2": limpar_texto(contexto["h2"]),
                "seccao_h3": limpar_texto(contexto["h3"]),
                "seccao_h4": limpar_texto(contexto["h4"]),
            })

    return pd.DataFrame(registros)


# ============================================================
# EXECUÇÃO DO SCRAPING
# ============================================================

def executar_scraping() -> pd.DataFrame:
    """Orquestra download, extração, filtro de escopo e limpeza."""

    print("Iniciando scraping...")

    html = baixar_html()
    print(f"HTML baixado: {len(html):,} caracteres")

    tabelas = extrair_tabelas_com_contexto(html)
    print(f"Tabelas encontradas: {len(tabelas)}")

    # Mantém só as tabelas que parecem pesquisas
    tabelas_pesquisa = [
        (contexto, tabela)
        for contexto, tabela in tabelas
        if eh_tabela_de_pesquisa(tabela)
    ]
    print(f"Tabelas de pesquisa: {len(tabelas_pesquisa)}")

    # Escopo: primeiro turno (meses de 2026) e segundo turno
    tabelas_2026 = [
        (contexto, tabela)
        for contexto, tabela in tabelas_pesquisa
        if esta_no_escopo(contexto)
    ]
    print(f"Tabelas dentro do escopo 2026: {len(tabelas_2026)}")

    # Diagnóstico: quantas tabelas entraram por turno e confronto
    # (confira se todos os confrontos de 2º turno aparecem aqui)
    print("\nTabelas por turno / confronto:")
    contagem = {}
    for contexto, _ in tabelas_2026:
        chave = (contexto["h2"], contexto["h3"] or "-")
        contagem[chave] = contagem.get(chave, 0) + 1
    for (turno, confronto), quantidade in sorted(contagem.items()):
        print(f"  {turno} | {confronto}: {quantidade}")

    resultados = []

    for contexto, tabela in tabelas_2026:
        resultado = processar_tabela(
            tabela=tabela,
            # No 2º turno o h4 pode não existir; usa texto vazio
            mes=contexto["h4"] or "",
            contexto=contexto,
        )
        if not resultado.empty:
            resultados.append(resultado)

    if not resultados:
        raise RuntimeError("Nenhum dado foi extraído.")

    dados = pd.concat(resultados, ignore_index=True)

    # Data/hora UTC em que a coleta foi feita
    # ATENÇÃO: não usar o nome "data_coleta" aqui, porque ele já é o
    # nome da partição no S3 (data_coleta=AAAA-MM-DD) e o Glue/Athena
    # não aceitam duas colunas com o mesmo nome
    dados["timestamp_coleta"] = datetime.now(timezone.utc).isoformat()

    # Remove duplicidades exatas
    colunas_chave = [
        "id_pesquisa", "id_cenario", "candidato", "partido", "percentual",
    ]

    antes = len(dados)
    dados = dados.drop_duplicates(subset=colunas_chave)
    print(f"\nDuplicidades removidas: {antes - len(dados)}")

    dados = dados.sort_values(
        by=[
            "mes_referencia",
            "data_pesquisa",
            "contratante_pesquisa",
            "id_cenario",
            "candidato",
        ]
    ).reset_index(drop=True)

    return dados


# ============================================================
# VALIDAÇÃO
# ============================================================

def imprimir_secao(titulo: str, caractere: str = "-"):
    print("\n" + caractere * 70)
    print(titulo)
    print(caractere * 70)


def validar_dados(dados: pd.DataFrame):
    """Imprime um relatório para conferir a qualidade dos dados."""

    imprimir_secao("VALIDAÇÃO DOS DADOS", "=")

    print(f"\nRegistros: {len(dados):,}")
    print(f"Pesquisas únicas: {dados['id_pesquisa'].nunique():,}")
    print(f"Cenários únicos: {dados['id_cenario'].nunique():,}")
    print(f"Candidatos: {dados['candidato'].nunique():,}")
    print(f"Partidos: {dados['partido'].nunique():,}")
    print(f"Contratantes originais: {dados['contratante_pesquisa'].nunique():,}")
    print(f"Contratantes padronizados: {dados['contratante_padronizado'].nunique():,}")

    # Lista de candidatos: aqui deve aparecer só gente de verdade
    imprimir_secao("CANDIDATOS E PARTIDOS")
    candidatos = (
        dados[["candidato", "partido"]]
        .drop_duplicates()
        .sort_values(["candidato", "partido"])
    )
    print(candidatos.to_string(index=False))

    # Nomes suspeitos de NÃO serem candidatos (ex.: Vantagem)
    imprimir_secao("CANDIDATOS SEM PARTIDO IDENTIFICADO")
    sem_partido = (
        dados[dados["partido"].isna()]["candidato"]
        .drop_duplicates()
        .sort_values()
    )
    print("Nenhum." if sem_partido.empty else sem_partido.to_string(index=False))

    imprimir_secao("CONTRATANTES")
    contratantes = (
        dados[["contratante_pesquisa", "contratante_padronizado"]]
        .drop_duplicates()
        .sort_values(["contratante_padronizado", "contratante_pesquisa"])
    )
    print(contratantes.to_string(index=False))

    imprimir_secao("VALORES NULOS POR COLUNA")
    print(dados.isna().sum().to_string())

    # Percentuais fora de 0-100
    invalidos = dados[(dados["percentual"] < 0) | (dados["percentual"] > 100)]
    print(f"\nPercentuais inválidos: {len(invalidos)}")

    duplicados = dados[
        dados.duplicated(
            subset=["id_pesquisa", "id_cenario", "candidato", "partido", "percentual"],
            keep=False,
        )
    ]
    print(f"Registros duplicados: {len(duplicados)}")

    # Candidato aparecendo em mais de um cenário na mesma pesquisa
    imprimir_secao("CANDIDATOS COM MÚLTIPLOS CENÁRIOS NA MESMA PESQUISA")
    cenarios_por_candidato = (
        dados.groupby(["id_pesquisa", "candidato"])["id_cenario"]
        .nunique()
        .reset_index(name="quantidade_cenarios")
    )
    multiplos = cenarios_por_candidato[
        cenarios_por_candidato["quantidade_cenarios"] > 1
    ]
    print(f"Ocorrências: {len(multiplos)}")
    if not multiplos.empty:
        print(multiplos.head(20).to_string(index=False))

    imprimir_secao("DISTRIBUIÇÃO DE CENÁRIOS POR PESQUISA")
    print(
        dados.groupby("id_pesquisa")["id_cenario"]
        .nunique()
        .value_counts()
        .sort_index()
        .to_string()
    )

    imprimir_secao("PESQUISAS POR TURNO E CONFRONTO")
    print(
        dados.groupby(["seccao_h2", "seccao_h3"], dropna=False)
        .agg(
            pesquisas=("id_pesquisa", "nunique"),
            registros=("id_pesquisa", "size"),
        )
        .to_string()
    )

    imprimir_secao("REGISTROS POR MÊS")
    print(
        dados.groupby("mes_referencia").size()
        .sort_values(ascending=False)
        .to_string()
    )

    imprimir_secao("REGISTROS POR PARTIDO")
    print(
        dados.groupby("partido", dropna=False).size()
        .sort_values(ascending=False)
        .to_string()
    )


# ============================================================
# ENVIO PARA O S3
# ============================================================

def enviar_para_s3(arquivo_local: Path) -> str:
    """
    Envia o CSV para o S3 no padrão chave=valor, com uma
    subpasta por data de coleta:

    raw/fonte=wikipedia/ano=2026/data_coleta=AAAA-MM-DD/arquivo.csv

    Requer credenciais configuradas (aws configure).
    """
    # Importa aqui para o scraper funcionar mesmo sem boto3
    import boto3

    hoje = date.today().isoformat()

    chave_s3 = (
        f"raw/fonte=wikipedia/ano=2026/data_coleta={hoje}/"
        f"{arquivo_local.name}"
    )

    s3 = boto3.client("s3")
    s3.upload_file(str(arquivo_local), BUCKET, chave_s3)

    return f"s3://{BUCKET}/{chave_s3}"


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    # 1. Coleta e transformação
    dados = executar_scraping()

    # 2. Validação (confira se 'Vantagem' NÃO aparece como candidato)
    validar_dados(dados)

    # 3. Trava de segurança: nenhuma coluna do CSV pode ter o mesmo
    #    nome de uma partição do S3 (ano, data_coleta)
    conflitos = COLUNAS_RESERVADAS_PARTICAO.intersection(dados.columns)
    if conflitos:
        raise ValueError(
            f"Colunas do CSV conflitam com partições do S3: {conflitos}"
        )

    # 4. Salva local em utf-8 SEM BOM (leitura correta no Glue/Athena)
    dados.to_csv(ARQUIVO_SAIDA, index=False, encoding="utf-8")

    imprimir_secao("SCRAPING CONCLUÍDO", "=")
    print(f"\nArquivo salvo em: {ARQUIVO_SAIDA}")
    print(f"Total de registros: {len(dados):,}")
    print(f"Total de pesquisas: {dados['id_pesquisa'].nunique():,}")
    print(f"Total de cenários: {dados['id_cenario'].nunique():,}")
    print(f"Total de candidatos: {dados['candidato'].nunique():,}")
    print(f"Total de partidos: {dados['partido'].nunique():,}")

    # 5. Envio para o S3 (opcional)
    if ENVIAR_PARA_S3:
        destino = enviar_para_s3(ARQUIVO_SAIDA)
        print(f"\nEnviado para: {destino}")
