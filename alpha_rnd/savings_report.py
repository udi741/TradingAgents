import json
from pathlib import Path

from alpha_rnd.case_integrity import verify_case


def compare_metrics(baseline: dict, optimized: dict | None) -> dict:
    if not isinstance(optimized, dict):
        return {"realized_savings": "NOT_MEASURED", "quality": "UNAVAILABLE"}
    base_time = baseline.get("wall_clock", {}).get("elapsed_ms")
    opt_time = optimized.get("wall_clock", {}).get("elapsed_ms")
    result = {"realized_savings": "MEASURED", "quality": {}}
    for key, before, after in (
        ("time_saved_ms", base_time, opt_time),
        ("model_calls_avoided",
         baseline.get("model_calls", {}).get("total"),
         optimized.get("model_calls", {}).get("total")),
        ("provider_calls_avoided",
         baseline.get("provider_calls", {}).get("logical_data_calls"),
         optimized.get("provider_calls", {}).get("logical_data_calls")),
    ):
        result[key] = before - after if isinstance(before, (int, float)) and isinstance(
            after, (int, float)
        ) else None
        result["quality"][key] = "MEASURED" if result[key] is not None else "UNAVAILABLE"
    before_network = baseline.get("provider_calls", {}).get("external_network_calls")
    after_network = optimized.get("provider_calls", {}).get("external_network_calls")
    result["external_network_calls_avoided"] = (
        before_network - after_network
        if isinstance(before_network, (int, float))
        and isinstance(after_network, (int, float)) else None
    )
    network_quality = (
        "MEASURED"
        if baseline.get("provider_calls", {}).get("external_network_quality") == "MEASURED"
        and optimized.get("provider_calls", {}).get("external_network_quality") == "MEASURED"
        else "PARTIAL" if result["external_network_calls_avoided"] is not None
        else "UNAVAILABLE"
    )
    result["quality"]["external_network_calls_avoided"] = network_quality
    result["time_saved_pct"] = (
        result["time_saved_ms"] / base_time * 100
        if base_time and result["time_saved_ms"] is not None else None
    )
    result["quality"]["time_saved_pct"] = (
        "MEASURED" if result["time_saved_pct"] is not None else "UNAVAILABLE"
    )
    baseline_tokens = baseline.get("tokens", {})
    optimized_tokens = optimized.get("tokens", {})
    token_quality = "MEASURED" if (
        baseline_tokens.get("availability") == "EXACT"
        and optimized_tokens.get("availability") == "EXACT"
        and all(isinstance(baseline_tokens.get(key), (int, float))
                and isinstance(optimized_tokens.get(key), (int, float))
                for key in ("input_tokens", "output_tokens", "total_tokens"))
    ) else "UNAVAILABLE"
    result["tokens"] = {
        "availability": token_quality,
        **{
            key: (
                baseline_tokens.get(key) - optimized_tokens.get(key)
                if token_quality == "MEASURED" else None
            )
            for key in ("input_tokens", "output_tokens", "total_tokens")
        },
    }
    result["token_saved_pct"] = (
        result["tokens"]["total_tokens"] / baseline_tokens["total_tokens"] * 100
        if token_quality == "MEASURED" and baseline_tokens.get("total_tokens") else None
    )
    result["quality"]["token_saved_pct"] = (
        "MEASURED" if result["token_saved_pct"] is not None else "UNAVAILABLE"
    )
    return result


def _validation_section(validation_dir: Path) -> str:
    """PAIRED VALIDATION + MEASURED SAVINGS from controlled paired runs."""
    try:
        from alpha_rnd.reuse_engine import evaluate_readiness, load_pairs
        pairs = load_pairs(validation_dir)
        gate = evaluate_readiness(validation_dir)
    except Exception as exc:
        return f"PAIRED VALIDATION\n\nUNAVAILABLE ({type(exc).__name__}: {exc})\n"
    if not pairs:
        return (
            "PAIRED VALIDATION\n\nPairs completed: 0\n\n"
            "ROLLOUT GATE\n\n"
            f"READY_FOR_OPTIMIZED_AUTHORITY: "
            f"{gate['ready_for_optimized_authority']}\n"
            "  auto-enable: NO — operator approval required\n")
    optimized_modes = {}
    for pair in pairs:
        mode = pair.get("optimized_mode") or "UNKNOWN"
        optimized_modes[mode] = optimized_modes.get(mode, 0) + 1
    signal_agree = sum(p.get("signal_agreement") is True for p in pairs if p.get("optimized_mode") != "FULL_REFRESH")
    rated = [p for p in pairs if p.get("optimized_mode") != "FULL_REFRESH"]
    rating_agree = sum(p.get("rating_agreement") is True for p in rated)
    exec_agree = sum(p.get("executable_action_agreement") is True for p in rated)
    unsafe = sum(p.get("executable_disagreement") is True for p in pairs)
    fallbacks = sum(p.get("fallback_to_full_refresh") is True for p in pairs)
    def _measured_values(key):
        return [
            p["savings"][key] for p in pairs
            if (p.get("savings") or {}).get("quality", {}).get(key) == "MEASURED"
            and isinstance(p["savings"].get(key), (int, float))
        ]

    saved_time = _measured_values("time_saved_ms")
    saved_model = _measured_values("model_calls_avoided")
    saved_prov = _measured_values("provider_calls_avoided")
    base_time = [
        (p.get("baseline_metrics") or {}).get("wall_clock", {}).get("elapsed_ms")
        for p in pairs]
    base_time = [v for v in base_time if isinstance(v, (int, float))]
    opt_time = [
        (p.get("optimized_metrics") or {}).get("wall_clock", {}).get("elapsed_ms")
        for p in pairs]
    opt_time = [v for v in opt_time if isinstance(v, (int, float))]
    token_q = {
        q: sum((p.get("savings") or {}).get("tokens", {}).get("availability") == q
               for p in pairs)
        for q in ("MEASURED", "UNAVAILABLE")
    }
    # FULL_REFRESH pairs paid real probe overhead — zero model savings plus
    # extra provider work must be visible, not hidden behind UPDATE/REUSE gains.
    refresh_pairs = [
        p for p in pairs if p.get("optimized_mode") == "FULL_REFRESH"]
    overhead_ms = [
        (p.get("probe_overhead") or {}).get("elapsed_ms")
        for p in refresh_pairs]
    overhead_ms = [v for v in overhead_ms if isinstance(v, (int, float))]
    overhead_calls = [
        (p.get("probe_overhead") or {}).get("provider_call_count")
        for p in refresh_pairs]
    overhead_calls = [v for v in overhead_calls if isinstance(v, (int, float))]
    net_model = [
        p["savings"]["model_calls_avoided"] for p in pairs
        if (p.get("savings") or {}).get("quality", {}).get("model_calls_avoided")
        == "MEASURED"]
    net_time = [
        p["savings"]["time_saved_ms"] for p in pairs
        if (p.get("savings") or {}).get("quality", {}).get("time_saved_ms")
        == "MEASURED"]
    partial_time = sum(
        (p.get("savings") or {}).get("quality", {}).get("time_saved_ms")
        == "PARTIAL" for p in pairs)
    safety = {}
    for pair in pairs:
        for reason in pair.get("decision_reasons") or []:
            safety[reason] = safety.get(reason, 0) + 1
    return (
        "PAIRED VALIDATION\n\n"
        f"Pairs completed: {len(pairs)} "
        f"across {len({p['ticker'] for p in pairs})} tickers\n"
        f"Optimized modes: {json.dumps(dict(sorted(optimized_modes.items())))}\n"
        f"Signal agreement: {signal_agree}/{len(rated)}\n"
        f"Rating agreement: {rating_agree}/{len(rated)}\n"
        f"Executable-action agreement: {exec_agree}/{len(rated)}\n"
        f"Unsafe disagreements: {unsafe}\n"
        f"Fallbacks to full refresh: {fallbacks}\n\n"
        "MEASURED SAVINGS (paired runs)\n"
        f"  baseline time: {sum(base_time):.3f} ms over {len(base_time)} runs\n"
        f"  optimized time: {sum(opt_time):.3f} ms over {len(opt_time)} runs\n"
        f"  time saved: {sum(saved_time):.3f} ms (MEASURED)\n"
        f"  model calls avoided: {sum(saved_model)} (MEASURED)\n"
        f"  provider calls avoided: {sum(saved_prov)} (MEASURED)\n"
        f"  token savings: {token_q['MEASURED']} MEASURED, "
        f"{token_q['UNAVAILABLE']} UNAVAILABLE\n\n"
        "FULL_REFRESH probe overhead (real cost, zero model savings):\n"
        f"  cases: {len(refresh_pairs)}\n"
        f"  measured probe time: "
        f"{sum(overhead_ms):.3f} ms over {len(overhead_ms)} cases\n"
        f"  extra logical provider requests: "
        f"{sum(overhead_calls)} over {len(overhead_calls)} cases\n\n"
        "NET / QUALITY:\n"
        f"  measured model-call effect: {sum(net_model)} calls "
        f"({len(net_model)} MEASURED pairs)\n"
        f"  measured time effect: {sum(net_time):.0f} ms "
        f"({len(net_time)} MEASURED pairs; {partial_time} PARTIAL not summed)\n\n"
        "ROLLOUT GATE\n\n"
        f"READY_FOR_OPTIMIZED_AUTHORITY: {gate['ready_for_optimized_authority']}\n"
        f"  pairs {gate['pairs_completed']}/{gate['required_pairs']}, "
        f"tickers {gate['distinct_tickers']}/{gate['required_tickers']}\n"
        f"  unsafe executable disagreements: {len(gate['unsafe_executable_disagreements'])}\n"
        f"  missed full-refresh triggers: {len(gate['missed_full_refresh_triggers'])}\n"
        f"  integrity/point-in-time failures: {len(gate['integrity_or_pit_failures'])}\n"
        f"  measured benefit: time {gate['measured_time_saved_ms']:.0f} ms, "
        f"model calls {gate['measured_model_calls_avoided']}\n"
        f"  auto-enable: NO — operator approval required\n\n"
        f"SAFETY TRIGGERS: {json.dumps(dict(sorted(safety.items())), sort_keys=True)}\n"
    )


def render_report(case_dir: Path, shadow_dir: Path | None = None,
                  validation_dir: Path | None = None) -> str:
    cases = []
    for path in sorted(case_dir.glob("*.json")):
        try:
            artifact = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(artifact, dict):
            cases.append(artifact)
    records = []
    for path in sorted((shadow_dir or case_dir.parent / "reuse_shadow").glob("*.json")):
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    modes = {
        name: sum(
            record.get("shadow_mode", {}).get("classification") == name
            for record in records
        )
        for name in ("FULL_REFRESH_REQUIRED", "UPDATE_MODE_RECOMMENDED", "REUSE_ELIGIBLE")
    }
    trusted_cases = [case for case in cases if verify_case(case)]
    elapsed = [
        case.get("analysis_metrics", {}).get("wall_clock", {}).get("elapsed_ms")
        for case in trusted_cases
    ]
    elapsed = [value for value in elapsed if isinstance(value, (int, float))]
    model_calls = [
        case.get("analysis_metrics", {}).get("model_calls", {}).get("total")
        for case in trusted_cases
    ]
    model_calls = [value for value in model_calls if isinstance(value, int)]
    provider_calls = [
        case.get("analysis_metrics", {}).get("provider_calls", {}).get("logical_data_calls")
        for case in trusted_cases
    ]
    provider_calls = [value for value in provider_calls if isinstance(value, int)]
    optimized = [
        case.get("optimized_analysis_metrics") for case in trusted_cases
        if isinstance(case.get("optimized_analysis_metrics"), dict)
    ]
    optimized_times = [
        metrics.get("wall_clock", {}).get("elapsed_ms") for metrics in optimized
    ]
    optimized_times = [value for value in optimized_times if isinstance(value, (int, float))]
    paired_savings = [
        compare_metrics(case.get("analysis_metrics", {}), case["optimized_analysis_metrics"])
        for case in trusted_cases if isinstance(case.get("optimized_analysis_metrics"), dict)
    ]
    measured_time_savings = [
        value["time_saved_ms"] for value in paired_savings
        if value["quality"]["time_saved_ms"] == "MEASURED"
    ]
    measured_model_savings = [
        value["model_calls_avoided"] for value in paired_savings
        if value["quality"]["model_calls_avoided"] == "MEASURED"
    ]
    measured_provider_savings = [
        value["provider_calls_avoided"] for value in paired_savings
        if value["quality"]["provider_calls_avoided"] == "MEASURED"
    ]
    network_savings = [
        value["external_network_calls_avoided"] for value in paired_savings
        if value["quality"]["external_network_calls_avoided"] in ("MEASURED", "PARTIAL")
    ]
    network_quality = (
        "PARTIAL" if any(
            value["quality"]["external_network_calls_avoided"] == "PARTIAL"
            for value in paired_savings
        ) else "MEASURED" if network_savings else "UNAVAILABLE"
    )
    measured_token_savings = [
        value["tokens"]["total_tokens"] for value in paired_savings
        if value["tokens"]["availability"] == "MEASURED"
    ]
    measured_time_percentages = [
        value["time_saved_pct"] for value in paired_savings
        if value["quality"]["time_saved_pct"] == "MEASURED"
    ]
    measured_token_percentages = [
        value["token_saved_pct"] for value in paired_savings
        if value["quality"]["token_saved_pct"] == "MEASURED"
    ]
    exact_tokens = sum(
        case.get("analysis_metrics", {}).get("tokens", {}).get("availability") == "EXACT"
        for case in trusted_cases
    )
    partial_tokens = sum(
        case.get("analysis_metrics", {}).get("tokens", {}).get("availability") == "PARTIAL"
        for case in trusted_cases
    )
    unavailable_tokens = len(cases) - exact_tokens - partial_tokens
    safety_reasons = {}
    for record in records:
        for reason in record.get("shadow_mode", {}).get("reasons", []):
            safety_reasons[reason] = safety_reasons.get(reason, 0) + 1
    projected_calls = sum(
        record.get("estimated_reuse", {}).get("estimated_model_calls_avoidable", 0) or 0
        for record in records
    )
    valid = len(trusted_cases)
    elapsed_text = (
        f"{sum(elapsed):.3f} ms across {len(elapsed)} runs"
        if elapsed else "UNAVAILABLE (0 measured runs)"
    )
    model_text = (
        f"{sum(model_calls)} across {len(model_calls)} runs"
        if model_calls else "UNAVAILABLE (0 measured runs)"
    )
    provider_text = (
        f"{sum(provider_calls)} across {len(provider_calls)} runs"
        if provider_calls else "UNAVAILABLE (0 measured runs)"
    )
    optimized_text = (
        f"{sum(optimized_times):.3f} ms across {len(optimized_times)} runs"
        if optimized_times else "UNAVAILABLE (0 optimized runs)"
    )
    savings_text = lambda values: (
        f"{sum(values)} MEASURED across {len(values)} paired runs"
        if values else "UNAVAILABLE"
    )
    return (
        "REPEAT ANALYSIS EFFICIENCY\n\n"
        f"Repeated cases: {len(records)}\n"
        f"Full refresh: {modes['FULL_REFRESH_REQUIRED']}\n"
        f"Update mode: {modes['UPDATE_MODE_RECOMMENDED']}\n"
        f"Reuse eligible: {modes['REUSE_ELIGIBLE']}\n\n"
        "Measured baseline:\n"
        f"  full-analysis time: {elapsed_text}\n"
        f"  logical model invocations: {model_text}\n"
        f"  logical provider calls: {provider_text}\n"
        f"  cases with exact token usage: {exact_tokens}\n"
        f"  partial token usage: {partial_tokens}\n"
        f"  unavailable token usage: {unavailable_tokens}\n\n"
        f"Actual optimized-analysis time: {optimized_text}\n"
        f"Time saved: {savings_text(measured_time_savings)}\n"
        f"Model calls avoided: {savings_text(measured_model_savings)}\n"
        f"Provider calls avoided: {savings_text(measured_provider_savings)}\n"
        f"External network calls avoided: "
        f"{sum(network_savings)} {network_quality} across {len(network_savings)} paired runs\n"
        f"Exact token savings: {savings_text(measured_token_savings)}\n"
        f"Time saved percentage: {savings_text(measured_time_percentages)}\n"
        f"Exact token saved percentage: {savings_text(measured_token_percentages)}\n"
        + (
            "REALIZED SAVINGS: NOT MEASURED — no optimized analysis has skipped work.\n"
            if not optimized else "REALIZED SAVINGS: paired run metrics shown above.\n"
        )
        + f"Projected model calls avoidable: ESTIMATED / PROJECTED lower bound {projected_calls}\n"
        f"Case artifacts: {len(cases)}; integrity verified: {valid}\n"
        f"Safety reasons: {json.dumps(dict(sorted(safety_reasons.items())), sort_keys=True)}\n\n"
        + _validation_section(
            validation_dir or case_dir.parent / "reuse_validation")
    )


if __name__ == "__main__":
    from alpha_rnd.reuse_shadow import CASE_DIR

    print(render_report(CASE_DIR))
