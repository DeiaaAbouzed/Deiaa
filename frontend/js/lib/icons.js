// A small hand-drawn 24px stroke icon set (currentColor), built as DOM nodes.
import { svg } from './dom.js';

const P = (d) => ['path', { d }];
const C = (cx, cy, r, fill) => ['circle', { cx, cy, r, ...(fill ? { fill: 'currentColor', stroke: 'none' } : {}) }];
const R = (x, y, width, height, rx = 0) => ['rect', { x, y, width, height, rx }];
const L = (points) => ['polyline', { points }];

const ICONS = {
  scan: [P('M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2'), P('M7 12h10')],
  camera: [P('M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z'), C(12, 13, 3.2)],
  image: [R(3, 3, 18, 18, 2), C(9, 9, 2), P('m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21')],
  upload: [P('M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'), L('17 8 12 3 7 8'), P('M12 3v12')],
  download: [P('M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'), L('7 10 12 15 17 10'), P('M12 15V3')],
  check: [L('20 6 9 17 4 12')],
  x: [P('M18 6 6 18M6 6l12 12')],
  alert: [P('M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'), P('M12 9v4'), C(12, 17, 1, true)],
  info: [C(12, 12, 10), P('M12 16v-4'), C(12, 8, 1, true)],
  shield: [P('M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'), L('9 12 11 14 15 10')],
  lock: [R(3, 11, 18, 11, 2), P('M7 11V7a5 5 0 0 1 10 0v4')],
  key: [C(7.5, 15.5, 5.5), P('m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3')],
  user: [P('M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2'), C(12, 7, 4)],
  users: [P('M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2'), C(9, 7, 4), P('M23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8')],
  sliders: [P('M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6')],
  book: [P('M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z'), P('M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z')],
  pill: [P('M10.5 20.5 3.5 13.5a5 5 0 1 1 7-7l7 7a5 5 0 1 1-7 7z'), P('m8.5 8.5 7 7')],
  doctor: [P('M5 3H4a2 2 0 0 0-2 2v4a6 6 0 0 0 12 0V5a2 2 0 0 0-2-2h-1'), P('M8 15v1a6 6 0 0 0 12 0v-3'), C(20, 11, 2)],
  layers: [['polygon', { points: '12 2 2 7 12 12 22 7 12 2' }], L('2 17 12 22 22 17'), L('2 12 12 17 22 12')],
  chart: [L('22 7 13.5 15.5 8.5 10.5 2 17'), L('16 7 22 7 22 13')],
  clock: [C(12, 12, 10), L('12 6 12 12 16 14')],
  inbox: [L('22 12 16 12 14 15 10 15 8 12 2 12'), P('M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z')],
  logout: [P('M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4'), L('16 17 21 12 16 7'), P('M21 12H9')],
  sun: [C(12, 12, 4), P('M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4')],
  moon: [P('M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z')],
  printer: [L('6 9 6 2 18 2 18 9'), P('M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2'), R(6, 14, 12, 8)],
  refresh: [P('M21 12a9 9 0 1 1-2.6-6.4L21 8'), L('21 3 21 8 16 8')],
  trash: [L('3 6 5 6 21 6'), P('M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2')],
  pencil: [P('M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z')],
  eyeOff: [P('M17.9 17.9A10 10 0 0 1 12 20c-7 0-11-8-11-8a18.5 18.5 0 0 1 5.1-5.9M9.9 4.2A9 9 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.2 3.2m-6.7-1.1a3 3 0 1 1-4.2-4.2'), P('M1 1l22 22')],
  rotate: [L('23 4 23 10 17 10'), P('M20.5 15a9 9 0 1 1-2.1-9.4L23 10')],
  undo: [P('M3 7v6h6'), P('M21 17a9 9 0 0 0-15-6.7L3 13')],
  zoomIn: [C(11, 11, 8), P('m21 21-4.3-4.3M11 8v6M8 11h6')],
  zoomOut: [C(11, 11, 8), P('m21 21-4.3-4.3M8 11h6')],
  fit: [P('M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M16 21h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3')],
  sparkles: [P('M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z'), P('M19 2v4M21 4h-4')],
  arrowUp: [P('M12 19V5M5 12l7-7 7 7')],
  arrowDown: [P('M12 5v14M19 12l-7 7-7-7')],
  chevronLeft: [L('15 18 9 12 15 6')],
  chevronRight: [L('9 18 15 12 9 6')],
  plus: [P('M12 5v14M5 12h14')],
  search: [C(11, 11, 8), P('m21 21-4.3-4.3')],
  file: [P('M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'), L('14 2 14 8 20 8'), P('M16 13H8M16 17H8')],
  award: [C(12, 8, 6), P('M15.5 12.9 17 22l-5-3-5 3 1.5-9.1')],
  timer: [C(12, 13, 8), P('M12 9v4l2 2M10 2h4')],
  cpu: [R(4, 4, 16, 16, 2), R(9, 9, 6, 6), P('M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3')],
  cloud: [P('M17.5 19H9a7 7 0 1 1 6.7-9h1.8a4.5 4.5 0 1 1 0 9z')],
  more: [C(5, 12, 1.6, true), C(12, 12, 1.6, true), C(19, 12, 1.6, true)],
  activity: [L('22 12 18 12 15 21 9 3 6 12 2 12')],
  tag: [P('M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z'), C(7, 7, 1.2, true)],
  contrast: [C(12, 12, 10), ['path', { d: 'M12 2a10 10 0 0 0 0 20z', fill: 'currentColor', stroke: 'none' }]],
  merge: [C(18, 18, 3), C(6, 6, 3), P('M6 21V9a9 9 0 0 0 9 9')],
  home: [P('M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z')],
};

export function icon(name, cls = '') {
  const parts = ICONS[name] || ICONS.info;
  return svg(
    'svg',
    {
      viewBox: '0 0 24 24',
      fill: 'none',
      stroke: 'currentColor',
      'stroke-width': 2,
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      'aria-hidden': 'true',
      focusable: 'false',
      class: cls || null,
    },
    parts.map(([tag, attrs]) => svg(tag, attrs)),
  );
}

let logoSeq = 0;

/** The رُشد mark: a prescription "R/" with a scanning spark. */
export function logo() {
  const id = `lg${++logoSeq}`;
  return svg(
    'svg',
    { viewBox: '0 0 64 64', 'aria-hidden': 'true' },
    svg(
      'defs',
      {},
      svg(
        'linearGradient',
        { id, x1: 0, y1: 0, x2: 1, y2: 1 },
        svg('stop', { offset: '0', 'stop-color': '#16b3a1' }),
        svg('stop', { offset: '1', 'stop-color': '#005b53' }),
      ),
    ),
    svg('rect', { width: 64, height: 64, rx: 17, fill: `url(#${id})` }),
    svg('path', {
      d: 'M20 47V17h12.5a9 9 0 0 1 0 18H20M30.5 35 44 48.5M37 48.5 45.5 40',
      fill: 'none',
      stroke: '#ffffff',
      'stroke-width': 5,
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    }),
    svg('circle', { cx: 50, cy: 15.5, r: 4, fill: '#a8f5e6' }),
  );
}
