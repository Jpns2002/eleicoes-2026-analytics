# ============================================================
# PROBABILIDADE ELEITORAL (1º TURNO) - PROJETO ELEIÇÕES 2026
#
# O que este script faz:
#   1. Lê as pesquisas comparáveis (do Athena ou de um CSV)
#   2. Calcula um peso para cada pesquisa:
#        - amostra limitada a 3.000 (evita que uma pesquisa gigante,
#          como as de 40.500 entrevistas, domine a média)
#        - decaimento por recência (pesquisas novas pesam mais)
#   3. Estima a média de cada candidato
#   4. Simula 20.000 cenários, reamostrando INSTITUTOS (para capturar
#      a diferença sistemática entre eles) e somando um erro
#      sistemático extra (pesquisas erram mais que a margem de erro)
#   5. Conta, nas simulações, quantas vezes cada candidato lidera e
#      quantas vezes fica entre os dois primeiros
#
# ATENÇÃO: é uma estimativa simplificada, NÃO um modelo preditivo
# validado. Os parâmetros abaixo são premissas, não fatos.
# ============================================================

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# CONFIGURAÇÕES
# ============================================================

# De onde ler os dados: "athena" (consulta direta) ou "csv"
FONTE = "csv"

# Configuração do Athena (usada quando FONTE = "athena")
DATABASE = "eleicoes2026"
S3_RESULTADOS_ATHENA = "s3://joaopedro-eleicoes2026-raw/athena-results/"

# Arquivo CSV (usado quando FONTE = "csv"): resultado da consulta SQL
# abaixo, baixado do Athena com "Baixar CSV dos resultados"
ARQUIVO_CSV = Path("dados_processados/pesquisas_comparaveis.csv")

# Onde salvar o resultado
ARQUIVO_SAIDA = Path("resultados/probabilidades.csv")

# Candidatos que entram na simulação
CANDIDATOS = ["Lula", "Flávio", "Cury", "Renan", "Caiado", "Zema"]

# Premissas do método (documente no README)
DIAS_JANELA = 45            # só pesquisas dos últimos 45 dias
META_VIDA_DIAS = 14         # a cada 14 dias, o peso cai pela metade
LIMITE_AMOSTRA = 3000       # amostra máxima considerada no peso
ERRO_SISTEMATICO_PP = 2.0   # erro extra (pontos percentuais) por candidato
N_SIMULACOES = 20000
SEMENTE = 2026              # fixa o sorteio, para o resultado ser repetível

# Data de referência (None = hoje)
DATA_REFERENCIA = None


# ============================================================
# CONSULTA SQL (uma linha por pesquisa e candidato)
# Só cenários que contêm Lula e Flávio (view vw_pesquisas_comparaveis)
# ============================================================

lista_candidatos_sql = ", ".join(f"'{c}'" for c in CANDIDATOS)

SQL = f"""
SELECT id_pesquisa,
       instituto,
       candidato,
       MAX(data_fim) AS data_fim,
       MAX(tamanho_amostra) AS amostra,
       AVG(percentual) AS pct
FROM eleicoes2026.vw_pesquisas_comparaveis
WHERE candidato IN ({lista_candidatos_sql})
GROUP BY id_pesquisa, instituto, candidato
"""


# ============================================================
# LEITURA DOS DADOS
# ============================================================

def carregar_dados() -> pd.DataFrame:
    """Lê os dados do Athena ou do CSV, conforme FONTE."""

    if FONTE == "athena":
        # Requer: pip install awswrangler e permissões de Athena/Glue
        import awswrangler as wr

        return wr.athena.read_sql_query(
            sql=SQL,
            database=DATABASE,
            s3_output=S3_RESULTADOS_ATHENA,
            ctas_approach=False,
        )

    return pd.read_csv(ARQUIVO_CSV)


# ============================================================
# PREPARAÇÃO: formato largo (1 linha por pesquisa)
# ============================================================

def preparar_pesquisas(dados: pd.DataFrame, data_ref: pd.Timestamp):
    """
    Devolve:
      pct   -> tabela pesquisa x candidato com os percentuais
      meta  -> instituto, amostra e data_fim de cada pesquisa
    """
    dados = dados.copy()
    dados["data_fim"] = pd.to_datetime(dados["data_fim"])

    # Mantém só a janela de tempo definida
    inicio = data_ref - pd.Timedelta(days=DIAS_JANELA)
    dados = dados[(dados["data_fim"] >= inicio) & (dados["data_fim"] <= data_ref)]

    if dados.empty:
        raise RuntimeError("Nenhuma pesquisa dentro da janela de tempo.")

    # Candidatos em colunas
    pct = dados.pivot_table(
        index="id_pesquisa",
        columns="candidato",
        values="pct",
        aggfunc="mean",
    ).reindex(columns=CANDIDATOS)

    # Metadados de cada pesquisa (um valor por id_pesquisa)
    meta = (
        dados.groupby("id_pesquisa")
        .agg(
            instituto=("instituto", "first"),
            amostra=("amostra", "max"),
            data_fim=("data_fim", "max"),
        )
        .loc[pct.index]
    )

    return pct, meta


# ============================================================
# PESOS
# ============================================================

def calcular_pesos(meta: pd.DataFrame, data_ref: pd.Timestamp) -> pd.Series:
    """Peso = amostra limitada x decaimento por recência."""

    dias = (data_ref - meta["data_fim"]).dt.days.clip(lower=0)
    amostra = meta["amostra"].clip(upper=LIMITE_AMOSTRA)

    return amostra * 0.5 ** (dias / META_VIDA_DIAS)


# ============================================================
# ESTIMATIVA E SOMAS POR INSTITUTO
# ============================================================

def somas_ponderadas(pct: pd.DataFrame, pesos: pd.Series, institutos: pd.Series):
    """
    Para cada instituto e candidato, devolve:
      num = soma de (percentual x peso)
      den = soma dos pesos (só das pesquisas em que o candidato aparece)
    """
    tem_valor = pct.notna()

    num = pct.fillna(0).mul(pesos, axis=0).groupby(institutos).sum()
    den = tem_valor.mul(pesos, axis=0).groupby(institutos).sum()

    return num, den


# ============================================================
# SIMULAÇÃO
# ============================================================

def simular(num, den, estimativa, rng) -> np.ndarray:
    """
    Cada simulação:
      1. sorteia institutos COM reposição (mesmo número de institutos)
      2. recalcula a média ponderada de cada candidato
      3. soma um erro sistemático aleatório
    Devolve uma matriz (simulações x candidatos).
    """
    n_inst = len(num)

    # Institutos sorteados em cada simulação
    sorteio = rng.integers(0, n_inst, size=(N_SIMULACOES, n_inst))

    soma_num = num.to_numpy()[sorteio].sum(axis=1)
    soma_den = den.to_numpy()[sorteio].sum(axis=1)

    with np.errstate(divide="ignore", invalid="ignore"):
        medias = soma_num / soma_den

    # Se um candidato não aparece nos institutos sorteados,
    # usa a estimativa geral dele
    medias = np.where(np.isfinite(medias), medias, estimativa.to_numpy())

    # Erro sistemático (pesquisas erram mais que a margem de erro)
    ruido = rng.normal(0, ERRO_SISTEMATICO_PP, size=medias.shape)

    return np.clip(medias + ruido, 0, None)


# ============================================================
# PROBABILIDADES
# ============================================================

def calcular_probabilidades(simulacao: np.ndarray, estimativa: pd.Series):
    """Conta quantas vezes cada candidato lidera e fica no top 2."""

    n_sim, n_cand = simulacao.shape

    # Índices dos candidatos, do mais votado ao menos votado
    ordem = np.argsort(-simulacao, axis=1)

    lider = ordem[:, 0]
    top2 = ordem[:, :2]

    p_liderar = np.bincount(lider, minlength=n_cand) / n_sim
    p_top2 = np.array([(top2 == c).any(axis=1).mean() for c in range(n_cand)])

    resultado = pd.DataFrame({
        "candidato": estimativa.index,
        "estimativa_pct": estimativa.round(1).to_numpy(),
        "intervalo90_min": np.percentile(simulacao, 5, axis=0).round(1),
        "intervalo90_max": np.percentile(simulacao, 95, axis=0).round(1),
        "prob_liderar_pct": (100 * p_liderar).round(1),
        "prob_2_turno_pct": (100 * p_top2).round(1),
    })

    return resultado.sort_values("estimativa_pct", ascending=False).reset_index(drop=True)


# ============================================================
# EXECUÇÃO
# ============================================================

def executar() -> pd.DataFrame:

    data_ref = pd.Timestamp(DATA_REFERENCIA or date.today())

    dados = carregar_dados()
    print(f"Linhas lidas: {len(dados):,}")

    pct, meta = preparar_pesquisas(dados, data_ref)
    pesos = calcular_pesos(meta, data_ref)

    print(f"Pesquisas na janela: {len(pct)}")
    print(f"Institutos: {meta['instituto'].nunique()}")

    # Quanto cada instituto pesa no total (confira se nenhum domina)
    peso_inst = (pesos.groupby(meta["instituto"]).sum() / pesos.sum() * 100).round(1)
    print("\nPeso de cada instituto (%):")
    print(peso_inst.sort_values(ascending=False).to_string())

    # Estimativa pontual de cada candidato
    num, den = somas_ponderadas(pct, pesos, meta["instituto"])
    estimativa = num.sum() / den.sum()

    # Simulação
    rng = np.random.default_rng(SEMENTE)
    simulacao = simular(num, den, estimativa, rng)

    resultado = calcular_probabilidades(simulacao, estimativa)

    ARQUIVO_SAIDA.parent.mkdir(exist_ok=True)
    resultado.to_csv(ARQUIVO_SAIDA, index=False, encoding="utf-8")

    return resultado


if __name__ == "__main__":

    resultado = executar()

    print("\n" + "=" * 70)
    print("PROBABILIDADES ESTIMADAS (1º TURNO)")
    print("=" * 70)
    print(resultado.to_string(index=False))

    print(
        "\nLeitura: 'prob_liderar' é a chance de ter mais votos que os "
        "demais no 1º turno;\n'prob_2_turno' é a chance de ficar entre os "
        "dois mais votados.\nÉ uma estimativa simplificada, baseada em "
        "premissas, e NÃO uma previsão."
    )
    print(f"\nResultado salvo em: {ARQUIVO_SAIDA}")
