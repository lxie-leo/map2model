"""日志配置:简洁的控制台输出格式,uvicorn 的日志也一并接管。"""

from __future__ import annotations

import logging.config


def setup_logging(level: str = "INFO") -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    "datefmt": "%H:%M:%S",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "stream": "ext://sys.stdout",
                },
            },
            "loggers": {
                "uvicorn": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn.error": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn.access": {"handlers": ["console"], "level": "WARNING", "propagate": False},
                "httpx": {"handlers": ["console"], "level": "WARNING", "propagate": False},
                "app": {"handlers": ["console"], "level": level, "propagate": False},
            },
            "root": {"handlers": ["console"], "level": level},
        }
    )
