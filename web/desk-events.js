// One bounded event connection per active task. Rendering is owned by the caller.
export function createTaskEventHub({ connect, onUpdate, onInvalidate = () => {} }) {
  const streams = new Map();
  const cursors = new Map();
  let refreshing = false;
  let dirty = false;
  async function refresh() {
    dirty = true;
    if (refreshing) return;
    refreshing = true;
    try {
      while (dirty) {
        dirty = false;
        try { await onUpdate(); } catch { /* Existing polling will retry. */ }
      }
    } finally { refreshing = false; }
  }
  function disconnect() {
    for (const source of streams.values()) source.close();
    streams.clear();
  }
  function sync(items, hidden = false) {
    if (hidden) { disconnect(); return; }
    const active = new Set(items.filter(item => item.kind === 'task' && ['queued','running','cancelling'].includes(item.status)).slice(0, 6).map(item => item.id));
    for (const [id, source] of streams) {
      if (!active.has(id)) { source.close(); streams.delete(id); }
    }
    for (const id of cursors.keys()) if (!active.has(id)) cursors.delete(id);
    for (const id of active) {
      if (streams.has(id)) continue;
      const source = connect('/api/tasks/' + encodeURIComponent(id) + '/events/stream?after=' + (cursors.get(id) || 0));
      streams.set(id, source);
      const close = () => { source.close(); if (streams.get(id) === source) streams.delete(id); };
      function receive(event, terminal = false) {
        if (streams.get(id) !== source) return; // Closed connections cannot repaint.
        const next = Number(event.lastEventId || 0);
        if (terminal) close();
        if (!terminal && Number.isFinite(next) && next > 0 && next <= (cursors.get(id) || 0)) return;
        if (Number.isSafeInteger(next) && next > (cursors.get(id) || 0)) cursors.set(id, next);
        onInvalidate(id);
        refresh();
      }
      for (const name of ['task_created','task_updated','stage_timing','draft_ready']) source.addEventListener(name, event => receive(event));
      for (const name of ['task_terminal','task_missing']) source.addEventListener(name, event => receive(event, true));
      source.onerror = close;
    }
  }
  return {sync, disconnect};
}
