
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from chat_network import Mensagem, No
from config_loader import ConfigError, load_network_config


@dataclass
class EstadoCLI:
    # Nome da conversa atualmente aberta no prompt.
    conversa_ativa: str
    # Quantidade de mensagens não lidas por conversa.
    nao_lidas: Dict[str, int]


class ChatCLI:
    def __init__(self, no: No):
        self.no = no
        self.estado = EstadoCLI(conversa_ativa="", nao_lidas={})
        self._print_lock = threading.Lock()

        for nome in self.no.listar_conversas():
            self.estado.nao_lidas[nome] = 0

        self.no._callback_nova_msg = self._on_nova_msg

    def _safe_print(self, texto: str = ""):
        with self._print_lock:
            print(texto)

    def _prompt_label(self) -> str:
        return self.estado.conversa_ativa if self.estado.conversa_ativa else f"R{self.no.router_id}"

    def _imprimir_evento_assincrono(self, linhas: List[str]):
        with self._print_lock:
            sys.stdout.write("\r\033[2K")
            for linha in linhas:
                sys.stdout.write(f"{linha}\n")
            sys.stdout.write(f"[{self._prompt_label()}]> ")
            sys.stdout.flush()

    def _limpar_linha_entrada(self):
        with self._print_lock:
            sys.stdout.write("\033[1A\033[2K\r")
            sys.stdout.flush()

    def _limpar_tela(self):
        with self._print_lock:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

    def _on_nova_msg(self, conversa: str):
        if conversa not in self.estado.nao_lidas:
            self.estado.nao_lidas[conversa] = 0

        if conversa == self.estado.conversa_ativa:
            hist = self.no.get_historico(conversa)
            if not hist:
                self._imprimir_evento_assincrono([f"Nova atividade em [{conversa}]", "(sem mensagens)"])
                return

            idx = len(hist) - 1
            self._imprimir_evento_assincrono(
                [
                    f"{idx:03d} {self._formatar_item(hist[-1])}",
                ]
            )
        else:
            self.estado.nao_lidas[conversa] += 1
            n = self.estado.nao_lidas[conversa]
            self._imprimir_evento_assincrono([f"{n} nova(s) em [{conversa}]"])

    def _formatar_item(self, item: dict) -> str:
        tipo = item["tipo"]
        msg: Mensagem = item["msg"]
        sufixo = f" (Seq:{msg.seq})"

        if tipo == "eu":
            return f"[{msg.hora()}] Voce -> [{msg.destino_id}]: {msg.conteudo}{sufixo}"
        if tipo == "fwd_sent":
            return f"[{msg.hora()}] Encaminhada: {msg.conteudo}{sufixo}"
        return f"[{msg.hora()}] [{msg.origem_id}]: {msg.conteudo}{sufixo}"

    def _mostrar_historico(self, conversa: str, limite: Optional[int] = None):
        if not conversa:
            self._safe_print("Nenhuma conversa ativa. Use /abrir <id>.")
            return

        hist = self.no.get_historico(conversa)
        if not hist:
            self._safe_print("(sem mensagens)")
            return

        inicio = max(0, len(hist) - limite) if limite else 0
        itens = hist[inicio:]
        for i, item in enumerate(itens, start=inicio):
            self._safe_print(f"{i:03d} {self._formatar_item(item)}")

    def _listar_conversas(self):
        self._safe_print("\n=== Conversas (IDs) ===")
        for nome in self.no.listar_conversas():
            marcador = "*" if nome == self.estado.conversa_ativa else " "
            badge = self.estado.nao_lidas.get(nome, 0)
            extra = f" ({badge} nova(s))" if badge else ""
            self._safe_print(f"{marcador} {nome}{extra}")

    def _mostrar_rotas(self):
        tabela = self.no.tabela_encaminhamento()
        self._safe_print("\n=== Tabela de Encaminhamento ===")
        if not tabela:
            self._safe_print("(sem rotas alcancaveis)")
            return
        for destino in sorted(tabela):
            next_hop, custo = tabela[destino]
            self._safe_print(
                f"destino={destino} -> proximo_hop={next_hop} custo_total={custo}"
            )

    def _menu(self):
        self._safe_print(
            """
==================== CHAT_TCP ====================
    Mensageria P2P Confiavel sobre UDP
--------------------------------------------------
 Roteador : {rid}
 Endereco : {ip}:{porta}
--------------------------------------------------

Comandos disponíveis:
  /ajuda                         Mostra esta ajuda
  /conversas                     Lista conversas
    /abrir <id>                    Abre conversa por ID
  /historico                     Mostra histórico da conversa ativa
    /enviar <texto>                Envia para o destino da conversa ativa
    /enviarpara <id> <texto>       Envia diretamente para um ID
    /rotas                         Mostra tabela de encaminhamento
  /sair                          Encerra

Dica: se digitar texto sem comando, equivale a /enviar <texto>.
==================================================
""".strip().format(
                                rid=self.no.router_id,
                                ip=self.no.routers[self.no.router_id].ip,
                                porta=self.no.routers[self.no.router_id].port,
                        )
        )

    def _ajuda(self):
        self._menu()

    def _render_conversa_ativa(self):
        self._limpar_tela()
        self._menu()
        if not self.estado.conversa_ativa:
            self._safe_print("\nNenhuma conversa ativa. Use /abrir <id>.")
            return
        self._safe_print(f"\n✅ Conversa ativa: [{self.estado.conversa_ativa}]")
        self._mostrar_historico(self.estado.conversa_ativa)

    def _abrir_conversa(self, nome: str):
        conversas = self.no.listar_conversas()
        if nome not in conversas:
            self._safe_print(f"Conversa '{nome}' não existe.")
            return

        self.estado.conversa_ativa = nome
        self.estado.nao_lidas[nome] = 0

        self._render_conversa_ativa()

    def _enviar(self, texto: str, destino_forcado: Optional[int] = None):
        if not texto.strip():
            return
        if destino_forcado is None:
            if not self.estado.conversa_ativa:
                self._safe_print("Nenhuma conversa ativa. Use /abrir <id>.")
                return
            try:
                destino_id = int(self.estado.conversa_ativa)
            except ValueError:
                self._safe_print("Conversa ativa invalida para envio.")
                return
        else:
            destino_id = destino_forcado

        ok, detalhe = self.no.enviar(destino_id, texto)
        if not ok:
            self._safe_print(f"Falha: {detalhe}")
            return

        hist = self.no.get_historico(str(destino_id))
        if hist:
            idx = len(hist) - 1
            self._safe_print(f"{idx:03d} {self._formatar_item(hist[-1])}")
        else:
            self._safe_print(detalhe)

    def executar(self):
        self._safe_print()
        self._menu()

        while True:
            try:
                linha = input(f"[{self._prompt_label()}]> ").strip()
            except (EOFError, KeyboardInterrupt):
                self._safe_print("\nSaindo...")
                break

            if not linha:
                continue

            self._limpar_linha_entrada()

            if not linha.startswith("/"):
                self._enviar(linha)
                continue

            partes = linha.split(maxsplit=2)
            cmd = partes[0].lower()

            if cmd == "/sair":
                break
            if cmd == "/ajuda":
                self._ajuda()
            elif cmd == "/conversas":
                self._listar_conversas()
            elif cmd == "/historico":
                self._render_conversa_ativa()
            elif cmd == "/abrir" and len(partes) >= 2:
                self._abrir_conversa(partes[1])
            elif cmd == "/rotas":
                self._mostrar_rotas()
            elif cmd == "/enviar" and len(partes) >= 2:
                texto = linha.split(maxsplit=1)[1]
                self._enviar(texto)
            elif cmd == "/enviarpara" and len(partes) == 3:
                try:
                    destino_id = int(partes[1])
                except ValueError:
                    self._safe_print("ID de destino invalido.")
                    continue
                self._enviar(partes[2], destino_forcado=destino_id)
            else:
                self._safe_print("Comando inválido. Use /ajuda.")

        self.no.encerrar()


def parsear_argumentos() -> int:
    args = sys.argv[1:]
    if len(args) != 1:
        print(
            "Uso:\n"
            "  python3 chat_gui.py <ID_roteador>"
        )
        sys.exit(1)

    try:
        router_id = int(args[0])
    except ValueError:
        print("ID de roteador invalido (use valor numerico).")
        sys.exit(1)

    return router_id


if __name__ == "__main__":
    router_id = parsear_argumentos()
    base_dir = Path(__file__).resolve().parent

    try:
        network_config = load_network_config(str(base_dir))
    except ConfigError as exc:
        print(f"Erro de configuracao: {exc}")
        sys.exit(1)

    try:
        no = No(
            router_id=router_id,
            routers=network_config.routers,
            graph=network_config.graph,
        )
    except ValueError as exc:
        print(exc)
        sys.exit(1)

    ChatCLI(no).executar()
