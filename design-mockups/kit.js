/* Small helpers shared by the "familiar" mockups (11-20).
   Every one of them keeps ShadowTree's real vocabulary: Redacted / Original, Best guess,
   Reveal on Disk, Index (Read-Only), match %, weak matches (< 25) hidden. */
window.KIT = (function () {
  const S = window.ST;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => [...(r || document).querySelectorAll(s)];

  const P = {
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    pdf: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 14h6M9 17h4"/>',
    text: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 15h6M9 18h3"/>',
    image: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m4 17 5-4.5 4 3.5 3-2.5 4 3.5"/>',
    audio: '<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    eyeoff: '<path d="M3 3l18 18M10 5.8A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 0 1-3.2 4M6.5 7.2A15 15 0 0 0 2.5 12S6 18.5 12 18.5a9 9 0 0 0 3.6-.8M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    shield: '<path d="M12 3 5 6v5.5c0 4.3 2.8 8 7 9.5 4.2-1.5 7-5.2 7-9.5V6z"/><path d="m9 12 2.2 2.2L15 10"/>',
    lock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
    chevR: '<path d="m9 6 6 6-6 6"/>', chevD: '<path d="m6 9 6 6 6-6"/>', chevL: '<path d="m15 6-6 6 6 6"/>', chevU: '<path d="m6 15 6-6 6 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14-4.5L4 9M4 4v5h5M4 13a8 8 0 0 0 14 4.5L20 15M20 20v-5h-5"/>',
    grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    list: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    sort: '<path d="M8 5v14M8 19l-3-3M8 19l3-3M16 19V5M16 5l-3 3M16 5l3 3"/>',
    disk: '<rect x="3.5" y="6" width="17" height="12" rx="2"/><path d="M3.5 14h17M7 16.5h.01"/>',
    open: '<path d="M14 4h6v6M20 4l-9 9M18 14v5H5V6h5"/>',
    copy: '<rect x="8" y="8" width="11" height="12" rx="2"/><path d="M5 16V5a1 1 0 0 1 1-1h9"/>',
    tree: '<path d="M12 21v-7M12 14c-3 0-6-2-6-5.5S9 3 12 3s6 2 6 5.5-3 5.5-6 5.5zM12 11l-3-2M12 9l3-2"/>',
    sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>',
    help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17h.01"/>',
    star: '<path d="m12 3.5 2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.9 6.8 19.7l1-5.9L3.5 9.7l5.9-.8z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    more: '<path d="M5 12h.01M12 12h.01M19 12h.01"/>',
    home: '<path d="M4 11 12 4l8 7v9h-5v-5H9v5H4z"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/>',
  };
  const icon = (n, s = 18, cls = '') => `<svg class="ic ${cls}" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[n] || P.file}</svg>`;
  const kindIcon = f => ({ pdf: 'pdf', text: 'text', image: 'image', audio: 'audio' }[f.kind] || 'file');

  const TYPE_NAME = { GIVEN_NAME: 'first name', SURNAME: 'surname', EMAIL: 'email address', PHONE: 'phone number', ACCOUNT: 'account number' };
  const nice = t => TYPE_NAME[t] || t.toLowerCase();

  /* File text as HTML. Redacted shows the same [TYPE_n] tokens the real app does. */
  function body(f, red, q) {
    const cnt = {};
    return S.parseText(f.text).map(s => {
      if (s.t === 'text') return q ? hl(s.v, q) : esc(s.v);
      cnt[s.type] = (cnt[s.type] || 0) + 1;
      return red
        ? `<mark class="pii r" data-type="${s.type}" title="Personal data: ${nice(s.type)}">[${s.type}_${cnt[s.type]}]</mark>`
        : `<mark class="pii o" data-type="${s.type}" title="Personal data: ${nice(s.type)}">${esc(s.v)}</mark>`;
    }).join('');
  }
  /* Same, but as an array of text lines so editors can number them. */
  function lines(f, red) { return body(f, red).split('\n'); }

  function hl(text, q) {
    const words = (q || '').toLowerCase().split(/\s+/).filter(w => w.length > 3);
    let out = esc(text);
    words.forEach(w => { out = out.replace(new RegExp('(' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\w*)', 'ig'), '<b class="hit">$1</b>'); });
    return out;
  }

  const FCOL = { fin: '#2e8b62', work: '#3f68d4', personal: '#b4469a', media: '#d98a1c', unsorted: '#78828f', pii: '#c2255c' };

  /* Search with the app's rules: weak (< 25) hidden. Returns {hits, weak}. */
  function run(q) {
    const all = S.search(q);
    return { hits: all.filter(r => r.match >= 25), weak: all.filter(r => r.match < 25).length };
  }
  const folderOf = f => S.primary(f);
  const guess = f => S.isGuess(f);
  const pii = f => S.piiList(f).length;

  /* default toast style, prepended so a page's own #toast rules win */
  const st = document.createElement('style');
  st.textContent = '#toast{position:fixed;left:50%;bottom:44px;transform:translate(-50%,12px);background:#222;color:#fff;padding:10px 18px;border-radius:8px;opacity:0;transition:.2s;pointer-events:none;z-index:99;font:14px system-ui}#toast.on{opacity:1;transform:translate(-50%,0)}';
  document.head.prepend(st);

  function toast(msg) {
    let t = $('#toast');
    if (!t) { t = document.createElement('div'); t.id = 'toast'; t.setAttribute('role', 'status'); document.body.appendChild(t); }
    t.textContent = msg; t.classList.add('on');
    clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove('on'), 2600);
  }

  /* Fake scan: calls tick(0..1) then done(). */
  function scan(tick, done) {
    let p = 0; const id = setInterval(() => { p += 0.06 + Math.random() * 0.06; tick(Math.min(p, 1)); if (p >= 1) { clearInterval(id); done && done(); } }, 120);
  }

  return { S, esc, $, $$, icon, kindIcon, body, lines, hl, nice, FCOL, run, folderOf, guess, pii, toast, scan };
})();
