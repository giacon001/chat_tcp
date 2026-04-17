import json
import socket
import threading
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set, Tuple


@dataclass
class Mensagem:
    # Momento em que a mensagem foi criada (ISO string).
    timestamp: str
    # Identidade do autor original da mensagem.
    remetente_nome: str
    remetente_ip: str
    remetente_porta: int
    # Destino final previsto no pacote.
    dest_nome: str
    dest_ip: str
    dest_porta: int
    # Conteúdo textual da mensagem.
    conteudo: str
    # Flags de encaminhamento.
    encaminhado: bool = False
    encaminhado_por: Optional[str] = None

    def serializar(self) -> bytes:
        # Dataclass -> dict -> JSON UTF-8 bytes, formato transmitido no UDP.
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    @staticmethod
    def desserializar(dados: bytes) -> "Mensagem":
        # Inverso da serialização: bytes -> dict -> objeto Mensagem.
        return Mensagem(**json.loads(dados.decode("utf-8")))

    def hora(self) -> str:
        # Recorte simples de HH:MM do timestamp ISO.
        return self.timestamp[11:16]


@dataclass
class Vizinho:
    nome: str
    ip: str
    porta: int

    @property
    def endereco(self) -> tuple[str, int]:
        # Tupla imutável (ip, porta) para uso em sendto/recvfrom.
        return (self.ip, self.porta)


class No:
    def __init__(self, nome: str, ip: str, porta: int, vizinhos: List[Vizinho]):
        # Identidade local do nó.
        self.nome = nome
        self.ip = ip
        self.porta = porta
        self.vizinhos = vizinhos

        # Socket UDP IPv4.
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Escuta em todas as interfaces, na porta local informada.
        self._sock.bind(("0.0.0.0", self.porta))

        # dict de endpoint exato -> alias local da conversa.
        # Ex.: ("127.0.0.1", 5002) -> "No_B"
        # Isso evita colisão quando vários nós compartilham o mesmo IP.
        self._alias_por_endpoint: Dict[Tuple[str, int], str] = {
            (v.ip, v.porta): v.nome for v in vizinhos
        }

        # dict de IP -> conjunto de aliases conhecidos naquele IP.
        # Usado como fallback quando endpoint exato não é encontrado.
        self._aliases_por_ip: Dict[str, Set[str]] = {}
        for v in vizinhos:
            self._aliases_por_ip.setdefault(v.ip, set()).add(v.nome)

        # Histórico por conversa (tipo + mensagem).
        self._historico: Dict[str, deque] = {v.nome: deque(maxlen=300) for v in vizinhos}
        # Cópias "cruas" das mensagens recebidas/armazenadas.
        self._brutas: Dict[str, deque] = {v.nome: deque(maxlen=100) for v in vizinhos}

        # Lock para proteger estruturas compartilhadas entre threads.
        self._lock = threading.Lock()
        self._rodando = True
        # Callback opcional para avisar camada de interface.
        self._callback_nova_msg: Optional[Callable[[str], None]] = None

        # Thread daemon para escutar pacotes sem bloquear a CLI.
        threading.Thread(target=self._loop_escuta, daemon=True).start()

    def _agora(self) -> str:
        # Timestamp local em ISO sem frações de segundo.
        return datetime.now().isoformat(timespec="seconds")

    def _notificar(self, conversa: str):
        # Só notifica se a camada de UI registrou callback.
        if self._callback_nova_msg:
            self._callback_nova_msg(conversa)

    def _garantir_conversa(self, conversa: str):
        # Cria as estruturas da conversa sob demanda.
        if conversa not in self._historico:
            self._historico[conversa] = deque(maxlen=300)
            self._brutas[conversa] = deque(maxlen=100)

    def _conversa_por_origem(
        self,
        origem_ip: str,
        origem_porta: int,
        nome_sugerido: str,
    ) -> str:
        # 1) Prioriza endpoint exato (ip,porta).
        endpoint = (origem_ip, origem_porta)
        if endpoint in self._alias_por_endpoint:
            return self._alias_por_endpoint[endpoint]

        # 2) Se IP mapeia para um único alias, usa esse alias.
        aliases = self._aliases_por_ip.get(origem_ip)
        if aliases and len(aliases) == 1:
            return next(iter(aliases))

        # 3) Fallback: nome sugerido; último fallback: "ip:porta".
        return nome_sugerido or f"{origem_ip}:{origem_porta}"

    def enviar(self, destino: Vizinho, conteudo: str):
        # Monta pacote normal (não encaminhado).
        msg = Mensagem(
            timestamp=self._agora(),
            remetente_nome=self.nome,
            remetente_ip=self.ip,
            remetente_porta=self.porta,
            dest_nome=destino.nome,
            dest_ip=destino.ip,
            dest_porta=destino.porta,
            conteudo=conteudo,
            encaminhado=False,
        )
        # Fire-and-forget UDP: não há confirmação de entrega no protocolo.
        self._sock.sendto(msg.serializar(), destino.endereco)

        with self._lock:
            self._garantir_conversa(destino.nome)
            self._historico[destino.nome].append({"tipo": "eu", "msg": msg})

    def encaminhar(self, msg_original: Mensagem, destino: Vizinho):
        # Encaminhamento preserva autor original e marca quem encaminhou.
        msg = Mensagem(
            timestamp=self._agora(),
            remetente_nome=msg_original.remetente_nome,
            remetente_ip=msg_original.remetente_ip,
            remetente_porta=msg_original.remetente_porta,
            dest_nome=destino.nome,
            dest_ip=destino.ip,
            dest_porta=destino.porta,
            conteudo=msg_original.conteudo,
            encaminhado=True,
            encaminhado_por=self.nome,
        )
        self._sock.sendto(msg.serializar(), destino.endereco)

        # Nota local para histórico do encaminhador (não altera autor original).
        nota = Mensagem(
            timestamp=msg.timestamp,
            remetente_nome=self.nome,
            remetente_ip=self.ip,
            remetente_porta=self.porta,
            dest_nome=destino.nome,
            dest_ip=destino.ip,
            dest_porta=destino.porta,
            conteudo=f'"{msg_original.conteudo[:40]}" para {destino.nome}',
            encaminhado=True,
            encaminhado_por=self.nome,
        )

        with self._lock:
            self._garantir_conversa(destino.nome)
            self._historico[destino.nome].append({"tipo": "fwd_sent", "msg": nota})

    def _loop_escuta(self):
        # Loop de recepção até encerrar o nó.
        while self._rodando:
            try:
                # recvfrom retorna bytes + tupla de origem (ip, porta).
                dados, origem = self._sock.recvfrom(65535)
                msg = Mensagem.desserializar(dados)
                self._processar(msg, origem)
            except OSError:
                # Socket fechado durante encerrar().
                break
            except Exception:
                # Em produção, aqui caberia log; por simplicidade, continua escutando.
                continue

    def _processar(self, msg: Mensagem, origem: Tuple[str, int]):
        # Origem real do pacote na rede.
        origem_ip, origem_porta = origem
        # Em encaminhadas, conversa tende a ser do nó que encaminhou.
        nome_sugerido = msg.encaminhado_por if msg.encaminhado and msg.encaminhado_por else msg.remetente_nome
        conversa = self._conversa_por_origem(
            origem_ip,
            origem_porta,
            nome_sugerido,
        )
        # Tipo de histórico para renderização na UI.
        tipo = "fwd" if msg.encaminhado else "deles"

        with self._lock:
            self._garantir_conversa(conversa)
            self._historico[conversa].append({"tipo": tipo, "msg": msg})
            # deep copy para preservar snapshot bruto da mensagem.
            self._brutas[conversa].append(deepcopy(msg))

        # Dispara callback para atualizar interface/contadores.
        self._notificar(conversa)

    def get_historico(self, conversa: str) -> list:
        # Retorna cópia em lista para evitar exposição da deque interna.
        with self._lock:
            return list(self._historico.get(conversa, []))

    def get_brutas(self, conversa: str) -> List[Mensagem]:
        with self._lock:
            return list(self._brutas.get(conversa, []))

    def listar_conversas(self) -> List[str]:
        with self._lock:
            return list(self._historico.keys())

    def encerrar(self):
        # Sinaliza parada e fecha socket para destravar recvfrom.
        self._rodando = False
        try:
            self._sock.close()
        except OSError:
            pass
