/* oriz-nifty-signal client-side screener engine. Backend-free: fetches the whole
   universe once, then filters / sorts / re-weights entirely in the browser.
   ~5000 rows kept snappy via a virtualized (windowed) table + debounced filters. */
(() => {
  'use strict';

  // ---- config: metric + factor metadata ---------------------------------
  const FACTORS = [
    { key: 'ep', label: 'E/P', z: 'ep' },
    { key: 'bp', label: 'B/P', z: 'bp' },
    { key: 'sp', label: 'S/P', z: 'sp' },
    { key: 'ebit_ev', label: 'EBIT/EV', z: 'ebit_ev' },
    { key: 'fcf_yield', label: 'FCF yield', z: 'fcf_yield' },
    { key: 'inv_peg', label: '1/PEG', z: 'inv_peg' },
    { key: 'div_yield', label: 'Div yield', z: 'div_yield' },
  ];
  // z-key aliases the pipeline may emit
  const Z_ALIASES = {
    ep: ['ep', 'e_p', 'earnings_yield'],
    bp: ['bp', 'b_p', 'book_yield'],
    sp: ['sp', 's_p', 'sales_yield'],
    ebit_ev: ['ebit_ev', 'ebitev', 'evebit', 'ebit_to_ev'],
    fcf_yield: ['fcf_yield', 'fcfy', 'fcf'],
    inv_peg: ['inv_peg', 'invpeg', 'peg_inv', 'one_over_peg'],
    div_yield: ['div_yield', 'divyield', 'dividend_yield', 'divYield'],
  };
  const COLUMNS = [
    { key: 'composite', label: 'Composite', fmt: 'z', help: 'Live value composite (weighted z-score)' },
    { key: 'symbol', label: 'Symbol', fmt: 'text' },
    { key: 'sector', label: 'Sector', fmt: 'text' },
    { key: 'mcap', label: 'Mcap ₹cr', fmt: 'int' },
    { key: 'pe', label: 'PE', fmt: 'x' },
    { key: 'pb', label: 'PB', fmt: 'x' },
    { key: 'ps', label: 'PS', fmt: 'x' },
    { key: 'ev_ebit', label: 'EV/EBIT', fmt: 'x' },
    { key: 'ev_ebitda', label: 'EV/EBITDA', fmt: 'x' },
    { key: 'p_fcf', label: 'P/FCF', fmt: 'x' },
    { key: 'peg', label: 'PEG', fmt: 'n2' },
    { key: 'fcf_yield', label: 'FCF yld %', fmt: 'pct1' },
    { key: 'div_yield', label: 'Div %', fmt: 'n2' },
    { key: 'roe', label: 'ROE %', fmt: 'n1' },
    { key: 'roce', label: 'ROCE %', fmt: 'n1' },
    { key: 'debt_to_equity', label: 'D/E', fmt: 'n2' },
    { key: 'f_score', label: 'Piotroski', fmt: 'int' },
    { key: 'earnings_growth_pct', label: 'EPS g %', fmt: 'n1' },
    { key: 'ret_1y', label: '1Y ret %', fmt: 'n1' },
    { key: 'aftertax_1y', label: 'After-tax 1Y %', fmt: 'n1', help: '1Y return − MTF interest − LTCG 12.5%' },
    { key: 'beta', label: 'Beta', fmt: 'n2' },
    { key: 'quality', label: 'Quality', fmt: 'bool' },
    { key: 'is_mtf_eligible', label: 'MTF', fmt: 'bool' },
    { key: 'completeness', label: 'Data', fmt: 'pct0', help: 'Fraction of core metrics present' },
  ];
  // metrics selectable in the numeric filter builder
  const FILTER_METRICS = COLUMNS.filter((c) =>
    ['x', 'n1', 'n2', 'int', 'pct1', 'pct0', 'z'].includes(c.fmt),
  ).concat([{ key: 'value_score', label: 'Pipeline value score', fmt: 'z' }]);

  // core metrics for the completeness score
  const CORE = ['pe', 'pb', 'ps', 'roe', 'roce', 'div_yield', 'f_score', 'ret_1y', 'debt_to_equity'];

  const MTF_RATE = 12; // assumed MTF interest %/yr
  const LTCG = 0.125; // 12.5% on the gain

  // ---- presets ------------------------------------------------------------
  const PRESETS = {
    mtf: {
      label: 'MTF Buy-and-Hold (1yr)',
      flagship: true,
      note: 'MTF-eligible, quality-tilted, low-beta value — ranked by after-tax, after-interest 1Y return. The flagship.',
      sort: { key: 'aftertax_1y', dir: 'desc' },
      filters: [
        { kind: 'flag', field: 'is_mtf_eligible', on: true },
        { kind: 'num', field: 'beta', op: '<=', a: 1.2 },
        { kind: 'num', field: 'roe', op: '>=', a: 12 },
      ],
      weights: null,
    },
    deep: {
      label: 'Deep Value',
      note: 'Cheapest names by the composite — pure value, no quality gate.',
      sort: { key: 'composite', dir: 'desc' },
      filters: [{ kind: 'num', field: 'pe', op: 'between', a: 0.01, b: 15 }],
      weights: null,
    },
    quality: {
      label: 'Quality Value',
      note: 'Cheap AND high-quality — ROE>15, ROCE>15, Piotroski≥6, low debt.',
      sort: { key: 'composite', dir: 'desc' },
      filters: [
        { kind: 'num', field: 'roe', op: '>=', a: 15 },
        { kind: 'num', field: 'roce', op: '>=', a: 15 },
        { kind: 'num', field: 'f_score', op: '>=', a: 6 },
        { kind: 'num', field: 'debt_to_equity', op: '<=', a: 1 },
      ],
      weights: null,
    },
    lowpepb: {
      label: 'Low PE + PB',
      note: 'Classic Graham screen — cheap on both earnings and book.',
      sort: { key: 'composite', dir: 'desc' },
      filters: [
        { kind: 'num', field: 'pe', op: 'between', a: 0.01, b: 18 },
        { kind: 'num', field: 'pb', op: 'between', a: 0.01, b: 2 },
      ],
      weights: null,
    },
    fcf: {
      label: 'High FCF yield',
      note: 'Cash-generative — weight the composite fully on FCF yield.',
      sort: { key: 'composite', dir: 'desc' },
      filters: [{ kind: 'num', field: 'fcf_yield', op: '>=', a: 0.05 }],
      weights: { ep: 0, bp: 0, sp: 0, ebit_ev: 0.3, fcf_yield: 1, inv_peg: 0, div_yield: 0 },
    },
    nonpsu: {
      label: 'Value non-PSU',
      note: 'Value composite, PSUs excluded (cyclical / policy risk).',
      sort: { key: 'composite', dir: 'desc' },
      filters: [{ kind: 'flag', field: 'is_psu', on: false }],
      weights: null,
    },
  };

  // ---- state --------------------------------------------------------------
  let ROWS = [];
  let SECTOR_MED = {}; // sector -> {metricKey: median}
  const state = {
    filters: [], // {kind:'num',field,op,a,b} | {kind:'flag',field,on} | {kind:'text',field,vals:[]}
    sort: { key: 'composite', dir: 'desc' },
    weights: equalWeights(),
    page: 0,
    preset: null,
    watch: new Set(), // watchlisted symbols
  };
  const PAGE = 100; // rows per page (virtualized window)

  function equalWeights() {
    const w = {};
    for (const f of FACTORS) w[f.key] = 1;
    return w;
  }

  // ---- helpers ------------------------------------------------------------
  const num = (v) => (typeof v === 'number' && isFinite(v) ? v : null);
  function zval(row, key) {
    const z = row.z || {};
    for (const a of Z_ALIASES[key] || [key]) {
      if (typeof z[a] === 'number' && isFinite(z[a])) return z[a];
    }
    return null;
  }
  function composite(row) {
    let sum = 0;
    let wsum = 0;
    for (const f of FACTORS) {
      const w = state.weights[f.key];
      if (!w) continue;
      const z = zval(row, f.key);
      if (z === null) continue;
      sum += w * z;
      wsum += Math.abs(w);
    }
    if (wsum === 0) return num(row.value_score); // fall back to pipeline score
    return sum / wsum;
  }
  function aftertax1y(row) {
    const r = num(row.ret_1y);
    if (r === null) return null;
    const afterInterest = r - MTF_RATE;
    const tax = afterInterest > 0 ? afterInterest * LTCG : 0;
    return afterInterest - tax;
  }
  function completeness(row) {
    let have = 0;
    for (const k of CORE) if (num(row[k]) !== null) have++;
    return have / CORE.length;
  }

  const MEDIAN_KEYS = ['pe', 'pb', 'ps', 'ev_ebit', 'roe', 'roce', 'debt_to_equity', 'div_yield', 'fcf_yield', 'f_score', 'ret_1y', 'composite'];
  function computeSectorMedians() {
    const bySector = {};
    for (const r of ROWS) {
      const s = r.sector || '—';
      (bySector[s] ||= []).push(r);
    }
    SECTOR_MED = {};
    for (const [s, rows] of Object.entries(bySector)) {
      const med = { __n: rows.length };
      for (const k of MEDIAN_KEYS) {
        const vals = rows.map((r) => derived(r, k)).filter((v) => v !== null).sort((a, b) => a - b);
        med[k] = vals.length ? vals[Math.floor(vals.length / 2)] : null;
      }
      SECTOR_MED[s] = med;
    }
  }
  function derived(row, key) {
    if (key === 'composite') return composite(row);
    if (key === 'aftertax_1y') return aftertax1y(row);
    if (key === 'completeness') return completeness(row);
    if (key === 'quality' || key === 'is_mtf_eligible' || key === 'is_psu')
      return row[key] ? 1 : 0;
    if (key === 'symbol' || key === 'sector') return row[key] ?? '';
    return num(row[key]);
  }

  const fmt = {
    z: (v) => (v === null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2)),
    x: (v) => (v === null ? '—' : v.toFixed(1) + 'x'),
    n1: (v) => (v === null ? '—' : v.toFixed(1)),
    n2: (v) => (v === null ? '—' : v.toFixed(2)),
    int: (v) => (v === null ? '—' : Math.round(v).toLocaleString('en-IN')),
    pct1: (v) => (v === null ? '—' : (v * 100).toFixed(1) + '%'),
    pct0: (v) => (v === null ? '—' : Math.round(v * 100) + '%'),
    bool: (v) => (v ? '✓' : '·'),
    text: (v) => v || '—',
  };

  const debounce = (fn, ms) => {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  };

  // ---- filtering + sorting ------------------------------------------------
  function passes(row) {
    for (const f of state.filters) {
      if (f.kind === 'num') {
        const v = derived(row, f.field);
        if (v === null) return false;
        if (f.op === '<' && !(v < f.a)) return false;
        if (f.op === '<=' && !(v <= f.a)) return false;
        if (f.op === '>' && !(v > f.a)) return false;
        if (f.op === '>=' && !(v >= f.a)) return false;
        if (f.op === 'between' && !(v >= f.a && v <= f.b)) return false;
      } else if (f.kind === 'flag') {
        if (Boolean(row[f.field]) !== f.on) return false;
      } else if (f.kind === 'text') {
        if (!f.vals.length) continue;
        const v = String(row[f.field] ?? '');
        if (!f.vals.includes(v)) return false;
      } else if (f.kind === 'index') {
        const idx = row.indices || [];
        if (!idx.includes(f.val)) return false;
      } else if (f.kind === 'tier') {
        if ((row.mcap_tier || '') !== f.val) return false;
      }
    }
    return true;
  }

  function computeView() {
    const out = ROWS.filter(passes);
    const { key, dir } = state.sort;
    const mul = dir === 'desc' ? -1 : 1;
    out.sort((a, b) => {
      const va = derived(a, key);
      const vb = derived(b, key);
      if (va === null && vb === null) return 0;
      if (va === null) return 1; // nulls last
      if (vb === null) return -1;
      if (typeof va === 'string') return mul * va.localeCompare(vb);
      return mul * (va < vb ? -1 : va > vb ? 1 : 0);
    });
    return out;
  }

  // ---- URL encode / decode ------------------------------------------------
  function encodeState() {
    const w = FACTORS.map((f) => state.weights[f.key]).join(',');
    const q = {
      s: state.sort.key + ':' + state.sort.dir,
      w,
      f: state.filters
        .map((f) =>
          f.kind === 'num'
            ? `n~${f.field}~${f.op}~${f.a}~${f.b ?? ''}`
            : f.kind === 'flag'
              ? `b~${f.field}~${f.on ? 1 : 0}`
              : f.kind === 'index'
                ? `i~${f.val}`
                : f.kind === 'tier'
                  ? `t~${f.val}`
                  : `x~${f.field}~${(f.vals || []).join('.')}`,
        )
        .join(';'),
      p: state.preset || '',
    };
    const usp = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v) usp.set(k, v);
    history.replaceState(null, '', '?' + usp.toString());
  }
  function decodeState() {
    const usp = new URLSearchParams(location.search);
    if (usp.get('p') && PRESETS[usp.get('p')]) {
      applyPreset(usp.get('p'), false);
    }
    if (usp.get('s')) {
      const [key, dir] = usp.get('s').split(':');
      if (key) state.sort = { key, dir: dir === 'asc' ? 'asc' : 'desc' };
    }
    if (usp.get('w')) {
      const parts = usp.get('w').split(',').map(Number);
      FACTORS.forEach((f, i) => {
        if (isFinite(parts[i])) state.weights[f.key] = parts[i];
      });
    }
    if (usp.get('f')) {
      state.filters = usp
        .get('f')
        .split(';')
        .map((s) => {
          const p = s.split('~');
          if (p[0] === 'n') return { kind: 'num', field: p[1], op: p[2], a: +p[3], b: p[4] === '' ? undefined : +p[4] };
          if (p[0] === 'b') return { kind: 'flag', field: p[1], on: p[2] === '1' };
          if (p[0] === 'i') return { kind: 'index', val: p[1] };
          if (p[0] === 't') return { kind: 'tier', val: p[1] };
          if (p[0] === 'x') return { kind: 'text', field: p[1], vals: (p[2] || '').split('.').filter(Boolean) };
          return null;
        })
        .filter(Boolean);
    }
  }

  // ---- rendering ----------------------------------------------------------
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };

  let VIEW = [];

  function render() {
    VIEW = computeView();
    $('#result-count').textContent = VIEW.length.toLocaleString('en-IN');
    renderTable();
    encodeState();
  }

  function renderTableHead() {
    const tr = el('tr');
    const star = el('th', 'col-star');
    star.textContent = '★';
    star.title = 'watchlist';
    tr.appendChild(star);
    for (const c of COLUMNS) {
      const th = el('th', 'col-' + c.fmt);
      const btn = el('button', 'sort-btn');
      btn.textContent = c.label;
      if (state.sort.key === c.key) {
        btn.classList.add('active');
        btn.textContent += state.sort.dir === 'desc' ? ' ↓' : ' ↑';
      }
      if (c.help) btn.title = c.help;
      btn.addEventListener('click', () => {
        if (state.sort.key === c.key) {
          state.sort.dir = state.sort.dir === 'desc' ? 'asc' : 'desc';
        } else {
          state.sort = { key: c.key, dir: c.fmt === 'text' ? 'asc' : 'desc' };
        }
        state.page = 0;
        render();
      });
      th.appendChild(btn);
      tr.appendChild(th);
    }
    return tr;
  }

  function renderTable() {
    const table = $('#stable');
    table.innerHTML = '';
    const thead = el('thead');
    thead.appendChild(renderTableHead());
    table.appendChild(thead);

    const tbody = el('tbody');
    const start = state.page * PAGE;
    const slice = VIEW.slice(start, start + PAGE);
    for (let ri = 0; ri < slice.length; ri++) {
      const row = slice[ri];
      const rankInView = start + ri + 1;
      const tr = el('tr');
      const starTd = el('td', 'col-star');
      const sb = el('button', 'star-btn' + (state.watch.has(row.symbol) ? ' on' : ''), state.watch.has(row.symbol) ? '★' : '☆');
      sb.setAttribute('aria-label', 'toggle watchlist');
      sb.addEventListener('click', () => {
        if (state.watch.has(row.symbol)) state.watch.delete(row.symbol);
        else state.watch.add(row.symbol);
        sb.textContent = state.watch.has(row.symbol) ? '★' : '☆';
        sb.classList.toggle('on', state.watch.has(row.symbol));
        renderWatch();
      });
      starTd.appendChild(sb);
      tr.appendChild(starTd);
      for (const c of COLUMNS) {
        const td = el('td', 'col-' + c.fmt);
        const raw = c.key === 'symbol' || c.key === 'sector' ? row[c.key] : derived(row, c.key);
        if (c.key === 'composite') {
          // hero viz: a signal-bar (traffic-light gradient by z magnitude) + value
          td.classList.add('composite-cell');
          const v = raw;
          const wrap = el('div', 'zbar-wrap');
          const bar = el('div', 'zbar');
          // map z (~ -3..+3) to 0..100% width; colour by sign/strength
          const pct = v === null ? 0 : Math.max(4, Math.min(100, ((v + 3) / 6) * 100));
          const col = v === null ? 'var(--dimmer)' : v >= 1 ? 'var(--buy)' : v >= 0 ? 'var(--accum)' : v >= -1 ? 'var(--hold)' : 'var(--caution)';
          bar.style.width = pct + '%';
          bar.style.background = col;
          const lab = el('span', 'zval', fmt.z(v));
          lab.style.color = col;
          wrap.append(bar, lab);
          td.appendChild(wrap);
        } else if (c.fmt === 'bool') {
          td.textContent = fmt.bool(row[c.key]);
          if (row[c.key]) td.classList.add('yes');
        } else if (c.fmt === 'text') {
          if (c.key === 'symbol') {
            td.classList.add('sym');
            const badge = el('span', 'rank-badge' + (rankInView <= 3 ? ' top' : ''), '#' + rankInView);
            td.append(badge, document.createTextNode(fmt.text(raw)));
          } else {
            td.textContent = fmt.text(raw);
          }
        } else {
          td.textContent = fmt[c.fmt](raw);
          if (c.key === 'aftertax_1y' && raw !== null) td.style.color = raw >= 0 ? 'var(--accum)' : 'var(--caution)';
        }
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);

    // pager
    const pages = Math.max(1, Math.ceil(VIEW.length / PAGE));
    $('#pager').innerHTML = '';
    if (pages > 1) {
      const mk = (label, to, dis) => {
        const b = el('button', 'pg', label);
        b.disabled = dis;
        b.addEventListener('click', () => {
          state.page = to;
          renderTable();
          $('#stable').scrollIntoView({ block: 'nearest' });
        });
        return b;
      };
      $('#pager').append(
        mk('‹ prev', Math.max(0, state.page - 1), state.page === 0),
        el('span', 'pg-info', `${start + 1}–${Math.min(start + PAGE, VIEW.length)} of ${VIEW.length.toLocaleString('en-IN')}`),
        mk('next ›', Math.min(pages - 1, state.page + 1), state.page >= pages - 1),
      );
    }
  }

  // ---- filter builder UI --------------------------------------------------
  function renderFilters() {
    const box = $('#filter-list');
    box.innerHTML = '';
    state.filters.forEach((f, i) => {
      const chip = el('div', 'chip');
      let txt = '';
      if (f.kind === 'num') txt = `${labelFor(f.field)} ${f.op} ${f.a}${f.op === 'between' ? '–' + f.b : ''}`;
      else if (f.kind === 'flag') txt = `${labelFor(f.field)} = ${f.on ? 'yes' : 'no'}`;
      else if (f.kind === 'index') txt = `in ${f.val}`;
      else if (f.kind === 'tier') txt = `${f.val}-cap`;
      else if (f.kind === 'text') txt = `${labelFor(f.field)} ∈ ${f.vals.join(', ')}`;
      chip.appendChild(el('span', null, txt));
      const x = el('button', 'chip-x', '×');
      x.setAttribute('aria-label', 'remove filter');
      x.addEventListener('click', () => {
        state.filters.splice(i, 1);
        state.preset = null;
        state.page = 0;
        renderFilters();
        render();
      });
      chip.appendChild(x);
      box.appendChild(chip);
    });
    if (!state.filters.length) box.appendChild(el('span', 'chip-empty', 'no filters — showing all'));
  }
  function labelFor(field) {
    const c = COLUMNS.concat(FILTER_METRICS).find((x) => x.key === field);
    return c ? c.label : field;
  }

  function addNumFilter() {
    const field = $('#f-metric').value;
    const op = $('#f-op').value;
    const a = parseFloat($('#f-a').value);
    const b = parseFloat($('#f-b').value);
    if (!isFinite(a)) return;
    state.filters.push({ kind: 'num', field, op, a, b: op === 'between' && isFinite(b) ? b : undefined });
    state.preset = null;
    state.page = 0;
    renderFilters();
    render();
  }

  // ---- weight sliders -----------------------------------------------------
  function renderWeights() {
    const box = $('#weights');
    box.innerHTML = '';
    for (const f of FACTORS) {
      const row = el('label', 'wrow');
      row.appendChild(el('span', 'wlab', f.label));
      const sl = el('input');
      sl.type = 'range';
      sl.min = '0';
      sl.max = '2';
      sl.step = '0.1';
      sl.value = String(state.weights[f.key]);
      const out = el('span', 'wval', Number(state.weights[f.key]).toFixed(1));
      sl.addEventListener('input', () => {
        state.weights[f.key] = parseFloat(sl.value);
        out.textContent = parseFloat(sl.value).toFixed(1);
        debouncedRender();
      });
      row.append(sl, out);
      box.appendChild(row);
    }
  }
  const debouncedRender = debounce(render, 120);

  // ---- presets ------------------------------------------------------------
  function applyPreset(id, doRender = true) {
    const p = PRESETS[id];
    if (!p) return;
    state.preset = id;
    state.filters = JSON.parse(JSON.stringify(p.filters));
    state.sort = { ...p.sort };
    state.weights = p.weights ? { ...equalWeights(), ...p.weights } : equalWeights();
    state.page = 0;
    $('#preset-note').textContent = p.note;
    if (doRender) {
      renderFilters();
      renderWeights();
      render();
      syncPresetButtons();
    }
  }
  function syncPresetButtons() {
    document.querySelectorAll('.preset-btn').forEach((b) => {
      b.classList.toggle('active', b.dataset.preset === state.preset);
    });
  }

  // ---- watchlist + side-by-side compare ----------------------------------
  const CMP_ROWS = [
    { key: 'composite', label: 'Composite', fmt: 'z', hi: 'high' },
    { key: 'pe', label: 'PE', fmt: 'x', hi: 'low' },
    { key: 'pb', label: 'PB', fmt: 'x', hi: 'low' },
    { key: 'ps', label: 'PS', fmt: 'x', hi: 'low' },
    { key: 'ev_ebit', label: 'EV/EBIT', fmt: 'x', hi: 'low' },
    { key: 'peg', label: 'PEG', fmt: 'n2', hi: 'low' },
    { key: 'fcf_yield', label: 'FCF yld', fmt: 'pct1', hi: 'high' },
    { key: 'div_yield', label: 'Div %', fmt: 'n2', hi: 'high' },
    { key: 'roe', label: 'ROE %', fmt: 'n1', hi: 'high' },
    { key: 'roce', label: 'ROCE %', fmt: 'n1', hi: 'high' },
    { key: 'debt_to_equity', label: 'D/E', fmt: 'n2', hi: 'low' },
    { key: 'f_score', label: 'Piotroski', fmt: 'int', hi: 'high' },
    { key: 'ret_1y', label: '1Y ret %', fmt: 'n1', hi: 'high' },
    { key: 'aftertax_1y', label: 'After-tax 1Y %', fmt: 'n1', hi: 'high' },
    { key: 'beta', label: 'Beta', fmt: 'n2', hi: 'low' },
  ];
  function renderWatch() {
    const box = $('#compare');
    const syms = [...state.watch];
    $('#watch-count').textContent = String(syms.length);
    if (!syms.length) {
      box.innerHTML = '<p class="cmp-empty">Star stocks in the table to compare them side-by-side (up to 8) — the "pick your 5" workflow.</p>';
      return;
    }
    const picked = syms.slice(0, 8).map((s) => ROWS.find((r) => r.symbol === s)).filter(Boolean);
    const table = el('table', 'cmp-table');
    const thead = el('thead');
    const htr = el('tr');
    htr.appendChild(el('th', 'cmp-metric', 'Metric'));
    for (const p of picked) {
      const th = el('th');
      th.appendChild(el('div', 'cmp-sym', p.symbol));
      th.appendChild(el('div', 'cmp-sec', p.sector || ''));
      htr.appendChild(th);
    }
    htr.appendChild(el('th', 'cmp-sec-med', 'sector median'));
    thead.appendChild(htr);
    table.appendChild(thead);
    const tbody = el('tbody');
    for (const m of CMP_ROWS) {
      const tr = el('tr');
      tr.appendChild(el('td', 'cmp-metric', m.label));
      const vals = picked.map((p) => derived(p, m.key));
      const valid = vals.filter((v) => v !== null);
      const best = m.hi === 'high' ? Math.max(...valid) : Math.min(...valid);
      picked.forEach((p, i) => {
        const td = el('td', null, fmt[m.fmt](vals[i]));
        if (valid.length > 1 && vals[i] === best) td.classList.add('best');
        tr.appendChild(td);
      });
      // sector-median column: median of the FIRST picked stock's sector
      const secMed = SECTOR_MED[picked[0].sector]?.[m.key] ?? null;
      tr.appendChild(el('td', 'cmp-sec-med', fmt[m.fmt](secMed)));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    box.innerHTML = '';
    box.appendChild(table);
    box.appendChild(el('p', 'cmp-note', 'Highlighted = best of the picked set on that metric. Last column = median for ' + picked[0].sector + ' (peer context). Not investment advice.'));
  }

  // ---- sector view --------------------------------------------------------
  function renderSectorView() {
    const box = $('#sector-view');
    const secs = Object.entries(SECTOR_MED)
      .filter(([, m]) => m.__n >= 3)
      .sort((a, b) => (b[1].composite ?? -99) - (a[1].composite ?? -99));
    const table = el('table', 'sector-table');
    const head = ['Sector', 'n', 'Median composite', 'Med PE', 'Med PB', 'Med ROE', 'Med 1Y', 'Cheapest-quality'];
    const thead = el('thead');
    const htr = el('tr');
    head.forEach((h) => htr.appendChild(el('th', null, h)));
    thead.appendChild(htr);
    table.appendChild(thead);
    const tbody = el('tbody');
    for (const [s, m] of secs) {
      const tr = el('tr');
      // cheapest-quality: highest composite among quality names in the sector
      const cq = ROWS.filter((r) => (r.sector || '—') === s && r.quality)
        .sort((a, b) => (derived(b, 'composite') ?? -99) - (derived(a, 'composite') ?? -99))[0];
      const cells = [
        s, String(m.__n), fmt.z(m.composite), fmt.x(m.pe), fmt.x(m.pb), fmt.n1(m.roe), fmt.n1(m.ret_1y),
        cq ? cq.symbol : '—',
      ];
      cells.forEach((c, i) => {
        const td = el('td', i === 0 ? 'sec-name' : null, c);
        if (i === 2 && m.composite !== null) td.style.color = m.composite >= 0 ? 'var(--buy)' : 'var(--caution)';
        if (i === 7 && cq) td.classList.add('sym');
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    box.innerHTML = '';
    box.appendChild(table);
  }

  // ---- CSV export ---------------------------------------------------------
  function exportCsv() {
    const cols = COLUMNS.map((c) => c.key);
    const head = COLUMNS.map((c) => c.label).join(',');
    const lines = [head];
    for (const row of VIEW) {
      const cells = cols.map((k) => {
        const v = k === 'symbol' || k === 'sector' ? row[k] : derived(row, k);
        if (v === null || v === undefined) return '';
        return typeof v === 'string' ? `"${v.replace(/"/g, '""')}"` : v;
      });
      lines.push(cells.join(','));
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'nifty-screen.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ---- AI commentary (from committed JSON, best-effort) -------------------
  function renderAI(data) {
    const box = $('#ai-analysis');
    const ai = data.ai || data.commentary || null;
    if (!ai) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    const body = $('#ai-body');
    body.innerHTML = '';
    if (typeof ai === 'string') {
      body.appendChild(el('p', null, ai));
    } else if (ai.market || ai.summary) {
      body.appendChild(el('p', null, ai.market || ai.summary));
    }
    // per-stock takes: { picks: [{symbol, take, risk}] }
    const picks = ai.picks || ai.stocks || [];
    if (Array.isArray(picks) && picks.length) {
      const ul = el('ul', 'ai-picks');
      for (const p of picks.slice(0, 12)) {
        const li = el('li');
        li.appendChild(el('b', null, p.symbol || ''));
        li.appendChild(document.createTextNode(' — ' + (p.take || p.note || '')));
        if (p.risk) {
          const r = el('span', 'ai-risk', ' Risk: ' + p.risk);
          li.appendChild(r);
        }
        ul.appendChild(li);
      }
      body.appendChild(ul);
    }
  }


  async function boot() {
    const status = $('#screener-status');
    try {
      const res = await fetch('screener-data.json');
      const data = await res.json();
      ROWS = (data.stocks || []).filter((r) => r && r.symbol);
      computeSectorMedians();
      renderAI(data);
      if (data.__demo) {
        $('#demo-banner').hidden = false;
      }
      if (data.ts) $('#data-ts').textContent = new Date(data.ts).toUTCString();
      status.hidden = true;
    } catch (e) {
      status.textContent = 'Could not load screener data. Try again after the daily run.';
      return;
    }

    // filter-metric dropdown
    const sel = $('#f-metric');
    for (const c of FILTER_METRICS) {
      const o = el('option', null, c.label);
      o.value = c.key;
      sel.appendChild(o);
    }
    $('#f-op').addEventListener('change', () => {
      $('#f-b').hidden = $('#f-op').value !== 'between';
    });
    $('#f-b').hidden = true;
    $('#f-add').addEventListener('click', addNumFilter);

    // quick flag + membership toggles
    document.querySelectorAll('[data-quick]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const kind = btn.dataset.kind;
        const val = btn.dataset.val;
        const field = btn.dataset.field;
        let f;
        if (kind === 'flag') f = { kind: 'flag', field, on: btn.dataset.on === '1' };
        else if (kind === 'index') f = { kind: 'index', val };
        else if (kind === 'tier') f = { kind: 'tier', val };
        // toggle: remove if identical exists
        const key = JSON.stringify(f);
        const idx = state.filters.findIndex((x) => JSON.stringify(x) === key);
        if (idx >= 0) state.filters.splice(idx, 1);
        else state.filters.push(f);
        state.preset = null;
        state.page = 0;
        btn.classList.toggle('active', idx < 0);
        renderFilters();
        render();
      });
    });

    // presets
    document.querySelectorAll('.preset-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        applyPreset(btn.dataset.preset);
      });
    });

    // reset + share
    $('#reset').addEventListener('click', () => {
      state.filters = [];
      state.sort = { key: 'composite', dir: 'desc' };
      state.weights = equalWeights();
      state.preset = null;
      state.page = 0;
      $('#preset-note').textContent = '';
      document.querySelectorAll('.preset-btn,[data-quick]').forEach((b) => b.classList.remove('active'));
      renderFilters();
      renderWeights();
      render();
    });
    $('#share').addEventListener('click', async () => {
      encodeState();
      try {
        await navigator.clipboard.writeText(location.href);
        $('#share').textContent = 'copied!';
        setTimeout(() => ($('#share').textContent = 'share query'), 1400);
      } catch {
        /* clipboard blocked — URL already in address bar */
      }
    });
    $('#eq-weights').addEventListener('click', () => {
      state.weights = equalWeights();
      renderWeights();
      render();
    });
    $('#csv').addEventListener('click', exportCsv);
    $('#clear-watch').addEventListener('click', () => {
      state.watch.clear();
      renderWatch();
      renderTable();
    });
    const secBtn = $('#toggle-sector');
    secBtn.addEventListener('click', () => {
      const sv = $('#sector-panel');
      sv.hidden = !sv.hidden;
      secBtn.classList.toggle('active', !sv.hidden);
      if (!sv.hidden) renderSectorView();
    });

    decodeState();
    renderFilters();
    renderWeights();
    renderWatch();
    syncPresetButtons();
    if (state.preset && PRESETS[state.preset]) $('#preset-note').textContent = PRESETS[state.preset].note;
    render();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
