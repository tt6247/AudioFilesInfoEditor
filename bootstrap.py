"""Load project-local dependencies without modifying the user's Python setup."""
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / ".vendor"
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))
