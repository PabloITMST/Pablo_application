"""Stage 1: entity activation. Stage 2: passage ranking."""
import networkx as nx


def activate(graph: nx.Graph, query_entities: list[str], delta: int) -> set[str]:
    # spread from the query's entities, pruned at delta hops
    seen, frontier = set(query_entities), set(query_entities)
    for _ in range(delta):
        frontier = {m for n in frontier for m in graph.neighbors(n)
                    if graph.nodes[m]["kind"] == "entity"} - seen
        seen |= frontier
    return seen


def retrieve(graph: nx.Graph, query_entities: list[str], cfg: dict) -> list[str]:
    k = cfg["retrieval"]["top_k"]
    lam = cfg["retrieval"]["lam"]
    seeds = activate(graph, query_entities, cfg["pruning"]["delta"])
    passages = [n for n, d in graph.nodes(data=True) if d["kind"] == "passage"]
    sub = graph.subgraph([n for n, d in graph.nodes(data=True) if d["kind"] in ("entity", "passage")])
    personalization = {n: 1.0 if n in seeds else (lam if n in passages else 0.0) for n in sub}
    scores = nx.pagerank(sub, alpha=cfg["pagerank"]["damping"], personalization=personalization)
    return sorted(passages, key=lambda p: scores.get(p, 0.0), reverse=True)[:k]
