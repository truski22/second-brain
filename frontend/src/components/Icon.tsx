export const icons = {
  newChat: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z",
  tasks: "M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9",
  memory: "M12 5a3 3 0 1 0-6 .1A4 4 0 0 0 4 12a4 4 0 0 0 2 3.5V17a3 3 0 0 0 6 0M12 5a3 3 0 1 1 6 .1A4 4 0 0 1 20 12a4 4 0 0 1-2 3.5V17a3 3 0 0 1-6 0M12 5v14",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM4 12h2M18 12h2M12 4v2M12 18v2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M6.3 17.7l1.4-1.4M16.3 7.7l1.4-1.4",
  trash: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6",
  send: "M12 19V5M5 12l7-7 7 7",
  mic: "M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3ZM19 10v2a7 7 0 0 1-14 0v-2M12 19v3",
};

export function Icon({ d, size = 18 }: { d: string; size?: number }) {
  return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>;
}

export function StopIcon({ size = 14 }: { size?: number }) {
  return <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
    <rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor" /></svg>;
}
