// Event-only progress must not rebuild an unchanged reader or reset its position.
export function renderEditionStable(element, scroller, key, revision, render) {
  const sameSource = element.dataset.readerSource === key;
  if (sameSource && element.dataset.readerRevision === revision) return false;
  const top = scroller?.scrollTop || 0;
  const viewportTop = scroller?.getBoundingClientRect?.().top || 0;
  const headings = [...element.querySelectorAll("h1,h2,h3")];
  const anchor = sameSource && headings.find(node => node.getBoundingClientRect().bottom >= viewportTop);
  const anchorText = anchor?.textContent, anchorTag = anchor?.tagName;
  const anchorOffset = anchor ? anchor.getBoundingClientRect().top - viewportTop : null;
  render();
  element.dataset.readerSource = key;
  element.dataset.readerRevision = revision;
  if (sameSource && scroller) {
    const next = anchor && [...element.querySelectorAll("h1,h2,h3")]
      .find(node => node.tagName === anchorTag && node.textContent === anchorText);
    scroller.scrollTop = top + (next ? next.getBoundingClientRect().top - viewportTop - anchorOffset : 0);
  }
  return true;
}
