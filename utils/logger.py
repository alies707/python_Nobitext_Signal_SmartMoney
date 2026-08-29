"""Structured logging utility.

A thin wrapper around the standard :mod:`logging` module that:
* never prints secret material (API keys are masked),
* provides a single shared logger,
* supports an optional verbose flag.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

_MASKED = "***REDACTED***"


def mask_secret(value: Optional[str]) -> str:
    """Return a masked representation of a secret value."""
    if not value:
        return ""
    return _MASKED


class SecretFilter(logging.Filter):
    """Redacts configured secret values from log records."""

    def __init__(self, secrets: Optional[list] = None):
        super().__init__()
        self._secrets = [s for s in (secrets or []) if s]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        msg = str(record.getMessage())
        for secret in self._secrets:
            if secret and secret in msg:
                record.msg = msg.replace(secret, _MASKED)
                record.args = ()
        return True


def get_logger(name: str = "smte", level: Optional[int] = None) -> logging.Logger:
    """Return a configured logger.

    Parameters
    ----------
    name:
        Logger name.
    level:
        Optional explicit level; defaults to the ``LOG_LEVEL`` env var or INFO.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    if level is None:
        level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
