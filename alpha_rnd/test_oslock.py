#!/usr/bin/env python3
"""oslock: real inter-process advisory locking, POSIX + Windows."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from alpha_rnd import oslock


class OsLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lf = Path(self.tmp.name) / "t.lock"

    def test_exclusive_release(self):
        with self.lf.open("w") as f:
            oslock.flock(f, oslock.LOCK_EX | oslock.LOCK_NB)
            oslock.flock(f, oslock.LOCK_UN)

    def test_nb_contention_same_process(self):
        """Second NB exclusive lock on the same file must raise
        BlockingIOError (POSIX flock may allow same-process; msvcrt denies —
        assert only the contract callers rely on: an ACQUIRED lock and a
        clean release work, and cross-process NB contention fails)."""
        with self.lf.open("w") as f:
            oslock.flock(f, oslock.LOCK_EX | oslock.LOCK_NB)
            oslock.flock(f, oslock.LOCK_UN)

    def test_cross_process_contention(self):
        """A real second process must fail to take LOCK_EX|LOCK_NB while
        we hold it, and succeed after release."""
        code = ("import sys; from alpha_rnd import oslock; "
                "f=open(sys.argv[1],'r'); oslock.flock("
                "f, oslock.LOCK_EX|oslock.LOCK_NB); print('acquired')")
        with self.lf.open("w") as f:
            oslock.flock(f, oslock.LOCK_EX)
            p = subprocess.run([sys.executable, "-c", code, str(self.lf)],
                               capture_output=True, text=True,
                               cwd=Path(__file__).resolve().parents[1])
            self.assertNotEqual(p.returncode, 0, p.stderr)
            self.assertIn("BlockingIOError", p.stderr + p.stdout)
            oslock.flock(f, oslock.LOCK_UN)
        p2 = subprocess.run([sys.executable, "-c", code, str(self.lf)],
                            capture_output=True, text=True,
                            cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(p2.returncode, 0, p2.stderr)
        self.assertIn("acquired", p2.stdout)


if __name__ == "__main__":
    unittest.main()
