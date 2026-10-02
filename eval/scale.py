"""How the in-memory knowledge base behaves as the corpus grows.

    python eval/scale.py

The supplied corpus is copied 1, 10 and 100 times, each copy with its drawings and BOM rows renumbered so
nothing collides, and the work done on every question is timed: building the knowledge base from its
observations, the graph, part search, one part's evidence, and a path between two parts. Extraction is not
repeated; it runs once per drawing at build time and is cached. The copies share their names, so search
vocabulary does not grow with them: this measures volume, not variety.
"""

import json
import re
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meridian import graph  # noqa: E402
from meridian.knowledge import KnowledgeBase  # noqa: E402

QUERIES = ["recoater arm", "build plate", "silicone wiper", "galvo", "24 V power supply", "biuld cylinder clamp ring"]


def copies(kb: KnowledgeBase, n: int) -> KnowledgeBase:
    observations, relations, sheets = [], [], {}
    for k in range(n):
        drawing = lambda s, k=k: re.sub(r"\bD-(\d{3})\b", lambda m: f"D-{k * 1000 + int(m.group(1)):05d}", s)
        name = lambda s, k=k: re.sub(r"\bBOM\.(\d+)", lambda m: f"BOM.{k * 1000 + int(m.group(1))}", drawing(s))
        for o in kb.base_observations:
            parsed = json.loads(name(json.dumps(o.parsed))) if o.parsed else o.parsed
            if o.field == "bom_link":
                parsed["rows"] = [k * 1000 + r for r in parsed["rows"]]
            source = replace(o.source, doc=name(o.source.doc), row=o.source.row + k * 1000 if o.source.row else o.source.row)
            observations.append(replace(o, id=name(o.id), subject=name(o.subject), source=source, parsed=parsed))
        relations += [replace(r, id=name(r.id), a=name(r.a), b=name(r.b), evidence=tuple(map(name, r.evidence)))
                      for r in kb.base_relations]
        sheets |= {drawing(d): info for d, info in kb.sheets.items()}
    return KnowledgeBase(observations, relations, sheets, corrections_log=kb.corrections_log)


def timed(call, repeat: int = 1) -> float:
    times = []
    for _ in range(repeat):
        started = time.perf_counter()
        call()
        times.append(time.perf_counter() - started)
    return statistics.median(times) * 1000


def main() -> None:
    base = KnowledgeBase.load()
    print("| copies | drawings | observations | build (ms) | graph (ms) | search (ms) | part (ms) | path (ms) |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for n in (1, 10, 100):
        built = []
        build_ms = timed(lambda: built.append(copies(base, n)))
        kb = built[0]
        graph_ms = timed(lambda: kb.graph)
        kb.find("warm up")  # the search vocabulary is built once, on first use
        search_ms = statistics.median(timed(lambda q=q: kb.find(q), 5) for q in QUERIES)
        last = f"D-{(n - 1) * 1000 + 11:05d}"
        part_ms = timed(lambda: kb.part(last), 5)
        path_ms = timed(lambda: graph.path(kb.graph, last, f"D-{(n - 1) * 1000 + 26:05d}"), 5)
        print(f"| {n} | {len(kb.sheets)} | {len(kb.obs)} | {build_ms:.0f} | {graph_ms:.0f} | {search_ms:.1f} | {part_ms:.1f} | {path_ms:.1f} |")


if __name__ == "__main__":
    main()
