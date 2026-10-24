"""Test-session shim: monitor/scheduler modules import POSIX-only `fcntl`
at module scope for live state locking. On Windows the import fails before
any test can run. The stubbed functions are only reached by tests that
exercise state locking, which none of the unit tests do."""
import sys
import types

if "fcntl" not in sys.modules:
    try:
        import fcntl  # noqa: F401
    except ImportError:
        fcntl = types.ModuleType("fcntl")
        fcntl.flock = lambda *a, **k: None
        fcntl.LOCK_EX = fcntl.LOCK_SH = fcntl.LOCK_UN = fcntl.LOCK_NB = 0
        sys.modules["fcntl"] = fcntl
