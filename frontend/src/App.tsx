import { useCallback, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import {
  api, authenticate, errorText, runEvents, speak, type Conversation, type Message,
  type Reminder, type Run, type RunEvent, type Status,
} from "./api/client";
import { Composer } from "./components/Composer";
import { Icon, icons } from "./components/Icon";
import { Integrations, Memories, SettingsPanel, Tasks } from "./components/Panels";

interface ChatMessage extends Message { run?: string; streaming?: boolean; voice?: boolean }
type View = "chat" | "tasks" | "memory" | "settings";
const newId = () => crypto.randomUUID();

export function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [thread, setThread] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [tasks, setTasks] = useState<Reminder[]>([]);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [activeRun, setActiveRun] = useState<string | null>(null);
  const [recoverableRun, setRecoverableRun] = useState<string | null>(sessionStorage.getItem("second-brain-run"));
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [view, setView] = useState<View>("chat");
  const [memoryRevision, setMemoryRevision] = useState(0);
  const currentThread = useRef<string | null>(null);
  const requestVersion = useRef(0);
  const bottom = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const streams = useRef(new Map<string, AbortController>());
  const audio = useRef<HTMLAudioElement | null>(null);
  const report = useCallback((message: string) => setError(message), []);

  const refresh = useCallback(async () => {
    const [rows, pending, health] = await Promise.all([
      api<Conversation[]>("/conversations"), api<Reminder[]>("/reminders"), api<Status>("/status"),
    ]);
    setConversations(rows); setTasks(pending); setStatus(health);
  }, []);
  useEffect(() => {
    void authenticate().then(refresh).then(() => setReady(true)).catch(error => report(errorText(error)));
    const controllers = streams.current;
    return () => { controllers.forEach(controller => controller.abort()); audio.current?.pause(); };
  }, [refresh, report]);
  useEffect(() => {
    if (nearBottom.current) bottom.current?.scrollIntoView({ behavior: "instant" });
  }, [messages]);

  async function open(id: string) {
    const version = ++requestVersion.current;
    setLoadingHistory(true);
    currentThread.current = id; setThread(id); setMessages([]); setView("chat");
    try {
      const history = await api<Message[]>(`/conversations/${id}/messages`);
      if (version === requestVersion.current) setMessages(history);
    } catch (error) { report(errorText(error)); }
    finally { if (version === requestVersion.current) setLoadingHistory(false); }
  }
  function newConversation() {
    requestVersion.current++; currentThread.current = null;
    setThread(null); setMessages([]); setError(""); setView("chat");
    setLoadingHistory(false);
  }
  async function remove(conversation: Conversation) {
    if (!confirm("¿Borrar esta conversación? Los recuerdos y las tareas se conservan.")) return;
    try {
      await api(`/conversations/${conversation.id}`, { method: "DELETE" });
      if (thread === conversation.id) newConversation();
      await refresh();
    } catch (error) { report(errorText(error)); }
  }
  async function play(text: string) {
    try {
      const url = await speak(text);
      audio.current?.pause();
      const player = new Audio(url); audio.current = player;
      player.onended = () => URL.revokeObjectURL(url);
      player.onerror = () => { URL.revokeObjectURL(url); report("No se pudo reproducir la respuesta."); };
      try { await player.play(); }
      catch (error) { URL.revokeObjectURL(url); throw error; }
    } catch (error) { report(errorText(error)); }
  }
  async function listen(runId: string, voice: boolean) {
    const controller = new AbortController();
    streams.current.set(runId, controller);
    function receive(event: RunEvent) {
      if (event.type === "done") {
        setActiveRun(current => current === runId ? null : current);
        void refresh().catch(error => report(errorText(error)));
      }
      if (event.type === "memory_saved") setMemoryRevision(value => value + 1);
      if (currentThread.current !== event.thread_id) return;
      if (event.type === "token") setMessages(rows => rows.map(m => m.run === runId
        ? { ...m, content: m.content + (event.text ?? "") } : m));
      if (event.type === "reset") setMessages(rows => rows.map(m => m.run === runId ? { ...m, content: "" } : m));
      if (event.type === "reply") {
        setMessages(rows => rows.map(m => m.run === runId
          ? { ...m, content: event.text ?? "", streaming: false } : m));
        if (voice && event.text) void play(event.text);
      }
      if (["warning", "error", "memory_failed"].includes(event.type)) report(event.message ?? "Operación fallida.");
      if (event.type === "done") setMessages(rows => rows.map(m => m.run === runId
        ? { ...m, streaming: false, content: m.content || event.message || "Respuesta no completada." } : m));
    }
    try {
      await runEvents(runId, receive, controller.signal);
      const state = await api<Run>(`/runs/${runId}`);
      if (state.status !== "completed" && state.error) report(state.error);
      if (sessionStorage.getItem("second-brain-run") === runId) {
        sessionStorage.removeItem("second-brain-run"); setRecoverableRun(null);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setRecoverableRun(runId);
        report(`${errorText(error)} Puedes recuperar el estado; no reenvíes acciones.`);
      }
    } finally {
      streams.current.delete(runId);
      setActiveRun(current => current === runId ? null : current);
    }
  }
  async function send(text: string, voice: boolean) {
    if (activeRun || loadingHistory) return;
    const id = currentThread.current ?? newId();
    const runId = newId();
    sessionStorage.setItem("second-brain-run", runId);
    currentThread.current = id; setThread(id); setError(""); setView("chat"); setActiveRun(runId);
    setMessages(rows => [...rows, { id: runId, role: "user", content: text, voice },
      { id: `${runId}-answer`, run: runId, role: "assistant", content: "", streaming: true }]);
    try {
      await api<Run>("/runs", { method: "POST",
        body: JSON.stringify({ run_id: runId, thread_id: id, agent_id: "second-brain", text }) });
      void listen(runId, voice);
    } catch (error) {
      setActiveRun(null); setRecoverableRun(runId); report(errorText(error));
      setMessages(rows => rows.map(m => m.run === runId
        ? { ...m, streaming: false, content: "No se pudo confirmar la solicitud. Consulta el estado antes de reenviar." } : m));
      await refresh().catch(error => report(errorText(error)));
    }
  }
  async function stop() {
    if (!activeRun) return;
    try { await api(`/runs/${activeRun}/cancel`, { method: "POST" }); }
    catch (error) { report(errorText(error)); }
  }
  async function recover() {
    const id = status?.active_run ?? recoverableRun;
    if (!id) return;
    try {
      const run = await api<Run>(`/runs/${id}`);
      await open(run.thread_id);
      if (["completed", "failed", "cancelled", "interrupted"].includes(run.status)) {
        setRecoverableRun(null); sessionStorage.removeItem("second-brain-run");
        if (run.error || run.status !== "completed") report(run.error ?? `Estado de ejecución: ${run.status}`);
        return;
      }
      setMessages(rows => [...rows, { id: `${id}-answer`, run: id, role: "assistant", content: "", streaming: true }]);
      setActiveRun(id); void listen(id, false);
    } catch (error) { report(errorText(error)); }
  }
  async function browser() {
    try {
      await api("/browser", { method: "POST" });
    } catch (error) { report(errorText(error)); }
  }
  const nav: [View, string, string][] = [["tasks", "Tareas", icons.tasks], ["memory", "Memoria", icons.memory],
    ["settings", "Ajustes", icons.settings]];
  return <div className="app-shell">
    <aside className="sidebar">
      <button className="nav-item" onClick={newConversation} disabled={!ready}>
        <Icon d={icons.newChat} /><span>Nueva conversación</span></button>
      {nav.map(([id, label, icon]) => <button key={id} className={`nav-item ${view === id ? "selected" : ""}`}
        aria-current={view === id ? "page" : undefined} onClick={() => setView(id)}>
        <Icon d={icon} /><span>{label}</span>
        {id === "tasks" && tasks.length > 0 && <span className="badge">{tasks.length}</span>}
      </button>)}
      <h2 className="sidebar-heading">Conversaciones</h2>
      <nav aria-label="Conversaciones" className="conversation-list">
        {conversations.map(conversation => <div key={conversation.id}
          className={`conversation ${view === "chat" && thread === conversation.id ? "selected" : ""}`}>
          <button className="conversation-title" onClick={() => void open(conversation.id)}>{conversation.title}</button>
          <button className="delete-conversation" aria-label={`Borrar ${conversation.title}`} title="Borrar"
            onClick={() => void remove(conversation)} disabled={!!activeRun}><Icon d={icons.trash} size={15} /></button>
        </div>)}
      </nav>
      <div className="sidebar-bottom" title={status?.ollama_ready ? "Ollama conectado" : "Ollama no preparado"}>
        <span className={`dot ${status?.ollama_ready ? "online" : ""}`} />
        <span className="model-name">{status?.model ?? "Conectando…"}</span>
      </div>
    </aside>
    <main className="chat">
      {error && <div className="error-banner" role="alert"><span>{error}</span>
        <button aria-label="Cerrar aviso" onClick={() => setError("")}>×</button></div>}
      {(status?.active_run || recoverableRun) && !activeRun && <div className="notice">Hay una ejecución que puedes consultar.
        <button onClick={() => void recover()}>Recuperar</button></div>}
      {view === "chat" ? <>
        <div className="messages" onScroll={e => {
          const el = e.currentTarget; nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
        }}>
          {!messages.length && !loadingHistory && <div className="welcome">
            <h2>¿En qué estás pensando?</h2>
            <div className="suggestions">{["¿Qué tengo pendiente hoy?", "Recuérdame comprar pan mañana"].map(text =>
              <button key={text} disabled={!ready || !!activeRun} onClick={() => void send(text, false)}>{text}</button>)}</div>
          </div>}
          {messages.map((message, index) => <article key={message.id ?? index} className={`message ${message.role}`}>
            <div className="message-content">{message.role === "user" ? message.content
              : message.content ? <Markdown>{message.content}</Markdown> :
              message.streaming && <span className="typing" role="status" aria-label="Pensando">
                <span /><span /><span /></span>}
              {message.streaming && message.content && <span className="cursor" />}
            </div>
          </article>)}
          <div ref={bottom} />
        </div>
        <Composer busy={!!activeRun || !ready || loadingHistory} voiceReady={status?.voice_ready ?? false}
          send={send} stop={() => void stop()} report={report} />
      </> : <div className="page"><div className="page-inner">
        {view === "tasks" && <Tasks tasks={tasks} today={status?.clock.date ?? ""}
          refresh={refresh} report={report} />}
        {view === "memory" && ready && <Memories revision={memoryRevision} report={report} />}
        {view === "settings" && status && <SettingsPanel key={`${status.model}:${status.configured_timezone}`}
          status={status} refresh={refresh} report={report} openBrowser={() => void browser()} />}
        {view === "settings" && status && <Integrations report={report} />}
      </div></div>}
    </main>
  </div>;
}
