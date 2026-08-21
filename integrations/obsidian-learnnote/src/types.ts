export interface LearnNoteHealth {
  ok: boolean;
  app_version?: string;
  extension_connected?: boolean;
  local_asr_available?: boolean;
}

export interface LearnNoteIntegrationManifest {
  schema_version: number;
  product?: string;
  app_version?: string;
  api_version?: string;
  protocol_version?: number;
  task_schema_version?: number;
  exports?: Record<string, string>;
  privacy?: Record<string, boolean>;
}

export interface LearnNoteTask {
  id: string;
  title: string;
  status: string;
  progress?: number;
  source_type?: string;
  page_url?: string;
  source?: { page_url?: string };
  created_at?: string;
  updated_at?: string;
  note_path?: string;
  transcript_path?: string;
  visual_index_path?: string;
  frame_grids?: unknown[];
  visual_windows?: unknown[];
  error_code?: string;
}

export interface TaskListResponse {
  tasks: LearnNoteTask[];
}

export interface QuestionCitation {
  label?: string;
  source?: string;
  start?: number;
  end?: number;
  excerpt?: string;
  text?: string;
}

export interface QuestionResult {
  answer: string;
  source?: string;
  warning?: string;
  model?: string;
  citations?: QuestionCitation[];
}

export interface QuestionHistoryItem {
  question?: string;
  answer?: string;
  created_at?: string;
  source?: string;
  citations?: QuestionCitation[];
}

export interface LearnNoteSettings {
  backendUrl: string;
  targetFolder: string;
  includeTranscript: boolean;
  includeVisualWindows: boolean;
  includeQaHistory: boolean;
  includeManifest: boolean;
  openAfterImport: boolean;
}

export interface ImportResult {
  notePath: string;
  folderPath: string;
  created: boolean;
  extractedFiles: number;
}
