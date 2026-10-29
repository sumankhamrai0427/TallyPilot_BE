"""Centralized logging utility for TallyPilot."""
import logging
import sys
from utils.config import config


def get_logger(name: str = "TallyPilot") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
        logger.setLevel(log_level)
    return logger


logger = get_logger()

