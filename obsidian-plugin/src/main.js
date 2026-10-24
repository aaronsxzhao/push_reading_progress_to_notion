'use strict';
const { Plugin, PluginSettingTab, Setting, Notice, Modal, TFile, TFolder, requestUrl } = require('obsidian');
const Core = require('./core');

const DEFAULTS = { sourceInput: '', sourceId: '', secretName: 'weread-notion-readonly', initialFolder: '微信读书自动摘录', initialized: false, automatic: true, pageChoices: {} };

class ChoiceModal extends Modal {
  constructor(app, title, choices, done) { super(app); this.title = title; this.choices = choices; this.done = done; this.selected = null; }
  onOpen() {
    this.setTitle(this.title);
    this.contentEl.createEl('p', { text: '只选择后续同步的位置或来源，不删除、移动或合并其他内容。关闭窗口则暂停本次同步。' });
    const list = this.contentEl.createDiv({ cls: 'weread-sync-choices' });
    for (const choice of this.choices) {
      const button = list.createEl('button', { text: choice.label });
      button.addEventListener('click', () => { this.selected = choice.value; this.close(); });
    }
  }
  onClose() { this.contentEl.empty(); this.done(this.selected); }
}

class ResultModal extends Modal {
  constructor(app, plugin) { super(app); this.plugin = plugin; }
  onOpen() {
    this.setTitle('微信读书同步结果');
    const summary = this.contentEl.createEl('p');
    const details = this.contentEl.createEl('pre', { cls: 'weread-sync-log' });
    this.unsubscribe = this.plugin.subscribeReport(report => {
      summary.setText(report.summary);
      details.setText((report.details || []).join('\n') || (this.plugin.running ? '正在处理，进度会自动更新。首次导入请保持 Obsidian 打开。' : '没有需要处理的问题。'));
    });
  }
  onClose() { this.unsubscribe?.(); this.contentEl.empty(); }
}

class ExcerptsPlugin extends Plugin {
  async onload() {
    this.settings = { ...DEFAULTS, ...(await this.loadData()) };
    this.settings.pageChoices = { ...(this.settings.pageChoices || {}) };
    this.device = this.app.loadLocalStorage(Core.PLUGIN_ID + '-device') || {};
    this.running = false; this.epoch = 0; this.disposed = false; this.lastStarted = 0;
    this.reportListeners = new Set();
    this.report = { summary: '尚未同步', details: [] };
    this.status = this.addStatusBarItem();
    this.addSettingTab(new ExcerptsSettings(this.app, this));
    this.addCommand({ id: 'sync-now', name: '立即同步 Notion 摘录', callback: () => this.sync(true) });
    this.addCommand({ id: 'show-result', name: '查看同步结果', callback: () => new ResultModal(this.app, this).open() });
    this.addRibbonIcon('refresh-cw', '同步微信读书摘录', () => this.sync(true));
    this.app.workspace.onLayoutReady(() => this.schedule());
    this.registerDomEvent(document, 'visibilitychange', () => {
      if (document.hidden && (!this.runDocument || this.runDocument.hidden)) this.epoch++;
      else this.schedule();
    });
    this.registerDomEvent(window, 'focus', () => this.schedule());
    this.registerEvent(this.app.vault.on('rename', file => {
      // No sync on rename. Only invalidate an in-flight run so old paths cannot be reused.
      if (file instanceof TFolder || file.name === Core.MARKER_NAME) this.epoch++;
    }));
    this.register(() => { this.disposed = true; this.epoch++; window.clearTimeout(this.startTimer); this.reportListeners.clear(); });
  }
  async saveSettings() { await this.saveData(this.settings); }
  saveDevice() { this.app.saveLocalStorage(Core.PLUGIN_ID + '-device', this.device); }
  schedule() {
    if (this.disposed || !this.settings.automatic || !this.settings.initialized || document.hidden) return;
    window.clearTimeout(this.startTimer);
    this.startTimer = window.setTimeout(() => this.sync(false), 1200);
  }
  setReport(summary, details = []) {
    this.report = { summary, details };
    this.status?.setText('微信读书：' + summary);
    for (const listener of this.reportListeners) { try { listener(this.report); } catch (_) { /* A closed settings window must not abort data sync. */ } }
  }
  subscribeReport(listener) {
    this.reportListeners.add(listener);
    listener(this.report);
    return () => this.reportListeners.delete(listener);
  }
  token() {
    if (!this.app.secretStorage) throw new Core.SyncError('version', '请将 Obsidian 升级到 1.11.4 或以上，以使用本机凭据存储。');
    const token = this.app.secretStorage.getSecret(this.settings.secretName);
    if (!token) throw new Core.SyncError('token', '请在此设备的插件设置中保存 Notion 只读凭据。');
    return token;
  }
  reader(check = () => {}) {
    return new Core.NotionReader({ token: this.token(), check, request: async params => {
      let timer;
      try {
        return await Promise.race([
          requestUrl(params),
          new Promise((_, reject) => { timer = window.setTimeout(() => reject(new Error('timeout')), 30000); })
        ]);
      } finally { window.clearTimeout(timer); }
    } });
  }
  io(check = () => {}) {
    const vault = this.app.vault;
    const file = path => {
      const result = vault.getAbstractFileByPath(path);
      if (!(result instanceof TFile)) throw new Core.SyncError('file_missing', '文件暂不可用，等待 iCloud 同步后重试。');
      return result;
    };
    return {
      files: () => vault.getFiles(),
      exists: path => !!vault.getAbstractFileByPath(path),
      read: path => vault.read(file(path)),
      create: (path, data) => { check(); return vault.create(path, data); },
      process: (path, fn) => { check(); return vault.process(file(path), current => { check(); return fn(current); }); },
      rename: async (from, to, expected) => {
        const entry = file(from);
        if (await vault.read(entry) !== expected) throw new Core.SyncError('concurrent', '摘录在重命名前发生变化，已保留原文件。');
        check();
        if (entry.path !== from) throw new Core.SyncError('concurrent', '摘录位置发生变化，本次停止修改。');
        if (vault.getAbstractFileByPath(to)) throw new Core.SyncError('occupied', '目标文件已存在，未重命名或覆盖。');
        // Vault.rename avoids rewriting links in the user's personal notes.
        await vault.rename(entry, to);
      },
      mkdir: async path => {
        let parent = '';
        for (const part of path.split('/')) {
          parent = parent ? parent + '/' + part : part;
          const entry = vault.getAbstractFileByPath(parent);
          if (entry && !(entry instanceof TFolder)) throw new Core.SyncError('occupied', '目录路径被现有文件占用。');
          if (!entry) await vault.createFolder(parent);
        }
      }
    };
  }
  choose(title, choices) { return new Promise(resolve => new ChoiceModal(this.app, title, choices, resolve).open()); }
  async connect() {
    if (this.running) throw new Core.SyncError('running', '请等待当前同步结束后再修改配置。');
    const sourceId = await this.reader().resolveSource(this.settings.sourceInput);
    if (this.settings.initialized && this.settings.sourceId && sourceId !== this.settings.sourceId) {
      throw new Core.SyncError('source_locked', '此插件已绑定另一数据源，不能直接把原摘录改为其他来源。');
    }
    this.settings.sourceId = sourceId;
    this.settings.sourceInput = sourceId;
    await this.saveSettings();
    return new Core.ExcerptStore(this.io(), sourceId);
  }
  async setup(createNew) {
    try {
      const store = await this.connect();
      let root;
      try { root = createNew ? await store.initialize(this.settings.initialFolder) : await store.resolveFolder(); }
      catch (error) {
        if (error.code !== 'folder_duplicate') throw error;
        root = await this.choose('选择已有同步目录', error.paths.map(path => ({ label: path, value: path })));
        if (!root) return;
        this.device.selectedFolder = root; this.saveDevice();
      }
      this.settings.initialized = true;
      await this.saveSettings();
      new Notice('已连接：' + root + '。点击“立即同步”开始导入。');
      this.setReport('已连接，等待首次同步');
    } catch (error) { this.showError(error); }
  }
  showError(error) {
    const message = error instanceof Core.SyncError ? error.message : '操作失败，已停止写入。请检查网络、iCloud 文件状态后重试。';
    this.setReport(message); new Notice(message, 10000);
  }
  async sync(manual = false, ownerDocument = document) {
    if (this.disposed || ownerDocument.hidden) return;
    if (this.running) {
      if (this.epoch !== this.runningEpoch) this.pendingResume = true;
      if (manual) new Notice('同步正在进行：' + this.report.summary, 5000);
      return;
    }
    // Coalesce startup/focus/visibility events, not a recurring timer.
    if (!manual && Date.now() - this.lastStarted < 5000) return;
    if (!this.settings.initialized || !this.settings.sourceId) {
      if (manual) { this.setReport('请先连接 Notion 并创建或识别同步目录。'); new Notice(this.report.summary); }
      return;
    }
    this.running = true; this.lastStarted = Date.now();
    this.runDocument = ownerDocument;
    const onOwnerHidden = () => { if (ownerDocument.hidden) this.epoch++; };
    if (ownerDocument !== document) ownerDocument.addEventListener('visibilitychange', onOwnerHidden);
    this.setReport('正在检查同步目录…');
    if (manual) new Notice('同步已开始，可以在当前设置页或“查看结果”中查看实时进度。', 5000);
    const epoch = this.epoch;
    this.runningEpoch = epoch;
    const check = () => {
      if (this.disposed || ownerDocument.hidden || epoch !== this.epoch) throw new Core.SyncError('cancelled', '同步已暂停；下次打开或手动同步时重新检查。');
    };
    const counts = { created: 0, updated: 0, unchanged: 0, empty: 0, failed: 0 };
    const details = [];
    try {
      const reader = this.reader(check);
      const store = new Core.ExcerptStore(this.io(check), this.settings.sourceId);
      let root;
      try { root = await store.resolveFolder(this.device.selectedFolder); }
      catch (error) {
        if (error.code !== 'folder_duplicate') throw error;
        root = await this.choose('找到多个摘录目录，请选择', error.paths.map(path => ({ label: path, value: path })));
        if (!root) throw new Core.SyncError('cancelled', '未选择同步目录，本次未写入。');
        this.device.selectedFolder = root; this.saveDevice();
      }
      check();
      this.setReport('正在读取 Notion 书目…');
      const pages = await reader.pages(this.settings.sourceId);
      const groups = Core.groupPages(pages);
      const initialFiles = await store.index(root);
      let number = 0;
      for (const [bookKey, items] of groups) {
        check(); number++;
        const item = items[0];
        this.setReport(`正在核对 ${number}/${groups.size}：${item.book.title}`);
        try {
          const { book, rendered } = await reader.readGroup(items);
          check();
          // Fail closed if the page's source identity changed during the read.
          if (book.bookKey !== item.book.bookKey) throw new Core.SyncError('changed', '书籍标识正在变化，已跳过。');
          const outcome = await store.write(root, book, rendered);
          counts[outcome]++;
        } catch (error) {
          if (['cancelled', 'folder_changed', 'auth', 'network', 'retry'].includes(error.code)) throw error;
          counts.failed++;
          details.push(item.book.title + '：' + (error instanceof Core.SyncError ? error.message : '读取或写入失败，未继续处理此书。'));
        }
      }
      check();
      const currentIds = new Set(pages.map(p => Core.cleanId(p.id)));
      const missing = initialFiles.filter(f => !currentIds.has(f.meta.pageId) && !groups.has(f.meta.bookKey));
      if (missing.length) details.push(`${missing.length} 个旧摘录的来源本次未查到，已保留原文件。`);
      const summary = `新增 ${counts.created} 本，更新 ${counts.updated} 本，未变 ${counts.unchanged} 本${counts.failed ? `，跳过 ${counts.failed} 本` : ''}`;
      this.device.lastSuccess = new Date().toISOString(); this.device.lastRoot = root; this.saveDevice();
      this.setReport(summary, details);
      if (manual || counts.created || counts.updated || details.length) new Notice(summary + (details.length ? '。可在命令面板查看同步结果。' : ''), 8000);
    } catch (error) {
      const message = error instanceof Core.SyncError ? error.message : '同步失败，已停止；请检查网络和文件状态后重试。';
      this.setReport(message, [`本轮已新增 ${counts.created} 本、更新 ${counts.updated} 本。`, ...details]);
      if (!this.disposed && !ownerDocument.hidden) new Notice(message, 10000);
    } finally {
      this.running = false;
      this.runDocument = null;
      if (ownerDocument !== document) ownerDocument.removeEventListener('visibilitychange', onOwnerHidden);
      this.setReport(this.report.summary, this.report.details);
      if (this.pendingResume) { this.pendingResume = false; this.lastStarted = 0; this.schedule(); }
    }
  }
}

class ExcerptsSettings extends PluginSettingTab {
  constructor(app, plugin) { super(app, plugin); this.plugin = plugin; }
  hide() { this.unsubscribe?.(); this.unsubscribe = null; }
  display() {
    this.unsubscribe?.();
    const p = this.plugin; const el = this.containerEl; el.empty();
    el.createEl('h2', { text: '微信读书自动摘录' });
    el.createEl('p', { text: 'Mac 和 iPhone 都直接读取 Notion。仅写入带插件标识的自动摘录；自己的笔记请另建文件。凭据每台设备各保存一次。' });
    new Setting(el).setName('Notion 只读凭据（本设备）').setDesc('仅授权读书数据库的 Read content。保存到 Obsidian SecretStorage，不进入 iCloud 笔记或插件 data.json。')
      .addText(text => {
        text.inputEl.type = 'password'; text.inputEl.autocomplete = 'off';
        text.setPlaceholder(p.app.secretStorage?.getSecret(p.settings.secretName) ? '本设备已保存；输入可替换' : '粘贴 Notion integration secret');
        this.tokenInput = text;
      }).addButton(button => button.setButtonText('保存凭据').onClick(() => {
        if (p.running) { new Notice('请等待同步结束后再修改凭据。'); return; }
        const token = this.tokenInput.getValue().trim();
        if (!token) { new Notice('请输入凭据。'); return; }
        if (!p.app.secretStorage) { new Notice('请更新 Obsidian 到 1.11.4 或以上。'); return; }
        p.app.secretStorage.setSecret(p.settings.secretName, token); this.tokenInput.setValue(''); new Notice('已保存到本设备。');
      }));
    new Setting(el).setName('Notion 数据源 ID 或数据库链接').setDesc('书目数据库必须包含 Source 多选字段，微信读书值为 WeRead。绑定后不可直接改成另一个来源。')
      .addText(text => text.setValue(p.settings.sourceInput).setDisabled(p.settings.initialized).onChange(async value => { if (!p.settings.initialized && !p.running) { p.settings.sourceInput = value.trim(); await p.saveSettings(); } }));
    new Setting(el).setName('首次创建目录').setDesc('相对当前笔记库的路径。创建后可以移动整个目录；插件按内部标识重新定位。')
      .addText(text => text.setValue(p.settings.initialFolder).setDisabled(p.settings.initialized).onChange(async value => { if (!p.settings.initialized && !p.running) { p.settings.initialFolder = value; await p.saveSettings(); } }));
    new Setting(el).setName('连接已有目录').setDesc('新设备请先等待 iCloud 同步，再点这里；不会创建新目录。')
      .addButton(button => button.setButtonText('识别已有目录').onClick(async () => { button.setDisabled(true); await p.setup(false); this.display(); }));
    if (!p.settings.initialized) {
      new Setting(el).setName('首次安装：创建目录').setDesc('只在第一台设备使用一次。第二台设备使用“识别已有目录”，避免 iCloud 尚未到达时重复初始化。')
        .addButton(button => button.setButtonText('连接并创建空目录').onClick(async () => { button.setDisabled(true); await p.setup(true); this.display(); }));
    }
    new Setting(el).setName('打开或回到前台时自动检查').setDesc('不进行周期轮询。手机锁屏或退到后台会暂停，下次打开继续核对。')
      .addToggle(toggle => toggle.setValue(p.settings.automatic).onChange(async value => { p.settings.automatic = value; await p.saveSettings(); }));
    let syncButton, stopButton;
    new Setting(el).setName('同步操作')
      .addButton(button => { syncButton = button; button.setButtonText('立即同步').onClick(() => p.sync(true, el.ownerDocument)); })
      .addButton(button => { stopButton = button; button.setButtonText('停止本次同步').onClick(() => { p.epoch++; p.setReport('正在停止，等待当前读取结束…'); new Notice('将在当前读取结束后停止。'); }); })
      .addButton(button => button.setButtonText('查看结果').onClick(() => new ResultModal(p.app, p).open()));
    if (p.device.selectedFolder) {
      new Setting(el).setName('重新选择重复目录').setDesc('仅清除重复目录选择；书籍按微信读书 ID 自动合并，无需选择来源。')
        .addButton(button => button.setButtonText('清除选择').onClick(async () => { if (p.running) { new Notice('请等待同步结束。'); return; } p.settings.pageChoices = {}; delete p.device.selectedFolder; p.saveDevice(); await p.saveSettings(); this.display(); }));
    }
    const progress = el.createEl('p', { cls: 'weread-sync-log', attr: { role: 'status', 'aria-live': 'polite' } });
    this.unsubscribe = p.subscribeReport(report => {
      syncButton.setButtonText(p.running ? '同步中…' : '立即同步').setDisabled(p.running);
      stopButton.setDisabled(!p.running);
      progress.setText(`状态：${report.summary}\n上次完成检查：${p.device.lastSuccess ? new Date(p.device.lastSuccess).toLocaleString() : '尚无'}\n最近目录：${p.device.lastRoot || '尚未同步'}`);
    });
  }
}

module.exports = ExcerptsPlugin;
