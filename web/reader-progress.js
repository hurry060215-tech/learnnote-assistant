const viewportTop = scroller => scroller?.ownerDocument?.scrollingElement === scroller
  ? 0 : scroller?.getBoundingClientRect?.().top || 0;

// Status metadata and its later event-history response can resize the panel
// above an unchanged edition. Compensate synchronously, without touching the
// reader DOM/selection or retaining a position across user input/navigation.
export function preserveReaderPosition(element, scroller, key, render) {
  const reading = scroller?.scrollTop > 0 && !element.hidden && element.isConnected
    && element.dataset.readerSource === key;
  const before = reading ? element.getBoundingClientRect().top : null;
  const anchored = before !== null && before <= viewportTop(scroller);
  const result = render();
  if (anchored && !element.hidden && element.isConnected && element.dataset.readerSource === key) {
    const delta = element.getBoundingClientRect().top - before;
    // Read scrollTop after layout: native scroll anchoring may have already
    // compensated, in which case delta is zero and no scroll write is needed.
    if (delta) scroller.scrollTop += delta;
  }
  return result;
}

// Event-only progress must not rebuild an unchanged reader or reset its position.
export function renderEditionStable(element, scroller, key, revision, render) {
  const sameSource = element.dataset.readerSource === key;
  if (sameSource && element.dataset.readerRevision === revision) return false;
  const top = scroller?.scrollTop || 0;
  const viewport = viewportTop(scroller);
  const headings = [...element.querySelectorAll("h1,h2,h3")];
  const anchor = sameSource && (headings.findLast(node => node.getBoundingClientRect().top <= viewport)
    || headings.find(node => node.getBoundingClientRect().bottom >= viewport));
  const keyFor = node => `${node.tagName}:${node.textContent}`;
  // Markdown duplicate IDs are occurrence-based. An earlier arriving batch can
  // take an old ID, so fall back to a unique enclosing source-range heading.
  const candidates = anchor ? headings.slice(0, headings.indexOf(anchor) + 1).reverse()
    .filter(node => headings.filter(other => keyFor(other) === keyFor(node)).length === 1)
    .map(node => ({ key: keyFor(node), offset: node.getBoundingClientRect().top - viewport })) : [];
  render();
  element.dataset.readerSource = key;
  element.dataset.readerRevision = revision;
  if (sameSource && scroller) {
    const nextHeadings = [...element.querySelectorAll("h1,h2,h3")];
    const match = candidates.map(candidate => ({ candidate, nodes: nextHeadings.filter(node => keyFor(node) === candidate.key) }))
      .find(item => item.nodes.length === 1);
    scroller.scrollTop = top + (match ? match.nodes[0].getBoundingClientRect().top - viewport - match.candidate.offset : 0);
  }
  return true;
}
