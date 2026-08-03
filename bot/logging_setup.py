from __future__ import annotations
import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logging(log_dir: str, level: str = "INFO") -> None:
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level, logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s - %(message)s"
    )

    # Console
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # Rotating file
    fh = RotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        maxBytes=5_000_000,
        backupCount=5
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)
