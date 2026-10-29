// One bounded page request at a time per query; obsolete replies cannot publish.
export function createMaterialListing({ api, now = Date.now, ttl = 30000 }) {
  let query = "", generation = 0, value = null, checked = 0, pending = null, pendingMore = false, queuedMore = null, pages = 1;
  function request(more = false) {
    if (pending) return pending;
    const token = generation, currentQuery = query, previous = value;
    const operation = (async () => {
      let cursor = more ? previous?.next_cursor || "" : "", rows = more ? [...previous.materials] : [], result, loaded = 0;
      do {
        result = await api(`/api/library/materials?standalone=true&limit=100&q=${encodeURIComponent(currentQuery)}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
        if (token !== generation) return null;
        rows.push(...result.materials); loaded++;
        cursor = result.next_cursor || "";
      } while (!more && loaded < pages && result.has_more && cursor);
      pages = more ? pages + 1 : loaded;
      value = { ...result, materials: [...new Map(rows.map(item => [item.material_id, item])).values()] };
      checked = now();
      return value;
    })().finally(() => { if (pending === operation) { pending = null; pendingMore = false; } });
    pending = operation;
    pendingMore = more;
    return operation;
  }
  return {
    get query() { return query; },
    get value() { return value; },
    setQuery(next) {
      next = next.trim().slice(0, 200);
      if (query === next) return false;
      query = next; generation++; value = null; checked = 0; pending = null; pendingMore = false; queuedMore = null; pages = 1;
      return true;
    },
    invalidate() { generation++; checked = -Infinity; pending = null; pendingMore = false; queuedMore = null; },
    refresh() {
      // Refresh the number of pages the reader opened, following fresh cursors.
      if (value && now() - checked < ttl) return Promise.resolve(value);
      return request();
    },
    more() {
      if (queuedMore) return queuedMore;
      if (!value?.has_more) return Promise.resolve(value);
      if (!pending || pendingMore) return request(true);
      const token = generation;
      // A next-page click is a different intent from refreshing existing pages.
      // Preserve it once, using the refresh's new cursor, without reviving a query.
      const operation = pending.then(result => {
        if (token !== generation || !result) return null;
        return value?.has_more ? request(true) : value;
      }).finally(() => { if (queuedMore === operation) queuedMore = null; });
      queuedMore = operation;
      return operation;
    },
  };
}
