import { requestUrl } from "obsidian";
import { normalizeBackendUrl } from "./core.mjs";
import type {
  LearnNoteHealth,
  LearnNoteTask,
  QuestionHistoryItem,
  QuestionResult,
  TaskListResponse
} from "./types";

export class LearnNoteApi {
  constructor(private readonly backendUrl: () => string) {}

  private baseUrl(): string {
    return normalizeBackendUrl(this.backendUrl());
  }

  private async json<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
    const response = await requestUrl({
      url: `${this.baseUrl()}${path}`,
      method: init.method || "GET",
      contentType: init.body === undefined ? undefined : "application/json",
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      throw: false
    });
    if (response.status < 200 || response.status >= 300) {
      const detail = response.json?.detail;
      const message = typeof detail === "string" ? detail : detail?.message || detail?.code;
      throw new Error(message || `LearnNote 请求失败 (${response.status})`);
    }
    return response.json as T;
  }

  health(): Promise<LearnNoteHealth> {
    return this.json<LearnNoteHealth>("/api/health");
  }

  async tasks(): Promise<LearnNoteTask[]> {
    const response = await this.json<TaskListResponse>("/api/tasks");
    return (response.tasks || [])
      .filter(task => task.status === "success" && Boolean(task.note_path))
      .sort((left, right) => String(right.updated_at || "").localeCompare(String(left.updated_at || "")));
  }

  async task(taskId: string): Promise<LearnNoteTask> {
    const response = await this.json<{ task: LearnNoteTask }>(`/api/tasks/${encodeURIComponent(taskId)}`);
    return response.task;
  }

  async bundle(taskId: string): Promise<ArrayBuffer> {
    const response = await requestUrl({
      url: `${this.baseUrl()}/api/tasks/${encodeURIComponent(taskId)}/exports/bundle`,
      method: "GET",
      throw: false
    });
    if (response.status < 200 || response.status >= 300) {
      throw new Error(`资料包下载失败 (${response.status})`);
    }
    return response.arrayBuffer;
  }

  question(taskId: string, question: string): Promise<QuestionResult> {
    return this.json<QuestionResult>(`/api/tasks/${encodeURIComponent(taskId)}/qa`, {
      method: "POST",
      body: { question }
    });
  }

  async questionHistory(taskId: string): Promise<QuestionHistoryItem[]> {
    const response = await this.json<{ items: QuestionHistoryItem[] }>(`/api/tasks/${encodeURIComponent(taskId)}/qa`);
    return response.items || [];
  }
}
