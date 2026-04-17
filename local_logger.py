import threading
from datetime import datetime
from pathlib import Path


class NodeLogger:
    def __init__(self, router_id: int, logs_dir: str = "logs"):
        self._lock = threading.Lock()
        base = Path(logs_dir)
        base.mkdir(parents=True, exist_ok=True)
        self.file_path = base / f"roteador_{router_id}.log"

    def _write(self, categoria: str, texto: str):
        timestamp = datetime.now().isoformat(timespec="seconds")
        linha = f"{timestamp} | {categoria} | {texto}\n"
        with self._lock:
            with self.file_path.open("a", encoding="utf-8") as fp:
                fp.write(linha)

    def log_enviada(
        self,
        msg_id: str,
        seq: int,
        origem: int,
        destino: int,
        proximo_hop: int,
        conteudo: str,
    ):
        self._write(
            "Enviadas",
            (
                f"msg_id={msg_id} seq={seq} origem={origem} destino={destino} "
                f"proximo_hop={proximo_hop} conteudo={conteudo}"
            ),
        )

    def log_encaminhada(
        self,
        msg_id: str,
        seq: int,
        origem: int,
        destino: int,
        proximo_hop: int,
        conteudo: str,
    ):
        self._write(
            "Encaminhadas",
            (
                f"msg_id={msg_id} seq={seq} origem={origem} destino={destino} "
                f"proximo_hop={proximo_hop} conteudo={conteudo}"
            ),
        )

    def log_recebida(
        self,
        msg_id: str,
        seq: int,
        origem: int,
        destino: int,
        conteudo: str,
    ):
        self._write(
            "Recebidas",
            f"msg_id={msg_id} seq={seq} origem={origem} destino={destino} conteudo={conteudo}",
        )

    def log_descarte(
        self,
        msg_id: str,
        seq: int,
        origem: int,
        destino: int,
        motivo: str,
    ):
        self._write(
            "Descartes",
            f"msg_id={msg_id} seq={seq} origem={origem} destino={destino} motivo={motivo}",
        )
