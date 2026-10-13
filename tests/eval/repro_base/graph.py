"""The relation-free graph over the corpus."""
import networkx as nx

from preprocess import entities, split_sentences


def build(passages: dict[str, str]) -> nx.Graph:
    g = nx.Graph()
    for pid, text in passages.items():
        g.add_node(pid, kind="passage")
        for i, sent in enumerate(split_sentences(text)):
            sid = f"{pid}#s{i}"
            g.add_node(sid, kind="sentence")
            g.add_edge(pid, sid)
            for ent in entities(sent):
                g.add_node(ent, kind="entity")
                g.add_edge(sid, ent)
                g.add_edge(ent, pid)
    return g
