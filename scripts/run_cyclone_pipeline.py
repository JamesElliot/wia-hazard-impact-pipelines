#!/usr/bin/env python3
"""Compatibility wrapper for ``wia-hazards run-cyclone``."""

from __future__ import annotations

import sys

from wia_pipelines.cli import main as cli_main


def main() -> int:
    sys.argv.insert(1, "run-cyclone")
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
