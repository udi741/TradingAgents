#!/usr/bin/env python3
"""R7 CLI: python -m alpha_rnd.investigate --ticker TWST | --all | --build"""
import sys

from alpha_rnd import postmortems

if __name__ == "__main__":
    if "--all" in sys.argv:
        postmortems.build_all()
        for t in postmortems.TICKERS:
            print(postmortems.report(t))
            print("=" * 60)
    elif "--ticker" in sys.argv:
        print(postmortems.report(sys.argv[sys.argv.index("--ticker") + 1]))
    else:
        postmortems.build_all()
        print("built packets:", postmortems.OUT)
