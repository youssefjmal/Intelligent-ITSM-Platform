"""Refresh the Jira KB semantic index and print compact metrics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

from app.services.jira_kb import refresh_jira_kb_index  # noqa: E402


def main() -> int:
    metrics = refresh_jira_kb_index(force=True)
    print(json.dumps(metrics, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
