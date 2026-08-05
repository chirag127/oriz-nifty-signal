"""CLI: python -m nifty_signal [--data DIR] [--no-llm] [--no-notify] [-v]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import run
from .util import configure_logging, log


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nifty_signal", description="Nifty market-timing signal")
    p.add_argument("--data", default="data", help="data dir for JSON snapshots")
    p.add_argument("--no-llm", action="store_true", help="skip g4f commentary")
    p.add_argument("--no-notify", action="store_true", help="skip Telegram/ntfy")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    configure_logging(args.verbose)
    try:
        sig = run(
            data_dir=Path(args.data),
            with_llm=not args.no_llm,
            with_notify=not args.no_notify,
        )
    except Exception as e:  # noqa: BLE001
        log.error("run failed: %s", e)
        return 1
    log.info("done: %s (score %.1f)", sig.verdict, sig.verdict_score)
    return 0


if __name__ == "__main__":
    sys.exit(main())
