# ============================================================
# GRÁFICOS - PROJETO ELEIÇÕES 2026
#
# Gera 3 imagens a partir dos arquivos que o projeto já tem:
#   1. evolucao_lula_flavio.png  -> média móvel de 14 dias, ao longo do ano
#   2. probabilidades.png        -> estimativa, intervalo de 90% e chance de liderar
#   3. comparacao_institutos.png -> Lula x Flávio em cada instituto
#
# Entradas:
#   dados_processados/pesquisas_comparaveis.csv  (exportado do Athena)
#   resultados/probabilidades.csv                (gerado por probabilidade.py)
#
# Saída: pasta graficos/
#
# Requer: python -m pip install matplotlib pandas numpy
# ============================================================

from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # gera arquivos sem abrir janela
import matplotlib.dates as mdates
import matplotlib.ticker
import matplotlib.pyplot as plt
import pandas as pd


# ============================================================
# CONFIGURAÇÕES
# ============================================================

ARQUIVO_PESQUISAS = Path("dados_processados/pesquisas_comparaveis.csv")
ARQUIVO_PROBABILIDADES = Path("resultados/probabilidades.csv")
PASTA_SAIDA = Path("graficos")

# Mesmas premissas do probabilidade.py
LIMITE_AMOSTRA = 3000
DIAS_JANELA_INSTITUTOS = 45
JANELA_MEDIA_MOVEL_DIAS = 14

MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
            "jul", "ago", "set", "out", "nov", "dez"]

# Cores neutras (boas para daltonismo), sem associação partidária
COR_LULA = "#D55E00"
COR_FLAVIO = "#0072B2"
COR_OUTROS = "#7F7F7F"

DATA_REFERENCIA = None  # None = hoje


# ============================================================
# LEITURA
# ============================================================

def carregar_pesquisas(data_ref: pd.Timestamp) -> pd.DataFrame:
    """Lê o CSV e converte a data final da pesquisa."""
    dados = pd.read_csv(ARQUIVO_PESQUISAS)
    dados["data_fim"] = pd.to_datetime(dados["data_fim"])
    dados["peso_base"] = dados["amostra"].clip(upper=LIMITE_AMOSTRA)
    return dados[dados["data_fim"] <= data_ref]


# ============================================================
# GRÁFICO 1: EVOLUÇÃO (MÉDIA MÓVEL DE 14 DIAS)
# ============================================================

def serie_media_movel(dados: pd.DataFrame, candidato: str, data_ref: pd.Timestamp):
    """
    Para cada semana, calcula a média ponderada (amostra limitada a 3.000)
    das pesquisas dos 14 dias anteriores.
    """
    base = dados[dados["candidato"] == candidato]
    datas = pd.date_range(base["data_fim"].min() + pd.Timedelta(days=14),
                          data_ref, freq="7D")

    pontos = []
    for data in datas:
        janela = base[
            (base["data_fim"] > data - pd.Timedelta(days=JANELA_MEDIA_MOVEL_DIAS))
            & (base["data_fim"] <= data)
        ]
        if len(janela) >= 2:
            media = (janela["pct"] * janela["peso_base"]).sum() / janela["peso_base"].sum()
            pontos.append((data, media))

    return pd.DataFrame(pontos, columns=["data", "media"])


def grafico_evolucao(dados: pd.DataFrame, data_ref: pd.Timestamp):
    lula = serie_media_movel(dados, "Lula", data_ref)
    flavio = serie_media_movel(dados, "Flávio", data_ref)

    fig, ax = plt.subplots(figsize=(10, 5.5))

    ax.plot(lula["data"], lula["media"], color=COR_LULA, linewidth=2.2, label="Lula")
    ax.plot(flavio["data"], flavio["media"], color=COR_FLAVIO, linewidth=2.2, label="Flávio")

    # Valor final de cada série
    for serie, cor in [(lula, COR_LULA), (flavio, COR_FLAVIO)]:
        ultimo = serie.iloc[-1]
        ax.annotate(f"{ultimo['media']:.1f}%",
                    (ultimo["data"], ultimo["media"]),
                    textcoords="offset points", xytext=(8, 0),
                    color=cor, fontsize=11, fontweight="bold", va="center")

    ax.set_title("Evolução das intenções de voto: Lula x Flávio\n"
                 "Média móvel de 14 dias, ponderada pela amostra (limitada a 3.000)",
                 fontsize=12, loc="left")
    ax.set_ylabel("% das intenções de voto (1º turno)")
    ax.set_ylim(20, 50)

    # Um marcador por mês, com o nome do mês em português
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda x, _: MESES_PT[mdates.num2date(x).month - 1])
    )
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="lower right")

    fig.text(0.01, 0.01,
             "Fonte: pesquisas registradas na Wikipédia, processadas na AWS (S3, Glue, Athena). "
             "Só cenários com Lula e Flávio.",
             fontsize=8, color="#555555")

    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(PASTA_SAIDA / "evolucao_lula_flavio.png", dpi=150)
    plt.close(fig)


# ============================================================
# GRÁFICO 2: PROBABILIDADES
# ============================================================

def grafico_probabilidades():
    resultado = pd.read_csv(ARQUIVO_PROBABILIDADES)
    resultado = resultado.sort_values("estimativa_pct", ascending=True)

    cores = [COR_LULA if c == "Lula" else COR_FLAVIO if c == "Flávio" else COR_OUTROS
             for c in resultado["candidato"]]

    fig, ax = plt.subplots(figsize=(10, 5))

    ax.barh(resultado["candidato"], resultado["estimativa_pct"], color=cores, alpha=0.85)

    # Intervalo de 90% das simulações
    erro_esq = resultado["estimativa_pct"] - resultado["intervalo90_min"]
    erro_dir = resultado["intervalo90_max"] - resultado["estimativa_pct"]
    ax.errorbar(resultado["estimativa_pct"], resultado["candidato"],
                xerr=[erro_esq, erro_dir], fmt="none", ecolor="black",
                capsize=4, linewidth=1.2)

    # Texto com estimativa e chance de liderar
    for _, linha in resultado.iterrows():
        texto = f"{linha['estimativa_pct']:.1f}%"
        if linha["prob_liderar_pct"] > 0:
            # Uma casa decimal, para as chances de Lula e Flávio somarem 100%
            texto += f"  |  chance de liderar: {linha['prob_liderar_pct']:.1f}%"
        ax.text(linha["intervalo90_max"] + 0.8, linha["candidato"], texto,
                va="center", fontsize=10)

    ax.set_xlim(0, 62)
    ax.set_title("Estimativa por candidato e chance de liderar o 1º turno\n"
                 "Barras: estimativa | Linhas: intervalo de 90% das simulações",
                 fontsize=12, loc="left")
    ax.set_xlabel("% das intenções de voto")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.3)

    fig.text(0.01, 0.01,
             "Estimativa simplificada com premissas (peso por amostra e recência, "
             "reamostragem de institutos, erro sistemático de 2 p.p.). Não é uma previsão.",
             fontsize=8, color="#555555")

    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(PASTA_SAIDA / "probabilidades.png", dpi=150)
    plt.close(fig)


# ============================================================
# GRÁFICO 3: COMPARAÇÃO POR INSTITUTO
# Uma barra por instituto: a diferença entre Lula e Flávio
# ============================================================

def grafico_institutos(dados: pd.DataFrame, data_ref: pd.Timestamp):
    inicio = data_ref - pd.Timedelta(days=DIAS_JANELA_INSTITUTOS)
    recente = dados[(dados["data_fim"] >= inicio)
                    & (dados["candidato"].isin(["Lula", "Flávio"]))]

    # Média de cada candidato em cada instituto e a diferença entre eles
    tabela = (recente.groupby(["instituto", "candidato"])["pct"].mean()
              .unstack("candidato").dropna())
    tabela["dif"] = tabela["Lula"] - tabela["Flávio"]
    tabela = tabela.sort_values("dif")  # Flávio à frente embaixo, Lula no topo

    total = len(tabela)
    lula_na_frente = int((tabela["dif"] > 0).sum())

    cores = [COR_LULA if d > 0 else COR_FLAVIO for d in tabela["dif"]]
    posicoes = list(range(total))

    fig, ax = plt.subplots(figsize=(9, 6.5))

    ax.barh(posicoes, tabela["dif"], color=cores, height=0.65)
    ax.axvline(0, color="#333333", linewidth=1)

    # Valor da diferença na ponta de cada barra
    for pos, dif in zip(posicoes, tabela["dif"]):
        if dif >= 0:
            ax.text(dif + 0.25, pos, f"+{dif:.1f}", va="center", ha="left", fontsize=10)
        else:
            ax.text(dif - 0.25, pos, f"{dif:.1f}", va="center", ha="right", fontsize=10)

    # Indicação do lado de cada candidato, acima das barras
    ax.text(-0.3, total - 0.1, "← Flávio à frente", ha="right", va="bottom",
            color=COR_FLAVIO, fontsize=10, fontweight="bold")
    ax.text(0.3, total - 0.1, "Lula à frente →", ha="left", va="bottom",
            color=COR_LULA, fontsize=10, fontweight="bold")

    # Eixos enxutos: sem números no eixo x, sem bordas desnecessárias
    ax.set_yticks(posicoes)
    ax.set_yticklabels(tabela.index, fontsize=10)
    ax.tick_params(axis="y", length=0)
    ax.set_xticks([])
    ax.set_xlim(tabela["dif"].min() - 2.2, tabela["dif"].max() + 2.2)
    ax.set_ylim(-0.6, total + 0.6)
    ax.spines[["top", "right", "bottom", "left"]].set_visible(False)

    ax.set_title(f"Lula lidera em {lula_na_frente} de {total} institutos",
                 loc="left", fontsize=14, fontweight="bold", pad=34)
    ax.text(0, 1.045, "Diferença entre Lula e Flávio, em pontos percentuais "
            f"(média das pesquisas dos últimos {DIAS_JANELA_INSTITUTOS} dias)",
            transform=ax.transAxes, fontsize=10, color="#555555")

    fig.text(0.01, 0.01, "Só cenários com Lula e Flávio. Institutos com poucas pesquisas "
             "(1 a 2) oscilam mais.", fontsize=8, color="#555555")

    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(PASTA_SAIDA / "comparacao_institutos.png", dpi=150)
    plt.close(fig)


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    data_ref = pd.Timestamp(DATA_REFERENCIA or date.today())
    PASTA_SAIDA.mkdir(exist_ok=True)

    dados = carregar_pesquisas(data_ref)
    print(f"Linhas lidas: {len(dados):,}")

    grafico_evolucao(dados, data_ref)
    print("Gerado: graficos/evolucao_lula_flavio.png")

    grafico_probabilidades()
    print("Gerado: graficos/probabilidades.png")

    grafico_institutos(dados, data_ref)
    print("Gerado: graficos/comparacao_institutos.png")
