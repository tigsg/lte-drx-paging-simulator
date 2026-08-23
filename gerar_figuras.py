"""
gerar_figuras.py — Figuras explicativas para a metodologia do relatorio.

Gera quatro imagens que explicam COMO o simulador funciona (as figuras de
resultados vem do monte_carlo_novo.py e do varredura.py):

  fig1_arquitetura.png    Os tres componentes e como conversam por UDP
  fig2_drx_vs_blind.png   Linha do tempo: quando cada modo liga o radio
  fig3_transicao_drx.png  Ciclo curto -> ciclo longo apos despertares em vao
  fig4_multiprocessing.png  Evidencia de paralelismo (PIDs distintos por UE)

A figura 4 le o resultados_simulacao.csv se existir. Rode o Monte Carlo antes
para ter dados reais; sem o CSV ela e' gerada com dados ilustrativos.

Uso:  python gerar_figuras.py
"""
from __future__ import annotations

import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

DPI = 200
AZUL, VERMELHO, CINZA, VERDE = "#3b6fd4", "#e05c4b", "#5c5c5c", "#2e8b57"


def _caixa(ax, x, y, w, h, texto, cor, fonte=10, cor_texto="white"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02",
                                facecolor=cor, edgecolor="black", linewidth=1.2))
    ax.text(x + w / 2, y + h / 2, texto, ha="center", va="center",
            fontsize=fonte, color=cor_texto, weight="bold", linespacing=1.4)


def _seta(ax, xy_de, xy_para, texto="", cor="black", desloc=0.0, estilo="-|>"):
    ax.add_patch(FancyArrowPatch(xy_de, xy_para, arrowstyle=estilo,
                                 mutation_scale=14, linewidth=1.4, color=cor))
    if texto:
        mx = (xy_de[0] + xy_para[0]) / 2
        my = (xy_de[1] + xy_para[1]) / 2 + desloc
        ax.text(mx, my, texto, ha="center", va="center", fontsize=8.5,
                color=cor, bbox=dict(facecolor="white", edgecolor="none", pad=1.5))


# ---------------------------------------------------------------------------
# Figura 1 — Arquitetura
# ---------------------------------------------------------------------------
def fig_arquitetura(caminho="fig1_arquitetura.png"):
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")

    _caixa(ax, 0.3, 4.4, 2.6, 1.1,
           "Monte Carlo\n(processo principal)", CINZA, 10)
    _caixa(ax, 6.9, 4.4, 2.6, 1.1, "eNodeB\n(estacao base)", AZUL, 10)

    # Processos de UE
    for x, rotulo in zip([0.5, 2.4, 4.3, 6.2],
                         ["UE 1\nPID 9620", "UE 2\nPID 2356",
                          "UE 3\nPID 12096", "UE n\nPID ..."]):
        _caixa(ax, x, 0.9, 1.6, 1.0, rotulo, VERDE, 9)
    ax.text(8.05, 1.4, "cada UE roda em um\nprocesso proprio do\nsistema operacional",
            fontsize=8.5, style="italic", color=VERDE, ha="left", va="center")

    _seta(ax, (2.9, 5.0), (6.9, 5.0), "ordens de paging  (UDP 10000)", CINZA, 0.22)
    _seta(ax, (8.2, 4.4), (8.2, 3.3), "", AZUL)
    ax.text(8.35, 3.85, "broadcast do relogio +\nlista de paging (UDP 9999)",
            fontsize=8.5, color=AZUL, ha="left", va="center")

    # Barramento de broadcast
    ax.plot([0.8, 8.2], [3.2, 3.2], color=AZUL, linewidth=2.2)
    for x in [1.3, 3.2, 5.1, 7.0]:
        _seta(ax, (x, 3.2), (x, 1.9), "", AZUL)

    _seta(ax, (1.3, 0.9), (1.3, 0.45), "", CINZA)
    ax.plot([1.3, 1.9], [0.45, 0.45], color=CINZA, linewidth=1.4)
    ax.text(2.05, 0.45, "resultados (latencia, consumo, PID) -> fila -> CSV",
            fontsize=8.5, color=CINZA, va="center")

    ax.set_title("Figura 1 - Arquitetura do simulador",
                 fontsize=12, weight="bold", pad=12)
    fig.tight_layout()
    fig.savefig(caminho, dpi=DPI, facecolor="white")
    plt.close(fig)
    return caminho


# ---------------------------------------------------------------------------
# Figura 2 — DRX vs Blind Search na linha do tempo
# ---------------------------------------------------------------------------
def fig_drx_vs_blind(caminho="fig2_drx_vs_blind.png", ciclo=16, po_abs=99, total=480):
    fig, ax = plt.subplots(figsize=(10, 3.6))

    # Blind: radio ligado o tempo todo
    ax.broken_barh([(0, total)], (1.55, 0.5), facecolors=VERMELHO,
                   edgecolor="black", linewidth=0.4)

    # DRX: acorda 1 subframe a cada ciclo
    despertares = list(range(po_abs, total, ciclo * 10))
    ax.broken_barh([(d, 3) for d in despertares], (0.55, 0.5),
                   facecolors=AZUL, edgecolor="black", linewidth=0.4)
    ax.broken_barh([(0, total)], (0.55, 0.5), facecolors="#e9edf7", zorder=0)

    for d in despertares:
        ax.annotate("PO", xy=(d + 1.5, 0.5), xytext=(d + 1.5, 0.12),
                    ha="center", fontsize=8, color=AZUL,
                    arrowprops=dict(arrowstyle="->", color=AZUL, linewidth=1))

    if len(despertares) >= 2:
        a, b = despertares[0], despertares[1]
        ax.annotate("", xy=(a, 1.35), xytext=(b, 1.35),
                    arrowprops=dict(arrowstyle="<->", color="black", linewidth=1.1))
        ax.text((a + b) / 2, 1.42, f"ciclo = {ciclo} frames = {ciclo*10} subframes",
                ha="center", fontsize=9)

    ax.set_yticks([0.8, 1.8])
    ax.set_yticklabels(["DRX", "Blind Search"], fontsize=10, weight="bold")
    ax.set_xlabel("Tempo (subframes)")
    ax.set_xlim(0, total)
    ax.set_ylim(0, 2.35)
    ax.grid(axis="x", alpha=0.25)
    ax.set_title("Figura 2 - Quando cada modo liga o radio\n"
                 "(barra preenchida = radio ativo)",
                 fontsize=12, weight="bold", pad=10)
    fig.tight_layout()
    fig.savefig(caminho, dpi=DPI, facecolor="white")
    plt.close(fig)
    return caminho


# ---------------------------------------------------------------------------
# Figura 3 — Transicao ciclo curto -> ciclo longo
# ---------------------------------------------------------------------------
def fig_transicao(caminho="fig3_transicao_drx.png",
                  curto=4, longo=8, limite=3, po_abs=25, total=560):
    fig, ax = plt.subplots(figsize=(10, 3.4))

    t, wakes_curto, wakes_longo = po_abs, [], []
    for _ in range(limite):
        wakes_curto.append(t)
        t += curto * 10
    while t < total:
        wakes_longo.append(t)
        t += longo * 10

    ax.broken_barh([(0, total)], (0.6, 0.5), facecolors="#eef1f6", zorder=0)
    ax.broken_barh([(w, 4) for w in wakes_curto], (0.6, 0.5),
                   facecolors=AZUL, edgecolor="black", linewidth=0.4)
    ax.broken_barh([(w, 4) for w in wakes_longo], (0.6, 0.5),
                   facecolors=VERDE, edgecolor="black", linewidth=0.4)

    fim_curto = wakes_curto[-1] + curto * 10 / 2
    ax.axvline(fim_curto, color="black", linestyle="--", linewidth=1.2)
    ax.text(fim_curto - 8, 1.32, f"apos {limite} despertares\nsem paging",
            ha="right", fontsize=9)
    ax.text(fim_curto + 8, 1.32, "passa ao ciclo longo\n(acorda menos)",
            ha="left", fontsize=9, color=VERDE)

    for w in wakes_curto:
        ax.text(w + 2, 0.42, "x", ha="center", fontsize=9, color=VERMELHO)
    ax.text(wakes_curto[0], 0.22, "x = acordou e nao havia paging para ele",
            ha="left", fontsize=8.5, color=VERMELHO)

    ax.text((0 + fim_curto) / 2, 1.72, f"CICLO CURTO ({curto} frames)",
            ha="center", fontsize=10, weight="bold", color=AZUL)
    ax.text((fim_curto + total) / 2, 1.72, f"CICLO LONGO ({longo} frames)",
            ha="center", fontsize=10, weight="bold", color=VERDE)

    ax.set_yticks([])
    ax.set_xlabel("Tempo (subframes)")
    ax.set_xlim(0, total)
    ax.set_ylim(0, 2.0)
    ax.grid(axis="x", alpha=0.25)
    ax.set_title("Figura 3 - Transicao do ciclo curto para o ciclo longo",
                 fontsize=12, weight="bold", pad=10)
    fig.tight_layout()
    fig.savefig(caminho, dpi=DPI, facecolor="white")
    plt.close(fig)
    return caminho


# ---------------------------------------------------------------------------
# Figura 4 — Evidencia de multiprocessing (PIDs)
# ---------------------------------------------------------------------------
def fig_multiprocessing(caminho="fig4_multiprocessing.png",
                        csv_path="resultados_simulacao.csv", lote=8):
    pids, modos = [], []
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8") as f:
            for linha in csv.DictReader(f):
                try:
                    pids.append(int(linha["PID"]))
                    modos.append(int(linha["Modo"]))
                except (ValueError, KeyError):
                    pass
    origem = "dados reais da simulacao"
    if not pids:  # sem CSV: dados ilustrativos
        pids = list(range(9000, 9000 + 50 * 37, 37))
        modos = [1 if i % 2 else 2 for i in range(len(pids))]
        origem = "dados ilustrativos (rode o Monte Carlo para dados reais)"

    # PIDs distintos DENTRO de cada lote: e' isso que comprova a simultaneidade.
    # Entre lotes o sistema operacional reaproveita identificadores ja liberados,
    # entao o total de PIDs distintos e' menor que o numero de UEs.
    lotes = [pids[i:i + lote] for i in range(0, len(pids), lote)]
    lotes_limpos = sum(1 for L in lotes if len(set(L)) == len(L))

    fig, ax = plt.subplots(figsize=(9.5, 4.4))
    xs = range(1, len(pids) + 1)
    cores = [AZUL if m == 1 else VERMELHO for m in modos]
    ax.scatter(xs, pids, c=cores, s=26, edgecolor="black", linewidth=0.4, zorder=3)

    # Separadores de lote (sem poluir quando ha muitos lotes)
    if len(lotes) <= 30:
        for k in range(lote, len(pids), lote):
            ax.axvline(k + 0.5, color="#cccccc", linewidth=0.7, zorder=1)

    ax.set_xlabel(f"UE simulado (linhas verticais separam os lotes de {lote} processos)")
    ax.set_ylabel("PID do processo")
    ax.grid(axis="y", alpha=0.3)
    ax.set_title(f"Figura 4 - Cada UE executou em um processo proprio\n"
                 f"{len(pids)} UEs em {len(lotes)} lotes de {lote} processos "
                 f"simultaneos, todos com PID distinto dentro do lote "
                 f"({lotes_limpos}/{len(lotes)})", fontsize=11.5, weight="bold", pad=10)

    from matplotlib.lines import Line2D
    ax.legend(handles=[
        Line2D([0], [0], marker="o", color="w", markerfacecolor=AZUL,
               markeredgecolor="black", markersize=8, label="DRX"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=VERMELHO,
               markeredgecolor="black", markersize=8, label="Blind Search"),
    ], loc="upper right", fontsize=9)
    fig.text(0.5, 0.015,
             f"{len(set(pids))} PIDs distintos no total: entre lotes o sistema "
             f"operacional reaproveita identificadores ja liberados",
             ha="center", fontsize=8.5, color="#444444")
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    fig.savefig(caminho, dpi=DPI, facecolor="white")
    plt.close(fig)
    return caminho


if __name__ == "__main__":
    for gerar in (fig_arquitetura, fig_drx_vs_blind, fig_transicao,
                  fig_multiprocessing):
        print("gerado:", gerar())
    print("\nPronto. Insira as figuras na secao 7 (Metodologia) do relatorio.")
