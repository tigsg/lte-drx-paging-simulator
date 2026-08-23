"""
campanha_validacao.py — Campanha de validacao: DRX x Blind Search.

Compara os dois modos numa mesma populacao e produz a figura de duas faces do
compromisso: a distribuicao de latencia e o consumo medio de cada modo.

Duas decisoes de medicao, alinhadas com a varredura:

  AQUECIMENTO: os UEs escutam varios ciclos completos antes de a paginacao
  poder chegar. Sem isso a janela de observacao fecha cedo demais e o consumo
  do DRX sai inflado (uma campanha sem aquecimento indicou 2,46% para o ciclo
  16, contra 0,63% previstos pela teoria).

  POPULACAO GRANDE: 100 amostras por modo. Com 25, o histograma do DRX tem
  menos de uma amostra por caixa e a distribuicao uniforme nao aparece.

Pre-requisito: enodeb.py rodando em outro terminal.
Uso:  python campanha_validacao.py
"""
from __future__ import annotations

import csv
import multiprocessing as mp

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

QTD_UES = 200
CICLO = 16                      # frames; ciclo completo = 160 subframes
AQUECIMENTO_SF = max(200, 20 * CICLO)
TIMEOUT = 60

AZUL, VERMELHO = "#3b6fd4", "#e05c4b"


def _figura(drx_lat: list[int], bl_lat: list[int],
            drx_cpu: float, bl_cpu: float,
            caminho: str = "grafico_latencia_lte.png") -> None:
    """Duas faces do compromisso: latencia a esquerda, consumo a direita."""
    ciclo_sf = CICLO * 10
    fig, (ax_lat, ax_cpu) = plt.subplots(
        1, 2, figsize=(13, 5), gridspec_kw={"width_ratios": [2.2, 1]})

    # --- Esquerda: distribuicao de latencia, os dois modos no mesmo eixo ---
    bins = range(0, ciclo_sf + 11, 10)
    ax_lat.hist(drx_lat, bins=bins, color=AZUL, edgecolor="black",
                alpha=0.85, label=f"DRX (n={len(drx_lat)})")

    # Densidade teorica de uma uniforme em [0, ciclo_sf]: n * largura / ciclo
    esperado = len(drx_lat) * 10 / ciclo_sf
    ax_lat.axhline(esperado, color="black", linestyle=":", linewidth=1.6,
                   label="densidade uniforme prevista")

    media_drx = sum(drx_lat) / len(drx_lat)
    ax_lat.axvline(media_drx, color="darkblue", linestyle="--", linewidth=2,
                   label=f"media DRX = {media_drx:.1f} sf")

    # Blind concentra-se todo em ~1 sf: uma barra real seria n vezes mais alta
    # que as do DRX e esmagaria a escala, entao entra como marca anotada.
    ax_lat.axvline(sum(bl_lat) / len(bl_lat), color=VERMELHO, linewidth=3)

    # Folga no topo para a anotacao e a legenda nao colidirem com as barras.
    topo = max(len([v for v in drx_lat if b <= v < b + 10]) for b in bins[:-1])
    ax_lat.set_ylim(0, topo * 1.42)
    ax_lat.annotate(f"Blind Search: os {len(bl_lat)} UEs em 1 sf",
                    xy=(1, topo * 1.10), xytext=(ciclo_sf * 0.10, topo * 1.30),
                    color=VERMELHO, fontsize=9.5,
                    arrowprops=dict(arrowstyle="->", color=VERMELHO, linewidth=1.4))

    ax_lat.set_xlabel("Latencia (subframes)")
    ax_lat.set_ylabel("Numero de UEs")
    ax_lat.set_title("Distribuicao da latencia", fontweight="bold")
    ax_lat.set_xlim(0, ciclo_sf)
    ax_lat.legend(fontsize=9, loc="upper right")
    ax_lat.grid(axis="y", alpha=0.3)

    # --- Direita: o preco em consumo ---
    barras = ax_cpu.bar(["DRX", "Blind\nSearch"], [drx_cpu, bl_cpu],
                        color=[AZUL, VERMELHO], edgecolor="black", width=0.55)
    for b, v in zip(barras, [drx_cpu, bl_cpu]):
        ax_cpu.text(b.get_x() + b.get_width() / 2, v + 2.5, f"{v:.2f}%",
                    ha="center", fontsize=11, fontweight="bold")
    ax_cpu.set_ylabel("Subframes processados (%)")
    ax_cpu.set_ylim(0, 118)
    ax_cpu.set_title("Consumo de radio", fontweight="bold")
    ax_cpu.grid(axis="y", alpha=0.3)
    if drx_cpu > 0:
        ax_cpu.text(0.5, 62, f"{bl_cpu / drx_cpu:.0f}x mais\nconsumo",
                    ha="center", fontsize=10, style="italic", color="#333333")

    fig.suptitle(f"Campanha de validacao: ciclo DRX de {CICLO} frames "
                 f"({ciclo_sf} subframes)", fontsize=13, fontweight="bold")
    plt.tight_layout(rect=(0, 0.03, 1, 0.94))
    fig.text(0.5, 0.015,
             "Blind Search responde mais rapido; o DRX gasta uma fracao do radio",
             ha="center", fontsize=8.5, color="#444444")
    plt.savefig(caminho, dpi=150)
    plt.close()


def main() -> None:
    import monte_carlo as mc  # noqa: F401  (import tardio: precisa do guard)

    print(f"\n{'='*62}\n  CAMPANHA DE VALIDACAO\n"
          f"  {QTD_UES} UEs | ciclo {CICLO} frames | aquecimento "
          f"{AQUECIMENTO_SF} sf\n{'='*62}")

    from ue import DRXConfig
    res = mc.run_monte_carlo(qtd=QTD_UES, fracao_drx=0.5, timeout=TIMEOUT,
                             delay_paging=AQUECIMENTO_SF,
                             drx=DRXConfig(short_cycle=CICLO, long_cycle=2 * CICLO,
                                           limite_curto=10**9),
                             gerar_saidas=False, verbose=True)

    ok = [r for r in res if r.sucesso]
    drx = [r for r in ok if r.modo == 1]
    bl = [r for r in ok if r.modo == 2]
    drx_lat = [r.latencia for r in drx]
    bl_lat = [r.latencia for r in bl]
    drx_cpu = sum(r.eficiencia for r in drx) / len(drx)
    bl_cpu = sum(r.eficiencia for r in bl) / len(bl)

    with open("resultados_simulacao.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ID", "PID", "IMSI", "UE_ID", "Modo", "Sucesso",
                    "Latencia_sf", "CPU_%"])
        for i, r in enumerate(res, 1):
            w.writerow([i, r.pid, r.imsi, r.ue_id, r.modo,
                        "OK" if r.sucesso else "TIMEOUT",
                        r.latencia if r.sucesso else "", f"{r.eficiencia:.2f}"])

    _figura(drx_lat, bl_lat, drx_cpu, bl_cpu)

    print(f"\n{'='*62}\n  RESULTADO\n{'='*62}")
    print(f"  DRX   n={len(drx):3d} | latencia media={sum(drx_lat)/len(drx_lat):6.1f} sf "
          f"[{min(drx_lat)}..{max(drx_lat)}] | consumo={drx_cpu:.2f}%")
    print(f"  BLIND n={len(bl):3d} | latencia media={sum(bl_lat)/len(bl_lat):6.1f} sf "
          f"[{min(bl_lat)}..{max(bl_lat)}] | consumo={bl_cpu:.2f}%")
    print(f"  Timeouts: {len(res) - len(ok)}/{len(res)} | "
          f"PIDs unicos: {len({r.pid for r in res})}")
    print(f"  Previsto: latencia {CICLO*10/2:.0f} sf | consumo {100/(CICLO*10):.2f}%")
    print("  Arquivos: resultados_simulacao.csv | grafico_latencia_lte.png")


if __name__ == "__main__":
    mp.freeze_support()
    main()
