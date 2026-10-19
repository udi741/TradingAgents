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


def render_report(case_dir: Path, shadow_dir: Path | None = None) -> str:
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
        f"Safety reasons: {json.dumps(dict(sorted(safety_reasons.items())), sort_keys=True)}\n"
    )


if __name__ == "__main__":
    from alpha_rnd.reuse_shadow import CASE_DIR

    print(render_report(CASE_DIR))
