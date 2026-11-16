// ---------- 탭 ----------
(function () {
  const ids = ['now', 'indicators', 'performance', 'validation', 'guide'];
  function open(id, setLink) {
    if (!ids.includes(id)) id = 'now';
    document.querySelectorAll('.qd-tab').forEach((b) => b.setAttribute('aria-selected', b.dataset.tab === id ? 'true' : 'false'));
    ids.forEach((s) => document.querySelectorAll('#' + s).forEach((el) => { el.hidden = s !== id; }));
    if (setLink) dash.setLink(id);
  }
  document.querySelectorAll('.qd-tab').forEach((b) => b.addEventListener('click', () => open(b.dataset.tab, true)));
  const h = (location.hash || '').replace('#', '');
  if (ids.includes(h)) open(h, false);
})();
// ---------- 계산 ----------
dash.calc('sens_stats', {
  title: '민감도 샤프 범위',
  description: '27개 파라미터 조합의 샤프지수 최소·최대',
  inputs: ['sensitivity'],
  fn: (sensitivity) => {
    const v = sensitivity.map((r) => +r.sharpe).filter((x) => !isNaN(x));
    return v.length ? [{ min: Math.min(...v), max: Math.max(...v) }] : [];
  },
});
// ---------- 공통 차트 도구 ----------
window.F = d3.formatLocale({ decimal: '.', thousands: ',', grouping: [3], currency: ['', ''], minus: '-' }).format;
window.QD = (function () {
  const parse = d3.utcParse('%Y-%m-%d');
  const fDate = d3.utcFormat('%Y-%m-%d');
  const C = () => dash.colors || ['currentColor'];
  function ok(id) { const r = dash.data(id); return r.status === 'ok' && Array.isArray(r.data) && r.data.length ? r.data : null; }
  function failed(el, id) {
    const s = dash.data(id).status;
    el.replaceChildren();
    if (s === 'error') { const p = document.createElement('p'); p.className = 'qd-muted'; p.textContent = '불러오지 못했습니다'; el.appendChild(p); }
  }
  function measureLeft(svg, scale, fmt, ticks) {
    const g = svg.append('g').attr('class', 'qd-measure').call(d3.axisLeft(scale).ticks(ticks).tickFormat(fmt));
    let w = 0; g.selectAll('text').each(function () { w = Math.max(w, this.getComputedTextLength()); });
    g.remove(); return Math.ceil(w) + 12;
  }
  function tipBox(el) { const t = document.createElement('div'); t.className = 'qd-tip'; t.style.display = 'none'; el.appendChild(t); return t; }
  function showTip(el, tip, x, y, lines) {
    tip.replaceChildren();
    lines.forEach(([k, v, color], i) => {
      const d = document.createElement('div');
      if (i === 0 && v === null) { d.textContent = k; d.style.fontWeight = '600'; }
      else {
        if (color) { const s = document.createElement('span'); s.textContent = '● '; s.style.color = color; d.appendChild(s); }
        const a = document.createElement('span'); a.className = 'k'; a.textContent = k + ' '; d.appendChild(a);
        const b = document.createElement('span'); b.textContent = v; d.appendChild(b);
      }
      tip.appendChild(d);
    });
    tip.style.display = 'block';
    const W = el.clientWidth, tw = tip.offsetWidth;
    let left = x + 12; if (left + tw > W) left = Math.max(0, x - tw - 12);
    tip.style.left = left + 'px'; tip.style.top = Math.max(0, y - 10) + 'px';
  }

  // 시계열 선 차트
  function lines(el, rows, o) {
    el.replaceChildren();
    const data = rows.map((r) => Object.assign({ _d: parse(r[o.x]) }, r)).filter((r) => r._d);
    const W = Math.max(260, el.clientWidth), H = o.height || 260;
    const m = { t: 10, r: 14, b: 26, l: 40 };
    const vals = [];
    o.series.forEach((s) => data.forEach((r) => { const v = +r[s.key]; if (!isNaN(v)) vals.push(v); }));
    let ext = d3.extent(vals.concat(o.include || []));
    const y = (o.log ? d3.scaleLog() : d3.scaleLinear()).domain(ext).range([H - m.b, m.t]);
    if (!o.log) y.nice();
    const fmt = o.yFmt || F(',.1f');
    const svg = d3.select(el).append('svg').attr('width', '100%').attr('height', H).attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', el.getAttribute('aria-label') || '');
    m.l = measureLeft(svg, y, fmt, o.log ? 5 : 5);
    const x = d3.scaleUtc().domain(d3.extent(data, (d) => d._d)).range([m.l, W - m.r]);
    svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5, o.log ? '~g' : undefined).tickFormat(fmt).tickSize(-(W - m.l - m.r))).call((g) => g.select('.domain').remove());
    svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(Math.max(2, Math.floor((W - m.l) / 80))).tickFormat(d3.utcFormat('%Y')));
    (o.refs || []).forEach((v) => {
      if (v < y.domain()[0] || v > y.domain()[1]) return;
      svg.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(v)).attr('y2', y(v)).style('stroke', 'var(--cds-chart-reference)').style('stroke-dasharray', '4 3');
    });
    o.series.forEach((s, i) => {
      const color = s.color || C()[i % C().length];
      const def = (d) => !isNaN(+d[s.key]) && d[s.key] !== null && d[s.key] !== '';
      if (s.area) {
        const base = o.log ? y.domain()[0] : Math.max(y.domain()[0], Math.min(0, y.domain()[1]));
        svg.append('path').datum(data).attr('d', d3.area().defined(def).x((d) => x(d._d)).y0(y(base)).y1((d) => y(+d[s.key]))).style('fill', color).style('opacity', 0.22);
      }
      svg.append('path').datum(data).attr('d', d3.line().defined(def).x((d) => x(d._d)).y((d) => y(+d[s.key]))).style('fill', 'none').style('stroke', color).style('stroke-width', s.width || 1.6);
    });
    const vline = svg.append('line').attr('y1', m.t).attr('y2', H - m.b).style('stroke', 'var(--cds-chart-reference)').style('display', 'none');
    const tip = tipBox(el);
    const bis = d3.bisector((d) => d._d).center;
    svg.append('rect').attr('x', m.l).attr('y', m.t).attr('width', W - m.l - m.r).attr('height', H - m.t - m.b).style('fill', 'transparent')
      .on('pointermove', (ev) => {
        const [px, py] = d3.pointer(ev, svg.node());
        const d = data[bis(data, x.invert(px))]; if (!d) return;
        const sx = x(d._d); vline.attr('x1', sx).attr('x2', sx).style('display', null);
        const scale = el.clientWidth / W;
        showTip(el, tip, sx * scale, py * scale, [[fDate(d._d), null]].concat(o.series.map((s, i) => [s.label, (o.tipFmt || fmt)(+d[s.key]), s.color || C()[i % C().length]])));
      })
      .on('pointerleave', () => { tip.style.display = 'none'; vline.style('display', 'none'); });
  }

  // 세로 막대 (그룹)
  function bars(el, rows, o) {
    el.replaceChildren();
    const W = Math.max(260, el.clientWidth), H = o.height || 260;
    const m = { t: 18, r: 10, b: 26, l: 40 };
    const vals = [];
    rows.forEach((r) => o.series.forEach((s) => vals.push(+r[s.key])));
    const y = d3.scaleLinear().domain([Math.min(0, d3.min(vals)), Math.max(0, d3.max(vals))]).nice().range([H - m.b, m.t]);
    const fmt = o.yFmt || F(',.1f');
    const svg = d3.select(el).append('svg').attr('width', '100%').attr('height', H).attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', el.getAttribute('aria-label') || '');
    m.l = measureLeft(svg, y, fmt, 5);
    const x0 = d3.scaleBand().domain(rows.map((r) => r[o.x])).range([m.l, W - m.r]).padding(0.2);
    const x1 = d3.scaleBand().domain(o.series.map((s) => s.key)).range([0, x0.bandwidth()]).padding(0.08);
    svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(fmt).tickSize(-(W - m.l - m.r))).call((g) => g.select('.domain').remove());
    const step = Math.ceil(rows.length / Math.max(1, Math.floor((W - m.l) / 46)));
    svg.append('g').attr('transform', `translate(0,${y(0)})`).call(d3.axisBottom(x0).tickSizeOuter(0).tickFormat((d, i) => (i % step === 0 ? (o.xFmt ? o.xFmt(d) : d) : '')))
      .call((g) => g.selectAll('text').attr('transform', `translate(0,${H - m.b - y(0)})`));
    const tip = tipBox(el);
    rows.forEach((r) => {
      o.series.forEach((s, i) => {
        const v = +r[s.key], color = s.color || C()[i % C().length];
        const bx = x0(r[o.x]) + x1(s.key), bw = x1.bandwidth();
        svg.append('rect').attr('x', bx).attr('width', bw).attr('y', Math.min(y(v), y(0))).attr('height', Math.abs(y(v) - y(0))).style('fill', color)
          .on('pointermove', (ev) => {
            const [px, py] = d3.pointer(ev, svg.node()); const sc = el.clientWidth / W;
            showTip(el, tip, px * sc, py * sc, [[String(o.xFmt ? o.xFmt(r[o.x]) : r[o.x]), null]].concat(o.series.map((ss, j) => [ss.label, fmt(+r[ss.key]), ss.color || C()[j % C().length]])));
          })
          .on('pointerleave', () => { tip.style.display = 'none'; });
        if (o.labels) {
          svg.append('text').attr('class', 'qd-lbl').attr('x', bx + bw / 2).attr('y', v >= 0 ? y(v) - 4 : y(v) + 12).attr('text-anchor', 'middle').text(fmt(v));
        }
      });
    });
  }

  // 가로 발산 막대 (기여도)
  function hbars(el, rows, o) {
    el.replaceChildren();
    const W = Math.max(260, el.clientWidth), rowH = 34, H = rows.length * rowH + 30;
    const svg = d3.select(el).append('svg').attr('width', '100%').attr('height', H).attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', el.getAttribute('aria-label') || '');
    let lw = 0;
    const tmp = svg.append('g');
    rows.forEach((r) => { const t = tmp.append('text').attr('class', 'qd-lbl').text(r[o.label]); lw = Math.max(lw, t.node().getComputedTextLength()); });
    tmp.remove();
    const m = { t: 6, r: 44, b: 24, l: Math.ceil(lw) + 14 };
    const vals = rows.map((r) => +r[o.value]);
    const lim = Math.max(1, d3.max(vals.map(Math.abs)));
    const x = d3.scaleLinear().domain([-lim, lim]).nice().range([m.l + 30, W - m.r]);
    const y = d3.scaleBand().domain(rows.map((r) => r[o.key])).range([m.t, H - m.b]).padding(0.28);
    svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(5).tickFormat(F('+.1~f')).tickSize(-(H - m.t - m.b))).call((g) => g.select('.domain').remove());
    svg.append('line').attr('x1', x(0)).attr('x2', x(0)).attr('y1', m.t).attr('y2', H - m.b).style('stroke', 'var(--cds-chart-axis)');
    const fmt = F('+.2f');
    rows.forEach((r) => {
      const v = +r[o.value], yy = y(r[o.key]), bh = y.bandwidth();
      svg.append('text').attr('class', 'qd-lbl').attr('x', 0).attr('y', yy + bh / 2 + 4).text(r[o.label]);
      svg.append('rect').attr('x', Math.min(x(v), x(0))).attr('width', Math.abs(x(v) - x(0))).attr('y', yy).attr('height', bh)
        .style('fill', v >= 0 ? 'var(--color-ok)' : 'var(--color-bad)').style('opacity', 0.85);
      svg.append('text').attr('class', 'qd-lbl').attr('x', v >= 0 ? x(v) + 4 : x(v) - 4).attr('y', yy + bh / 2 + 4).attr('text-anchor', v >= 0 ? 'start' : 'end').text(fmt(v));
    });
  }

  function legend(el, items) {
    el.replaceChildren();
    items.forEach((it, i) => {
      const s = document.createElement('span'); const sw = document.createElement('i');
      sw.style.background = it.color || C()[i % C().length]; s.appendChild(sw); s.appendChild(document.createTextNode(it.label)); el.appendChild(s);
    });
  }
  return { ok, failed, lines, bars, hbars, legend, C };
})();
// ---------- 현재 신호 ----------
(function () {
  const f2 = F('.2f'), f1 = F('.1f');
  function cell(name, field, fmt, cls) {
    dash.draw(name, (el) => {
      const r = QD.ok('current_signal');
      if (!r) { el.textContent = '—'; return; }
      const v = r[0][field];
      el.textContent = fmt ? fmt(v) : v;
      if (cls) el.className = cls(v, el.className.replace(/\bqd-(good|bad|warn)\b/g, '').trim());
    });
  }
  cell('asof', 'as_of');
  cell('score', 'score', (v) => F('+.2f')(+v), (v, c) => (c + ' ' + (+v >= 0 ? 'qd-good' : 'qd-bad')).trim());
  cell('pctile', 'score_pctile', (v) => f1(+v));
  cell('target', 'target_weight', (v) => f1(+v));
  cell('held', 'held_weight', (v) => f1(+v));
  cell('quad', 'quadrant');
  cell('crisis', 'crisis', (v) => (String(v).toLowerCase() === 'true' ? '켜짐 (비중 30% 이하)' : '꺼짐'), (v, c) => (c + ' ' + (String(v).toLowerCase() === 'true' ? 'qd-warn' : '')).trim());
  cell('peak', 'kodex_from_peak', (v) => F('+.1f')(+v), (v, c) => (c + ' ' + (+v < -20 ? 'qd-bad' : '')).trim());
  dash.draw('stance', (el) => {
    const r = QD.ok('current_signal');
    if (!r) { el.textContent = '—'; return; }
    const t = +r[0].target_weight;
    el.textContent = t < 35 ? '방어적' : t <= 65 ? '중립' : '공격적';
  });
  dash.draw('contrib', (el) => {
    const r = QD.ok('indicators'); if (!r) return QD.failed(el, 'indicators');
    QD.hbars(el, r, { key: 'key', label: 'name', value: 'contribution' });
  });
  dash.draw('sw1', (el) => { el.style.background = QD.C()[0]; });
  dash.draw('sw2', (el) => { el.style.background = QD.C()[1 % QD.C().length]; });
  dash.draw('scoreline', (el) => {
    const r = QD.ok('weekly_series'); if (!r) return QD.failed(el, 'weekly_series');
    QD.lines(el, r, { x: 'date', series: [{ key: 'score', label: '레짐 점수' }], yFmt: F('+.1~f'), tipFmt: F('+.2f'), refs: [0], height: 240 });
  });
  dash.draw('weightarea', (el) => {
    const r = QD.ok('weekly_series'); if (!r) return QD.failed(el, 'weekly_series');
    QD.lines(el, r, { x: 'date', series: [{ key: 'equity_weight', label: '주식 비중 %', area: true, color: QD.C()[1 % QD.C().length] }], include: [0, 100], yFmt: F('.0f'), tipFmt: F('.1f'), height: 170 });
  });
})();
// ---------- 지표 ----------
(function () {
  const f2 = F('.2f');
  const sg = F('+.2f');
  ['rate', 'krw', 'semi', 'copper', 'credit'].forEach((k) => {
    [['lv', 'level', f2], ['ch', 'change', sg], ['ct', 'contribution', sg]].forEach(([p, field, fmt]) => {
      dash.draw(p + '-' + k, (el) => {
        const r = QD.ok('indicators');
        const row = r && r.find((x) => x.key === k);
        if (!row) { el.textContent = '—'; return; }
        el.textContent = fmt(+row[field]);
        if (p === 'ct') el.className = +row[field] >= 0 ? 'qd-good' : 'qd-bad';
      });
    });
  });
  dash.draw('indtable', (tb) => {
    const r = QD.ok('indicators'); tb.replaceChildren(); if (!r) return;
    r.forEach((row) => {
      const tr = document.createElement('tr'); tr.dataset.key = row.key;
      const cells = [row.name, f2(+row.level), row.unit, sg(+row.change), row.change_label, sg(+row.z), F('+.1f')(+row.weight), sg(+row.contribution)];
      cells.forEach((t, i) => { const td = document.createElement('td'); td.textContent = t; if (i === 7) td.className = +row.contribution >= 0 ? 'qd-good' : 'qd-bad'; tr.appendChild(td); });
      tb.appendChild(tr);
    });
  });
  dash.draw('reftable', (tb) => {
    const r = QD.ok('reference'); tb.replaceChildren(); if (!r) return;
    r.forEach((row) => {
      const tr = document.createElement('tr'); tr.dataset.key = encodeURIComponent(row.name);
      [row.name, F('.2~f')(+row.level), row.note].forEach((t) => { const td = document.createElement('td'); td.textContent = t; tr.appendChild(td); });
      tb.appendChild(tr);
    });
  });
})();
// ---------- 성과 ----------
(function () {
  dash.draw('sumtable', (tb) => {
    const r = QD.ok('summary'); tb.replaceChildren(); if (!r) return;
    const best = {};
    ['cagr', 'sharpe', 'mdd', 'calmar'].forEach((k) => { best[k] = d3.max(r, (x) => +x[k]); });
    r.forEach((row) => {
      const tr = document.createElement('tr'); tr.dataset.key = encodeURIComponent(row.strategy);
      const keys = ['strategy', 'cagr', 'vol', 'sharpe', 'mdd', 'calmar', 'multiple'];
      keys.forEach((k, i) => {
        const td = document.createElement('td');
        td.textContent = i === 0 ? row[k] : F('.2f')(+row[k]);
        if (best[k] !== undefined && +row[k] === best[k]) td.style.fontWeight = '600';
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
  });
  const pick = (field, where) => (el) => {
    const r = QD.ok('summary'); const row = r && r.find((x) => x.strategy === where);
    el.textContent = row ? F('.3~f')(+row[field]) : '—';
  };
  dash.draw('avgw', pick('avg_weight', '레짐 전략'));
  dash.draw('turn', pick('turnover', '레짐 전략'));
  dash.draw('cost', pick('cost', '레짐 전략'));
  dash.draw('bhsharpe', pick('sharpe', '코스피200 보유'));

  const navSeries = () => [
    { key: 'nav_strategy', label: '레짐 전략', width: 2 },
    { key: 'nav_buyhold', label: '코스피200 보유' },
    { key: 'nav_fixed60', label: '고정 60/40' },
  ];
  dash.draw('navlegend', (el) => QD.legend(el, navSeries()));
  dash.draw('navchart', (el) => {
    const r = QD.ok('weekly_series'); if (!r) return QD.failed(el, 'weekly_series');
    QD.lines(el, r, { x: 'date', series: navSeries(), log: true, yFmt: F('.1~f'), tipFmt: F('.2f'), refs: [1], height: 300 });
  });
  const ddSeries = () => [{ key: 'dd_strategy', label: '레짐 전략', area: true, width: 1.6 }, { key: 'dd_buyhold', label: '코스피200 보유' }];
  dash.draw('ddlegend', (el) => QD.legend(el, ddSeries()));
  dash.draw('ddchart', (el) => {
    const r = QD.ok('weekly_series'); if (!r) return QD.failed(el, 'weekly_series');
    QD.lines(el, r, { x: 'date', series: ddSeries(), yFmt: F('.0f'), tipFmt: F('.1f'), include: [0], height: 220 });
  });
  const yrSeries = () => [{ key: 'strategy', label: '레짐 전략' }, { key: 'kospi200', label: '코스피200' }];
  dash.draw('yrlegend', (el) => QD.legend(el, yrSeries()));
  dash.draw('yrchart', (el) => {
    const r = QD.ok('yearly'); if (!r) return QD.failed(el, 'yearly');
    QD.bars(el, r, { x: 'year', series: yrSeries(), yFmt: F('.0f'), height: 280, xFmt: (d) => "'" + String(d).slice(2) });
  });
})();
// ---------- 검증 ----------
(function () {
  dash.draw('bucketchart', (el) => {
    const r = QD.ok('score_buckets'); if (!r) return QD.failed(el, 'score_buckets');
    const lab = { Q1: '최저 20%', Q2: '20~40%', Q3: '40~60%', Q4: '60~80%', Q5: '최고 20%' };
    QD.bars(el, r, { x: 'bucket', series: [{ key: 'fwd_ret', label: '다음 달 평균 수익률 %' }], yFmt: F('.2f'), labels: true, height: 220, xFmt: (d) => lab[d] || d });
  });
  dash.draw('quadtable', (tb) => {
    const r = QD.ok('regime_report'); tb.replaceChildren(); if (!r) return;
    const best = d3.max(r, (x) => +x.fwd_ret);
    r.forEach((row) => {
      const tr = document.createElement('tr'); tr.dataset.key = encodeURIComponent(row.quadrant);
      ['quadrant', 'days', 'share', 'fwd_ret', 'up_prob', 'vol'].forEach((k, i) => {
        const td = document.createElement('td');
        td.textContent = i === 0 ? row[k] : F('.2~f')(+row[k]);
        if (k === 'fwd_ret' && +row[k] === best) { td.className = 'qd-good'; td.style.fontWeight = '600'; }
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
  });
  dash.draw('senstable', (tb) => {
    const r = QD.ok('sensitivity'); tb.replaceChildren(); if (!r) return;
    const bh = QD.ok('summary'); const bhRow = bh && bh.find((x) => x.strategy === '코스피200 보유');
    const ref = bhRow ? +bhRow.sharpe : null;
    r.slice().sort((a, b) => +b.sharpe - +a.sharpe).forEach((row) => {
      const tr = document.createElement('tr');
      tr.dataset.key = [row.mom_window, row.slope, row.vix_crisis].map(encodeURIComponent).join(',');
      ['mom_window', 'slope', 'vix_crisis', 'cagr', 'vol', 'sharpe', 'mdd'].forEach((k) => {
        const td = document.createElement('td'); td.textContent = F('.2~f')(+row[k]);
        if (k === 'sharpe' && ref !== null) td.className = +row[k] > ref ? 'qd-good' : 'qd-bad';
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
  });
  dash.draw('sminv', (el) => { const v = dash.data('sens_stats'); el.textContent = v.status === 'ok' && v.data && v.data[0] ? F('.2f')(v.data[0].min) : '—'; });
  dash.draw('smaxv', (el) => { const v = dash.data('sens_stats'); el.textContent = v.status === 'ok' && v.data && v.data[0] ? F('.2f')(v.data[0].max) : '—'; });
})();