"""Shared deployment paths only; services own their storage and business logic."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APP_ROOT = Path(os.environ.get('DFM_APP_ROOT') or (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else BASE_DIR))
DATA_DIR = APP_ROOT / 'data'
STATIC_DIR = BASE_DIR / 'static'
