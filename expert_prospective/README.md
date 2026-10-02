# expert_prospective/

Append-only store for prospective expert signals. See
`../tracks/EXPERT_PROSPECTIVE_PROTOCOL.md`.

- `signals/<signal_id>/raw_message.txt` + `signal.json` + `events.jsonl` + `outcome.json`
- `ta_comparisons/<signal_id>/` frozen same-time TA state dumps

Never delete or rewrite a captured signal. Corrections are append-only events.
