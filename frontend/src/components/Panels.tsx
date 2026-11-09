import { useEffect, useState } from "react";
import { api, errorText, type Integration, type Memory, type Reminder, type Status } from "../api/client";

export function dateGroup(date: string | null, today: string) {
  if (!date) return "Sin fecha";
  const difference = (Date.parse(date) - Date.parse(today)) / 86400000;
  if (difference < 0) return "Atrasadas";
  if (difference === 0) return "Hoy";
  if (difference === 1) return "Mañana";
  if (difference <= 7) return "Próximos 7 días";
  return "Más adelante";
}

export function Tasks({ tasks, today, refresh, report }: {
  tasks: Reminder[]; today: string; refresh: () => Promise<void>; report: (message: string) => void;
}) {
  async function complete(task: Reminder) {
    try {
      await api(`/reminders/${task.id}/complete`, { method: "POST" });
      await refresh();
    } catch (error) { report(errorText(error)); }
  }
  const groups = ["Atrasadas", "Hoy", "Mañana", "Próximos 7 días", "Más adelante", "Sin fecha"];
  return <section aria-label="Tareas pendientes">
    <div className="section-heading"><h2>Tareas pendientes</h2><span className="pill">{tasks.length}</span></div>
    <p className="muted">Fechas del reloj local, no del chat.</p>
    {!tasks.length && <div className="empty-card">Nada pendiente.<br />Pide al agente que anote una tarea.</div>}
    {groups.map(group => {
      const items = tasks.filter(task => dateGroup(task.due_date, today) === group);
      return items.length > 0 && <div className="task-group" key={group}>
        <h3>{group} <span>{items.length}</span></h3>
        {items.map(task => <div className="task-card" key={task.id}>
          <button className="check" aria-label={`Completar: ${task.task}`} onClick={() => void complete(task)}>✓</button>
          <div><p>{task.task}</p><small>{task.due_date ?? "Sin fecha"}</small></div>
        </div>)}
      </div>;
    })}
  </section>;
}

export function Memories({ report, revision }: { report: (message: string) => void; revision: number }) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true);
    const timer = setTimeout(() => {
      api<Memory[]>(`/memories?offset=${offset}&limit=20&query=${encodeURIComponent(query)}`)
        .then(rows => { if (active) setMemories(rows); })
        .catch(error => { if (active) report(errorText(error)); })
        .finally(() => { if (active) setLoading(false); });
    }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [offset, query, revision, report]);
  async function remove(memory: Memory) {
    if (!confirm("¿Borrar este recuerdo? El texto de las conversaciones se conserva.")) return;
    try {
      await api(`/memories/${memory.id}`, { method: "DELETE" });
      setMemories(current => current.filter(item => item.id !== memory.id));
    } catch (error) { report(errorText(error)); }
  }
  return <section>
    <h2>Tu memoria</h2><p className="muted">Información que has compartido. Puedes revisarla y borrarla.</p>
    <input aria-label="Buscar recuerdos" placeholder="Buscar por significado…"
      value={query} onChange={e => { setQuery(e.target.value); setOffset(0); }} />
    {loading ? <p role="status">Consultando memoria…</p> : !memories.length &&
      <p className="empty-card">No hay recuerdos en esta página.</p>}
    {memories.map(memory => <article className="memory-card" key={memory.id}>
      <p>{memory.text}</p>
      <small>{memory.metadata.created_at?.slice(0, 10) ?? "Fecha desconocida"} · {
        memory.metadata.source_conversation ? "Declaración del usuario" : "Recuerdo importado, sin origen"}
      </small>
      <button className="text-button danger-text" onClick={() => void remove(memory)}>Borrar recuerdo</button>
    </article>)}
    {!query && <div className="pagination">
      <button disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 20))}>Anterior</button>
      <button disabled={memories.length < 20 || loading} onClick={() => setOffset(offset + 20)}>Siguiente</button>
    </div>}
  </section>;
}

export function SettingsPanel({ status, refresh, report, openBrowser }: {
  status: Status; refresh: () => Promise<void>; report: (message: string) => void; openBrowser?: () => void;
}) {
  const [model, setModel] = useState(status.model);
  const [timezone, setTimezone] = useState(status.configured_timezone);
  const [saving, setSaving] = useState(false);
  async function save() {
    setSaving(true);
    try {
      await api("/settings", { method: "PUT", body: JSON.stringify({ model, timezone }) });
      await refresh();
    } catch (error) { report(errorText(error)); }
    finally { setSaving(false); }
  }
  return <section>
    <h2>Ajustes locales</h2>
    <label>Modelo Ollama<select value={model} onChange={e => setModel(e.target.value)}>
      {[...new Set([status.model, ...status.models])].map(name => <option key={name}>{name}</option>)}
    </select></label>
    <label>Zona horaria IANA<input value={timezone} placeholder="Vacío: sistema operativo"
      onChange={e => setTimezone(e.target.value)} /></label>
    <p className="muted">Actual: {status.clock.timezone}. Ejemplo: Europe/Madrid.</p>
    <button onClick={() => void save()} disabled={saving}>Guardar ajustes</button>
    <dl><dt>Ollama</dt><dd>{status.ollama_ready ? "Conectado" : "No preparado"}</dd>
      <dt>Reloj real</dt><dd>{status.clock.date}</dd><dt>Datos</dt><dd>{status.data_dir}</dd>
      <dt>Voz</dt><dd>{status.voice_ready ? "Preparada" : "Pendiente de preparación"}</dd></dl>
    {openBrowser && <button onClick={openBrowser}>Abrir en el navegador</button>}
    <p className="muted">Sin inferencia en la nube. Ollama se administra por separado.</p>
  </section>;
}

export function Integrations({ report }: { report: (message: string) => void }) {
  const [items, setItems] = useState<Integration[]>([]);
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [busy, setBusy] = useState("");
  useEffect(() => {
    api<Integration[]>("/integrations").then(setItems).catch(error => report(errorText(error)));
  }, [report]);
  function field(id: string, name: string, value: string) {
    setValues(current => ({ ...current, [id]: { ...current[id], [name]: value } }));
  }
  async function change(item: Integration, connect: boolean) {
    if (!connect && !confirm(`¿Desconectar ${item.name}? Se borrará el token guardado.`)) return;
    setBusy(item.id);
    try {
      if (connect) {
        const updated = await api<Integration>(`/integrations/${item.id}`, {
          method: "PUT", body: JSON.stringify({ values: values[item.id] ?? {} }),
        });
        setItems(current => current.map(row => row.id === item.id ? updated : row));
        setValues(current => ({ ...current, [item.id]: {} }));
      } else {
        await api(`/integrations/${item.id}`, { method: "DELETE" });
        setItems(current => current.map(row => row.id === item.id ? { ...row, connected: false, account: "" } : row));
      }
    } catch (error) { report(errorText(error)); }
    finally { setBusy(""); }
  }
  return <section aria-label="Integraciones">
    <h2>Integraciones</h2>
    <p className="muted">Los tokens se guardan en el almacén de credenciales de Windows. El contenido
      consultado se procesa con tu modelo local.</p>
    {items.map(item => <article className="memory-card" key={item.id}>
      <div className="section-heading"><h3>{item.name}</h3>
        <span className="pill">{item.connected ? `Conectado · ${item.account}` : "Sin conectar"}</span></div>
      {item.connected ? <>
        <p className="muted">{item.url} · {item.access === "read" ? "Solo lectura" : "Lectura y escritura"}</p>
        <button className="text-button danger-text" disabled={busy === item.id}
          onClick={() => void change(item, false)}>Desconectar</button>
      </> : <form onSubmit={event => { event.preventDefault(); void change(item, true); }}>
        {item.fields.map(spec => <label key={spec.name}>{spec.label}
          <input type={spec.secret ? "password" : "text"} autoComplete="off" required
            placeholder={spec.placeholder} value={values[item.id]?.[spec.name] ?? ""}
            onChange={event => field(item.id, spec.name, event.target.value)} /></label>)}
        <button type="submit" disabled={busy === item.id}>
          {busy === item.id ? "Comprobando…" : `Conectar ${item.name}`}</button>
      </form>}
    </article>)}
  </section>;
}
