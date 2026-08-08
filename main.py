#!/usr/bin/env python3
"""Compatibility entry point that preserves ``python main.py``."""

import sys

from src.cli import main

if __name__ == "__main__":
    sys.exit(main())
