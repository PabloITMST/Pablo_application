"""Launcher for host agents: python <repo>/pablo.py <command> ... (no install needed)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from pablo_v2.__main__ import main  # noqa: E402

sys.exit(main())
