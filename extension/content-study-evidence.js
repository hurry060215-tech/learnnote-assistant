/* Bounded source chapter evidence helper. No capture lifecycle, network, or Chrome APIs. */
(function (root) {
"use strict";
function collectChapterEvidence({video, pageUrl, document, safeQueryAll}) {
  const duration = Number(video?.duration || 0), chapters = [], seen = new Set();
  const add = (start, end, title, provenance) => {
    start = Number(start); end = Number(end);
    const name = String(title || "").replace(/\s+/g, " ").trim().slice(0, 200);
    if (!name || !Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start || (duration > 0 && end > duration + 0.1) || chapters.length >= 200) return;
    const key = `${start}:${end}:${name}`; if (seen.has(key)) return;
    seen.add(key); chapters.push({start,end,title:name,provenance});
  };
  let tracks = [];
  try { tracks = Array.from(video?.textTracks || []); } catch { /* Unavailable tracks are not chapter evidence. */ }
  for (const track of tracks) {
    let cues = [];
    try { if (track.kind !== "chapters") continue; cues = Array.from(track.cues || []).slice(0, 200); }
    catch { continue; }
    for (const cue of cues) add(cue.startTime,cue.endTime,cue.text,"native_chapter_track");
  }
  for (const node of safeQueryAll(document, "[data-chapter-start][data-chapter-end]").slice(0, 200)) add(node.getAttribute("data-chapter-start"), node.getAttribute("data-chapter-end"), node.getAttribute("data-chapter-title") || node.textContent, "explicit_page_chapter");
  for (const node of safeQueryAll(document, 'script[type="application/ld+json"]').slice(0, 16)) {
    const raw = String(node.textContent || ""); if (raw.length > 100000) continue;
    let parsed; try { parsed = JSON.parse(raw); } catch { continue; }
    const candidates = Array.isArray(parsed) ? parsed : [parsed, ...(Array.isArray(parsed?.["@graph"]) ? parsed["@graph"] : [])];
    for (const item of candidates.slice(0, 100)) {
      if (!item || ![item["@type"]].flat().includes("VideoObject")) continue;
      const target = item.url || item.mainEntityOfPage;
      if (typeof target === "string") {
        try {
          const expected = new URL(target, pageUrl), actual = new URL(pageUrl);
          if (expected.origin !== actual.origin || expected.pathname.replace(/\/$/,"") !== actual.pathname.replace(/\/$/,"") || ["v","p"].some(key => (expected.searchParams.get(key) || (key === "p" ? "1" : "")) !== (actual.searchParams.get(key) || (key === "p" ? "1" : "")))) continue;
        } catch { continue; }
      }
      for (const clip of (Array.isArray(item.hasPart) ? item.hasPart : item.hasPart ? [item.hasPart] : []).slice(0,200)) if (clip?.["@type"] === "Clip") add(clip.startOffset,clip.endOffset,clip.name,"structured_video_clip");
    }
  }
  return chapters.sort((left,right) => left.start-right.start || left.end-right.end);
}

root.LearnNoteStudyEvidence = Object.freeze({collectChapterEvidence});
})(globalThis);
