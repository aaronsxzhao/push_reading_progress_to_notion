const { test } = require('node:test');
const assert = require('node:assert/strict');
const C = require('../src/core');
const SOURCE = '11111111111111111111111111111111';
const PAGE = '22222222222222222222222222222222';
const PAGE2 = '33333333333333333333333333333333';
const BLOCK = '44444444444444444444444444444444';
const rt = text => [{ type: 'text', text: { content: text }, plain_text: text }];
const paragraph = (text, id = BLOCK) => ({ id, type: 'paragraph', paragraph: { rich_text: rt(text) }, has_children: false });
const page = (id = PAGE, extras = {}) => ({ id, last_edited_time: '2026-10-24T01:00:00.000Z', properties: { Title: { type: 'title', title: rt('测试书') }, Author: { type: 'rich_text', rich_text: rt('测试作者') }, Source: { type: 'multi_select', multi_select: [{ name: 'WeRead' }] } }, ...extras });
const listing = results => ({ results, has_more: false, next_cursor: null });
const book = () => C.describePage(page());
const rendered = text => C.renderBlocks([paragraph(text)]);

class MemoryIO {
  constructor() { this.data = new Map(); this.dirs = new Set(); this.writes = []; }
  files() { return [...this.data.keys()].map(path => ({ path })); }
  exists(path) { return this.data.has(path) || this.dirs.has(path); }
  async read(path) { if (!this.data.has(path)) throw Error('missing'); return this.data.get(path); }
  async create(path, data) { if (this.exists(path)) throw Error('exists'); this.data.set(path, data); this.writes.push(path); }
  async process(path, fn) { this.data.set(path, fn(await this.read(path))); this.writes.push(path); }
  async mkdir(path) { this.dirs.add(path); }
  async rename(from, to, expected) {
    if (this.exists(to)) throw new C.SyncError('occupied', 'exists');
    if (await this.read(from) !== expected) throw new C.SyncError('concurrent', 'changed');
    this.data.set(to, this.data.get(from)); this.data.delete(from); this.writes.push(to);
  }
  move(from, to) {
    for (const [path, content] of [...this.data]) if (path.startsWith(from + '/')) { this.data.delete(path); this.data.set(to + path.slice(from.length), content); }
    this.dirs.delete(from); this.dirs.add(to);
  }
}
async function initialized() {
  const io = new MemoryIO(); const store = new C.ExcerptStore(io, SOURCE);
  const root = await store.initialize('微信读书自动摘录');
  return { io, store, root };
}
function readerFor(handler, options = {}) {
  return new C.NotionReader({ token: 'synthetic-test-token', interval: 0, wait: async () => {}, request: async args => ({ status: 200, json: await handler(args), headers: {} }), ...options });
}

test('Notion URL parsing ignores the view ID', () => {
  assert.equal(C.cleanId(`https://www.notion.so/Books-${PAGE}?v=${PAGE2}`), PAGE);
  assert.equal(C.cleanId('not a page'), '');
});
test('reject absolute, traversal, hidden or empty output paths', () => {
  for (const path of ['../notes', '/tmp/notes', '.obsidian', 'a/../b', 'a//b', '']) assert.throws(() => C.relativePath(path));
  assert.equal(C.relativePath('阅读/微信读书自动摘录'), '阅读/微信读书自动摘录');
});
test('first import, repeat, source edit and note deletion converge without duplicates', async () => {
  const { io, store, root } = await initialized(); const b = book();
  assert.equal(await store.write(root, b, rendered('第一条')), 'created');
  const n = io.writes.length;
  assert.equal(await store.write(root, b, rendered('第一条')), 'unchanged');
  assert.equal(io.writes.length, n);
  assert.equal(await store.write(root, b, rendered('第二条')), 'updated');
  assert.equal(await store.write(root, b, C.renderBlocks([])), 'updated');
  const files = await store.index(root);
  assert.equal(files.length, 1);
  assert.match(files[0].body, /当前没有摘录正文/);
  assert.doesNotMatch(files[0].body, /第一条|第二条/);
});
test('timestamp-only changes do not trigger iCloud writes', async () => {
  const { io, store, root } = await initialized(); const b = book();
  await store.write(root, b, rendered('正文')); const n = io.writes.length;
  assert.equal(await store.write(root, { ...b, edited: '2026-10-25T01:00:00.000Z' }, rendered('正文')), 'unchanged');
  assert.equal(io.writes.length, n);
});
test('empty books create no empty automatic notes', async () => {
  const { store, root } = await initialized();
  assert.equal(await store.write(root, book(), C.renderBlocks([])), 'empty');
  assert.equal((await store.index(root)).length, 0);
});
test('moving the whole folder is discovered on a second device and no old directory is recreated', async () => {
  const { io, store, root } = await initialized();
  await store.write(root, book(), rendered('原文'));
  io.move(root, '阅读/微信读书自动摘录');
  const second = new C.ExcerptStore(io, SOURCE);
  const moved = await second.resolveFolder();
  assert.equal(moved, '阅读/微信读书自动摘录');
  assert.equal(await second.write(moved, book(), rendered('更新')), 'updated');
  assert.equal((await second.index(moved)).length, 1);
  assert.equal(io.exists(root), false);
});
test('missing marker pauses; does not silently recreate folder', async () => {
  const { io, store, root } = await initialized(); io.data.delete(root + '/' + C.MARKER_NAME);
  const n = io.writes.length;
  await assert.rejects(store.resolveFolder(), { code: 'folder_missing' });
  await assert.rejects(store.write(root, book(), rendered('new')), { code: 'folder_changed' });
  assert.equal(io.writes.length, n);
});
test('copied folder requires explicit choice and leaves other copy untouched', async () => {
  const { io, store, root } = await initialized();
  await store.write(root, book(), rendered('原文'));
  for (const [path, text] of [...io.data]) io.data.set('副本/' + path, text);
  await assert.rejects(store.resolveFolder(), e => e.code === 'folder_duplicate' && e.paths.length === 2);
  assert.equal(await store.resolveFolder(root), root);
  const copy = await io.read('副本/' + root + '/' + C.bookFilename(book()));
  await store.write(root, book(), rendered('更新'));
  assert.equal(await io.read('副本/' + root + '/' + C.bookFilename(book())), copy);
});
test('personal notes in, below and outside output folder remain byte-for-byte untouched', async () => {
  const { io, store, root } = await initialized();
  const own = [root + '/我的心得.md', root + '/子目录/【自动摘录】自己的.md', '个人/测试书.md'];
  for (const name of own) await io.create(name, '我自己写的\n\n<!-- not plugin owned -->');
  await store.write(root, book(), rendered('一')); await store.write(root, book(), rendered('二'));
  for (const name of own) assert.equal(await io.read(name), '我自己写的\n\n<!-- not plugin owned -->');
});
test('same target filename owned by the user is never overwritten', async () => {
  const { io, store, root } = await initialized(); const path = root + '/' + C.bookFilename(book());
  await io.create(path, '我的笔记');
  await assert.rejects(store.write(root, book(), rendered('自动内容')), { code: 'occupied' });
  assert.equal(await io.read(path), '我的笔记');
});
test('manually edited automatic note is protected', async () => {
  const { io, store, root } = await initialized(); await store.write(root, book(), rendered('原文'));
  const path = root + '/' + C.bookFilename(book()); io.data.set(path, await io.read(path) + '\n手写补充');
  await assert.rejects(store.write(root, book(), rendered('更新')), { code: 'manual_edit' });
  assert.match(await io.read(path), /手写补充/);
});
test('source title change updates existing note without creating a renamed duplicate', async () => {
  const { store, root } = await initialized(); const b = book();
  await store.write(root, b, rendered('原文'));
  assert.equal(await store.write(root, { ...b, title: '新书名' }, rendered('原文')), 'updated');
  const files = await store.index(root); assert.equal(files.length, 1); assert.equal(files[0].path, root + '/【自动摘录】新书名.md');
});
test('duplicate managed note stops updates to both copies', async () => {
  const { io, store, root } = await initialized(); await store.write(root, book(), rendered('原文'));
  await io.create(root + '/副本.md', await io.read(root + '/' + C.bookFilename(book())));
  await assert.rejects(store.write(root, book(), rendered('新内容')), { code: 'file_duplicate' });
});
test('second device importing same source is idempotent', async () => {
  const { io, store, root } = await initialized(); const second = new C.ExcerptStore(io, SOURCE);
  await store.write(root, book(), rendered('原文'));
  assert.equal(await second.write(await second.resolveFolder(), book(), rendered('原文')), 'unchanged');
  assert.equal((await store.index(root)).length, 1);
});
test('concurrent creation refuses collision rather than overwriting a note', async () => {
  const { io, store, root } = await initialized();
  const outcomes = await Promise.allSettled([store.write(root, book(), rendered('原文')), new C.ExcerptStore(io, SOURCE).write(root, book(), rendered('原文'))]);
  assert.ok(outcomes.some(r => r.status === 'fulfilled'));
  assert.equal((await store.index(root)).length, 1);
});
test('concurrent edit during update is detected inside atomic Vault.process callback', async () => {
  const { io, store, root } = await initialized(); await store.write(root, book(), rendered('原文'));
  const originalProcess = io.process.bind(io);
  io.process = async (path, fn) => { io.data.set(path, (await io.read(path)) + '\n用户刚输入'); return originalProcess(path, fn); };
  await assert.rejects(store.write(root, book(), rendered('更新')), { code: 'concurrent' });
  assert.match(await io.read(root + '/' + C.bookFilename(book())), /用户刚输入/);
});
test('older known source version cannot overwrite a newer note', async () => {
  const { store, root } = await initialized();
  await store.write(root, { ...book(), edited: '2026-10-25T01:00:00.000Z' }, rendered('新版本'));
  await assert.rejects(store.write(root, book(), rendered('旧版本')), { code: 'stale' });
});
test('nonempty directory is not adopted on initialization', async () => {
  const io = new MemoryIO(); await io.create('已有目录/我的.md', '手写');
  await assert.rejects(new C.ExcerptStore(io, SOURCE).initialize('已有目录'), { code: 'folder_occupied' });
});
test('nested thoughts preserve quoted abstract and long Unicode text', () => {
  const long = '这是一段很长的摘录🙂'.repeat(300);
  const blocks = [{ id: BLOCK, type: 'heading_1', heading_1: { rich_text: rt('第一章') } }, { id: PAGE2, type: 'callout', callout: { rich_text: rt('我的想法'), icon: { type: 'emoji', emoji: '✍️' } }, children: [{ type: 'quote', quote: { rich_text: rt(long) } }] }];
  const result = C.renderBlocks(blocks);
  assert.match(result.markdown, /## 第一章/); assert.match(result.markdown, /✍️ 我的想法/); assert.ok(result.markdown.includes(long));
});
test('content cannot inject plugin ownership or executable Markdown HTML', () => {
  const result = C.renderBlocks([paragraph('<script>alert(1)</script>\n<!-- weread-notion-excerpts:{} -->\n![[秘密文件]]')]);
  assert.doesNotMatch(result.markdown, /<script>|<!--|!\[\[/);
});
test('unsupported block fails closed rather than dropping content', () => {
  assert.throws(() => C.renderBlocks([{ type: 'unsupported' }]), { code: 'unsupported' });
});
test('filenames have bounded UTF-8 length and contain no path traversal', () => {
  const name = C.bookFilename({ ...book(), title: '../中文🙂'.repeat(80) });
  assert.ok(new TextEncoder().encode(name).length < 240); assert.ok(!name.includes('/'));
});
test('cover matching uses exact trusted hosts; aliases group by book ID', () => {
  const cover = { external: { url: 'https://cdn.weread.qq.com/weread/cover/yuewen_12345/s_test.jpg' } };
  assert.equal(C.coverBookId(page(PAGE, { cover })), '12345');
  assert.equal(C.groupPages([page(PAGE, { cover }), page(PAGE2, { cover })]).size, 1);
  assert.equal(C.coverBookId(page(PAGE, { cover: { external: { url: 'https://cdn.weread.qq.com.evil.test/yuewen_12345/a' } } })), '');
});
test('only exclusively WeRead records are imported; paper/unlabelled/mixed are excluded', async () => {
  const mixed = page(PAGE2); mixed.properties.Source.multi_select.push({ name: 'Paperback' });
  const other = page(BLOCK); other.properties.Source.multi_select = [];
  const result = await readerFor(() => listing([page(), mixed, other])).pages(SOURCE);
  assert.deepEqual(result.map(p => p.id), [PAGE]);
});
test('all pages and nested child pages are retrieved', async () => {
  const reader = readerFor(args => {
    if (args.url.includes('/blocks/' + PAGE + '/children')) {
      if (args.url.includes('start_cursor')) return listing([paragraph('第二页', PAGE2)]);
      return { results: [{ id: BLOCK, type: 'callout', callout: { rich_text: rt('想法') }, has_children: true }], has_more: true, next_cursor: 'next-page' };
    }
    if (args.url.includes('/blocks/' + BLOCK)) return listing([{ id: SOURCE, type: 'quote', quote: { rich_text: rt('原文') } }]);
    throw Error('unexpected');
  });
  const tree = await reader.tree(PAGE); const result = C.renderBlocks(tree);
  assert.match(result.markdown, /想法/); assert.match(result.markdown, /原文/); assert.match(result.markdown, /第二页/);
});
test('pagination failure cannot partially update an existing file', async () => {
  const { io, store, root } = await initialized(); await store.write(root, book(), rendered('保留原文'));
  const before = new Map(io.data);
  const reader = readerFor(args => {
    if (args.url.includes('/pages/')) return page();
    if (args.url.includes('start_cursor')) throw Error('offline');
    return { results: [paragraph('半份内容')], has_more: true, next_cursor: 'next' };
  });
  await assert.rejects((async () => { const { book: b, rendered: r } = await reader.readBook(page()); await store.write(root, b, r); })(), { code: 'network' });
  assert.deepEqual(io.data, before);
});
test('pagination cycles and duplicate block IDs fail closed', async () => {
  const reader = readerFor(() => ({ results: [paragraph('x')], has_more: true, next_cursor: 'same' }));
  await assert.rejects(reader.tree(PAGE), { code: 'pagination' });
});
test('page being edited during a fetch is not written', async () => {
  let times = 0;
  const reader = readerFor(args => args.url.includes('/pages/') ? page(PAGE, { last_edited_time: String(++times) }) : listing([paragraph('原文')]));
  await assert.rejects(reader.readBook(page()), { code: 'changed' });
});
test('page whose source changes mid-read is rejected', async () => {
  let times = 0;
  const reader = readerFor(args => {
    if (!args.url.includes('/pages/')) return listing([paragraph('x')]);
    const result = page(); if (++times > 1) result.properties.Source.multi_select = [{ name: 'Paperback' }]; return result;
  });
  await assert.rejects(reader.readBook(page()), { code: 'changed' });
});
test('Notion 429 observes Retry-After and then retries', async () => {
  let times = 0; const waits = [];
  const reader = readerFor(() => null, { wait: async ms => waits.push(ms), request: async () => ++times === 1 ? { status: 429, headers: { 'retry-after': '2' } } : { status: 200, json: listing([]) } });
  await reader.tree(PAGE); assert.equal(times, 2); assert.ok(waits.includes(2000));
});
test('permissions failures expose no credential or raw server payload', async () => {
  const reader = readerFor(() => null, { request: async () => ({ status: 403, json: { secret: 'do-not-display' } }) });
  await assert.rejects(reader.tree(PAGE), e => e.code === 'auth' && !e.message.includes('do-not-display'));
});
test('credentials are sent only to fixed Notion API host and only read/query methods', async () => {
  const calls = [];
  const reader = readerFor(args => { calls.push(args); return listing([]); });
  await reader.pages(SOURCE); await reader.tree(PAGE);
  for (const call of calls) {
    assert.equal(new URL(call.url).hostname, 'api.notion.com');
    assert.ok(call.method === 'GET' || (call.method === 'POST' && call.url.endsWith('/query')));
  }
  await assert.rejects(reader.api('https://evil.test'), { code: 'endpoint' });
});
test('data source ID and single-source database URL both resolve', async () => {
  const calls = [];
  const reader = readerFor(args => { calls.push(args.url); return { id: SOURCE, properties: { Source: { type: 'multi_select' } } }; });
  assert.equal(await reader.resolveSource(SOURCE), SOURCE);
  const databaseReader = readerFor(() => null, { request: async args => {
    if (args.url.endsWith('/data_sources/' + PAGE)) return { status: 404 };
    if (args.url.endsWith('/databases/' + PAGE)) return { status: 200, json: { data_sources: [{ id: SOURCE }] } };
    return { status: 200, json: { id: SOURCE, properties: { Source: { type: 'multi_select' } } } };
  } });
  assert.equal(await databaseReader.resolveSource(`https://notion.so/${PAGE}`), SOURCE);
});
test('mobile/background cancellation prevents further API requests', async () => {
  let calls = 0;
  const reader = readerFor(() => { calls++; return listing([]); }, { check: () => { throw new C.SyncError('cancelled', 'paused'); } });
  await assert.rejects(reader.tree(PAGE), { code: 'cancelled' }); assert.equal(calls, 0);
});

module.exports = { MemoryIO, SOURCE, PAGE, page, paragraph, rendered, listing };

function alias(id, title, explicit = false) {
  const p = page(id, { cover: { external: { url: 'https://cdn.weread.qq.com/cover/YueWen_123/image.jpg' } } });
  p.properties.Title.title = rt(title);
  if (explicit) p.properties['WeRead Book ID'] = { type: 'rich_text', rich_text: rt('123') };
  return p;
}
test('explicit book IDs survive cover and title changes, including imported books', () => {
  const p = alias(PAGE, '新书名', true); p.cover = null;
  p.properties['WeRead Book ID'].rich_text = rt('CB_uploaded-123');
  assert.equal(C.describePage(p).bookKey, 'weread-CB_uploaded-123');
  p.properties['WeRead Book ID'].rich_text = rt('invalid id');
  assert.throws(() => C.describePage(p), { code: 'identity' });
});
test('same ID with three titles merges all unique excerpts into one note without a choice', async () => {
  const pages = [alias(PAGE, '新书名', true), alias(PAGE2, '旧书名'), alias(SOURCE, '更旧书名')];
  const texts = { [PAGE]: ['共同划线', '新想法'], [PAGE2]: ['共同划线', '旧页独有想法'], [SOURCE]: [] };
  const reader = readerFor(args => {
    const id = args.url.split('/')[5];
    return args.url.includes('/pages/') ? pages.find(p => p.id === id) : listing(texts[id].map((t, i) => paragraph(t, BLOCK.slice(0, 31) + i)));
  });
  const groups = C.groupPages(pages); assert.equal(groups.size, 1);
  const result = await reader.readGroup([...groups.values()][0]);
  assert.equal(result.book.title, '新书名');
  assert.equal(result.rendered.markdown.match(/共同划线/g).length, 1);
  assert.match(result.rendered.markdown, /旧页独有想法/);
  const { store, root } = await initialized();
  await store.write(root, result.book, result.rendered);
  await store.write(root, result.book, result.rendered);
  assert.equal((await store.index(root)).length, 1);
});
test('failure reading any duplicate source prevents replacing the existing excerpts', async () => {
  const pages = [alias(PAGE, 'A'), alias(PAGE2, 'B')];
  const reader = readerFor(args => {
    if (args.url.includes(PAGE2)) throw new C.SyncError('network', 'offline');
    return args.url.includes('/pages/') ? pages[0] : listing([paragraph('部分内容')]);
  });
  await assert.rejects(reader.readGroup([...C.groupPages(pages).values()][0]), { code: 'network' });
});
test('canonical migration reuses an old page-based note without creating a second file', async () => {
  const { store, root } = await initialized();
  await store.write(root, book(), rendered('原始内容'));
  await store.write(root, { ...C.describePage(alias(PAGE2, '新名字', true)), sourcePageIds: [PAGE, PAGE2] }, rendered('合并内容'));
  const files = await store.index(root);
  assert.equal(files.length, 1); assert.match(files[0].body, /合并内容/);
});
test('same title with different book IDs remains two separate books', () => {
  const a = alias(PAGE, '同名书', true), b = alias(PAGE2, '同名书', true);
  b.properties['WeRead Book ID'].rich_text = rt('456');
  assert.equal(C.groupPages([a, b]).size, 2);
});
test('single-source rendering preserves intentional repeated paragraphs', async () => {
  const p = alias(PAGE, 'A');
  const reader = readerFor(args => args.url.includes('/pages/') ? p : listing([paragraph('重复', BLOCK), paragraph('重复', PAGE2)]));
  const result = await reader.readGroup([...C.groupPages([p]).values()][0]);
  assert.equal(result.rendered.markdown.match(/重复/g).length, 2);
});

async function legacyNote(io, root, b = book()) {
  const path = root + '/【自动摘录】' + b.title + '--' + b.pageId + '.md';
  const body = '# 【自动摘录】' + b.title + '\n\n' + C.bookBody(b, rendered('原文'));
  const text = await C.packManaged(body, { sourceId: SOURCE, pageId: b.pageId, bookKey: b.bookKey, sourceEdited: b.edited });
  await io.create(path, text);
  return { path, text };
}
test('legacy ID filename and duplicate heading migrate once without duplicating notes', async () => {
  const { io, store, root } = await initialized(); const old = await legacyNote(io, root);
  assert.equal(await store.write(root, book(), rendered('原文')), 'updated');
  assert.equal(io.exists(old.path), false);
  const notes = await store.index(root); assert.equal(notes.length, 1);
  assert.equal(notes[0].path, root + '/【自动摘录】测试书.md');
  assert.doesNotMatch(notes[0].body, /^# 【自动摘录】/m);
  assert.equal(notes[0].meta.pageId, PAGE); assert.equal(notes[0].meta.bookKey, book().bookKey);
  assert.equal(await store.write(root, book(), rendered('原文')), 'unchanged');
});
test('legacy migration preserves manually edited notes and conflicting personal filenames', async () => {
  const { io, store, root } = await initialized(); const old = await legacyNote(io, root);
  const target = root + '/' + C.bookFilename(book());
  await io.create(target, '我的笔记');
  await assert.rejects(store.write(root, book(), rendered('新原文')), { code: 'occupied' });
  assert.equal(await io.read(old.path), old.text); assert.equal(await io.read(target), '我的笔记');
  io.data.delete(target); io.data.set(old.path, old.text + '手写内容');
  await assert.rejects(store.write(root, book(), rendered('新原文')), { code: 'manual_edit' });
  assert.equal(io.exists(target), false); assert.equal(await io.read(old.path), old.text + '手写内容');
});
test('edit arriving before migration rename is preserved', async () => {
  const { io, store, root } = await initialized(); const old = await legacyNote(io, root);
  const rename = io.rename.bind(io);
  io.rename = async (...args) => { io.data.set(old.path, old.text + '刚写的'); return rename(...args); };
  await assert.rejects(store.write(root, book(), rendered('新原文')), { code: 'concurrent' });
  assert.equal(await io.read(old.path), old.text + '刚写的');
  assert.equal(io.exists(root + '/' + C.bookFilename(book())), false);
});
test('different IDs with identical filenames never overwrite or merge each other', async () => {
  const { io, store, root } = await initialized(); await store.write(root, book(), rendered('第一本'));
  const before = await io.read(root + '/' + C.bookFilename(book()));
  await assert.rejects(store.write(root, C.describePage(page(PAGE2)), rendered('第二本')), { code: 'occupied' });
  assert.equal(await io.read(root + '/' + C.bookFilename(book())), before);
});
