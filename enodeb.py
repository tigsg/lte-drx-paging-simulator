"""
enodeb.py — Estacao base LTE. Transmite o relogio (SFN/subframe) por broadcast
UDP e mantem a lista de pagings activos.

Pagings entram por duas vias:
  - teclado (MME manual): digite um UE_ID e ENTER
  - UDP:10000 (API): ordens automaticas do monte_carlo

JANELA_PAGING >> ciclo longo do UE, senao um UE em ciclo longo pode expirar
antes da sua proxima Paging Occasion. lock_pagings protege o dict partilhado
pelas 3 threads (evita "dict changed size during iteration" e perda de pagings).
"""
from __future__ import annotations

import json
import socket
import threading
import time

TEMPO_SUBFRAME: float = 0.1   # segundos por subframe (rapido p/ Monte Carlo)
PORTA_BROADCAST: int = 9999
CICLO_PAGING: int = 16        # = short_cycle do UE
JANELA_PAGING: int = CICLO_PAGING * 4  # 64 frames de vida do paging

pagings_ativos: dict[int, dict[str, int]] = {}
lock_pagings = threading.Lock()
sfn_global: int = 0
subframe_global: int = 0


def _registrar(alvo_id: int) -> None:
    with lock_pagings:
        pagings_ativos[alvo_id] = {
            "frames_restantes": JANELA_PAGING,
            "sfn_criacao": sfn_global,
            "sf_criacao": subframe_global,
        }


def escutar_mme() -> None:
    """Thread: chamadas manuais via teclado."""
    while True:
        try:
            entrada = input()
        except EOFError:
            return  # sem stdin interativo (lancado por script): encerra a thread
        except ValueError:
            continue
        if entrada.isdigit():
            _registrar(int(entrada))
            print(f"\n[MME] Paging para UE_ID {entrada} em [{sfn_global},{subframe_global}]")


def escutar_api_monte_carlo() -> None:
    """Thread: chamadas automaticas via UDP:10000 (do monte_carlo)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 10000))
    while True:
        try:
            dados, _ = sock.recvfrom(1024)
            _registrar(int(dados.decode("utf-8")))
        except (ValueError, OSError):
            pass


def iniciar_enodeb() -> None:
    global sfn_global, subframe_global

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    threading.Thread(target=escutar_mme, daemon=True).start()
    threading.Thread(target=escutar_api_monte_carlo, daemon=True).start()

    print(" eNodeB iniciado! A transmitir o relogio LTE...")
    print("  Chamada manual: digite o UE_ID e ENTER.\n")

    try:
        while True:
            # Snapshot da lista de pagings sob lock.
            with lock_pagings:
                lista = [
                    {"ue_id": uid, "sfn_criacao": i["sfn_criacao"], "sf_criacao": i["sf_criacao"]}
                    for uid, i in pagings_ativos.items()
                ]
            msg = {"sfn": sfn_global, "subframe": subframe_global, "paging_list": lista}
            sock.sendto(json.dumps(msg).encode("utf-8"), ("<broadcast>", PORTA_BROADCAST))
            time.sleep(TEMPO_SUBFRAME)

            # Avanca o relogio.
            subframe_global += 1
            if subframe_global > 9:
                subframe_global = 0
                sfn_global = (sfn_global + 1) % 1024
                # Envelhece e remove pagings expirados (sob lock).
                with lock_pagings:
                    expirados = []
                    for uid, info in pagings_ativos.items():
                        info["frames_restantes"] -= 1
                        if info["frames_restantes"] <= 0:
                            expirados.append(uid)
                    for uid in expirados:
                        del pagings_ativos[uid]
    except KeyboardInterrupt:
        print("\n eNodeB desligado.")
        sock.close()


if __name__ == "__main__":
    iniciar_enodeb()
