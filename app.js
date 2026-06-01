'use strict';

const NAVER_URL = t => `https://finance.naver.com/item/main.naver?code=${t}`;

let currentSort = { key: 'rank', dir: 'asc' };
let stockData = [];

async function loadData() {
  try {
    const res = await fetch('./data/latest.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (!data.meta.generated_at) {
      showEmpty();
      return;
    }

    stockData = data.stocks || [];
    renderAll(data);
  } catch (e) {
    showError(e.message);
  }
}

function renderAll(data) {
  renderMeta(data.meta);
  renderCards(data.meta);
  renderWarnings(data.meta.warnings);
  renderTable(data.stocks);
  renderChangelog(data.changelog);
}

function renderMeta(meta) {
  const bar = document.getElementById('meta-bar');
  const d = meta.generated_at ? new Date(meta.generated_at) : null;
  const dateStr = d ? d.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-';
  bar.innerHTML = `
    <span>기준일: <strong>${meta.data_as_of || '-'}</strong></span>
    <span>회계연도: <strong>${meta.fiscal_year || '-'}년</strong></span>
    <span>생성: <strong>${dateStr}</strong></span>
    <span>다음 리밸런싱: <strong>${meta.next_rebalance || '-'}</strong></span>
  `;
}

function renderCards(meta) {
  const container = document.getElementById('summary-cards');
  const items = [
    { value: meta.universe_size, label: '유니버스 (시총 상위)' },
    { value: meta.survived_filters, label: '필터 통과' },
    { value: meta.quality_passed, label: '퀄리티 통과' },
    { value: meta.selected_count, label: '최종 선정 종목' },
  ];
  container.innerHTML = items.map(i => `
    <div class="stat-card">
      <div class="value">${i.value ?? '-'}</div>
      <div class="label">${i.label}</div>
    </div>
  `).join('');
}

function renderWarnings(warnings) {
  const el = document.getElementById('warning-banner');
  if (warnings && warnings.length > 0) {
    el.textContent = '⚠ ' + warnings.join(' | ');
    el.style.display = 'block';
  }
}

// --- Table ---

const COLUMNS = [
  { key: 'rank',                     label: '순위',      numeric: true,  align: 'center' },
  { key: 'name',                     label: '종목명',    numeric: false, align: 'left'   },
  { key: 'sector',                   label: '업종',      numeric: false, align: 'left'   },
  { key: 'market_cap_bn_krw',        label: '시가총액\n(억원)', numeric: true,  align: 'right'  },
  { key: 'composite_score',          label: '종합점수',  numeric: true,  align: 'right'  },
  { key: 'pbr',                      label: 'PBR',       numeric: true,  align: 'right'  },
  { key: 'per',                      label: 'PER',       numeric: true,  align: 'right'  },
  { key: 'psr',                      label: 'PSR',       numeric: true,  align: 'right'  },
  { key: 'pcr',                      label: 'PCR',       numeric: true,  align: 'right'  },
  { key: 'roe_pct',                  label: 'ROE %',     numeric: true,  align: 'right'  },
  { key: 'debt_ratio_pct',           label: '부채비율 %', numeric: true, align: 'right'  },
  { key: 'current_ratio_pct',        label: '유동비율 %', numeric: true, align: 'right'  },
  { key: 'piotroski_fscore',         label: 'F-Score',   numeric: true,  align: 'right'  },
  { key: 'is_new',                   label: '신규',      numeric: false, align: 'center' },
];

function renderTable(stocks) {
  const thead = document.querySelector('#results thead tr');
  const tbody = document.querySelector('#results tbody');

  thead.innerHTML = COLUMNS.map(col => `
    <th data-key="${col.key}" class="${currentSort.key === col.key ? 'sort-' + currentSort.dir : ''}">${col.label}</th>
  `).join('');

  thead.querySelectorAll('th').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      if (currentSort.key === key) {
        currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
      } else {
        currentSort = { key, dir: 'asc' };
      }
      renderTable(stockData);
    });
  });

  const sorted = [...stocks].sort((a, b) => {
    let av = a[currentSort.key], bv = b[currentSort.key];
    if (av === null || av === undefined) av = currentSort.dir === 'asc' ? Infinity : -Infinity;
    if (bv === null || bv === undefined) bv = currentSort.dir === 'asc' ? Infinity : -Infinity;
    if (typeof av === 'boolean') av = av ? 1 : 0;
    if (typeof bv === 'boolean') bv = bv ? 1 : 0;
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return currentSort.dir === 'asc' ? cmp : -cmp;
  });

  tbody.innerHTML = sorted.map(s => `
    <tr>
      <td>${s.rank}</td>
      <td><a href="${NAVER_URL(s.ticker)}" target="_blank" rel="noopener">${s.name}</a><br><small style="color:var(--text-dim)">${s.ticker}</small></td>
      <td>${s.sector || '-'}</td>
      <td>${fmt(s.market_cap_bn_krw, 0)}</td>
      <td>${renderScoreBar(s.composite_score)}</td>
      <td class="${s.pbr && s.pbr < 1 ? 'val-good' : ''}">${fmt(s.pbr, 2) ?? nullVal()}</td>
      <td>${fmt(s.per, 1) ?? nullVal()}</td>
      <td class="${s.psr && s.psr < 0.5 ? 'val-good' : ''}">${fmt(s.psr, 2) ?? nullVal()}</td>
      <td>${fmt(s.pcr, 1) ?? nullVal()}</td>
      <td class="${s.roe_pct && s.roe_pct > 15 ? 'val-good' : ''}">${fmt(s.roe_pct, 1) ?? nullVal()}</td>
      <td class="${s.debt_ratio_pct && s.debt_ratio_pct > 100 ? 'val-warn' : ''}">${fmt(s.debt_ratio_pct, 1) ?? nullVal()}</td>
      <td>${fmt(s.current_ratio_pct, 1) ?? nullVal()}</td>
      <td>${renderFscore(s.piotroski_fscore)}</td>
      <td>${s.is_new ? '<span class="badge badge-new">NEW</span>' : (s.prev_rank ? `<small style="color:var(--text-dim)">${s.prev_rank}위</small>` : '')}</td>
    </tr>
  `).join('');
}

function renderScoreBar(score) {
  if (score == null) return nullVal();
  // score is 0-100, lower is better → fill from right
  const pct = Math.max(0, Math.min(100, 100 - score));
  const hue = Math.round(pct * 1.2); // 0=red, 120=green
  return `<div class="score-bar-wrap">
    <span>${score.toFixed(1)}</span>
    <div class="score-bar"><div class="score-bar-fill" style="width:${pct}%;background:hsl(${hue},70%,45%)"></div></div>
  </div>`;
}

function renderFscore(f) {
  if (f == null) return nullVal();
  const cls = f >= 8 ? 'badge-green' : f >= 6 ? 'badge-blue' : 'badge-yellow';
  return `<span class="badge badge-fscore ${cls}">${f}/9</span>`;
}

function fmt(v, decimals) {
  if (v == null || v !== v) return null; // null or NaN
  return Number(v).toLocaleString('ko-KR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
function nullVal() { return '<span class="val-null">-</span>'; }

// --- Changelog ---
function renderChangelog(changelog) {
  if (!changelog) return;
  const section = document.getElementById('changelog');
  const enterEl = document.getElementById('cl-entered');
  const exitEl = document.getElementById('cl-exited');

  const entered = changelog.entered || [];
  const exited = changelog.exited || [];

  enterEl.innerHTML = `<span class="cl-label">신규 진입</span>` + (entered.length
    ? entered.map(t => `<span class="cl-ticker entered">${t}</span>`).join('')
    : '<span class="cl-label">없음</span>');

  exitEl.innerHTML = `<span class="cl-label">이탈</span>` + (exited.length
    ? exited.map(t => `<span class="cl-ticker exited">${t}</span>`).join('')
    : '<span class="cl-label">없음</span>');

  if (entered.length === 0 && exited.length === 0) {
    section.style.display = 'none';
  }
}

// --- Error / Empty states ---
function showError(msg) {
  document.getElementById('main-content').style.display = 'none';
  const el = document.getElementById('error-state');
  el.style.display = 'block';
  el.querySelector('p').textContent = `오류: ${msg}`;
}

function showEmpty() {
  document.getElementById('main-content').style.display = 'none';
  document.getElementById('empty-state').style.display = 'block';
}

loadData();
