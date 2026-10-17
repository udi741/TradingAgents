'use strict';
/* TradingAgents Command Center — vanilla JS, no deps. */

// ---------- helpers ----------
const $ = sel => document.querySelector(sel);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = String(text);
  return e;
}
function frag() { return document.createDocumentFragment(); }

const DASH = '—';
const nul = v => v === null || v === undefined || v === '' || (typeof v === 'number' && Number.isNaN(v));

function fmtNum(v, dp = 2) {
  if (nul(v)) return DASH;
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
function fmtInt(v) { return nul(v) ? DASH : Number(v).toLocaleString('en-US'); }
function fmtMoney(v) {
  if (nul(v)) return DASH;
  const n = Number(v);
  return (n < 0 ? '-$' : '$') + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPct(v, dp = 2) { return nul(v) ? DASH : Number(v).toFixed(dp) + '%'; }
function fmtSigned(v, dp = 2) { return nul(v) ? DASH : (v >= 0 ? '+' : '') + Number(v).toFixed(dp); }
function fmtTs(v) { return nul(v) ? DASH : String(v).replace('T', ' ').replace(/\.\d+/, '').replace('+00:00', 'Z'); }
function ago(ts) {
  if (nul(ts)) return DASH;
  const t = Date.parse(ts);
  if (Number.isNaN(t)) return DASH;
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 90) return Math.round(s) + 's ago';
  if (s < 5400) return Math.round(s / 60) + 'm ago';
  if (s < 129600) return (s / 3600).toFixed(1) + 'h ago';
  return (s / 86400).toFixed(1) + 'd ago';
}
function signedClass(v) { return nul(v) ? '' : (v >= 0 ? 'pos' : 'neg'); }

async function api(path) {
  const r = await fetch(path, { headers: { 'Accept': 'application/json' } });
  if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + path);
  return r.json();
}

function chip(text, kind) { return el('span', 'chip' + (kind ? ' chip-' + kind : ''), nul(text) ? 'UNKNOWN' : text); }
function chipFor(text, map) {
  if (nul(text)) return chip('UNKNOWN', 'gray');
  return chip(text, map[String(text)] || map._default || '');
}
const STATUS_KIND = {
  OK: 'ok', HEALTHY: 'ok', MARKED: 'ok', SUCCESS: 'ok', COMPLETE: 'ok', AVAILABLE: 'ok',
  VALIDATED: 'info', ENQUEUED: 'teal', FILLED: 'ok', EXECUTED: 'ok', PENDING_FILL: 'warn',
  TRIGGERED: 'warn', FAILED: 'bad', BROKEN: 'bad', DUPLICATED: 'warn', DEGRADED: 'warn',
  UNKNOWN: 'gray', STALE: 'warn', UNMARKED: 'warn',
  ACTIVE_PRODUCTION: 'ok', ACTIVE_PARTIAL: 'teal', SHADOW_ONLY: 'purple',
  RESEARCH_ONLY: 'info', LEGACY: 'gray', UNUSED: 'gray',
};

// meta freshness/degraded banner
function metaBanner(meta) {
  if (!meta) return null;
  const items = Array.isArray(meta) ? meta : Object.values(meta);
  const bad = items.filter(m => m && typeof m === 'object' && 'state' in m && m.state !== 'ok');
  if (!bad.length) return null;
  const b = el('div', 'banner banner-bad');
  b.textContent = 'DEGRADED STATE — ' + bad.length + ' source(s) not ok: ' +
    bad.map(m => (m.path ? m.path.split('/').pop() : '?') + ' [' + m.state + ']').join(', ');
  return b;
}

// generic sortable/filterable table
// cols: [{k, label, num, fmt(v,row), sort}]
function makeTable(cols, rows, opts = {}) {
  const wrap = el('div');
  const filter = el('input', 'filterbox');
  filter.placeholder = opts.filterPlaceholder || 'filter…';
  const count = el('span', 'tbl-count');
  wrap.appendChild(filter); wrap.appendChild(count);
  const tw = el('div', 'tablewrap');
  const tbl = el('table', 'dt');
  const thead = el('thead'); const htr = el('tr');
  let sortKey = opts.sortKey || null, sortDir = opts.sortDir || 1;
  cols.forEach((c, i) => {
    const th = el('th', c.num ? 'num' : '', c.label);
    th.dataset.i = i;
    th.addEventListener('click', () => {
      if (sortKey === i) sortDir = -sortDir; else { sortKey = i; sortDir = 1; }
      render();
    });
    htr.appendChild(th);
  });
  thead.appendChild(htr); tbl.appendChild(thead);
  const tbody = el('tbody'); tbl.appendChild(tbody);
  tw.appendChild(tbl); wrap.appendChild(tw);

  function cellVal(c, r) {
    const v = c.sort !== undefined ? (typeof c.sort === 'function' ? c.sort(r) : r[c.sort]) : r[c.k];
    if (nul(v)) return null;
    return v;
  }
  function render() {
    tbody.textContent = '';
    const q = filter.value.trim().toLowerCase();
    let data = rows.filter(r => !q || cols.some(c => {
      const v = cellVal(c, r); return v !== null && String(v).toLowerCase().includes(q);
    }));
    if (sortKey !== null) {
      const c = cols[sortKey];
      data = data.slice().sort((a, b) => {
        const va = cellVal(c, a), vb = cellVal(c, b);
        if (va === null && vb === null) return 0;
        if (va === null) return 1; if (vb === null) return -1;
        return (typeof va === 'number' && typeof vb === 'number')
          ? (va - vb) * sortDir : String(va).localeCompare(String(vb)) * sortDir;
      });
    }
    count.textContent = data.length + ' / ' + rows.length;
    cols.forEach((c, i) => {
      const th = htr.children[i];
      th.querySelectorAll('.arrow').forEach(x => x.remove());
      if (i === sortKey) th.appendChild(el('span', 'arrow', sortDir > 0 ? '▲' : '▼'));
    });
    if (!data.length) {
      const tr = el('tr'); const td = el('td', 'dim', '(no rows)');
      td.colSpan = cols.length; tr.appendChild(td); tbody.appendChild(tr); return;
    }
    data.forEach(r => {
      const tr = el('tr');
      cols.forEach(c => {
        const td = el('td', c.num ? 'num' : '');
        const out = c.fmt ? c.fmt(r[c.k], r) : (nul(r[c.k]) ? DASH : String(r[c.k]));
        if (out instanceof Node) td.appendChild(out); else td.textContent = out;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }
  render();
  return wrap;
}

function pageHead(title, refreshFn) {
  const h = el('div', 'page-head');
  h.appendChild(el('h1', 'pagetitle', title));
  const btn = el('button', 'refresh-btn', '↻ refresh');
  btn.addEventListener('click', refreshFn);
  h.appendChild(btn);
  const lr = el('span', 'last-refresh'); lr.id = 'last-refresh';
  h.appendChild(lr);
  return h;
}
function markRefreshed() {
  const lr = $('#last-refresh');
  if (lr) lr.textContent = 'last refresh ' + new Date().toISOString().replace('T', ' ').slice(0, 19) + 'Z';
}
function errPanel(e) {
  const p = el('div', 'error-panel');
  p.textContent = 'FETCH FAILED\n' + (e && e.message ? e.message : String(e));
  return p;
}
function kvList(pairs) {
  const d = el('div', 'kv');
  pairs.forEach(([k, v]) => {
    d.appendChild(el('div', 'k', k));
    const vv = el('div', 'v');
    if (v instanceof Node) vv.appendChild(v); else vv.textContent = nul(v) ? DASH : String(v);
    d.appendChild(vv);
  });
  return d;
}
function tickerLink(t) {
  const a = el('a', 'ticker-link', t);
  a.href = '#/positions/' + encodeURIComponent(t);
  return a;
}
function statStrip(stats) {
  const s = el('div', 'statstrip');
  stats.forEach(([k, v, cls, sub]) => {
    const st = el('div', 'stat');
    st.appendChild(el('div', 'k', k));
    st.appendChild(el('div', 'v ' + (cls || ''), v));
    if (sub) st.appendChild(el('div', 's', sub));
    s.appendChild(st);
  });
  return s;
}
function emptyNote(t) { return el('div', 'empty', t || '(none)'); }
function objChips(obj, map) {
  const f = frag();
  if (!obj || !Object.keys(obj).length) { f.appendChild(emptyNote()); return f; }
  Object.entries(obj).forEach(([k, v]) => {
    const c = chip(k + ' · ' + v, (map && map[v]) || '');
    f.appendChild(c);
  });
  return f;
}

// ---------- pages ----------
const pages = {};

pages.overview = async (root) => {
  const d = await api('/api/overview');
  const mb = metaBanner(d.meta); if (mb) root.appendChild(mb);
  const p = d.portfolio || {};
  root.appendChild(statStrip([
    ['Cash', fmtMoney(p.cash)],
    ['NAV', fmtMoney(p.nav)],
    ['Market Value', fmtMoney(p.market_value)],
    ['Exposure', fmtMoney(p.exposure)],
    ['Realized', fmtMoney(p.realized), signedClass(p.realized)],
    ['Unrealized', fmtMoney(p.unrealized), signedClass(p.unrealized),
      'marked ' + (p.mark_session || DASH)],
  ]));
  if (p.unmarked_positions && p.unmarked_positions.length)
    root.appendChild(el('div', 'banner', 'UNMARKED positions: ' + p.unmarked_positions.join(', ')));

  // attention
  const att = d.attention || [];
  if (att.length) {
    const h = el('h2', 'sec', 'Attention required');
    root.appendChild(h);
    att.forEach(a => {
      const isMgmt = /MGMT_ACTION|ADAPTIVE_EXECUTION/i.test(a.kind || '');
      const b = el('div', 'banner ' + (isMgmt ? 'banner-shadow' : ''));
      b.appendChild(chip(a.kind, isMgmt ? 'purple' : 'warn'));
      b.appendChild(document.createTextNode(' ' + (a.ticker || '') + ' — ' + (a.detail || DASH)));
      root.appendChild(b);
    });
  }

  const g = el('div', 'grid grid-2');
  // positions mini-table
  const pp = el('div', 'panel');
  pp.appendChild(el('div', 'panel-title', 'Positions'));
  if (d.positions && d.positions.length) {
    pp.appendChild(makeTable([
      { k: 'ticker', label: 'Ticker', fmt: v => tickerLink(v) },
      { k: 'shares', label: 'Shs', num: true, fmt: v => fmtInt(v) },
      { k: 'fill', label: 'Fill', num: true, fmt: v => fmtNum(v) },
      { k: 'mark', label: 'Mark', num: true, fmt: v => fmtNum(v) },
      { k: 'unrealized', label: 'Unrl', num: true, fmt: v => el('span', signedClass(v), fmtSigned(v)) },
      { k: 'unrealized_pct', label: 'Unrl %', num: true, fmt: v => el('span', signedClass(v), fmtPct(v)) },
      { k: 'mark_status', label: 'Mark st', fmt: v => chipFor(v, STATUS_KIND) },
      { k: 'mark_session', label: 'Mk sess' },
      { k: 'seeded', label: 'Seeded', fmt: v => v ? chip('SEEDED', 'warn') : '' },
    ], d.positions, { sortKey: 0 }));
  } else pp.appendChild(emptyNote());
  g.appendChild(pp);

  // pending + watch
  const pw = el('div', 'panel');
  pw.appendChild(el('div', 'panel-title', 'Pending orders'));
  const pendRows = [
    ...(d.pending_entries || []).map(x => ({ side: 'ENTRY', ...x })),
    ...(d.pending_exits || []).map(x => ({ side: 'EXIT', ...x })),
  ];
  if (pendRows.length) {
    pw.appendChild(makeTable([
      { k: 'side', label: 'Side', fmt: v => chip(v, v === 'EXIT' ? 'warn' : 'info') },
      { k: 'ticker', label: 'Ticker', fmt: v => tickerLink(v) },
      { k: 'type', label: 'Type' },
      { k: 'shares', label: 'Shs', num: true, fmt: v => fmtInt(v) },
      { k: 'reason', label: 'Reason', fmt: v => el('span', 'dim', v) },
      { k: 'confirm_session', label: 'Confirm sess' },
    ], pendRows, { sortKey: 0 }));
  } else pw.appendChild(emptyNote('no pending orders'));
  pw.appendChild(el('div', 'panel-title mt', 'Watch status'));
  const wdiv = el('div');
  Object.entries(d.watch_status || {}).forEach(([t, s]) => {
    const c = chip(t + ': ' + s, s === 'TRIGGERED' ? 'warn' : 'info');
    wdiv.appendChild(c);
  });
  if (!Object.keys(d.watch_status || {}).length) wdiv.appendChild(emptyNote());
  pw.appendChild(wdiv);
  if (d.risk_blocked && Object.keys(d.risk_blocked).length) {
    pw.appendChild(el('div', 'panel-title mt', 'Risk blocked'));
    const rb = el('div');
    Object.entries(d.risk_blocked).forEach(([t, r]) => rb.appendChild(chip(t + ': ' + r, 'bad')));
    pw.appendChild(rb);
  }
  g.appendChild(pw);
  root.appendChild(g);

  // scheduler
  const lc = (d.scheduler || {}).last_cycle;
  const sp = el('div', 'panel');
  sp.appendChild(el('div', 'panel-title', 'Scheduler — last cycle'));
  if (lc) {
    const an = (lc.summary || {}).analysis || {};
    const pub = (lc.summary || {}).published || {};
    sp.appendChild(kvList([
      ['session', lc.session],
      ['finished_at', fmtTs(lc.finished_at) + ' (' + ago(lc.finished_at) + ')'],
      ['ta requested/succeeded/failed', [an.ta_requested, an.ta_succeeded, an.ta_failed].map(x => nul(x) ? DASH : x).join(' / ')],
      ['analysis complete', an.analysis_complete === undefined ? DASH : String(an.analysis_complete)],
      ['published watch_count', pub.watch_count],
      ['published_at', fmtTs(pub.published_at)],
      ['deep selected', ((lc.summary || {}).deep || []).join(', ')],
      ['validated', ((lc.summary || {}).validated || []).join(', ')],
    ]));
  } else sp.appendChild(emptyNote('no scheduler data'));
  root.appendChild(sp);
};

pages.funnel = async (root, params) => {
  const session = params.get('session');
  const d = await api('/api/funnel' + (session ? '?session=' + encodeURIComponent(session) : ''));
  const mb = metaBanner(d.meta); if (mb) root.appendChild(mb);
  const f = d.funnel || {};

  // session selector
  if (d.sessions && d.sessions.length) {
    const sel = el('select', 'filterbox');
    sel.style.width = 'auto';
    d.sessions.forEach(s => {
      const o = el('option', '', s); o.value = s;
      if (s === f.session) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener('change', () => { location.hash = '#/funnel?session=' + sel.value; });
    const lab = el('div'); lab.appendChild(el('span', 'dim small', 'session ')); lab.appendChild(sel);
    root.appendChild(lab);
  }

  const stages = [
    ['raw universe', f.raw_universe_count],
    ['eligible', f.eligible_count],
    ['candidate pool', f.summary && f.summary.deep_selected ? 'see pool' : null],
    ['deep selected', f.deep_selected_count],
    ['TA completed', f.ta_completed_count],
    ['exec watch', f.executable_watch_count],
    ['triggered', f.triggered_count],
    ['paper entries', f.paper_entry_count],
  ];
  const band = el('div', 'funnel-band');
  stages.forEach(([k, v], i) => {
    if (i) band.appendChild(el('span', 'farrow', '→'));
    const st = el('div', 'fstage');
    st.appendChild(el('div', 'k', k));
    st.appendChild(el('div', 'v', nul(v) ? 'UNKNOWN' : (typeof v === 'number' ? fmtInt(v) : String(v))));
    band.appendChild(st);
  });
  root.appendChild(band);
  // disposition counts
  const dd = el('div');
  dd.appendChild(el('span', 'dim small', 'publication dispositions: '));
  Object.entries(f.publication_disposition_counts || {}).forEach(([k, v]) =>
    dd.appendChild(chip(k + ' ' + v, k === 'EXECUTABLE_WATCH' ? 'ok' : 'info')));
  root.appendChild(dd);

  const s = f.summary || {};
  const g = el('div', 'grid grid-2 mt');
  const p1 = el('div', 'panel'); p1.appendChild(el('div', 'panel-title', 'Exclusion counts'));
  p1.appendChild(kvList(Object.entries(s.excluded || {}).map(([k, v]) => [k, fmtInt(v)])));
  g.appendChild(p1);
  const p2 = el('div', 'panel'); p2.appendChild(el('div', 'panel-title', 'Rank cohorts'));
  p2.appendChild(kvList(Object.entries(s.rank_cohorts || {}).map(([k, v]) => [k, fmtInt(v)])));
  g.appendChild(p2);
  root.appendChild(g);

  // candidates + publication intents
  const c = await api('/api/candidates' + (session ? '?session=' + encodeURIComponent(session) : ''));
  const mb2 = metaBanner(c.meta); if (mb2) root.appendChild(mb2);
  const intents = (c.publication && c.publication.intents) || {};
  root.appendChild(el('h2', 'sec', 'Candidate pool — session ' + ((c.pool || {}).session || DASH) +
    ' (frozen ' + fmtTs((c.pool || {}).frozen_at) + ')'));
  const cands = (c.pool && c.pool.candidates) || [];
  if (cands.length) {
    root.appendChild(makeTable([
      { k: 'ticker', label: 'Ticker', fmt: v => tickerLink(v) },
      { k: 'labels', label: 'Labels', fmt: v => { const f2 = frag(); (v || []).forEach(l => f2.appendChild(chip(l, 'gray'))); return f2; } },
      { k: 'close', label: 'Close', num: true, fmt: v => fmtNum(v) },
      { k: 'ret_5', label: 'ret5', num: true, fmt: v => el('span', signedClass(v), fmtSigned(v * 100, 1) + '%'), sort: r => r.ret_5 },
      { k: 'ret_20', label: 'ret20', num: true, fmt: v => el('span', signedClass(v), fmtSigned(v * 100, 1) + '%'), sort: r => r.ret_20 },
      { k: 'rs_60', label: 'rs60', num: true, fmt: v => fmtNum(v, 2) },
      { k: 'rsi_14', label: 'RSI', num: true, fmt: v => fmtNum(v, 1) },
      { k: 'deep_score', label: 'DeepScore', num: true, fmt: v => fmtNum(v, 1) },
      {
        k: '_disp', label: 'Disposition', sort: r => { const it = intents[r.ticker]; return it ? (it.disposition || it.classification) : null; },
        fmt: (v, r) => { const it = intents[r.ticker]; return it ? chipFor(it.disposition || it.classification, { ...STATUS_KIND, _default: 'info' }) : chip('—', 'gray'); }
      },
      { k: '_wm', label: 'Watch mode', sort: r => { const it = intents[r.ticker]; return it && it.watch_mode; }, fmt: (v, r) => { const it = intents[r.ticker]; return it && it.watch_mode ? it.watch_mode : DASH; } },
      { k: '_trig', label: 'Trigger', sort: () => null, fmt: (v, r) => { const it = intents[r.ticker]; return it && it.trigger ? el('span', 'dim small', String(it.trigger).slice(0, 90)) : DASH; } },
      { k: '_inv', label: 'Invalidation / stop / target / horizon', sort: () => null, fmt: (v, r) => {
        const it = intents[r.ticker]; if (!it) return DASH;
        const parts = [];
        if (it.invalidation) parts.push('inv: ' + it.invalidation);
        if (it.stop_level != null) parts.push('stop: ' + it.stop_level);
        if (it.target != null) parts.push('tgt: ' + it.target);
        if (it.horizon) parts.push('hz: ' + it.horizon);
        return el('span', 'dim small', parts.join(' · ').slice(0, 140) || DASH);
      } },
    ], cands, { sortKey: 7, sortDir: -1 }));
  } else root.appendChild(emptyNote('no candidate pool'));

  if (c.pool && c.pool.lane_counts) {
    root.appendChild(el('h2', 'sec', 'Lane counts'));
    root.appendChild(kvList(Object.entries(c.pool.lane_counts).map(([k, v]) => [k, fmtInt(v)])));
  }
};

pages.research = async (root) => {
  const d = await api('/api/research');
  const rows = (d.artifacts || []);
  root.appendChild(el('div', 'dim small', rows.length + ' artifacts — click a row to open the decision record'));
  root.appendChild(makeTable([
    { k: 'ticker', label: 'Ticker', fmt: v => { const a = el('a', 'ticker-link', v); a.href = '#/research/' + v; return a; } },
    { k: 'session', label: 'Session' },
    { k: 'kind', label: 'Kind', fmt: v => chipFor(v, STATUS_KIND) },
    { k: 'file', label: 'File', fmt: v => el('span', 'mono dim', v) },
    { k: 'mtime_utc', label: 'Modified', fmt: v => el('span', '', fmtTs(v) + ' (' + ago(v) + ')') },
  ], rows, { sortKey: 4, sortDir: -1 }));
};

pages.researchDetail = async (root, ticker) => {
  const d = await api('/api/research/' + encodeURIComponent(ticker));
  const mb = metaBanner(d.meta); if (mb) root.appendChild(mb);
  const a = d.artifact || {};
  if (a.error || (d.meta && d.meta.state !== 'ok')) {
    root.appendChild(el('div', 'banner banner-bad', 'artifact state: ' + (d.meta && d.meta.state) + (a.error ? ' — ' + a.error : '')));
  }
  const chips = el('div');
  [['signal', a.signal], ['rm_rating', a.rm_rating], ['trader_action', a.trader_action],
   ['pm_rating', a.pm_rating], ['model', a.model_routing], ['duration_s', nul(a.duration_s) ? null : fmtNum(a.duration_s, 1)],
   ['decision_session', a.decision_session]]
    .forEach(([k, v]) => chips.appendChild(chip(k + ': ' + (nul(v) ? 'UNKNOWN' : v), 'info')));
  root.appendChild(chips);
  if (d.available && d.available.length) {
    const av = el('div', 'dim small mt'); av.textContent = 'artifacts: ';
    d.available.forEach(x => av.appendChild(chip(x.session + ' ' + x.kind, x.kind === 'ok' ? 'ok' : 'bad')));
    root.appendChild(av);
  }
  const sections = ['market_report', 'sentiment_report', 'news_report', 'fundamentals_report',
    'bull_history', 'bear_history', 'judge_decision', 'investment_plan',
    'trader_investment_plan', 'risk_judge_decision', 'final_trade_decision'];
  sections.forEach(k => {
    const v = a[k];
    if (nul(v)) return;
    const det = el('details', 'sec-block');
    det.appendChild(el('summary', '', k.replace(/_/g, ' ')));
    const body = el('div', 'body');
    const pre = el('div', 'preblock');
    pre.textContent = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
    body.appendChild(pre); det.appendChild(body);
    root.appendChild(det);
  });
};

pages.positions = async (root) => {
  const d = await api('/api/positions');
  const mb = metaBanner(d.meta); if (mb) root.appendChild(mb);
  const rows = d.positions || [];
  if (!rows.length) { root.appendChild(emptyNote('no open positions')); }
  else {
    root.appendChild(makeTable([
      { k: 'ticker', label: 'Ticker', fmt: v => tickerLink(v) },
      { k: 'shares', label: 'Shs', num: true, fmt: v => fmtInt(v) },
      { k: 'fill', label: 'Fill', num: true, fmt: v => fmtNum(v) },
      { k: 'mark', label: 'Mark', num: true, fmt: v => fmtNum(v) },
      { k: 'unrealized', label: 'Unrl $', num: true, fmt: v => el('span', signedClass(v), fmtSigned(v)) },
      { k: 'unrealized_pct', label: 'Unrl %', num: true, fmt: v => el('span', signedClass(v), fmtPct(v)) },
      { k: 'mark_status', label: 'Mark st', fmt: v => chipFor(v, STATUS_KIND) },
      { k: 'mark_session', label: 'Mk sess' },
      { k: 'seeded', label: 'Seeded', fmt: v => v ? chip('SEEDED', 'warn') : '' },
      { k: 'invalidation', label: 'Invalidation', fmt: v => el('span', 'dim', v) },
    ], rows, { sortKey: 0 }));
  }
  if (d.watch_status && Object.keys(d.watch_status).length) {
    root.appendChild(el('h2', 'sec', 'Watch status'));
    root.appendChild(objChips(d.watch_status, { TRIGGERED: 'warn', RISK_PLAN_REQUIRED: 'info' }));
  }
};

pages.positionDetail = async (root, ticker) => {
  const d = await api('/api/positions/' + encodeURIComponent(ticker));
  const p = d.position || {};
  root.appendChild(el('h2', 'sec', 'Current state'));
  const cs = el('div', 'panel');
  cs.appendChild(kvList([
    ['ticker', ticker], ['shares', fmtInt(p.shares)], ['fill', fmtMoney(p.fill)],
    ['mark', fmtMoney(p.mark)], ['mark_status', p.mark_status], ['mark_session', p.mark_session],
    ['mark_source', p.mark_source],
    ['unrealized', fmtSigned(p.unrealized) + ' (' + fmtPct(p.unrealized_pct) + ')'],
    ['invalidation', p.invalidation], ['horizon', p.horizon],
    ['seeded', p.seeded ? 'SEEDED / legacy' : 'no'],
  ]));
  root.appendChild(cs);

  root.appendChild(el('h2', 'sec', 'Entry plan / Phase-G snapshot'));
  if (!d.has_phase_g_snapshot || !d.entry_snapshot) {
    root.appendChild(el('div', 'banner', 'LEGACY/SEEDED — no Phase-G snapshot'));
  } else {
    const es = d.entry_snapshot, rp = es.risk_plan || {};
    const ep = el('div', 'panel');
    ep.appendChild(kvList([
      ['entry_price', fmtMoney(es.entry_price)], ['entry_session', es.entry_session],
      ['initial_shares', fmtInt(es.initial_shares)],
      ['stop_level', fmtMoney(rp.stop_level)],
      ['stop_rule', rp.stop_rule], ['invalidation', rp.invalidation || es.invalidation],
      ['bear_case', es.bear_case], ['catalysts', es.catalysts],
      ['reevaluation', es.reevaluation], ['horizon', es.horizon],
      ['missing_context', (es.missing_context || []).join(', ')],
      ['artifact', es.artifact_ref],
    ]));
    root.appendChild(ep);
  }

  root.appendChild(el('h2', 'sec', 'Watch rules'));
  const wr = el('div', 'panel');
  if (d.watch) wr.appendChild(kvList([['watch', JSON.stringify(d.watch)]]));
  if (d.open_position_rules) {
    const r = d.open_position_rules;
    wr.appendChild(kvList([
      ['style', r.style], ['invalidation', r.invalidation ? r.invalidation.type + ' @ ' + r.invalidation.level + ' (' + (r.invalidation.label || '') + ')' : DASH],
      ['exit_rules', (r.exit_rules || []).map(x => x.type + ' @ ' + x.level + (x.label ? ' ' + x.label : '')).join('; ')],
      ['reeval', r.reeval], ['horizon', r.horizon], ['artifact', r.artifact],
    ]));
  }
  if (!d.watch && !d.open_position_rules) wr.appendChild(emptyNote());
  root.appendChild(wr);

  root.appendChild(el('h2', 'sec', 'Management actions'));
  const ma = el('div', 'panel');
  const acts = Object.values(d.management_actions || {});
  if (acts.length) ma.appendChild(makeTable([
    { k: 'action_id', label: 'ID', fmt: v => el('span', 'mono', v) },
    { k: 'action', label: 'Action', fmt: v => chip(v, 'info') },
    { k: 'status', label: 'Status', fmt: v => chipFor(v, STATUS_KIND) },
    { k: 'qty', label: 'Qty', num: true, fmt: v => fmtInt(v) },
    { k: 'expected_remaining', label: 'Remain', num: true, fmt: v => fmtInt(v) },
    { k: 'remainder_status', label: 'Rem status', fmt: v => chipFor(v, STATUS_KIND) },
    { k: 'remainder_rule', label: 'Remainder rule', fmt: v => v ? el('span', 'dim small', v.type + ' @ ' + v.level + ' — ' + String(v.label).slice(0, 80)) : DASH },
    { k: 'enqueued_at', label: 'Enqueued', fmt: v => fmtTs(v) },
  ], acts, { sortKey: 0 }));
  else ma.appendChild(emptyNote());
  root.appendChild(ma);

  root.appendChild(el('h2', 'sec', 'Shadow reassessments'));
  const lbl = el('div', 'section-label lbl-shadow', 'SHADOW — analyses only, no economic authority');
  root.appendChild(lbl);
  const anas = (d.management_analyses || []).map(x => x.analysis || x);
  if (anas.length) {
    root.appendChild(makeTable([
      { k: 'recommended_action', label: 'Action', fmt: v => chipFor(v, { _default: 'purple' }) },
      { k: 'thesis_status', label: 'Thesis' },
      { k: 'catalyst_status', label: 'Catalyst' },
      { k: 'confidence', label: 'Conf' },
      { k: 'proposed_stop', label: 'Proposed stop', num: true, fmt: v => fmtNum(v), sort: r => r.proposed_stop },
      { k: 'reasoning_summary', label: 'Reasoning', fmt: v => el('span', 'dim small', String(v || '').slice(0, 160) || DASH), sort: r => r.reasoning_summary },
      { k: 'next_reassessment', label: 'Next', fmt: v => el('span', 'dim small', String(v || '').slice(0, 80)) },
    ], anas, { sortKey: 0 }));
  } else root.appendChild(emptyNote());

  root.appendChild(el('h2', 'sec', 'Management intents'));
  const lbl2 = el('div', 'section-label lbl-shadow', 'SHADOW VALIDATION — NOT ECONOMIC');
  root.appendChild(lbl2);
  const ints = d.management_intents || [];
  if (ints.length) {
    root.appendChild(makeTable([
      { k: 'action_id', label: 'ID', fmt: v => el('span', 'mono', v) },
      { k: 'recommended_action', label: 'Action', fmt: v => chipFor(v, { _default: 'purple' }) },
      { k: 'status', label: 'Status', fmt: v => chipFor(v, { _default: 'purple' }) },
      { k: 'proposed_exit_fraction', label: 'Frac', num: true, fmt: v => fmtNum(v, 2) },
      { k: 'normalized_exit_quantity', label: 'Qty', num: true, fmt: v => fmtInt(v) },
      { k: 'decision_session', label: 'Session' },
      { k: 'validated_at', label: 'Validated', fmt: v => fmtTs(v) },
      { k: 'risk_validation', label: 'Risk val', fmt: v => v && v.status ? chip(v.status, 'purple') : DASH },
    ], ints, { sortKey: 0 }));
  } else root.appendChild(emptyNote());

  // timeline
  root.appendChild(el('h2', 'sec', 'Timeline'));
  const tl = [];
  (d.ledger_records || []).forEach(r => tl.push({ ts: r.frozen_at || r.ts || r.session, kind: 'LEDGER', t: r.type, det: r.ticker ? r.ticker + ' ' + (r.shares ? r.shares + 'sh ' : '') + (r.fill_price ? '@' + r.fill_price : '') : (r.note || '') }));
  (d.trigger_events || []).forEach(r => tl.push({ ts: r.utc || r.at || r.frozen_at || r.confirm_session, kind: 'TRIGGER', t: r.action || r.family || r.kind, det: (r.why || r.reason || '') }));
  (d.management_events || []).forEach(r => tl.push({ ts: r.at, kind: 'MGMT', t: r.kind + (r.result ? '/' + r.result : ''), det: (r.ticker || '') + ' ' + (r.reason || r.result || '') }));
  tl.sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
  if (tl.length) {
    root.appendChild(makeTable([
      { k: 'ts', label: 'TS', fmt: v => el('span', 'mono', fmtTs(v)) },
      { k: 'kind', label: 'Src', fmt: v => chip(v, v === 'MGMT' ? 'purple' : v === 'TRIGGER' ? 'warn' : 'info') },
      { k: 't', label: 'Type' },
      { k: 'det', label: 'Detail', fmt: v => el('span', 'dim small', String(v || '').slice(0, 120)) },
    ], tl, { sortKey: 0 }));
  } else root.appendChild(emptyNote());
};

pages.management = async (root) => {
  const d = await api('/api/management');
  const mb = metaBanner(d.meta); if (mb) root.appendChild(mb);
  const pol = d.policy || {};
  const enabled = pol.execution && pol.execution.enabled;

  root.appendChild(el('h2', 'sec', 'Adaptive execution policy'));
  const flag = el('div', 'banner ' + (enabled ? 'banner-bad' : ''));
  flag.style.fontWeight = '700';
  flag.textContent = 'ADAPTIVE EXECUTION: ' + (enabled ? 'ENABLED' : 'DISABLED') +
    '  (policy v' + (pol.version || '?') + ', mode ' + (pol.mode || '?') + ')';
  root.appendChild(flag);
  if (pol.execution && pol.execution.comment)
    root.appendChild(el('div', 'dim small', pol.execution.comment));

  const g = el('div', 'grid grid-2');
  // deterministic
  const det = el('div', 'panel');
  det.appendChild(el('div', 'section-label lbl-det', 'DETERMINISTIC'));
  const det0 = d.deterministic || {};
  det.appendChild(el('div', 'panel-title', 'Pending open exits'));
  const poe = det0.pending_open_exits || [];
  if (poe.length) det.appendChild(makeTable([
    { k: 'ticker', label: 'Ticker', fmt: v => tickerLink(v) },
    { k: 'type', label: 'Type' },
    { k: 'shares', label: 'Shs', num: true, fmt: v => fmtInt(v) },
    { k: 'reason', label: 'Reason', fmt: v => el('span', 'dim small', v) },
    { k: 'confirm_session', label: 'Confirm' },
  ], poe));
  else det.appendChild(emptyNote('none'));
  det.appendChild(el('div', 'panel-title mt', 'Position invalidations'));
  const pinv = det0.positions_invalidation || {};
  if (Object.keys(pinv).length) det.appendChild(kvList(Object.entries(pinv).map(([k, v]) => [k, v])));
  else det.appendChild(emptyNote());
  g.appendChild(det);

  // adaptive actions lifecycle
  const ad = el('div', 'panel');
  ad.appendChild(el('div', 'section-label lbl-ad', 'ADAPTIVE'));
  ad.appendChild(el('div', 'panel-title', 'Actions lifecycle (VALIDATED → ENQUEUED → FILLED → EXECUTED)'));
  const acts = Object.values(d.actions || {});
  if (acts.length) ad.appendChild(makeTable([
    { k: 'action_id', label: 'ID', fmt: v => el('span', 'mono', v) },
    { k: 'action', label: 'Action' },
    { k: 'status', label: 'Status', fmt: v => chipFor(v, STATUS_KIND) },
    { k: 'qty', label: 'Qty', num: true, fmt: v => fmtInt(v) },
    { k: 'remainder_status', label: 'Rem status', fmt: v => chipFor(v, STATUS_KIND) },
    { k: 'remainder_rule', label: 'Remainder', fmt: v => v ? el('span', 'dim small', v.type + ' @ ' + v.level) : DASH },
    { k: 'enqueued_at', label: 'Enqueued', fmt: v => fmtTs(v) },
  ], acts));
  else ad.appendChild(emptyNote());
  g.appendChild(ad);
  root.appendChild(g);

  // trigger families
  if (pol.triggers) {
    root.appendChild(el('h2', 'sec', 'Trigger families'));
    const tp = el('div', 'panel');
    tp.appendChild(kvList(Object.entries(pol.triggers).map(([k, v]) =>
      [k, Object.entries(v).map(([kk, vv]) => kk + '=' + vv).join(' · ').slice(0, 200)])));
    root.appendChild(tp);
  }

  // analyses
  root.appendChild(el('h2', 'sec', 'Analyses (SHADOW)'));
  const anas = (d.analyses || []).map(x => x.analysis || x);
  if (anas.length) root.appendChild(makeTable([
    { k: 'ticker', label: 'Ticker', sort: r => r.ticker || (r.position_id || '').split(':')[0], fmt: (v, r) => tickerLink(r.ticker || (r.position_id || '').split(':')[0]) },
    { k: 'recommended_action', label: 'Action', fmt: v => chipFor(v, { _default: 'purple' }) },
    { k: 'thesis_status', label: 'Thesis' },
    { k: 'catalyst_status', label: 'Catalyst' },
    { k: 'confidence', label: 'Conf' },
    { k: 'reasoning_summary', label: 'Summary', fmt: v => el('span', 'dim small', String(v || '').slice(0, 140)) },
  ], anas));
  else root.appendChild(emptyNote());

  // events tail deduped
  root.appendChild(el('h2', 'sec', 'Events (tail, deduped)'));
  const evs = d.events || [];
  const groups = [];
  for (const e of evs) {
    const key = e.kind + '|' + (e.result || '') + '|' + (e.ticker || '');
    const last = groups[groups.length - 1];
    if (last && last.key === key) { last.count++; last.last = e; }
    else groups.push({ key, count: 1, first: e, last: e });
  }
  if (groups.length) root.appendChild(makeTable([
    { k: 'at', label: 'Last at', sort: r => r.last.at, fmt: (v, r) => el('span', 'mono', fmtTs(r.last.at)) },
    { k: 'count', label: '×', num: true, sort: r => r.count, fmt: (v, r) => r.count > 1 ? el('span', 'mono', '×' + r.count) : '' },
    { k: 'kind', label: 'Kind', sort: r => r.last.kind, fmt: (v, r) => el('span', 'mono', r.last.kind) },
    { k: 'result', label: 'Result', sort: r => r.last.result, fmt: (v, r) => chipFor(r.last.result, { ALREADY_ENQUEUED: 'warn', _default: '' }) },
    { k: 'ticker', label: 'Ticker', sort: r => r.last.ticker, fmt: (v, r) => r.last.ticker ? tickerLink(r.last.ticker) : DASH },
    { k: 'det', label: 'Detail', sort: () => null, fmt: (v, r) => el('span', 'dim small', JSON.stringify(Object.assign({}, r.last, { at: undefined, kind: undefined, result: undefined, ticker: undefined })).slice(0, 120)) },
  ], groups, { sortKey: 0 }));
  else root.appendChild(emptyNote());
};

pages.executions = async (root) => {
  const d = await api('/api/executions');
  const mb = metaBanner(d.meta); if (mb) root.appendChild(mb);
  root.appendChild(el('div', 'banner banner-info',
    'recommendation ≠ pending ≠ fill. ' + (d.authority_note || 'executed[] is the fill authority.')));
  const g = el('div', 'grid grid-2');
  const pe = el('div', 'panel'); pe.appendChild(el('div', 'panel-title', 'Pending entries'));
  if ((d.pending_entries || []).length) pe.appendChild(makeTable([
    { k: 'ticker', label: 'Ticker', fmt: v => tickerLink(v) },
    { k: 'type', label: 'Type' }, { k: 'reason', label: 'Reason' },
    { k: 'confirm_session', label: 'Confirm' },
  ], d.pending_entries)); else pe.appendChild(emptyNote('none'));
  pe.appendChild(el('div', 'panel-title mt', 'Pending exits'));
  if ((d.pending_exits || []).length) pe.appendChild(makeTable([
    { k: 'ticker', label: 'Ticker', fmt: v => tickerLink(v) },
    { k: 'type', label: 'Type' }, { k: 'shares', label: 'Shs', num: true, fmt: v => fmtInt(v) },
    { k: 'reason', label: 'Reason', fmt: v => el('span', 'dim small', v) },
    { k: 'confirm_session', label: 'Confirm' },
  ], d.pending_exits)); else pe.appendChild(emptyNote('none'));
  g.appendChild(pe);
  const ex = el('div', 'panel');
  ex.appendChild(el('div', 'panel-title', 'executed[] — the fill authority (' + (d.executed_ids || []).length + ')'));
  (d.executed_ids || []).forEach(id => {
    const dv = el('div', 'mono small', id); dv.style.padding = '2px 0'; ex.appendChild(dv);
  });
  if (!(d.executed_ids || []).length) ex.appendChild(emptyNote());
  g.appendChild(ex);
  root.appendChild(g);

  root.appendChild(el('h2', 'sec', 'Ledger tail'));
  const lt = d.ledger_tail || [];
  if (lt.length) {
    root.appendChild(makeTable([
      { k: 'frozen_at', label: 'Frozen at', fmt: v => el('span', 'mono', fmtTs(v)), sort: r => r.frozen_at || r.session },
      { k: 'type', label: 'Type', fmt: v => chip(v, 'info') },
      { k: 'session', label: 'Session' },
      { k: 'ticker', label: 'Ticker', fmt: v => v ? tickerLink(v) : DASH },
      { k: 'shares', label: 'Shs', num: true, fmt: v => fmtInt(v) },
      { k: 'fill_price', label: 'Price', num: true, fmt: v => fmtNum(v) },
      { k: 'notional', label: 'Notional', num: true, fmt: v => fmtMoney(v) },
      { k: 'note', label: 'Note', fmt: (v, r) => el('span', 'dim small', (v || r.trigger || r.invalidation || JSON.stringify(r.entries ? r.entries.length + ' entries' : '')).toString().slice(0, 110)) },
    ], lt, { sortKey: 0 }));
  } else root.appendChild(emptyNote());

  root.appendChild(el('h2', 'sec', 'Trigger events (tail, deduped)'));
  const seen = new Set(); const tev = [];
  (d.trigger_events || []).forEach(e => {
    const id = e.event_id || JSON.stringify(e);
    if (seen.has(id)) return; seen.add(id); tev.push(e);
  });
  if (tev.length) root.appendChild(makeTable([
    { k: 'utc', label: 'UTC', fmt: v => el('span', 'mono', fmtTs(v)) },
    { k: 'ticker', label: 'Ticker', fmt: v => v ? tickerLink(v) : DASH },
    { k: 'action', label: 'Action', fmt: v => chipFor(v, { _default: 'warn' }) },
    { k: 'kind', label: 'Kind' },
    { k: 'why', label: 'Why', fmt: v => el('span', 'dim small', String(v || '').slice(0, 110)) },
    { k: 'confirm_session', label: 'Confirm' },
    { k: 'missed_session', label: 'Missed' },
  ], tev, { sortKey: 0 }));
  else root.appendChild(emptyNote());
};

pages.performance = async (root) => {
  const d = await api('/api/performance');
  const mb = metaBanner(d.meta); if (mb) root.appendChild(mb);
  if (d.sample && d.sample.sufficient === false) {
    const b = el('div', 'banner banner-bad banner-big');
    b.textContent = 'INSUFFICIENT SAMPLE — ' + (d.sample.closed_trades || 0) + ' closed trades; ' + (d.sample.note || 'statistics withheld');
    root.appendChild(b);
  }
  root.appendChild(statStrip([
    ['NAV', fmtMoney(d.nav)],
    ['Realized', fmtMoney(d.realized), signedClass(d.realized)],
    ['Unrealized', fmtMoney(d.unrealized), signedClass(d.unrealized)],
    ['Fills', fmtInt(d.fill_count)],
    ['Closed exit events', fmtInt(d.closed_exit_events)],
  ]));

  // mark_series chart
  root.appendChild(el('h2', 'sec', 'Unrealized P&L over sessions'));
  const ms = d.mark_series || [];
  if (ms.length) {
    // aggregate per session (last value per session)
    const bySess = {};
    ms.forEach(m => { bySess[m.session] = m.unrealized; });
    const pts = Object.entries(bySess).sort((a, b) => a[0].localeCompare(b[0]));
    root.appendChild(svgLineChart(pts.map(([s, v]) => ({ x: s, y: v }))));
    const note = el('div', 'chart-note', pts.length + ' sessions (last mark per session); ' + ms.length + ' raw rows');
    root.appendChild(note);
  } else root.appendChild(emptyNote('no mark series'));

  root.appendChild(el('h2', 'sec', 'Fills'));
  const fills = d.fills || [];
  if (fills.length) root.appendChild(makeTable([
    { k: 'session', label: 'Session' },
    { k: 'ticker', label: 'Ticker', fmt: v => tickerLink(v) },
    { k: 'fill_price', label: 'Fill', num: true, fmt: v => fmtNum(v) },
    { k: 'shares', label: 'Shs', num: true, fmt: v => fmtInt(v) },
    { k: 'notional', label: 'Notional', num: true, fmt: v => fmtMoney(v) },
    { k: 'pm', label: 'PM', fmt: v => chip(v, 'info') },
    { k: 'trigger', label: 'Trigger', fmt: v => el('span', 'dim small', String(v || '').slice(0, 90)) },
  ], fills, { sortKey: 0 }));
  else root.appendChild(emptyNote());
  if (d.cohort_outcomes) {
    root.appendChild(el('h2', 'sec', 'Cohort outcomes'));
    root.appendChild(kvList(Object.entries(d.cohort_outcomes).map(([k, v]) => [k, String(v)])));
  }
};

function svgLineChart(pts) {
  const W = 720, H = 190, P = { l: 56, r: 14, t: 12, b: 28 };
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  svg.style.width = '100%'; svg.style.maxWidth = W + 'px'; svg.style.height = 'auto';
  const box = el('div', 'chart-box'); box.appendChild(svg);
  if (!pts.length) return box;
  const ys = pts.map(p => p.y);
  let ymin = Math.min(0, ...ys), ymax = Math.max(0, ...ys);
  if (ymax - ymin < 1) { ymax += 1; ymin -= 1; }
  const X = i => P.l + (pts.length === 1 ? (W - P.l - P.r) / 2 : i * (W - P.l - P.r) / (pts.length - 1));
  const Y = v => P.t + (ymax - v) * (H - P.t - P.b) / (ymax - ymin);
  // gridlines
  for (let i = 0; i <= 4; i++) {
    const v = ymin + i * (ymax - ymin) / 4, y = Y(v);
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', P.l); ln.setAttribute('x2', W - P.r);
    ln.setAttribute('y1', y); ln.setAttribute('y2', y);
    ln.setAttribute('stroke', '#262d36'); svg.appendChild(ln);
    const t = document.createElementNS(ns, 'text');
    t.setAttribute('x', P.l - 6); t.setAttribute('y', y + 3); t.setAttribute('text-anchor', 'end');
    t.setAttribute('fill', '#6e7681'); t.setAttribute('font-size', '9'); t.setAttribute('font-family', 'monospace');
    t.textContent = fmtNum(v, 0); svg.appendChild(t);
  }
  // zero line
  if (ymin < 0 && ymax > 0) {
    const ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', P.l); ln.setAttribute('x2', W - P.r);
    ln.setAttribute('y1', Y(0)); ln.setAttribute('y2', Y(0));
    ln.setAttribute('stroke', '#484f58'); ln.setAttribute('stroke-dasharray', '4 3'); svg.appendChild(ln);
  }
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', pts.map((p, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(p.y).toFixed(1)).join(' '));
  path.setAttribute('fill', 'none'); path.setAttribute('stroke', '#58a6ff'); path.setAttribute('stroke-width', '1.5');
  svg.appendChild(path);
  pts.forEach((p, i) => {
    const c = document.createElementNS(ns, 'circle');
    c.setAttribute('cx', X(i)); c.setAttribute('cy', Y(p.y)); c.setAttribute('r', '2.5');
    c.setAttribute('fill', p.y >= 0 ? '#3fb950' : '#f85149');
    const tt = document.createElementNS(ns, 'title'); tt.textContent = p.x + ': ' + fmtSigned(p.y);
    c.appendChild(tt); svg.appendChild(c);
  });
  // x labels (first/mid/last)
  [0, Math.floor((pts.length - 1) / 2), pts.length - 1].forEach(i => {
    if (i < 0) return;
    const t = document.createElementNS(ns, 'text');
    t.setAttribute('x', X(i)); t.setAttribute('y', H - 8); t.setAttribute('text-anchor', 'middle');
    t.setAttribute('fill', '#6e7681'); t.setAttribute('font-size', '9'); t.setAttribute('font-family', 'monospace');
    t.textContent = pts[i].x; svg.appendChild(t);
  });
  box.appendChild(el('div', 'chart-note', 'unrealized $ by session'));
  return box;
}

pages.providers = async (root) => {
  const d = await api('/api/providers');
  const inf = d.infra || {};
  const g = el('div', 'grid grid-3');
  const p1 = el('div', 'panel'); p1.appendChild(el('div', 'panel-title', 'Infra'));
  p1.appendChild(kvList([
    ['bridge_process', chipFor(inf.bridge_process, STATUS_KIND)],
    ['analysis_capability', chipFor(inf.analysis_capability, STATUS_KIND)],
    ['checked_at', fmtTs(inf.checked_at)],
    ['unit_active', inf.bridge_probe ? String(inf.bridge_probe.unit_active) : DASH],
    ['models_endpoint_ok', inf.bridge_probe ? String(inf.bridge_probe.models_endpoint_ok) : DASH],
  ]));
  g.appendChild(p1);
  const up = inf.upstream || {};
  const p2 = el('div', 'panel'); p2.appendChild(el('div', 'panel-title', 'Upstream'));
  p2.appendChild(kvList([
    ['status', chipFor(up.status, STATUS_KIND)],
    ['latest success', fmtTs(up.latest_success_at)],
    ['latest failure', fmtTs(up.latest_failure_at)],
    ['reason_code', up.reason_code],
    ['evidence_count', fmtInt(up.evidence_count)],
  ]));
  g.appendChild(p2);
  const an = d.analysis_status || {};
  const p3 = el('div', 'panel'); p3.appendChild(el('div', 'panel-title', 'Analysis status'));
  p3.appendChild(kvList([
    ['session', an.session], ['status', chipFor(an.status, STATUS_KIND)],
    ['ta req/succ/fail', [an.ta_requested, an.ta_succeeded, an.ta_failed].map(x => nul(x) ? DASH : x).join(' / ')],
    ['failed tickers', (an.failed_tickers || []).join(', ') || 'none'],
    ['checked_at', fmtTs(an.checked_at)],
  ]));
  g.appendChild(p3);
  root.appendChild(g);

  root.appendChild(el('h2', 'sec', 'Provider semantics (key names only — never values)'));
  root.appendChild(makeTable([
    { k: 'provider', label: 'Provider', fmt: v => el('span', 'mono', v) },
    { k: 'pit', label: 'PIT', fmt: v => el('span', 'dim small', v) },
    { k: 'retry', label: 'Retry', fmt: v => el('span', 'dim small', v) },
    { k: 'key', label: 'Key name', fmt: v => el('span', 'mono small', v) },
    { k: 'fail_visibility', label: 'Fail visibility', fmt: v => el('span', 'dim small', v) },
    { k: 'coverage', label: 'Coverage', fmt: v => el('span', 'dim small', v) },
    { k: 'status_note', label: 'Status note', fmt: v => el('span', 'dim small', v) },
  ], d.provider_semantics || [], { sortKey: 0 }));

  root.appendChild(el('h2', 'sec', 'Model failures'));
  const mf = d.model_failures || {};
  const mfRows = Object.entries(mf).map(([k, v]) => ({ k, v: typeof v === 'object' ? JSON.stringify(v).slice(0, 160) : String(v) }));
  if (mfRows.length) root.appendChild(makeTable([
    { k: 'k', label: 'Key', fmt: v => el('span', 'mono', v) },
    { k: 'v', label: 'Detail', fmt: v => el('span', 'dim small', v) },
  ], mfRows)); else root.appendChild(emptyNote('none recorded'));
  if (d.failure_reasons && Object.keys(d.failure_reasons).length) {
    root.appendChild(el('div', 'dim small', JSON.stringify(d.failure_reasons).slice(0, 400)));
  }

  root.appendChild(el('h2', 'sec', 'Market data health'));
  const mdh = d.market_data_health || {};
  root.appendChild(kvList(Object.entries(mdh).map(([k, v]) => [k, String(v)])));
  if (d.monitor_last_check) {
    root.appendChild(el('div', 'dim small mt', 'monitor last check: ' + JSON.stringify(d.monitor_last_check).slice(0, 300)));
  }
  const slc = d.scheduler_last_cycle;
  if (slc) {
    root.appendChild(el('h2', 'sec', 'Scheduler last cycle'));
    const an2 = (slc.summary || {}).analysis || {};
    root.appendChild(kvList([
      ['session', slc.session], ['finished_at', fmtTs(slc.finished_at)],
      ['ta req/succ/fail', [an2.ta_requested, an2.ta_succeeded, an2.ta_failed].map(x => nul(x) ? DASH : x).join(' / ')],
      ['watch_count', (slc.summary || {}).published ? (slc.summary.published.watch_count) : DASH],
    ]));
  }
};

pages.health = async (root) => {
  const d = await api('/api/health');
  const oh = d.ops_health || {};
  const overall = oh.overall;
  root.appendChild(el('div', 'banner ' + (overall === 'OK' || overall === 'HEALTHY' ? 'banner-info' : 'banner-bad') + ' banner-big',
    'OVERALL: ' + (overall || 'UNKNOWN')));
  root.appendChild(el('h2', 'sec', 'Checks'));
  root.appendChild(makeTable([
    { k: 'status', label: 'Status', fmt: v => chipFor(v, STATUS_KIND) },
    { k: 'name', label: 'Check', fmt: v => el('span', 'mono small', v) },
  ], oh.checks || [], { sortKey: 0, sortDir: -1 }));
  if (d.bridge) {
    root.appendChild(el('h2', 'sec', 'SWE bridge'));
    root.appendChild(kvList([
      ['reachable', String(d.bridge.reachable)],
      ['models', (d.bridge.models || []).join(', ')],
    ]));
  }
  if (d.ops_status && d.ops_status.lines) {
    root.appendChild(el('h2', 'sec', 'ops status'));
    const pre = el('div', 'preblock'); pre.textContent = d.ops_status.lines.join('\n');
    root.appendChild(pre);
  }
  if (d.units && d.units.length) {
    root.appendChild(el('h2', 'sec', 'systemd units'));
    root.appendChild(makeTable([
      { k: 'unit', label: 'Unit', fmt: v => el('span', 'mono', v) },
      { k: 'load', label: 'Load' },
      { k: 'active', label: 'Active', fmt: v => chipFor(v, { active: 'ok', inactive: 'gray', failed: 'bad' }) },
      { k: 'sub', label: 'Sub', fmt: v => chipFor(v, { running: 'ok', waiting: 'info', dead: 'gray', failed: 'bad' }) },
      { k: 'desc', label: 'Description', fmt: v => el('span', 'dim small', v) },
    ], d.units, { sortKey: 0 }));
  }
};

pages.capabilities = async (root) => {
  const d = await api('/api/capabilities');
  const mb = metaBanner(d.meta); if (mb) root.appendChild(mb);
  const head = el('div');
  head.appendChild(chip('registry v' + (d.registry_version ?? '?'), 'info'));
  head.appendChild(chip(d.count + ' capabilities', ''));
  root.appendChild(head);
  let statusFilter = null;
  const chipsRow = el('div', 'mt');
  const caps = d.capabilities || [];
  const holder = el('div');
  function renderTable() {
    holder.textContent = '';
    let rows = caps;
    if (statusFilter) rows = rows.filter(c => c.status === statusFilter);
    holder.appendChild(makeTable([
      { k: 'id', label: 'ID', fmt: v => el('span', 'mono', v) },
      { k: 'status', label: 'Status', fmt: v => chipFor(v, STATUS_KIND) },
      { k: 'purpose', label: 'Purpose', fmt: v => el('span', 'dim small', String(v || '').slice(0, 140)) },
      { k: 'modules', label: 'Modules', fmt: v => el('span', 'mono dim small', (v || []).join(', ').slice(0, 80)) },
      { k: 'authority', label: 'Authority', fmt: v => el('span', 'dim small', String(v || '').slice(0, 80)) },
      {
        k: 'limitations', label: '…', sort: () => null, fmt: v => {
          if (!v || !v.length) return '';
          const det = el('details');
          det.appendChild(el('summary', 'dim small', 'limitations/notes'));
          const b = el('div', 'preblock'); b.textContent = v.join('\n'); det.appendChild(b);
          return det;
        }
      },
    ], rows, { sortKey: 0 }));
  }
  Object.entries(d.by_status || {}).forEach(([st, n]) => {
    const c = chip(st + ' ' + n, STATUS_KIND[st] || 'gray');
    c.style.cursor = 'pointer';
    c.addEventListener('click', () => {
      statusFilter = statusFilter === st ? null : st;
      chipsRow.querySelectorAll('.chip').forEach(x => x.style.outline = '');
      if (statusFilter) c.style.outline = '1px solid currentColor';
      renderTable();
    });
    chipsRow.appendChild(c);
  });
  root.appendChild(chipsRow);
  root.appendChild(el('div', 'mt')).appendChild(holder);
  renderTable();
};

pages.tracks = async (root) => {
  const d = await api('/api/tracks');
  const warns = {
    alpha: 'ALPHA_RND — live R&D paper track',
    c12: 'C12 frozen control — never mixed',
    expert: 'EXPERT parked — never mixed with ALPHA economics',
    research: 'research simulations are not live economics',
  };
  const g = el('div', 'grid grid-2');
  ['alpha', 'c12', 'expert', 'research'].forEach(k => {
    const t = d[k]; if (!t) return;
    const p = el('div', 'panel');
    p.appendChild(el('div', 'panel-title', k.toUpperCase() + ' — ' + (t.name || '')));
    const b = el('div', 'banner', warns[k]); b.style.marginBottom = '8px'; p.appendChild(b);
    p.appendChild(kvList([
      ['type', t.type], ['root', t.authoritative_root], ['note', t.note],
    ]));
    if (k === 'alpha' && t.overview) {
      p.appendChild(el('div', 'dim small mt', 'see #/overview for full ALPHA portfolio state'));
    }
    if (k === 'c12' && t.latest_nav) {
      const nv = t.latest_nav;
      p.appendChild(el('div', 'panel-title mt', 'Latest NAV'));
      p.appendChild(kvList([
        ['nav', fmtMoney(nv.nav)], ['cash', fmtMoney(nv.cash)],
        ['open mkt value', fmtMoney(nv.open_mkt_value)],
        ['closed pnl', fmtMoney(nv.closed_pnl)],
        ['open positions', fmtInt(nv.open_positions)],
        ['ts', fmtTs(nv.ts)],
      ]));
      const tr = t.open_trades || [];
      if (tr.length) {
        p.appendChild(el('div', 'panel-title mt', 'Open trades'));
        p.appendChild(makeTable([
          { k: 'ticker', label: 'Ticker' },
          { k: 'decision_session', label: 'Dec sess' },
          { k: 'entry_session', label: 'Entry sess' },
          { k: 'entry_price', label: 'Entry', num: true, fmt: v => fmtNum(v) },
          { k: 'shares', label: 'Shs', num: true, fmt: v => fmtNum(v, 1) },
          { k: 'notional', label: 'Notional', num: true, fmt: v => fmtMoney(v) },
          { k: 'status', label: 'Status', fmt: v => chipFor(v, { OPEN: 'info', _default: '' }) },
        ], tr));
      }
    }
    g.appendChild(p);
  });
  root.appendChild(g);
  if (d.boundaries) {
    root.appendChild(el('h2', 'sec', 'Track boundaries'));
    Object.entries(d.boundaries).forEach(([k, v]) => {
      const p = el('div', 'panel');
      p.appendChild(el('div', 'panel-title', k));
      p.appendChild(kvList(Object.entries(v).map(([kk, vv]) => [kk, String(vv)])));
      root.appendChild(p);
    });
  }
};

pages.controls = async (root) => {
  const d = await api('/api/controls');
  root.appendChild(el('div', 'banner banner-info',
    'Safe operations — allowlist only. ' + (d.note || '')));
  (d.controls || []).forEach(c => {
    const card = el('div', 'control-card');
    const wrap = el('div', 'wrap');
    const row = el('div', 'row');
    row.appendChild(el('span', 'cid', c.id));
    row.appendChild(el('span', 'desc', c.desc));
    if (c.mutates) row.appendChild(chip('MUTATES', 'warn'));
    const btn = el('button', 'btn btn-danger', 'Run…');
    row.appendChild(btn);
    wrap.appendChild(row);
    card.appendChild(wrap);
    root.appendChild(card);
    btn.addEventListener('click', () => confirmControl(c, wrap, d.confirm_token || 'I_UNDERSTAND'));
  });
};

function confirmControl(c, wrap, token) {
  const dlg = el('dialog');
  const body = el('div', 'dialog-body');
  body.appendChild(el('h3', '', 'Confirm: ' + c.id));
  body.appendChild(el('div', 'effect',
    'Effect: ' + (c.desc || '(none)') + '\nTarget: POST /api/controls/' + c.id +
    '\nMutates: ' + (c.mutates ? 'YES' : 'no') +
    '\n\nType ' + token + ' to confirm.'));
  const inp = el('input'); inp.type = 'text'; inp.placeholder = token;
  body.appendChild(inp);
  const btns = el('div', 'dialog-btns');
  const cancel = el('button', 'btn', 'Cancel');
  const run = el('button', 'btn btn-danger', 'Execute');
  run.disabled = true;
  inp.addEventListener('input', () => { run.disabled = inp.value.trim() !== token; });
  cancel.addEventListener('click', () => dlg.close());
  run.addEventListener('click', async () => {
    run.disabled = true; run.textContent = 'running…';
    try {
      const r = await fetch('/api/controls/' + encodeURIComponent(c.id) + '?confirm=' + encodeURIComponent(token), { method: 'POST' });
      const j = await r.json().catch(() => ({}));
      const out = el('div', 'control-out');
      out.textContent = JSON.stringify(j, null, 2);
      wrap.appendChild(out);
    } catch (e) {
      wrap.appendChild(errPanel(e));
    }
    dlg.close();
  });
  btns.appendChild(cancel); btns.appendChild(run);
  body.appendChild(btns); dlg.appendChild(body);
  document.body.appendChild(dlg);
  dlg.addEventListener('close', () => dlg.remove());
  dlg.showModal(); inp.focus();
}

// ---------- router ----------
let navToken = 0;
let pageInflight = false;
function route2() {
  const hash = location.hash.slice(2) || 'overview';
  const [pathPart, queryPart] = hash.split('?');
  const params = new URLSearchParams(queryPart || '');
  const segs = pathPart.split('/').filter(Boolean);
  const name = segs[0] || 'overview';
  const arg = segs[1] ? decodeURIComponent(segs[1]) : null;
  document.querySelectorAll('#nav a').forEach(a =>
    a.classList.toggle('active', a.dataset.route === name));
  const page = $('#page');
  page.textContent = '';
  const title = name + (arg ? ' / ' + arg : '');
  page.appendChild(pageHead(title.toUpperCase(), () => route2()));
  const token = ++navToken;
  let fn = pages[name] || pages.overview;
  if (name === 'research' && arg) fn = pages.researchDetail;
  if (name === 'positions' && arg) fn = pages.positionDetail;
  pageInflight = true;
  Promise.resolve()
    .then(() => (name === 'research' && arg) ? pages.researchDetail(page, arg)
      : (name === 'positions' && arg) ? pages.positionDetail(page, arg)
      : fn(page, params))
    .then(markRefreshed)
    .catch(e => { if (token === navToken) page.appendChild(errPanel(e)); })
    .finally(() => { pageInflight = false; });
}

// ---------- near-live refresh ----------
// Persisted artifacts/state are the source of truth: re-render the current
// page every 30s. Guards: never overlap an in-flight render, never while the
// tab is hidden, a modal is open, or the user is typing in a field.
const PAGE_REFRESH_MS =
  parseInt(new URLSearchParams(location.search).get('refresh_ms')) || 30000;
function autoRefresh() {
  if (pageInflight || document.hidden) return;
  if (document.querySelector('dialog[open]')) return;
  const ae = document.activeElement;
  if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' ||
             ae.tagName === 'SELECT')) return;
  route2();
}
setInterval(autoRefresh, PAGE_REFRESH_MS);

// ---------- topbar ----------
async function pollTopbar() {
  try {
    const d = await api('/api/overview');
    const h = await api('/api/health').catch(() => null);
    const dot = $('#health-dot'), lab = $('#health-label');
    const overall = h && h.ops_health ? h.ops_health.overall : null;
    dot.className = 'dot ' + (overall === 'OK' || overall === 'HEALTHY' ? 'dot-ok' :
      overall === 'FAILED' ? 'dot-bad' : overall ? 'dot-warn' : 'dot-unknown');
    lab.textContent = overall || 'UNKNOWN';
    const ms = d.meta && d.meta.monitor_state;
    $('#freshness').textContent = ms && ms.mtime_utc
      ? 'monitor_state ' + fmtTs(ms.mtime_utc) + ' (' + ago(ms.mtime_utc) + ')' + (ms.state !== 'ok' ? ' [' + ms.state + ']' : '')
      : 'monitor_state UNKNOWN';
  } catch (e) {
    $('#health-dot').className = 'dot dot-bad';
    $('#health-label').textContent = 'API UNREACHABLE';
  }
}

// ticker search: try position detail first, fall back to research
$('#ticker-search').addEventListener('keydown', async (e) => {
  if (e.key !== 'Enter') return;
  const t = e.target.value.trim().toUpperCase();
  if (!t) return;
  try {
    const d = await api('/api/positions');
    if ((d.positions || []).some(p => p.ticker === t)) { location.hash = '#/positions/' + t; return; }
  } catch (_) { /* fall through to research */ }
  location.hash = '#/research/' + t;
  e.target.value = '';
});

window.addEventListener('hashchange', route2);
if (!location.hash) location.hash = '#/overview';
route2();
pollTopbar();
setInterval(pollTopbar, 60000);
