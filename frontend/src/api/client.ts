import type { components } from "./schema";

export type RunEvent = components["schemas"]["RunEvent"];
export type RunRequest = components["schemas"]["RunRequest"];
export interface Conversation { id: string; title: string; agent_id: string; updated_at: string }
export interface Message { id: string | null; role: "user" | "assistant"; content: string }
export interface Reminder { id: string; task: string; due_date: string | null }
export interface Memory { id: string; text: string; metadata: Record<string, string> }
export interface Status {
  clock: { date: string; timezone: string; datetime: string };
  model: string; models: string[]; ollama_ready: boolean; issue: string | null;
  voice_ready: boolean; data_dir: string; active_run: string | null;
  configured_timezone: string;
}
export interface IntegrationField { name: string; label: string; secret: boolean; placeholder: string }
export interface Integration {
  id: string; name: string; connected: boolean; url: string; account: string;
  access: "read" | "write"; fields: IntegrationField[];
}
export interface Run {
  id: string; thread_id: string; status: string; reply: string | null;
  error: string | null; memory_status: string | null;
}

let session = sessionStorage.getItem("second-brain-session") ?? "";

export async function authenticate() {
  const token = new URLSearchParams(location.hash.slice(1)).get("token");
  if (token) {
    history.replaceState(null, "", location.pathname);
    const response = await fetch("/auth", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
    });
    if (!response.ok) throw new Error("Sesión caducada. Reinicia el lanzador.");
    const data: { session: string } = await response.json();
    session = data.session;
    sessionStorage.setItem("second-brain-session", session);
  }
  if (!session) throw new Error("Abre esta página desde el lanzador de Second Brain.");
}

async function request(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${session}`);
  if (options.body && !(options.body instanceof Blob)) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, { ...options, headers });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : `Error HTTP ${response.status}`);
  }
  return response;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await request(path, options);
  return response.status === 204 ? undefined as T : response.json();
}

export async function runEvents(runId: string, receive: (event: RunEvent) => void, signal: AbortSignal) {
  let cursor = 0;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await request(`/runs/${runId}/events?after=${cursor}`, { signal });
      const reader = response.body?.getReader();
      if (!reader) throw new Error("Streaming no disponible.");
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const event: RunEvent = JSON.parse(line);
          if (event.version !== 1 || event.run_id !== runId || event.sequence <= cursor) continue;
          cursor = event.sequence;
          receive(event);
        }
        if (done) {
          if (buffer.trim()) throw new Error("Evento incompleto.");
          return;
        }
      }
    } catch (error) {
      if (signal.aborted || attempt === 2) throw error;
      await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)));
    }
  }
}

export async function transcribe(blob: Blob) {
  return api<{ text: string }>("/voice/transcribe", {
    method: "POST", headers: { "Content-Type": blob.type }, body: blob,
  });
}

export async function speak(text: string) {
  const response = await request("/voice/speak", { method: "POST", body: JSON.stringify({ text }) });
  return URL.createObjectURL(await response.blob());
}

export function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Operación fallida.";
}
