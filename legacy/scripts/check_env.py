"""Print TEST from .env — manual env check."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os

from dotenv import load_dotenv

load_dotenv()

value = os.getenv("TEST")

print(value)
