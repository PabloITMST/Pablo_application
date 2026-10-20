"""Index each dataset, answer its questions, score, and log the result."""
import json
import random
import sys

import yaml
from openai import OpenAI
from sentence_transformers import SentenceTransformer

from evaluate import score
from graph import build
from retrieve import retrieve

cfg = yaml.safe_load(open("config.yaml"))
random.seed(cfg["seed"])
client, encoder = OpenAI(), SentenceTransformer(cfg["embedding_model"])

for name in cfg["datasets"]:
    data = json.load(open(f"data/{name}/{cfg['eval']['split']}.json"))[: cfg["eval"]["questions_per_dataset"]]
    graph = build({p["id"]: p["text"] for p in json.load(open(f"data/{name}/corpus.json"))})
    preds = []
    for ex in data:
        top = retrieve(graph, ex["entities"], cfg)
        ctx = "\n".join(graph.nodes[p].get("text", p) for p in top)
        r = client.chat.completions.create(model=cfg["llm"], messages=[{"role": "user", "content": f"{ctx}\n\nQ: {ex['question']}"}])
        preds.append(r.choices[0].message.content)
    result = score(name, preds, [ex["answer"] for ex in data], client, cfg)
    line = " ".join([f"dataset={name}", f"split={cfg['eval']['split']}", f"questions={len(data)}"]
                    + [f"{k}={v:.2f}" for k, v in result.items()])
    open(f"logs/{name}.log", "w").write(line + "\n")
    print(line, file=sys.stderr)
