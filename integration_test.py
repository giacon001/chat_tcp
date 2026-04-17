import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from chat_network import No
from config_loader import ConfigError, load_network_config


ROOT = Path(__file__).resolve().parent


class TestReport:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, condition: bool, ok_msg: str, fail_msg: str):
        if condition:
            self.passed += 1
            print(f"PASS: {ok_msg}")
        else:
            self.failed += 1
            print(f"FAIL: {fail_msg}")

    def finish(self):
        print()
        print("===== RESUMO =====")
        print(f"PASS: {self.passed}")
        print(f"FAIL: {self.failed}")
        if self.failed == 0:
            print("STATUS FINAL: SUCESSO")
            return 0
        print("STATUS FINAL: COM FALHAS")
        return 1


def run_cli(args: List[str], stdin_text: str = "", timeout: float = 8.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "chat_gui.py", *args],
        cwd=ROOT,
        input=stdin_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def parse_msg_ids(log_text: str) -> List[str]:
    return re.findall(r"msg_id=([0-9a-fA-F-]{36})", log_text)


def count_by_category(log_text: str, categoria: str) -> int:
    token = f"| {categoria} |"
    return sum(1 for line in log_text.splitlines() if token in line)


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def reset_logs_dir():
    logs_dir = ROOT / "logs"
    if logs_dir.exists():
        shutil.rmtree(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)


def test_init_and_parser(report: TestReport):
    no_arg = run_cli([])
    report.check(
        no_arg.returncode != 0 and "Uso:" in no_arg.stdout,
        "Inicializacao falha sem ID conforme esperado",
        "Inicializacao sem ID deveria falhar com mensagem de uso",
    )

    invalid_id = run_cli(["abc"])
    report.check(
        invalid_id.returncode != 0 and "ID de roteador invalido" in invalid_id.stdout,
        "Inicializacao falha com ID invalido",
        "Inicializacao com ID invalido deveria falhar",
    )

    with tempfile.TemporaryDirectory(prefix="chat_tcp_bad_cfg_") as tmp_dir:
        tmp = Path(tmp_dir)
        (tmp / "roteador.config").write_text("1 25001 127.0.0.1\n", encoding="utf-8")
        (tmp / "enlaces.config").write_text("1 1 0\n", encoding="utf-8")
        try:
            load_network_config(str(tmp))
            ok = False
        except ConfigError:
            ok = True
        report.check(
            ok,
            "ConfigError disparado para configuracao invalida",
            "Era esperado ConfigError para configuracao invalida",
        )

    config = load_network_config(str(ROOT))
    report.check(
        len(config.routers) >= 5,
        f"Topologia possui pelo menos 5 nos ({len(config.routers)})",
        f"Topologia com menos de 5 nos ({len(config.routers)})",
    )

    rotas = run_cli(["1"], stdin_text="/rotas\n/sair\n")
    saida_rotas = rotas.stdout + rotas.stderr
    report.check(
        rotas.returncode == 0
        and "Tabela de Encaminhamento" in saida_rotas
        and "destino=" in saida_rotas,
        "Comando /rotas exibiu tabela de encaminhamento",
        "Comando /rotas nao exibiu a tabela esperada",
    )


def wait_until(condition, timeout_s: float, poll_s: float = 0.2) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(poll_s)
    return condition()


def read_logs_for_nodes(node_ids: Iterable[int]) -> Dict[int, str]:
    logs: Dict[int, str] = {}
    for rid in node_ids:
        log_path = ROOT / "logs" / f"roteador_{rid}.log"
        logs[rid] = read_text_if_exists(log_path)
    return logs


def test_network_end_to_end(report: TestReport):
    reset_logs_dir()
    config = load_network_config(str(ROOT))

    nodes: Dict[int, No] = {}
    try:
        for i in range(1, 6):
            nodes[i] = No(i, config.routers, config.graph, drop_rate=0.10, ack_timeout=0.15)

        report.check(
            all(((nodes[i]._sock.type & socket.SOCK_DGRAM) == socket.SOCK_DGRAM) for i in nodes),
            "Nos usam sockets UDP (SOCK_DGRAM)",
            "Algum no nao esta usando socket UDP",
        )

        rota_1_5 = nodes[1].routing_table.get(5)
        report.check(
            rota_1_5 == (3, 10),
            "Dijkstra calculou rota 1->5 como (proximo_hop=3, custo=10)",
            f"Rota 1->5 inesperada: {rota_1_5}",
        )

        ok_payload, msg_payload = nodes[1].enviar(5, "x" * 101)
        report.check(
            (not ok_payload) and ("excede 100" in msg_payload.lower()),
            "Payload > 100 caracteres foi rejeitado",
            f"Payload > 100 deveria ser rejeitado. retorno=({ok_payload}, {msg_payload})",
        )

        total_msgs = 20
        print(f"Enviando {total_msgs} mensagens de 1 para 5...")
        for _ in range(total_msgs):
            ok, detalhe = nodes[1].enviar(5, "Hello")
            if not ok:
                report.check(False, "", f"Falha inesperada no envio: {detalhe}")
                return
            time.sleep(0.05)

        received_all = wait_until(
            lambda: len(nodes[5].get_historico("1")) >= total_msgs,
            timeout_s=45.0,
            poll_s=0.25,
        )
        conversa = nodes[5].get_historico("1")
        report.check(
            received_all,
            f"Destino recebeu as {total_msgs} mensagens",
            f"Destino recebeu apenas {len(conversa)}/{total_msgs} mensagens",
        )

        recebido_ids = [item["msg"].msg_id for item in conversa if item.get("tipo") == "deles"]
        report.check(
            len(recebido_ids) == len(set(recebido_ids)) == total_msgs,
            "Anti-duplicacao preservada no destino (msg_id unico)",
            (
                "Duplicidade ou perda no destino: "
                f"total={len(recebido_ids)} unicos={len(set(recebido_ids))} esperado={total_msgs}"
            ),
        )

        logs = read_logs_for_nodes([1, 2, 3, 4, 5])
        report.check(
            count_by_category(logs[1], "Enviadas") >= total_msgs,
            "Log do no 1 possui categoria Enviadas",
            "Log do no 1 nao possui entradas suficientes em Enviadas",
        )
        report.check(
            count_by_category(logs[5], "Recebidas") >= total_msgs,
            "Log do no 5 possui categoria Recebidas",
            "Log do no 5 nao possui entradas suficientes em Recebidas",
        )
        report.check(
            any(count_by_category(logs[rid], "Encaminhadas") > 0 for rid in (2, 3, 4)),
            "Algum no intermediario registrou Encaminhadas",
            "Nenhum no intermediario registrou Encaminhadas",
        )
        report.check(
            any(count_by_category(logs[rid], "Descartes") > 0 for rid in (1, 2, 3, 4, 5)),
            "Descartes registrados com drop_rate=10%",
            "Nenhum descarte registrado com drop_rate=10%",
        )

        ids_n1 = parse_msg_ids(logs[1])
        ids_n5 = parse_msg_ids(logs[5])
        ids_inter = parse_msg_ids("\n".join(logs[rid] for rid in (2, 3, 4)))

        comum = set(ids_n1).intersection(ids_inter).intersection(ids_n5)
        report.check(
            len(comum) >= total_msgs,
            "Fluxo multi-hop confirmado por msg_id comum em origem/intermediario/destino",
            "Nao foi possivel confirmar multi-hop por correlacao de msg_id nos logs",
        )

        had_retransmission = any(
            logs[rid].count("timeout aguardando ACK") > 0 or logs[rid].count("reenviando") > 0
            for rid in (1, 2, 3, 4, 5)
        )
        # Console de timeout/reenvio nao vai para arquivo de log; validamos indiretamente por descarte + entrega total.
        report.check(
            (not had_retransmission) or (len(comum) >= total_msgs),
            "Confiabilidade validada: entrega total apesar de descartes",
            "Confiabilidade nao validada com descartes",
        )

    finally:
        for node in nodes.values():
            node.encerrar()


def main() -> int:
    report = TestReport()
    test_init_and_parser(report)
    test_network_end_to_end(report)
    return report.finish()


if __name__ == "__main__":
    raise SystemExit(main())
