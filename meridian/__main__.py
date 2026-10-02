"""python -m meridian build | score | serve"""

import argparse
import json
import logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="meridian")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="rebuild kb/ from dataset/ and curation/")
    sub.add_parser("score", help="score extraction and linking against eval/truth and curation")
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
        case "serve":
            import uvicorn
            uvicorn.run("meridian.server:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
