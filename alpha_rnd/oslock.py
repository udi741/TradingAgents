#!/usr/bin/env python3
"""Cross-platform advisory file locking matching the fcntl.flock API used by
alpha_rnd state modules.

POSIX: delegates to fcntl.flock (kernel inter-process lock).
Windows: msvcrt.locking on a 1-byte range — a real inter-process lock
(rejecting concurrent writers), not a no-op. LOCK_EX|LOCK_NB contention
raises BlockingIOError to match POSIX behavior; blocking LOCK_EX retries
with a bounded deadline (~60s), then raises TimeoutError.

Usage mirrors fcntl:
    oslock.flock(fd, oslock.LOCK_EX)
    oslock.flock(fd, oslock.LOCK_EX | oslock.LOCK_NB)
    oslock.flock(fd, oslock.LOCK_UN)
"""
import os
import sys
import time

if os.name == "posix":
    import fcntl as _fcntl
    LOCK_SH = _fcntl.LOCK_SH
    LOCK_EX = _fcntl.LOCK_EX
    LOCK_NB = _fcntl.LOCK_NB
    LOCK_UN = _fcntl.LOCK_UN

    def flock(fd, flags):
        return _fcntl.flock(fd, flags)

else:
    import msvcrt

    LOCK_SH = 1
    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    _BLOCK_DEADLINE_S = 60.0

    def _lock_region(fd, exclusive: bool, block: bool):
        fileno = fd.fileno() if hasattr(fd, "fileno") else fd
        # lock byte 0 of the file; seek restored afterward
        fileno  # msvcrt operates on the OS fd
        cur = os.lseek(fileno, 0, os.SEEK_CUR)
        os.lseek(fileno, 0, os.SEEK_SET)
        try:
            mode = msvcrt.LK_LOCK if block else (
                msvcrt.LK_NBLCK if exclusive else msvcrt.LK_NBRLCK)
            msvcrt.locking(fileno, mode, 1)
        finally:
            os.lseek(fileno, cur, os.SEEK_SET)

    def _unlock(fd):
        fileno = fd.fileno() if hasattr(fd, "fileno") else fd
        cur = os.lseek(fileno, 0, os.SEEK_CUR)
        os.lseek(fileno, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fileno, msvcrt.LK_UNLCK, 1)
        finally:
            os.lseek(fileno, cur, os.SEEK_SET)

    def flock(fd, flags):
        if flags & LOCK_UN:
            return _unlock(fd)
        excl = bool(flags & (LOCK_EX | LOCK_SH))
        if flags & LOCK_NB:
            try:
                _lock_region(fd, excl, block=False)
            except OSError as e:
                raise BlockingIOError(str(e)) from e
            return
        # blocking: retry until acquired or deadline
        deadline = time.time() + _BLOCK_DEADLINE_S
        while True:
            try:
                _lock_region(fd, excl, block=False)
                return
            except OSError as e:
                if time.time() >= deadline:
                    raise TimeoutError("oslock deadline exceeded") from e
                time.sleep(0.05)
