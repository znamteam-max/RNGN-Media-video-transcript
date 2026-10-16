/* RNGN Media interface. Talks to Python through window.pywebview.api (see rngn/api.py);
   the clickable preview swaps in window.RNGN_MOCK with the same methods. */
(() => {
  "use strict";

  // ---- icons ------------------------------------------------------------------------
  const P = {
    download: '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
    cc: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 15h4"/><path d="M13 15h4"/><path d="M7 11h10"/>',
    convert: '<path d="M4 8h13l-3-3"/><path d="M20 16H7l3 3"/>',
    list: '<path d="M9 6h11"/><path d="M9 12h11"/><path d="M9 18h11"/><path d="M4.5 6h.01"/><path d="M4.5 12h.01"/><path d="M4.5 18h.01"/>',
    sliders: '<path d="M4 7h9"/><path d="M19 7h1"/><circle cx="16" cy="7" r="2.5"/><path d="M4 17h3"/><path d="M13 17h7"/><circle cx="10" cy="17" r="2.5"/>',
    folder: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z"/>',
    x: '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7"/>',
    alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><path d="M12 16.5v.01"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/>',
    paste: '<rect x="8" y="3" width="8" height="4" rx="1"/><path d="M8 5H6.5A2.5 2.5 0 0 0 4 7.5v11A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5v-11A2.5 2.5 0 0 0 17.5 5H16"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
    moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8"/><path d="M12 16v4"/>',
    chip: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
    scissors: '<circle cx="6" cy="7" r="2.5"/><circle cx="6" cy="17" r="2.5"/><path d="M8.2 8.4 20 18"/><path d="M8.2 15.6 20 6"/>',
    retry: '<path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4.5V8h3.5"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    trash: '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M9 7V4h6v3"/>',
    external: '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
    music: '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
    film: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 9.5h4M3 14.5h4M17 9.5h4M17 14.5h4"/>',
    upload: '<path d="M12 16V5"/><path d="m7 9 5-5 5 5"/><path d="M5 20h14"/>',
    play: '<path d="M8 5.5v13l10.5-6.5z"/>',
    stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9"/><path d="m16.5 6.5 3 3"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.5v.01"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>',
    queue: '<path d="M4 6h16"/><path d="M4 12h10"/><path d="M4 18h7"/><path d="m16 15 3 3-3 3"/>',
  };
  const icon = (name, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[name] || ""}</svg>`;

  // ---- helpers ----------------------------------------------------------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const plural = (n, one, few, many) => {
    const a = Math.abs(n) % 100, b = a % 10;
    if (a > 10 && a < 20) return many;
    if (b === 1) return one;
    if (b >= 2 && b <= 4) return few;
    return many;
  };
  function fmtTime(seconds) {
    const s = Math.max(0, Math.round(Number(seconds) || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    const pad = (v) => String(v).padStart(2, "0");
    return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
  }
  function parseTime(text) {
    const parts = String(text || "").trim().replace(",", ".").split(":");
    if (!parts[0] || parts.length > 3 || parts.some((p) => p === "" || isNaN(Number(p)))) return NaN;
    return parts.map(Number).reduce((acc, v) => acc * 60 + v, 0);
  }
  function fmtSize(bytes) {
    const b = Number(bytes) || 0;
    if (!b) return "";
    if (b >= 1e9) return `${(b / 1e9).toFixed(1).replace(".", ",")} ГБ`;
    if (b >= 1e6) return `${Math.round(b / 1e6)} МБ`;
    return `${Math.max(1, Math.round(b / 1e3))} КБ`;
  }
  const baseName = (path) => String(path || "").split(/[\\/]/).pop();
  const urlsIn = (text) => [...new Set((String(text || "").match(/https?:\/\/[^\s<>"'\]\[)(]+/gi) || []).map((u) => u.replace(/[.,;)\]}>]+$/, "")))];

  // ---- state ------------------------------------------------------------------------
  const state = {
    api: null,
    app: { version: "", platform: "windows" },
    settings: { theme: "system", download: {}, transcribe: {}, convert: {} },
    gpu: {},
    models: [],
    languages: [],
    profiles: [],
    tools: {},
    cookies: {},
    update: null,
    page: "download",
    jobs: new Map(),
    jobsFilter: "all",
    openLogs: new Set(),
    logs: new Map(),
    dl: { text: "", status: "idle", info: null, error: null, urls: [], req: 0, mode: "video", height: null, audioFormat: "mp3",
          clipOn: false, clipStart: 0, clipEnd: 0, transcribeAfter: false, tracks: null, trackId: null, subFormats: ["txt", "srt"],
          batchHeight: 1080, queued: false },
    tr: { files: [] },
    cv: { files: [] },
  };

  const call = async (name, ...args) => {
    try {
      return await state.api[name](...args);
    } catch (err) {
      console.error(name, err);
      toast("bad", "Что-то пошло не так", String(err && err.message ? err.message : err));
      return null;
    }
  };
  const saveSettings = async (patch) => {
    const result = await call("save_settings", patch);
    if (result) state.settings = result;
  };

  // ---- theme ------------------------------------------------------------------------
  function applyTheme() {
    const theme = state.settings.theme || "system";
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    const sw = $("#theme-switch");
    const sys = state.app.platform === "mac" ? "Как в системе" : "Как в Windows";
    sw.innerHTML = [["system", "monitor", sys], ["light", "sun", "Светлая"], ["dark", "moon", "Тёмная"]]
      .map(([id, ic, label]) => `<button type="button" data-action="theme" data-theme="${id}" aria-pressed="${theme === id}" title="${label}" aria-label="${label}">${icon(ic)}</button>`)
      .join("");
  }

  // ---- rail ------------------------------------------------------------------------------
  const PAGES = [
    ["download", "download", "Скачать"],
    ["transcribe", "mic", "Расшифровка"],
    ["convert", "convert", "Конвертер"],
    ["jobs", "list", "Задания"],
    ["settings", "sliders", "Настройки"],
  ];
  const activeJobs = () => [...state.jobs.values()].filter((j) => j.state === "running" || j.state === "queued");

  function renderNav() {
    const count = activeJobs().length;
    $("#nav").innerHTML = PAGES.map(([id, ic, label]) => `
      <button class="nav-item" type="button" data-action="nav" data-page="${id}" ${state.page === id ? 'aria-current="page"' : ""}>
        ${icon(ic)}<span class="lbl">${label}</span>${id === "jobs" && count ? `<span class="count num">${count}</span>` : ""}
      </button>`).join("");
    $("#brand-ver").textContent = state.app.version ? `версия ${state.app.version}` : "";
    renderGpuPill();
  }

  function gpuView() {
    const g = state.gpu || {};
    if (state.app.platform !== "windows" || g.supported === false) return null;
    const name = (g.gpu && g.gpu.name || "").replace(/^NVIDIA\s+(GeForce\s+)?/i, "");
    if (g.ready) return { cls: "on", title: name || "NVIDIA", text: "ускорение включено" };
    if (g.gpu) return { cls: "off", title: name || "NVIDIA", text: "ускорение выключено" };
    return { cls: "", title: "Процессор", text: "видеокарта NVIDIA не найдена" };
  }

  function renderGpuPill() {
    const pill = $("#gpu-pill");
    const view = gpuView();
    pill.hidden = !view;
    if (!view) return;
    pill.className = `gpu-pill ${view.cls}`;
    pill.innerHTML = `<i class="dot"></i><div><b>${esc(view.title)}</b><span>${esc(view.text)}</span></div>`;
    pill.title = "Расшифровка речи: " + view.text;
  }

  // ---- toasts ----------------------------------------------------------------------------
  function toast(kind, title, text = "", action = null) {
    const box = document.createElement("div");
    box.className = `toast ${kind}`;
    box.innerHTML = `${icon(kind === "ok" ? "check" : kind === "bad" ? "alert" : "info")}<div class="grow"><b>${esc(title)}</b>${text ? `<span>${esc(text)}</span>` : ""}</div>`;
    if (action) {
      const btn = document.createElement("button");
      btn.className = "btn small";
      btn.type = "button";
      btn.textContent = action.label;
      btn.addEventListener("click", () => { action.run(); box.remove(); });
      box.appendChild(btn);
    }
    const close = document.createElement("button");
    close.className = "btn small ghost icon";
    close.type = "button";
    close.setAttribute("aria-label", "Закрыть");
    close.innerHTML = icon("x");
    close.addEventListener("click", () => box.remove());
    box.appendChild(close);
    $("#toasts").appendChild(box);
    setTimeout(() => box.remove(), 7000);
  }

  // ---- page frame ------------------------------------------------------------------------
  function folderLink(sub) {
    const root = state.settings.output_root || "";
    const path = sub ? `${root}\\${sub}` : root;
    return `<button class="folder-link" type="button" data-action="open-output" data-sub="${esc(sub || "")}" title="Открыть папку ${esc(path)}">${icon("folder")}<span>${esc(path)}</span></button>`;
  }
  function updateBanner() {
    const u = state.update;
    if (!u || !u.version) return "";
    return `<div class="banner">${icon("download")}<div class="grow"><b>Вышла версия ${esc(u.version)}</b> — в ней исправления и новые функции.</div>
      <button class="btn small" type="button" data-action="open-url" data-url="${esc(u.url)}">Скачать</button></div>`;
  }

  function renderPage() {
    const page = $("#page");
    if (state.page === "download") page.innerHTML = downloadPage();
    else if (state.page === "transcribe") page.innerHTML = transcribePage();
    else if (state.page === "convert") page.innerHTML = convertPage();
    else if (state.page === "jobs") page.innerHTML = jobsPage();
    else page.innerHTML = settingsPage();
    if (state.page === "download") {
      const ta = $("#link");
      ta.value = state.dl.text;
      autoGrow(ta);
      renderDownloadBody();
    }
    renderJobsSlot();
  }

  function demoNote() {
    if (!state.api || !state.api.__mock) return "";
    return `<div class="notice info">${icon("info")}<div class="grow"><b>Кликабельный макет</b><p>Всё можно нажимать, но ссылки, файлы и задания здесь — примеры: ничего не скачивается. В программе на месте примеров будут твои видео.</p></div></div>`;
  }

  function head(title, text, sub) {
    return `${demoNote()}<div class="page-head"><div><h1>${title}</h1><p>${text}</p></div>${sub === undefined ? "" : folderLink(sub)}</div>${updateBanner()}`;
  }

  // ---- download page ---------------------------------------------------------------------
  function downloadPage() {
    return `${head("Скачать по ссылке", "Видео, звук или субтитры с YouTube, VK, Rutube, TikTok, Instagram и ещё 1800 сайтов. Можно вставить сразу несколько ссылок.", "")}
      <div class="link-field">
        ${icon("link")}
        <textarea id="link" rows="1" spellcheck="false" placeholder="Вставь ссылку на видео или пост" aria-label="Ссылка"></textarea>
        <div class="actions">
          <button class="btn" type="button" data-action="paste">${icon("paste")}<span class="lbl">Вставить</span></button>
          <button class="btn ghost icon" type="button" data-action="clear-link" aria-label="Очистить">${icon("x")}</button>
        </div>
      </div>
      <div id="dl-body"></div>
      <section class="dock" id="jobs-slot"></section>`;
  }

  function renderDownloadBody() {
    const body = $("#dl-body");
    if (!body) return;
    const d = state.dl;
    if (d.status === "idle") {
      body.innerHTML = `<div class="sites"><b>Работает с</b>${["YouTube", "VK Видео", "Rutube", "TikTok", "Instagram", "X", "Дзен", "OK", "Vimeo", "Twitch"].map((s) => `<span class="site-chip">${s}</span>`).join("")}<span>и другими</span></div>`;
      return;
    }
    if (d.status === "analyzing") {
      body.innerHTML = `<div class="card skeleton"><div class="spinner"></div><div class="grow" style="flex:1"><b>Проверяю ссылку…</b><div class="meta">Узнаю название, длительность и доступное качество</div></div>
        <button class="btn" type="button" data-action="cancel-analysis">Отмена</button></div>`;
      return;
    }
    if (d.status === "error") {
      const e = d.error || {};
      body.innerHTML = `<div class="notice bad">${icon("alert")}<div class="grow"><b>${esc(e.message || "Не получилось проверить ссылку.")}</b>
        ${e.hint ? `<p>${esc(e.hint)}</p>` : ""}
        <div class="row"><button class="btn small" type="button" data-action="reanalyze">${icon("retry")}Проверить ещё раз</button>
        <button class="btn small" type="button" data-action="download-blind">${icon("download")}Скачать без проверки</button>
        ${e.kind === "auth" || e.kind === "private" ? `<button class="btn small ghost" type="button" data-action="nav" data-page="settings">${icon("key")}Вход на сайты</button>` : ""}</div>
        ${e.details ? `<details class="log"><summary class="meta">Подробности</summary><pre>${esc(e.details)}</pre></details>` : ""}</div></div>`;
      return;
    }
    if (d.status === "batch") {
      body.innerHTML = batchCard(d.urls.map((u) => ({ url: u.url, title: "", site: u.site })), `${d.urls.length} ${plural(d.urls.length, "ссылка", "ссылки", "ссылок")}`);
      return;
    }
    if (d.status === "media" && d.info && d.info.kind === "playlist") {
      const info = d.info;
      body.innerHTML = batchCard(info.entries.map((e) => ({ url: e.url, title: e.title, site: info.site, duration: e.duration })),
        `Плейлист «${esc(info.title)}» · ${info.entries.length} ${plural(info.entries.length, "видео", "видео", "видео")}`);
      return;
    }
    if (d.status === "media" && d.info) body.innerHTML = mediaCard(d.info);
  }

  function batchCard(items, title) {
    const d = state.dl;
    const heights = [2160, 1440, 1080, 720, 480];
    return `<div class="card"><div class="panel">
      <h2>${title}</h2>
      <div class="batch-list">${items.map((it) => `<div><span class="site-chip">${esc(it.site || "")}</span><span class="u">${esc(it.title || it.url)}</span>${it.duration ? `<small class="num">${fmtTime(it.duration)}</small>` : ""}</div>`).join("")}</div>
      <div class="row">
        <div class="seg" role="group" aria-label="Что скачать">
          <button type="button" data-action="mode" data-mode="video" aria-pressed="${d.mode !== "audio"}">${icon("film")}Видео</button>
          <button type="button" data-action="mode" data-mode="audio" aria-pressed="${d.mode === "audio"}">${icon("music")}Только звук</button>
        </div>
        ${d.mode === "audio"
          ? `<div class="seg">${["mp3", "m4a", "wav"].map((f) => `<button type="button" data-action="audio-format" data-format="${f}" aria-pressed="${d.audioFormat === f}">${f.toUpperCase()}</button>`).join("")}</div>`
          : `<label class="field"><span class="label">Качество не выше</span><select class="input" id="batch-height">${heights.map((h) => `<option value="${h}" ${d.batchHeight === h ? "selected" : ""}>${h}p</option>`).join("")}<option value="0" ${!d.batchHeight ? "selected" : ""}>Лучшее</option></select></label>`}
      </div>
      <label class="switch"><input type="checkbox" id="transcribe-after" ${d.transcribeAfter ? "checked" : ""}><div><b>Сразу расшифровать</b><span>После скачивания каждого файла сделать текст и субтитры</span></div></label>
      <div class="go"><span class="hint">Файлы будут скачиваться по очереди, прогресс — внизу и в «Заданиях».</span>
        <button class="btn primary" type="button" data-action="start-batch">${icon("queue")}Добавить ${items.length} в очередь</button></div>
    </div></div>`;
  }

  function mediaCard(info) {
    const d = state.dl;
    const thumb = info.thumbnail ? `<img src="${esc(info.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : "";
    const duration = info.duration ? `<span class="dur num">${fmtTime(info.duration)}</span>` : "";
    const subs = info.subtitle_tracks ? `<span class="badge">${icon("cc")}есть субтитры</span>` : "";
    return `<div class="card">
      <div class="media">
        <div class="thumb">${icon("play", "fill")}${thumb}${duration}</div>
        <div class="media-body">
          <h2 class="media-title">${esc(info.title || "Без названия")}</h2>
          <div class="meta"><span class="badge accent">${esc(info.site)}</span>${info.uploader ? `<span>${esc(info.uploader)}</span>` : ""}${info.is_live ? '<span class="badge warn">прямой эфир</span>' : ""}${subs}</div>
          <div class="seg" role="group" aria-label="Что скачать" style="margin-top:6px">
            <button type="button" data-action="mode" data-mode="video" aria-pressed="${d.mode === "video"}">${icon("film")}Видео</button>
            <button type="button" data-action="mode" data-mode="audio" aria-pressed="${d.mode === "audio"}">${icon("music")}Только звук</button>
            <button type="button" data-action="mode" data-mode="subtitles" aria-pressed="${d.mode === "subtitles"}">${icon("cc")}Субтитры</button>
          </div>
        </div>
      </div>
      <div class="options">${d.mode === "subtitles" ? subtitleOptions() : mediaOptions(info)}</div>
    </div>`;
  }

  function mediaOptions(info) {
    const d = state.dl;
    let pick = "";
    if (d.mode === "video") {
      pick = `<div class="field"><span class="label">Качество</span><div class="choices">${info.choices.map((c) => `
        <button class="choice" type="button" data-action="height" data-height="${c.height || 0}" aria-pressed="${(d.height || 0) === (c.height || 0)}">
          <span class="top"><b>${esc(c.label)}${c.fps && c.fps > 30 ? `<small> ${c.fps} к/с</small>` : ""}</b>${c.size ? `<small class="num">~${fmtSize(c.size)}</small>` : ""}</span>
          <span class="note ${c.direct ? "direct" : ""}">${esc(c.note)}</span>
        </button>`).join("")}</div></div>`;
    } else {
      const formats = [["mp3", "MP3", "подойдёт везде"], ["m4a", "M4A", "без потерь, если источник AAC"], ["wav", "WAV", "для монтажа, файл большой"]];
      pick = `<div class="field"><span class="label">Формат звука</span><div class="choices">${formats.map(([id, label, note]) => `
        <button class="choice" type="button" data-action="audio-format" data-format="${id}" aria-pressed="${d.audioFormat === id}"><span class="top"><b>${label}</b></span><span class="note">${note}</span></button>`).join("")}</div></div>`;
    }
    const canClip = info.duration && !info.is_live;
    const clip = canClip ? `
      <label class="switch"><input type="checkbox" id="clip-on" ${d.clipOn ? "checked" : ""}><div><b>${icon("scissors")} Только отрезок</b><span>Скачать кусок между двумя таймкодами</span></div></label>
      <div class="clip" id="clip-box" ${d.clipOn ? "" : "hidden"}>
        <div class="row">
          <label class="field"><span class="label">С</span><input class="input time num" id="clip-start" value="${fmtTime(d.clipStart)}" inputmode="numeric"></label>
          <label class="field"><span class="label">По</span><input class="input time num" id="clip-end" value="${fmtTime(d.clipEnd)}" inputmode="numeric"></label>
          <span class="meta" id="clip-len">Длина отрезка: <b class="num">${fmtTime(d.clipEnd - d.clipStart)}</b></span>
        </div>
        <div class="range" id="clip-range"><div class="track"></div><div class="sel" id="clip-sel"></div>
          <input type="range" id="clip-a" min="0" max="${Math.floor(info.duration)}" step="1" value="${Math.floor(d.clipStart)}" aria-label="Начало отрезка">
          <input type="range" id="clip-b" min="0" max="${Math.floor(info.duration)}" step="1" value="${Math.ceil(d.clipEnd)}" aria-label="Конец отрезка">
        </div>
      </div>` : "";
    const chosen = info.choices.find((c) => (c.height || 0) === (d.height || 0));
    const label = d.mode === "video" ? `Скачать видео${chosen ? " · " + chosen.label : ""}` : `Скачать звук · ${d.audioFormat.toUpperCase()}`;
    const hint = d.queued ? `${icon("check")} Добавлено в очередь — смотри ниже.` : (d.mode === "video" ? "Сохраню как MP4 H.264 + AAC — откроется в Premiere." : "Звук сохранится в папку сайта.");
    return `${pick}${clip}
      <label class="switch"><input type="checkbox" id="transcribe-after" ${d.transcribeAfter ? "checked" : ""}><div><b>Сразу расшифровать</b><span>После скачивания сделать текст и субтитры (настройки — во вкладке «Расшифровка»)</span></div></label>
      <div class="go"><span class="hint" id="go-hint">${hint}</span><button class="btn primary" type="button" data-action="start-download">${icon("download")}${esc(label)}</button></div>`;
  }

  function subtitleOptions() {
    const d = state.dl;
    if (d.tracks === "loading") return `<div class="row"><div class="spinner"></div><span class="meta">Ищу субтитры…</span></div>`;
    if (d.tracks && d.tracks.error) {
      return `<div class="notice bad">${icon("alert")}<div class="grow"><b>${esc(d.tracks.error.message)}</b><p>${esc(d.tracks.error.hint || "")}</p>
        <div class="row"><button class="btn small" type="button" data-action="load-tracks">${icon("retry")}Ещё раз</button></div></div></div>`;
    }
    const tracks = (d.tracks && d.tracks.tracks) || [];
    if (!tracks.length) {
      return `<div class="notice info">${icon("info")}<div class="grow"><b>У этого видео нет готовых субтитров.</b><p>Могу скачать звук и расшифровать речь сам — получится текст и SRT.</p>
        <div class="row"><button class="btn small" type="button" data-action="whisper-from-link">${icon("mic")}Скачать звук и расшифровать</button></div></div></div>`;
    }
    const formats = [["txt", "TXT — сплошной текст"], ["srt", "SRT — для монтажа"], ["vtt", "VTT — для сайтов"]];
    return `<div class="field"><span class="label">Дорожка</span><div class="track-list">${tracks.map((t) => `
        <button class="choice" type="button" data-action="track" data-track="${esc(t.id)}" aria-pressed="${d.trackId === t.id}">
          <span><b>${esc(t.name)}</b> <small class="mono">${esc(t.code)}</small></span>
          <span class="row" style="gap:6px">${t.original ? '<span class="badge accent">оригинал</span>' : ""}<span class="badge ${t.source === "manual" ? "ok" : ""}">${t.source === "manual" ? "вручную" : "автоматические"}</span></span>
        </button>`).join("")}</div></div>
      <div class="field"><span class="label">Сохранить как</span><div class="formats">${formats.map(([id, label]) => `<label class="check"><input type="checkbox" data-subfmt="${id}" ${d.subFormats.includes(id) ? "checked" : ""}>${label}</label>`).join("")}</div></div>
      <div class="go"><span class="hint">${d.queued ? `${icon("check")} Добавлено в очередь.` : "Whisper не нужен — беру готовые субтитры с сайта."}</span><button class="btn primary" type="button" data-action="start-subtitles">${icon("cc")}Сохранить субтитры</button></div>`;
  }

  function autoGrow(ta) {
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 220) + "px";
  }

  let analyzeTimer = null;
  function scheduleAnalyze(immediate = false) {
    clearTimeout(analyzeTimer);
    analyzeTimer = setTimeout(analyze, immediate ? 0 : 550);
  }

  async function analyze() {
    const d = state.dl;
    const urls = urlsIn(d.text);
    if (!urls.length) {
      if (d.status !== "idle") { d.status = "idle"; d.info = null; renderDownloadBody(); }
      return;
    }
    const key = urls.join("\n");
    if (key === d.lastKey && d.status !== "error") return;
    d.lastKey = key;
    const req = ++d.req;
    d.status = "analyzing";
    d.queued = false;
    d.tracks = null;
    renderDownloadBody();
    const result = await call("analyze", d.text);
    if (req !== d.req || !result || result.cancelled) return;
    if (!result.ok) {
      d.status = "error";
      d.error = result.error;
      d.blindUrl = result.url || urls[0];
      d.blindSite = result.site || "";
    } else if (result.kind === "batch") {
      d.status = "batch";
      d.urls = result.urls;
    } else {
      const info = result.info;
      d.status = "media";
      d.info = info;
      const prefer = Number(state.settings.download.height) || 1080;
      const heights = info.choices.map((c) => c.height || 0);
      d.height = heights.includes(prefer) ? prefer : (info.default_height || heights[0] || 0);
      d.mode = state.settings.download.mode || "video";
      if (d.mode === "subtitles" && !info.subtitle_tracks && info.platform !== "YouTube") d.mode = "video";
      d.audioFormat = state.settings.download.audio_format || "mp3";
      d.transcribeAfter = !!state.settings.download.transcribe_after;
      d.subFormats = state.settings.download.subtitle_formats || ["txt", "srt"];
      d.clipOn = false;
      d.clipStart = 0;
      d.clipEnd = info.duration || 0;
      if (d.mode === "subtitles") loadTracks();
    }
    renderDownloadBody();
  }

  async function loadTracks() {
    const d = state.dl;
    if (!d.info) return;
    const url = d.info.url;
    d.tracks = "loading";
    renderDownloadBody();
    const result = await call("subtitle_tracks", url);
    if (!d.info || d.info.url !== url) return;
    if (!result || !result.ok) d.tracks = { error: (result && result.error) || { message: "Не удалось получить субтитры." } };
    else {
      d.tracks = result.info;
      const first = (result.info.tracks || [])[0];
      d.trackId = first ? first.id : null;
    }
    renderDownloadBody();
  }

  function clipValid() {
    const d = state.dl;
    if (!d.clipOn) return true;
    const max = (d.info && d.info.duration) || Infinity;
    return d.clipEnd > d.clipStart && d.clipStart >= 0 && d.clipStart < max;
  }

  function syncClipUi(from) {
    const d = state.dl;
    const a = $("#clip-a"), b = $("#clip-b");
    if (!a || !b) return;
    if (from !== "range") { a.value = Math.floor(d.clipStart); b.value = Math.ceil(d.clipEnd); }
    if (from !== "text") { $("#clip-start").value = fmtTime(d.clipStart); $("#clip-end").value = fmtTime(d.clipEnd); }
    const max = Number(a.max) || 1;
    const sel = $("#clip-sel");
    sel.style.left = `${(d.clipStart / max) * 100}%`;
    sel.style.width = `${Math.max(0, (d.clipEnd - d.clipStart) / max) * 100}%`;
    const ok = clipValid();
    $("#clip-start").classList.toggle("invalid", !ok);
    $("#clip-end").classList.toggle("invalid", !ok);
    $("#clip-len").innerHTML = ok ? `Длина отрезка: <b class="num">${fmtTime(d.clipEnd - d.clipStart)}</b>` : '<b style="color:var(--bad)">Конец должен быть позже начала</b>';
  }

  // ---- transcribe page --------------------------------------------------------------------
  function fileRows(files, listName) {
    if (!files.length) return "";
    return `<div class="files">${files.map((f, i) => `<div class="file">${icon(f.kind === "audio" ? "music" : "film")}<span class="name" title="${esc(f.path)}">${esc(f.name)}</span><small class="num">${fmtSize(f.size)}</small>
      <button class="btn small ghost icon" type="button" data-action="remove-file" data-list="${listName}" data-index="${i}" aria-label="Убрать">${icon("x")}</button></div>`).join("")}</div>`;
  }

  function dropZone(listName, what) {
    return `<div class="drop" data-drop="${listName}">${icon("upload")}<b>Перетащи ${what} сюда</b><span>или</span>
      <button class="btn" type="button" data-action="pick-files" data-list="${listName}">${icon("folder")}Выбрать файлы</button></div>`;
  }

  function transcribePage() {
    const t = state.settings.transcribe || {};
    const files = state.tr.files;
    const g = gpuView();
    const formats = t.formats || ["txt", "srt"];
    const gpuLine = !g ? "" : g.cls === "on"
      ? `<div class="notice info">${icon("chip")}<div class="grow"><b>Считаю на видеокарте ${esc(g.title)}</b><p>Это в десятки раз быстрее, чем на процессоре.</p></div></div>`
      : g.cls === "off"
        ? `<div class="notice warn">${icon("chip")}<div class="grow"><b>Видеокарта ${esc(g.title)} не используется</b><p>Сейчас распознавание идёт на процессоре — это намного медленнее. Нужно один раз скачать библиотеки NVIDIA (~${state.gpu.download_mb || 810} МБ).</p>
          <div class="row"><button class="btn small" type="button" data-action="setup-gpu">${icon("download")}Включить ускорение</button></div></div></div>`
        : "";
    return `${head("Расшифровка речи", "Аудио или видео превращаются в текст и субтитры. Всё считается на этом компьютере — файлы никуда не отправляются.", "Transcripts")}
      ${dropZone("tr", "аудио или видео")}
      ${fileRows(files, "tr")}
      <div class="card"><div class="panel">
        <div class="settings-grid">
          <div class="field"><span class="label">Модель</span><div class="model-cards">${state.models.map((m) => `
            <button class="choice" type="button" data-action="model" data-model="${m.id}" aria-pressed="${(t.model || "turbo") === m.id}">
              <span class="top"><b>${esc(m.label)}</b>${m.installed ? '<span class="badge ok">скачана</span>' : `<small>${(m.size_mb / 1000).toFixed(1).replace(".", ",")} ГБ</small>`}</span>
              <span class="note">${esc(m.description)}</span></button>`).join("")}</div></div>
          <div class="field"><label for="tr-lang">Язык речи</label>
            <select class="input" id="tr-lang">${state.languages.map((l) => `<option value="${l.id}" ${(t.language || "mixed") === l.id ? "selected" : ""}>${esc(l.label)}</option>`).join("")}</select>
            <span class="meta">«Микс» сам определяет язык по фрагментам — если в записи говорят на разных языках. Перевода нет: текст будет на языке речи.</span>
          </div>
        </div>
        <div class="field"><span class="label">Результат</span><div class="formats">
          ${[["txt", "TXT — текст"], ["srt", "SRT — субтитры"], ["vtt", "VTT — субтитры для сайтов"]].map(([id, label]) => `<label class="check"><input type="checkbox" data-trfmt="${id}" ${formats.includes(id) ? "checked" : ""}>${label}</label>`).join("")}
          <label class="check"><input type="checkbox" id="tr-ts" ${t.timestamps ? "checked" : ""}>Таймкоды в тексте</label>
        </div></div>
        ${gpuLine}
        <div class="go"><span class="hint">${files.length ? `${files.length} ${plural(files.length, "файл", "файла", "файлов")} — каждый станет отдельным заданием.` : "Сначала добавь файлы."}</span>
          <button class="btn primary" type="button" data-action="start-transcribe" ${files.length ? "" : "disabled"}>${icon("mic")}Расшифровать${files.length > 1 ? ` ${files.length} ${plural(files.length, "файл", "файла", "файлов")}` : ""}</button></div>
      </div></div>
      <section class="dock" id="jobs-slot"></section>`;
  }

  // ---- convert page ---------------------------------------------------------------------------
  function convertPage() {
    const profile = (state.settings.convert && state.settings.convert.profile) || "premiere";
    const files = state.cv.files;
    return `${head("Конвертер видео", "Перевести видео в формат для монтажа, уменьшить размер или достать звук.", "Converted")}
      ${dropZone("cv", "видео")}
      ${fileRows(files, "cv")}
      <div class="card"><div class="panel">
        <div class="field"><span class="label">Во что превратить</span><div class="profile-grid">${state.profiles.map((p) => `
          <button class="choice" type="button" data-action="profile" data-profile="${p.id}" aria-pressed="${profile === p.id}">
            <span class="top"><b>${esc(p.label)}</b>${p.audio_only ? icon("music") : ""}</span><span class="note">${esc(p.description)}</span></button>`).join("")}</div></div>
        ${state.app.platform === "windows" ? `<label class="switch"><input type="checkbox" id="gpu-encoder" ${state.settings.gpu_encoder !== false ? "checked" : ""}><div><b>Кодировать на видеокарте</b><span>H.264 и H.265 в несколько раз быстрее на NVIDIA. Если видеокарта не справится — автоматически перейду на процессор.</span></div></label>` : ""}
        <div class="go"><span class="hint">${files.length ? `${files.length} ${plural(files.length, "файл", "файла", "файлов")} в очереди на конвертацию.` : "Сначала добавь файлы."}</span>
          <button class="btn primary" type="button" data-action="start-convert" ${files.length ? "" : "disabled"}>${icon("convert")}Конвертировать</button></div>
      </div></div>
      <section class="dock" id="jobs-slot"></section>`;
  }

  // ---- jobs ------------------------------------------------------------------------------------
  const KIND_ICON = { download: "download", subtitles: "cc", transcribe: "mic", convert: "convert", gpu_setup: "chip" };
  const STATE_LABEL = { queued: "в очереди", running: "идёт", done: "готово", error: "ошибка", cancelled: "отменено" };

  function sortedJobs() {
    const rank = { running: 0, queued: 1 };
    return [...state.jobs.values()].sort((a, b) => {
      const ra = rank[a.state] ?? 2, rb = rank[b.state] ?? 2;
      if (ra !== rb) return ra - rb;
      return (b.finished || b.created || 0) - (a.finished || a.created || 0);
    });
  }

  function jobCard(job) {
    const running = job.state === "running";
    const active = running || job.state === "queued";
    const thumb = job.meta && job.meta.thumbnail ? `<img src="${esc(job.meta.thumbnail)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : "";
    const progress = running
      ? `<div class="bar ${job.progress == null ? "indeterminate" : ""}"><i style="width:${job.progress || 0}%"></i></div>`
      : "";
    const first = (job.outputs || [])[0];
    const acts = [];
    if (active) acts.push(`<button class="btn small" type="button" data-action="cancel-job" data-id="${job.id}">${icon("stop")}Отмена</button>`);
    if (job.state === "done" && first && job.kind !== "gpu_setup") {
      acts.push(`<button class="btn small" type="button" data-action="open-file" data-path="${esc(first)}">${icon("play")}Открыть</button>`);
      acts.push(`<button class="btn small ghost icon" type="button" data-action="reveal" data-path="${esc(first)}" title="Показать в папке" aria-label="Показать в папке">${icon("folder")}</button>`);
      if (job.kind === "download" && /\.(mp4|mov|mkv|webm|mp3|m4a|wav|opus|ogg|flac|aac)$/i.test(first)) {
        acts.push(`<button class="btn small ghost icon" type="button" data-action="transcribe-output" data-path="${esc(first)}" title="Расшифровать" aria-label="Расшифровать">${icon("mic")}</button>`);
      }
    }
    if (job.state === "error" || job.state === "cancelled") acts.push(`<button class="btn small" type="button" data-action="retry-job" data-id="${job.id}">${icon("retry")}Повторить</button>`);
    acts.push(`<button class="btn small ghost icon" type="button" data-action="toggle-log" data-id="${job.id}" title="Подробности" aria-label="Подробности" aria-expanded="${state.openLogs.has(job.id)}">${icon("list")}</button>`);
    if (!active) acts.push(`<button class="btn small ghost icon" type="button" data-action="remove-job" data-id="${job.id}" title="Убрать из списка" aria-label="Убрать из списка">${icon("x")}</button>`);
    const stage = job.state === "queued" ? "В очереди" : job.state === "cancelled" ? "Отменено" : (job.stage || STATE_LABEL[job.state]);
    const hint = job.state === "error" && job.error && job.error.hint ? `<div class="hint">${esc(job.error.hint)}</div>` : "";
    const log = state.openLogs.has(job.id) ? `<div class="log"><pre id="log-${job.id}">${esc(((state.logs.get(job.id) || {}).lines || []).join("\n")) || "Журнал пока пуст."}</pre>
      <div class="row"><button class="btn small" type="button" data-action="copy-log" data-id="${job.id}">${icon("copy")}Скопировать журнал</button></div></div>` : "";
    return `<div class="job ${job.state}" data-job="${job.id}">
      <div class="ico">${icon(KIND_ICON[job.kind] || "file")}${thumb}</div>
      <div class="title" title="${esc(job.title)}">${esc(job.title)}</div>
      <div class="acts">${acts.join("")}</div>
      <div class="stage" title="${esc(stage)}">${esc(stage)}</div>
      ${progress}${hint}${log}
    </div>`;
  }

  function renderJobsSlot() {
    const slot = $("#jobs-slot");
    if (!slot) return;
    if (state.page === "jobs") {
      const all = sortedJobs();
      const filter = state.jobsFilter;
      const shown = all.filter((j) => filter === "all" || (filter === "active" ? ["running", "queued"].includes(j.state) : filter === "done" ? j.state === "done" : ["error", "cancelled"].includes(j.state)));
      slot.innerHTML = shown.length ? `<div class="jobs">${shown.map(jobCard).join("")}</div>`
        : `<div class="empty"><b>${all.length ? "Здесь пусто" : "Заданий пока нет"}</b>Скачай видео или расшифруй файл — задания появятся здесь.</div>`;
      const counts = $("#job-counts");
      if (counts) counts.textContent = jobCounts();
    } else {
      const active = sortedJobs().filter((j) => ["running", "queued"].includes(j.state));
      const recent = sortedJobs().filter((j) => !["running", "queued"].includes(j.state)).slice(0, Math.max(0, 3 - Math.min(active.length, 3)));
      const list = [...active, ...recent];
      slot.innerHTML = list.length ? `<div class="dock-head"><h2>Задания</h2><button class="btn small ghost" type="button" data-action="nav" data-page="jobs">Все задания${icon("chevron")}</button></div><div class="jobs" style="margin-top:10px">${list.map(jobCard).join("")}</div>` : "";
    }
    renderNav();
  }

  function jobCounts() {
    const all = [...state.jobs.values()];
    const c = (s) => all.filter((j) => s.includes(j.state)).length;
    return `Идёт: ${c(["running"])} · в очереди: ${c(["queued"])} · готово: ${c(["done"])} · с ошибкой: ${c(["error"])}`;
  }

  function jobsPage() {
    const filters = [["all", "Все"], ["active", "Идут"], ["done", "Готово"], ["failed", "Ошибки"]];
    return `<div class="page-head"><div><h1>Задания</h1><p id="job-counts">${jobCounts()}</p></div>
      <button class="btn" type="button" data-action="clear-finished">${icon("trash")}Убрать завершённые</button></div>
      <div class="filters">${filters.map(([id, label]) => `<button class="btn small ${state.jobsFilter === id ? "" : "ghost"}" type="button" data-action="jobs-filter" data-filter="${id}" aria-pressed="${state.jobsFilter === id}">${label}</button>`).join("")}</div>
      <section id="jobs-slot"></section>`;
  }

  async function refreshLog(id) {
    const prev = state.logs.get(id) || { lines: [], seq: 0 };
    const res = await call("job_log", id, prev.seq);
    if (!res) return;
    const lines = prev.seq && res.seq >= prev.seq ? prev.lines.concat(res.lines).slice(-3000) : res.lines;
    state.logs.set(id, { lines, seq: res.seq });
    const pre = document.getElementById(`log-${id}`);
    if (pre) {
      const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
      pre.textContent = lines.join("\n") || "Журнал пока пуст.";
      if (atBottom) pre.scrollTop = pre.scrollHeight;
    }
  }
  setInterval(() => {
    for (const id of state.openLogs) {
      const job = state.jobs.get(id);
      if (job && ["running", "queued"].includes(job.state)) refreshLog(id);
    }
  }, 1200);

  // ---- settings page -------------------------------------------------------------------------------
  function settingsPage() {
    const s = state.settings;
    const g = state.gpu || {};
    const sys = state.app.platform === "mac" ? "Как в системе" : "Как в Windows";
    const gpuRow = state.app.platform !== "windows" ? "" : `
      <div class="set-row"><div class="txt"><b>Ускорение NVIDIA</b><span>${g.ready
        ? `Работает на ${esc(g.gpu && g.gpu.name || "видеокарте")}${g.libs_source === "znambo" ? " · библиотеки взяты из ZNAMBO Transcriber" : ""}.`
        : g.gpu ? `Видеокарта ${esc(g.gpu.name)} найдена, но библиотек NVIDIA нет — расшифровка идёт на процессоре.` : "Видеокарта NVIDIA не найдена — расшифровка идёт на процессоре."}</span></div>
        ${!g.ready && g.gpu ? `<button class="btn" type="button" data-action="setup-gpu">${icon("download")}Включить (~${g.download_mb || 810} МБ)</button>` : g.ready ? '<span class="badge ok">включено</span>' : ""}</div>`;
    const models = state.models.map((m) => `<div class="set-row"><div class="txt"><b>Модель «${esc(m.label)}»</b><span>${m.installed ? `Скачана${m.shared_with_znambo ? " (общая с ZNAMBO Transcriber)" : ""} · ${esc(m.location)}` : `Скачается при первой расшифровке · ${(m.size_mb / 1000).toFixed(1).replace(".", ",")} ГБ`}</span></div>${m.installed ? '<span class="badge ok">готова</span>' : '<span class="badge">не скачана</span>'}</div>`).join("");
    const c = state.cookies || {};
    const yt = (state.tools || {})["yt-dlp"] || {};
    const checked = yt.checked ? new Date(yt.checked * 1000).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) : "ещё не проверялся";
    return `<div class="page-head"><div><h1>Настройки</h1><p>Сохраняются сами и не сбрасываются после перезапуска.</p></div></div>
      <div class="set-title">Внешний вид</div>
      <div class="card set-group"><div class="set-row"><div class="txt"><b>Тема</b><span>«${sys}» переключается вместе с системой.</span></div>
        <div class="seg">${[["system", "monitor", sys], ["light", "sun", "Светлая"], ["dark", "moon", "Тёмная"]].map(([id, ic, label]) => `<button type="button" data-action="theme" data-theme="${id}" aria-pressed="${(s.theme || "system") === id}">${icon(ic)}${label}</button>`).join("")}</div></div></div>

      <div class="set-title">Сохранение</div>
      <div class="card set-group"><div class="set-row"><div class="txt"><b>Папка для результатов</b><span class="mono">${esc(s.output_root)}</span><br><span>Внутри — папки по сайтам, Transcripts, Subtitles и Converted.</span></div>
        <div class="row"><button class="btn" type="button" data-action="open-output" data-sub="">${icon("folder")}Открыть</button><button class="btn" type="button" data-action="pick-folder">Изменить</button></div></div></div>

      <div class="set-title">Расшифровка речи</div>
      <div class="card set-group">${gpuRow}${models}</div>

      <div class="set-title">Скачивание</div>
      <div class="card set-group">
        ${state.app.platform === "windows" ? `<div class="set-row"><label class="switch"><input type="checkbox" id="gpu-encoder" ${s.gpu_encoder !== false ? "checked" : ""}><div><b>Перекодировать на видеокарте</b><span>Когда видео приходится переводить в H.264 для Premiere (4K, VP9, AV1) — в разы быстрее на NVIDIA.</span></div></label></div>` : ""}
        <div class="set-row"><div class="txt"><b>${icon("key")} Вход на сайты</b><span>${c.file ? `Используется файл cookies${c.domains && c.domains.length ? ": " + esc(c.domains.slice(0, 6).join(", ")) + (c.domains.length > 6 ? " и др." : "") : ""}.` : "Нужен для закрытых и 18+ видео, Instagram и сайтов, которые просят войти. Без него программа сама пробует вход через Firefox."}</span>
          <br><span>Как получить: поставь в браузер расширение «Get cookies.txt LOCALLY», открой сайт, где ты уже вошёл, нажми Export и выбери этот файл здесь.</span></div>
          <div class="row"><button class="btn" type="button" data-action="import-cookies">${icon("upload")}${c.file ? "Заменить файл" : "Выбрать файл cookies"}</button>${c.own ? `<button class="btn ghost danger" type="button" data-action="remove-cookies">${icon("trash")}Удалить</button>` : ""}</div></div>
      </div>

      <div class="set-title">Обновления</div>
      <div class="card set-group">
        <div class="set-row"><div class="txt"><b>Загрузчик видео (yt-dlp)</b><span>Версия <span class="num">${esc(yt.version || "—")}</span> · проверено: ${esc(checked)}. Сайты часто меняются — программа сама обновляет загрузчик раз в день.</span></div>
          <div class="row"><label class="check"><input type="checkbox" id="auto-tools" ${s.auto_update_tools !== false ? "checked" : ""}>Автоматически</label><button class="btn" type="button" data-action="update-tools">${icon("retry")}Обновить сейчас</button></div></div>
        <div class="set-row"><div class="txt"><b>RNGN Media ${esc(state.app.version)}</b><span>${state.update && state.update.version ? `Доступна версия ${esc(state.update.version)}.` : "Установлена последняя версия."}</span></div>
          <div class="row">${state.update && state.update.url ? `<button class="btn" type="button" data-action="open-url" data-url="${esc(state.update.url)}">${icon("external")}Скачать</button>` : ""}<button class="btn" type="button" data-action="check-app">${icon("retry")}Проверить</button></div></div>
      </div>`;
  }

  // ---- actions --------------------------------------------------------------------------------------
  function go(page) {
    state.page = page;
    renderNav();
    renderPage();
    $("#scroll").scrollTop = 0;
  }

  function addJobs(list) {
    for (const job of [].concat(list || [])) if (job && job.id) state.jobs.set(job.id, job);
    renderJobsSlot();
  }

  function addFiles(listName, files) {
    const target = listName === "cv" ? state.cv.files : state.tr.files;
    const known = new Set(target.map((f) => f.path));
    let skipped = 0;
    for (const f of files || []) {
      const ok = listName === "cv" ? f.kind === "video" || f.kind === "audio" : f.transcribable;
      if (!ok) { skipped++; continue; }
      if (!known.has(f.path)) { target.push(f); known.add(f.path); }
    }
    if (skipped) toast("bad", `${skipped} ${plural(skipped, "файл не подходит", "файла не подходят", "файлов не подходят")}`, listName === "cv" ? "Нужны видео или аудио." : "Нужны аудио или видео (MP3, M4A, WAV, MP4, MOV…).");
  }

  const actions = {
    nav: (el) => go(el.dataset.page),
    theme: async (el) => { await saveSettings({ theme: el.dataset.theme }); applyTheme(); if (state.page === "settings") renderPage(); },
    "open-output": (el) => call("open_output", el.dataset.sub || ""),
    "open-url": (el) => call("open_url", el.dataset.url),
    paste: async () => {
      const text = await call("read_clipboard");
      const ta = $("#link");
      if (!text || !ta) { toast("info", "В буфере обмена нет ссылки"); return; }
      ta.value = text.trim();
      state.dl.text = ta.value;
      autoGrow(ta);
      scheduleAnalyze(true);
    },
    "clear-link": () => {
      const ta = $("#link");
      if (ta) { ta.value = ""; ta.focus(); autoGrow(ta); }
      Object.assign(state.dl, { text: "", status: "idle", info: null, lastKey: "", queued: false });
      call("cancel_analysis");
      renderDownloadBody();
    },
    "cancel-analysis": () => { call("cancel_analysis"); Object.assign(state.dl, { status: "idle", lastKey: "" }); state.dl.req++; renderDownloadBody(); },
    reanalyze: () => { state.dl.lastKey = ""; analyze(); },
    "download-blind": async () => {
      const d = state.dl;
      const job = await call("start_download", { url: d.blindUrl, title: d.blindUrl, site: d.blindSite, mode: "video", height: Number(state.settings.download.height) || 1080, exact: false });
      if (job) { addJobs(job); toast("ok", "Добавлено в очередь", "Скачаю в лучшем доступном качестве до 1080p."); }
    },
    mode: (el) => {
      const d = state.dl;
      d.mode = el.dataset.mode;
      d.queued = false;
      saveSettings({ download: { mode: d.mode } });
      if (d.mode === "subtitles" && !d.tracks) loadTracks();
      renderDownloadBody();
    },
    height: (el) => { state.dl.height = Number(el.dataset.height) || 0; state.dl.queued = false; if (state.dl.height) saveSettings({ download: { height: state.dl.height } }); renderDownloadBody(); },
    "audio-format": (el) => { state.dl.audioFormat = el.dataset.format; state.dl.queued = false; saveSettings({ download: { audio_format: el.dataset.format } }); renderDownloadBody(); },
    track: (el) => { state.dl.trackId = el.dataset.track; state.dl.queued = false; renderDownloadBody(); },
    "load-tracks": () => loadTracks(),
    "start-download": async () => {
      const d = state.dl, info = d.info;
      if (!info) return;
      if (!clipValid()) { toast("bad", "Проверь отрезок", "Конец должен быть позже начала."); return; }
      const job = await call("start_download", {
        url: info.url, title: info.title, thumbnail: info.thumbnail, site: info.site, duration: info.duration,
        mode: d.mode === "audio" ? "audio" : "video", height: d.height || null,
        exact: info.choices.some((c) => (c.height || 0) === (d.height || 0) && c.height), audio_format: d.audioFormat,
        clip: d.clipOn ? [d.clipStart, d.clipEnd] : null, access: info.access, transcribe_after: d.transcribeAfter,
      });
      if (job) { addJobs(job); d.queued = true; renderDownloadBody(); }
    },
    "start-subtitles": async () => {
      const d = state.dl;
      const track = ((d.tracks && d.tracks.tracks) || []).find((t) => t.id === d.trackId);
      if (!track) { toast("bad", "Выбери дорожку субтитров"); return; }
      if (!d.subFormats.length) { toast("bad", "Отметь хотя бы один формат"); return; }
      const job = await call("start_subtitles", { url: d.info.url, track, formats: d.subFormats, title: d.info.title, site: d.info.site, thumbnail: d.info.thumbnail });
      if (job) { addJobs(job); d.queued = true; renderDownloadBody(); }
    },
    "whisper-from-link": async () => {
      const info = state.dl.info;
      const job = await call("start_download", { url: info.url, title: info.title, thumbnail: info.thumbnail, site: info.site, mode: "audio", audio_format: "m4a", access: info.access, transcribe_after: true });
      if (job) { addJobs(job); toast("ok", "Скачаю звук и расшифрую", "Текст появится в папке Transcripts."); }
    },
    "start-batch": async () => {
      const d = state.dl;
      const urls = d.status === "batch" ? d.urls.map((u) => u.url) : ((d.info && d.info.entries) || []).map((e) => e.url);
      const jobs = await call("start_batch", urls, { mode: d.mode === "audio" ? "audio" : "video", height: d.batchHeight || null, audio_format: d.audioFormat, transcribe_after: d.transcribeAfter });
      if (jobs) { addJobs(jobs); toast("ok", `Добавлено в очередь: ${jobs.length}`); }
    },
    "pick-files": async (el) => {
      const paths = await call("pick_files", el.dataset.list === "cv" ? "video" : "media");
      if (!paths || !paths.length) return;
      addFiles(el.dataset.list, await call("describe_files", paths));
      renderPage();
    },
    "remove-file": (el) => { (el.dataset.list === "cv" ? state.cv.files : state.tr.files).splice(Number(el.dataset.index), 1); renderPage(); },
    model: (el) => { saveSettings({ transcribe: { model: el.dataset.model } }).then(renderPage); },
    profile: (el) => { saveSettings({ convert: { profile: el.dataset.profile } }).then(renderPage); },
    "start-transcribe": async () => {
      const files = state.tr.files.map((f) => f.path);
      const jobs = await call("start_transcribe", files, state.settings.transcribe);
      if (jobs) { state.tr.files = []; addJobs(jobs); renderPage(); }
    },
    "start-convert": async () => {
      const files = state.cv.files.map((f) => f.path);
      const jobs = await call("start_convert", files, (state.settings.convert && state.settings.convert.profile) || "premiere");
      if (jobs) { state.cv.files = []; addJobs(jobs); renderPage(); }
    },
    "cancel-job": (el) => call("cancel_job", el.dataset.id),
    "retry-job": async (el) => { const job = await call("retry_job", el.dataset.id); if (job) addJobs(job); },
    "remove-job": async (el) => { if (await call("remove_job", el.dataset.id)) { state.jobs.delete(el.dataset.id); renderJobsSlot(); } },
    "clear-finished": async () => { await call("clear_finished"); for (const [id, j] of state.jobs) if (!["running", "queued"].includes(j.state)) state.jobs.delete(id); renderJobsSlot(); },
    "jobs-filter": (el) => { state.jobsFilter = el.dataset.filter; renderPage(); },
    "toggle-log": async (el) => {
      const id = el.dataset.id;
      if (state.openLogs.has(id)) state.openLogs.delete(id);
      else { state.openLogs.add(id); await refreshLog(id); }
      renderJobsSlot();
    },
    "copy-log": async (el) => {
      const lines = ((state.logs.get(el.dataset.id) || {}).lines || []).join("\n");
      let ok = false;
      try { await navigator.clipboard.writeText(lines); ok = true; } catch (_) { ok = await call("copy_text", lines); }
      toast(ok ? "ok" : "bad", ok ? "Журнал скопирован" : "Не удалось скопировать");
    },
    "open-file": (el) => call("open_path", el.dataset.path),
    reveal: (el) => call("reveal_path", el.dataset.path),
    "transcribe-output": async (el) => {
      const jobs = await call("start_transcribe", [el.dataset.path], state.settings.transcribe);
      if (jobs) { addJobs(jobs); toast("ok", "Расшифровка добавлена в очередь"); }
    },
    "setup-gpu": async () => { const job = await call("setup_gpu"); if (job) { addJobs(job); toast("ok", "Скачиваю библиотеки NVIDIA", "Прогресс — в «Заданиях»."); } },
    "pick-folder": async () => { const s = await call("pick_folder"); if (s) { state.settings = s; renderPage(); } },
    "import-cookies": async () => {
      const res = await call("import_cookies");
      if (!res) return;
      state.cookies = res.cookies || state.cookies;
      if (res.ok) toast("ok", "Файл cookies сохранён", (state.cookies.domains || []).slice(0, 4).join(", "));
      else if (res.error) toast("bad", res.error.message, res.error.hint || "");
      renderPage();
    },
    "remove-cookies": async () => { state.cookies = (await call("remove_cookies")) || {}; renderPage(); },
    "update-tools": async (el) => {
      el.disabled = true;
      el.innerHTML = `<span class="spinner" style="width:16px;height:16px"></span>Проверяю…`;
      const tools = await call("update_tools_now");
      if (tools) state.tools = tools;
      const st = (tools && tools["yt-dlp"] && tools["yt-dlp"].status) || "";
      toast("ok", st === "updated" ? "Загрузчик обновлён" : "Загрузчик уже последней версии");
      renderPage();
    },
    "check-app": async () => {
      const u = await call("check_app_update");
      state.update = u;
      toast(u ? "ok" : "info", u ? `Доступна версия ${u.version}` : "Установлена последняя версия");
      renderPage();
    },
  };

  document.addEventListener("click", (event) => {
    const el = event.target.closest("[data-action]");
    if (!el || el.disabled) return;
    const fn = actions[el.dataset.action];
    if (fn) { event.preventDefault(); fn(el, event); }
  });

  document.addEventListener("input", (event) => {
    const el = event.target;
    const d = state.dl;
    if (el.id === "link") {
      d.text = el.value;
      autoGrow(el);
      scheduleAnalyze();
    } else if (el.id === "clip-a" || el.id === "clip-b") {
      const a = Number($("#clip-a").value), b = Number($("#clip-b").value);
      d.clipStart = Math.min(a, b);
      d.clipEnd = Math.max(a, b);
      if (d.clipEnd === d.clipStart) d.clipEnd = Math.min(Number($("#clip-a").max), d.clipStart + 1);
      syncClipUi("range");
    } else if (el.id === "clip-start" || el.id === "clip-end") {
      const v = parseTime(el.value);
      if (!isNaN(v)) {
        if (el.id === "clip-start") d.clipStart = v; else d.clipEnd = v;
      }
      syncClipUi("text");
    }
  });

  document.addEventListener("change", (event) => {
    const el = event.target;
    const d = state.dl;
    if (el.id === "clip-on") { d.clipOn = el.checked; $("#clip-box").hidden = !el.checked; if (el.checked) syncClipUi(); }
    else if (el.id === "transcribe-after") { d.transcribeAfter = el.checked; saveSettings({ download: { transcribe_after: el.checked } }); }
    else if (el.id === "batch-height") d.batchHeight = Number(el.value) || 0;
    else if (el.dataset.subfmt) {
      const set = new Set(d.subFormats);
      el.checked ? set.add(el.dataset.subfmt) : set.delete(el.dataset.subfmt);
      d.subFormats = ["txt", "srt", "vtt"].filter((f) => set.has(f));
      saveSettings({ download: { subtitle_formats: d.subFormats } });
    } else if (el.dataset.trfmt) {
      const set = new Set(state.settings.transcribe.formats || ["txt", "srt"]);
      el.checked ? set.add(el.dataset.trfmt) : set.delete(el.dataset.trfmt);
      const formats = ["txt", "srt", "vtt"].filter((f) => set.has(f));
      saveSettings({ transcribe: { formats: formats.length ? formats : ["txt"] } }).then(() => { if (!formats.length) renderPage(); });
    } else if (el.id === "tr-lang") saveSettings({ transcribe: { language: el.value } });
    else if (el.id === "tr-ts") saveSettings({ transcribe: { timestamps: el.checked } });
    else if (el.id === "gpu-encoder") saveSettings({ gpu_encoder: el.checked });
    else if (el.id === "auto-tools") saveSettings({ auto_update_tools: el.checked });
  });

  document.addEventListener("keydown", (event) => {
    if (event.target.id === "link" && event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      state.dl.lastKey = "";
      scheduleAnalyze(true);
    }
  });

  // Drag-and-drop visuals; the actual file paths arrive from Python (files_dropped).
  let dragDepth = 0;
  document.addEventListener("dragenter", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { dragDepth++; document.body.classList.add("dragging"); } });
  document.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) document.body.classList.remove("dragging"); });
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    document.body.classList.remove("dragging");
    if (state.api && state.api.__mock && e.dataTransfer && e.dataTransfer.files.length) {
      window.rngn.receive({ type: "files_dropped", files: state.api.__describe(e.dataTransfer.files) });
    }
  });

  // ---- events from Python --------------------------------------------------------------------------------
  window.rngn = {
    toast,
    receive(event) {
      if (!event || !event.type) return;
      if (event.type === "jobs") {
        for (const job of event.jobs || []) state.jobs.set(job.id, job);
        renderJobsSlot();
      } else if (event.type === "job_removed") {
        state.jobs.delete(event.id);
        renderJobsSlot();
      } else if (event.type === "jobs_reset") {
        state.jobs = new Map((event.jobs || []).map((j) => [j.id, j]));
        renderJobsSlot();
      } else if (event.type === "job_done") {
        const job = state.jobs.get(event.id);
        const first = job && (job.outputs || [])[0];
        toast("ok", `Готово: ${event.title}`, event.summary || "", first ? { label: "Открыть", run: () => call("open_path", first) } : null);
      } else if (event.type === "files_dropped") {
        const target = state.page === "convert" ? "cv" : "tr";
        addFiles(target, event.files);
        if (state.page !== "convert" && state.page !== "transcribe") go("transcribe");
        else renderPage();
      } else if (event.type === "tools") {
        state.tools = event.tools || state.tools;
        if (state.page === "settings") renderPage();
      } else if (event.type === "app_update") {
        state.update = event.update;
        if (["download", "transcribe", "convert"].includes(state.page)) renderPage();
      } else if (event.type === "gpu") {
        state.gpu = event.status || state.gpu;
        renderNav();
        if (["transcribe", "settings"].includes(state.page)) renderPage();
      }
    },
  };

  // ---- start ------------------------------------------------------------------------------------------------------
  function waitForApi() {
    return new Promise((resolve) => {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.bootstrap) return resolve(window.pywebview.api);
      window.addEventListener("pywebviewready", () => resolve(window.pywebview.api), { once: true });
      const fallback = () => { if (window.RNGN_MOCK) resolve(window.RNGN_MOCK); };
      if (window.RNGN_MOCK) setTimeout(fallback, 150);
    });
  }

  async function start() {
    state.api = await waitForApi();
    const boot = await call("bootstrap");
    if (!boot) return;
    state.app = boot.app;
    state.settings = boot.settings;
    state.gpu = boot.gpu;
    state.models = boot.models;
    state.languages = boot.languages;
    state.profiles = boot.profiles;
    state.tools = boot.tools;
    state.cookies = boot.cookies;
    state.update = boot.update && boot.update.version ? boot.update : null;
    state.jobs = new Map((boot.jobs || []).map((j) => [j.id, j]));
    state.dl.batchHeight = Number(state.settings.download.height) || 1080;
    if (boot.demo) Object.assign(state.dl, boot.demo.dl || {});
    applyTheme();
    renderNav();
    renderPage();
    if (boot.demo && boot.demo.text) {
      const ta = $("#link");
      if (ta) { ta.value = boot.demo.text; state.dl.text = boot.demo.text; autoGrow(ta); }
    }
  }

  start();
})();
