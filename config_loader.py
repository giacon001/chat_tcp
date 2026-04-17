from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class RouterInfo:
    router_id: int
    port: int
    ip: str

    @property
    def endpoint(self) -> tuple[str, int]:
        return (self.ip, self.port)


@dataclass(frozen=True)
class Link:
    source: int
    target: int
    cost: int


@dataclass(frozen=True)
class NetworkConfig:
    routers: Dict[int, RouterInfo]
    links: List[Link]
    graph: Dict[int, Dict[int, int]]


class ConfigError(ValueError):
    pass


def _load_routers(config_path: Path) -> Dict[int, RouterInfo]:
    routers: Dict[int, RouterInfo] = {}
    if not config_path.exists():
        raise ConfigError(f"Arquivo nao encontrado: {config_path}")

    with config_path.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            if len(parts) != 3:
                raise ConfigError(
                    f"Linha invalida em {config_path.name}:{line_no}. "
                    "Formato esperado: <ID> <Porta> <IP>"
                )

            id_str, port_str, ip = parts
            try:
                router_id = int(id_str)
                port = int(port_str)
            except ValueError as exc:
                raise ConfigError(
                    f"ID/Porta invalidos em {config_path.name}:{line_no}"
                ) from exc

            if router_id in routers:
                raise ConfigError(
                    f"ID duplicado em {config_path.name}:{line_no} -> {router_id}"
                )

            routers[router_id] = RouterInfo(router_id=router_id, port=port, ip=ip)

    if not routers:
        raise ConfigError(f"Nenhum roteador encontrado em {config_path.name}")

    return routers


def _load_links(config_path: Path, routers: Dict[int, RouterInfo]) -> List[Link]:
    links: List[Link] = []
    if not config_path.exists():
        raise ConfigError(f"Arquivo nao encontrado: {config_path}")

    with config_path.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            if len(parts) != 3:
                raise ConfigError(
                    f"Linha invalida em {config_path.name}:{line_no}. "
                    "Formato esperado: <ID_Origem> <ID_Destino> <Custo>"
                )

            src_str, dst_str, cost_str = parts
            try:
                source = int(src_str)
                target = int(dst_str)
                cost = int(cost_str)
            except ValueError as exc:
                raise ConfigError(
                    f"IDs/Custo invalidos em {config_path.name}:{line_no}"
                ) from exc

            if source not in routers or target not in routers:
                raise ConfigError(
                    f"Enlace com roteador desconhecido em {config_path.name}:{line_no}"
                )
            if source == target:
                raise ConfigError(
                    f"Enlace invalido (origem=destino) em {config_path.name}:{line_no}"
                )
            if cost <= 0:
                raise ConfigError(
                    f"Custo deve ser > 0 em {config_path.name}:{line_no}"
                )

            links.append(Link(source=source, target=target, cost=cost))

    if not links:
        raise ConfigError(f"Nenhum enlace encontrado em {config_path.name}")

    return links


def _build_bidirectional_graph(
    routers: Dict[int, RouterInfo],
    links: List[Link],
) -> Dict[int, Dict[int, int]]:
    graph: Dict[int, Dict[int, int]] = {router_id: {} for router_id in routers}

    for link in links:
        prev_ab = graph[link.source].get(link.target)
        prev_ba = graph[link.target].get(link.source)

        # Em duplicidade de enlace, mantem o menor custo.
        graph[link.source][link.target] = (
            link.cost if prev_ab is None else min(prev_ab, link.cost)
        )
        graph[link.target][link.source] = (
            link.cost if prev_ba is None else min(prev_ba, link.cost)
        )

    return graph


def load_network_config(base_dir: str) -> NetworkConfig:
    base = Path(base_dir)
    routers_path = base / "roteador.config"
    links_path = base / "enlaces.config"

    routers = _load_routers(routers_path)
    links = _load_links(links_path, routers)
    graph = _build_bidirectional_graph(routers, links)

    return NetworkConfig(routers=routers, links=links, graph=graph)
