// Event-only progress must not rebuild an unchanged reader or reset its position.
export function renderEditionStable(element, scroller, key, revision, render) {
  const sameSource = element.dataset.readerSource === key;
  if (sameSource && element.dataset.readerRevision === revision) return false;
  const top = scroller?.scrollTop || 0;
  const rootScroll = scroller?.ownerDocument?.scrollingElement === scroller;
  const viewportTop = rootScroll ? 0 : scroller?.getBoundingClientRect?.().top || 0;
  const headings = [...element.querySelectorAll("h1,h2,h3")];
  const anchor = sameSource && (headings.findLast(node => node.getBoundingClientRect().top <= viewportTop)
    || headings.find(node => node.getBoundingClientRect().bottom >= viewportTop));
  const keyFor = node => `${node.tagName}:${node.textContent}`;
  // Markdown duplicate IDs are occurrence-based. An earlier arriving batch can
  // take an old ID, so fall back to a unique enclosing source-range heading.
  const candidates = anchor ? headings.slice(0, headings.indexOf(anchor) + 1).reverse()
    .filter(node => headings.filter(other => keyFor(other) === keyFor(node)).length === 1)
    .map(node => ({ key: keyFor(node), offset: node.getBoundingClientRect().top - viewportTop })) : [];
  render();
  element.dataset.readerSource = key;
  element.dataset.readerRevision = revision;
  if (sameSource && scroller) {
    const nextHeadings = [...element.querySelectorAll("h1,h2,h3")];
    const match = candidates.map(candidate => ({ candidate, nodes: nextHeadings.filter(node => keyFor(node) === candidate.key) }))
      .find(item => item.nodes.length === 1);
    scroller.scrollTop = top + (match ? match.nodes[0].getBoundingClientRect().top - viewportTop - match.candidate.offset : 0);
  }
  return true;
}
