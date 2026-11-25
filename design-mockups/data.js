/* Shared sample data for all ShadowTree mockups.
   Mirrors the real sample folder (scripts/make_samples.py) plus a few extra files
   so every state exists: best guess (<0.5), Unsorted, PII, ai fallback.
   PII markup in `text`: {{TYPE:value}} */
window.ST = (function () {
  const ROOT = 'C:\\Demo\\sample_messy_folder\\';

  const folders = [
    { id: 'fin',      name: 'Finance & Receipts',  short: 'Finance',  blurb: 'invoices, receipts, bills, money moving' },
    { id: 'work',     name: 'Work & Research',     short: 'Work',     blurb: 'meetings, research, projects' },
    { id: 'personal', name: 'Personal & Notes',    short: 'Personal', blurb: 'journals, diaries, private notes' },
    { id: 'media',    name: 'Screenshots & Media', short: 'Media',    blurb: 'screenshots, photos, voice memos' },
    { id: 'unsorted', name: 'Unsorted',            short: 'Unsorted', blurb: 'nothing matched well enough' },
  ];

  const files = [
    { id: 1, name: 'invoice INV-3307.pdf', title: 'INV-3307', kind: 'pdf', bytes: 218400,
      links: [['fin', .93]], ai: 'ok',
      summary: 'Invoice from Northwind Supplies for an ergonomic chair and a standing desk. Total due $701.00 by 5 December.',
      tags: ['invoice', 'ergonomic chair', 'standing desk', 'northwind'],
      text: 'INVOICE INV-3307\nFrom: Northwind Supplies, 12 Example Street\nBill to: {{GIVEN_NAME:Alex}} {{SURNAME:Sample}}\nContact: {{EMAIL:billing@example.com}}, {{PHONE:+1 555-0142}}\n\n1 x ergonomic chair      $289.00\n1 x standing desk        $412.00\n\nTotal due: $701.00      Due 2026-12-05' },
    { id: 2, name: 'coffee receipt.txt', title: 'Coffee receipt', kind: 'text', bytes: 412,
      links: [['fin', .98]], ai: 'fallback',
      summary: 'Corner Cafe receipt for two flat whites and an almond croissant. Total paid $10.50.',
      tags: ['receipt', 'cafe', 'date', 'customer'],
      text: 'Corner Cafe receipt\nDate: 2026-11-02\nCustomer: {{GIVEN_NAME:Alex}} {{SURNAME:Sample}}, {{EMAIL:alex.sample@example.com}}, phone {{PHONE:555-0123}}\nCard ending 4242\n\n2 x flat white           $7.00\n1 x almond croissant     $3.50\n\nTotal paid: $10.50. Thank you for your payment.' },
    { id: 3, name: 'budget screenshot.png', title: 'Budget screenshot', kind: 'image', bytes: 96300,
      links: [['media', .81], ['fin', .55]], ai: 'ok',
      summary: 'Screenshot of a monthly budget window: groceries $120.50, rent $950.00, transport $60.00.',
      tags: ['screenshot', 'budget', 'groceries', 'rent'],
      text: 'Monthly Budget\nGroceries   $120.50\nRent        $950.00\nTransport    $60.00' },
    { id: 4, name: 'meeting notes.md', title: 'Team meeting notes', kind: 'text', bytes: 1480,
      links: [['work', .99]], ai: 'ok',
      summary: 'Sam owns the API migration and will report on Friday. Release checklist due Wednesday.',
      tags: ['meeting', 'api migration', 'release checklist', 'team'],
      text: 'Team meeting notes\nAttendees: {{GIVEN_NAME:Sam}}, {{GIVEN_NAME:Priya}}, {{GIVEN_NAME:Jo}}\n\nSam owns the API migration and will report on Friday.\n- release checklist: draft by Wednesday\n- ask {{EMAIL:jo.lee@example.com}} for the staging key review\n\nNext sync: Friday 10:00' },
    { id: 5, name: 'research outline.md', title: 'Research outline', kind: 'text', bytes: 2210,
      links: [['work', .70]], ai: 'ok',
      summary: 'Can small on-device models rank personal documents? Compare keyword search with a zero-shot classifier.',
      tags: ['research', 'outline', 'models', 'local-first'],
      text: 'Question: can small on-device models rank personal documents?\nMethod: compare keyword search with a zero-shot classifier.\nData: 8 sample files, no uploads.\nRisk: small models rank by meaning only roughly.' },
    { id: 6, name: 'journal nov.txt', title: 'Journal, 18 November', kind: 'text', bytes: 1960,
      links: [['personal', .88]], ai: 'ok',
      summary: 'A short diary entry about a bad night, a walk to the river before work, and wanting to write more.',
      tags: ['diary', 'journal', 'river', 'walk'],
      text: 'Nov 18. Slept badly. Walked to the river before work and the light was low and orange. Called Mum about the weekend. Want to write more of these.' },
    { id: 7, name: 'voice memo.wav', title: 'Voice memo', kind: 'audio', bytes: 612000,
      links: [['media', .74], ['fin', .61]], ai: 'ok',
      summary: 'A spoken reminder to pay the electricity invoice before Friday.',
      tags: ['reminder', 'invoice', 'friday', 'electricity'],
      text: 'Hey, it is {{GIVEN_NAME:Alex}}. Please pay the electricity invoice before Friday. The reference is in the email from {{EMAIL:accounts@example.com}}.' },
    { id: 8, name: 'bank transfer note.txt', title: 'Bank transfer note', kind: 'text', bytes: 233,
      links: [['fin', .67]], ai: 'ok',
      summary: 'Note about a $950.00 transfer for November rent, reference RENT-11.',
      tags: ['rent', 'transfer', 'bank', 'november'],
      text: 'Transfer to {{GIVEN_NAME:Jordan}} {{SURNAME:Rivera}} for November rent.\nAmount $950.00. Reference RENT-11.\nAccount ending {{ACCOUNT:0198}}.' },
    { id: 9, name: 'scan0042.pdf', title: 'Scanned electricity bill', kind: 'pdf', bytes: 1480000,
      links: [['fin', .46]], ai: 'fallback',
      summary: 'Scanned page read by OCR: an electricity bill, amount due $84.20, dated 30November.',
      tags: ['bill', 'electricity', 'scan', 'ocr'],
      text: 'Electricity bill, 30November.\nAmount due $84.20.\nAccount {{ACCOUNT:7712}}.' },
    { id: 10, name: 'IMG_4471.jpg', title: 'Desk photo', kind: 'image', bytes: 2840000,
      links: [['media', .44]], ai: 'ok',
      summary: 'A slightly blurred photo of a desk with a laptop and an open notebook.',
      tags: ['photo', 'desk', 'laptop', 'notebook'],
      text: 'A photo of a desk with a laptop and a notebook, slightly blurred.' },
    { id: 11, name: 'Screenshot 2026-11-20.png', title: 'Error dialog screenshot', kind: 'image', bytes: 143000,
      links: [['media', .88]], ai: 'ok',
      summary: 'Screenshot of a dialog reading error 0x80070057, the parameter is incorrect.',
      tags: ['screenshot', 'error', 'dialog', '0x80070057'],
      text: 'Error 0x80070057\nThe parameter is incorrect.\n[ OK ]  [ Cancel ]' },
    { id: 12, name: 'lecture 7 slides.pdf', title: 'Lecture 7: Attention', kind: 'pdf', bytes: 3190000,
      links: [['work', .77]], ai: 'ok',
      summary: 'Slides on attention and transformers: query, key and value, positional encoding. Reading: chapter 9.',
      tags: ['lecture', 'transformers', 'attention', 'slides'],
      text: 'Lecture 7. Attention and transformers.\nQuery, key and value.\nPositional encoding.\nReading: chapter 9.' },
    { id: 13, name: 'tmp_export.txt', title: 'tmp_export', kind: 'text', bytes: 5400,
      links: [['unsorted', 1]], ai: 'fallback',
      summary: 'Comma separated numbers with no labels. Title taken from the file name.',
      tags: ['numbers', 'export'],
      text: '4412,9031,17,882,6,1203,77,\n(312 more values)' },
  ];

  const byId = Object.fromEntries(files.map(f => [f.id, f]));
  const fById = Object.fromEntries(folders.map(f => [f.id, f]));
  const KIND = { pdf: 'PDF', text: 'Text', image: 'Image', audio: 'Audio' };

  function parseText(text) {
    const out = []; const re = /\{\{([A-Z_]+):([^}]*)\}\}/g; let i = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > i) out.push({ t: 'text', v: text.slice(i, m.index) });
      out.push({ t: 'pii', type: m[1], v: m[2] }); i = re.lastIndex;
    }
    if (i < text.length) out.push({ t: 'text', v: text.slice(i) });
    return out;
  }
  const piiList = f => parseText(f.text).filter(s => s.t === 'pii');
  const piiTypes = f => [...new Set(piiList(f).map(s => s.type))];
  const plain = f => parseText(f.text).map(s => s.v).join('');

  // Hand-tuned rankings for the queries the demo script uses; anything else falls back to word overlap.
  const CANNED = {
    'invoice':          [[1, 100], [7, 71], [9, 58], [2, 44], [8, 31]],
    'pay the bill':     [[7, 88], [1, 64], [9, 59], [8, 41], [2, 33]],
    'my diary':         [[6, 97], [13, 12]],
    'meeting':          [[4, 100], [5, 38], [12, 27]],
    'money i spent':    [[8, 78], [7, 66], [2, 61], [1, 52], [3, 47]],
  };
  function search(q) {
    const k = q.trim().toLowerCase();
    if (!k) return [];
    if (CANNED[k]) return CANNED[k].map(([id, m]) => ({ f: byId[id], match: m }));
    const words = k.split(/\s+/).filter(w => w.length > 1);
    return files.map(f => {
      const hay = (f.name + ' ' + f.title + ' ' + f.summary + ' ' + f.tags.join(' ') + ' ' + plain(f)).toLowerCase();
      const hit = words.filter(w => hay.includes(w.slice(0, Math.max(3, w.length - 2)))).length;
      const inName = words.every(w => (f.name + f.title).toLowerCase().includes(w));
      let m = words.length ? Math.round(80 * hit / words.length) : 0;
      if (inName) m = Math.min(100, m + 20);
      return { f, match: m };
    }).filter(r => r.match > 0).sort((a, b) => b.match - a.match);
  }

  return {
    ROOT, folders, files, byId, fById, KIND, parseText, piiList, piiTypes, plain, search,
    primary: f => fById[f.links[0][0]],
    score: f => f.links[0][1],
    isGuess: f => f.links[0][0] !== 'unsorted' && f.links[0][1] < 0.5,
    inFolder: id => files.filter(f => f.links.some(l => l[0] === id)),
    sensitive: () => files.filter(f => piiList(f).length),
    pct: s => Math.round(s * 100),
    size: b => b < 1024 ? b + ' B' : b < 1048576 ? Math.round(b / 1024) + ' KB' : (b / 1048576).toFixed(1) + ' MB',
    path: f => ROOT + f.name,
    redact: (v, type, n) => '[' + type + '_' + n + ']',
  };
})();
