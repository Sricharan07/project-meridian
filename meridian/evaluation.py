"""Measure the system on eval/questions.json, against a baseline that pastes the documents into the prompt.

    python -m meridian eval

Every question is asked twice with no shared state, to see how repeatable the
answers are. The baseline gets the same questions with the BOM and every
sheet's text (OCR for the scans) in its prompt and no tools: the approach the
brief warns against, measured rather than assumed. The correction scenario is
scripted end to end in a throwaway log, so var/ is never touched.

Results go to eval/runs/<time>/; the answers of the first run are also saved as
eval/transcripts.json, which the app replays when no API key is configured.
"""

import json
import re
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from openai import OpenAI

from meridian import config, corrections
from meridian.chat.agent import PRICES, Chat, question_key
from meridian.evidence import Method
from meridian.knowledge import KnowledgeBase

QUESTIONS = config.ROOT / "eval" / "questions.json"
RUNS = config.ROOT / "eval" / "runs"
TRANSCRIPTS = config.ROOT / "eval" / "transcripts.json"
WORKERS = 6

BASELINE_INSTRUCTIONS = """\
You answer questions about the OpenLPBF v2 metal 3D printer. The documents below are its bill of materials (CSV)
and the text of its 30 fabrication drawings. Answer from the documents.
"""


def run(repeats: int = 2) -> dict:
    questions = json.loads(QUESTIONS.read_text())
    out = RUNS / datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    out.mkdir(parents=True)

    with tempfile.TemporaryDirectory() as tmp:
        kb = KnowledgeBase.load(Path(tmp) / "corrections.jsonl")
        runs = [_ask_all(kb, questions) for _ in range(repeats)]
        scenario = _correction_scenario(Path(tmp) / "scenario.jsonl")
    baseline = _baseline(kb, questions)

    with (out / "answers.jsonl").open("w") as f:
        for n, turns in enumerate(runs, start=1):
            for q, turn in zip(questions, turns):
                f.write(json.dumps({"run": n, "id": q["id"], "turn": turn, "score": score(q, turn)}, ensure_ascii=False) + "\n")
    (out / "baseline.jsonl").write_text("".join(
        json.dumps({"id": q["id"], "answer": b["answer"], "score": score(q, b, baseline=True), "usage": b["usage"],
                    "seconds": b["seconds"]}, ensure_ascii=False) + "\n" for q, b in zip(questions, baseline)))
    (out / "correction.json").write_text(json.dumps(scenario, indent=1, ensure_ascii=False))
    TRANSCRIPTS.write_text(json.dumps({question_key(q["question"]): t | {"recorded_at": out.name}
                                       for q, t in zip(questions, runs[0])}, indent=1, ensure_ascii=False))

    summary = summarise(questions, runs, baseline, scenario)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    summary["run_dir"] = str(out.relative_to(config.ROOT))
    return summary


# --- asking ---------------------------------------------------------------------

def _ask_all(kb: KnowledgeBase, questions: list[dict]) -> list[dict]:
    with ThreadPoolExecutor(WORKERS) as pool:
        return list(pool.map(lambda q: Chat(kb).ask(q["question"]).to_dict(), questions))


def _correction_scenario(log: Path) -> dict:
    """Ask, correct D-023's misread fit, accept, ask again: the brief's before/after, recorded."""
    question = "What does the build cylinder fit into?"
    kb = KnowledgeBase.load(log)
    before = Chat(kb).ask(question).to_dict()
    proposal = corrections.propose(kb, "D-023.p1.vision.c06", "Ø262,0 j7 +0,026 / -0,026",
                                   "The sheet prints j7; the vision model read it as H7.", question, log)
    decided = corrections.decide(proposal.id, True, "evaluation run", "Scripted scenario; the sheet shows j7 at 200 dpi.", log)
    after_kb = KnowledgeBase.load(log)
    after = Chat(after_kb).ask(question).to_dict()
    return {
        "question": question,
        "before": before,
        "correction": asdict(decided),
        "after": after,
        "fit_relations_before": [r.relation for r in kb.relations if r.kind == "inferred" and "D-023" in (r.a, r.b)],
        "fit_relations_after": [r.relation for r in after_kb.relations if r.kind == "inferred" and "D-023" in (r.a, r.b)],
        "answer_changed": before["answer"] != after["answer"],
        "after_mentions_correction": "C-001" in after["answer"],
        "original_still_citable": after_kb.evidence(proposal.target)["value"] == proposal.current_value,
    }


def _baseline(kb: KnowledgeBase, questions: list[dict]) -> list[dict]:
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    documents = _documents(kb)

    def ask(q: dict) -> dict:
        started = time.monotonic()
        response = client.responses.create(
            model=config.MODEL, instructions=BASELINE_INSTRUCTIONS, reasoning={"effort": "medium"}, store=False,
            input=[{"role": "user", "content": f"{documents}\n\nQuestion: {q['question']}"}])
        price_in, price_out = PRICES[config.MODEL]
        usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
        usage["usd"] = round(usage["input_tokens"] * price_in / 1e6 + usage["output_tokens"] * price_out / 1e6, 5)
        return {"answer": response.output_text.strip(), "usage": usage, "seconds": round(time.monotonic() - started, 2)}

    with ThreadPoolExecutor(WORKERS) as pool:
        return list(pool.map(ask, questions))


def _documents(kb: KnowledgeBase) -> str:
    """What a paste-it-all pipeline would see: the raw BOM and each sheet's text, OCR for the scans."""
    parts = ["=== BOM (CSV) ===", config.BOM_CSV.read_text(encoding="utf-8-sig")]
    for drawing, info in kb.sheets.items():
        method = Method.OCR if info["degraded"] else Method.PDF_TEXT
        lines = [o.value for o in kb.by_subject[drawing] if o.method == method and o.value]
        parts += [f"=== Drawing {drawing} ({info['upstream_path'].rsplit('/', 1)[-1]}) ===", "\n".join(lines)]
    return "\n".join(parts)


# --- scoring --------------------------------------------------------------------

def score(q: dict, turn: dict, baseline: bool = False) -> dict:
    """Every expectation in the question, checked mechanically. The baseline is held to the content checks only."""
    text = _normal(turn["answer"])
    checks = {}
    for group in q.get("mentions", []):
        checks[f"mentions {group[0]}"] = any(_normal(g) in text for g in group)
    for pattern in q.get("avoids", []):
        checks[f"avoids /{pattern}/"] = re.search(pattern, turn["answer"], re.I) is None
    if not baseline:
        refs = [a.get("ref") for a in turn["attachments"]]
        if q.get("opens"):
            checks[f"opens {q['opens']}"] = q["opens"] in refs
        if q.get("model"):
            checks["offers the 3D view"] = any(a.get("model_3d") for a in turn["attachments"] if a.get("ref") == q.get("opens"))
        if q.get("cites_any"):
            checks["cites the key evidence"] = bool(set(q["cites_any"]) & set(turn["citations"]))
        if q.get("tool"):
            checks[f"calls {q['tool']}"] = any(s["tool"] == q["tool"] for s in turn["steps"])
        checks["passes the citation check"] = turn["check"]["ok"]
    return {"pass": all(checks.values()), "failed": [k for k, ok in checks.items() if not ok]}


def summarise(questions: list[dict], runs: list[list[dict]], baseline: list[dict], scenario: dict) -> dict:
    scored = [[score(q, t) for q, t in zip(questions, turns)] for turns in runs]
    first = runs[0]
    seconds = sorted(t["seconds"] for turns in runs for t in turns)
    cost = [t["usage"]["usd"] for turns in runs for t in turns]
    by_category: dict[str, list[bool]] = {}
    for q, s in zip(questions, scored[0]):
        by_category.setdefault(q["category"], []).append(s["pass"])
    agreement = [a["pass"] == b["pass"] for a, b in zip(scored[0], scored[-1])]
    overlap = [_jaccard(set(a["citations"]), set(b["citations"])) for a, b in zip(runs[0], runs[-1])]
    base = [score(q, b, baseline=True) for q, b in zip(questions, baseline)]
    content_only = [score(q, t, baseline=True) for q, t in zip(questions, first)]
    return {
        "model": config.MODEL,
        "questions": len(questions),
        "pass_rate_per_run": [round(sum(s["pass"] for s in run) / len(run), 3) for run in scored],
        "by_category": {c: f"{sum(v)}/{len(v)}" for c, v in by_category.items()},
        "failures_run_1": {q["id"]: s["failed"] for q, s in zip(questions, scored[0]) if not s["pass"]},
        "repeatability": {"same_verdict": f"{sum(agreement)}/{len(agreement)}",
                          "citation_overlap_median": round(statistics.median(overlap), 2)},
        "latency_seconds": {"median": statistics.median(seconds), "p90": seconds[int(0.9 * (len(seconds) - 1))]},
        "cost_usd": {"per_answer_median": round(statistics.median(cost), 5), "all_runs": round(sum(cost), 4)},
        "rewritten_after_failed_check": sum(t["check"]["rewritten"] for turns in runs for t in turns),
        "still_failing_check": sum(not t["check"]["ok"] for turns in runs for t in turns),
        "baseline": {
            "content_pass_rate": round(sum(s["pass"] for s in base) / len(base), 3),
            "system_content_pass_rate": round(sum(s["pass"] for s in content_only) / len(content_only), 3),
            "failures": {q["id"]: s["failed"] for q, s in zip(questions, base) if not s["pass"]},
            "input_tokens_per_question": statistics.median(b["usage"]["input_tokens"] for b in baseline),
            "cost_usd": round(sum(b["usage"]["usd"] for b in baseline), 4),
        },
        "correction": {k: scenario[k] for k in ("fit_relations_before", "fit_relations_after", "answer_changed",
                                                "after_mentions_correction", "original_still_citable")},
    }


def _normal(text: str) -> str:
    """Case-folded, with "45,000" read as 45000 and the drawings' decimal comma read as a point."""
    text = re.sub(r"(?<![\d,.])([1-9]\d{0,2}),(\d{3})(?![\d,])", r"\1\2", text.casefold())
    return re.sub(r"(\d),(\d)", r"\1.\2", text)


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0
