import { useEffect, useRef, useState } from "react";
import { errorText, transcribe } from "../api/client";
import { Icon, icons, StopIcon } from "./Icon";

export function Composer({ busy, voiceReady, send, stop, report }: {
  busy: boolean; voiceReady: boolean; send: (text: string, voice: boolean) => Promise<void>;
  stop: () => void; report: (error: string) => void;
}) {
  const [text, setText] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  useEffect(() => () => {
    mounted.current = false;
    if (timer.current) clearTimeout(timer.current);
    if (recorder.current?.state === "recording") recorder.current.stop();
    recorder.current?.stream.getTracks().forEach(track => track.stop());
  }, []);

  async function submit() {
    if (!text.trim() || busy || transcribing || recording) return;
    const message = text.trim();
    setText("");
    if (field.current) field.current.style.height = "auto";
    await send(message, false);
  }

  async function microphone() {
    if (recording) { recorder.current?.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = ["audio/webm", "audio/ogg"].find(type => MediaRecorder.isTypeSupported(type));
      if (!mime) { stream.getTracks().forEach(t => t.stop()); throw new Error("Grabación no compatible."); }
      const media = new MediaRecorder(stream, { mimeType: mime });
      recorder.current = media;
      const chunks: Blob[] = [];
      let size = 0;
      media.ondataavailable = event => {
        chunks.push(event.data); size += event.data.size;
        if (size > 9 * 1024 * 1024 && media.state === "recording") media.stop();
      };
      media.onstop = async () => {
        if (timer.current) clearTimeout(timer.current);
        stream.getTracks().forEach(track => track.stop());
        if (!mounted.current) return;
        setRecording(false); setTranscribing(true);
        try {
          const result = await transcribe(new Blob(chunks, { type: mime }));
          await send(result.text, true);
        } catch (error) { report(errorText(error)); }
        finally { if (mounted.current) setTranscribing(false); }
      };
      media.onerror = () => { report("Error durante la grabación."); media.stop(); };
      media.start(500);
      setRecording(true);
      timer.current = setTimeout(() => { if (media.state === "recording") media.stop(); }, 120000);
    } catch (error) { report(errorText(error)); }
  }

  return <footer className="composer">
    {recording && <div className="recording" role="status"><span className="rec-dot" />Grabando… (máx. 2 min)</div>}
    {transcribing && <div className="recording" role="status"><span className="typing"><span /><span /><span /></span></div>}
    <div className="input-shell">
      <textarea ref={field} aria-label="Mensaje" placeholder="Escribe un mensaje…"
        value={text} maxLength={16000} disabled={recording || transcribing} rows={1}
        onChange={event => {
          setText(event.target.value);
          const el = event.target; el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
        }}
        onKeyDown={event => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault(); void submit();
          }
        }} />
      <div className="composer-actions">
        <button className={`icon-button ${recording ? "recording-on" : ""}`} onClick={() => void microphone()}
          disabled={busy || transcribing || !voiceReady} aria-label={recording ? "Detener audio" : "Micrófono"}
          title={voiceReady ? (recording ? "Detener grabación" : "Dictar") : "Prepara la voz con second-brain --prepare-voice"}>
          {recording ? <StopIcon /> : <Icon d={icons.mic} />}
        </button>
        {busy ? <button className="send-button" onClick={stop} aria-label="Detener" title="Detener"><StopIcon /></button>
          : <button className="send-button" disabled={!text.trim() || recording || transcribing}
            aria-label="Enviar" title="Enviar" onClick={() => void submit()}><Icon d={icons.send} /></button>}
      </div>
    </div>
  </footer>;
}
