// Diagnostic-only native text geometry for two named synthetic fixtures.
// This is deliberately not a product visibility algorithm or a general text walker.
function syntheticTimestampRanges({ mode, items }) {
  const original = mode === 'original';
  const title = original ? 'Synthetic Bilibili-shaped visible DOM fixture' : 'Synthetic inline timestamp geometry fixture';
  if (!['original', 'representative'].includes(mode) || document.title !== title) throw Error('Timestamp diagnostics require a named synthetic fixture');
  const definitions = original
    ? [['original-inline', '.bpx-player-dm-list-time', 'Could we revisit this step?']]
    : [['clear-inline', '#inlineClearTime', 'Clear inline timestamp example.'],
      ['covered-inline', '#inlineCoveredTime', 'Covered inline timestamp example.']];
  const label = node => node ? { node_type: node.nodeType, tag: node.tagName || null,
    id: ['inlineClearTime', 'inlineCoveredTime', 'timestampCover'].includes(node.id) ? node.id : null } : null;
  const rect = box => Object.fromEntries(['left', 'top', 'right', 'bottom', 'width', 'height'].map(key => [key, Number.isFinite(box[key]) ? box[key] : null]));
  const styles = node => {
    const style = getComputedStyle(node);
    return Object.fromEntries(['display', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'wordSpacing',
      'whiteSpace', 'visibility', 'opacity', 'pointerEvents', 'overflowX', 'overflowY', 'transform', 'zoom'].map(key => [key, String(style[key] || '').slice(0, 180)]));
  };
  const samples = definitions.map(([id, selector, body]) => {
    const node = document.querySelector(selector), captured = items.slice(0, 20).find(item => item.text === body);
    if (!node) return { id, missing: true };
    const text = node.childNodes.length === 1 && node.firstChild.nodeType === 3 ? node.firstChild : null;
    const exact = text?.data === '01:23';
    const ancestors = [];
    for (let parent = node, depth = 0; parent && depth < 4; parent = parent.parentElement, depth++) {
      ancestors.push({ ...label(parent), rect: rect(parent.getBoundingClientRect()), style: styles(parent), hidden: Boolean(parent.hidden),
        aria_hidden: parent.getAttribute('aria-hidden') === 'true', inert: parent.hasAttribute('inert') });
    }
    const hits = box => {
      const insetX = Math.min(.5, box.width / 4), insetY = Math.min(.5, box.height / 4);
      return [[(box.left + box.right) / 2, (box.top + box.bottom) / 2],
        [box.left + insetX, box.top + insetY], [box.right - insetX, box.top + insetY],
        [box.left + insetX, box.bottom - insetY], [box.right - insetX, box.bottom - insetY]].map(([x, y]) => {
        const hit = document.elementFromPoint(x, y), stack = document.elementsFromPoint(x, y);
        const layers = []; for (let i = 0; i < Math.min(stack.length, 4); i++) layers.push(label(stack[i]));
        return { x, y, device_x: x * devicePixelRatio, device_y: y * devicePixelRatio,
          hit: label(hit), contained: hit === node || node.contains(hit), layers };
      });
    };
    const boxes = list => {
      const values = []; for (let i = 0; i < Math.min(list.length, 4); i++) values.push({ rect: rect(list[i]), hits: hits(list[i]) });
      return { count: list.length, truncated: list.length > 4, values };
    };
    const geometry = { id, expected_text_matches: exact, direct_text_node: Boolean(text), text_parent_matches: text?.parentElement === node,
      text_node: label(text), ancestors, element_rects: boxes(node.getClientRects()),
      associated_with_timed_body: Boolean(node.closest('.bpx-player-dm-list-item')?.querySelector('.bpx-player-dm-list-dm')),
      collector_visible: LearnNoteCommunityDOM.visible(node, window), collected_seconds: Number.isFinite(captured?.timestamp_seconds) ? captured.timestamp_seconds : null };
    if (!exact) return geometry; // Never range-read arbitrary or nested page text.
    const range = document.createRange();
    range.setStart(text, 0); range.setEnd(text, 5);
    geometry.text_rects = boxes(range.getClientRects());
    geometry.characters = [];
    for (let index = 0; index < 5; index++) {
      range.setStart(text, index); range.setEnd(text, index + 1);
      geometry.characters.push({ index, ...boxes(range.getClientRects()) });
    }
    return geometry;
  });
  const cover = mode === 'representative' ? document.querySelector('#timestampCover') : null;
  return { fixture: 'synthetic-inline-time-ranges-v1', device_pixel_ratio: devicePixelRatio,
    viewport: { width: innerWidth, height: innerHeight }, samples,
    cover: cover ? { rect: rect(cover.getBoundingClientRect()), style: styles(cover) } : null };
}

module.exports = { syntheticTimestampRanges };
