"""
monte_carlo_novo.py — Monte Carlo LTE com multiprocessing.

Cada UE corre no seu proprio processo (mp.Process) e abre o seu proprio
socket UDP:9999 — no Windows, SO_REUSEADDR deixa varios sockets receberem
o mesmo broadcast, por isso nao e' preciso receptor central nem filas.

O main process e' sequencial: spawn -> paging -> recolhe resultados, lote a lote.
A unica estrutura partilhada e' a result_queue.

Tunar ciclos DRX: edite DRX_BASE (todos os UEs) ou config_drx() (por UE).
Ver multiprocessing (Windows): Get-Process python | ft Id,CPU,WS
"""
from __future__ import annotations

import csv
import multiprocessing as mp
import os
import queue
import random
import socket
import time

import matplotlib.pyplot as plt

from ue import DRXConfig, ResultadoUE, processo_ue

# --- Configuracoes ---
QTD_UES_TOTAL: int = 50
TAMANHO_LOTE: int = min(8, os.cpu_count() or 4)  # processos simultaneos
TIMEOUT_UE: int = 30
FRACAO_DRX: float = 0.5                           # 0.5 = metade DRX, metade Blind
DELAY_PAGING_SF: int = 0                          # >0 atrasa paging p/ forcar curto->longo
DRX_BASE = DRXConfig(short_cycle=16, long_cycle=32, limite_curto=3)


def config_drx(indice: int) -> DRXConfig:
    """Config DRX de cada UE. Edite para variar os tempos por UE, ex.:
        return random.choice([DRXConfig(8, 32, 2), DRXConfig(16, 64, 4)])"""
    return DRX_BASE


def run_monte_carlo(*, qtd: int | None = None, lote: int | None = None,
                    timeout: int | None = None, fracao_drx: float | None = None,
                    delay_paging: int | None = None, drx: DRXConfig | None = None,
                    gerar_saidas: bool = True, verbose: bool = True) -> list[ResultadoUE]:
    """
    Corre UMA campanha de simulacao e devolve a lista de ResultadoUE.

    Sem argumentos -> usa as constantes globais (comportamento standalone).
    Os argumentos servem a varredura (varredura.py), que chama esta funcao
    varias vezes com parametros diferentes. `drx` (se dado) aplica-se a todos
    os UEs; caso contrario usa-se config_drx() (que pode variar por UE).
    """
    qtd = QTD_UES_TOTAL if qtd is None else qtd
    lote = TAMANHO_LOTE if lote is None else lote
    timeout = TIMEOUT_UE if timeout is None else timeout
    fracao_drx = FRACAO_DRX if fracao_drx is None else fracao_drx
    delay_paging = DELAY_PAGING_SF if delay_paging is None else delay_paging
    drx_de = (lambda i: drx) if drx is not None else config_drx

    if verbose:
        print(f"\n{'='*60}\n  Monte Carlo LTE — MULTIPROCESSING\n"
              f"  main PID={os.getpid()} | UEs={qtd} | lote={lote}"
              f" | cpu={os.cpu_count()}\n  timeout={timeout}s | "
              f"{drx if drx is not None else DRX_BASE}\n{'='*60}")

    sock_api = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    resultados_q: mp.Queue = mp.Queue()
    resultados: list[ResultadoUE] = []

    # Plano de modos com proporcao exacta.
    n_drx = round(qtd * fracao_drx)
    modos = [1] * n_drx + [2] * (qtd - n_drx)
    random.shuffle(modos)
    if verbose:
        print(f"  Plano: {n_drx} DRX + {qtd - n_drx} Blind\n")

    t0, idx = time.time(), 0
    lotes = [min(lote, qtd - i) for i in range(0, qtd, lote)]

    for n_lote, tam in enumerate(lotes, 1):
        procs: list[mp.Process] = []
        eventos: list = []

        # Arranca um processo por UE.
        for _ in range(tam):
            imsi, modo, cfg = random.randint(10000, 99999), modos[idx], drx_de(idx)
            idx += 1
            ev = mp.Event()
            p = mp.Process(target=processo_ue,
                           args=(imsi, modo, cfg, resultados_q, ev, timeout),
                           name=f"UE-{imsi % 1024:04d}", daemon=True)
            p.start()
            procs.append(p)
            eventos.append(ev)
        if verbose:
            print(f">>> Lote {n_lote}/{len(lotes)} — {tam} UEs | PIDs={[p.pid for p in procs]}")

        # Espera os sockets ligarem, (opcional) atrasa, e dispara os pagings.
        for ev in eventos:
            ev.wait(timeout=15)
        if delay_paging > 0:
            time.sleep(delay_paging * 0.1)  # TEMPO_SUBFRAME = 0.1s no eNodeB
        for p in procs:
            ue_id = int(p.name.split("-")[1])
            sock_api.sendto(str(ue_id).encode(), ("127.0.0.1", 10000))
            time.sleep(0.005)

        # Recolhe 1 resultado por processo (barreira natural) e limpa.
        for _ in range(tam):
            try:
                resultados.append(resultados_q.get(timeout=timeout + 20))
            except queue.Empty:
                break
        for p in procs:
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()
        if verbose:
            ok = sum(r.sucesso for r in resultados)
            print(f"    concluido. OK={ok}/{len(resultados)} | {time.time()-t0:.1f}s")

    tempo_total = time.time() - t0
    sock_api.close()
    if gerar_saidas:
        _exportar_csv(resultados)
        _gerar_grafico(resultados, tempo_total, qtd)
    if verbose:
        _relatorio(resultados, tempo_total, qtd)
    return resultados


def _latencias(resultados: list[ResultadoUE], modo: int) -> list[int]:
    """Latencias validas de um modo (devolve list[int] — Pylance-friendly)."""
    return [r.latencia for r in resultados if r.modo == modo and r.sucesso]


def _exportar_csv(resultados: list[ResultadoUE], caminho: str = "resultados_simulacao.csv") -> None:
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ID", "PID", "IMSI", "UE_ID", "Modo", "Sucesso",
                    "Latencia_sf", "CPU_%", "Ciclos_Curto", "Ciclos_Longo", "Estado_DRX"])
        for i, r in enumerate(resultados, 1):
            estado = ("LONGO" if r.em_longo else "CURTO") if r.modo == 1 else "N/A"
            w.writerow([i, r.pid, r.imsi, r.ue_id, r.modo, "OK" if r.sucesso else "TIMEOUT",
                        r.latencia if r.sucesso else "", f"{r.eficiencia:.2f}",
                        r.ciclos_curto, r.ciclos_longo, estado])


def _hist(ax, dados: list[int], cor: str, titulo: str, bins) -> None:
    if dados:
        media = sum(dados) / len(dados)
        ax.hist(dados, bins=bins, color=cor, edgecolor="black", alpha=0.85)
        ax.axvline(media, color="black", linestyle="--", linewidth=2, label=f"media={media:.1f}")
        ax.legend()
    ax.set_title(f"{titulo}  (n={len(dados)})", fontweight="bold")
    ax.set_xlabel("Latencia (subframes)")
    ax.set_ylabel("Frequencia")
    ax.grid(axis="y", alpha=0.4)


def _gerar_grafico(resultados: list[ResultadoUE], tempo_total: float, qtd: int,
                   caminho: str = "grafico_latencia_lte.png") -> None:
    drx, blind = _latencias(resultados, 1), _latencias(resultados, 2)
    todas = drx + blind
    bins = range(0, max(todas) + 10, 5) if todas else 10

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    _hist(ax1, drx, "royalblue", "DRX / Paging", bins)
    _hist(ax2, blind, "tomato", "Blind Search", bins)
    fig.suptitle(f"LTE Monte Carlo (multiprocessing) — {len(todas)}/{qtd} validas"
                 f" — {tempo_total:.1f}s", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(caminho, dpi=150)
    plt.close()


def _relatorio(resultados: list[ResultadoUE], tempo_total: float, qtd: int) -> None:
    drx, blind = _latencias(resultados, 1), _latencias(resultados, 2)
    pids = {r.pid for r in resultados}
    timeouts = sum(not r.sucesso for r in resultados)
    drx_longo = sum(r.modo == 1 and r.em_longo for r in resultados if r.sucesso)
    media = lambda x: sum(x) / len(x) if x else 0
    print(f"\n{'='*60}\n  SIMULACAO CONCLUIDA\n{'='*60}")
    print(f"  Tempo total      : {tempo_total:.1f}s")
    print(f"  Amostras validas : {len(drx) + len(blind)}/{qtd}")
    print(f"  Timeouts         : {timeouts}")
    print(f"  PIDs unicos      : {len(pids)}  (prova do multiprocessing)")
    print(f"  DRX   lat. media : {media(drx):.1f} sf  (n={len(drx)})")
    print(f"  Blind lat. media : {media(blind):.1f} sf  (n={len(blind)})")
    print(f"  DRX -> ciclo longo: {drx_longo}")
    print(f"  Ficheiros: resultados_simulacao.csv | grafico_latencia_lte.png")


# Guard obrigatorio: sem ele o spawn do Windows re-executa o script.
if __name__ == "__main__":
    mp.freeze_support()
    run_monte_carlo()
