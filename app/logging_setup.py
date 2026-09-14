# -*- coding: utf-8 -*-
"""统一日志配置。

要点：
1. 日志同时写控制台和滚动文件 ``<data>/logs/server.log``（单文件 5 MB × 5 份），
   打包成 exe 后双击运行也能事后查看。
2. uvicorn 启动时会用自带 dictConfig 覆盖已有 handler，因此这里既提供
   ``uvicorn_log_config()`` 直接交给 ``uvicorn.Config(log_config=...)``，
   也提供 ``configure_logging()`` 在应用导入时兜底挂文件 handler。
"""
import logging
import logging.handlers
from pathlib import Path
from typing import List

LOG_FILE_NAME = "server.log"
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

_configured_dir: Path = None  # type: ignore[assignment]


def log_dir(app_root: Path) -> Path:
    """日志目录：``<exe 同级目录或项目根>/data/logs``。"""
    path = Path(app_root) / "data" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file(app_root: Path) -> Path:
    return log_dir(app_root) / LOG_FILE_NAME


def _file_handler(path: Path) -> logging.Handler:
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    return handler


def _console_handler() -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    return handler


def configure_logging(app_root: Path, level: str = "INFO") -> Path:
    """配置根日志（文件 + 控制台），并给 uvicorn 各 logger 兜底挂文件 handler。

    可重复调用（只生效一次），返回日志文件路径。
    """
    global _configured_dir
    directory = log_dir(app_root)
    path = directory / LOG_FILE_NAME
    if _configured_dir == directory:
        return path

    root = logging.getLogger()
    root.setLevel(level.upper())
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        root.addHandler(_file_handler(path))
    if not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in root.handlers
    ):
        root.addHandler(_console_handler())

    # uvicorn 的 logger 默认 propagate=False 且启动时会被 dictConfig 重置，
    # 因此这里（应用导入后）再挂一次文件 handler，确保访问/错误日志落盘。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.setLevel(level.upper())
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers):
            logger.addHandler(_file_handler(path))

    _configured_dir = directory
    logging.getLogger("dfm").info("日志已启用：%s", path)
    return path


def uvicorn_log_config(app_root: Path, level: str = "info") -> dict:
    """供 ``uvicorn.Config(log_config=...)`` 使用，避免自带配置覆盖文件日志。"""
    path = log_dir(app_root) / LOG_FILE_NAME
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "dfm": {"format": LOG_FORMAT, "datefmt": DATE_FORMAT},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "dfm",
                "stream": "ext://sys.stderr",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "dfm",
                "filename": str(path),
                "maxBytes": MAX_BYTES,
                "backupCount": BACKUP_COUNT,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["console", "file"], "level": level.upper(), "propagate": False},
            "uvicorn.error": {"handlers": ["console", "file"], "level": level.upper(), "propagate": False},
            "uvicorn.access": {"handlers": ["console", "file"], "level": level.upper(), "propagate": False},
            "dfm": {"handlers": ["console", "file"], "level": level.upper(), "propagate": False},
        },
        "root": {"handlers": ["console", "file"], "level": level.upper()},
    }


def tail_lines(app_root: Path, lines: int = 200) -> List[str]:
    """读取日志文件最后 N 行（含轮转文件缺失时的容错）。"""
    path = log_dir(app_root) / LOG_FILE_NAME
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fp:
            return [line.rstrip("\n") for line in fp.readlines()[-max(1, lines):]]
    except OSError:
        return []
