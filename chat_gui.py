
import sys
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

from chat_network import Mensagem, No, Vizinho


@dataclass
class EstadoCLI:
    # Nome da conversa atualmente aberta no prompt.
    conversa_ativa: str
    # Quantidade de mensagens não lidas por conversa.
    nao_lidas: Dict[str, int]


class ChatCLI:
    def __init__(self, no: No):
        # Referência para a camada de rede (socket UDP + histórico).
        self.no = no
        # Mapa para lookup rápido: nome do vizinho -> objeto Vizinho.
        self.vizinhos = {v.nome: v for v in no.vizinhos}
        # Começa sem conversa ativa; usuário escolhe com /abrir.
        self.estado = EstadoCLI(conversa_ativa="", nao_lidas={})
        # Lock para serializar prints e evitar "embaralhar" terminal.
        self._print_lock = threading.Lock()

        # Inicializa contador de não lidas para todas as conversas já conhecidas.
        for nome in self.no.listar_conversas():
            self.estado.nao_lidas[nome] = 0

        # Conecta callback da rede para avisar a CLI sobre novas mensagens.
        self.no._callback_nova_msg = self._on_nova_msg

    def _safe_print(self, texto: str = ""):
        # Toda escrita de saída protegida por lock para evitar concorrência visual.
        with self._print_lock:
            print(texto)

    def _prompt_label(self) -> str:
        # Se não houver conversa ativa, usa rótulo "menu" no prompt.
        return self.estado.conversa_ativa if self.estado.conversa_ativa else "menu"

    def _imprimir_evento_assincrono(self, linhas: List[str]):
        """Imprime eventos vindos da thread de rede e redesenha o prompt da CLI."""
        with self._print_lock:
            # Limpa a linha atual do input para evitar mistura visual.
            sys.stdout.write("\r\033[2K")
            # Escreve cada linha do evento (mensagem recebida, badge, etc.).
            for linha in linhas:
                sys.stdout.write(f"{linha}\n")
            # Reescreve o prompt para o usuário continuar digitando no contexto atual.
            sys.stdout.write(f"[{self._prompt_label()}]> ")
            sys.stdout.flush()

    def _limpar_linha_entrada(self):
        """Remove visualmente a linha recém-digitada para manter saída padronizada abaixo do menu."""
        with self._print_lock:
            # Sobe uma linha, limpa a linha inteira e volta ao início.
            sys.stdout.write("\033[1A\033[2K\r")
            sys.stdout.flush()

    def _limpar_tela(self):
        """Limpa a tela inteira da CLI para trocar o contexto visual da conversa."""
        with self._print_lock:
            # ANSI: limpa tela e posiciona cursor no canto superior esquerdo.
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

    def _on_nova_msg(self, conversa: str):
        # Se for conversa nova criada dinamicamente, inicializa contador de badge.
        if conversa not in self.estado.nao_lidas:
            self.estado.nao_lidas[conversa] = 0

        # Se a conversa recebida está aberta, imprime a mensagem já formatada no fluxo.
        if conversa == self.estado.conversa_ativa:
            hist = self.no.get_historico(conversa)
            if not hist:
                self._imprimir_evento_assincrono([f"📨 Nova mensagem em [{conversa}]", "(sem mensagens)"])
                return

            # Índice real da última mensagem para manter padrão do histórico (000, 001, ...).
            idx = len(hist) - 1
            self._imprimir_evento_assincrono(
                [
                    f"{idx:03d} {self._formatar_item(hist[-1])}",
                ]
            )
        else:
            # Se a conversa não está ativa, só incrementa badge e notifica sem abrir histórico.
            self.estado.nao_lidas[conversa] += 1
            n = self.estado.nao_lidas[conversa]
            self._imprimir_evento_assincrono([f"🔔 {n} nova(s) em [{conversa}]"])

    def _formatar_item(self, item: dict) -> str:
        # Cada item do histórico tem estrutura: {"tipo": str, "msg": Mensagem}
        tipo = item["tipo"]
        msg: Mensagem = item["msg"]

        if tipo == "eu":
            return f"[{msg.hora()}] Você: {msg.conteudo}"
        if tipo == "fwd_sent":
            return f"[{msg.hora()}] Você (encaminhou): {msg.conteudo}"
        if tipo == "fwd":
            return (
                f"[{msg.hora()}] Encaminhado por {msg.encaminhado_por}: "
                f"[{msg.remetente_nome}] {msg.conteudo}"
            )
        return f"[{msg.hora()}] {msg.remetente_nome}: {msg.conteudo}"

    def _mostrar_historico(self, conversa: str, limite: Optional[int] = None):
        # Proteção para chamadas sem conversa ativa.
        if not conversa:
            self._safe_print("Nenhuma conversa ativa. Use /abrir <nome>.")
            return

        # Sem mensagens ainda nessa conversa.
        hist = self.no.get_historico(conversa)
        if not hist:
            self._safe_print("(sem mensagens)")
            return

        # Se limite existir, mostra só a cauda mantendo índice absoluto.
        inicio = max(0, len(hist) - limite) if limite else 0
        itens = hist[inicio:]
        for i, item in enumerate(itens, start=inicio):
            self._safe_print(f"{i:03d} {self._formatar_item(item)}")

    def _listar_conversas(self):
        self._safe_print("\n=== Conversas ===")
        for nome in self.no.listar_conversas():
            # '*' indica conversa ativa.
            marcador = "*" if nome == self.estado.conversa_ativa else " "
            # Badge de mensagens não lidas.
            badge = self.estado.nao_lidas.get(nome, 0)
            extra = f" ({badge} nova(s))" if badge else ""
            self._safe_print(f"{marcador} {nome}{extra}")

    def _menu(self):
        self._safe_print(
            """
==================== CHAT_UDP ====================
        Sistema de Mensageria P2P (UDP)
--------------------------------------------------
 Nó local : {nome}
 Endereço : {ip}:{porta}
--------------------------------------------------

Comandos disponíveis:
  /ajuda                         Mostra esta ajuda
  /conversas                     Lista conversas
  /abrir <nome>                  Abre conversa
  /historico                     Mostra histórico da conversa ativa
  /enviar <texto>                Envia para o vizinho da conversa ativa
  /encaminhar <idx> <destino>    Encaminha mensagem recebida para outro nó
  /sair                          Encerra

Dica: se digitar texto sem comando, equivale a /enviar <texto>.
==================================================
""".strip().format(nome=self.no.nome, ip=self.no.ip, porta=self.no.porta)
        )

    def _ajuda(self):
        self._menu()

    def _render_conversa_ativa(self):
        """Redesenha a tela mostrando apenas menu e conteúdo da conversa ativa."""
        self._limpar_tela()
        self._menu()
        if not self.estado.conversa_ativa:
            self._safe_print("\nNenhuma conversa ativa. Use /abrir <nome>.")
            return
        self._safe_print(f"\n✅ Conversa ativa: [{self.estado.conversa_ativa}]")
        self._mostrar_historico(self.estado.conversa_ativa)

    def _abrir_conversa(self, nome: str):
        # Conversas existentes (vizinhos + eventuais conversas criadas dinamicamente).
        conversas = self.no.listar_conversas()
        if nome not in conversas:
            self._safe_print(f"Conversa '{nome}' não existe.")
            return

        # Seleciona conversa e zera badge de não lidas dela.
        self.estado.conversa_ativa = nome
        self.estado.nao_lidas[nome] = 0

        # Ao trocar conversa, limpa o histórico visual anterior e mostra só a conversa aberta.
        self._render_conversa_ativa()

    def _enviar(self, texto: str):
        # Ignora envios vazios.
        if not texto.strip():
            return
        # Exige conversa ativa.
        if not self.estado.conversa_ativa:
            self._safe_print("Nenhuma conversa ativa. Use /abrir <nome>.")
            return
        # Só envia direto para vizinho conhecido (não faz roteamento automático multi-hop).
        destino = self.vizinhos.get(self.estado.conversa_ativa)
        if not destino:
            self._safe_print("Só é possível enviar para vizinhos diretos.")
            return
        self.no.enviar(destino, texto)

        # Reimprime a última linha no padrão do histórico para manter UI consistente.
        hist = self.no.get_historico(destino.nome)
        if hist:
            idx = len(hist) - 1
            self._safe_print(f"{idx:03d} {self._formatar_item(hist[-1])}")

    def _encaminhar(self, idx_str: str, destino_nome: str):
        # Encaminhamento sempre parte da conversa ativa.
        conversa = self.estado.conversa_ativa
        if not conversa:
            self._safe_print("Nenhuma conversa ativa. Use /abrir <nome>.")
            return
        hist = self.no.get_historico(conversa)
        if not hist:
            self._safe_print("Sem mensagens nessa conversa.")
            return

        # Converte índice textual para inteiro.
        try:
            idx = int(idx_str)
        except ValueError:
            self._safe_print("Índice inválido.")
            return

        if idx < 0 or idx >= len(hist):
            self._safe_print("Índice fora do intervalo.")
            return

        # Só permite encaminhar mensagens recebidas, não enviadas por você.
        item = hist[idx]
        if item["tipo"] not in ("deles", "fwd"):
            self._safe_print("Você só pode encaminhar mensagens recebidas.")
            return

        # Destino de encaminhamento também precisa ser vizinho direto.
        destino = self.vizinhos.get(destino_nome)
        if not destino:
            self._safe_print(f"Destino '{destino_nome}' não é vizinho direto.")
            return

        self.no.encaminhar(item["msg"], destino)
        self._safe_print(f"✅ Encaminhado para {destino.nome}")

    def executar(self):
        # Render inicial da CLI.
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

            # Limpa o comando digitado para deixar apenas saída formatada no fluxo.
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
            elif cmd == "/enviar" and len(partes) >= 2:
                texto = linha.split(maxsplit=1)[1]
                self._enviar(texto)
            elif cmd == "/encaminhar" and len(partes) == 3:
                self._encaminhar(partes[1], partes[2])
            else:
                self._safe_print("Comando inválido. Use /ajuda.")

        self.no.encerrar()


def parsear_argumentos():
    # Formato esperado: nome ip porta + blocos de vizinhos em trincas.
    args = sys.argv[1:]
    if len(args) < 6 or len(args) % 3 != 0:
        print(
            "Uso:\n"
            "  python3 chat_gui.py <nome> <ip> <porta> "
            "<viz1_nome> <viz1_ip> <viz1_porta> "
            "[<viz2_nome> <viz2_ip> <viz2_porta> ...]"
        )
        sys.exit(1)

    # Primeira trinca define este nó local.
    nome, ip, porta_str = args[0], args[1], args[2]
    try:
        porta = int(porta_str)
    except ValueError:
        print(f"Porta inválida: {porta_str}")
        sys.exit(1)

    # Demais trincas definem vizinhos diretos.
    vizinhos: List[Vizinho] = []
    for i in range(3, len(args), 3):
        v_nome, v_ip, v_porta_str = args[i], args[i + 1], args[i + 2]
        try:
            v_porta = int(v_porta_str)
        except ValueError:
            print(f"Porta inválida para {v_nome}: {v_porta_str}")
            sys.exit(1)
        vizinhos.append(Vizinho(v_nome, v_ip, v_porta))

    return nome, ip, porta, vizinhos


if __name__ == "__main__":
    nome, ip, porta, vizinhos = parsear_argumentos()
    no = No(nome, ip, porta, vizinhos)
    ChatCLI(no).executar()
