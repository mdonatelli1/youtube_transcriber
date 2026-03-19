// ── State ─────────────────────────────────────────────────────────────────────
const jobs = {};
let selectedVideos = new Set();
let prevPanel = "history";

// ── WebSocket ─────────────────────────────────────────────────────────────────
let ws;

function connectWS() {
    ws = new WebSocket(`ws://${location.host}/ws`);

    ws.onopen = () => {
        document.getElementById("ws-dot").className = "ws-dot connected";
        document.getElementById("ws-label").textContent = "connecté";
        document.getElementById("ws-label").style.color = "var(--green)";
    };

    ws.onmessage = (e) => handleJobUpdate(JSON.parse(e.data));

    ws.onclose = () => {
        document.getElementById("ws-dot").className = "ws-dot disconnected";
        document.getElementById("ws-label").textContent = "déconnecté";
        document.getElementById("ws-label").style.color = "var(--red)";
        setTimeout(connectWS, 2000);
    };
}

connectWS();

// ── Job updates ───────────────────────────────────────────────────────────────
function handleJobUpdate(msg) {
    jobs[msg.job_id] = msg;
    renderQueue();
    updateQueueBadge();
    if (msg.status === "done") {
        toast(msg.title || msg.job_id, "ok");
        loadHistory();
    }
    if (msg.status === "error") {
        toast(msg.error, "alert", 4000);
    }
}

function updateQueueBadge() {
    const active = Object.values(jobs).filter(
        (j) => j.status !== "done" && j.status !== "error",
    ).length;
    const badge = document.getElementById("queue-badge");
    badge.textContent = active;
    badge.classList.toggle("visible", active > 0);
    document.getElementById("global-spinner").style.display =
        active > 0 ? "inline-block" : "none";
}

// ── Panels ────────────────────────────────────────────────────────────────────
function showPanel(name) {
    document
        .querySelectorAll(".panel")
        .forEach((p) => p.classList.remove("active"));
    document
        .querySelectorAll(".nav-item")
        .forEach((n) => n.classList.remove("active"));
    document.getElementById("panel-" + name).classList.add("active");
    const nav = document.getElementById("nav-" + name);
    if (nav) nav.classList.add("active");
    if (name === "history") loadHistory();
    if (name === "queue") renderQueue();
}

function goBack() {
    showPanel(prevPanel);
}

// ── Single enqueue ────────────────────────────────────────────────────────────
async function enqueueSingle() {
    const url = document.getElementById("single-url").value.trim();
    const model = document.getElementById("single-model").value;
    const lang = document.getElementById("single-lang").value;
    if (!url) {
        toast("URL manquante", "alert");
        return;
    }

    const res = await fetch("/api/enqueue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, model, language: lang }),
    });
    const data = await res.json();
    jobs[data.job_id] = {
        job_id: data.job_id,
        status: "pending",
        title: url,
        msg: "En attente…",
    };
    renderQueue();
    updateQueueBadge();
    showPanel("queue");
    toast("Ajouté à la file", "ok");
}

// ── Channel ───────────────────────────────────────────────────────────────────
async function fetchChannel() {
    const url = document.getElementById("channel-url").value.trim();
    if (!url) {
        toast("URL de chaîne manquante", "alert");
        return;
    }

    const btn = document.getElementById("fetch-btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Chargement…';

    const res = await fetch("/api/channel/videos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
    });
    const data = await res.json();

    btn.disabled = false;
    btn.innerHTML = '<svg><use href="#ic-search"/></svg> Charger les vidéos';

    if (data.error) {
        toast(data.error, "alert", 4000);
        return;
    }

    selectedVideos.clear();
    renderVideosGrid(data.videos);
    document.getElementById("channel-results").style.display = "block";
    document.getElementById("channel-count").textContent =
        `${data.videos.length} vidéos`;
}

function renderVideosGrid(videos) {
    const grid = document.getElementById("videos-grid");
    grid.innerHTML = "";
    videos.forEach((v) => {
        const card = document.createElement("div");
        card.className = "video-card";
        card.dataset.id = v.id;
        card.innerHTML = `
      <div class="video-thumb">
        ${
            v.thumbnail
                ? `<img src="${v.thumbnail}" alt="" onerror="this.style.display='none'">`
                : '<svg><use href="#ic-play"/></svg>'
        }
      </div>
      <div class="check"><svg><use href="#ic-check"/></svg></div>
      <div class="video-info">
        <div class="video-title">${esc(v.title)}</div>
        <div class="video-date">${fmtDate(v.upload_date)}</div>
      </div>`;
        card.onclick = () => toggleVideo(card, v.id);
        grid.appendChild(card);
    });
}

function toggleVideo(card, id) {
    if (selectedVideos.has(id)) {
        selectedVideos.delete(id);
        card.classList.remove("selected");
    } else {
        selectedVideos.add(id);
        card.classList.add("selected");
    }
    updateSelectBar();
}

function selectAll() {
    document.querySelectorAll(".video-card").forEach((c) => {
        selectedVideos.add(c.dataset.id);
        c.classList.add("selected");
    });
    updateSelectBar();
}

function selectNone() {
    selectedVideos.clear();
    document
        .querySelectorAll(".video-card")
        .forEach((c) => c.classList.remove("selected"));
    updateSelectBar();
}

function updateSelectBar() {
    const n = selectedVideos.size;
    document.getElementById("selected-count").textContent =
        `${n} vidéo${n > 1 ? "s" : ""} sélectionnée${n > 1 ? "s" : ""}`;
    document.getElementById("enqueue-batch-btn").disabled = n === 0;
}

async function enqueueBatch() {
    const model = document.getElementById("channel-model").value;
    const lang = document.getElementById("channel-lang").value;
    const ids = [...selectedVideos];

    const res = await fetch("/api/channel/enqueue-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_ids: ids, model, language: lang }),
    });
    const data = await res.json();

    data.job_ids.forEach((jid) => {
        jobs[jid] = {
            job_id: jid,
            status: "pending",
            title: "…",
            msg: "En attente…",
        };
    });
    renderQueue();
    updateQueueBadge();
    toast(`${ids.length} vidéo(s) ajoutées`, "ok");
    showPanel("queue");
}

// ── Queue render ──────────────────────────────────────────────────────────────
function renderQueue() {
    const list = document.getElementById("job-list");
    const all = Object.values(jobs);

    if (!all.length) {
        list.innerHTML = `
      <div class="empty">
        <svg><use href="#ic-clock"/></svg>
        <p>Aucun job en cours.</p>
      </div>`;
        return;
    }

    list.innerHTML = all
        .slice()
        .reverse()
        .map(
            (j) => `
    <div class="job-item">
      <div class="job-dot ${j.status}"></div>
      <div class="job-info">
        <div class="job-title">${esc(j.title || j.job_id)}</div>
        <div class="job-msg">${esc(j.msg || j.error || "")}</div>
      </div>
      <span class="job-status-label ${j.status}">${j.status}</span>
      ${
          j.status === "done" && j.transcript_id
              ? `<button class="btn btn-ghost btn-sm" onclick="viewTranscript(${j.transcript_id}, 'queue')">Voir</button>`
              : ""
      }
    </div>`,
        )
        .join("");
}

// ── History ───────────────────────────────────────────────────────────────────
async function loadHistory() {
    const res = await fetch("/api/history");
    const data = await res.json();
    const list = document.getElementById("hist-list");

    if (!data.length) {
        list.innerHTML = `
      <div class="empty">
        <svg><use href="#ic-list"/></svg>
        <p>Aucune transcription.</p>
      </div>`;
        return;
    }

    list.innerHTML = data
        .map(
            (t) => `
    <div class="hist-item" onclick="viewTranscript(${t.id}, 'history')">
      <div class="hist-icon"><svg><use href="#ic-play"/></svg></div>
      <div class="hist-info">
        <div class="hist-title">${esc(t.title || t.video_id)}</div>
        <div class="hist-meta">
          ${esc(t.channel || "")} · ${t.word_count} mots · ${(t.language || "").toUpperCase()} · ${fmtDatetime(t.created_at)}
        </div>
      </div>
      <div class="hist-actions" onclick="event.stopPropagation()">
        <a class="btn btn-ghost btn-sm" href="/api/transcript/${t.id}/export/txt"  download>TXT</a>
        <a class="btn btn-ghost btn-sm" href="/api/transcript/${t.id}/export/srt"  download>SRT</a>
        <a class="btn btn-ghost btn-sm" href="/api/transcript/${t.id}/export/json" download>JSON</a>
        <button class="btn btn-danger btn-sm" onclick="deleteTranscript(${t.id})">
          <svg><use href="#ic-trash"/></svg>
        </button>
      </div>
    </div>`,
        )
        .join("");
}

async function deleteTranscript(id) {
    if (!confirm("Supprimer cette transcription ?")) return;
    await fetch(`/api/transcript/${id}`, { method: "DELETE" });
    toast("Supprimé", "ok");
    loadHistory();
}

// ── Viewer ────────────────────────────────────────────────────────────────────
async function viewTranscript(id, from) {
    prevPanel = from || "history";

    const res = await fetch(`/api/transcript/${id}`);
    const t = await res.json();

    document.getElementById("viewer-title").textContent = t.title || t.video_id;
    document.getElementById("viewer-meta").textContent =
        `${t.channel || ""} · ${t.word_count} mots · ${(t.language || "").toUpperCase()} · modèle: ${t.model}`;

    document.getElementById("viewer-actions").innerHTML = `
    <a class="btn btn-ghost btn-sm" href="/api/transcript/${id}/export/txt"  download>
      <svg><use href="#ic-download"/></svg> TXT
    </a>
    <a class="btn btn-ghost btn-sm" href="/api/transcript/${id}/export/srt"  download>
      <svg><use href="#ic-download"/></svg> SRT
    </a>
    <a class="btn btn-ghost btn-sm" href="/api/transcript/${id}/export/json" download>
      <svg><use href="#ic-download"/></svg> JSON
    </a>
    <a class="btn btn-ghost btn-sm" href="${t.url}" target="_blank">
      <svg><use href="#ic-link"/></svg> YouTube
    </a>`;

    document.getElementById("viewer-text").textContent = t.full_text;

    document.getElementById("viewer-segments").innerHTML = (t.segments || [])
        .map(
            (s) => `
    <div class="seg-row">
      <span class="seg-time">${fmtSec(s.start)} → ${fmtSec(s.end)}</span>
      <span class="seg-text">${esc(s.text.trim())}</span>
    </div>`,
        )
        .join("");

    showPanel("viewer");
}

function switchTab(name) {
    document
        .querySelectorAll(".tab")
        .forEach((t, i) =>
            t.classList.toggle("active", ["text", "segments"][i] === name),
        );
    document
        .querySelectorAll(".tab-content")
        .forEach((c, i) =>
            c.classList.toggle(
                "active",
                ["tab-text", "tab-segments"][i] === "tab-" + name,
            ),
        );
}

// ── Search ────────────────────────────────────────────────────────────────────
async function doSearch() {
    const q = document.getElementById("search-input").value.trim();
    if (!q) return;

    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    const div = document.getElementById("search-results");

    if (!data.length) {
        div.innerHTML = `
      <div class="empty">
        <svg><use href="#ic-search"/></svg>
        <p>Aucun résultat.</p>
      </div>`;
        return;
    }

    div.innerHTML = data
        .map(
            (r) => `
    <div class="search-hit" onclick="viewTranscript(${r.id}, 'search')">
      <div class="search-hit-title">${esc(r.title || r.video_id)}</div>
      <div class="search-hit-snip">${r.snippet || ""}</div>
      <div class="search-hit-meta">${esc(r.channel || "")} · ${fmtDatetime(r.created_at)}</div>
    </div>`,
        )
        .join("");
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function esc(s) {
    return String(s || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function fmtSec(s) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = Math.floor(s % 60);
    return h ? `${pad(h)}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
}

function pad(n) {
    return String(n).padStart(2, "0");
}

function fmtDate(d) {
    if (!d || d.length < 8) return "";
    return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;
}

function fmtDatetime(s) {
    if (!s) return "";
    return s.replace("T", " ").slice(0, 16);
}

// ── Copy ──────────────────────────────────────────────────────────────────────
function copyText() {
    const text = document.getElementById("viewer-text").textContent;
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
        const btn = document.getElementById("copy-btn");
        btn.classList.add("copied");
        btn.innerHTML = '<svg><use href="#ic-check"/></svg> Copié';
        setTimeout(() => {
            btn.classList.remove("copied");
            btn.innerHTML = '<svg><use href="#ic-copy"/></svg> Copier';
        }, 2000);
    });
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let toastTimer;

function toast(msg, type = "ok", duration = 2500) {
    const el = document.getElementById("toast");
    const icon = document.getElementById("toast-icon");
    const txt = document.getElementById("toast-msg");
    icon.innerHTML = `<use href="#ic-${type === "alert" ? "alert" : "ok"}"/>`;
    icon.style.color = type === "alert" ? "var(--red)" : "var(--green)";
    txt.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), duration);
}

// ── Init ──────────────────────────────────────────────────────────────────────
loadHistory();

fetch("/api/jobs")
    .then((r) => r.json())
    .then((data) => {
        data.forEach((j) => {
            jobs[j.job_id] = j;
        });
        renderQueue();
        updateQueueBadge();
    });
