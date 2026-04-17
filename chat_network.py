import json
import random
import socket
import threading
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

from config_loader import RouterInfo
from local_logger import NodeLogger
from routing import build_forwarding_table


TIPO_DADOS = "msg"
TIPO_ACK = "ack"


@dataclass
class Mensagem:
    timestamp: str
    msg_id: str
    seq: int
    tipo_pacote: str
    origem_id: int
    destino_id: int
    ultimo_hop_id: int
    conteudo: str = ""

    def serializar(self) -> bytes:
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    @staticmethod
    def desserializar(dados: bytes) -> "Mensagem":
        return Mensagem(**json.loads(dados.decode("utf-8")))

    def hora(self) -> str:
        return self.timestamp[11:16]


@dataclass
class _OutboundTask:
    msg: Mensagem
    next_hop_id: int


class No:
    def __init__(
        self,
        router_id: int,
        routers: Dict[int, RouterInfo],
        graph: Dict[int, Dict[int, int]],
        drop_rate: float = 0.10,
        ack_timeout: float = 0.7,
    ):
        if router_id not in routers:
            raise ValueError(f"ID de roteador desconhecido: {router_id}")

        self.router_id = router_id
        self.routers = routers
        self.graph = graph
        self.drop_rate = drop_rate
        self.ack_timeout = ack_timeout
        self.routing_table = build_forwarding_table(graph, router_id)

        local = self.routers[self.router_id]
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", local.port))

        self._logger = NodeLogger(router_id=self.router_id)

        self._historico: Dict[str, Deque[dict]] = {
            str(rid): deque(maxlen=300) for rid in self.routers if rid != self.router_id
        }

        self._lock = threading.Lock()
        self._rodando = True
        self._callback_nova_msg: Optional[Callable[[str], None]] = None

        self._fila_envio: Deque[_OutboundTask] = deque()
        self._fila_cv = threading.Condition()

        self._ack_event = threading.Event()
        self._ack_lock = threading.Lock()
        self._aguardando_msg_id: Optional[str] = None
        self._aguardando_hop_id: Optional[int] = None

        self._seq = 0
        self._vistos: Set[str] = set()
        self._fila_vistos: Deque[str] = deque(maxlen=5000)

        threading.Thread(target=self._loop_escuta, daemon=True).start()
        threading.Thread(target=self._loop_envio, daemon=True).start()

    def _agora(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _notificar(self, conversa: str):
        if self._callback_nova_msg:
            self._callback_nova_msg(conversa)

    def _garantir_conversa(self, conversa: str):
        if conversa not in self._historico:
            self._historico[conversa] = deque(maxlen=300)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _resolver_proximo_hop(self, destino_id: int) -> Optional[int]:
        if destino_id == self.router_id:
            return self.router_id
        rota = self.routing_table.get(destino_id)
        if not rota:
            return None
        return rota[0]

    def _enfileirar_envio(self, task: _OutboundTask):
        with self._fila_cv:
            self._fila_envio.append(task)
            self._fila_cv.notify()

    def _enviar_udp(self, msg: Mensagem, destino_hop_id: int):
        endpoint = self.routers[destino_hop_id].endpoint
        self._sock.sendto(msg.serializar(), endpoint)

    def _enviar_ack(self, data_msg: Mensagem):
        destino_hop = data_msg.ultimo_hop_id
        if destino_hop not in self.routers:
            return

        ack = Mensagem(
            timestamp=self._agora(),
            msg_id=data_msg.msg_id,
            seq=data_msg.seq,
            tipo_pacote=TIPO_ACK,
            origem_id=self.router_id,
            destino_id=destino_hop,
            ultimo_hop_id=self.router_id,
            conteudo="",
        )
        self._enviar_udp(ack, destino_hop)

    def _marcar_visto(self, msg_id: str) -> bool:
        if msg_id in self._vistos:
            return False

        self._vistos.add(msg_id)
        self._fila_vistos.append(msg_id)

        if len(self._fila_vistos) == self._fila_vistos.maxlen:
            while len(self._vistos) > self._fila_vistos.maxlen:
                antigo = self._fila_vistos.popleft()
                self._vistos.discard(antigo)

        return True

    def enviar(self, destino_id: int, conteudo: str) -> tuple[bool, str]:
        texto = conteudo.strip()
        if not texto:
            return False, "Mensagem vazia."
        if len(texto) > 100:
            return False, "Payload excede 100 caracteres."
        if destino_id == self.router_id:
            return False, "Use um destino diferente do roteador local."
        if destino_id not in self.routers:
            return False, f"Destino desconhecido: {destino_id}."

        next_hop = self._resolver_proximo_hop(destino_id)
        if next_hop is None:
            return False, f"Sem rota para destino {destino_id}."

        msg = Mensagem(
            timestamp=self._agora(),
            msg_id=str(uuid.uuid4()),
            seq=self._next_seq(),
            tipo_pacote=TIPO_DADOS,
            origem_id=self.router_id,
            destino_id=destino_id,
            ultimo_hop_id=self.router_id,
            conteudo=texto,
        )

        conversa = str(destino_id)
        with self._lock:
            self._garantir_conversa(conversa)
            self._historico[conversa].append({"tipo": "eu", "msg": msg})

        self._logger.log_enviada(
            msg_id=msg.msg_id,
            seq=msg.seq,
            origem=msg.origem_id,
            destino=msg.destino_id,
            proximo_hop=next_hop,
            conteudo=msg.conteudo,
        )

        self._enfileirar_envio(_OutboundTask(msg=msg, next_hop_id=next_hop))
        return True, f"Mensagem enfileirada para destino {destino_id}."

    def _loop_envio(self):
        while self._rodando:
            with self._fila_cv:
                while self._rodando and not self._fila_envio:
                    self._fila_cv.wait()

                if not self._rodando:
                    break

                task = self._fila_envio.popleft()

            tentativa = 0
            while self._rodando:
                tentativa += 1
                with self._ack_lock:
                    self._aguardando_msg_id = task.msg.msg_id
                    self._aguardando_hop_id = task.next_hop_id
                    self._ack_event.clear()

                if tentativa == 1:
                    print(
                        f"Roteador [{self.router_id}] encaminhando mensagem "
                        f"(Seq: {task.msg.seq}) para o destino {task.msg.destino_id} "
                        f"via {task.next_hop_id}"
                    )
                else:
                    print(
                        f"Roteador [{self.router_id}] reenviando mensagem "
                        f"(Seq: {task.msg.seq}) para o destino {task.msg.destino_id} "
                        f"via {task.next_hop_id} (tentativa {tentativa})"
                    )

                self._enviar_udp(task.msg, task.next_hop_id)
                recebeu_ack = self._ack_event.wait(self.ack_timeout)

                if recebeu_ack:
                    with self._ack_lock:
                        self._aguardando_msg_id = None
                        self._aguardando_hop_id = None
                    break

                print(
                    f"Roteador [{self.router_id}] timeout aguardando ACK "
                    f"(Seq: {task.msg.seq}) de {task.next_hop_id}"
                )

    def _loop_escuta(self):
        while self._rodando:
            try:
                dados, _ = self._sock.recvfrom(65535)
                msg = Mensagem.desserializar(dados)
                if msg.tipo_pacote == TIPO_ACK:
                    self._processar_ack(msg)
                elif msg.tipo_pacote == TIPO_DADOS:
                    self._processar_dados(msg)
            except OSError:
                break
            except Exception:
                continue

    def _processar_ack(self, msg: Mensagem):
        if msg.destino_id != self.router_id:
            return

        with self._ack_lock:
            if (
                msg.msg_id == self._aguardando_msg_id
                and msg.origem_id == self._aguardando_hop_id
            ):
                self._ack_event.set()

    def _processar_dados(self, msg: Mensagem):
        if random.random() < self.drop_rate:
            self._logger.log_descarte(
                msg_id=msg.msg_id,
                seq=msg.seq,
                origem=msg.origem_id,
                destino=msg.destino_id,
                motivo="descarte_aleatorio_10pct",
            )
            print(
                f"Roteador [{self.router_id}] descartou mensagem "
                f"(Seq: {msg.seq}) para destino {msg.destino_id}"
            )
            return

        self._enviar_ack(msg)

        if not self._marcar_visto(msg.msg_id):
            return

        if msg.destino_id == self.router_id:
            conversa = str(msg.origem_id)
            with self._lock:
                self._garantir_conversa(conversa)
                self._historico[conversa].append({"tipo": "deles", "msg": msg})

            self._logger.log_recebida(
                msg_id=msg.msg_id,
                seq=msg.seq,
                origem=msg.origem_id,
                destino=msg.destino_id,
                conteudo=msg.conteudo,
            )
            print(
                f"Roteador [{self.router_id}] recebeu mensagem "
                f"(Seq: {msg.seq}) do roteador {msg.origem_id}"
            )
            self._notificar(conversa)
            return

        next_hop = self._resolver_proximo_hop(msg.destino_id)
        if next_hop is None:
            self._logger.log_descarte(
                msg_id=msg.msg_id,
                seq=msg.seq,
                origem=msg.origem_id,
                destino=msg.destino_id,
                motivo="sem_rota_para_destino",
            )
            print(
                f"Roteador [{self.router_id}] descartou mensagem "
                f"(Seq: {msg.seq}) por falta de rota para {msg.destino_id}"
            )
            return

        reenvelope = Mensagem(
            timestamp=msg.timestamp,
            msg_id=msg.msg_id,
            seq=msg.seq,
            tipo_pacote=TIPO_DADOS,
            origem_id=msg.origem_id,
            destino_id=msg.destino_id,
            ultimo_hop_id=self.router_id,
            conteudo=msg.conteudo,
        )

        nota = Mensagem(
            timestamp=self._agora(),
            msg_id=msg.msg_id,
            seq=msg.seq,
            tipo_pacote=TIPO_DADOS,
            origem_id=self.router_id,
            destino_id=msg.destino_id,
            ultimo_hop_id=self.router_id,
            conteudo=f'"{msg.conteudo[:40]}" para {msg.destino_id}',
        )
        conversa = str(msg.destino_id)
        with self._lock:
            self._garantir_conversa(conversa)
            self._historico[conversa].append({"tipo": "fwd_sent", "msg": nota})

        self._logger.log_encaminhada(
            msg_id=msg.msg_id,
            seq=msg.seq,
            origem=msg.origem_id,
            destino=msg.destino_id,
            proximo_hop=next_hop,
            conteudo=msg.conteudo,
        )
        self._enfileirar_envio(_OutboundTask(msg=reenvelope, next_hop_id=next_hop))
        self._notificar(conversa)

    def get_historico(self, conversa: str) -> list:
        with self._lock:
            return list(self._historico.get(conversa, []))

    def listar_conversas(self) -> List[str]:
        with self._lock:
            return sorted(self._historico.keys(), key=lambda x: int(x))

    def tabela_encaminhamento(self) -> Dict[int, Tuple[int, int]]:
        return dict(self.routing_table)

    def encerrar(self):
        self._rodando = False
        with self._fila_cv:
            self._fila_cv.notify_all()
        try:
            self._sock.close()
        except OSError:
            pass
