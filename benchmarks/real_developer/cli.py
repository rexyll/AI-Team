from __future__ import annotations

import argparse

from .runner import RealDeveloperBenchmark


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Real Developer benchmarks. Live provider calls require --live."
    )
    parser.add_argument("--developers", type=int, nargs="+", default=[1])
    parser.add_argument("--scenario", default="independent")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--live", action="store_true", help="Allow real provider/API calls.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if any(count <= 0 for count in args.developers):
        raise SystemExit("--developers values must be greater than 0")
    if args.repeat <= 0:
        raise SystemExit("--repeat must be greater than 0")
    if not args.live:
        raise SystemExit("Real Developer benchmark requires explicit --live")
    # Provider/model are intentionally validated by the live executor layer.
    _ = (args.provider, args.model, args.scenario)
    raise SystemExit(
        "Live Real Developer execution is not wired to a provider executor yet; "
        "use the deterministic benchmark until the live executor contract is enabled."
    )


if __name__ == "__main__":
    main()
