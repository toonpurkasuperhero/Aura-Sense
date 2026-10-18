// Shared UI helpers: escaping, icons, formatting, gauges, sparklines, toasts.

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const P = {
  grid: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  stetho: '<path d="M4.8 2.3A.3.3 0 1 0 5 2H4a2 2 0 0 0-2 2v5a6 6 0 0 0 6 6v0a6 6 0 0 0 6-6V4a2 2 0 0 0-2-2h-1a.2.2 0 1 0 .3.3"/><path d="M8 15v1a6 6 0 0 0 6 6v0a6 6 0 0 0 6-6v-4"/><circle cx="20" cy="10" r="2"/>',
  scan: '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="3"/><path d="m16 16-1.9-1.9"/>',
  list: '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11h4M12 16h4M8 11h.01M8 16h.01"/>',
  settings: '<path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.3a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.7l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.3a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.3a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.7v-.5a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.3a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  alert: '<path d="m21.7 18-8-14a2 2 0 0 0-3.5 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3z"/><path d="M12 9v4M12 17h.01"/>',
  check: '<path d="M22 11.1V12a10 10 0 1 1-5.9-9.1"/><path d="m9 11 3 3L22 4"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5M12 3v12"/>',
  camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3"/>',
  mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
  file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v4a2 2 0 0 0 2 2h4M16 13H8M16 17H8M10 9H8"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5M12 15V3"/>',
  chat: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22z"/>',
  phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.7 9a1 1 0 0 1-.7 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.2-2.7a1.2 1.2 0 0 1 1.6 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  truck: '<path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2M15 18H9M19 18h2a1 1 0 0 0 1-1v-3.6a1 1 0 0 0-.2-.6l-3.5-4.4A1 1 0 0 0 17.5 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/>',
  book: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>',
  compass: '<circle cx="12" cy="12" r="10"/><path d="m16.2 7.8-2.1 6.4-6.4 2.1 2.1-6.4z"/>',
  pen: '<path d="M12 20h9"/><path d="M16.4 3.6a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4z"/>',
  user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2"/>',
  zap: '<path d="M4 14a1 1 0 0 1-.8-1.6l9.9-10.2a.5.5 0 0 1 .9.5l-1.9 6A1 1 0 0 0 13 10h7a1 1 0 0 1 .8 1.6l-9.9 10.2a.5.5 0 0 1-.9-.5l1.9-6A1 1 0 0 0 11 14z"/>',
  thermo: '<path d="M14 4v10.5a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0z"/>',
  fan: '<path d="M10.8 12.7c-1 3.3-4.6 6.2-7 4.6-2.2-1.5.4-5.1 3.6-6.2 2.6-.9 4.3.4 3.4 1.6z"/><path d="M12.8 10.8c3.4.7 6.7 4 5.3 6.5-1.3 2.4-5.1.1-6.4-3-1-2.5.2-4.3 1.1-3.5z"/><path d="M12.4 12.6c-.1-3.4 2.6-7.6 5.4-6.7 2.6.9 1 5.1-1.8 7-2.2 1.5-4.2.7-3.6-.3z"/><circle cx="12" cy="12" r="1"/>',
  droplet: '<path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5S5 13 5 15a7 7 0 0 0 7 7z"/>',
  cog: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.8 9.8 0 0 1 6.7 2.7L21 8"/><path d="M21 3v5h-5M21 12a9 9 0 0 1-9 9 9.8 9.8 0 0 1-6.7-2.7L3 16"/><path d="M8 16H3v5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/>',
  brain: '<path d="M12 5a3 3 0 1 0-6 .1 4 4 0 0 0-2.5 5.8 4 4 0 0 0 .6 6.6A4 4 0 1 0 12 18z"/><path d="M12 5a3 3 0 1 1 6 .1 4 4 0 0 1 2.5 5.8 4 4 0 0 1-.6 6.6A4 4 0 1 1 12 18z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/>',
  wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z"/>',
  pin: '<path d="M20 10c0 5-5.5 10.2-7.4 11.8a1 1 0 0 1-1.2 0C9.5 20.2 4 15 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>',
  star: '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  wave: '<path d="M2 13a2 2 0 0 0 2-2V7a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0V4a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0v-4a2 2 0 0 1 2-2"/>',
  crosshair: '<circle cx="12" cy="12" r="10"/><path d="M22 12h-4M6 12H2M12 6V2M12 22v-4"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  rupee: '<path d="M6 3h12M6 8h12M6 13l8.5 8M6 13h3a5 5 0 0 0 0-10"/>',
  sparkles: '<path d="M9.9 15.5A2 2 0 0 0 8.5 14l-6.1-1.6a.5.5 0 0 1 0-1L8.5 9.9A2 2 0 0 0 9.9 8.5l1.6-6.1a.5.5 0 0 1 1 0l1.6 6.1a2 2 0 0 0 1.4 1.4l6.1 1.6a.5.5 0 0 1 0 1l-6.1 1.6a2 2 0 0 0-1.4 1.4l-1.6 6.1a.5.5 0 0 1-1 0z"/>',
  ear: '<path d="M6 8.5a6.5 6.5 0 1 1 13 0c0 6-6 6-6 10a3.5 3.5 0 1 1-7 0"/><path d="M15 8.5a2.5 2.5 0 0 0-5 0v1a2 2 0 1 1 0 4"/>',
  layers: '<path d="m12.8 2.2 8.6 3.9a.8.8 0 0 1 0 1.5l-8.6 3.9a2 2 0 0 1-1.6 0L2.6 7.6a.8.8 0 0 1 0-1.5l8.6-3.9a2 2 0 0 1 1.6 0z"/><path d="m22 17.6-9.2 4.2a2 2 0 0 1-1.6 0L2 17.6M22 12.6l-9.2 4.2a2 2 0 0 1-1.6 0L2 12.6"/>',
  history: '<path d="M3 12a9 9 0 1 0 9-9 9.8 9.8 0 0 0-6.7 2.7L3 8"/><path d="M3 3v5h5M12 7v5l4 2"/>',
  send: '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
  hourglass: '<path d="M5 22h14M5 2h14M17 22v-4.2a2 2 0 0 0-.6-1.4L12 12l-4.4 4.4a2 2 0 0 0-.6 1.4V22M7 2v4.2a2 2 0 0 0 .6 1.4L12 12l4.4-4.4a2 2 0 0 0 .6-1.4V2"/>',
};

export const icon = (name, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[name] || P.info}</svg>`;

export const MACHINE_ICON = { motor: "cog", fan: "fan", pump: "droplet", compressor: "zap", gearbox: "cog", other: "cpu" };

export const AGENTS = {
  sentinel: { name: "Tier-1 Sentinel", icon: "zap", color: "#ef4444" },
  orchestrator: { name: "Orchestrator", icon: "compass", color: "#64748b" },
  intake: { name: "Intake Clerk", icon: "mic", color: "#a78bfa" },
  signal_analyst: { name: "Signal Analyst", icon: "activity", color: "#38bdf8" },
  diagnostician: { name: "Diagnostician", icon: "stetho", color: "#ff7a1a" },
  librarian: { name: "Manual Librarian", icon: "book", color: "#14b8a6" },
  safety_auditor: { name: "Safety Auditor", icon: "shield", color: "#f5a524" },
  logistics: { name: "Logistics Coordinator", icon: "truck", color: "#22c55e" },
  reporter: { name: "Reporter", icon: "pen", color: "#ec4899" },
  human: { name: "Human", icon: "user", color: "#94a3b8" },
};
export const PIPELINE = ["intake", "signal_analyst", "librarian", "diagnostician", "safety_auditor", "logistics", "reporter"];

export const statusBadge = (s) => {
  const map = { OK: "ok", LEARNING: "info", WARN: "warn", ALERT: "bad", OFFLINE: "", INVESTIGATING: "warn", DIAGNOSING: "accent",
    DIAGNOSED: "info", APPROVED: "ok", RESOLVED: "", ERROR: "bad" };
  const live = ["ALERT", "DIAGNOSING", "WARN", "LEARNING"].includes(s) ? " live" : "";
  return `<span class="badge ${map[s] ?? ""}${live}"><span class="dot"></span>${esc(s)}</span>`;
};
export const sevBadge = (s) => s ? `<span class="badge ${{ LOW: "ok", MEDIUM: "warn", HIGH: "high", CRITICAL: "bad" }[s] || ""}">${esc(s)}</span>` : "";
export const healthColor = (h) => h == null ? "var(--muted)" : h >= 75 ? "var(--ok)" : h >= 50 ? "var(--warn)" : "var(--bad)";

export const ago = (ts) => {
  if (!ts) return "–";
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (s < 60) return `${Math.max(0, Math.round(s))}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${(s / 3600).toFixed(1)} h ago`;
  return new Date(ts).toLocaleDateString();
};
export const inr = (v) => "₹" + Math.round(v || 0).toLocaleString("en-IN");
export const pct = (v) => v == null ? "–" : Math.round(v * 100) + "%";
export const fix = (v, d = 2) => v == null || isNaN(v) ? "–" : Number(v).toFixed(d);

export function gauge(value, size = 96, label = "health") {
  const r = size / 2 - 8, c = 2 * Math.PI * r, v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const col = healthColor(value);
  return `<div class="gauge" style="width:${size}px;height:${size}px">
    <svg width="${size}" height="${size}">
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="var(--surface-3)" stroke-width="8" fill="none"/>
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="${col}" stroke-width="8" fill="none" stroke-linecap="round"
        stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - v / 100)}" style="transition:stroke-dashoffset .6s ease, stroke .3s"/>
    </svg>
    <div class="val"><div><b style="color:${col}">${value == null ? "–" : Math.round(value)}</b><span>${label}</span></div></div>
  </div>`;
}

export function sparkline(values, color = "var(--accent)", h = 46) {
  if (!values || values.length < 2) return `<svg class="spark" viewBox="0 0 100 ${h}"></svg>`;
  const max = Math.max(0.15, ...values) * 1.1, n = values.length;
  const pts = values.map((v, i) => [(i / (n - 1)) * 100, h - (v / max) * (h - 4) - 2]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2)).join(" ");
  const id = "g" + Math.random().toString(36).slice(2, 8);
  return `<svg class="spark" viewBox="0 0 100 ${h}" preserveAspectRatio="none">
    <defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".35"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    <path d="${d} L100 ${h} L0 ${h} Z" fill="url(#${id})"/>
    <path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

export function toast(msg, type = "info") {
  const box = document.getElementById("toasts");
  const t = document.createElement("div");
  t.className = `toast ${type}`;
  t.innerHTML = icon(type === "ok" ? "check" : type === "bad" ? "alert" : "info") + `<span>${esc(msg)}</span>`;
  box.appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; setTimeout(() => t.remove(), 300); }, 3800);
}

export function lightbox(src) {
  const d = document.createElement("div");
  d.className = "lightbox";
  d.innerHTML = `<img src="${esc(src)}" alt="">`;
  d.onclick = () => d.remove();
  document.body.appendChild(d);
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
