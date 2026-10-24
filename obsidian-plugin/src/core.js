'use strict';

const PLUGIN_ID = 'weread-notion-excerpts';
const MARKER_NAME = '_微信读书同步标识.md';
const FILE_PREFIX = '<!-- weread-notion-excerpts:';
const MARKER_PREFIX = '<!-- weread-notion-folder:';
const API_VERSION = '2025-09-03';

class SyncError extends Error {
  constructor(code, message) { super(message); this.name = 'SyncError'; this.code = code; }
}
const fail = (code, text) => { throw new SyncError(code, text); };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function cleanId(value) {
  const text = String(value || '').trim();
  // A Notion URL may also contain a view UUID. Prefer its final path segment.
  let candidate = text;
  if (/^https?:\/\//i.test(text)) {
    try { candidate = new URL(text).pathname.split('/').pop(); } catch (_) { return ''; }
  }
  const match = candidate.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32}/i);
  return match ? match[0].replace(/-/g, '').toLowerCase() : '';
}
function relativePath(value) {
  const path = String(value || '').trim().replace(/\\/g, '/');
  if (!path || path.startsWith('/') || path.split('/').some(p => !p || p === '.' || p === '..' || p.startsWith('.') || /[:\x00-\x1f]/.test(p))) {
    fail('path', '请输入笔记库内的普通文件夹路径，不能使用绝对路径、隐藏目录或 ..。');
  }
  return path;
}
const parentPath = path => path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
const isUnder = (path, root) => path.startsWith(root + '/');
async function digest(text) {
  if (!globalThis.crypto?.subtle) fail('crypto', '当前环境不支持内容校验，请更新 Obsidian。');
  const bytes = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
}
function commentValue(text, prefix) {
  if (!text.startsWith(prefix)) return null;
  const end = text.indexOf(' -->\n');
  if (end < 0 || end > 8192) return null;
  try { return { meta: JSON.parse(text.slice(prefix.length, end)), body: text.slice(end + 5) }; }
  catch (_) { return null; }
}
function markerText(sourceId) {
  return `${MARKER_PREFIX}${JSON.stringify({ schema: 1, sourceId, folderId: 'notion-' + sourceId })} -->\n# 微信读书同步标识\n\n此文件随整个文件夹一起移动。请勿删除、改名或复制；它用于识别同步目录，不包含访问密钥。\n`;
}
function parseMarker(text) {
  const value = commentValue(text, MARKER_PREFIX)?.meta;
  return value?.schema === 1 && cleanId(value.sourceId) === value.sourceId && value.folderId === 'notion-' + value.sourceId ? value : null;
}
function parseManaged(text) {
  const parsed = commentValue(text, FILE_PREFIX);
  if (!parsed) return null;
  const m = parsed.meta;
  if (m.schema !== 1 || m.owner !== PLUGIN_ID || cleanId(m.pageId) !== m.pageId || cleanId(m.sourceId) !== m.sourceId || !/^([a-f0-9]{64})$/.test(m.bodyHash || '') || typeof m.bookKey !== 'string') return null;
  return parsed;
}
async function packManaged(body, meta) {
  return `${FILE_PREFIX}${JSON.stringify({ schema: 1, owner: PLUGIN_ID, ...meta, bodyHash: await digest(body) })} -->\n${body}`;
}
function plain(rich) { return (rich || []).map(r => r.plain_text ?? r.text?.content ?? r.mention?.page?.id ?? '').join(''); }
function escapeMd(text) {
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/([\\`*_[\]#!|~])/g, '\\$1');
}
function richText(rich) {
  return (rich || []).map(item => {
    let value = escapeMd(item.plain_text ?? item.text?.content ?? '');
    const a = item.annotations || {};
    if (a.code) value = '<code>' + value + '</code>';
    if (a.bold) value = '**' + value + '**';
    if (a.italic) value = '*' + value + '*';
    if (a.strikethrough) value = '~~' + value + '~~';
    const href = item.href || item.text?.link?.url;
    if (href && /^https?:\/\//i.test(href)) value = `[${value}](<${href.replace(/[<>\r\n]/g, '')}>)`;
    return value;
  }).join('');
}
function renderBlocks(blocks, depth = 0) {
  if (depth > 25) fail('depth', 'Notion 内容层级过深，本书暂不导入。');
  let count = 0;
  const parts = [];
  for (const block of blocks) {
    if (block.archived || block.in_trash) continue;
    const type = block.type;
    const data = block[type] || {};
    const text = richText(data.rich_text);
    const nested = renderBlocks(block.children || [], depth + 1);
    count += nested.count;
    let rendered = '';
    const children = nested.markdown ? '\n\n' + nested.markdown : '';
    if (['paragraph', 'heading_1', 'heading_2', 'heading_3', 'callout', 'quote', 'bulleted_list_item', 'numbered_list_item', 'to_do', 'toggle'].includes(type)) {
      if (plain(data.rich_text).trim()) count++;
      if (type.startsWith('heading_')) rendered = '#'.repeat(Number(type.slice(-1)) + 1) + ' ' + text + children;
      else if (type === 'callout' || type === 'quote') {
        const icon = type === 'callout' && data.icon?.type === 'emoji' ? data.icon.emoji + ' ' : '';
        rendered = (icon + text + children).split('\n').map(line => '> ' + line).join('\n');
      } else if (type === 'bulleted_list_item' || type === 'numbered_list_item' || type === 'to_do') {
        const prefix = type === 'to_do' ? `- [${data.checked ? 'x' : ' '}] ` : type === 'numbered_list_item' ? '1. ' : '- ';
        rendered = prefix + text + children.replace(/\n/g, '\n    ');
      } else rendered = text + children;
    } else if (type === 'table_of_contents' || type === 'breadcrumb') continue;
    else if (type === 'divider') rendered = '---';
    else if (type === 'column_list' || type === 'column' || type === 'synced_block') rendered = nested.markdown;
    else if (type === 'code') {
      count++;
      const raw = plain(data.rich_text);
      const fence = '`'.repeat(Math.max(3, ...Array.from(raw.matchAll(/`+/g), m => m[0].length + 1)));
      rendered = fence + '\n' + raw + '\n' + fence;
    } else if (type === 'table') rendered = nested.markdown;
    else if (type === 'table_row') {
      count++;
      // One bullet per row avoids fabricating or dropping a header row.
      rendered = '- ' + (data.cells || []).map(richText).join(' · ');
    } else if (['bookmark', 'link_preview', 'embed', 'image', 'file', 'pdf', 'audio', 'video'].includes(type)) {
      count++;
      const url = data.url || data.external?.url;
      const caption = richText(data.caption) || '附件（在 Notion 原页面查看）';
      rendered = url && /^https?:\/\//i.test(url) ? `[${caption}](<${url.replace(/[<>\r\n]/g, '')}>)` : caption;
    } else if (type === 'equation') { count++; rendered = '$$\n' + data.expression + '\n$$'; }
    else fail('unsupported', `遇到暂不支持的 Notion 内容类型 ${type || 'unknown'}，保留本地旧文件。`);
    if (rendered.trim()) parts.push(rendered);
  }
  return { markdown: parts.join('\n\n'), count };
}
function coverBookId(page) {
  const explicit = plain(page.properties?.['WeRead Book ID']?.rich_text);
  if (explicit) {
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(explicit)) fail('identity', 'WeRead Book ID 无效，本书未更新。');
    return explicit;
  }
  try {
    const url = new URL(page.cover?.external?.url || '');
    if (url.protocol !== 'https:') return '';
    if (url.hostname === 'cdn.weread.qq.com') return url.pathname.match(/\/yuewen_(\d+)\//i)?.[1] || '';
    if (url.hostname === 'wfqqreader-1252317822.image.myqcloud.com') return url.pathname.match(/^\/cover\/\d+\/(\d+)\/t\d+_\1\.jpg$/)?.[1] || '';
  } catch (_) { /* Missing or non-WeRead covers use a Notion page identity. */ }
  return '';
}
function describePage(page) {
  const titleProp = Object.values(page.properties || {}).find(p => p.type === 'title');
  const title = plain(titleProp?.title) || '未命名书籍';
  const author = plain(page.properties?.Author?.rich_text);
  const pageId = cleanId(page.id);
  if (!pageId) fail('page', 'Notion 页面缺少有效 ID。');
  const bookId = coverBookId(page);
  return { pageId, title, author, bookKey: bookId ? 'weread-' + bookId : 'notion-' + pageId, edited: page.last_edited_time || '' };
}
function isWereadPage(page) {
  const values = page.properties?.Source?.multi_select;
  return !page.archived && !page.in_trash && Array.isArray(values) && values.length === 1 && values[0].name === 'WeRead';
}
function bookBody(book, rendered) {
  return `# 【自动摘录】${escapeMd(book.title)}\n\n> 自动同步自 Notion；请将自己的笔记写在其他文件中。\n\n${book.author ? '作者：' + escapeMd(book.author) + '\n\n' : ''}[在 Notion 中查看](https://www.notion.so/${book.pageId})\n\n---\n\n${rendered.markdown || '（Notion 当前没有摘录正文。）'}\n`;
}
function bookFilename(book) {
  let title = book.title.replace(/[\\/:*?"<>|\[\]#^\x00-\x1f\x7f]/g, '_').replace(/[. ]+$/g, '').trim() || '未命名';
  while (new TextEncoder().encode(title).length > 110) title = Array.from(title).slice(0, -1).join('');
  return `【自动摘录】${title}--${book.pageId}.md`;
}

class NotionReader {
  constructor({ request, token, check = () => {}, wait = sleep, now = Date.now, interval = 380 }) {
    this.request = request; this.token = token; this.check = check; this.wait = wait; this.now = now; this.interval = interval; this.lastRequest = 0;
  }
  async api(path, body) {
    if (!/^\/(data_sources|databases|pages|blocks)\/[a-f0-9-]+(\/query|\/children)?(\?[^\s]*)?$/.test(path)) fail('endpoint', '拒绝非预期的 Notion 请求。');
    for (let attempt = 0; attempt < 4; attempt++) {
      this.check();
      await this.wait(Math.max(0, this.lastRequest + this.interval - this.now()));
      this.check(); this.lastRequest = this.now();
      let response;
      try {
        response = await this.request({ url: 'https://api.notion.com/v1' + path, method: body ? 'POST' : 'GET', headers: { Authorization: 'Bearer ' + this.token, 'Notion-Version': API_VERSION, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}), throw: false });
      } catch (_) { fail('network', '无法连接 Notion，请检查网络后重试。'); }
      this.check();
      if (response.status === 429 || response.status >= 500) {
        if (attempt === 3) fail('retry', 'Notion 暂时繁忙，已保留本地内容，请稍后重试。');
        const retry = Number(response.headers?.['retry-after'] || response.headers?.['Retry-After'] || 2 ** attempt);
        if (retry > 30) fail('retry', 'Notion 要求稍后重试，本次同步已暂停。');
        await this.wait(Math.max(1000, retry * 1000));
        continue;
      }
      if (response.status === 401 || response.status === 403) fail('auth', 'Notion 凭据无效或没有读取权限，请检查插件设置和数据库连接。');
      if (response.status === 404) fail('not_found', 'Notion 页面或数据源不可访问，请检查 ID 和读取权限。');
      if (response.status < 200 || response.status >= 300) fail('api', `Notion 返回 ${response.status}，未写入本书。`);
      const data = response.json;
      if (!data || typeof data !== 'object' || data.object === 'error') fail('response', 'Notion 响应不完整。');
      return data;
    }
  }
  async resolveSource(input) {
    const id = cleanId(input);
    if (!id) fail('id', '请输入有效的 Notion 数据源 ID 或数据库链接。');
    let source;
    try { source = await this.api('/data_sources/' + id); }
    catch (error) {
      if (error.code !== 'not_found') throw error;
      const database = await this.api('/databases/' + id);
      if (database.data_sources?.length !== 1) fail('source', '此数据库包含多个数据源，请在 Notion 中复制目标数据源 ID 后填写。');
      const sourceId = cleanId(database.data_sources[0].id);
      if (!sourceId) fail('source', 'Notion 数据库缺少有效数据源。');
      source = await this.api('/data_sources/' + sourceId);
    }
    if (source.properties?.Source?.type !== 'multi_select') fail('schema', '目标数据源需要名为 Source 的多选字段，以便只读取 WeRead 书籍。');
    return cleanId(source.id) || id;
  }
  async paginate(path, queryBody) {
    let cursor;
    const seen = new Set(); const results = []; const ids = new Set();
    do {
      const query = queryBody ? { ...queryBody, page_size: 100, ...(cursor ? { start_cursor: cursor } : {}) } : undefined;
      const url = queryBody ? path : path + '?page_size=100' + (cursor ? '&start_cursor=' + encodeURIComponent(cursor) : '');
      const data = await this.api(url, query);
      if (!Array.isArray(data.results) || typeof data.has_more !== 'boolean') fail('pagination', 'Notion 分页响应不完整，未采用本次结果。');
      for (const item of data.results) {
        if (!item?.id || ids.has(item.id)) fail('pagination', 'Notion 分页内容重复或缺少标识，请稍后重试。');
        ids.add(item.id); results.push(item);
      }
      if (!data.has_more) break;
      cursor = data.next_cursor;
      if (!cursor || seen.has(cursor) || seen.size > 1000) fail('pagination', 'Notion 分页游标异常，未采用本次结果。');
      seen.add(cursor);
    } while (true);
    return results;
  }
  async pages(sourceId) {
    const pages = await this.paginate('/data_sources/' + sourceId + '/query', { filter: { property: 'Source', multi_select: { contains: 'WeRead' } } });
    return pages.filter(isWereadPage);
  }
  async tree(id, depth = 0, budget = { remaining: 20000 }) {
    if (depth > 25) fail('depth', 'Notion 内容层级过深，未写入本书。');
    const blocks = await this.paginate('/blocks/' + cleanId(id) + '/children');
    budget.remaining -= blocks.length;
    if (budget.remaining < 0) fail('size', '单本书超过 20000 个内容块，已暂停以保护设备。');
    for (const block of blocks) {
      if (block.has_children) block.children = await this.tree(block.id, depth + 1, budget);
    }
    return blocks;
  }
  async readBook(page) {
    const id = cleanId(page.id);
    const before = await this.api('/pages/' + id);
    if (!isWereadPage(before)) fail('changed', '此书已归档或来源发生变化，本地文件保持不变。');
    const blocks = await this.tree(id);
    const after = await this.api('/pages/' + id);
    if (!isWereadPage(after) || before.last_edited_time !== after.last_edited_time) fail('changed', 'Notion 正在更新这本书，稍后重新打开或手动同步即可。');
    return { book: describePage(after), rendered: renderBlocks(blocks),
      segments: blocks.map(block => renderBlocks([block])).filter(part => part.markdown.trim()) };
  }
  async readGroup(items) {
    // Fully read every alias before writing: failure cannot erase an older
    // source's unique excerpts. A stable ID groups editions, never title text.
    if (items.length === 1) {
      const result = await this.readBook(items[0].page);
      if (result.book.bookKey !== items[0].book.bookKey) fail('changed', '书籍标识正在变化，已跳过。');
      return result;
    }
    const reads = [];
    for (const item of items) {
      const result = await this.readBook(item.page);
      if (result.book.bookKey !== item.book.bookKey) fail('changed', '书籍标识正在变化，已跳过。');
      reads.push({ ...result, explicit: !!plain(item.page.properties?.['WeRead Book ID']?.rich_text) });
    }
    reads.sort((a, b) => Number(b.explicit) - Number(a.explicit) || b.rendered.count - a.rendered.count || a.book.pageId.localeCompare(b.book.pageId));
    const primary = reads[0];
    const seen = new Set(), parts = [];
    let count = 0;
    for (const result of reads) {
      for (const segment of result.segments) {
        if (result === primary || !seen.has(segment.markdown)) {
          seen.add(segment.markdown); parts.push(segment.markdown); count += segment.count;
        }
      }
    }
    return { book: { ...primary.book, edited: reads.map(r => r.book.edited).sort().at(-1),
      sourcePageIds: reads.map(r => r.book.pageId) }, rendered: { markdown: parts.join('\n\n'), count } };
  }
}

// IO adapter uses Vault APIs in production; the same logic is exercised by tests.
class ExcerptStore {
  constructor(io, sourceId) { this.io = io; this.sourceId = sourceId; }
  async folders() {
    const found = [];
    for (const file of this.io.files()) {
      if (file.path.split('/').pop() !== MARKER_NAME) continue;
      const marker = parseMarker(await this.io.read(file.path));
      if (marker?.sourceId === this.sourceId) found.push(parentPath(file.path));
    }
    return found.sort();
  }
  async resolveFolder(selectedPath) {
    const found = await this.folders();
    if (!found.length) fail('folder_missing', '未找到同步标识，已暂停。请等待 iCloud 同步；不会在旧位置自动重建文件夹。');
    if (found.length === 1) return found[0];
    if (selectedPath && found.includes(selectedPath)) return selectedPath;
    const error = new SyncError('folder_duplicate', '找到多个同步目录，请选择要使用的目录。');
    error.paths = found; throw error;
  }
  async initialize(path) {
    const found = await this.folders();
    if (found.length) return this.resolveFolder();
    path = relativePath(path);
    if (this.io.files().some(f => isUnder(f.path, path))) fail('folder_occupied', '目标目录已有文件，未接管或覆盖。请选择空目录，或等待原同步标识到达。');
    await this.io.mkdir(path);
    const markerPath = path + '/' + MARKER_NAME;
    // A second device may have created the identical marker in the meantime.
    if (this.io.exists(markerPath)) {
      if (parseMarker(await this.io.read(markerPath))?.sourceId !== this.sourceId) fail('marker', '目标位置的同步标识不匹配。');
    } else await this.io.create(markerPath, markerText(this.sourceId));
    return path;
  }
  async index(root) {
    const found = [];
    for (const file of this.io.files()) {
      if (!isUnder(file.path, root) || !file.path.endsWith('.md') || file.path.endsWith('/' + MARKER_NAME)) continue;
      const text = await this.io.read(file.path);
      const parsed = parseManaged(text);
      if (parsed?.meta.sourceId === this.sourceId) found.push({ path: file.path, text, ...parsed });
    }
    return found;
  }
  async write(root, book, rendered) {
    // Recheck the marker before each write: moving/removing a folder mid-run must not recreate it.
    const markerPath = root + '/' + MARKER_NAME;
    if (!this.io.exists(markerPath) || parseMarker(await this.io.read(markerPath))?.sourceId !== this.sourceId) fail('folder_changed', '同步目录已移动或暂不可用，本次停止写入，下次会重新查找。');
    const all = await this.index(root);
    const matches = all.filter(f => f.meta.pageId === book.pageId || f.meta.bookKey === book.bookKey || book.sourcePageIds?.includes(f.meta.pageId));
    if (matches.length > 1) fail('file_duplicate', `《${book.title}》存在多个自动摘录副本，未修改任何副本。`);
    const existing = matches[0];
    if (!existing && rendered.count === 0) return 'empty';
    const body = bookBody(book, rendered);
    const next = await packManaged(body, { sourceId: this.sourceId, pageId: book.pageId, bookKey: book.bookKey, sourceEdited: book.edited });
    if (existing) {
      if (await digest(existing.body) !== existing.meta.bodyHash) fail('manual_edit', `《${book.title}》的自动摘录已被修改，已保留你的内容并跳过。`);
      if (existing.meta.pageId === book.pageId && existing.meta.sourceEdited && book.edited && existing.meta.sourceEdited > book.edited) fail('stale', `《${book.title}》本地来源版本较新，未使用旧数据覆盖。`);
      // Source timestamps alone do not cause iCloud writes.
      if (existing.body === body && existing.meta.pageId === book.pageId) return 'unchanged';
      await this.io.process(existing.path, current => {
        if (current !== existing.text) fail('concurrent', `《${book.title}》在同步期间发生变化，本次未覆盖。`);
        return next;
      });
      return 'updated';
    }
    const path = root + '/' + bookFilename(book);
    if (this.io.exists(path)) fail('occupied', `《${book.title}》的目标文件已经存在，未覆盖。`);
    await this.io.create(path, next);
    return 'created';
  }
}

function groupPages(pages) {
  const groups = new Map();
  for (const page of pages) {
    const book = describePage(page);
    const items = groups.get(book.bookKey) || [];
    items.push({ page, book }); groups.set(book.bookKey, items);
  }
  return groups;
}

module.exports = { PLUGIN_ID, MARKER_NAME, API_VERSION, FILE_PREFIX, SyncError, cleanId, relativePath, parentPath, isUnder, digest, markerText, parseMarker, parseManaged, packManaged, plain, richText, renderBlocks, coverBookId, describePage, isWereadPage, bookBody, bookFilename, NotionReader, ExcerptStore, groupPages, sleep };
