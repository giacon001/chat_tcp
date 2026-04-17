# Chat P2P Confiavel sobre UDP

Aplicacao de mensageria P2P em Python usando apenas biblioteca padrao.

O transporte continua sendo UDP, mas a confiabilidade e implementada na aplicacao
com ACK, timeout e retransmissao no estilo stop-and-wait (hop-by-hop).

## Arquivos de configuracao obrigatorios

### roteador.config

Formato:

```text
<ID> <Porta> <IP>
```

Exemplo:

```text
1 25001 127.0.0.1
```

### enlaces.config

Formato:

```text
<ID_Origem> <ID_Destino> <Custo>
```

Exemplo:

```text
1 2 10
```

Observacao: os enlaces sao tratados como bidirecionais.

## Inicializacao

Cada no deve ser iniciado com o ID do roteador:

```bash
python3 chat_gui.py <ID_roteador>
```

Exemplo com 5 terminais:

```bash
# Terminal 1
python3 chat_gui.py 1

# Terminal 2
python3 chat_gui.py 2

# Terminal 3
python3 chat_gui.py 3

# Terminal 4
python3 chat_gui.py 4

# Terminal 5
python3 chat_gui.py 5
```

## Roteamento

- Topologia estatica carregada dos arquivos.
- Cada no possui visao global da rede.
- Dijkstra e usado para calcular menor custo.
- Tabela de encaminhamento: destino -> proximo_hop.

## Confiabilidade (stop-and-wait)

- Apenas 1 pacote de dados por vez e enviado por no.
- Cada hop envia ACK ao hop anterior quando recebe um pacote valido.
- Se o ACK nao chega dentro do timeout, o pacote e reenviado.
- Retransmissao segue no mesmo caminho enquanto a topologia for estatica.

## Simulacao de falhas

- Cada roteador descarta aleatoriamente 10% dos pacotes de dados.
- ACKs nao entram nessa perda simulada.
- Pacotes descartados nao geram ACK.

## Restricoes de payload

- Mensagens de texto limitadas a 100 caracteres.
- Cada mensagem e enviada em um unico pacote.

## Logs locais

Cada no grava um arquivo em `logs/roteador_<ID>.log` com entradas cronologicas das categorias:

- Enviadas
- Encaminhadas
- Recebidas
- Descartes

## Rastreabilidade no console

Nos processamentos de envio/encaminhamento, o no imprime status com sequencia e destino.

Exemplo:

```text
Roteador [2] encaminhando mensagem (Seq: 7) para o destino 5 via 4
```

## Comandos da CLI

- `/ajuda`
- `/conversas`
- `/abrir <id>`
- `/historico`
- `/enviar <texto>`
- `/enviarpara <id> <texto>`
- `/rotas`
- `/sair`

Atalho: texto sem `/` equivale a `/enviar <texto>` para a conversa ativa.

## Estrutura principal

```text
Chat_TCP/
├── chat_gui.py         # CLI e bootstrap por ID
├── chat_network.py     # Rede UDP + ACK/reenvio + stop-and-wait
├── config_loader.py    # Parser de roteador.config/enlaces.config
├── routing.py          # Dijkstra e tabela de encaminhamento
├── local_logger.py     # Logs locais por categoria
├── roteador.config     # Mapa ID -> porta/IP
└── enlaces.config      # Topologia e custos
```
