// Learning curve: weekly accuracy of the AI against pharmacist-verified truth.
// One series -> no legend box; thin 2px line, 10% area wash, end label, hairline grid,
// crosshair + tooltip on hover/focus, and a table twin so no value hides behind hover.
import { h, mount, svg } from '../lib/dom.js';
import { fmtDay, fmtNum, fmtPct } from '../lib/ui.js';

const W = 640;
const H = 240;
const PAD = { top: 16, right: 46, bottom: 30, left: 44 };

export function learningCurve(points) {
  const hasData = points.some((p) => p.accuracy !== null && p.accuracy !== undefined);
  const wrap = h('div', { class: 'chart', dir: 'ltr' });
  const table = curveTable(points);
  table.classList.add('hidden');
  const toggle = h('button', { type: 'button', class: 'btn sm ghost' }, 'عرض كجدول');
  toggle.addEventListener('click', () => {
    const showTable = table.classList.toggle('hidden') === false;
    wrap.classList.toggle('hidden', showTable);
    toggle.textContent = showTable ? 'عرض كرسم' : 'عرض كجدول';
  });
  if (!hasData) {
    return h('div', { class: 'empty' }, h('p', {}, 'سيظهر منحنى التعلّم بعد اعتماد أول روشتات قرأها الذكاء الاصطناعي.'));
  }

  const iw = W - PAD.left - PAD.right;
  const ih = H - PAD.top - PAD.bottom;
  const x = (i) => PAD.left + (points.length === 1 ? iw / 2 : (i * iw) / (points.length - 1));
  const y = (v) => PAD.top + ih - v * ih;

  const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'منحنى دقة القراءة الأسبوعية' });
  const grid = svg('g', { class: 'grid' });
  for (const v of [0, 0.25, 0.5, 0.75, 1]) {
    grid.append(svg('line', { x1: PAD.left, x2: W - PAD.right, y1: y(v), y2: y(v), class: v === 0 ? 'baseline' : '' }));
    const label = svg('text', { x: PAD.left - 8, y: y(v) + 4, 'text-anchor': 'end', class: 'tick' });
    label.textContent = fmtPct(v);
    grid.append(label);
  }
  points.forEach((p, i) => {
    if (i % 2 === (points.length - 1) % 2) {
      const label = svg('text', { x: x(i), y: H - 8, 'text-anchor': 'middle', class: 'tick' });
      label.textContent = fmtDay(p.week);
      grid.append(label);
    }
  });
  root.append(grid);

  // Break the line where a week has no verified readings.
  const segments = [];
  let current = [];
  points.forEach((p, i) => {
    if (p.accuracy === null || p.accuracy === undefined) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push([x(i), y(p.accuracy)]);
    }
  });
  if (current.length) segments.push(current);
  for (const seg of segments) {
    const line = seg.map(([px, py], i) => `${i ? 'L' : 'M'}${px.toFixed(1)},${py.toFixed(1)}`).join('');
    if (seg.length > 1) {
      root.append(svg('path', { d: `${line}L${seg[seg.length - 1][0].toFixed(1)},${y(0)}L${seg[0][0].toFixed(1)},${y(0)}Z`, class: 'area' }));
    }
    root.append(svg('path', { d: line, class: 'series' }));
    if (seg.length === 1) root.append(svg('circle', { cx: seg[0][0], cy: seg[0][1], r: 4, class: 'marker' }));
  }
  const lastIndex = points.map((p) => p.accuracy !== null && p.accuracy !== undefined).lastIndexOf(true);
  const last = points[lastIndex];
  root.append(svg('circle', { cx: x(lastIndex), cy: y(last.accuracy), r: 4.5, class: 'marker' }));
  const endLabel = svg('text', { x: x(lastIndex) + 9, y: y(last.accuracy) + 4, class: 'end-label' });
  endLabel.textContent = fmtPct(last.accuracy);
  root.append(endLabel);

  // Hover / focus layer: the crosshair snaps to the nearest week.
  const cross = svg('line', { y1: PAD.top, y2: PAD.top + ih, class: 'crosshair', visibility: 'hidden' });
  const dot = svg('circle', { r: 5, class: 'marker', visibility: 'hidden' });
  const hit = svg('rect', { x: PAD.left - 10, y: PAD.top, width: iw + 20, height: ih, class: 'hit', tabindex: '0', 'aria-label': 'تفاصيل كل أسبوع' });
  root.append(cross, dot, hit);
  const tip = h('div', { class: 'chart-tooltip hidden', role: 'status' });
  wrap.append(root, tip);

  let focusIndex = lastIndex;
  function show(i) {
    const p = points[i];
    cross.setAttribute('x1', x(i));
    cross.setAttribute('x2', x(i));
    cross.setAttribute('visibility', 'visible');
    if (p.accuracy !== null && p.accuracy !== undefined) {
      dot.setAttribute('cx', x(i));
      dot.setAttribute('cy', y(p.accuracy));
      dot.setAttribute('visibility', 'visible');
    } else {
      dot.setAttribute('visibility', 'hidden');
    }
    mount(
      tip,
      h('div', {}, h('strong', {}, p.accuracy === null || p.accuracy === undefined ? 'لا بيانات' : fmtPct(p.accuracy))),
      h('div', {}, h('span', { class: 'key' }), 'دقة أسماء الأدوية'),
      h('div', { class: 'muted' }, `أسبوع ${fmtDay(p.week)} · ${fmtNum(p.count)} روشتة`),
    );
    tip.classList.remove('hidden');
    const box = wrap.getBoundingClientRect();
    const px = (x(i) / W) * box.width;
    tip.style.setProperty('left', `${Math.min(Math.max(px - 70, 0), box.width - 150)}px`);
    tip.style.setProperty('top', '0px');
  }
  function hide() {
    cross.setAttribute('visibility', 'hidden');
    dot.setAttribute('visibility', 'hidden');
    tip.classList.add('hidden');
  }
  hit.addEventListener('pointermove', (e) => {
    const box = root.getBoundingClientRect();
    const sx = ((e.clientX - box.left) / box.width) * W;
    const i = Math.round(((sx - PAD.left) / iw) * (points.length - 1));
    focusIndex = Math.max(0, Math.min(points.length - 1, i));
    show(focusIndex);
  });
  hit.addEventListener('pointerleave', hide);
  hit.addEventListener('focus', () => show(focusIndex));
  hit.addEventListener('blur', hide);
  hit.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowRight') focusIndex = Math.min(points.length - 1, focusIndex + 1);
    else if (e.key === 'ArrowLeft') focusIndex = Math.max(0, focusIndex - 1);
    else return;
    e.preventDefault();
    show(focusIndex);
  });

  return h('div', {}, h('div', { class: 'row', style: { 'justify-content': 'flex-end' } }, toggle), wrap, table);
}

function curveTable(points) {
  return h(
    'div',
    { class: 'table-wrap' },
    h(
      'table',
      { class: 'table' },
      h('thead', {}, h('tr', {}, h('th', {}, 'الأسبوع'), h('th', { class: 'num' }, 'الدقة'), h('th', { class: 'num' }, 'عدد الروشتات'))),
      h(
        'tbody',
        {},
        points.map((p) => h('tr', {}, h('td', {}, fmtDay(p.week)), h('td', { class: 'num' }, fmtPct(p.accuracy)), h('td', { class: 'num' }, fmtNum(p.count)))),
      ),
    ),
  );
}
