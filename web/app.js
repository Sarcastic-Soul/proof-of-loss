// Proof of Loss web app: one claim per device, kept in localStorage.
// Talks to /api (Lambda behind the same CloudFront domain). ?api=https://... overrides it for local testing.
/* global TEXT, PERILS, CROPS */

const API = new URLSearchParams(location.search).get("api") || "/api";
const STORE_KEY = "pol-claim-v1";
const LANG_KEY = "pol-lang";
const MAX_PHOTO_BYTES = 10 * 1024 * 1024;

const $ = (id) => document.getElementById(id);
let state = load();
let lang = loadLang();
let busy = false;
let pending = null;
const t = (key) => TEXT[lang][key];

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY));
    if (saved && saved.claimId) return saved;
  } catch { /* private mode or bad data: start fresh */ }
  return { claimId: null, messages: [], summary: null, packetUrl: null };
}

function loadLang() {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (TEXT[saved]) return saved;
  } catch { /* fall through */ }
  return (navigator.language || "").startsWith("hi") ? "hi" : "mix";
}

function save() {
  // Photo previews are object URLs that die on reload, so they stay out of storage.
  const messages = state.messages.map(({ img, ...m }) => m);
  try { localStorage.setItem(STORE_KEY, JSON.stringify({ ...state, messages })); } catch { /* not critical */ }
}

async function api(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function ensureClaim() {
  if (!state.claimId) {
    state.claimId = (await api("/claims")).claim_id;
    save();
  }
  return state.claimId;
}

// ---------- rendering ----------

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatTime(iso) {
  return new Date(iso).toLocaleString(lang === "hi" ? "hi-IN" : "en-IN", {
    day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata",
  });
}

const crop = (c) => (c ? CROPS[lang][c] || c : "");
const peril = (p) => (p ? PERILS[lang][p] || p : "");

function renderStatic() {
  document.documentElement.lang = lang === "en" ? "en" : "hi";
  for (const node of document.querySelectorAll("[data-t]")) node.textContent = t(node.dataset.t);
  for (const b of document.querySelectorAll("[data-lang]")) b.setAttribute("aria-pressed", String(b.dataset.lang === lang));
  $("text").placeholder = t("placeholder");
  $("mic-label").textContent = listening ? t("stop") : t("speak");
}

function renderSign() {
  const s = state.summary;
  const loss = (s && s.loss) || {};
  const sign = $("sign");
  sign.classList.remove("urgent", "late");
  const cropText = loss.crop && `${crop(loss.crop)}${loss.area_acres ? ` ${loss.area_acres} ${t("acre")}` : ""}`;
  $("sign-label").textContent = [peril(loss.peril), cropText, s && s.farmer && s.farmer.district]
    .filter(Boolean).join(" · ") || t("tagline");

  if (!s || !s.deadline) {
    $("hours").textContent = "72";
    $("hours-unit").innerHTML = t("hoursFresh");
    $("sign-note").textContent = t("noteFresh");
    return;
  }
  const left = (new Date(s.deadline.report_by) - Date.now()) / 3600000;
  if (left <= 0) {
    sign.classList.add("late");
    $("hours").textContent = "0";
    $("hours-unit").innerHTML = t("late");
    $("sign-note").textContent = t("noteLate");
    return;
  }
  if (left < 24) sign.classList.add("urgent");
  $("hours").textContent = String(Math.floor(left));
  $("hours-unit").innerHTML = t("hoursLeft");
  $("sign-note").textContent = t("noteLeft")(formatTime(s.deadline.report_by));
}

function stepRows() {
  const s = state.summary || {};
  const f = s.farmer || {}, loss = s.loss || {}, open = (s.open_items || []).join(" ").toLowerCase();
  const photos = Object.keys(s.photos || {}).length;
  const photoOk = photos > 0 && !open.includes("photo");
  const w = s.weather;
  const titles = t("steps");
  return [
    [f.name && f.village && f.district && f.state ? "done" : "todo", titles[0],
      [f.name, f.village, f.district, f.state].filter(Boolean).join(", ") || t("farmerTodo")],
    [loss.crop && loss.peril && loss.area_acres && loss.loss_date ? "done" : "todo", titles[1],
      [crop(loss.crop), loss.area_acres && `${loss.area_acres} ${t("acre")}`, peril(loss.peril), loss.loss_date]
        .filter(Boolean).join(", ") || t("lossTodo")],
    [photoOk ? "done" : photos ? "bad" : "todo", titles[2],
      !photos ? t("photoNone") : photoOk ? t("photoOk")(photos) : t("photoBad")(photos)],
    w ? [w.verdict === "contradicted" ? "bad" : "done", titles[3], `${t("verdict")[w.verdict] || w.verdict}: ${w.reason}`]
      : ["todo", titles[3], t("weatherTodo")],
    [s.packet_key ? "done" : "todo", titles[4], s.packet_key ? t("packetDone") : t("packetTodo")],
    ["todo", titles[5], t("submit")],
  ];
}

function renderSteps() {
  const icons = { done: "ph-fill ph-check-circle", bad: "ph-fill ph-warning-circle", todo: "ph ph-circle" };
  $("steps").replaceChildren(...stepRows().map(([kind, title, detail]) => {
    const li = el("li", kind);
    const body = el("div");
    body.append(el("b", "", title), el("span", "", detail));
    li.append(el("i", icons[kind]), body);
    return li;
  }));
}

function renderLog() {
  const msgs = state.messages.length ? state.messages : [{ who: "bot", text: t("welcome") }];
  const nodes = msgs.map((m) => {
    const node = el("p", `msg ${m.who}`);
    if (m.who === "you") node.append(el("span", "who", t("you")));
    node.append(m.photo ? t("photoSent") : m.text);
    if (m.img) node.append(Object.assign(el("img"), { src: m.img, alt: "" }));
    return node;
  });
  if (pending) {
    const wait = el("p", "msg wait");
    wait.append(el("i", "ph ph-circle-notch"), el("span", "", t(pending)));
    nodes.push(wait);
  }
  $("log").replaceChildren(...nodes);
}

function render() {
  renderStatic();
  renderSign();
  renderSteps();
  renderLog();
  const s = state.summary;
  $("file-anyway").hidden = !(s && s.can_file_anyway) || busy;
  $("packet").hidden = !state.packetUrl;
  if (state.packetUrl) $("packet").href = state.packetUrl;
  document.body.classList.toggle("busy", busy);
  for (const id of ["mic", "type", "photo-input"]) $(id).disabled = busy;
}

function scrollToEnd() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

// ---------- actions ----------

async function send({ text = "", photos = [], fileAnyway = false, img = null, wait = "thinking" }) {
  if (busy) return;
  busy = true;
  pending = wait;
  if (text || photos.length) state.messages.push({ who: "you", text, photo: !text && photos.length > 0, img });
  render();
  scrollToEnd();
  try {
    const claimId = await ensureClaim();
    const out = await api("/chat", { claim_id: claimId, message: text, photos, file_anyway: fileAnyway, lang });
    state.messages.push({ who: "bot", text: out.reply || "…" });
    state.summary = out.claim || state.summary;
    if (out.packet_url) state.packetUrl = out.packet_url;
  } catch (err) {
    state.messages.push({ who: "err", text: t("sendFail")(err.message) });
  } finally {
    busy = false;
    pending = null;
    save();
    render();
    scrollToEnd();
  }
}

function currentPosition() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy_m: Math.round(p.coords.accuracy) }),
      () => resolve(null), { enableHighAccuracy: true, timeout: 8000, maximumAge: 120000 });
  });
}

async function sendPhoto(file) {
  if (!file || busy) return;
  if (file.size > MAX_PHOTO_BYTES) {
    state.messages.push({ who: "err", text: t("tooBig") });
    return render();
  }
  busy = true;
  pending = "uploading";
  render();
  scrollToEnd();
  let photo;
  try {
    const [claimId, where] = await Promise.all([ensureClaim(), currentPosition()]);
    const up = await api("/upload-url", { claim_id: claimId });
    const form = new FormData();
    for (const [k, v] of Object.entries(up.fields)) form.append(k, v);
    form.append("file", file);
    const res = await fetch(up.url, { method: "POST", body: form });
    if (!res.ok) throw new Error(`upload ${res.status}`);
    photo = { key: up.key, device: { ...(where || {}), captured_at: new Date(file.lastModified).toISOString() } };
  } catch (err) {
    state.messages.push({ who: "err", text: t("uploadFail")(err.message) });
  }
  busy = false;
  pending = null;
  if (!photo) { save(); return render(); }
  await send({ photos: [photo], img: URL.createObjectURL(file), wait: "checking" });
}

async function refreshPacketLink() {
  if (!state.claimId || !(state.summary && state.summary.packet_key)) return;
  try {
    state.packetUrl = (await api("/packet", { claim_id: state.claimId })).url;
    save();
    render();
  } catch { /* keep the old link */ }
}

// ---------- voice (browser speech recognition) ----------

const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
let listening = null;

function toggleMic() {
  if (!Speech) {
    state.messages.push({ who: "err", text: t("noSpeech") });
    return render();
  }
  if (listening) return listening.stop();
  const rec = new Speech();
  rec.lang = t("speech");
  rec.interimResults = true;
  const box = $("text");
  const before = box.value ? `${box.value} ` : "";
  openComposer();
  rec.onresult = (e) => { box.value = before + Array.from(e.results, (r) => r[0].transcript).join(" "); };
  rec.onend = () => {
    listening = null;
    $("mic").setAttribute("aria-pressed", "false");
    renderStatic();
    box.focus();
  };
  rec.onerror = rec.onend;
  listening = rec;
  $("mic").setAttribute("aria-pressed", "true");
  renderStatic();
  rec.start();
}

function openComposer() {
  document.body.classList.add("typing");
  $("text").focus();
}

$("type").addEventListener("click", () => {
  if (!document.body.classList.toggle("typing")) return;
  $("text").focus();
});
$("mic").addEventListener("click", toggleMic);
$("photo-input").addEventListener("change", (e) => { sendPhoto(e.target.files[0]); e.target.value = ""; });
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("text").value.trim();
  if (!text || busy) return;
  $("text").value = "";
  send({ text });
});
$("text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("composer").requestSubmit(); }
});
$("file-anyway").addEventListener("click", () => {
  if (!confirm(t("anywayConfirm"))) return;
  send({ text: t("anywayText"), fileAnyway: true });
});
$("new-claim").addEventListener("click", () => {
  if (state.messages.length && !confirm(t("newConfirm"))) return;
  state = { claimId: null, messages: [], summary: null, packetUrl: null };
  save();
  render();
});
for (const b of document.querySelectorAll("[data-lang]")) {
  b.addEventListener("click", () => {
    lang = b.dataset.lang;
    try { localStorage.setItem(LANG_KEY, lang); } catch { /* not critical */ }
    render();
  });
}

setInterval(renderSign, 60000);
render();
refreshPacketLink();
