"""python -m meridian build | score | eval | suppliers | serve"""

import argparse
import json
import logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="meridian")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="rebuild kb/ from dataset/ and curation/")
    sub.add_parser("score", help="score extraction and linking against eval/truth and curation")
    evaluate = sub.add_parser("eval", help="ask eval/questions.json twice, run the baseline and the correction scenario")
    evaluate.add_argument("--rescore", metavar="RUN_DIR", help="score a finished run again after a grader fix, without asking")
    suppliers = sub.add_parser("suppliers", help="search the web for other suppliers, once, into kb/suppliers")
    suppliers.add_argument("--refresh", action="store_true", help="search again even where a response is cached")
    serve = sub.add_parser("serve", help="run the app")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Imported per command: serving needs only requirements.txt, building needs requirements-build.txt.
    match args.command:
        case "build":
            from meridian.build import build
            print(json.dumps(build(), indent=1))
        case "score":
            from meridian.scores import report
            print(report())
        case "eval":
            from pathlib import Path
            from meridian.evaluation import rescore, run
            print(json.dumps(rescore(Path(args.rescore)) if args.rescore else run(), indent=1, ensure_ascii=False))
        case "suppliers":
            from meridian import config, evidence, suppliers
            print(json.dumps(suppliers.run(list(evidence.read_jsonl(config.KB / "observations.jsonl")), args.refresh), indent=1))
        case "serve":
            import uvicorn
            uvicorn.run("meridian.server:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
