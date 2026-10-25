# Research workspace

All future autonomous strategy research lives here:

- Branch: `research/alpha-lab`
- Worktree: `~/udi_provate/TradingAgents-contract`
- Data: persistent outputs go to `~/udi_provate/*-data/` or
  `~/udi_provate/research-results-archive/` — never into a worktree.
- Archived dataset: `~/udi_provate/research-results-archive/eligible_bars.pkl`
  (md5 b25fe6abe3c115e65670ba2eedc01c79) — point `universe_pt.CACHE` /
  `admission_sensitivity.BARS` at this path when reproducing.
- `TradingAgents-backtest` = PROTECTED RUNTIME (shadow cron refs its
  path). Do not develop there.
- Production checkout, all cron entries, ALPHA/C12/PBF, shadow-data and
  decision-portfolio are off-limits.
- Historical experiment branches are archived via their commits/tags;
  all unique work is preserved in `~/udi_provate/research-results-archive/`
  and in git history.
