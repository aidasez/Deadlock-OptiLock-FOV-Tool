"""Entry point for the Deadlock FOV tool."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deadlock_fov.gui import run

if __name__ == "__main__":
    raise SystemExit(run())
