/* Clickable-preview backend: same methods as rngn/api.py, example data only.
   Nothing is downloaded; jobs just play a believable progress script. */
(() => {
  "use strict";
  const ROOT = "C:\\Users\\RNGN\\Videos\\RNGN Media";
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const now = () => Date.now() / 1000;
  let seq = 1;
  const id = () => `demo${seq++}`;

  const settings = {
    output_root: ROOT,
    theme: "system",
    download: { mode: "video", height: 1080, audio_format: "mp3", transcribe_after: false, subtitle_formats: ["txt", "srt"] },
    transcribe: { model: "turbo", language: "mixed", timestamps: false, formats: ["txt", "srt"], use_gpu: true },
    convert: { profile: "premiere" },
    gpu_encoder: true,
    auto_update_tools: true,
    check_app_updates: true,
  };

  const CHOICES = [
    { height: 2160, label: "2160p", note: "VP9 → перекодирую в H.264", direct: false, fps: 50, size: 612e6 },
    { height: 1440, label: "1440p", note: "VP9 → перекодирую в H.264", direct: false, fps: 50, size: 318e6 },
    { height: 1080, label: "1080p", note: "H.264 + AAC · без перекодирования", direct: true, fps: 50, size: 182e6 },
    { height: 720, label: "720p", note: "H.264 + AAC · без перекодирования", direct: true, fps: 50, size: 96e6 },
    { height: 480, label: "480p", note: "H.264 + AAC · без перекодирования", direct: true, fps: 25, size: 41e6 },
    { height: 360, label: "360p", note: "H.264 + AAC · без перекодирования", direct: true, fps: 25, size: 24e6 },
  ];
  const sampleInfo = (url, site = "YouTube", platform = "YouTube") => ({
    url, platform, site, kind: "video",
    title: "Пример: все голы матча СКА — ЦСКА, 3:2 ОТ",
    uploader: "Пример канала", duration: 754, thumbnail: "", is_live: false,
    choices: platform === "VK" ? CHOICES.slice(2) : CHOICES, default_height: 1080,
    audio_note: "AAC", access: { client: null, browser: null, label: "обычный режим" }, entries: [], subtitle_tracks: 2,
  });
  const siteOf = (url) => {
    const h = (url.match(/^https?:\/\/([^/]+)/i) || [])[1] || "";
    if (/youtu/.test(h)) return ["YouTube", "YouTube"];
    if (/vk\.|vkvideo/.test(h)) return ["VK Видео", "VK"];
    if (/rutube/.test(h)) return ["Rutube", "Rutube"];
    if (/tiktok/.test(h)) return ["TikTok", "TikTok"];
    if (/instagram/.test(h)) return ["Instagram", "Instagram"];
    return [h.replace(/^www\./, "") || "Сайт", "Other"];
  };

  const jobs = new Map();
  const job = (kind, title, extra = {}) => ({
    id: id(), kind, title, meta: {}, state: "queued", progress: 0, stage: "В очереди", created: now(),
    started: null, finished: null, outputs: [], summary: "", error: null, parent: null, log_seq: 0, params: {}, ...extra,
  });
  const logs = new Map();
  const say = (j, line) => { const l = logs.get(j.id) || []; l.push(`${new Date().toLocaleTimeString("ru-RU")}  ${line}`); logs.set(j.id, l); j.log_seq = l.length; };

  // Example history shown on first open.
  const seed = [
    job("download", "Пример: финал Кубка Гагарина, лучшие моменты", { meta: { site: "YouTube" }, params: { mode: "video" }, script: "video", state: "queued" }),
    job("transcribe", "Пример: пресс-конференция после матча", { meta: {}, params: {}, script: "transcribe" }),
    job("transcribe", "Пример: интервью с капитаном", {
      state: "done", progress: 100, finished: now() - 600,
      summary: "Готово за 1:42 · видеокарта · Русский 86%, English 14%",
      stage: "Готово за 1:42 · видеокарта · Русский 86%, English 14%",
      outputs: [`${ROOT}\\Transcripts\\Пример интервью.transcript.txt`, `${ROOT}\\Transcripts\\Пример интервью.subtitles.srt`],
    }),
    job("download", "instagram.com/reel/пример", {
      state: "error", finished: now() - 1800, meta: { site: "Instagram" },
      stage: "Instagram требует вход в аккаунт.",
      error: { message: "Instagram требует вход в аккаунт.", hint: "Войди на сайт в Firefox или загрузи файл cookies в «Настройки → Вход на сайты», затем повтори.", kind: "auth" },
    }),
    job("convert", "Пример: камера 2 → MP4 для Premiere", {
      state: "done", progress: 100, finished: now() - 3600, summary: "Сохранено: Камера 2.premiere.mp4",
      stage: "Сохранено: Камера 2.premiere.mp4", outputs: [`${ROOT}\\Converted\\Камера 2.premiere.mp4`],
    }),
  ];
  seed.forEach((j) => { jobs.set(j.id, j); say(j, j.state === "error" ? "ERROR: [Instagram] Requested content is not available, rate-limit reached or login required" : "Пример записи журнала"); });

  const SCRIPTS = {
    video: [
      { to: 70, step: 0.9, stage: (p) => `Скачиваю видео · ${Math.round(p / 0.85)}% · 18,4 МБ/с · осталось 00:${String(Math.max(1, Math.round((70 - p) / 3))).padStart(2, "0")}`, log: "[download] Destination: Пример.f137.mp4" },
      { to: 85, step: 2.5, stage: () => "Собираю видео и звук в один файл…", log: "[Merger] Merging formats into \"Пример.mp4\"" },
      { to: 100, step: 7.5, stage: () => "Готово", log: "FFprobe: видео=h264; звук=aac — перекодирование не нужно" },
    ],
    audio: [
      { to: 85, step: 2, stage: (p) => `Скачиваю звук · ${Math.round(p / 0.85)}% · 9,1 МБ/с`, log: "[download] Destination: Пример.webm" },
      { to: 100, step: 7.5, stage: () => "Конвертирую звук…", log: "[ExtractAudio] Destination: Пример.mp3" },
    ],
    transcribe: [
      { to: 4, step: 4, stage: () => "Загружаю модель «Быстрая» · видеокарта…", log: "model=large-v3-turbo device=cuda compute=float16" },
      { to: 100, step: 1.2, stage: (p) => `Распознаю речь · ${Math.round(p)}% · Русский · видеокарта`, log: "language chunk: ru (98%)" },
    ],
    subtitles: [{ to: 100, step: 25, stage: () => "Скачиваю субтитры · Русский", log: "Резервный способ yt-dlp · mweb" }],
    convert: [{ to: 100, step: 1.5, stage: (p) => `MP4 для Premiere · видеокарта · ${Math.round(p)}%`, log: "-c:v h264_nvenc -preset p7 -cq 16" }],
    gpu: [{ to: 100, step: 0.8, stage: (p) => `Скачиваю библиотеки NVIDIA · ${Math.round(p * 8.1)} из 810 МБ`, log: "Источник: Purfview cuBLAS/cuDNN" }],
  };
  const LANE = { download: "net", subtitles: "net", transcribe: "work", convert: "work", gpu_setup: "setup" };

  const emit = (list) => window.rngn && window.rngn.receive({ type: "jobs", jobs: list.map(view) });
  const view = (j) => { const { script, phase, ...rest } = j; return { ...rest }; };

  function finish(j) {
    j.state = "done";
    j.progress = 100;
    j.finished = now();
    const name = j.title.replace(/^Пример:\s*/, "");
    const out = {
      download: j.params.mode === "audio" ? `${ROOT}\\YouTube\\${name}.${j.params.audio_format || "mp3"}` : `${ROOT}\\YouTube\\${name}.mp4`,
      transcribe: `${ROOT}\\Transcripts\\${name}.transcript.txt`,
      subtitles: `${ROOT}\\Subtitles\\${name}.ru.auto.srt`,
      convert: `${ROOT}\\Converted\\${name}.premiere.mp4`,
      gpu_setup: "",
    }[j.kind];
    j.outputs = out ? [out] : [];
    j.summary = j.kind === "transcribe" ? "Готово за 0:48 · видеокарта" : j.kind === "gpu_setup" ? "Ускорение NVIDIA включено" : `Сохранено: ${String(out).split("\\").pop()}`;
    j.stage = j.summary;
    say(j, j.summary);
    window.rngn.receive({ type: "job_done", id: j.id, title: j.title, summary: j.summary });
    if (j.kind === "download" && j.params.transcribe_after) {
      const t = job("transcribe", j.title, { script: "transcribe", parent: j.id });
      jobs.set(t.id, t);
      emit([t]);
    }
  }

  setInterval(() => {
    const changed = [];
    const busy = new Set([...jobs.values()].filter((j) => j.state === "running").map((j) => LANE[j.kind]));
    for (const j of jobs.values()) {
      if (j.state === "queued" && !busy.has(LANE[j.kind])) {
        busy.add(LANE[j.kind]);
        j.state = "running";
        j.started = now();
        j.phase = 0;
        changed.push(j);
      }
    }
    for (const j of jobs.values()) {
      if (j.state !== "running") continue;
      const script = SCRIPTS[j.script] || SCRIPTS.video;
      const ph = script[j.phase];
      if (!ph) { finish(j); changed.push(j); continue; }
      j.progress = Math.min(ph.to, (j.progress || 0) + ph.step);
      j.stage = ph.stage(j.progress);
      if (!j.logged || j.logged !== j.phase + 1) { say(j, ph.log); j.logged = j.phase + 1; }
      if (j.progress >= ph.to) j.phase++;
      changed.push(j);
    }
    if (changed.length) emit(changed);
  }, 450);

  const merge = (base, patch) => {
    for (const [k, v] of Object.entries(patch || {})) {
      if (v && typeof v === "object" && !Array.isArray(v) && base[k] && typeof base[k] === "object") merge(base[k], v);
      else base[k] = v;
    }
    return base;
  };
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const note = (title, text) => window.rngn && window.rngn.toast && window.rngn.toast("info", title, text);
  const submit = (kind, title, params, script, meta = {}) => { const j = job(kind, title, { params, script, meta }); jobs.set(j.id, j); emit([j]); return view(j); };

  window.RNGN_MOCK = {
    __mock: true,
    __describe: (fileList) => [...fileList].map((f) => {
      const ext = (f.name.split(".").pop() || "").toLowerCase();
      const video = ["mp4", "mov", "mkv", "webm", "avi", "m4v", "ts"].includes(ext);
      const audio = ["mp3", "m4a", "wav", "aac", "flac", "ogg", "opus", "wma"].includes(ext);
      return { path: f.name, name: f.name, size: f.size, kind: video ? "video" : audio ? "audio" : "other", transcribable: video || audio };
    }),
    async bootstrap() {
      return {
        app: { name: "RNGN Media", version: "0.4.0", platform: "windows" },
        settings: clone(settings),
        jobs: [...jobs.values()].map(view).reverse(),
        gpu: { supported: true, gpu: { name: "NVIDIA GeForce RTX 4080 SUPER", driver: "610.88", memory_mb: 16376 }, libs_dir: "…\\ZNAMBO Transcriber\\cuda-libs", libs_source: "znambo", ready: true, download_mb: 810 },
        models: [
          { id: "turbo", label: "Быстрая", description: "large-v3-turbo · почти та же точность, в 3–4 раза быстрее", installed: true, location: "%LOCALAPPDATA%\\RNGN-Media\\models", shared_with_znambo: false, size_mb: 1620 },
          { id: "large", label: "Точная", description: "large-v3 · максимум точности, медленнее", installed: true, location: "%LOCALAPPDATA%\\RNGN-Media\\models", shared_with_znambo: false, size_mb: 3090 },
        ],
        languages: [["mixed", "Авто · микс языков"], ["auto", "Авто · один язык"], ["ru", "Русский"], ["en", "English"], ["uk", "Українська"], ["fr", "Français"], ["es", "Español"], ["de", "Deutsch"], ["it", "Italiano"], ["pt", "Português"], ["tr", "Türkçe"], ["zh", "中文"], ["ja", "日本語"], ["ko", "한국어"], ["ar", "العربية"]].map(([id, label]) => ({ id, label })),
        profiles: [
          { id: "premiere", label: "MP4 для Premiere", description: "H.264, исходные разрешение и частота кадров, очень высокое качество.", audio_only: false },
          { id: "hevc", label: "MP4 H.265", description: "Файл заметно меньше при высоком качестве.", audio_only: false },
          { id: "prores", label: "MOV ProRes 422 HQ", description: "Монтажный формат без потерь на глаз. Файл очень большой.", audio_only: false },
          { id: "remux_mp4", label: "MP4 без перекодирования", description: "Меняется только контейнер, качество 1:1. Секунды вместо минут.", audio_only: false },
          { id: "remux_mov", label: "MOV без перекодирования", description: "Контейнер MOV, видео и звук копируются бит в бит.", audio_only: false },
          { id: "remux_mkv", label: "MKV без перекодирования", description: "Самый терпимый контейнер: переносятся все дорожки.", audio_only: false },
          { id: "audio_wav", label: "Звук · WAV", description: "Несжатый звук для монтажа.", audio_only: true },
          { id: "audio_mp3", label: "Звук · MP3", description: "MP3 320 кбит/с — откроется где угодно.", audio_only: true },
        ],
        tools: { "yt-dlp": { version: "2026.08.19", checked: now() - 3600, status: "up-to-date" }, "gallery-dl": { version: "2026.10.16", checked: now() - 3600 } },
        cookies: { file: null, own: false, domains: [] },
        update: null,
        demo: {
          text: "https://www.youtube.com/watch?v=PRIMER00001",
          dl: { status: "media", info: sampleInfo("https://www.youtube.com/watch?v=PRIMER00001"), mode: "video", height: 1080, clipEnd: 754, lastKey: "https://www.youtube.com/watch?v=PRIMER00001" },
        },
      };
    },
    async analyze(text) {
      const urls = [...new Set(String(text).match(/https?:\/\/[^\s<>"']+/gi) || [])];
      await sleep(900);
      if (!urls.length) return { ok: false, error: { message: "Здесь нет ссылки.", hint: "Скопируй адрес видео из браузера.", kind: "input" } };
      if (urls.length > 1) return { ok: true, kind: "batch", urls: urls.map((u) => ({ url: u, site: siteOf(u)[0] })) };
      const [site, platform] = siteOf(urls[0]);
      if (platform === "Instagram") return { ok: false, url: urls[0], site, error: { message: "Instagram требует вход в аккаунт.", hint: "Войди на сайт в Firefox или загрузи файл cookies в «Настройки → Вход на сайты», затем повтори.", kind: "auth", details: "ERROR: [Instagram] login required" } };
      if (/playlist|list=/.test(urls[0])) {
        return { ok: true, kind: "media", info: { ...sampleInfo(urls[0]), kind: "playlist", title: "Пример плейлиста: обзоры тура", choices: [],
          entries: Array.from({ length: 8 }, (_, i) => ({ url: `https://www.youtube.com/watch?v=PRIMER0000${i}`, title: `Пример: обзор матча №${i + 1}`, duration: 300 + i * 41 })) } };
      }
      return { ok: true, kind: "media", info: sampleInfo(urls[0], site, platform) };
    },
    async cancel_analysis() { return true; },
    async subtitle_tracks() {
      await sleep(600);
      return { ok: true, info: { video_id: "PRIMER", title: "Пример", tracks: [
        { id: "auto:ru-orig", code: "ru-orig", name: "Русский", source: "auto", source_label: "авто", original: true, label: "Русский", base_url: "" },
        { id: "manual:en", code: "en", name: "English", source: "manual", source_label: "вручную", original: false, label: "English", base_url: "" },
      ] } };
    },
    async start_download(p) {
      const title = p.title && !/^https?:/.test(p.title) ? p.title : `Пример: ${p.url}`;
      return submit("download", title, { mode: p.mode, audio_format: p.audio_format, transcribe_after: !!p.transcribe_after }, p.mode === "audio" ? "audio" : "video", { site: p.site, thumbnail: p.thumbnail });
    },
    async start_batch(urls, p) { return urls.map((u, i) => submit("download", `Пример: видео ${i + 1} из ${urls.length}`, { mode: p.mode, audio_format: p.audio_format, transcribe_after: !!p.transcribe_after }, p.mode === "audio" ? "audio" : "video", { site: siteOf(u)[0] })); },
    async start_subtitles(p) { return submit("subtitles", `${p.title} · ${p.track.name}`, {}, "subtitles", { site: p.site }); },
    async start_transcribe(files) { return files.map((f) => submit("transcribe", String(f).split(/[\\/]/).pop().replace(/\.[^.]+$/, ""), {}, "transcribe")); },
    async start_convert(files, profile) { return files.map((f) => submit("convert", `${String(f).split(/[\\/]/).pop()} → ${profile}`, {}, "convert")); },
    async setup_gpu() { return submit("gpu_setup", "Ускорение NVIDIA", {}, "gpu"); },
    async cancel_job(jid) {
      const j = jobs.get(jid);
      if (!j || !["running", "queued"].includes(j.state)) return false;
      Object.assign(j, { state: "cancelled", stage: "Отменено", finished: now() });
      emit([j]);
      return true;
    },
    async retry_job(jid) { const j = jobs.get(jid); return j ? submit(j.kind, j.title.replace(/^instagram/, "Пример: instagram"), j.params, j.script || "video", j.meta) : null; },
    async remove_job(jid) { return jobs.delete(jid); },
    async clear_finished() { for (const [k, j] of jobs) if (!["running", "queued"].includes(j.state)) jobs.delete(k); return 0; },
    async job_log(jid, since) { const l = logs.get(jid) || []; return { lines: l.slice(since || 0), seq: l.length }; },
    async describe_files(paths) { return paths.map((p) => ({ path: p, name: p.split("\\").pop(), size: 48e6, kind: /\.(mp3|m4a|wav)$/i.test(p) ? "audio" : "video", transcribable: true })); },
    async pick_files(purpose) { return purpose === "video" ? [`${ROOT}\\Пример камера 1.mov`] : [`${ROOT}\\Пример интервью.m4a`, `${ROOT}\\Пример пресс-конференция.mp4`]; },
    async pick_folder() { note("В программе откроется выбор папки", "В макете папка не меняется."); return clone(settings); },
    async open_path(p) { note("В программе откроется файл", String(p).split("\\").pop()); return true; },
    async reveal_path(p) { note("В программе откроется папка с файлом", String(p).split("\\").pop()); return true; },
    async open_output(sub) { note("В программе откроется папка", sub ? `${ROOT}\\${sub}` : ROOT); return true; },
    async open_url() { note("В программе откроется страница загрузки"); return true; },
    async read_clipboard() { return "https://vkvideo.ru/video-1_456239017"; },
    async copy_text() { return true; },
    async save_settings(patch) { merge(settings, patch); return clone(settings); },
    async gpu_status() { return {}; },
    async import_cookies() { return { ok: true, cookies: { file: "cookies.txt", own: true, domains: ["instagram.com", "youtube.com", "vk.com"] } }; },
    async remove_cookies() { return { file: null, own: false, domains: [] }; },
    async update_tools_now() { await sleep(1200); return { "yt-dlp": { version: "2026.08.19", checked: now(), status: "up-to-date" } }; },
    async check_app_update() { await sleep(600); return null; },
  };
})();
