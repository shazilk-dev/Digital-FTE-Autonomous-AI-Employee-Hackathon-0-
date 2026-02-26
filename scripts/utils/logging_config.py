"""Logging configuration for AI Employee watchers."""

import logging
import logging.handlers
import os
from pathlib import Path


def setup_logger(name: str, log_level: str | None = None) -> logging.Logger:
    """
    Configure and return a logger.

    - Level from LOG_LEVEL env var (default INFO)
    - Format: "[YYYY-MM-DD HH:MM:SS] [LEVEL] [name] message"
    - Output to stderr (so stdout is clean for piping)
    - Also log to file: {vault_path}/Logs/watcher_{name}.log (rotating, 5MB max, 3 backups)
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    level_str = log_level or os.getenv("LOG_LEVEL", "INFO")
    level = getattr(logging, level_str.upper(), logging.INFO)
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # stderr handler
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    # Rotating file handler — only if VAULT_PATH is set
    vault_path_str = os.getenv("VAULT_PATH")
    if vault_path_str:
        vault_path = Path(vault_path_str)
        logs_dir = vault_path / "Logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f"watcher_{name}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
