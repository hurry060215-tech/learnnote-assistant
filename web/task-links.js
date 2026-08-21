(function installLearnNoteTaskLinks(global) {
  "use strict";

  const encoded = value => encodeURIComponent(value || "");
  const taskPath = (task, suffix) => `/api/tasks/${encoded(task?.id)}/${suffix}`;

  global.LearnNoteTaskLinks = Object.freeze({
    exportUrl(apiUrl, task, type) {
      return apiUrl(`${taskPath(task, "exports")}/${type}`);
    },
    clipExportUrl(apiUrl, task, windowId) {
      return apiUrl(`${taskPath(task, "exports")}/clips/${encoded(windowId || "window")}`);
    },
    rerunUrl(apiUrl, taskId) {
      return apiUrl(`/api/tasks/${encoded(taskId)}/rerun-from-media`);
    },
    resumeUrl(apiUrl, taskId) {
      return apiUrl(`/api/tasks/${encoded(taskId)}/resume`);
    },
    qaUrl(apiUrl, taskId) {
      return apiUrl(`/api/tasks/${encoded(taskId)}/qa`);
    }
  });
})(typeof globalThis !== "undefined" ? globalThis : window);
