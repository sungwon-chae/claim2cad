"""Claim2CAD — patent-claim-to-CAD pipeline.

Importing this package configures logging once: messages flow to both
``stdout`` and ``logs/run.log`` (rotating at 1 MB, 3 backups). All submodules
should call ``logging.getLogger(__name__)`` and the configuration is inherited.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

__version__ = "0.1.0"

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "run.log"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s :: %(message)s"


def _configure_logging() -> None:
    root = logging.getLogger("claim2cad")
    if root.handlers:
        return  # Already configured (e.g. re-imported from a test).

    level_name = os.environ.get("CLAIM2CAD_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root.setLevel(level)

    formatter = logging.Formatter(_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S")

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            _LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        rotating.setFormatter(formatter)
        root.addHandler(rotating)
    except OSError as exc:  # boundary: filesystem failures shouldn't crash imports.
        root.warning("Could not open %s for logging: %s", _LOG_FILE, exc)


_configure_logging()
