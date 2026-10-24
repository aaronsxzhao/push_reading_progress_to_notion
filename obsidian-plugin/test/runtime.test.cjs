const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const C = require('../src/core');
const SOURCE = '11111111111111111111111111111111', PAGE = '22222222222222222222222222222222', BLOCK = '33333333333333333333333333333333';
const root = '微信读书自动摘录';
const rt = text => [{ plain_text: text, text: { content: text } }];

async function harness({ initialized = true, mobile = false, aliases = false, bookCount = 1, empty = false } = {}) {
  const data = new Map([[root + '/' + C.MARKER_NAME, C.markerText(SOURCE)], ['自己的笔记.md', '永久保留']]);
  const notices = [], calls = [], handlers = [], timers = new Map(); let tid = 0, requestsPending = 0, maxConcurrent = 0;
  const changed = new Map(); let failPage = null;
  let content = '测试划线'; let version = '2026-10-22T01:00:00Z';
  const document = { hidden: false };
  class TFile { constructor(path) { this.path = path; this.name = path.split('/').pop(); } }
  class TFolder { constructor(path) { this.path = path; this.name = path.split('/').pop(); } }
  class Plugin {
    async loadData() { return { sourceInput: SOURCE, sourceId: SOURCE, initialized }; }
    async saveData(settings) { this.saved = JSON.parse(JSON.stringify(settings)); }
    addStatusBarItem() { return { setText() {} }; }
    addSettingTab() {}
    addCommand(command) { (this.commands ||= []).push(command); }
    addRibbonIcon() {}
    registerDomEvent(target, event, fn) { handlers.push({ target, event, fn }); }
    registerEvent() {}
    register(fn) { this.disposeFn = fn; }
  }
  const window = {
    setTimeout(fn, ms) { timers.set(++tid, { fn, ms }); return tid; },
    clearTimeout(id) { timers.delete(id); }
  };
  const obsidian = { Plugin, PluginSettingTab: class {}, Setting: class {}, Notice: class { constructor(text) { notices.push(text); } }, Modal: class {}, TFile, TFolder,
    requestUrl: async args => {
      requestsPending++; maxConcurrent = Math.max(maxConcurrent, requestsPending); calls.push(args);
      await Promise.resolve(); requestsPending--;
      const list = results => ({ results, has_more: false, next_cursor: null });
      const page = { id: PAGE, last_edited_time: version, properties: { Title: { type: 'title', title: rt('测试书') }, Source: { type: 'multi_select', multi_select: [{ name: 'WeRead' }] } } };
      if (aliases) page.properties['WeRead Book ID'] = { type: 'rich_text', rich_text: rt('123') };
      const oldPage = { ...page, id: SOURCE, properties: { ...page.properties, Title: { type: 'title', title: rt('旧书名') } } };
      let json;
      if (args.url.endsWith('/query')) {
        const query = JSON.parse(args.body), offset = Number(query.start_cursor || 0);
        const pages = aliases ? [page, oldPage] : Array.from({ length: bookCount }, (_, n) => ({ ...page, id: n ? n.toString(16).padStart(32, '0') : PAGE, last_edited_time: changed.get(n)?.version || version,
          properties: { ...page.properties, Title: { type: 'title', title: rt('测试书' + (n || '')) } } }));
        json = { results: pages.slice(offset, offset + 100), has_more: offset + 100 < pages.length, next_cursor: offset + 100 < pages.length ? String(offset + 100) : null };
      }
      else if (args.url.includes('/pages/')) {
        const id = args.url.split('/').pop(), n = id === PAGE ? 0 : parseInt(id, 16);
        if (id === failPage) return { status: 404, json: {} };
        json = aliases ? (id === SOURCE ? oldPage : page) : { ...page, id, last_edited_time: changed.get(n)?.version || version,
          properties: { ...page.properties, Title: { type: 'title', title: rt('测试书' + (n || '')) } } };
      }
      else if (args.url.includes('/children')) {
        const id = args.url.split('/blocks/')[1].split('/')[0], n = id === PAGE ? 0 : parseInt(id, 16);
        json = list(empty && !changed.has(n) ? [] : [{ id: BLOCK, type: 'paragraph', paragraph: { rich_text: rt(changed.get(n)?.content || content) } }]);
      }
      else throw Error('unexpected');
      return { status: 200, json };
    }
  };
  const app = {
    isMobile: mobile,
    loadLocalStorage: () => null, saveLocalStorage(key, value) { this.localSaved = JSON.parse(JSON.stringify(value)); }, secretStorage: { getSecret: () => 'synthetic-readonly-token' },
    workspace: { onLayoutReady(fn) { this.ready = fn; } },
    vault: {
      getFiles: () => [...data.keys()].map(p => new TFile(p)),
      getAbstractFileByPath: p => data.has(p) ? new TFile(p) : p === root ? new TFolder(p) : null,
      read: async f => data.get(f.path),
      create: async (p, text) => { if (data.has(p)) throw Error('exists'); data.set(p, text); return new TFile(p); },
      process: async (f, fn) => data.set(f.path, fn(data.get(f.path))),
      rename: async (f, to) => { if (data.has(to)) throw Error('exists'); data.set(to, data.get(f.path)); data.delete(f.path); f.path = to; },
      createFolder: async () => {}, on: () => ({})
    }
  };
  // Browser-like VM: no process, Buffer, fs, path, Electron or Node built-ins.
  // The only allowed external module is the real plugin API surface mocked above.
  const module = { exports: {} };
  const context = vm.createContext({ module, require(name) { assert.equal(name, 'obsidian'); return obsidian; }, window, document, crypto: webcrypto, TextEncoder, URL, console,
    setTimeout(fn) { queueMicrotask(fn); return 1; }, clearTimeout() {},
    Date, Map, Set, Promise
  });
  const main = fs.readFileSync(path.join(__dirname, '../src/main.js'), 'utf8');
  const core = fs.readFileSync(path.join(__dirname, '../src/core.js'), 'utf8');
  vm.runInContext(main.replace("const Core = require('./core');", `const Core=(()=>{const module={exports:{}};${core}\nreturn module.exports;})();`), context);
  const plugin = new module.exports(); plugin.app = app; await plugin.onload();
  return { plugin, app, document, window, handlers, timers, notices, calls, data,
    change(text) { content = text; version = '2026-10-23T01:00:00Z'; },
    changeBook(n, text) { changed.set(n, { content: text, version: '2026-10-23T02:00:00Z' }); },
    fail(id) { failPage = id; }, maxConcurrent: () => maxConcurrent,
    async flushOpenTimer() { const entry = [...timers.entries()].find(([, t]) => t.ms === 150); if (entry) { timers.delete(entry[0]); await entry[1].fn(); } }
  };
}

test('desktop plugin end-to-end imports and updates only its managed file', async () => {
  const h = await harness(); await h.plugin.sync(true);
  const managed = [...h.data.keys()].filter(k => k.includes('【自动摘录】')); assert.equal(managed.length, 1);
  assert.match(h.data.get(managed[0]), /测试划线/);
  h.change('修改后的划线'); await h.plugin.sync(true);
  assert.match(h.data.get(managed[0]), /修改后的划线/);
  assert.equal(h.data.get('自己的笔记.md'), '永久保留');
});
test('mobile-like runtime loads and syncs without Node or Electron APIs', async () => {
  const h = await harness({ mobile: true }); await h.plugin.sync(true);
  assert.equal([...h.data.keys()].filter(k => k.includes('【自动摘录】')).length, 1);
  assert.ok(h.calls.length >= 4);
});
test('desktop and mobile automatically consolidate legacy titles without opening a source chooser', async () => {
  for (const mobile of [false, true]) {
    const h = await harness({ mobile, aliases: true });
    h.plugin.choose = () => { throw Error('must not ask which title is the same book'); };
    await h.plugin.sync(true); await h.plugin.sync(true);
    const managed = [...h.data.keys()].filter(k => k.includes('【自动摘录】'));
    assert.equal(managed.length, 1);
    assert.equal(h.data.get(managed[0]).match(/测试划线/g).length, 1);
    assert.match(h.plugin.report.summary, /未变 1 本/);
    assert.equal(h.data.get('自己的笔记.md'), '永久保留');
  }
});
test('startup schedules one debounced sync, without recurring polling', async () => {
  const h = await harness(); h.app.workspace.ready();
  for (const event of h.handlers.filter(x => x.event === 'focus')) event.fn();
  assert.equal([...h.timers.values()].filter(t => t.ms === 150).length, 1);
  await h.flushOpenTimer();
  assert.equal(h.timers.size, 0); assert.ok(h.calls.length);
});
test('iPhone returning to foreground triggers a sync independently of any Mac', async () => {
  const h = await harness({ mobile: true });
  const visibility = h.handlers.find(x => x.event === 'visibilitychange');
  h.document.hidden = true; visibility.fn(); assert.equal(h.timers.size, 0);
  h.document.hidden = false; visibility.fn(); await h.flushOpenTimer();
  assert.ok(h.calls.length); assert.match(h.plugin.report.summary, /新增 1 本/);
});
test('duplicate foreground/manual requests never start parallel runs', async () => {
  const h = await harness(); await Promise.all([h.plugin.sync(true), h.plugin.sync(true), h.plugin.sync(true)]);
  assert.equal(h.maxConcurrent(), 1); assert.equal([...h.data.keys()].filter(k => k.includes('【自动摘录】')).length, 1);
});
test('unconfigured plugin does not request Notion or write files', async () => {
  const h = await harness({ initialized: false }); const before = [...h.data];
  await h.plugin.sync(true); h.app.workspace.ready();
  assert.equal(h.calls.length, 0); assert.deepEqual([...h.data], before); assert.equal(h.timers.size, 0);
});
test('device without secret never requests API or overwrites notes', async () => {
  const h = await harness(); h.app.secretStorage.getSecret = () => null;
  await h.plugin.sync(true); assert.equal(h.calls.length, 0); assert.match(h.plugin.report.summary, /本设备|此设备/);
});
test('turning off auto sync leaves manual command available', async () => {
  const h = await harness(); h.plugin.settings.automatic = false; h.app.workspace.ready();
  assert.equal(h.timers.size, 0); await h.plugin.sync(true); assert.ok(h.calls.length);
});
test('unloading removes timers and stops later writes', async () => {
  const h = await harness(); h.app.workspace.ready(); h.plugin.disposeFn();
  assert.equal(h.timers.size, 0); await h.plugin.sync(true); assert.equal(h.calls.length, 0);
});
test('settings never persist Notion credentials', async () => {
  const h = await harness(); await h.plugin.saveSettings();
  assert.ok(!JSON.stringify(h.plugin.saved).includes('synthetic-readonly-token'));
  assert.equal(h.plugin.saved.secretName, 'weread-notion-readonly');
});

test('manual sync immediately publishes running feedback and completion to live subscribers', async () => {
  const h = await harness(); const updates = [];
  const unsubscribe = h.plugin.subscribeReport(report => updates.push({ text: report.summary, running: h.plugin.running }));
  const pending = h.plugin.sync(true);
  assert.ok(updates.some(r => r.running && /正在检查同步目录/.test(r.text)));
  assert.ok(h.notices.some(text => /同步已开始/.test(text)));
  await pending;
  assert.ok(updates.some(r => /正在核对/.test(r.text)));
  assert.equal(updates.at(-1).running, false);
  assert.match(updates.at(-1).text, /新增 1 本/);
  const length = updates.length; unsubscribe(); h.plugin.setReport('after close'); assert.equal(updates.length, length);
});
test('manual click in visible settings popout works when main document is hidden', async () => {
  const h = await harness(); h.document.hidden = true;
  const registered = new Map();
  const settingsDocument = { hidden: false, addEventListener: (event, fn) => registered.set(event, fn), removeEventListener: event => registered.delete(event) };
  await h.plugin.sync(true, settingsDocument);
  assert.match(h.plugin.report.summary, /新增 1 本/);
  assert.equal(registered.size, 0);
});
test('a second manual click explains that a task is already running', async () => {
  const h = await harness(); const first = h.plugin.sync(true); await h.plugin.sync(true); await first;
  assert.ok(h.notices.some(text => /同步正在进行/.test(text)));
});
test('closing a stale UI subscriber cannot interrupt the synchronization', async () => {
  const h = await harness();
  h.plugin.subscribeReport(() => {});
  h.plugin.reportListeners.add(() => { throw new Error('window closed'); });
  await h.plugin.sync(true); assert.match(h.plugin.report.summary, /新增 1 本/);
});

for (const mobile of [false, true]) test(`legacy note migration uses cross-platform Vault APIs (mobile=${mobile})`, async () => {
  const h = await harness({ mobile }); await h.plugin.sync(true);
  const cleanPath = root + '/【自动摘录】测试书.md';
  const oldPath = root + '/【自动摘录】测试书--' + PAGE + '.md';
  const parsed = C.parseManaged(h.data.get(cleanPath));
  h.data.set(oldPath, await C.packManaged('# 【自动摘录】测试书\n\n' + parsed.body, parsed.meta));
  h.data.delete(cleanPath);
  await h.plugin.sync(true);
  assert.equal(h.data.has(oldPath), false); assert.equal(h.data.has(cleanPath), true);
  assert.doesNotMatch(C.parseManaged(h.data.get(cleanPath)).body, /^# 【自动摘录】/m);
  assert.equal(h.data.get('自己的笔记.md'), '永久保留');
  await h.plugin.sync(true);
  assert.equal([...h.data.keys()].filter(p => p.includes('【自动摘录】')).length, 1);
});

for (const mobile of [false, true]) test(`185 unchanged books need only two listing requests (mobile=${mobile})`, async () => {
  const h = await harness({ mobile, bookCount: 185 }); await h.plugin.sync(true);
  assert.equal(h.calls.length, 557);
  h.calls.length = 0;
  // Simulate loading the persisted device cache after reopening the app.
  h.plugin.device = JSON.parse(JSON.stringify(h.app.localSaved));
  await h.plugin.sync(true);
  assert.equal(h.calls.length, 2); assert.ok(h.calls.every(c => c.url.endsWith('/query')));
  assert.match(h.plugin.report.summary, /未变 185 本；读取正文 0 本，2 次请求/);
  h.changeBook(3, '只更新这一本'); h.calls.length = 0; await h.plugin.sync(true);
  assert.equal(h.calls.length, 5);
  assert.match(h.data.get(root + '/【自动摘录】测试书3.md'), /只更新这一本/);
  assert.match(h.plugin.report.summary, /更新 1 本，未变 184 本/);
});
test('empty books are cached and become notes when their source changes', async () => {
  const h = await harness({ bookCount: 185, empty: true }); await h.plugin.sync(true);
  h.calls.length = 0; await h.plugin.sync(true); assert.equal(h.calls.length, 2);
  h.changeBook(2, '新划线'); h.calls.length = 0; await h.plugin.sync(true);
  assert.equal(h.calls.length, 5); assert.match(h.data.get(root + '/【自动摘录】测试书2.md'), /新划线/);
});
test('cached local deletion is restored and manual edits are never hidden by cache', async () => {
  const h = await harness(); await h.plugin.sync(true);
  const path = root + '/【自动摘录】测试书.md'; h.data.delete(path);
  h.calls.length = 0; await h.plugin.sync(true); assert.equal(h.calls.length, 4); assert.ok(h.data.has(path));
  h.data.set(path, h.data.get(path) + '我的手写');
  await h.plugin.sync(true); assert.match(h.plugin.report.details.join(''), /已被修改/);
  assert.match(h.data.get(path), /我的手写/);
});
test('failed source read is retried instead of being cached as success', async () => {
  const h = await harness(); h.fail(PAGE); await h.plugin.sync(true);
  assert.match(h.plugin.report.summary, /跳过 1 本/);
  h.fail(null); h.calls.length = 0; await h.plugin.sync(true);
  assert.equal(h.calls.length, 4); assert.match(h.plugin.report.summary, /新增 1 本/);
});
test('full verification bypasses cache and cache contains no credentials or excerpts', async () => {
  const h = await harness(); await h.plugin.sync(true);
  const saved = JSON.stringify(h.app.localSaved);
  assert.doesNotMatch(saved, /synthetic-readonly-token|测试划线/);
  h.calls.length = 0; await h.plugin.sync(true, h.document, true); assert.equal(h.calls.length, 4);
  assert.ok(h.plugin.commands.some(c => c.id === 'verify-all'));
});
