// Local playback uses task-local seconds. Never reuse another source's clock.
export const localMediaUrl = taskId => `/api/tasks/${encodeURIComponent(taskId)}/media`;

function hasSourceMetadata(player, taskId) {
  if (!player || player.dataset.sourceTaskId !== taskId ||
      player.getAttribute("src") !== localMediaUrl(taskId) || player.readyState < 1) return false;
  try {
    const current = new URL(player.currentSrc);
    return current.pathname === localMediaUrl(taskId) && !current.search;
  } catch { return false; }
}

export function localPlaybackPosition(player, taskId) {
  if (!hasSourceMetadata(player, taskId) || !Number.isFinite(player.currentTime) || player.currentTime < 0) return null;
  return Math.round(player.currentTime * 1000) / 1000;
}

export function createLocalPlayer(player) {
  let pending = null;
  function cancelSeek() {
    if (!pending) return;
    player.removeEventListener("loadedmetadata", pending);
    player.removeEventListener("error", cancelSeek);
    player.removeEventListener("seeking", cancelSeek);
    pending = null;
  }
  function setSource(taskId) {
    const url = taskId ? localMediaUrl(taskId) : "";
    if (player.dataset.sourceTaskId === taskId && player.getAttribute("src") === url) return;
    cancelSeek();
    player.pause();
    delete player.dataset.sourceTaskId;
    if (taskId) {
      player.dataset.sourceTaskId = taskId;
      player.src = url;
    } else if (player.hasAttribute("src")) {
      player.removeAttribute("src");
      player.load();
    }
  }
  function seek(seconds) {
    cancelSeek();
    const taskId = player.dataset.sourceTaskId;
    if (!taskId || typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return false;
    const apply = () => {
      // A queued old-resource event can arrive after src replacement. Keep the
      // pending intent until this task's own metadata is actually current.
      if (!hasSourceMetadata(player, taskId)) return;
      cancelSeek();
      // Metadata may not have been available when the citation was clicked.
      // A seek changes position only; it never grants permission to autoplay.
      player.currentTime = Number.isFinite(player.duration) ? Math.min(seconds, player.duration) : seconds;
    };
    if (hasSourceMetadata(player, taskId)) apply();
    else {
      pending = apply;
      player.addEventListener("loadedmetadata", apply);
      player.addEventListener("error", cancelSeek);
      player.addEventListener("seeking", cancelSeek);
    }
    return true;
  }
  return { setSource, seek, cancelSeek };
}
