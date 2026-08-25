/* RebrandX UI — vanilla JS. Talks to the Python shell over the `rbx` bridge. */
'use strict';

/* ---------------------------------------------------------------- bridge */
const _pending = new Map();
let _seq = 0;
const _handlers = {};

// Two transports, one API. Linux runs inside WebKitGTK and posts messages
// that Python answers via __rbx_reply; Windows runs inside WebView2 where
// pywebview exposes an async api object directly.
const HAS_WEBKIT = !!(window.webkit && window.webkit.messageHandlers
                      && window.webkit.messageHandlers.rbx);

function call(method, params) {
  params = params || {};
  if (HAS_WEBKIT) {
    return new Promise((resolve, reject) => {
      const id = ++_seq;
      _pending.set(id, [resolve, reject]);
      try {
        window.webkit.messageHandlers.rbx.postMessage(
          JSON.stringify({ id, method, params }));
      } catch (e) {
        _pending.delete(id);
        reject(new Error('bridge unavailable'));
      }
    });
  }
  if (window.pywebview && window.pywebview.api) {
    return window.pywebview.api.rpc(method, params).then((r) => {
      if (!r || r.ok === false) throw new Error((r && r.error) || 'call failed');
      return r.value;
    });
  }
  return Promise.reject(new Error('bridge unavailable'));
}
window.__rbx_reply = (id, payload, error) => {
  const p = _pending.get(id);
  if (!p) return;
  _pending.delete(id);
  error ? p[1](new Error(error)) : p[0](payload);
};
window.__rbx_event = (channel, payload) => {
  (_handlers[channel] || []).forEach((fn) => fn(payload));
};
const on = (ch, fn) => (_handlers[ch] = _handlers[ch] || []).push(fn);

/* ----------------------------------------------------------------- state */
const S = {
  source: '', sourceLabel: '', recents: [],
  find: '', replace: '',
  caseSensitive: true, matchVariants: true, useRegex: false,
  renameFiles: true, replaceContents: true, stripMeta: false, dryRun: false,
  stripProjectFiles: false, projectGlobs: {},
  excludes: { '.git/': true, 'node_modules/': true, '*.lock': true },
  mode: 'copy', dest: '', destTouched: false,
  selected: null, skippedFiles: new Set(), skippedLines: new Set(),
  entries: [], chips: [], regexError: null, truncated: false, scanError: null,
  totals: { filesChanged: 0, replacements: 0, renames: 0, removed: 0, dropped: 0 },
  diff: null, applied: false, appliedInfo: null,
  advOpen: false, pickerOpen: false, settingsOpen: false,
  settings: { confirmBeforeApply: true, showLineNumbers: true, backup: true, copyIgnored: false },
  busy: false, scanning: false, home: '',
  platform: '', sep: '/',
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

function shortPath(p, max) {
  max = max || 44;
  if (p.length <= max) return p;
  return '…' + p.slice(-(max - 1));
}
function plural(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }

/* --------------------------------------------------------------- options */
function optsPayload() {
  return {
    find: S.find, replace: S.replace,
    caseSensitive: S.caseSensitive, matchVariants: S.matchVariants,
    useRegex: S.useRegex, renameFiles: S.renameFiles,
    replaceContents: S.replaceContents, stripMeta: S.stripMeta,
    stripProjectFiles: S.stripProjectFiles, projectGlobs: S.projectGlobs,
    excludes: S.excludes,
    skippedFiles: [...S.skippedFiles],
    skippedLines: [...S.skippedLines],
  };
}

/* ---------------------------------------------------------------- scanning */
let scanTimer = null, scanGen = 0;

function invalidate(opts) {
  opts = opts || {};
  if (!opts.keepApplied) { S.applied = false; S.appliedInfo = null; }
  clearTimeout(scanTimer);
  scanTimer = setTimeout(runScan, opts.now ? 0 : 220);
  render();
}

async function runScan() {
  if (!S.source) {
    S.entries = []; S.chips = []; S.diff = null; S.selected = null;
    S.totals = { filesChanged: 0, replacements: 0, renames: 0, removed: 0, dropped: 0 };
    S.scanning = false; render();
    return;
  }
  const gen = ++scanGen;
  S.scanning = true;
  renderStatus();
  try {
    const r = await call('scan', { source: S.source, opts: optsPayload() });
    if (gen !== scanGen) return;
    S.entries = r.entries || [];
    S.totals = r.totals;
    S.chips = r.chips || [];
    S.regexError = r.regexError;
    S.truncated = r.truncated;
    S.scanError = r.error;
    S.sourceLabel = r.rootLabel || S.sourceLabel;
    if (S.selected && !S.entries.some((e) => e.path === S.selected && !e.dir && !e.excluded)) {
      S.selected = null; S.diff = null;
    }
    if (!S.selected) autoSelect();
  } catch (e) {
    S.scanError = e.message;
  } finally {
    if (gen === scanGen) S.scanning = false;
    render();
    if (S.selected) loadDiff(S.selected);
  }
}

function autoSelect() {
  const best = S.entries.find((e) => !e.dir && !e.excluded && (e.count || e.removed || e.renamed));
  if (best) { S.selected = best.path; S.diff = null; }
}

let diffGen = 0;
async function loadDiff(path) {
  const gen = ++diffGen;
  try {
    const d = await call('diff', { source: S.source, path, opts: optsPayload() });
    if (gen !== diffGen) return;
    S.diff = d;
    renderDiff();
  } catch (e) { /* selection changed under us */ }
}

/* ------------------------------------------------------------- rendering */
function render() {
  renderHeader();
  renderToolbar();
  renderRules();
  renderFiles();
  renderDiff();
  renderStatus();
}

function closePops() {
  if (!S.pickerOpen && !S.settingsOpen) return;
  S.pickerOpen = S.settingsOpen = false;
  renderHeader();
}

function renderHeader() {
  $('folderPath').textContent = S.source ? shortPath(S.sourceLabel) : 'Pick a folder';
  $('folderPill').title = S.source || '';
  $('picker').hidden = !S.pickerOpen;
  $('settings').hidden = !S.settingsOpen;

  if (S.pickerOpen) {
    $('recents').innerHTML = S.recents.length
      ? S.recents.map((r, i) =>
        `<button class="rec${r.path === S.source ? ' current' : ''}" data-rec="${i}">
           <span class="p">${esc(r.label)}</span><span class="grow"></span>
           <span class="note">${r.path === S.source ? 'current' : ''}</span>
         </button>`).join('')
      : `<div class="rec" style="opacity:.5">No recent folders yet</div>`;
    $('recents').querySelectorAll('[data-rec]').forEach((b) => {
      b.onclick = () => { S.pickerOpen = false; setSource(S.recents[+b.dataset.rec].path); };
    });
  }
  if (S.settingsOpen) {
    const rows = [
      ['confirmBeforeApply', 'Confirm before apply', 'Show a summary dialog'],
      ['showLineNumbers', 'Line numbers in diff', ''],
      ['backup', 'Backup before in-place', 'Keeps a .rebrandx-backup copy'],
      ['copyIgnored', 'Copy ignored files too', 'Include .git, node_modules in a copy'],
    ];
    $('settingsRows').innerHTML = rows.map(([k, l, h]) => toggleHTML(k, l, h, S.settings[k], false, 'set')).join('');
    bindToggles($('settingsRows'), (k) => {
      S.settings[k] = !S.settings[k];
      call('config.set', { settings: S.settings });
      if (k === 'showLineNumbers') renderDiff();
      renderHeader();
      if (k === 'copyIgnored') renderStatus();
    });
  }
}

function toggleHTML(key, label, hint, on, disabled, ns) {
  return `<button class="trow${disabled ? ' off' : ''}" data-${ns || 'tg'}="${key}">
    <span class="tl"><span class="t1">${esc(label)}</span>${hint ? `<span class="t2">${esc(hint)}</span>` : ''}</span>
    <span class="sw${on ? ' on' : ''}"><i></i></span>
  </button>`;
}
function bindToggles(root, fn, ns) {
  root.querySelectorAll(`[data-${ns || 'tg'}]`).forEach((b) => {
    b.onclick = () => fn(b.dataset[ns === 'set' ? 'set' : (ns || 'tg')]);
  });
}

function renderToolbar() {
  $('modeInplace').className = S.mode === 'inplace' ? 'on' : '';
  $('modeCopy').className = S.mode === 'copy' ? 'on' : '';
  $('destWrap').hidden = S.mode !== 'copy';
  if (document.activeElement !== $('destInput')) $('destInput').value = S.dest;
  $('dryPill').hidden = !S.dryRun;
  $('applyBtn').hidden = S.applied;
  $('appliedWrap').hidden = !S.applied;
  $('applyBtn').textContent = S.dryRun ? 'Run dry run' : 'Apply rebrand';
  const nothing = !S.find || (S.useRegex && S.regexError) ||
    (!S.totals.filesChanged && !S.totals.renames);
  $('applyBtn').disabled = !!nothing || S.busy;
}

function renderRules() {
  if (document.activeElement !== $('findInput')) $('findInput').value = S.find;
  if (document.activeElement !== $('replInput')) $('replInput').value = S.replace;
  $('findInput').placeholder = S.useRegex ? 'Regex pattern' : 'Find';

  $('chips').innerHTML = S.regexError
    ? `<span class="chip bad">invalid regex</span>`
    : S.chips.map((c) => `<span class="chip">${esc(c)}</span>`).join('');

  $('toggles').innerHTML = [
    ['matchVariants', 'Match case variants', 'name · Name · NAME', S.useRegex || !S.caseSensitive],
    ['renameFiles', 'Rename files & folders', 'Apply rules to paths too', false],
    ['stripMeta', 'Remove old repo lines', 'Delete links to the old remote', false],
    ['stripProjectFiles', 'Remove old project files',
     'LICENSE, CHANGELOG, .github… — see Advanced', false],
  ].map(([k, l, h, d]) => toggleHTML(k, l, h, S[k], d)).join('');

  const gh = $('ghBtn');
  gh.className = 'quick' + (S.stripProjectFiles ? ' on' : '');
  gh.innerHTML = (S.stripProjectFiles ? 'Removing GitHub &amp; licence files' : 'Remove GitHub &amp; licence files')
    + (S.stripProjectFiles && S.totals.dropped ? `<span class="n">${S.totals.dropped}</span>` : '');
  gh.title = S.stripProjectFiles
    ? 'Click to keep them. Edit the exact list under Advanced.'
    : 'Deletes .github/, LICENSE, CHANGELOG, CONTRIBUTING, AUTHORS, SECURITY and similar. Backed up, and revertible.';

  $('advArrow').innerHTML = S.advOpen ? '&#9662;' : '&#9656;';
  $('advPanel').hidden = !S.advOpen;
  if (S.advOpen) {
    $('advToggles').innerHTML = [
      ['caseSensitive', 'Case sensitive', 'Match exactly as typed', false],
      ['useRegex', 'Regex find', 'Pattern match, $1 groups in replace', false],
      ['replaceContents', 'Replace inside contents', 'Rewrite matching lines', false],
      ['dryRun', 'Dry-run mode', 'Simulate — nothing is written', false],
    ].map(([k, l, h, d]) => toggleHTML(k, l, h, S[k], d)).join('');
    bindToggles($('advToggles'), onToggle);

    const keys = Object.keys(S.excludes);
    $('flags').innerHTML = keys.map((k) =>
      `<button class="flag${S.excludes[k] ? '' : ' off'}" data-flag="${esc(k)}"
        title="${S.excludes[k] ? 'Ignored by the scan — click to include' : 'Included — click to ignore'}"
        >${S.excludes[k] ? '⚑ ' : ''}${esc(k)}</button>`).join('') +
      `<button class="flag add" id="addFlag" title="Add an ignore pattern">+</button>`;
    $('flags').querySelectorAll('[data-flag]').forEach((b) => {
      b.onclick = () => { const k = b.dataset.flag; S.excludes[k] = !S.excludes[k]; invalidate(); };
    });
    $('addFlag').onclick = addFlag;
    renderProjectGlobs();
  }
  bindToggles($('toggles'), onToggle);
}

function renderProjectGlobs() {
  const host = $('projGlobs');
  if (!host) return;
  host.hidden = !S.stripProjectFiles;
  if (!S.stripProjectFiles) return;
  const keys = Object.keys(S.projectGlobs);
  host.innerHTML =
    `<div class="lbl" style="padding:10px 0 4px">Files to delete</div>
     <div class="flags">` +
    keys.map((k) => `<button class="flag${S.projectGlobs[k] ? ' del' : ' off'}"
        data-pglob="${esc(k)}"
        title="${S.projectGlobs[k] ? 'Will be deleted — click to keep' : 'Kept — click to delete'}"
        >${S.projectGlobs[k] ? '✕ ' : ''}${esc(k)}</button>`).join('') +
    `<button class="flag add" id="addPGlob" title="Add a pattern to delete">+</button></div>`;
  host.querySelectorAll('[data-pglob]').forEach((b) => {
    b.onclick = () => { const k = b.dataset.pglob; S.projectGlobs[k] = !S.projectGlobs[k]; invalidate(); };
  });
  $('addPGlob').onclick = () => showDialog({
    title: 'Delete which files?',
    body: `<div class="b">Anything matching this pattern is deleted when
      "Remove old project files" is on. Use <code>docs/</code> for a folder
      or <code>*.bak</code> for a glob.</div>
      <input class="inp" id="pgInput" style="width:100%" placeholder="NOTICE*" spellcheck="false">`,
    confirm: 'Add',
    onConfirm: () => {
      const v = ($('pgInput').value || '').trim();
      if (v) { S.projectGlobs[v] = true; invalidate(); }
    },
    onOpen: () => $('pgInput').focus(),
  });
}

function onToggle(k) {
  S[k] = !S[k];
  invalidate();
}

function addFlag() {
  showDialog({
    title: 'Ignore pattern',
    body: `<div class="b">Files and folders matching this pattern are skipped entirely.
      Use <code>build/</code> for a folder or <code>*.png</code> for a glob.</div>
      <input class="inp" id="flagInput" style="width:100%" placeholder="dist/" spellcheck="false">`,
    confirm: 'Add',
    onConfirm: () => {
      const v = ($('flagInput').value || '').trim();
      if (v) { S.excludes[v] = true; invalidate(); }
    },
    onOpen: () => $('flagInput').focus(),
  });
}

function renderFiles() {
  $('filesLabel').textContent = 'Files · ' + S.totals.filesChanged + ' changed';
  const host = $('fileList');
  if (S.scanError) {
    host.innerHTML = `<div style="padding:12px 10px;font-size:12px;color:var(--danger)">${esc(S.scanError)}</div>`;
    return;
  }
  if (!S.entries.length) {
    host.innerHTML = `<div style="padding:12px 10px;font-size:12px;color:var(--text-subtle)">${
      !S.source ? 'No folder picked yet' : S.scanning ? 'Scanning…' : 'Empty folder'}</div>`;
    return;
  }
  const MAX_ROWS = 1500;
  const shown = S.entries.length > MAX_ROWS ? S.entries.slice(0, MAX_ROWS) : S.entries;
  const frag = [];
  for (const e of shown) {
    const skipped = S.skippedFiles.has(e.path);
    const drop = !!e.drop;
    const changed = !!(e.count || e.removed || e.renamed || drop);
    const dim = e.excluded || skipped;
    const sel = S.selected === e.path;
    const pickable = !e.dir && !e.excluded && !drop;
    const badge = (e.count || 0) + (e.removed || 0);
    const newName = e.renamed ? e.newPath.split('/').pop() : '';
    // The engine flags a rename that would produce a name Windows will not
    // accept. On Windows it lands on a corrected name instead; everywhere
    // else the file is written as asked but would not survive the trip.
    const wtitle = e.winWarn ? `\n${newName} ${e.winWarn} on Windows` : '';
    frag.push(
      `<button class="frow${e.dir ? ' isdir' : ''}${sel ? ' sel' : ''}${dim ? ' dim' : ''}${drop ? ' drop' : ''}${pickable ? '' : ' nosel'}"
         data-path="${esc(e.path)}" data-pick="${pickable ? 1 : 0}"
         style="${e.depth ? 'margin-left:' + e.depth * 16 + 'px;' : ''}"
         title="${esc(e.path)}${e.binary ? ' (binary — contents left alone)' : ''}${e.tooBig ? ' (too large to scan)' : ''}${esc(wtitle)}">
        <span class="ico">${e.dir ? '▸' : '·'}</span>
        <span class="nm${(e.renamed || drop) && !S.applied ? ' struck' : ''}">${esc(e.path.split('/').pop())}</span>
        ${e.renamed && !drop && !S.applied ? `<span class="newnm">→ ${esc(newName)}</span>` : ''}
        ${e.winWarn && !drop && !S.applied ? `<span class="winwarn" title="${esc(newName)} ${esc(e.winWarn)} on Windows">⚠</span>` : ''}
        <span class="grow"></span>
        ${drop && !S.applied ? `<span class="badge del">delete</span>` : ''}
        ${badge && !drop ? `<span class="badge${S.applied ? ' done' : ''}">${badge}</span>` : ''}
        ${changed && !S.applied && !e.excluded
          ? `<span class="skipbtn${skipped ? ' shown' : ''}" data-skip="${esc(e.path)}"
               title="${drop ? (skipped ? 'Marked for deletion again' : 'Keep this file')
                             : (skipped ? 'Restore changes to this file' : 'Skip this file')}"
               >${skipped ? '↺' : '✕'}</span>`
          : ''}
      </button>`);
  }
  if (shown.length < S.entries.length) {
    frag.push(`<div style="padding:10px;font-size:11px;color:var(--text-subtle);
      font-family:var(--mono)">…${S.entries.length - shown.length} more not listed
      (showing the first ${MAX_ROWS})</div>`);
  }
  host.innerHTML = frag.join('');
  host.querySelectorAll('.frow').forEach((b) => {
    b.onclick = (ev) => {
      if (ev.target.dataset.skip !== undefined) return;
      if (b.dataset.pick !== '1') return;
      S.selected = b.dataset.path; S.diff = null;
      render(); loadDiff(S.selected);
    };
  });
  host.querySelectorAll('[data-skip]').forEach((s) => {
    s.onclick = (ev) => {
      ev.stopPropagation();
      const p = s.dataset.skip;
      S.skippedFiles.has(p) ? S.skippedFiles.delete(p) : S.skippedFiles.add(p);
      invalidate({ now: true });
    };
  });
}

function renderDiff() {
  const host = $('diffCol');
  const d = S.diff;
  if (!S.source) {
    host.innerHTML = `<div class="empty"><div class="card">
      <div class="glyph">⌂</div>
      <div class="t">Pick a folder to rebrand</div>
      <div class="d">Nothing is opened for you — choose the folder you want to
        work on, then enter the name to find and the name to replace it with.</div>
      <button class="cta" id="emptyBrowse" style="align-self:center;margin-top:6px">
        Choose a folder…</button></div></div>`;
    const b = $('emptyBrowse'); if (b) b.onclick = () => $('browseBtn').click();
    return;
  }
  if (!S.find) {
    host.innerHTML = `<div class="empty"><div class="card">
      <div class="glyph">▤</div>
      <div class="t">Enter a name to find</div>
      <div class="d">Type the old name and the new one on the left.
        Nothing is scanned until you do.</div></div></div>`;
    return;
  }
  const selEntry = S.entries.find((e) => e.path === S.selected);
  if (selEntry && selEntry.drop) {
    host.innerHTML = `<div class="empty"><div class="card">
      <div class="glyph" style="color:var(--danger)">✕</div>
      <div class="t">This file will be deleted</div>
      <div class="d"><code>${esc(selEntry.path)}</code> belongs to the old
        project rather than its code. It is backed up first, and Revert puts
        it back.<br><br>Click the ✕ beside it in the list to keep it.</div>
      </div></div>`;
    return;
  }
  if (!S.selected || !d) {
    host.innerHTML = `<div class="empty"><div class="card">
      <div class="glyph">▤</div>
      <div class="t">No file selected</div>
      <div class="d">Pick a file on the left to preview its changes.
        Skip any line you want to keep as-is.</div></div></div>`;
    return;
  }
  if (d.binary || d.tooBig) {
    host.innerHTML = diffHeadHTML(d) + `<div class="empty"><div class="card">
      <div class="glyph">${d.binary ? '◈' : '☷'}</div>
      <div class="t">${d.binary ? 'Binary file' : 'File too large'}</div>
      <div class="d">${d.binary
        ? 'Contents are copied through untouched.'
        : 'Over the 2&nbsp;MB scan limit — contents are copied through untouched.'}
        ${d.renamed ? '<br>It will still be renamed.' : ''}</div></div></div>`;
    return;
  }
  const nums = S.settings.showLineNumbers;
  const rows = d.rows.map((r) => {
    const n = nums ? String(r.i + 1) : '';
    if (r.kind === 'same') {
      return `<div class="ln"><span class="n">${n}</span><span class="t">${esc(r.text) || '&nbsp;'}</span></div>`;
    }
    const key = S.selected + '::' + r.i;
    const skip = S.skippedLines.has(key);
    const removed = r.new === null;
    return `<div class="pair${skip ? ' skipped' : ''}">
      <div class="old"><span class="n">−</span><span class="t">${esc(r.old) || '&nbsp;'}</span>
        <span class="grow"></span>
        <button class="skippill" data-line="${r.i}">${skip ? 'restore' : 'skip'}</button></div>
      ${!removed ? `<div class="new"><span class="n">+</span><span class="t">${esc(r.new) || '&nbsp;'}</span></div>` : ''}
      ${removed ? `<div class="note"><span class="n">×</span><span class="t">line removed — old repo reference</span></div>` : ''}
    </div>`;
  }).join('');
  host.innerHTML = diffHeadHTML(d) + `<div class="dbody">${rows}</div>`;
  host.querySelectorAll('[data-line]').forEach((b) => {
    b.onclick = () => {
      const key = S.selected + '::' + b.dataset.line;
      S.skippedLines.has(key) ? S.skippedLines.delete(key) : S.skippedLines.add(key);
      invalidate({ now: true });
    };
  });
}

function diffHeadHTML(d) {
  const n = (d.count || 0) + (d.removed || 0);
  const entry = S.entries.find((e) => e.path === d.path);
  const warn = entry && entry.winWarn;
  return `<div class="dhead">
    <div class="p">${esc(d.path)}</div>
    ${d.renamed && !S.applied ? `<div class="np">→ ${esc(d.newPath)}</div>` : ''}
    ${warn && !S.applied ? `<div class="np winwarn">⚠ ${esc(warn)} on Windows${
      S.platform === 'windows' ? ' — it will be adjusted' : ''}</div>` : ''}
    <span class="grow"></span>
    <div class="stat">${S.applied ? 'applied' : plural(n, 'change')}</div>
  </div>`;
}

function renderStatus() {
  $('sFiles').textContent = S.totals.filesChanged;
  $('sRepl').textContent = S.totals.replacements;
  $('sRen').textContent = S.totals.renames;
  $('sRem').textContent = S.totals.removed;
  $('sDrop').textContent = S.totals.dropped || 0;
  $('sDrop').parentElement.hidden = !S.stripProjectFiles;
  const warn = $('sWarn');
  warn.hidden = !S.truncated;
  if (S.truncated) warn.textContent = '⚠ tree truncated — folder too large';
  let mode;
  if (!S.source) mode = 'No folder picked';
  else if (S.scanning) mode = 'Scanning…';
  else if (S.applied) mode = 'Done · ' + (S.mode === 'copy' ? (S.appliedInfo?.destLabel || S.dest) : 'in place');
  else mode = (S.dryRun ? 'Dry run · ' : 'Preview · ') +
    (S.mode === 'copy' ? 'copy → ' + (S.dest || 'choose a destination') : 'in place');
  $('sMode').textContent = mode;
  $('app').classList.toggle('busy', S.busy);
}

/* --------------------------------------------------------------- actions */
function setSource(path) {
  S.source = path;
  S.selected = null; S.diff = null;
  S.skippedFiles.clear(); S.skippedLines.clear();
  S.applied = false; S.appliedInfo = null;
  call('config.remember', { path }).then((r) => { S.recents = r; renderHeader(); });
  suggestDest(true);
  invalidate({ now: true });
}

async function suggestDest(force) {
  if (S.mode !== 'copy') return;
  if (S.destTouched && !force) return;
  if (!S.source) return;
  const d = await call('suggest.dest', {
    source: S.source, find: S.find, replace: S.replace,
    caseSensitive: S.caseSensitive, matchVariants: S.matchVariants,
  });
  if (!S.destTouched || force) { S.dest = d; S.destTouched = false; renderToolbar(); renderStatus(); }
}

function summaryText() {
  const t = S.totals;
  return `${plural(t.filesChanged, 'file')} (${t.replacements} replacements, ` +
    `${t.renames} renames, ${t.removed} removed lines` +
    (t.dropped ? `, ${t.dropped} files deleted` : '') + ')';
}

async function doApply() {
  if (S.dryRun) {
    toast(`Dry run: ${summaryText()} would be ` +
      (S.mode === 'copy' ? 'copied to ' + S.dest : 'rewritten in place') + '. Nothing written.', 'info');
    return;
  }
  if (S.mode === 'copy' && !S.dest) { toast('Choose a destination folder first.', 'error'); return; }

  const ignored = Object.keys(S.excludes).filter((k) => S.excludes[k]);
  const note = S.mode === 'copy'
    ? `copied into <b>${esc(S.dest)}</b>` +
      (ignored.length && !S.settings.copyIgnored
        ? `. Ignored paths (${esc(ignored.join(', '))}) are <em>not copied</em>` : '')
    : `rewritten in place inside <b>${esc(S.sourceLabel)}</b>` +
      (S.settings.backup ? ' (a .rebrandx-backup copy is kept)' : ' <em>with no backup</em>');

  const del = S.totals.dropped
    ? `<br><br><b>${plural(S.totals.dropped, 'file')} will be deleted</b> ` +
      (S.mode === 'copy' ? '(simply not copied across).'
        : S.settings.backup ? '— backed up first, and Revert restores them.'
        : '— <em>with no backup</em>.')
    : '';
  const go = () => runApply();
  if (!S.settings.confirmBeforeApply) return go();
  showDialog({
    title: 'Apply rebrand?',
    body: `<div class="b">${summaryText()} will be ${note}.${del} You can revert afterwards.</div>`,
    confirm: 'Rebrand',
    onConfirm: go,
  });
}

async function runApply() {
  S.busy = true; renderStatus(); renderToolbar();
  showProgress();
  try {
    const r = await call('apply', {
      source: S.source, opts: optsPayload(), mode: S.mode, dest: S.dest,
      backup: S.settings.backup, copyIgnored: S.settings.copyIgnored,
    });
    S.applied = true; S.appliedInfo = r;
    closeDialog();
    toast(`Rebranded ${plural(r.files, 'file')} ` +
      (S.mode === 'copy' ? '→ ' + r.destLabel : 'in place') + '.',
      'success', S.mode === 'copy' ? { label: 'Open', fn: () => call('open.folder', { path: r.dest }) } : null);
  } catch (e) {
    closeDialog();
    toast(e.message, 'error');
  } finally {
    S.busy = false; render();
  }
}

async function doRevert() {
  S.busy = true; renderStatus();
  try {
    const r = await call('revert', {});
    S.applied = false; S.appliedInfo = null;
    toast(r.message, 'info');
    invalidate({ now: true });
  } catch (e) {
    toast(e.message, 'error');
  } finally { S.busy = false; render(); }
}

/* --------------------------------------------------------------- overlays */
let dialogState = null;
function showDialog({ title, body, confirm, onConfirm, onOpen }) {
  closePops();
  dialogState = { onConfirm };
  $('overlay').innerHTML = `<div class="scrim"><div class="dialog">
    <div class="h">${esc(title)}</div>${body}
    <div class="row">
      <button class="ghost" id="dlgCancel">Cancel</button>
      <button class="cta" id="dlgOk">${esc(confirm)}</button>
    </div></div></div>`;
  $('dlgCancel').onclick = closeDialog;
  $('dlgOk').onclick = () => { const f = dialogState && dialogState.onConfirm; closeDialog(); f && f(); };
  if (onOpen) onOpen();
}
function showProgress() {
  closePops();
  $('overlay').innerHTML = `<div class="scrim"><div class="dialog">
    <div class="h">Rebranding…</div>
    <div class="b" id="progPath" style="font-family:var(--mono);font-size:11.5px;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Starting…</div>
    <div class="bar"><i id="progBar"></i></div></div></div>`;
}
function closeDialog() { dialogState = null; $('overlay').innerHTML = ''; }

let toastTimer = null;
function toast(msg, kind, action) {
  clearTimeout(toastTimer);
  $('toastHost').innerHTML = `<div class="toast ${kind || 'success'}"><i></i>
    <span style="flex:1">${esc(msg)}</span>
    ${action ? `<button class="ghost" id="toastAct" style="padding:4px 10px;font-size:11.5px">${esc(action.label)}</button>` : ''}
  </div>`;
  if (action) $('toastAct').onclick = () => { action.fn(); };
  toastTimer = setTimeout(() => ($('toastHost').innerHTML = ''), 5200);
}

/* ------------------------------------------------------------ wiring */
function bind() {
  // window controls
  $('btnMin').onclick = () => call('window.minimize');
  $('btnMax').onclick = toggleMax;
  $('btnClose').onclick = () => call('window.close');

  $('hdr').addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('button,input,.pop')) return;
    if (S.pickerOpen || S.settingsOpen) { closePops(); return; }
    if (HAS_WEBKIT) call('window.drag', { x: e.screenX, y: e.screenY });
  });
  $('hdr').addEventListener('dblclick', (e) => {
    if (e.target.closest('button,input,.pop')) return;
    toggleMax();
  });
  document.querySelectorAll('.edge').forEach((el) => {
    if (!HAS_WEBKIT) { el.style.display = 'none'; return; }  // WebView2 resizes natively
    el.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      call('window.resize', { edge: el.dataset.edge, x: e.screenX, y: e.screenY });
    });
  });

  // popovers
  $('folderPill').onclick = (e) => {
    e.stopPropagation();
    S.pickerOpen = !S.pickerOpen; S.settingsOpen = false; renderHeader();
  };
  $('gearBtn').onclick = (e) => {
    e.stopPropagation();
    S.settingsOpen = !S.settingsOpen; S.pickerOpen = false; renderHeader();
  };
  document.addEventListener('pointerdown', (e) => {
    if (!S.pickerOpen && !S.settingsOpen) return;
    if (e.target.closest('.pop')) return;                  // working inside one
    if (e.target.closest('#folderPill,#gearBtn')) return;  // their own toggles
    closePops();
  }, true);
  // Anything that steals focus (the native folder chooser, another window,
  // the app being minimised) should leave no menu hanging behind it.
  window.addEventListener('blur', closePops);
  document.addEventListener('visibilitychange', () => { if (document.hidden) closePops(); });
  $('browseBtn').onclick = async () => {
    S.pickerOpen = false; renderHeader();
    const r = await call('pick.folder', { title: 'Choose the folder to rebrand', start: S.source });
    if (r && r.path) { S.recents = r.recents; setSource(r.path); }
  };

  // rules
  $('findInput').oninput = (e) => { S.find = e.target.value; suggestDest(); invalidate(); };
  $('replInput').oninput = (e) => { S.replace = e.target.value; suggestDest(); invalidate(); };
  $('destInput').oninput = (e) => { S.dest = e.target.value; S.destTouched = true; renderStatus(); renderToolbar(); };
  $('destPick').onclick = async () => {
    const r = await call('pick.folder', { title: 'Choose the destination folder',
      start: S.dest || S.source, createFolders: true, remember: false });
    if (r && r.path) { S.dest = r.label || r.path; S.destTouched = true; renderToolbar(); renderStatus(); }
  };

  $('ghBtn').onclick = () => {
    S.stripProjectFiles = !S.stripProjectFiles;
    if (S.stripProjectFiles) {
      // re-arm every pattern, so a previous "keep this one" doesn't linger
      Object.keys(S.projectGlobs).forEach((k) => { S.projectGlobs[k] = true; });
    }
    invalidate({ now: true });
  };
  $('advBtn').onclick = () => { S.advOpen = !S.advOpen; renderRules(); };
  $('presetBtn').onclick = () => {
    Object.assign(S, {
      caseSensitive: true, matchVariants: true, useRegex: false,
      renameFiles: true, replaceContents: true, stripMeta: true,
      stripProjectFiles: true, mode: 'copy',
    });
    suggestDest(true); invalidate({ now: true });
  };

  $('modeInplace').onclick = () => { S.mode = 'inplace'; invalidate(); };
  $('modeCopy').onclick = () => { S.mode = 'copy'; suggestDest(); invalidate(); };
  $('applyBtn').onclick = doApply;
  $('revertBtn').onclick = doRevert;

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if ($('overlay').innerHTML) return closeDialog();
      if (S.pickerOpen || S.settingsOpen) { S.pickerOpen = S.settingsOpen = false; renderHeader(); }
    }
    if (e.key === 'Enter' && dialogState) {
      const ok = $('dlgOk'); if (ok) ok.click();
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'o') { e.preventDefault(); $('browseBtn').click(); }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); if (!$('applyBtn').disabled) doApply(); }
    if ((e.ctrlKey || e.metaKey) && e.key === 'q') call('window.close');
  });
}

let maxed = false;
async function toggleMax() {
  maxed = await call('window.maximize');
  $('app').classList.toggle('maxed', !!maxed);
}

/* ------------------------------------------------------------------ boot */
on('boot', (p) => {
  S.home = p.home;
  S.platform = p.platform || '';
  S.sep = p.sep || '/';
  S.recents = p.recents || [];
  S.settings = Object.assign(S.settings, p.settings || {});
  S.excludes = Object.assign({}, p.defaults.excludes);
  S.projectGlobs = Object.assign({}, p.defaults.projectGlobs || {});
  $('findInput').focus();
  if (p.source) { S.source = p.source; S.sourceLabel = p.sourceLabel; setSource(p.source); }
  render();
});
on('open-folder', (p) => setSource(p.path));
on('progress', (p) => {
  const bar = $('progBar'), path = $('progPath');
  if (!bar) return;
  bar.style.width = (p.total ? Math.round((p.i / p.total) * 100) : 0) + '%';
  path.textContent = p.path;
});

function boot() {
  bind();
  render();
  if (HAS_WEBKIT) return;                 // GTK shell pushes 'boot' itself
  window.addEventListener('pywebviewready', pullBoot);
  if (window.pywebview && window.pywebview.api) pullBoot();
}

function pullBoot() {
  if (boot._done) return;
  boot._done = true;
  window.pywebview.api.boot().then((p) => window.__rbx_event('boot', p));
}

boot();
