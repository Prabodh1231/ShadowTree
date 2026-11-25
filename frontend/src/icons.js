// Small stroke icons, built with DOM calls (no innerHTML), drawn in currentColor.
const NS = 'http://www.w3.org/2000/svg';
const P = (d) => ['path', { d }];
const ICONS = {
  file: [P('M6 3h8l4 4v14H6z'), P('M14 3v4h4')],
  pdf: [P('M6 3h8l4 4v14H6z'), P('M14 3v4h4M9 14h6M9 17h4')],
  text: [P('M6 3h8l4 4v14H6z'), P('M14 3v4h4M9 12h6M9 15h6M9 18h3')],
  image: [['rect', { x: 3.5, y: 5, width: 17, height: 14, rx: 2 }], ['circle', { cx: 9, cy: 10, r: 1.6 }], P('m4 17 5-4.5 4 3.5 3-2.5 4 3.5')],
  audio: [P('M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2')],
  grid: [['rect', { x: 4, y: 4, width: 7, height: 7, rx: 1.5 }], ['rect', { x: 13, y: 4, width: 7, height: 7, rx: 1.5 }], ['rect', { x: 4, y: 13, width: 7, height: 7, rx: 1.5 }], ['rect', { x: 13, y: 13, width: 7, height: 7, rx: 1.5 }]],
  list: [P('M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01')],
  gallery: [['rect', { x: 3.5, y: 4, width: 17, height: 11, rx: 2 }], P('M6 19h2M11 19h2M16 19h2')],
  chevL: [P('m15 6-6 6 6 6')],
  open: [P('M14 4h6v6M20 4l-9 9M18 14v5H5V6h5')],
  copy: [['rect', { x: 8, y: 8, width: 11, height: 12, rx: 2 }], P('M5 16V5a1 1 0 0 1 1-1h9')],
  lock: [['rect', { x: 5, y: 10.5, width: 14, height: 10, rx: 2 }], P('M8 10.5V8a4 4 0 0 1 8 0v2.5')],
  plus: [P('M12 5v14M5 12h14')],
  x: [P('M6 6l12 12M18 6 6 18')],
  folder: [P('M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z')],
  info: [['circle', { cx: 12, cy: 12, r: 9 }], P('M12 11v5M12 8h.01')],
  panelLeft: [['rect', { x: 3.5, y: 4.5, width: 17, height: 15, rx: 2 }], P('M9.5 4.5v15')],
  panelRight: [['rect', { x: 3.5, y: 4.5, width: 17, height: 15, rx: 2 }], P('M14.5 4.5v15')],
  sun: [['circle', { cx: 12, cy: 12, r: 4 }], P('M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4')],
  moon: [P('M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z')],
  monitor: [['rect', { x: 3, y: 4.5, width: 18, height: 12, rx: 2 }], P('M9 20h6M12 16.5V20')],
  search: [['circle', { cx: 11, cy: 11, r: 6.5 }], P('m16 16 4.5 4.5')],
};

/** An <svg> element for the named icon. */
export function icon(name, size = 16) {
  const svg = document.createElementNS(NS, 'svg');
  for (const [k, v] of Object.entries({ width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    'stroke-width': 1.7, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', class: 'ic' })) svg.setAttribute(k, v);
  for (const [tag, attrs] of ICONS[name] ?? ICONS.file) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    svg.append(el);
  }
  return svg;
}

export const kindIcon = (kind) => (ICONS[kind] ? kind : 'file');
