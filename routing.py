import heapq
from math import inf
from typing import Dict, Tuple


def build_forwarding_table(
    graph: Dict[int, Dict[int, int]],
    source: int,
) -> Dict[int, Tuple[int, int]]:
    """
    Retorna tabela destino -> (proximo_hop, custo_total) usando Dijkstra.
    """
    if source not in graph:
        return {}

    dist: Dict[int, float] = {node: inf for node in graph}
    prev: Dict[int, int] = {}
    dist[source] = 0

    pq: list[tuple[float, int]] = [(0, source)]
    visited: set[int] = set()

    while pq:
        cost_u, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)

        for v, edge_cost in graph.get(u, {}).items():
            new_cost = cost_u + edge_cost
            if new_cost < dist[v]:
                dist[v] = new_cost
                prev[v] = u
                heapq.heappush(pq, (new_cost, v))

    table: Dict[int, Tuple[int, int]] = {}
    for destination in graph:
        if destination == source:
            continue
        if dist[destination] == inf:
            continue

        hop = destination
        while prev.get(hop) is not None and prev[hop] != source:
            hop = prev[hop]

        if prev.get(hop) is None and hop != destination:
            # Estado inconsistente improvavel; ignora entrada.
            continue

        first_hop = hop if hop != source else destination
        table[destination] = (first_hop, int(dist[destination]))

    return table
