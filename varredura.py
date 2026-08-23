"""
varredura.py — Varredura de parametros (parameter sweep) do simulador LTE.

Executa o Monte Carlo uma vez por tamanho de ciclo DRX e desenha o trade-off
central do estudo:

    ciclo maior  ->  o UE acorda menos  ->  consumo DESCE, latencia SOBE
    ciclo menor  ->  acorda mais        ->  latencia DESCE, consumo SOBE

Com REPETICOES > 1 a varredura inteira e' repetida e as amostras sao agrupadas
por ciclo. Isso estabiliza as medias: com 20 UEs por ponto uma execucao isolada
ainda oscila; tres execucoes dao 60 amostras por ciclo.

A varredura usa apenas UEs em DRX. O Blind Search e' constante por definicao
(latencia ~1 sf, consumo 100%) e entra no grafico como referencia anotada.

Pre-requisito : enodeb.py rodando em outro terminal.
Restricao     : long_cycle (= 2x o ciclo varrido) deve caber na JANELA_PAGING
                do eNodeB (64 frames) -> ciclo varrido max = 32.
"""
from __future__ import annotations

import csv
import multiprocessing as mp
from statistics import mean, median

import matplotlib.pyplot as plt

import monte_carlo as mc
from ue import DRXConfig, ResultadoUE

# --- O que varrer (edite aqui) ---
EIXO_X_LABEL = "Ciclo DRX (frames)"
VALORES = [2, 4, 8, 16]     # tamanhos de ciclo a testar (1 valor = 1 Monte Carlo)
UES_POR_PONTO = 20          # UEs por ponto em cada execucao
REPETICOES = 3              # execucoes da varredura inteira (amostras se somam)
TIMEOUT_SWEEP = 60          # tem de cobrir aquecimento + latencia maxima + spawn


def montar_kwargs(valor: int) -> dict:
    """Parametros do Monte Carlo para um ponto da varredura.

    Duas decisoes de desenho experimental:

    1. AQUECIMENTO (delay_paging): o UE escuta varios ciclos completos ANTES de
       o paging poder chegar. Sem isto, a janela de medicao termina no 1.o-2.o
       despertar e o racio processados/observados fica inflacionado (~2-3x
       acima do duty cycle real) e "achatado" entre ciclos vizinhos.

    2. TRANSICAO DESLIGADA (limite_curto enorme): a varredura mede um ciclo
       FIXO; com o limite normal, UEs que acordam em vao durante o aquecimento
       migrariam para o ciclo longo a meio da medicao, contaminando o ponto.
       (A transicao continua ativa no monte_carlo.py standalone.)
    """
    aquecimento = max(200, 20 * valor)   # >= 20 s de escuta e >= 2 ciclos
    return dict(qtd=UES_POR_PONTO, lote=UES_POR_PONTO, fracao_drx=1.0,
                timeout=TIMEOUT_SWEEP, delay_paging=aquecimento,
                drx=DRXConfig(short_cycle=valor, long_cycle=2 * valor,
                              limite_curto=10**9))


def _agregar(amostras: list[ResultadoUE], ciclo: int, falhas: int) -> dict:
    """Reduz as amostras de um ciclo a uma linha de metricas."""
    lats = sorted(r.latencia for r in amostras)
    cpus = [r.eficiencia for r in amostras]
    return {
        "ciclo": ciclo,
        "n": len(amostras),
        "lat_media": round(mean(lats), 1) if lats else 0.0,
        "lat_mediana": round(median(lats), 1) if lats else 0.0,
        "lat_min": min(lats) if lats else 0,
        "lat_max": max(lats) if lats else 0,
        "cpu_media": round(mean(cpus), 2) if cpus else 0.0,
        "timeouts": falhas,
    }


def _exportar_csv(pontos: list[dict], caminho: str = "resultados_varredura.csv") -> None:
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(pontos[0].keys()))
        w.writeheader()
        for p in pontos:
            w.writerow({k: (f"{v:.2f}" if isinstance(v, float) else v)
                        for k, v in p.items()})


def _exportar_bruto(brutos: list[dict], caminho: str = "varredura_bruto.csv") -> None:
    """Uma linha por UE — o rastro completo por tras dos agregados."""
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(brutos[0].keys()))
        w.writeheader()
        w.writerows(brutos)


def _grafico(pontos: list[dict], caminho: str = "grafico_varredura.png") -> None:
    """Trade-off em eixo duplo: latencia (esq., azul) x consumo (dir., vermelho)."""
    xs = [p["ciclo"] for p in pontos]

    fig, ax_lat = plt.subplots(figsize=(9.5, 5.5))
    ax_cpu = ax_lat.twinx()

    l_lat, = ax_lat.plot(xs, [p["lat_media"] for p in pontos], "o-",
                         color="royalblue", linewidth=2, markersize=8,
                         label="Latencia media")
    ax_lat.fill_between(xs, [p["lat_min"] for p in pontos],
                        [p["lat_max"] for p in pontos],
                        color="royalblue", alpha=0.12)
    l_cpu, = ax_cpu.plot(xs, [p["cpu_media"] for p in pontos], "s--",
                         color="tomato", linewidth=2, markersize=8,
                         label="Consumo (% subframes processados)")

    ax_lat.set_xlabel(EIXO_X_LABEL)
    ax_lat.set_ylabel("Latencia (subframes)", color="royalblue")
    ax_cpu.set_ylabel("Consumo — % de subframes processados", color="tomato")
    ax_lat.tick_params(axis="y", labelcolor="royalblue")
    ax_cpu.tick_params(axis="y", labelcolor="tomato")
    ax_lat.set_xticks(xs)
    ax_lat.grid(alpha=0.3)

    ax_lat.legend(handles=[l_lat, l_cpu], loc="upper center")
    n_total = pontos[0].get("n", 0) if pontos else 0
    linha_n = f"{n_total} amostras por ponto\n" if n_total else ""
    ax_lat.text(0.02, 0.03,
                f"{linha_n}Faixa azul: min-max da latencia\n"
                "Referencia Blind Search: latencia ~1 sf | consumo 100%",
                transform=ax_lat.transAxes, fontsize=9, va="bottom",
                bbox=dict(facecolor="lightyellow", boxstyle="round", alpha=0.9))

    fig.suptitle("Trade-off do DRX — ciclo maior: menos consumo, mais latencia",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(caminho, dpi=150)
    plt.close()


def run_varredura() -> None:
    print(f"\n{'#'*62}\n  VARREDURA — ciclos {VALORES} | {UES_POR_PONTO} UEs por "
          f"ponto | {REPETICOES} execucao(oes)\n{'#'*62}")

    brutos: list[dict] = []
    coletadas: dict[int, list[ResultadoUE]] = {c: [] for c in VALORES}
    falhas: dict[int, int] = {c: 0 for c in VALORES}

    for rep in range(1, REPETICOES + 1):
        for ciclo in VALORES:
            res = mc.run_monte_carlo(**montar_kwargs(ciclo),
                                     gerar_saidas=False, verbose=False)
            for r in res:
                brutos.append({
                    "rep": rep, "ciclo": ciclo, "imsi": r.imsi, "ue_id": r.ue_id,
                    "pid": r.pid, "sucesso": int(r.sucesso),
                    "latencia_sf": r.latencia if r.sucesso else "",
                    "consumo_pct": f"{r.eficiencia:.4f}" if r.sucesso else "",
                })
                if r.sucesso:
                    coletadas[ciclo].append(r)
                else:
                    falhas[ciclo] += 1
            ok = sum(r.sucesso for r in res)
            print(f"  rep {rep} | ciclo {ciclo:2d}: {ok}/{len(res)} ok", flush=True)

    pontos = [_agregar(coletadas[c], c, falhas[c]) for c in VALORES]

    _exportar_bruto(brutos)
    _exportar_csv(pontos)
    _grafico(pontos)

    print(f"\n{'#'*62}\n  AGREGADO\n{'#'*62}")
    print(f"  {'ciclo':>5} {'n':>4} {'lat_media':>10} {'faixa':>12} {'consumo':>9}")
    for p in pontos:
        faixa = f"{p['lat_min']}..{p['lat_max']}"
        print(f"  {p['ciclo']:>5} {p['n']:>4} {p['lat_media']:>10.1f} "
              f"{faixa:>12} {p['cpu_media']:>8.2f}%")
    print("\n  Arquivos: varredura_bruto.csv | resultados_varredura.csv | "
          "grafico_varredura.png")


if __name__ == "__main__":
    mp.freeze_support()
    run_varredura()
