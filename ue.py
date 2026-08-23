"""
ue.py — UE LTE com DRX de ciclo curto/longo tunavel.

- DRXConfig  : tempos tunaveis (short_cycle, long_cycle, limite_curto). Um por UE.
- UEDevice   : maquina de estados DRX. Arranca no curto; apos `limite_curto`
               wake-ups sem paging, transita para o longo.
- processo_ue: entry-point do multiprocessing.Process. Cada UE abre o seu
               proprio socket UDP (SO_REUSEADDR permite varios na porta 9999).
"""
from __future__ import annotations

import json
import math
import os
import socket
import sys
import time
from dataclasses import dataclass
from multiprocessing.queues import Queue as MPQueue
from multiprocessing.synchronize import Event as MPEvent

Ns: int = 4
PORTA_BROADCAST: int = 9999
TABELA_PO: dict[int, int] = {0: 0, 1: 4, 2: 5, 3: 9}


@dataclass(frozen=True)
class DRXConfig:
    """Tempos DRX tunaveis (em frames)."""
    short_cycle: int = 16
    long_cycle: int = 32
    limite_curto: int = 3


@dataclass
class ResultadoUE:
    """Resultado de um UE, devolvido pela result_queue."""
    pid: int
    imsi: int
    ue_id: int
    modo: int                        # 1 = DRX, 2 = Blind
    sucesso: bool
    latencia: int = -1               # subframes (-1 = sem dados)
    eficiencia: float = 0.0          # % de subframes processados
    ciclos_curto: int = 0
    ciclos_longo: int = 0
    em_longo: bool = False


class UEDevice:
    def __init__(self, imsi: int, modo: int, drx: DRXConfig | None = None) -> None:
        self.imsi = imsi
        self.ue_id = imsi % 1024
        self.modo = modo
        self.drx = drx or DRXConfig()

        self.pf_short, self.po_short = self._paging_occasion(self.drx.short_cycle)
        self.pf_long, self.po_long = self._paging_occasion(self.drx.long_cycle)

        self.em_longo = False
        self.ciclos_curto = 0
        self.ciclos_longo = 0
        self._tentativas = 0
        self._ultimo_sfn = -1
        self._sf_totais = 0
        self._sf_processados = 0
        self._inicio_escuta = -1   # (sfn, sf) do 1.o pacote observado, em sf absolutos

    def _paging_occasion(self, ciclo: int) -> tuple[int, int]:
        return self.ue_id % ciclo, TABELA_PO[math.floor(self.ue_id / ciclo) % Ns]

    @staticmethod
    def latencia(sfn: int, sf: int, sfn_cri: int, sf_cri: int) -> int:
        agora, criado = sfn * 10 + sf, sfn_cri * 10 + sf_cri
        if agora < criado:
            agora += 1024 * 10  # wrap-around do SFN (0..1023)
        return agora - criado

    def _acordado(self, sfn: int, sf: int) -> bool:
        if self.em_longo:
            ciclo, pf, po = self.drx.long_cycle, self.pf_long, self.po_long
        else:
            ciclo, pf, po = self.drx.short_cycle, self.pf_short, self.po_short
        return sfn % ciclo == pf and sf == po

    def _registrar_wake(self, sfn: int) -> bool:
        """Conta o wake-up (uma vez por SFN) p/ o ciclo activo. True se e' novo."""
        if sfn == self._ultimo_sfn:
            return False
        self._ultimo_sfn = sfn
        if self.em_longo:
            self.ciclos_longo += 1
        else:
            self.ciclos_curto += 1
        return True

    def processar(self, dados: bytes) -> tuple[int, float] | None:
        """Devolve (latencia, eficiencia) se o pacote contiver o meu paging."""
        msg = json.loads(dados.decode("utf-8"))
        sfn, sf = msg["sfn"], msg["subframe"]
        self._sf_totais += 1
        if self._inicio_escuta < 0:
            self._inicio_escuta = sfn * 10 + sf

        wake_novo = False
        if self.modo == 1:                       # DRX: so na Paging Occasion
            if not self._acordado(sfn, sf):
                return None
            wake_novo = self._registrar_wake(sfn)
        # modo 2 (Blind): processa sempre

        self._sf_processados += 1
        for c in msg["paging_list"]:
            if c["ue_id"] == self.ue_id:
                lat = self.latencia(sfn, sf, c["sfn_criacao"], c["sf_criacao"])
                # Paginacao criada ANTES de este UE comecar a escutar: e' residuo
                # de uma execucao anterior cujo ue_id colidiu com o nosso (a
                # janela do eNodeB dura 64 frames). Nao e' o nosso paging.
                escuta = self.latencia(sfn, sf,
                                       self._inicio_escuta // 10,
                                       self._inicio_escuta % 10)
                if lat > escuta:
                    continue
                efi = self._sf_processados / max(self._sf_totais, 1) * 100
                return lat, efi

        # Acordou e o paging NAO estava la: so wakes falhados avancam o timer
        # da transicao curto->longo (encontrar paging e' atividade, nao conta).
        if wake_novo and not self.em_longo:
            self._tentativas += 1
            if self._tentativas >= self.drx.limite_curto:
                self.em_longo = True
        return None

    def escutar_rede(self, ready_event: MPEvent | None = None,
                     timeout: int = 30) -> tuple[int, float] | None:
        """Abre socket UDP:9999 e espera o proprio paging ate `timeout` segundos."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Buffer de 1 MB: sem isto, se o processo for preemptado por alguns
            # segundos (spawn de outros UEs), o buffer default (~64 KB) transborda
            # e datagramas sao descartados -> POs perdidas -> latencia inflada.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
            sock.bind(("", PORTA_BROADCAST))
            sock.settimeout(1.0)
            if ready_event is not None:
                ready_event.set()             # avisa que ja estou a ouvir
            fim = time.time() + timeout
            while time.time() < fim:
                try:
                    dados, _ = sock.recvfrom(65535)
                except socket.timeout:
                    continue                  # deadline global e' que manda
                try:
                    res = self.processar(dados)
                except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
                    continue                  # pacote estranho na porta: ignora
                if res is not None:
                    return res
        return None


def processo_ue(imsi: int, modo: int, drx: DRXConfig,
                result_queue: MPQueue, ready_event: MPEvent, timeout: int) -> None:
    """Alvo do mp.Process: corre num interpretador Python proprio (sem GIL comum).

    Qualquer excecao vira um resultado de falha na fila — o main process nunca
    fica pendurado a espera de um processo que morreu sem responder.
    """
    ue: UEDevice | None = None
    res: tuple[int, float] | None = None
    try:
        ue = UEDevice(imsi, modo, drx)
        res = ue.escutar_rede(ready_event=ready_event, timeout=timeout)
    except Exception:
        res = None
    finally:
        ready_event.set()   # garante que o main nunca espera por processo morto
    result_queue.put(ResultadoUE(
        pid=os.getpid(), imsi=imsi, ue_id=imsi % 1024, modo=modo,
        sucesso=res is not None,
        latencia=res[0] if res else -1,
        eficiencia=res[1] if res else 0.0,
        ciclos_curto=ue.ciclos_curto if ue else 0,
        ciclos_longo=ue.ciclos_longo if ue else 0,
        em_longo=ue.em_longo if ue else False,
    ))


# CLI manual: python ue.py <IMSI> <MODO> [short] [long] [limite]
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python ue.py <IMSI> <MODO: 1=DRX|2=Blind> [short] [long] [limite]")
        sys.exit(1)
    extra = [int(a) for a in sys.argv[3:6]]
    cfg = DRXConfig(*extra) if extra else DRXConfig()
    ue = UEDevice(int(sys.argv[1]), int(sys.argv[2]), cfg)
    print(f"A escutar... ue_id={ue.ue_id} {cfg}")
    res = ue.escutar_rede()
    if res is None:
        print("Timeout: paging nao recebido.")
    else:
        lat, efi = res
        print(f"UE {ue.ue_id} | latencia={lat} sf | CPU={efi:.2f}% | "
              f"ciclos(curto={ue.ciclos_curto}, longo={ue.ciclos_longo})")
