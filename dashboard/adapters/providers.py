"""Provider/runtime health adapter.

Sources:
- registry provider_semantics (static semantics: PIT capability, retry policy)
- alpha_rnd/infra_status.py status_report() — authoritative bridge+upstream
  classification derived from the executor journal (imported read-only from
  the live worktree; falls back to local probe if import fails)
- analysis_status_<session>.json — per-ticker analysis failures
- monitor_state.data_health — market-data health rollup
"""
from __future__ import annotations

import sys

from .. import config
from ..readutil import read_json
from . import alpha, health, capabilities


def _infra_status() -> dict:
    try:
        if str(config.ALPHA_ROOT) not in sys.path:
            sys.path.insert(0, str(config.ALPHA_ROOT))
        import importlib
        mod = importlib.import_module("alpha_rnd.infra_status")
        return {"source": "alpha_rnd.infra_status.status_report",
                **mod.status_report()}
    except Exception as e:
        probe = health.bridge()
        return {"source": "local bridge probe (infra_status import failed)",
                "error": str(e),
                "bridge_probe": probe,
                "bridge_process": "HEALTHY" if probe.get("reachable") else "DOWN",
                "upstream": {"status": "UNKNOWN"},
                "analysis_capability": "UNKNOWN"}


def providers() -> dict:
    infra = _infra_status()
    reg = capabilities.summary()
    semantics = reg.get("provider_semantics") or {}
    st, st_meta = alpha.analysis_status()
    ms, _ = alpha.monitor()
    sched, _ = alpha.scheduler()

    # model/provider failures for the latest analysis session
    failures = (st or {}).get("failures") or {}
    fail_reasons = (st or {}).get("ta_failure_reasons") or {}

    provider_rows = []
    for name, sem in sorted(semantics.items()):
        provider_rows.append({
            "provider": name,
            "key": sem.get("key"),
            "pit": sem.get("pit"),
            "retry": sem.get("retry"),
            "fail_visibility": sem.get("fail_visibility"),
            "coverage": sem.get("coverage"),
            "status_note": sem.get("absent_key") or sem.get("status"),
        })

    return {
        "infra": infra,
        "provider_semantics": provider_rows,
        "analysis_status": st,
        "analysis_status_meta": st_meta,
        "model_failures": failures,
        "failure_reasons": fail_reasons,
        "market_data_health": (ms or {}).get("data_health"),
        "monitor_last_check": (ms or {}).get("last_check_utc"),
        "scheduler_last_cycle": (sched or {}).get("last_cycle"),
    }
