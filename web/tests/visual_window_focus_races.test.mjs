import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app.js', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
function actualFunction(name) {
  let start = source.indexOf(`function ${name}(`);
  assert(start >= 0, name);
  if (source.slice(start - 6, start) === 'async ') start -= 6;
  const end = source.indexOf('\n}\n', start);
  assert(end > start, name);
  return source.slice(start, end + 3);
}
const deferred = () => {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return { promise, resolve };
};
const settle = async () => { for (let index = 0; index < 12; index++) await Promise.resolve(); };

// Run actual event binding, tab switching, task fetch, render lifecycle and focus.
// Only transport, pure HTML providers and the small DOM surface are test doubles.
function harness() {
  const requests = [], transcripts = [], timers = [], scrolls = [], allNodes = [];
  const makeNode = (id, surface) => {
    const classes = new Set();
    const node = { dataset: { visualWindow: id }, surface,
      classList: { add: value => classes.add(value), remove: value => classes.delete(value), contains: value => classes.has(value) },
      scrollIntoView: () => scrolls.push(node) };
    allNodes.push(node);
    return node;
  };
  let nodes = ['W001', 'W002'].map(id => makeNode(id, 'old-handout'));
  const buttons = ['W001', 'W002'].map(id => ({ dataset: { switchResultTab: 'transcript', focusVisualWindow: id } }));
  const detail = {};
  Object.defineProperty(detail, 'innerHTML', { set(value) {
    nodes = JSON.parse(value).map(id => makeNode(id, 'transcript'));
  } });
  Object.defineProperty(detail, 'textContent', { set() { nodes = []; } });
  const els = new Proxy({ detail }, { get(target, name) { return target[name] ||= {}; } });
  const document = { body: { dataset: { appView: 'notes' }, classList: { contains: () => false, toggle() {}, remove() {} } }, querySelectorAll(selector) {
    if (selector === '[data-visual-window]') return nodes;
    if (selector === '[data-switch-result-tab]') return buttons;
    return [];
  } };
  const context = vm.createContext({ document, els, selectedTaskId: 'task-a', selectedTab: 'slices', detailRenderGeneration: 0, selectedMaterialId: '', studyViewRequestGeneration: 0, resultViewGeneration: 0,
    RESULT_TAB_NAMES: new Set(['note', 'slices', 'frames', 'transcript']),
    window: { setTimeout(callback, delay) { timers.push({ callback, delay }); } },
    apiUrl: value => value,
    fetch(url) { const pending = deferred(); requests.push({ ...pending, url }); return pending.promise; },
    transcriptForTask(task) { const pending = deferred(); transcripts.push({ ...pending, task }); return pending.promise; },
    renderResultTabState() {}, syncSelectedTaskUrl() {}, syncLayoutForView() {},
    renderLibraryMaterials() {}, clearTaskCaches() {}, syncTaskSelection() {}, focusResultPanelOnMobile() {},
    showSettingsPane() {}, loadStorageSummary() {}, loadStudyView() {}, assistantSelectedTask: () => false, setAssistantOpen() {},
    noteVersionInfo: () => ({ total: 1 }), displayTaskTitle: task => task.id,
    taskDetailFingerprint: task => task.id, sourceText: () => 'local', statusText: () => 'success',
    resultMetaChipsHtml: () => '', mediaSeekDockHtml: () => '',
    transcriptTimeline: () => JSON.stringify(['W001', 'W002']),
    visualWindows: () => [], updateContinueFromMediaAction() {},
  });
  for (const name of ['unifiedExportType', 'canCreateNoteVersion', 'hasTaskBundle', 'hasTaskDiagnostics',
    'hasVisualWindowExport', 'hasExportableSubtitle', 'hasExportableMedia']) context[name] = () => false;
  for (const name of ['showAppView', 'selectTask', 'openTaskFromList', 'normalizeResultTabName', 'taskFromPayload', 'taskRecord', 'bindTaskOverviewActions',
    'focusVisualWindow', 'switchResultTab', 'renderDetail']) vm.runInContext(actualFunction(name), context);
  context.bindTaskOverviewActions();
  return { context, requests, transcripts, scrolls, allNodes, nodes: () => nodes,
    click(id = 'W002') { return buttons.find(button => button.dataset.focusVisualWindow === id).onclick(); },
    runTimers(delay) {
      const ready = timers.filter(timer => timer.delay === delay);
      for (const timer of ready) { timers.splice(timers.indexOf(timer), 1); timer.callback(); }
    },
    async task(index = 0) {
      requests[index].resolve({ json: async () => ({ task: { id: 'task-a', status: 'success' } }) });
      await settle();
    },
    async transcript(index = 0) { transcripts[index].resolve({ segments: [{ start: 0, end: 60, text: 'Synthetic source' }] }); await settle(); },
  };
}

{
  const h = harness();
  assert.equal(h.click(), undefined, 'Source event preserves synchronous void return');
  assert.equal(h.context.selectedTab, 'transcript', 'Tab state changes synchronously');
  assert.equal(h.requests[0].url, '/api/tasks/task-a');
  h.runTimers(0); h.runTimers(20);
  assert.equal(h.scrolls.length, 0, 'Delayed task response cannot focus the old handout');
  await h.task();
  assert.equal(h.transcripts.length, 1);
  h.runTimers(0); h.runTimers(20);
  assert.equal(h.scrolls.length, 0, 'Delayed transcript response cannot focus the old handout');
  await h.transcript(); h.runTimers(20);
  assert.equal(h.scrolls.length, 1);
  const focused = h.scrolls[0];
  assert.equal(focused.surface, 'transcript');
  assert.equal(focused.dataset.visualWindow, 'W002');
  assert(focused.classList.contains('visual-window-focused'));
  h.runTimers(1800);
  assert(!focused.classList.contains('visual-window-focused'), 'Original highlight expiry remains unchanged');
  h.context.switchResultTab('transcript');
  assert.equal(h.requests.length, 1, 'Ordinary current-tab clicks remain no-ops');
}

for (const responseOrder of [[0, 1], [1, 0]]) {
  const h = harness();
  h.click('W001'); h.click('W002');
  assert.equal(h.requests.length, 2, 'Repeated same-tab source clicks receive separate guarded renders');
  for (const index of responseOrder) await h.task(index);
  assert.equal(h.transcripts.length, 1, 'Superseded task response never requests transcript');
  await h.transcript(); h.runTimers(20);
  assert.deepEqual(h.scrolls.map(node => node.dataset.visualWindow), ['W002']);
  assert(h.allNodes.filter(node => node.surface === 'old-handout').every(node => !node.classList.contains('visual-window-focused')));
}

for (const stage of ['task', 'transcript']) {
  for (const cancel of ['task', 'tab', 'view', 'generation']) {
    const h = harness(); h.click();
    if (stage === 'transcript') await h.task();
    if (cancel === 'task') h.context.selectedTaskId = 'task-b';
    if (cancel === 'tab') h.context.selectedTab = 'frames';
    if (cancel === 'view') h.context.showAppView('workspace');
    if (cancel === 'generation') h.context.detailRenderGeneration++;
    if (stage === 'task') {
      await h.task();
      if (h.transcripts.length) await h.transcript();
    } else await h.transcript();
    h.runTimers(0); h.runTimers(20);
    assert.equal(h.scrolls.length, 0, `${cancel} changed during ${stage}: no stale focus`);
  }
}

{
  const h = harness();
  h.click('W001'); await h.task();
  h.click('W002'); await h.task(1);
  assert.equal(h.transcripts.length, 2);
  await h.transcript(1); h.runTimers(20);
  const current = h.nodes();
  await h.transcript(0); h.runTimers(20);
  assert.equal(h.nodes(), current, 'Late transcript cannot replace the latest rendered source');
  assert.deepEqual(h.scrolls.map(node => node.dataset.visualWindow), ['W002']);
}
{
  const h = harness();
  h.click('W001'); await h.task();
  const refresh = h.context.renderDetail();
  await h.task(1); await h.transcript(1); await refresh;
  const current = h.nodes();
  await h.transcript(0); h.runTimers(20);
  assert.equal(h.nodes(), current, 'A newer same-task refresh remains authoritative');
  assert.equal(h.scrolls.length, 0, 'An obsolete source action cannot focus the newer refresh');
}
for (const stage of ['task', 'transcript']) {
  const h = harness(); h.click();
  if (stage === 'transcript') await h.task();
  const originalGeneration = h.context.detailRenderGeneration;
  h.context.showAppView('settings'); h.context.showAppView('notes');
  assert.equal(h.context.detailRenderGeneration, originalGeneration, 'View cancellation leaves the pending render intact');
  assert.equal(h.context.resultViewGeneration, 2, 'Leaving and returning cannot recreate the original view generation');
  assert.equal(h.requests.length, 1, 'View navigation does not add a task fetch');
  h.context.showAppView('notes'); h.context.showAppView('history');
  assert.equal(h.context.resultViewGeneration, 2, 'Same-view navigation preserves its current generation');
  if (stage === 'task') await h.task();
  await h.transcript(); h.runTimers(20);
  assert(h.nodes().every(node => node.surface === 'transcript'), 'The pending render still commits fresh detail after return');
  assert.equal(h.scrolls.length, 0, 'Old source request cannot regain focus after settings and back');
}

{
  const h = harness(); h.click(); await h.task();
  h.context.showAppView('settings');
  const opened = h.context.openTaskFromList('task-b');
  assert.equal(h.requests.length, 2, 'Actual task entry adds only its one intended detail fetch');
  assert.equal(h.requests[1].url, '/api/tasks/task-b');
  h.requests[1].resolve({ json: async () => ({ task: { id: 'task-b', status: 'success' } }) });
  await settle(); await h.transcript(1); await opened;
  assert.equal(h.transcripts[1].task.id, 'task-b');
  const current = h.nodes();
  await h.transcript(0); h.runTimers(20);
  assert.equal(h.nodes(), current, 'Pending old task cannot replace the returned selected task');
  assert.equal(h.scrolls.length, 0);
}

{
  const h = harness();
  h.context.selectedMaterialId = 'material-a';
  h.context.showAppView('settings'); h.context.showAppView('notes');
  assert.equal(h.requests.length, 0, 'Returning to a material must not render a retained task');
  h.context.selectedMaterialId = ''; h.context.selectedTaskId = '';
  h.context.showAppView('settings'); h.context.showAppView('notes');
  assert.equal(h.requests.length, 0, 'Empty note view does not fetch task detail');
}
{
  const h = harness();
  h.context.document.body.dataset.appView = 'workspace';
  h.context.selectedTab = 'transcript';
  const list = deferred();
  Object.assign(h.context, {
    tasks: [], lastDetailFingerprint: '__unrendered__', lastTaskListFingerprint: '__unrendered__',
    lastTaskListLiveFingerprint: '__unrendered__', uiPollTimer: 0,
    hasExplicitTaskRoute: () => true, fetchJson: () => list.promise,
    taskListFingerprint: items => JSON.stringify(items), taskListLiveFingerprint: items => JSON.stringify(items),
    handleTaskStatusTransitions() {}, syncTaskEventStreams() {}, renderTasks() {}, patchTaskListLiveState() {},
    renderBrowserRouteSummary() {}, renderSourceWorkflow() {}, notifyTaskUpdateSubscribers() {},
  });
  const provider = readFileSync(new URL('../task-list.js', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
  const start = provider.indexOf('function noteVersionInfo('), end = provider.indexOf('\n}\n', start);
  assert(start >= 0 && end > start);
  vm.runInContext('globalThis.LearnNoteTaskList = { noteVersionInfo: ' + provider.slice(start, end + 3) + ' };', h.context);
  for (const name of ['noteVersionInfo', 'taskDetailFingerprint', 'initializeWorkspaceView', 'loadTasksOnce']) {
    vm.runInContext(actualFunction(name), h.context);
  }
  h.context.initializeWorkspaceView();
  const loading = h.context.loadTasksOnce();
  assert.equal(h.requests.length, 0, 'Explicit startup must wait for the task list before rendering detail');
  const task = { id: 'task-a', status: 'success' };
  list.resolve({ tasks: [task, { id: 'task-b', source_task_id: 'task-a', status: 'success', created_at: '2026-10-17' }] });
  await settle();
  assert.equal(h.requests.length, 1, 'Task-list arrival starts exactly one initial detail fetch');
  await h.task(); await h.transcript(); await loading;
  assert.equal(h.context.noteVersionInfo(task).total, 2);
  assert.match(h.context.els.selectedSource.textContent, /笔记版本 1\/2/, 'Initial detail sees the complete version family');
}
console.log('Visual source focus waits for real render completion and rejects delayed, reordered and cancelled navigation');
