#!/usr/bin/env node
// Debian side of page-open, page-click, page-type, page-shot, page-wait, page-eval and page-close.
// Drives the signed-in phone Chrome (Chrome Beta on the hidden screen "web", debug port 127.0.0.1:9335)
// over the DevTools protocol. page-open opens a new tab and remembers it; the other commands act on that tab.
//
//   node page.cjs open URL [WAIT_MS]
//   node page.cjs click 'TEXT or CSS SELECTOR'
//   node page.cjs type 'SELECTOR or LABEL' 'WORDS' [--enter]
//   node page.cjs shot OUT.png [--full]
//   node page.cjs wait 'TEXT' [TIMEOUT_MS]
//   node page.cjs eval 'JAVASCRIPT'
//   node page.cjs close
// Exit 0 when it worked, 1 when the page said no (not found, timed out, script error), 2 for wrong use.
'use strict';
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const PORT = process.env.CDP_PORT || 9335;
const BASE = 'http://127.0.0.1:' + PORT;
const TAB_FILE = process.env.PAGE_TAB_FILE || (process.env.HARNESS_STATE_DIR
  ? path.join(process.env.HARNESS_STATE_DIR, 'browser-tab') : '/root/.cache/harness-page/tab');
const UP = '/root/hidden-operator/web/phone-chrome.sh';
const USAGE = {
  open: "usage: page-open URL [WAIT_MS]",
  click: "usage: page-click 'TEXT or CSS SELECTOR'",
  type: "usage: page-type 'SELECTOR or LABEL' 'WORDS' [--enter]",
  shot: 'usage: page-shot OUT.png [--full]',
  wait: "usage: page-wait 'TEXT' [TIMEOUT_MS]",
  eval: "usage: page-eval 'JAVASCRIPT'",
  close: 'usage: page-close',
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
class Said extends Error { constructor(message, code) { super(message); this.code = code; } }
const usage = (verb) => { throw new Said(USAGE[verb] || 'usage: page.cjs open|click|type|shot|wait|eval|close ...', 2); };

function loadWs() {
  if (globalThis.WebSocket) return globalThis.WebSocket;
  for (const where of [undefined, '/root/.play/node_modules/ws', '/root/mbc-analytics/node_modules/ws']) {
    try { return where ? require(where) : require('ws'); } catch (e) { /* next */ }
  }
  throw new Said('The node module ws is missing on the Debian side.', 1);
}

async function getJson(p) {
  const c = new AbortController(); const t = setTimeout(() => c.abort(), 8000);
  try { const r = await fetch(BASE + p, { signal: c.signal }); return await r.json(); } finally { clearTimeout(t); }
}

function connect(url) {
  const WebSocket = loadWs();
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url); let id = 0; const pending = {};
    const timer = setTimeout(() => reject(new Said('the tab did not answer its debug socket in 8 s.', 1)), 8000);
    ws.onopen = () => {
      clearTimeout(timer);
      ws.onmessage = (event) => {
        const m = JSON.parse(event.data);
        if (m.id && pending[m.id]) { pending[m.id](m); delete pending[m.id]; }
      };
      const send = (method, params = {}, ms = 30000) => new Promise((ok, no) => {
        const i = ++id; const t = setTimeout(() => { delete pending[i]; no(new Said(method + ' timed out after ' + ms / 1000 + ' s.', 1)); }, ms);
        pending[i] = (m) => { clearTimeout(t); m.error ? no(new Said(method + ': ' + m.error.message, 1)) : ok(m.result); };
        ws.send(JSON.stringify({ id: i, method, params }));
      });
      resolve({ ws, send });
    };
    ws.onerror = () => { clearTimeout(timer); reject(new Said('the debug socket would not open.', 1)); };
  });
}

function chromeUp() {
  try { execFileSync('bash', [UP, 'up'], { encoding: 'utf8', timeout: 90000, stdio: ['ignore', 'pipe', 'pipe'] }); }
  catch (e) {
    if (String(e.stdout || '').includes('no debug socket answered as Chrome Beta')) {
      try {
        execFileSync('bash', ['/root/hidden-operator/scripts/hidden_display.sh', 'launch', '-n', 'web', 'com.chrome.beta'],
          { encoding: 'utf8', timeout: 90000, stdio: ['ignore', 'pipe', 'pipe'] });
        execFileSync('bash', [UP, 'up'], { encoding: 'utf8', timeout: 90000, stdio: ['ignore', 'pipe', 'pipe'] });
        return;
      } catch (retry) { e = retry; }
    }
    throw new Said('phone Chrome is not up: ' + ((e.stdout || '') + (e.stderr || '') || e.message).trim(), 1);
  }
}

async function browser() {
  let version = await getJson('/json/version').catch(() => null);
  if (!version) { chromeUp(); version = await getJson('/json/version').catch(() => null); }
  if (!version) throw new Said('no Chrome answered on port ' + PORT + '.', 1);
  return connect(version.webSocketDebuggerUrl);
}

async function currentTab() {
  let id;
  try { id = fs.readFileSync(TAB_FILE, 'utf8').trim(); } catch (e) { throw new Said('No page is open. Run page-open URL first.', 1); }
  let list = await getJson('/json').catch(() => null);
  if (!list) { chromeUp(); list = await getJson('/json').catch(() => []); }
  const tab = list.find((t) => t.id === id);
  if (!tab) throw new Said('The page opened by page-open is gone. Run page-open URL again.', 1);
  try { await fetch(BASE + '/json/activate/' + tab.id); } catch (e) { /* the attach below says if it is dead */ }
  await sleep(200);
  const page = await connect(tab.webSocketDebuggerUrl);
  page.tab = tab;
  return page;
}

async function evaluate(send, expression, ms = 30000) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true, userGesture: true }, ms);
  if (r.exceptionDetails) {
    const ex = r.exceptionDetails.exception;
    throw new Said('script error: ' + ((ex && (ex.description || ex.value)) || r.exceptionDetails.text), 1);
  }
  return r.result.value;
}

async function waitLoaded(send, ms = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const state = await evaluate(send, 'document.readyState', 5000).catch(() => null);
    if (state === 'complete') return;
    await sleep(300);
  }
}

async function where(send) {
  const v = await evaluate(send, 'JSON.stringify([document.title, location.href])', 10000).catch(() => null);
  const [title, url] = v ? JSON.parse(v) : ['', '(the page is changing)'];
  if (url.startsWith('chrome-error:')) {
    const reason = await evaluate(send, 'document.body.innerText').catch(() => 'Chrome error page');
    throw new Said('Chrome could not open the page: ' + reason, 1);
  }
  return 'TITLE: ' + title + '\nURL: ' + url;
}

// Finds one element by CSS selector, else by its words (exact, then contained), among things a person clicks or fills.
const FIND = `(function(query, mode){
  const seen = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  let found = null;
  try { found = Array.from(document.querySelectorAll(query)).find(seen) || null; } catch (e) { found = null; }
  if (!found) {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const q = norm(query);
    const kinds = mode === 'fill'
      ? 'input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select, [contenteditable=""], [contenteditable=true]'
      : 'a, button, input[type=submit], input[type=button], input[type=checkbox], input[type=radio], [role=button], [role=link], [role=tab], [role=menuitem], [role=option], label, summary, [onclick]';
    const words = (el) => {
      const own = [el.innerText, el.value, el.getAttribute('aria-label'), el.getAttribute('title'), el.getAttribute('placeholder'), el.getAttribute('name'), el.id];
      if (el.labels) for (const l of el.labels) own.push(l.innerText);
      const by = el.getAttribute('aria-labelledby'); if (by) for (const id of by.split(/\\s+/)) { const l = document.getElementById(id); if (l) own.push(l.innerText); }
      return own.map(norm).filter(Boolean);
    };
    const all = Array.from(document.querySelectorAll(kinds)).filter(seen);
    found = all.find((el) => words(el).some((w) => w === q)) || all.find((el) => words(el).some((w) => w.includes(q))) || null;
    if (!found && mode !== 'fill') {
      const any = Array.from(document.querySelectorAll('body *')).filter((el) => seen(el) && norm(el.innerText) === q);
      found = any[any.length - 1] || null;
    }
  }
  if (!found) return null;
  if (found.tagName === 'LABEL' && mode === 'fill' && found.control) found = found.control;
  found.scrollIntoView({block: 'center', inline: 'center'});
  window.__harnessTarget = found;
  const r = found.getBoundingClientRect();
  return {tag: found.tagName.toLowerCase(), type: found.type || '', words: (found.innerText || found.value || found.getAttribute('aria-label') || found.name || found.id || '').trim().slice(0, 80),
          x: r.left + r.width / 2, y: r.top + r.height / 2};
})`;

async function find(send, query, mode) {
  const hit = await evaluate(send, FIND + '(' + JSON.stringify(query) + ',' + JSON.stringify(mode) + ')');
  if (!hit) throw new Said('Nothing on the page matches ' + JSON.stringify(query) + '.', 1);
  return hit;
}

const verbs = {
  async open(args) {
    if (args.length < 1 || args.length > 2 || !/^https?:\/\//i.test(args[0])) usage('open');
    const extra = args[1] === undefined ? 2000 : Number(args[1]);
    if (!Number.isInteger(extra) || extra < 0 || extra > 120000) usage('open');
    const b = await browser();
    const made = await b.send('Target.createTarget', { url: args[0] });
    b.ws.close();
    fs.mkdirSync(path.dirname(TAB_FILE), { recursive: true });
    fs.writeFileSync(TAB_FILE, made.targetId + '\n');
    let tab = null;
    for (let i = 0; i < 30 && !tab; i++) { await sleep(300); tab = (await getJson('/json')).find((t) => t.id === made.targetId); }
    if (!tab) throw new Said('the new tab never appeared.', 1);
    const page = await connect(tab.webSocketDebuggerUrl);
    await page.send('Page.enable');
    await waitLoaded(page.send);
    await sleep(extra);
    console.log(await where(page.send));
    page.ws.close();
  },
  async click(args) {
    if (args.length !== 1 || !args[0]) usage('click');
    const page = await currentTab();
    const hit = await find(page.send, args[0], 'click');
    // The on-screen keyboard is closed first and the page settles, so the spot found below is the spot tapped.
    await evaluate(page.send, 'document.activeElement && document.activeElement.blur && document.activeElement.blur(); true');
    await sleep(400);
    const spot = await evaluate(page.send, `(function(){const t=window.__harnessTarget;const r=t.getBoundingClientRect();const x=r.left+r.width/2,y=r.top+r.height/2;
      const at=document.elementFromPoint(x,y);const box=t.control||(t.matches('input[type=checkbox],input[type=radio]')?t:null);
      return {x,y,hits:!!(at&&(at===t||t.contains(at)||at.contains(t))),before:box?box.checked:null};})()`);
    // A real tap at the element's middle, as a finger would. When the tap would land on something else,
    // or a box it should tick did not change, the element's own click() is used.
    let how = 'tap';
    if (spot.hits) {
      for (const type of ['mousePressed', 'mouseReleased']) {
        await page.send('Input.dispatchMouseEvent', { type, x: spot.x, y: spot.y, button: 'left', clickCount: 1 });
      }
      await sleep(300);
      if (spot.before !== null) {
        const after = await evaluate(page.send, '(function(){const t=window.__harnessTarget;const b=t.control||t;return b.checked;})()').catch(() => null);
        if (after === spot.before) { await evaluate(page.send, 'window.__harnessTarget.click(); true'); how = 'click()'; }
      }
    } else {
      await evaluate(page.send, 'window.__harnessTarget.click(); true');
      how = 'click()';
    }
    await sleep(1500);
    await waitLoaded(page.send, 15000);
    console.log('CLICKED ' + hit.tag + (hit.type ? '[' + hit.type + ']' : '') + (hit.words ? ' "' + hit.words + '"' : '') + ' by ' + how);
    console.log(await where(page.send));
    page.ws.close();
  },
  async type(args) {
    const enter = args.includes('--enter');
    args = args.filter((a) => a !== '--enter');
    if (args.length !== 2 || !args[0]) usage('type');
    const page = await currentTab();
    const hit = await find(page.send, args[0], 'fill');
    if (hit.tag === 'select') {
      const chose = await evaluate(page.send, `(function(w){const s=window.__harnessTarget;const o=Array.from(s.options).find(o=>o.text.trim().toLowerCase()===w.toLowerCase()||o.value===w);if(!o)return null;s.value=o.value;s.dispatchEvent(new Event('input',{bubbles:true}));s.dispatchEvent(new Event('change',{bubbles:true}));return o.text;})(${JSON.stringify(args[1])})`);
      if (chose === null) throw new Said('The list has no choice ' + JSON.stringify(args[1]) + '.', 1);
      console.log('CHOSE "' + chose + '" in select');
    } else if (['date', 'time', 'datetime-local', 'month', 'week', 'color', 'range'].includes(hit.type)) {
      // These fields take no typed keys on a phone; their value is set the way the page's own picker sets it.
      const now = await evaluate(page.send, `(function(w){const t=window.__harnessTarget;const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;set.call(t,w);t.dispatchEvent(new Event('input',{bubbles:true}));t.dispatchEvent(new Event('change',{bubbles:true}));return t.value;})(${JSON.stringify(args[1])})`);
      if (now !== args[1]) throw new Said('The ' + hit.type + ' field did not take ' + JSON.stringify(args[1]) + ' (it holds ' + JSON.stringify(now) + ').', 1);
      console.log('SET ' + hit.tag + '[' + hit.type + ']: ' + JSON.stringify(now));
    } else {
      // Text goes in the way the page's own field takes it: the field's value setter, then input and change events.
      // Android's on-screen keyboard is kept out of it; it can add its own words to a focused field.
      const now = await evaluate(page.send, `(function(w){const t=window.__harnessTarget;t.focus();
        if(t.isContentEditable){t.innerText=w;t.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:w}));t.blur();return t.innerText;}
        const proto=t.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto,'value').set.call(t,w);
        t.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:w}));t.dispatchEvent(new Event('change',{bubbles:true}));
        if(!${enter})t.blur();return t.value;})(${JSON.stringify(args[1])})`);
      console.log('TYPED into ' + hit.tag + (hit.type ? '[' + hit.type + ']' : '') + ': ' + JSON.stringify(now));
    }
    if (enter) {
      for (const type of ['keyDown', 'keyUp']) {
        await page.send('Input.dispatchKeyEvent', { type, key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: type === 'keyDown' ? '\r' : undefined });
      }
      await sleep(1500);
      await waitLoaded(page.send, 15000);
      console.log('PRESSED Enter');
      console.log(await where(page.send));
    }
    page.ws.close();
  },
  async shot(args) {
    const full = args.includes('--full');
    args = args.filter((a) => a !== '--full');
    if (args.length !== 1 || !/\.png$/i.test(args[0])) usage('shot');
    const out = path.resolve(args[0]);
    if (!fs.existsSync(path.dirname(out))) throw new Said('The folder ' + path.dirname(out) + ' does not exist.', 2);
    const page = await currentTab();
    await page.send('Page.enable');
    const shot = await page.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: full }, 60000);
    const bytes = Buffer.from(shot.data, 'base64');
    const temp = out + '.part-' + process.pid;
    fs.writeFileSync(temp, bytes); fs.renameSync(temp, out);
    const width = bytes.readUInt32BE(16), height = bytes.readUInt32BE(20);
    console.log(out + '  ' + bytes.length + ' bytes  ' + width + 'x' + height);
    console.log(await where(page.send));
    page.ws.close();
  },
  async wait(args) {
    if (args.length < 1 || args.length > 2 || !args[0]) usage('wait');
    const limit = args[1] === undefined ? 30000 : Number(args[1]);
    if (!Number.isInteger(limit) || limit < 0 || limit > 600000) usage('wait');
    const page = await currentTab();
    const t0 = Date.now();
    const probe = `(document.body ? document.body.innerText : '').includes(${JSON.stringify(args[0])})`;
    while (true) {
      if (await evaluate(page.send, probe, 10000).catch(() => false)) {
        console.log('FOUND ' + JSON.stringify(args[0]) + ' after ' + (Date.now() - t0) + ' ms');
        console.log(await where(page.send));
        page.ws.close();
        return;
      }
      if (Date.now() - t0 >= limit) throw new Said('The text ' + JSON.stringify(args[0]) + ' did not appear in ' + limit + ' ms.', 1);
      await sleep(500);
    }
  },
  async eval(args) {
    if (args.length !== 1 || !args[0].trim()) usage('eval');
    const page = await currentTab();
    const value = await evaluate(page.send, args[0], 60000);
    console.log(value === undefined ? 'undefined' : typeof value === 'string' ? value : JSON.stringify(value));
    page.ws.close();
  },
  async close(args) {
    if (args.length) usage('close');
    let id;
    try { id = fs.readFileSync(TAB_FILE, 'utf8').trim(); } catch (e) { throw new Said('No page is open.', 1); }
    const b = await browser();
    await b.send('Target.closeTarget', { targetId: id }).catch(() => null);
    b.ws.close();
    fs.unlinkSync(TAB_FILE);
    console.log('CLOSED ' + id);
  },
};

(async () => {
  const [verb, ...args] = process.argv.slice(2);
  const timer = setTimeout(() => { console.error('page: gave up after 15 minutes.'); process.exit(1); }, 900000);
  timer.unref();
  try {
    if (!verbs[verb]) usage();
    await verbs[verb](args);
    process.exit(0);
  } catch (e) {
    console.error(e instanceof Said ? e.message : 'page: ' + (e.message || e));
    process.exit(e instanceof Said ? e.code : 1);
  }
})();
