# ◈ AI Coding Agent Instructions — Roteadores UDP Confiáveis

## Visão Geral do Sistema

Projeto de mensageria P2P confiável sobre UDP em Python puro (sem dependências externas).

Escopo principal:
- Inicialização por ID de roteador via linha de comando.
- Carga obrigatória de `roteador.config` e `enlaces.config`.
- Roteamento estático com visão global da topologia.
- Encaminhamento multi-hop com menor caminho (Dijkstra).
- Confiabilidade com descarte aleatório + ACK/timeout/reenvio (stop-and-wait).
- Logs locais por categoria.

Arquitetura:
- `config_loader.py`: parser/validação dos arquivos de topologia.
- `routing.py`: Dijkstra e tabela de encaminhamento.
- `chat_network.py`: protocolo UDP, envio/recepção, ACKs, retransmissão e histórico.
- `chat_gui.py`: interface CLI e bootstrap do nó local.
- `local_logger.py`: escrita thread-safe de logs locais.

## Requisitos Funcionais (Obrigatórios)

### 1. Inicialização e Configuração

Cada nó deve iniciar com exatamente um argumento:

```bash
python3 chat_gui.py <ID_roteador>
```

O sistema deve carregar obrigatoriamente:

- `roteador.config`: mapeia `ID -> Porta/IP`
  - formato: `<ID> <Porta> <IP>`
  - exemplo: `1 25001 127.0.0.1`
- `enlaces.config`: define enlaces e custos
  - formato: `<ID_Origem> <ID_Destino> <Custo>`
  - exemplo: `1 2 10`

A topologia usada em testes/apresentações deve conter pelo menos 5 nós.

### 2. Topologia e Inteligência de Roteamento

- A topologia é estática durante a execução.
- Cada nó deve ter visão completa da rede (grafo completo carregado dos arquivos).
- O cálculo de rotas deve usar Dijkstra.
- A tabela de encaminhamento deve mapear `destino -> (proximo_hop, custo_total)`.

### 3. Mensageria e Encaminhamento

- Payload textual máximo: 100 caracteres.
- Cada mensagem deve trafegar em um único pacote.
- Encaminhamento deve seguir a rota calculada (hop-by-hop).
- Cada roteador (origem e intermediários) deve imprimir status no console durante envio/encaminhamento.

Exemplo de rastreabilidade aceitável:

```text
Roteador [2] encaminhando mensagem (Seq: 7) para o destino 5 via 4
```

### 4. Logs Locais

Cada nó mantém arquivo local em `logs/roteador_<ID>.log` com registros cronológicos nas categorias:

- `Enviadas`
- `Encaminhadas`
- `Recebidas`
- `Descartes`

### 5. Falhas e Confiabilidade

- Deve haver descarte aleatório de 10% para pacotes de dados antes de encaminhar/entregar.
- A entrega fim-a-fim deve ser garantida por retransmissão com ACK e timeout.
- Estratégia obrigatória: stop-and-wait (um pacote por vez por nó emissor).
- Transporte deve usar apenas sockets UDP.

## Contratos de Implementação

### Formato de Pacote (`Mensagem`)

Campos obrigatórios:
- `timestamp`
- `msg_id` (UUID)
- `seq`
- `tipo_pacote` (`"msg"` ou `"ack"`)
- `origem_id`
- `destino_id`
- `ultimo_hop_id`
- `conteudo`

### Fluxo Stop-and-Wait Hop-by-Hop

1. Nó enfileira um pacote de dados (`_fila_envio`).
2. Envia para `next_hop` e aguarda ACK (`_ack_event.wait(timeout)`).
3. Sem ACK no timeout: retransmite o mesmo pacote.
4. ACK válido é aceito apenas se `msg_id` e `origem_id` corresponderem ao esperado.

### Descarte Aleatório

- Aplicar somente em pacotes de dados.
- Se descartar, registrar em log (`Descartes`) e não enviar ACK.

### Anti-duplicação

- Mensagens já vistas (`msg_id`) devem ser ignoradas após ACK para evitar duplicidade em retransmissões.

## Thread Safety

Use locks ao acessar estruturas compartilhadas:
- `self._historico` com `self._lock`
- controle de ACK pendente com `self._ack_lock`
- fila de envio com `self._fila_cv`
- escrita de log com lock interno de `NodeLogger`

## Execução e Testes

### Subir 5 nós locais

```bash
python3 chat_gui.py 1
python3 chat_gui.py 2
python3 chat_gui.py 3
python3 chat_gui.py 4
python3 chat_gui.py 5
```

### Checklist mínimo de validação

1. Inicialização falha sem ID e com ID inválido.
2. Configuração inválida dispara erro de parser (`ConfigError`).
3. Comandos `/rotas` mostram próximos hops e custos.
4. Mensagem com `len > 100` é rejeitada.
5. Mensagem 1->N percorre intermediários e chega no destino.
6. Console mostra encaminhamento e (quando ocorrer) timeout/reenvio.
7. Logs locais possuem as quatro categorias esperadas.

## Convenções de Código

- Classes em `PascalCase` (`No`, `Mensagem`, `ChatCLI`, `NodeLogger`).
- Funções/métodos em `snake_case`.
- Campos internos com prefixo `_`.
- Sem bibliotecas externas para rede/confiabilidade.

## Diretrizes para Agentes de Código

- Preserve transporte UDP; não substituir por TCP.
- Não remover stop-and-wait sem requisito explícito.
- Ao editar roteamento, manter compatibilidade com `build_forwarding_table`.
- Ao editar parser, manter validações de formato e integridade dos IDs.
- Ao editar confiabilidade, manter logs e rastreabilidade no console.
- Antes de concluir mudanças, executar testes de integração com múltiplos nós.
