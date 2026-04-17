# Chat P2P UDP (CLI)

Aplicação de mensageria **P2P via UDP** em Python (somente biblioteca padrão), sem GUI.

## Arquitetura atual

```text
Chat_udp/
├── chat_network.py   # Camada de rede e histórico
└── chat_gui.py       # Interface CLI (nome legado do arquivo)
```

- `chat_network.py`
  - `Mensagem` e `Vizinho` (dataclasses)
  - classe `No` com socket UDP, thread de escuta, histórico e encaminhamento
- `chat_gui.py`
  - classe `ChatCLI` com comandos de terminal
  - parser de argumentos e loop principal

## Como funciona hoje

- Transporte: UDP (`socket.SOCK_DGRAM`), sem servidor central.
- Concorrência: uma thread escuta mensagens enquanto a CLI continua recebendo comandos.
- Histórico por conversa com tipos:
  - `eu` (mensagem enviada)
  - `deles` (mensagem recebida)
  - `fwd` (mensagem recebida e marcada como encaminhada)
  - `fwd_sent` (nota local de que você encaminhou algo)
- **Deduplicação de conversa por IP**:
  - para IPs já conhecidos, a conversa usa sempre o alias local configurado.
  - isso evita conversas duplicadas quando o outro nó usa nome diferente do seu contato local.

## Estrutura da mensagem

Cada pacote JSON contém:

- `timestamp`
- `remetente_nome`, `remetente_ip`, `remetente_porta`
- `dest_nome`, `dest_ip`, `dest_porta`
- `conteudo`
- `encaminhado` (bool)
- `encaminhado_por` (str opcional)

## Execução

Uso:

```bash
python3 chat_gui.py <nome> <ip> <porta> <viz1_nome> <viz1_ip> <viz1_porta> [<viz2_nome> <viz2_ip> <viz2_porta> ...]
```

Exemplo (3 nós):

```bash
# Terminal 1
python3 chat_gui.py No_A 192.168.1.10 5001 No_B 192.168.1.11 5002 No_C 192.168.1.12 5003

# Terminal 2
python3 chat_gui.py No_B 192.168.1.11 5002 No_A 192.168.1.10 5001 No_C 192.168.1.12 5003

# Terminal 3
python3 chat_gui.py No_C 192.168.1.12 5003 No_B 192.168.1.11 5002 No_A 192.168.1.10 5001 
```
Local (3 nós):

```bash
# Terminal 1
python3 chat_gui.py No_A 127.0.0.1 5001 No_B 127.0.0.1 5002 No_C 127.0.0.1 5003

# Terminal 2
python3 chat_gui.py No_B 127.0.0.1 5002 No_A 127.0.0.1 5001 No_C 127.0.0.1 5003

# Terminal 3
python3 chat_gui.py No_C 127.0.0.1 5003 No_B 127.0.0.1 5002 No_A 127.0.0.1 5001 
```

## Comandos disponíveis

- `/ajuda` — mostra ajuda
- `/conversas` — lista conversas e não lidas
- `/abrir <nome>` — define conversa ativa
- `/historico` — mostra histórico da conversa ativa
- `/enviar <texto>` — envia para o vizinho da conversa ativa
- `/encaminhar <indice> <destino>` — encaminha mensagem recebida para outro vizinho
- `/sair` — encerra o nó

Atalho: texto sem `/` é tratado como `/enviar <texto>`.

## Limitações atuais

- Envio direto (`/enviar`) só funciona para vizinho direto configurado.
- `/encaminhar` só aceita mensagens recebidas (`deles` ou `fwd`).
- UDP não garante entrega, ordem ou confirmação.
