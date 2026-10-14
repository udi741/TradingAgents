#!/usr/bin/env python3
"""Read-only funnel status CLI: python -m alpha_rnd.funnel_status --session X"""
import sys

from . import funnel

if __name__ == "__main__":
    sess = "latest"
    if "--session" in sys.argv:
        sess = sys.argv[sys.argv.index("--session") + 1]
    print(funnel.status(sess))
