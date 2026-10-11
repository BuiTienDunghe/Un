/* ══════════════════════════════════════════════════════════════════
   /ui/views/research.js — Không gian Nghiên cứu paper
   (#/research · #/research/<projectId> · #/research/<projectId>/p/<paperId>[?page=&tool=]).

   Một IIFE, không tên top-level. Bố cục riêng (Shell.setLayout("full")):
   kho paper 268 (trái) · tab bar 44 + ô đọc 1–2 ô (giữa) · panel công cụ
   min(330px, 38%) + rail 44 (phải). Mọi thứ ngoài ô đọc là panel.

   Nguồn: .scratch/research-space/spec.md (hợp đồng API + hành vi) và
   design_handoff_local_ai_core_v2/README.md "Phần 2" + prototype
   "Research Space v3.dc.html" (P:n = dòng prototype).

   Ô đọc: ảnh trang PNG từ máy chủ (GET /documents/{id}/pages/{n}.png) +
   lớp chữ `words` (span trong suốt định vị tuyệt đối) để bôi đen bằng
   chuột thật → highlight = rects của các từ trong vùng chọn, gộp theo dòng.
   Không dùng pdf.js. Trang tải lười (IntersectionObserver ±2 trang) qua
   Shell.fetchBlob → object URL (thu hồi khi gỡ ô / rời view).

   Gọi mạng: Shell.api (JSON, kể cả FormData), Shell.fetchBlob (ảnh trang,
   tệp gốc, export), Shell.stream (SSE /research/chat). API chưa có
   (404/405/501 KHÔNG kèm mã lỗi) → missingApiState, không giả vờ.

   S sống qua các lần mount (dự án, tab, panel, lịch sử hỏi đáp trong
   phiên…); V là DOM của lần mount đang sống, null khi đã rời view.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  /* ── hằng số ─────────────────────────────────────────────────── */
  const JSON_HEADERS = { "Content-Type": "application/json" };
  const STORE_KEY = "lac.research";
  const POLL_MS = 5000;             // GET project khi còn paper đang xử lý
  const LAST_PAGE_MS = 2000;        // PATCH last_page sau khi ngừng cuộn
  const NOTE_MS = 900;              // PATCH note_md sau khi ngừng gõ
  const PAGE_W = 720;               // bề rộng trang ở 100%
  const ZOOMS = [0.6, 0.75, 0.9, 1, 1.15, 1.3, 1.5, 1.75, 2];
  const DPI = 110;
  const DPI_HI = 160;               // ≥150% tải lại ảnh nét hơn
  const MOD = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";
  const TOOLS = [
    { id: "project", label: "Hỏi cả dự án", icon: "project" },
    { id: "compare", label: "So sánh", icon: "columns" },
    { id: "summary", label: "Tóm tắt AI", icon: "spark" },
    { id: "notes", label: "Highlight & ghi chú", icon: "highlighter" },
    { id: "chat", label: "Hỏi paper", icon: "chat" },
    { id: "outline", label: "Mục lục & hình", icon: "list" },
    { id: "info", label: "Thông tin & trạng thái", icon: "info" },
  ];
  const HL = [
    { color: "#f59e0b", name: "Vàng" }, { color: "#2563eb", name: "Xanh" },
    { color: "#22c55e", name: "Lục" }, { color: "#ec4899", name: "Hồng" },
  ];
  const STATUS = {
    unread: { label: "Chưa đọc", color: "var(--border-2)" },
    reading: { label: "Đang đọc", color: "var(--warn)" },
    read: { label: "Đã đọc", color: "var(--ok)" },
  };
  const FILTERS = [["all", "Tất cả"], ["unread", "Chưa đọc"], ["reading", "Đang đọc"], ["read", "Đã đọc"]];
  const EDGE = {
    builds: { label: "Xây trên", color: "var(--accent)", dash: "" },
    competes: { label: "Cùng bài toán", color: "var(--warn)", dash: "6 4" },
    backbone: { label: "Chung backbone", color: "var(--text-3)", dash: "2 4" },
  };
  const STAGE_LABEL = { ocr: "OCR", metadata: "metadata", outline: "outline", summary: "tóm tắt" };
  const SUM_CARDS = [["problem", "Vấn đề", "is-problem"], ["idea", "Ý tưởng", "is-idea"], ["result", "Kết quả", "is-result"], ["limits", "Hạn chế", "is-limits"]];
  const KEYS = [
    ["Tìm paper trong kho", `${MOD}+K`], ["Tìm trong PDF", `${MOD}+F`], ["Chia đôi / gộp", `${MOD}+\\`], ["Chế độ tập trung", `${MOD}+.`],
    ["Highlight vùng chọn", `${MOD}+H`], ["Ghi chú vùng chọn", `${MOD}+E`], ["Hỏi AI về vùng chọn", `${MOD}+A`], ["Dịch vùng chọn", `${MOD}+T`],
    ["Đóng tab", `${MOD}+W`], ["Chuyển tab", "Ctrl+Tab"], ["Trang trước / sau", "← →"],
  ];
  const ERROR_VI = {
    RESEARCH_PROJECT_NOT_FOUND: "Dự án không còn trên máy chủ.",
    RESEARCH_PAPER_NOT_FOUND: "Paper không còn trong dự án.",
    RESEARCH_ANNOTATION_NOT_FOUND: "Highlight này đã bị xoá.",
    RESEARCH_SUMMARY_MISSING: "Chưa paper nào có tóm tắt — mở panel Tóm tắt AI của vài paper trước.",
    RESEARCH_SOURCE_UNAVAILABLE: "Tệp gốc đã bị gỡ khỏi máy chủ.",
    RESEARCH_NOT_INDEXED: "Paper chưa lập chỉ mục xong (chưa có chữ) — chờ OCR hoàn tất.",
    DOCUMENT_PAGE_NOT_FOUND: "Máy chủ không có trang này.",
    DOCUMENT_NOT_FOUND: "Tài liệu không còn trên máy chủ.",
    RESEARCH_THREAD_NOT_FOUND: "Luồng chat này không còn trên máy chủ.",
    RESEARCH_THREAD_MISMATCH: "Luồng chat này không thuộc paper / dự án đang mở.",
    INTERNAL_ERROR: "Máy chủ gặp lỗi nội bộ.",
  };
  const CHAT_HINTS_PAPER = ["Giải thích Eq. 4 tiếng Việt", "Tóm tắt phần thí nghiệm", "Hạn chế chính?"];
  const CHAT_HINTS_PROJECT = ["Paper nào dùng 2DGS?", "Xu hướng 2024 → 2025", "Khoảng trống chưa ai làm"];
  // Điện thoại (≤768): kho paper thành drawer, rail thành thanh dưới, panel phủ toàn màn, không chia đôi.
  // CSS làm phần lớn (@media trong research.css); JS chỉ quyết định những gì phụ thuộc trạng thái.
  const PHONE_MQ = typeof window.matchMedia === "function" ? window.matchMedia("(max-width: 768px)") : null;
  const isPhone = () => Boolean(PHONE_MQ && PHONE_MQ.matches);
  const NEW_THREAD = "new";          // luồng chưa tạo trên máy chủ (POST khi gửi tin đầu)
  const SESSION_THREAD = "session";  // máy chủ chưa có /research/threads → lịch sử chỉ sống trong phiên

  /* ── trạng thái sống qua các lần mount ───────────────────────── */
  const S = {
    projects: null, projectsError: null, projectsMissing: false, projectsBusy: false,
    pid: null, project: null, projBusy: false, projError: null, projSeq: 0,
    // phiên theo dự án (lưu localStorage lac.research)
    tabs: [], active: "overview", split: false, second: null, focused: 0, tool: null,
    focusMode: false, sync: false, collapsed: {}, hl: HL[0].color, showAnno: true,
    filter: "all", search: "", sel2: new Set(),
    details: new Map(),     // paperId → {data, busy, error, seq, sumBusy, sumError, sumTried, outline, outlineBusy, outlineError}
    // "<scope>:<id>:<threadId>" → {msgs: [], draft: "", ctrl: AbortController|null, loaded, loading, loadError}
    // threadId = id máy chủ, NEW_THREAD (chưa tạo) hoặc SESSION_THREAD (máy chủ chưa có route luồng).
    chats: new Map(),
    // "<scope>:<id>" → {list: Thread[]|null, busy, error, missing, current: threadId|null, seq}
    threads: new Map(),
    quoteCtx: null,         // {paperId, text}
    pendingSel: null,       // {paperId, page, rects, quote, paneId}
    noteFilter: "all",
    openEdge: null,
    keysOpen: false,
    focusAnno: null,        // id annotation cần focus ô ghi chú khi panel notes mở
    insightsBusy: false, insightsError: null,
    pendingOpen: null,      // paper trên URL chờ GET project xong: {paperId, page, tool}
    drawerOpen: false,      // điện thoại: kho paper đang trượt ra
  };
  let V = null;

  /* ── tiện ích ────────────────────────────────────────────────── */
  const enc = (value) => encodeURIComponent(String(value));
  const isAbort = (error) => Boolean(error) && error.name === "AbortError";
  const routeMissing = (error) => isMissingApi(error) && !(error && error.code);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const projHash = (pid) => `#/research/${enc(pid)}`;
  const paperHash = (pid, paperId, extra) => `#/research/${enc(pid)}/p/${enc(paperId)}${extra ? `?${extra}` : ""}`;

  function fold(text) {
    return String(text ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[đĐ]/g, "d").toLowerCase();
  }

  function say(error, fallback) {
    if (!error) return fallback;
    if (error.code && ERROR_VI[error.code]) return ERROR_VI[error.code];
    if (!error.message) return fallback;
    // Máy chủ đã nói tiếng Việt cho người dùng (spec: "Máy chủ chạy offline; tải PDF rồi thả vào.") → in nguyên câu.
    if (error.code === "RESEARCH_FETCH_UNSUPPORTED") return error.message;
    if (error.code && !ERROR_HINTS[error.code]) return `Máy chủ báo lỗi: ${error.message}`;
    return error.message;
  }

  function safeSavePrefs() {
    try { savePrefs(); } catch { /* localStorage bị chặn */ }
  }

  const papers = () => (S.project && Array.isArray(S.project.papers) ? S.project.papers : []);
  const clusters = () => (S.project && Array.isArray(S.project.clusters) ? S.project.clusters : []);
  const edges = () => (S.project && Array.isArray(S.project.edges) ? S.project.edges : []);
  const paperById = (id) => papers().find((p) => p.id === id) || null;
  const paperByDoc = (docId) => papers().find((p) => p.document_id === docId) || null;
  const clusterById = (id) => clusters().find((c) => c.id === id) || null;

  /* Màu cụm của paper: var(--cN) theo color_index của cụm; không cụm → text-3. */
  function colorOf(paper) {
    const cluster = paper ? clusterById(paper.cluster_id) : null;
    return cluster ? clusterColor(cluster) : "var(--text-3)";
  }
  const clusterColor = (cluster) => `var(--c${clamp(Number(cluster && cluster.color_index) || 1, 1, 5)})`;
  const statusOf = (paper) => STATUS[paper && paper.status] || STATUS.unread;
  const shortOf = (paper) => (paper && (paper.short_name || paper.title)) || "Paper";
  const venueText = (paper) => [paper && paper.venue, paper && paper.year].filter(Boolean).join(" ");
  const totalPages = (paper) => { const n = Number(paper && paper.total_pages); return Number.isFinite(n) && n > 0 ? n : 0; };

  /* Paper còn đang xử lý nền (OCR / metadata / outline / tóm tắt)? */
  function stageInfo(paper) {
    // Tóm tắt gọi tay (spec: không chạy nền) → "pending" của summary không phải là đang xử lý;
    // chỉ OCR → metadata → outline là pipeline nền.
    const stages = (paper && paper.stages) || {};
    const order = ["ocr", "metadata", "outline"];
    const done = order.filter((k) => stages[k] === "done");
    const running = order.find((k) => stages[k] === "running" || stages[k] === "pending") || (stages.summary === "running" ? "summary" : null);
    const failed = [...order, "summary"].find((k) => stages[k] === "failed");
    if (failed === "ocr") return { busy: false, failed: true, text: "OCR thất bại — không đọc được chữ" };
    if (!running) return { busy: false, failed: Boolean(failed), text: failed ? `${STAGE_LABEL[failed]} thất bại` : "" };
    const pct = Math.round(((done.length + 0.5) / (order.length + 1)) * 100);
    const lastDone = done.length ? `${STAGE_LABEL[done[done.length - 1]]} xong · ` : "";
    return { busy: true, failed: false, pct, text: `${lastDone}đang ${stages[running] === "pending" ? "chờ" : "chạy"} ${STAGE_LABEL[running]}` };
  }
  const isWorking = (paper) => stageInfo(paper).busy || paper.document_status === "processing" || paper.document_status === "uploaded";

  /* ── phiên theo dự án (localStorage) ─────────────────────────── */
  function readStoreAll() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || "{}") || {}; } catch { return {}; }
  }
  function loadSession(pid) {
    const all = readStoreAll();
    const s = (all.projects && all.projects[pid]) || {};
    S.tabs = Array.isArray(s.tabs) ? s.tabs.filter((t) => typeof t === "string") : [];
    S.active = typeof s.active === "string" ? s.active : "overview";
    S.split = Boolean(s.split) && !isPhone();   // điện thoại: luôn một ô
    S.second = typeof s.second === "string" ? s.second : null;
    S.tool = TOOLS.some((t) => t.id === s.tool) ? s.tool : null;
    S.collapsed = s.collapsed && typeof s.collapsed === "object" ? s.collapsed : {};
    S.hl = HL.some((c) => c.color === s.hl) ? s.hl : HL[0].color;
    S.showAnno = s.showAnno !== false;
    S.sync = Boolean(s.sync);
    S.focused = 0;
    S.sel2 = new Set();
    S.quoteCtx = null;
    S.pendingSel = null;
    S.openEdge = null;
    S.drawerOpen = false;
  }
  /* Đổi qua/lại ngưỡng điện thoại (xoay máy, kéo cửa sổ): ép một ô, tắt tập trung, đóng drawer. */
  function applyPhone() {
    if (isPhone()) {
      if (S.split) { S.split = false; S.sync = false; S.focused = 0; }
      S.focusMode = false;
    } else S.drawerOpen = false;
    if (V) { saveSession(); renderAll(); syncUrl(); }
  }
  function setDrawer(open) {
    S.drawerOpen = Boolean(open) && isPhone();
    if (V) renderDrawer();
  }
  function renderDrawer() {
    if (!V) return;
    V.root.classList.toggle("is-drawer-open", S.drawerOpen);
    V.menuBtn.setAttribute("aria-expanded", String(S.drawerOpen));
    V.backdrop.hidden = !S.drawerOpen;
  }
  function saveSession() {
    if (!S.pid) return;
    const all = readStoreAll();
    all.lastProject = S.pid;
    all.projects = all.projects && typeof all.projects === "object" ? all.projects : {};
    all.projects[S.pid] = {
      tabs: S.tabs, active: S.active, split: S.split, second: S.second, tool: S.tool,
      collapsed: S.collapsed, hl: S.hl, showAnno: S.showAnno, sync: S.sync,
    };
    try { localStorage.setItem(STORE_KEY, JSON.stringify(all)); } catch { /* bị chặn: chỉ sống trong phiên */ }
  }
  const lastProject = () => readStoreAll().lastProject || null;
  /* Luồng chat dùng gần nhất theo "paper:<id>" | "project:<pid>" — khóa cấp cao của lac.research
     (saveSession chỉ ghi lại all.projects[pid] nên không đụng tới). */
  const storedThread = (tkey) => { const m = readStoreAll().threadByKey; return m && typeof m === "object" && typeof m[tkey] === "string" ? m[tkey] : null; };
  function rememberThread(tkey, threadId) {
    const all = readStoreAll();
    all.threadByKey = all.threadByKey && typeof all.threadByKey === "object" ? all.threadByKey : {};
    if (threadId) all.threadByKey[tkey] = threadId;
    else delete all.threadByKey[tkey];
    try { localStorage.setItem(STORE_KEY, JSON.stringify(all)); } catch { /* bị chặn */ }
  }

  /* Dọn tab trỏ tới paper không còn trong dự án. */
  function pruneTabs() {
    const known = new Set(papers().map((p) => p.id));
    S.tabs = S.tabs.filter((id) => known.has(id));
    if (S.active !== "overview" && !known.has(S.active)) S.active = S.tabs[S.tabs.length - 1] || "overview";
    if (S.second && !known.has(S.second)) S.second = null;
    for (const id of [...S.sel2]) if (!known.has(id)) S.sel2.delete(id);
  }

  /* ── tải dữ liệu ─────────────────────────────────────────────── */
  async function loadProjects() {
    if (S.projectsBusy) return;
    S.projectsBusy = true;
    const signal = V ? V.ctx.signal : undefined;
    try {
      const rows = await Shell.api("/research/projects", { signal });
      S.projects = Array.isArray(rows) ? rows.filter((r) => r && typeof r.id === "string") : [];
      S.projectsError = null;
      S.projectsMissing = false;
    } catch (error) {
      if (isAbort(error)) return;
      if (routeMissing(error)) S.projectsMissing = true;
      else S.projectsError = error;
    } finally {
      S.projectsBusy = false;
    }
  }

  async function loadProject(pid, { quiet = false } = {}) {
    const my = ++S.projSeq;
    const signal = V ? V.ctx.signal : undefined;
    S.projBusy = true;
    if (!quiet) renderAll();
    try {
      const data = await Shell.api(`/research/projects/${enc(pid)}`, { signal });
      if (my !== S.projSeq || S.pid !== pid) return;
      S.project = data && typeof data === "object" ? data : null;
      S.projError = null;
      pruneTabs();
      // Dòng paper trong detail đã mở có thể cũ hơn danh sách (status, stars…): làm mới phần dòng.
      for (const p of papers()) {
        const d = S.details.get(p.id);
        if (d && d.data) d.data = { ...d.data, ...p, summary: d.data.summary, annotations: d.data.annotations, outline: d.data.outline, note_md: d.data.note_md };
      }
    } catch (error) {
      if (my !== S.projSeq || isAbort(error)) return;
      S.projError = error;
      if (error && error.code === "RESEARCH_PROJECT_NOT_FOUND") {
        S.project = null;
      }
    } finally {
      if (my === S.projSeq) S.projBusy = false;
    }
    renderAll();
  }

  /* Dòng paper trong danh sách dự án đổi tại chỗ (sau PATCH) rồi vẽ lại. */
  function replacePaper(row) {
    if (!row || !S.project) return;
    const list = papers();
    const at = list.findIndex((p) => p.id === row.id);
    if (at === -1) list.push(row);
    else list[at] = { ...list[at], ...row };
    const d = S.details.get(row.id);
    if (d && d.data) d.data = { ...d.data, ...row, summary: d.data.summary, annotations: d.data.annotations, outline: d.data.outline, note_md: d.data.note_md };
  }

  function detailOf(id) {
    let d = S.details.get(id);
    if (!d) {
      d = { data: null, busy: false, error: null, seq: 0, sumBusy: false, sumError: null, sumTried: false, outline: null, outlineBusy: false, outlineError: null, outlineMissing: false, noteState: "" };
      S.details.set(id, d);
    }
    return d;
  }

  /* GET /research/papers/{id}: summary, outline, note_md, annotations. */
  async function ensureDetail(id, { force = false } = {}) {
    const d = detailOf(id);
    if ((d.data && !force) || d.busy) return d;
    const my = ++d.seq;
    d.busy = true;
    d.error = null;
    try {
      const data = await Shell.api(`/research/papers/${enc(id)}`, { signal: V ? V.ctx.signal : undefined });
      if (my !== d.seq) return d;
      d.data = data;
      d.data.annotations = Array.isArray(data.annotations) ? data.annotations : [];
      replacePaper({ ...data, annotations: undefined });
    } catch (error) {
      if (my !== d.seq || isAbort(error)) return d;
      d.error = error;
    } finally {
      if (my === d.seq) d.busy = false;
    }
    renderAll();
    return d;
  }

  async function patchPaper(id, body) {
    const row = await Shell.api(`/research/papers/${enc(id)}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body) });
    if (row && row.id) replacePaper(row);
    else replacePaper({ id, ...body });
    return row;
  }

  const annotationsOf = (id) => { const d = S.details.get(id); return d && d.data && Array.isArray(d.data.annotations) ? d.data.annotations : null; };
  const annoCount = (paper) => { const list = annotationsOf(paper.id); return list ? list.length : Number(paper.annotation_count) || 0; };

  /* ══════════════════════════════════════════════════════════════
     TAB / Ô ĐỌC / PANEL — hành động đổi trạng thái
     ══════════════════════════════════════════════════════════════ */
  function syncUrl() {
    if (!S.pid) return;
    const hash = S.active === "overview" ? projHash(S.pid) : paperHash(S.pid, S.active);
    if (location.hash !== hash) Router.replace(hash, { silent: true });
  }

  /* Mở paper trong tab (tab đã có thì chuyển sang). page → cuộn tới; tool → mở panel; side → ô 2 khi chia đôi. */
  function openPaper(id, { page = null, tool, side = false } = {}) {
    if (!paperById(id)) return;
    S.drawerOpen = false;
    if (side && S.split && S.active !== id) {
      S.second = id;
      S.focused = 1;
      if (!S.tabs.includes(id)) S.tabs.push(id);
    } else {
      if (!S.tabs.includes(id)) S.tabs.push(id);
      S.active = id;
      S.focused = 0;
      if (S.second === id) S.second = null;
    }
    if (tool !== undefined) S.tool = tool;
    S.pendingSel = null;
    saveSession();
    renderAll();
    syncUrl();
    if (page) {
      const pane = V && V.panes.get(id);
      if (pane) requestAnimationFrame(() => goPage(pane, page, { instant: true }));
    }
    ensureDetail(id);
  }

  function setActive(id) {
    S.active = id;
    S.drawerOpen = false;
    S.focused = 0;
    S.pendingSel = null;
    if (id !== "overview" && S.second === id) S.second = null;
    saveSession();
    renderAll();
    syncUrl();
  }

  function closeTab(id) {
    const at = S.tabs.indexOf(id);
    S.tabs = S.tabs.filter((t) => t !== id);
    if (S.active === id) S.active = S.tabs[Math.min(at, S.tabs.length - 1)] || S.tabs[S.tabs.length - 1] || "overview";
    if (S.second === id) S.second = null;
    if (V) destroyPane(id);
    saveSession();
    renderAll();
    syncUrl();
  }

  function setTool(tool) {
    S.tool = S.tool === tool ? null : tool;
    if (S.tool !== "chat") S.quoteCtx = S.tool === null ? S.quoteCtx : null;
    saveSession();
    renderAll();
  }

  /* Paper "đang focus" — panel bám theo ô này. */
  function currentPaperId() {
    if (S.active === "overview") return null;
    if (S.split && S.focused === 1 && secondId()) return secondId();
    return S.active;
  }
  const currentPaper = () => paperById(currentPaperId());

  function secondId() {
    if (!S.split) return null;
    if (S.second && S.second !== S.active && paperById(S.second)) return S.second;
    const other = S.tabs.find((t) => t !== S.active) || (papers().find((p) => p.id !== S.active) || {}).id || null;
    return other;
  }

  function toggleSplit() {
    if (isPhone()) { toast("Chia đôi chỉ dùng trên màn hình rộng.", "danger"); return; }
    if (!S.split) {
      if (S.active === "overview") {
        const first = S.tabs[0] || (papers()[0] || {}).id;
        if (!first) { toast("Chưa có paper nào để đọc.", "danger"); return; }
        S.active = first;
      }
      if (papers().length < 2) { toast("Cần ít nhất 2 paper để chia đôi.", "danger"); return; }
      S.split = true;
      S.second = secondId();
      if (S.second && !S.tabs.includes(S.second)) S.tabs.push(S.second);
    } else {
      S.split = false;
      S.sync = false;
    }
    S.focused = 0;
    saveSession();
    renderAll();
    syncUrl();
  }

  function closePane(idx) {
    if (!S.split) return;
    if (idx === 0) S.active = secondId() || S.active;
    S.split = false;
    S.sync = false;
    S.focused = 0;
    saveSession();
    renderAll();
    syncUrl();
  }

  function toggleFocusMode() {
    if (isPhone()) return;   // điện thoại: không có thanh bên để ẩn
    S.focusMode = !S.focusMode;
    if (S.focusMode) S.tool = null;
    renderAll();
  }

  function toggleSync() {
    S.sync = !S.sync;
    saveSession();
    renderAll();
    if (S.sync && V) {
      const a = V.panes.get(S.active);
      if (a) mirrorScroll(a);
    }
  }

  function focusPane(idx) {
    if (S.focused === idx) return;
    S.focused = idx;
    renderAll();
  }

  /* ══════════════════════════════════════════════════════════════
     Ô ĐỌC PDF — ảnh trang + lớp chữ + highlight + ghi chú lề
     ══════════════════════════════════════════════════════════════ */
  function createPane(paperId) {
    const pane = {
      id: paperId, idx: 0, zoom: 1, dpi: DPI, cur: 1, total: 0, pages: [], el: null, scroll: null, io: null, ro: null,
      savedTop: 0, syncing: false, noText: false, find: null, raf: 0, lastPatchPage: null, patchTimer: null, menu: null, w: 0,
    };
    const paper = paperById(paperId);

    const name = h("div", { class: "rs-tb-name", title: paper ? paper.title : "" }, shortOf(paper), h("span", null, venueText(paper) ? ` · ${venueText(paper)}` : ""));
    const select = h("select", { class: "rs-tb-select", hidden: true, "aria-label": "Đổi paper trong ô này" });
    select.addEventListener("change", () => {
      const id = select.value;
      if (pane.idx === 0) openPaper(id);
      else openPaper(id, { side: true });
    });
    const prev = h("button", { type: "button", class: "rs-ibtn rs-tb-wide", title: "Trang trước (←)", onClick: () => goPage(pane, pane.cur - 1) }, icon("arrow-left", { size: 13, sw: 2.2 }));
    const next = h("button", { type: "button", class: "rs-ibtn rs-tb-wide", title: "Trang sau (→)", onClick: () => goPage(pane, pane.cur + 1) }, icon("arrow-right", { size: 13, sw: 2.2 }));
    const pageLabel = h("span", { class: "rs-tb-page" }, "– / –");
    const findBtn = h("button", { type: "button", class: "rs-ibtn rs-tb-wide", title: `Tìm trong PDF (${MOD}+F)`, onClick: () => askFind(pane) }, icon("search", { size: 13, sw: 2.2 }));
    const hlSwatch = h("i", { style: { background: S.hl } });
    const hlBtn = h("button", { type: "button", class: "rs-tb-hlbtn", title: "Màu highlight đang chọn", onClick: () => pickColorMenu(hlBtn) }, icon("highlighter", { size: 13 }), hlSwatch);
    const swatches = HL.map((c) => h("button", {
      type: "button", class: ["rs-swatch", c.color === S.hl && "is-on"], title: c.name, style: { background: c.color }, dataset: { color: c.color },
      onClick: () => { S.hl = c.color; saveSession(); renderAll(); },
    }));
    const eye = h("button", { type: "button", class: ["rs-tb-eye", S.showAnno && "is-on"], title: S.showAnno ? "Ẩn ghi chú bên lề" : "Hiện ghi chú bên lề", onClick: () => { S.showAnno = !S.showAnno; saveSession(); renderAll(); } }, icon("eye", { size: 13 }));
    const hlGroup = h("div", { class: "rs-tb-hl rs-tb-wide" }, hlBtn, ...swatches, eye);
    const zoomLabel = h("span", null, "100%");
    const zoomGroup = h("div", { class: "rs-tb-zoom rs-tb-wide" },
      h("button", { type: "button", title: "Thu nhỏ", onClick: () => setZoom(pane, -1) }, "−"), zoomLabel,
      h("button", { type: "button", title: "Phóng to", onClick: () => setZoom(pane, 1) }, "+"));
    const more = h("button", { type: "button", class: "rs-ibtn rs-tb-more", title: "Thêm: trang, tìm, màu highlight, ghi chú lề, zoom", onClick: () => moreMenu(pane, more) }, icon("dots", { size: 14, sw: 2.6 }));
    const close = h("button", { type: "button", class: "rs-ibtn", title: "Đóng ô này", hidden: true, onClick: (event) => { event.stopPropagation(); closePane(pane.idx); } }, icon("x", { size: 12, sw: 2.4 }));
    close.style.color = "var(--text-3)";
    const sep1 = h("span", { class: "rs-tb-sep rs-tb-wide" });
    const sep2 = h("span", { class: "rs-tb-sep rs-tb-wide" });
    const toolbar = h("div", { class: "rs-toolbar" }, name, select, sep1,
      h("div", { class: "rs-tb-group" }, prev, pageLabel, next), sep2, findBtn, hlGroup, zoomGroup, more, close);

    const syncBadge = h("div", { class: "rs-sync-badge", hidden: true });
    const scroll = h("div", { class: "rs-pages", tabindex: "0", "aria-label": `Trang của ${shortOf(paper)}` }, syncBadge);
    const el = h("div", { class: "rs-pane", dataset: { paper: paperId } }, toolbar, scroll);
    el.addEventListener("mousedown", () => { if (S.split) focusPane(pane.idx); }, true);
    el.addEventListener("focusin", () => { if (S.split) focusPane(pane.idx); });

    Object.assign(pane, { el, scroll, toolbar, name, select, pageLabel, zoomLabel, hlSwatch, swatches, eye, close, syncBadge });

    scroll.addEventListener("scroll", () => {
      if (pane.raf) return;
      pane.raf = requestAnimationFrame(() => {
        pane.raf = 0;
        updateCurrent(pane);
        if (pane.syncing) { pane.syncing = false; return; }
        if (S.sync && S.split) mirrorScroll(pane);
      });
    });
    scroll.addEventListener("mousedown", (event) => {
      if (!event.target.closest(".rs-margin")) hideSelMenu(pane);
    });
    // Người dùng tự cuộn → thôi chỉnh vị trí theo cú nhảy trước.
    scroll.addEventListener("wheel", () => { pane.jumpTo = null; }, { passive: true });
    scroll.addEventListener("touchmove", () => { pane.jumpTo = null; }, { passive: true });
    scroll.addEventListener("mouseup", () => setTimeout(() => readSelection(pane), 0));
    // Cảm ứng: tay kéo chốt chọn không bắn mouseup; đọc lại sau khi nhấc tay (chốt cập nhật trễ một nhịp).
    scroll.addEventListener("touchend", () => setTimeout(() => readSelection(pane), 60), { passive: true });
    scroll.addEventListener("pointerup", (event) => { if (event.pointerType !== "mouse") setTimeout(() => readSelection(pane), 60); });
    scroll.addEventListener("keyup", (event) => { if (event.shiftKey) readSelection(pane); });

    pane.ro = new ResizeObserver((entries) => {
      const w = entries[0] ? entries[0].contentRect.width : el.clientWidth;
      pane.w = w;
      el.classList.toggle("is-narrow", w < 520);
      el.classList.toggle("is-wide640", w >= 640);
    });
    pane.ro.observe(el);
    pane.io = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const n = Number(entry.target.dataset.page);
        loadPage(pane, n);
      }
    }, { root: scroll, rootMargin: "150% 0px" });

    buildPages(pane);
    return pane;
  }

  function destroyPane(id) {
    const pane = V && V.panes.get(id);
    if (!pane) return;
    V.panes.delete(id);
    if (pane.ro) pane.ro.disconnect();
    if (pane.io) pane.io.disconnect();
    clearTimeout(pane.patchTimer);
    for (const page of pane.pages) if (page.url) URL.revokeObjectURL(page.url);
    pane.el.remove();
  }

  /* Khung trang: tỉ lệ 1:1.3 tới khi biết kích thước thật; total_pages chưa biết → 1 trang chờ. */
  function buildPages(pane) {
    const paper = paperById(pane.id);
    const total = totalPages(paper) || 1;
    if (pane.total === total && pane.pages.length) return;
    if (pane.io) pane.io.disconnect();
    for (const page of pane.pages) { if (page.url) URL.revokeObjectURL(page.url); page.el.remove(); }
    pane.pages = [];
    pane.total = total;
    for (let n = 1; n <= total; n++) {
      const img = h("img", { alt: `Trang ${n}`, hidden: true, draggable: "false" });
      const hls = h("div", { class: "rs-hls" });
      const words = h("div", { class: "rs-words" });
      const el = h("div", { class: "rs-page", dataset: { page: n } }, img, hls, words, h("span", { class: "rs-page-num" }, String(n)));
      const page = { n, el, img, hls, words, state: 0, url: null, data: null, ratio: null };
      pane.pages.push(page);
      pane.scroll.append(el);
      pane.io.observe(el);
    }
    pane.cur = clamp(pane.cur, 1, total);
    pane.pageLabel.textContent = `${pane.cur} / ${totalPages(paper) || "?"}`;
    paintAll(pane);
  }

  async function loadPage(pane, n) {
    const page = pane.pages[n - 1];
    const paper = paperById(pane.id);
    if (!page || page.state !== 0 || !paper || !paper.document_id) return;
    page.state = 1;
    page.el.classList.add("is-loading");
    const doc = enc(paper.document_id);
    const signal = V ? V.ctx.signal : undefined;
    const dpi = pane.dpi;
    const [img, words] = await Promise.all([
      Shell.fetchBlob(`/documents/${doc}/pages/${n}.png?dpi=${dpi}`, { signal }).then((blob) => ({ blob }), (error) => ({ error })),
      fetchWords(pane, n),
    ]);
    if (!V || !V.panes.has(pane.id) || pane.pages[n - 1] !== page) return;
    page.el.classList.remove("is-loading");
    if (img.error) {
      if (isAbort(img.error)) { page.state = 0; return; }
      page.state = 3;
      page.el.append(h("div", { class: "rs-page-err" }, routeMissing(img.error) ? "Máy chủ chưa có ảnh trang (GET /documents/{id}/pages/{n}.png)" : say(img.error, "Không tải được trang này.")));
      return;
    }
    page.url = URL.createObjectURL(img.blob);
    page.img.src = page.url;
    page.img.hidden = false;
    page.img.addEventListener("load", () => {
      if (!page.ratio && page.img.naturalWidth) setRatio(pane, page, page.img.naturalWidth, page.img.naturalHeight);
    }, { once: true });
    page.state = 2;
    if (words && words.width && words.height) setRatio(pane, page, words.width, words.height);
    renderWords(pane, page);
    paintPage(pane, page);
    // Trang đích của cú nhảy vừa rồi (hoặc một trang trước nó) vừa đổi chiều cao → đặt lại vị trí.
    if (pane.jumpTo && n <= pane.jumpTo) {
      const target = pane.pages[pane.jumpTo - 1];
      requestAnimationFrame(() => { if (pane.jumpTo === target.n) pane.scroll.scrollTop = target.el.offsetTop - 16; });
    }
  }

  /* Lớp chữ: {page, width, height, words:[{x0,y0,x1,y1,text,block,line}]} tỉ lệ 0..1. */
  async function fetchWords(pane, n) {
    const page = pane.pages[n - 1];
    if (!page) return null;
    if (page.data) return page.data;
    const paper = paperById(pane.id);
    try {
      const data = await Shell.api(`/documents/${enc(paper.document_id)}/pages/${n}/words`, { signal: V ? V.ctx.signal : undefined });
      page.data = data && Array.isArray(data.words) ? data : { words: [], has_text: false };
    } catch (error) {
      if (isAbort(error)) return null;
      page.data = { words: [], has_text: false, missing: routeMissing(error), error };
    }
    return page.data;
  }

  function setRatio(pane, page, w, h0) {
    if (!(w > 0 && h0 > 0)) return;
    page.ratio = w / h0;
    page.el.style.setProperty("--rs-ratio", `${w} / ${h0}`);
  }

  function renderWords(pane, page) {
    const data = page.data;
    page.words.replaceChildren();
    if (!data) return;
    const list = data.words || [];
    if (!list.length) {
      if (!pane.noText && (data.has_text === false || data.missing)) {
        pane.noText = true;
        page.el.append(h("span", { class: "rs-notext" }, data.missing ? "Máy chủ chưa có lớp chữ — không bôi đen được" : "Trang không có lớp chữ (PDF quét) — không bôi đen được"));
      }
      return;
    }
    const ratio = page.ratio || (1 / 1.3);
    const frag = document.createDocumentFragment();
    for (const w of list) {
      const x0 = Number(w.x0), y0 = Number(w.y0), x1 = Number(w.x1), y1 = Number(w.y1);
      if (![x0, y0, x1, y1].every(Number.isFinite)) continue;
      const hh = Math.max(0.002, y1 - y0);
      const span = h("span", {
        dataset: { b: w.block ?? 0, l: w.line ?? 0, p: page.n },
        style: { left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${hh * 100}%`, fontSize: `${hh / ratio * 100 * 0.82}cqw`, lineHeight: `${hh / ratio * 100}cqw` },
      }, String(w.text ?? ""));
      span._w = { x0, y0, x1, y1, text: String(w.text ?? "") };
      frag.append(span);
      frag.append(document.createTextNode(" "));
    }
    page.words.append(frag);
  }

  /* Highlight + ghi chú lề của một trang (từ annotations trong detail). */
  function paintPage(pane, page) {
    const list = annotationsOf(pane.id) || [];
    const mine = list.filter((a) => Number(a.page) === page.n);
    const nodes = [];
    for (const a of mine) {
      for (const r of (Array.isArray(a.rects) ? a.rects : [])) {
        nodes.push(h("div", { class: "rs-hl", style: { left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%`, background: a.color || S.hl } }));
      }
    }
    if (pane.find && pane.find.page === page.n) {
      for (const r of pane.find.rects) nodes.push(h("div", { class: "rs-hl is-find", style: { left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%`, background: "var(--c5)" } }));
    }
    page.hls.replaceChildren(...nodes);
    for (const old of page.el.querySelectorAll(".rs-margin")) old.remove();
    for (const a of mine) {
      if (!a.note || !Array.isArray(a.rects) || !a.rects.length) continue;
      const y = Math.min(...a.rects.map((r) => Number(r.y) || 0));
      page.el.append(h("div", {
        class: "rs-margin", style: { top: `${y * 100}%` }, title: "Mở trong Highlight & ghi chú",
        onClick: (event) => { event.stopPropagation(); S.focusAnno = a.id; S.tool = "notes"; saveSession(); renderAll(); },
      }, h("div", { class: "rs-margin-head" }, h("i", { style: { background: a.color || S.hl } }), h("span", null, `GHI CHÚ · tr. ${page.n}`)), a.note));
    }
  }
  function paintAll(pane) { for (const page of pane.pages) paintPage(pane, page); }
  function repaintPaper(paperId) {
    if (!V) return;
    const pane = V.panes.get(paperId);
    if (pane) paintAll(pane);
  }

  /* Trang hiện tại = trang chiếm giữa viewport → nhãn "k / N", last_page (PATCH sau 2 s), mục lục. */
  function updateCurrent(pane) {
    const mid = pane.scroll.scrollTop + pane.scroll.clientHeight / 2;
    let cur = pane.cur;
    for (const page of pane.pages) {
      const top = page.el.offsetTop;
      if (mid >= top - 7 && mid < top + page.el.offsetHeight + 7) { cur = page.n; break; }
    }
    if (cur === pane.cur) return;
    pane.cur = cur;
    const paper = paperById(pane.id);
    pane.pageLabel.textContent = `${cur} / ${totalPages(paper) || "?"}`;
    pane.syncBadge.textContent = `cuộn đồng bộ · ${cur}/${totalPages(paper) || "?"}`;
    clearTimeout(pane.patchTimer);
    pane.patchTimer = setTimeout(() => {
      if (!paperById(pane.id) || pane.lastPatchPage === cur) return;
      pane.lastPatchPage = cur;
      patchPaper(pane.id, { last_page: cur }).then(() => { if (V && currentPaperId() === pane.id && S.tool === "info") renderPanel(); }, () => {});
    }, LAST_PAGE_MS);
    if (V && S.tool === "outline" && currentPaperId() === pane.id) renderPanel();
  }

  /* instant: nhảy thẳng (mở paper, nhảy từ URL) và nhớ trang đích để chỉnh lại khi trang đó biết kích
     thước thật (khung 1:1.3 tạm → ảnh về thì chiều cao các trang trước đổi, vị trí trôi). */
  function goPage(pane, n, { instant = false } = {}) {
    const page = pane.pages[clamp(n, 1, pane.pages.length) - 1];
    if (!page) return;
    pane.jumpTo = instant ? page.n : null;
    pane.scroll.scrollTo({ top: page.el.offsetTop - 16, behavior: !instant && Shell.motionOn() ? "smooth" : "auto" });
  }

  function mirrorScroll(pane) {
    if (!V) return;
    const otherId = pane.idx === 0 ? secondId() : S.active;
    const other = otherId ? V.panes.get(otherId) : null;
    if (!other || other === pane) return;
    const max = pane.scroll.scrollHeight - pane.scroll.clientHeight;
    const ratio = max > 0 ? pane.scroll.scrollTop / max : 0;
    const target = Math.round(ratio * (other.scroll.scrollHeight - other.scroll.clientHeight));
    if (Math.abs(other.scroll.scrollTop - target) < 2) return;
    other.syncing = true;
    other.scroll.scrollTop = target;
  }

  function setZoom(pane, dir, exact) {
    let at = ZOOMS.indexOf(pane.zoom);
    if (at === -1) at = 3;
    const zoom = exact || ZOOMS[clamp(at + dir, 0, ZOOMS.length - 1)];
    if (zoom === pane.zoom) return;
    const keep = pane.cur;
    pane.zoom = zoom;
    pane.scroll.style.setProperty("--rs-page-w", `${Math.round(PAGE_W * zoom)}px`);
    pane.scroll.style.setProperty("--rs-zoom", String(zoom));   // điện thoại: bề rộng trang = (ô − 16px) × zoom
    pane.zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
    const dpi = zoom >= 1.5 ? DPI_HI : DPI;
    if (dpi !== pane.dpi) {
      pane.dpi = dpi;
      for (const page of pane.pages) {
        if (page.state !== 2) continue;
        page.state = 0;
        if (page.url) URL.revokeObjectURL(page.url);
        page.url = null;
      }
    }
    requestAnimationFrame(() => {
      goPage(pane, keep);
      for (const page of pane.pages) if (page.state === 0) { pane.io.unobserve(page.el); pane.io.observe(page.el); }
    });
  }

  function pickColorMenu(anchor) {
    dropdown(anchor, HL.map((c) => ({ label: c.name, onSelect: () => { S.hl = c.color; saveSession(); renderAll(); } })), { align: "start", width: 150 });
  }

  function moreMenu(pane, anchor) {
    dropdown(anchor, [
      { label: "Trang trước", icon: "arrow-left", hint: "←", onSelect: () => goPage(pane, pane.cur - 1) },
      { label: "Trang sau", icon: "arrow-right", hint: "→", onSelect: () => goPage(pane, pane.cur + 1) },
      { label: "Tìm trong PDF", icon: "search", hint: `${MOD}+F`, onSelect: () => askFind(pane) },
      { separator: true },
      ...HL.map((c) => ({ label: `Highlight ${c.name.toLowerCase()}`, icon: c.color === S.hl ? "check" : "highlighter", onSelect: () => { S.hl = c.color; saveSession(); renderAll(); } })),
      { label: S.showAnno ? "Ẩn ghi chú bên lề" : "Hiện ghi chú bên lề", icon: "eye", onSelect: () => { S.showAnno = !S.showAnno; saveSession(); renderAll(); } },
      { separator: true },
      { label: "Phóng to", icon: "plus", onSelect: () => setZoom(pane, 1) },
      { label: "Thu nhỏ", icon: "minus", onSelect: () => setZoom(pane, -1) },
    ], { align: "end", width: 220 });
  }

  /* Tìm trong PDF: duyệt lớp chữ từng trang (tải lười, cache) từ trang hiện tại; lần sau cùng từ → trang kế tiếp. */
  async function askFind(pane) {
    const q = await dialog({ icon: "search", title: "Tìm trong PDF", input: { value: pane.find ? pane.find.q : "", placeholder: "Từ hoặc cụm từ…" }, confirmLabel: "Tìm", signal: V ? V.ctx.signal : undefined });
    if (!q) return;
    await findInPane(pane, q);
  }

  async function findInPane(pane, q) {
    const needle = fold(q.trim());
    if (!needle) return;
    const total = pane.pages.length;
    const start = pane.find && pane.find.q === q ? pane.find.page + 1 : pane.cur;
    const close = toast(`Đang tìm «${q}»…`, "ok", { duration: Infinity });
    try {
      for (let i = 0; i < total; i++) {
        const n = ((start - 1 + i) % total) + 1;
        const data = await fetchWords(pane, n);
        if (!V || !V.panes.has(pane.id)) return;
        if (!data || !data.words || !data.words.length) continue;
        const words = data.words;
        const hits = [];
        // khớp từng từ, hoặc cụm từ liên tiếp trên cùng dòng
        const parts = needle.split(/\s+/).filter(Boolean);
        for (let k = 0; k < words.length; k++) {
          let ok = true;
          for (let j = 0; j < parts.length; j++) {
            const w = words[k + j];
            if (!w || !fold(w.text).includes(parts[j]) && !(j === 0 && parts.length === 1 && fold(w.text).includes(parts[0]))) { ok = false; break; }
          }
          if (ok) for (let j = 0; j < parts.length; j++) hits.push(words[k + j]);
        }
        if (!hits.length) continue;
        pane.find = { q, page: n, rects: hits.map((w) => ({ x: w.x0, y: w.y0, w: w.x1 - w.x0, h: w.y1 - w.y0 })) };
        paintAll(pane);
        goPage(pane, n);
        close();
        toast(`«${q}» · trang ${n} · ${hits.length} chỗ.`);
        return;
      }
      pane.find = null;
      paintAll(pane);
      close();
      toast(`Không thấy «${q}» trong lớp chữ của paper.`, "danger");
    } catch (error) {
      close();
      if (!isAbort(error)) toast(say(error, "Không tìm được."), "danger");
    }
  }

  /* ── Bôi đen → menu Highlight · Ghi chú · Hỏi AI · Dịch · Chép ── */
  function readSelection(pane) {
    if (!V || !V.panes.has(pane.id)) return;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) { hideSelMenu(pane); return; }
    const range = sel.getRangeAt(0);
    if (!pane.scroll.contains(range.commonAncestorContainer)) { hideSelMenu(pane); return; }
    let best = null;
    for (const page of pane.pages) {
      if (page.state !== 2 || !range.intersectsNode(page.words)) continue;
      const spans = [...page.words.children].filter((s) => s._w && range.intersectsNode(s));
      if (!spans.length) continue;
      if (!best || spans.length > best.spans.length) best = { page, spans };
    }
    if (!best) { hideSelMenu(pane); return; }
    const lines = new Map();
    const text = [];
    for (const s of best.spans) {
      const key = `${s.dataset.b}:${s.dataset.l}`;
      const w = s._w;
      const r = lines.get(key);
      if (!r) lines.set(key, { x0: w.x0, y0: w.y0, x1: w.x1, y1: w.y1 });
      else { r.x0 = Math.min(r.x0, w.x0); r.y0 = Math.min(r.y0, w.y0); r.x1 = Math.max(r.x1, w.x1); r.y1 = Math.max(r.y1, w.y1); }
      text.push(w.text);
    }
    const rects = [...lines.values()].map((r) => ({ x: round4(r.x0), y: round4(r.y0), w: round4(r.x1 - r.x0), h: round4(r.y1 - r.y0) }));
    S.pendingSel = { paneId: pane.id, paperId: pane.id, page: best.page.n, rects, quote: text.join(" ").replace(/\s+/g, " ").trim().slice(0, 2000) };
    showSelMenu(pane);
  }
  const round4 = (v) => Math.round(v * 10000) / 10000;

  function showSelMenu(pane) {
    hideSelMenu(pane, false);
    const item = (label, key, iconName, cls, fn) => h("button", { type: "button", class: cls, onClick: (event) => { event.stopPropagation(); fn(); } },
      icon(iconName, { size: 12, sw: 2.2 }), label, h("kbd", null, `${MOD}+${key}`));
    // touchstart/pointerdown không preventDefault (giữ click); selectionchange toàn cục trì hoãn việc ẩn trên cảm ứng.
    pane.menu = h("div", { class: "rs-selmenu", role: "toolbar", "aria-label": "Thao tác với vùng chọn", onMousedown: (event) => event.stopPropagation(), onTouchstart: (event) => event.stopPropagation() },
      item("Highlight", "H", "highlighter", null, () => selAction("highlight")),
      item("Ghi chú", "E", "pen", null, () => selAction("note")),
      item("Hỏi AI", "A", "chat", "is-accent", () => selAction("ask")),
      item("Dịch", "T", "translate", null, () => selAction("translate")),
      item("Chép", "C", "copy", "is-muted", () => selAction("copy")));
    pane.el.append(pane.menu);
  }

  function hideSelMenu(pane, clearSel = true) {
    if (pane.menu) { pane.menu.remove(); pane.menu = null; }
    if (clearSel && S.pendingSel && S.pendingSel.paneId === pane.id) S.pendingSel = null;
  }

  async function selAction(kind) {
    const sel = S.pendingSel;
    if (!sel) return;
    const pane = V && V.panes.get(sel.paneId);
    if (kind === "copy") {
      await copyText(sel.quote);
      if (pane) hideSelMenu(pane);
      window.getSelection()?.removeAllRanges();
      return;
    }
    if (kind === "ask" || kind === "translate") {
      S.quoteCtx = { paperId: sel.paperId, text: sel.quote };
      S.tool = "chat";
      chatOf(chatKey("paper", sel.paperId)).draft = kind === "ask" ? "Giải thích đoạn này bằng tiếng Việt" : "Dịch đoạn này sang tiếng Việt";
      if (pane) hideSelMenu(pane);
      window.getSelection()?.removeAllRanges();
      saveSession();
      renderAll();
      return;
    }
    // highlight / note → POST annotation
    if (pane) hideSelMenu(pane, false);
    const body = { page: sel.page, rects: sel.rects, color: S.hl, quote: sel.quote };
    try {
      const anno = await Shell.api(`/research/papers/${enc(sel.paperId)}/annotations`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
      S.pendingSel = null;
      window.getSelection()?.removeAllRanges();
      const d = detailOf(sel.paperId);
      if (d.data) d.data.annotations = [...(d.data.annotations || []), anno && anno.id ? anno : { id: `tmp-${Date.now()}`, ...body }];
      else await ensureDetail(sel.paperId);
      const row = paperById(sel.paperId);
      if (row) row.annotation_count = (annotationsOf(sel.paperId) || []).length;
      repaintPaper(sel.paperId);
      if (kind === "note") { S.focusAnno = anno && anno.id ? anno.id : null; S.tool = "notes"; saveSession(); }
      else toast("Đã lưu highlight.");
      renderAll();
    } catch (error) {
      if (routeMissing(error)) toast("Máy chủ chưa hỗ trợ highlight (POST /research/papers/{id}/annotations).", "danger");
      else toast(say(error, "Không lưu được highlight."), "danger");
    }
  }

  /* ══════════════════════════════════════════════════════════════
     HỎI PAPER / HỎI CẢ DỰ ÁN — SSE qua Shell.stream; nhiều LUỒNG mỗi
     paper / dự án, lưu máy chủ (/research/threads). Máy chủ chưa có
     route luồng → một luồng SESSION_THREAD chỉ sống trong phiên như cũ.
     ══════════════════════════════════════════════════════════════ */
  function chatOf(key) {
    let c = S.chats.get(key);
    if (!c) { c = { msgs: [], draft: "", ctrl: null, loaded: false, loading: false, loadError: null }; S.chats.set(key, c); }
    return c;
  }

  const threadKey = (scope, id) => `${scope}:${id}`;
  function threadsOf(tkey) {
    let t = S.threads.get(tkey);
    if (!t) { t = { list: null, busy: false, error: null, missing: false, current: null, seq: 0 }; S.threads.set(tkey, t); }
    return t;
  }
  /* Luồng đang mở của một paper / dự án: id máy chủ, NEW_THREAD khi chưa có, SESSION_THREAD khi route thiếu. */
  function currentThreadId(tkey) {
    const t = threadsOf(tkey);
    if (t.missing) return SESSION_THREAD;
    return t.current || NEW_THREAD;
  }
  const chatKey = (scope, id) => `${threadKey(scope, id)}:${currentThreadId(threadKey(scope, id))}`;
  const currentThread = (tkey) => { const t = threadsOf(tkey); return (t.list || []).find((x) => x.id === t.current) || null; };
  const threadTitle = (thread) => (thread && thread.title) || "Luồng chưa đặt tên";
  const sortThreads = (list) => [...list].sort((a, b) => String(b.last_message_at || b.created_at || "").localeCompare(String(a.last_message_at || a.created_at || "")));

  /* Danh sách luồng (GET /research/threads?scope=&id=) rồi chọn luồng: đang mở → dùng gần nhất (lac.research) → mới nhất → NEW. */
  async function loadThreads(tkey, scope, id, { quiet = false } = {}) {
    const t = threadsOf(tkey);
    if (t.busy) return t;
    const my = ++t.seq;
    t.busy = true;
    if (!quiet) t.error = null;
    try {
      const rows = await Shell.api(`/research/threads?scope=${enc(scope)}&id=${enc(id)}`, { signal: V ? V.ctx.signal : undefined });
      if (my !== t.seq) return t;
      t.list = sortThreads(Array.isArray(rows) ? rows.filter((r) => r && typeof r.id === "string") : []);
      t.missing = false;
      t.error = null;
      pickThread(tkey);
    } catch (error) {
      if (my !== t.seq || isAbort(error)) return t;
      if (routeMissing(error)) { t.missing = true; t.list = []; }
      else t.error = error;
    } finally {
      if (my === t.seq) t.busy = false;
    }
    if (V) renderPanel();
    return t;
  }

  function pickThread(tkey) {
    const t = threadsOf(tkey);
    const list = t.list || [];
    const has = (id) => list.some((x) => x.id === id);
    if (t.current === NEW_THREAD) return;              // người dùng vừa bấm "+ Luồng mới": giữ panel trống
    if (t.current && has(t.current)) return;
    const stored = storedThread(tkey);
    const next = (stored && has(stored) ? stored : null) || (list[0] ? list[0].id : null);
    // Bản nháp gõ trước khi danh sách về được chuyển sang luồng được chọn.
    const draft = S.chats.get(`${tkey}:${NEW_THREAD}`);
    t.current = next;
    if (next && draft && draft.draft && !chatOf(`${tkey}:${next}`).draft) { chatOf(`${tkey}:${next}`).draft = draft.draft; draft.draft = ""; }
  }

  function setThread(tkey, threadId) {
    const t = threadsOf(tkey);
    const before = `${tkey}:${currentThreadId(tkey)}`;
    if (t.current === threadId) return;
    stopQuestion(before);
    t.current = threadId;
    rememberThread(tkey, threadId && threadId !== NEW_THREAD ? threadId : null);
    renderPanel();
  }

  /* GET /research/threads/{id} → dựng lại tin nhắn; chip [n] = sources[n-1] (page, paper_id/document_id). */
  async function loadThreadMessages(tkey, threadId) {
    const key = `${tkey}:${threadId}`;
    const chat = chatOf(key);
    if (chat.loaded || chat.loading || chat.ctrl) return;
    chat.loading = true;
    chat.loadError = null;
    try {
      const data = await Shell.api(`/research/threads/${enc(threadId)}`, { signal: V ? V.ctx.signal : undefined });
      if (chat.ctrl) return;                            // đã bắt đầu hỏi trong lúc chờ: không ghi đè
      const msgs = [];
      let lastQ = "";
      for (const m of Array.isArray(data && data.messages) ? data.messages : []) {
        if (!m || typeof m !== "object") continue;
        const text = String(m.content ?? "");
        if (m.role === "user") { lastQ = text; msgs.push({ role: "user", text, quote: null }); continue; }
        const sources = Array.isArray(m.sources) ? m.sources.filter((s) => s && typeof s === "object") : [];
        msgs.push({ role: "ai", text, sources, papers: {}, live: false, error: null, question: lastQ, quote: null, model: m.model_used || null, node: null, frame: 0 });
      }
      chat.msgs = msgs;
      chat.loaded = true;
      const t = threadsOf(tkey);
      if (data && data.id && t.list) {
        const at = t.list.findIndex((x) => x.id === data.id);
        if (at !== -1) t.list[at] = { ...t.list[at], ...data, messages: undefined };
      }
    } catch (error) {
      if (isAbort(error)) return;
      if (error && error.code === "RESEARCH_THREAD_NOT_FOUND") { dropThread(tkey, threadId); toast(ERROR_VI.RESEARCH_THREAD_NOT_FOUND, "danger"); }
      else chat.loadError = error;
    } finally {
      chat.loading = false;
    }
    if (V) renderPanel();
  }

  /* Luồng biến mất phía máy chủ (xoá / 404): bỏ khỏi danh sách, quên trong store, chọn luồng khác. */
  function dropThread(tkey, threadId) {
    const t = threadsOf(tkey);
    if (t.list) t.list = t.list.filter((x) => x.id !== threadId);
    S.chats.delete(`${tkey}:${threadId}`);
    if (storedThread(tkey) === threadId) rememberThread(tkey, null);
    if (t.current === threadId) { t.current = null; pickThread(tkey); }
  }

  async function createThread(tkey, scope, id) {
    const row = await Shell.api("/research/threads", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ scope, id }) });
    if (!row || typeof row.id !== "string") throw new Error("Máy chủ không trả về luồng vừa tạo.");
    const t = threadsOf(tkey);
    t.list = [row, ...(t.list || []).filter((x) => x.id !== row.id)];
    // Bản nháp / tin nhắn của luồng NEW chuyển sang luồng thật.
    const fresh = S.chats.get(`${tkey}:${NEW_THREAD}`);
    if (fresh) { S.chats.delete(`${tkey}:${NEW_THREAD}`); fresh.loaded = true; S.chats.set(`${tkey}:${row.id}`, fresh); }
    else chatOf(`${tkey}:${row.id}`).loaded = true;
    t.current = row.id;
    rememberThread(tkey, row.id);
    return row;
  }

  async function renameThread(tkey, thread) {
    const title = await dialog({ icon: "pen", title: "Đổi tên luồng", input: { value: thread.title || "", placeholder: "Tên luồng…", maxlength: 200 }, confirmLabel: "Lưu", signal: V ? V.ctx.signal : undefined });
    if (title === null || title === undefined || title === false) return;
    const name = String(title).trim();
    if (!name || name === thread.title) return;
    try {
      const row = await Shell.api(`/research/threads/${enc(thread.id)}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ title: name }) });
      const t = threadsOf(tkey);
      if (t.list) t.list = t.list.map((x) => (x.id === thread.id ? { ...x, ...(row && row.id ? row : { title: name }) } : x));
      renderPanel();
    } catch (error) {
      if (error && error.code === "RESEARCH_THREAD_NOT_FOUND") { dropThread(tkey, thread.id); renderPanel(); }
      toast(say(error, "Không đổi tên được luồng."), "danger");
    }
  }

  async function deleteThread(tkey, thread) {
    const n = Number(thread.message_count) || 0;
    const ok = await confirmDialog({ title: "Xoá luồng chat?", body: `«${threadTitle(thread)}»${n ? ` cùng ${n} tin nhắn` : ""} sẽ bị xoá khỏi máy chủ.`, confirmLabel: "Xoá", signal: V ? V.ctx.signal : undefined });
    if (!ok) return;
    try {
      stopQuestion(`${tkey}:${thread.id}`);
      await Shell.api(`/research/threads/${enc(thread.id)}`, { method: "DELETE" });
      dropThread(tkey, thread.id);
      rememberThread(tkey, threadsOf(tkey).current);
      toast("Đã xoá luồng.");
      renderPanel();
    } catch (error) {
      if (error && error.code === "RESEARCH_THREAD_NOT_FOUND") { dropThread(tkey, thread.id); renderPanel(); return; }
      toast(say(error, "Không xoá được luồng."), "danger");
    }
  }

  function threadMenu(anchor, tkey) {
    const t = threadsOf(tkey);
    const cur = currentThread(tkey);
    const items = (t.list || []).map((x) => ({
      label: threadTitle(x), icon: x.id === t.current ? "check" : "chat",
      hint: `${Number(x.message_count) || 0} tin · ${fmtRelative(x.last_message_at || x.created_at)}`,
      onSelect: () => setThread(tkey, x.id),
    }));
    if (!items.length) items.push({ label: "Chưa có luồng nào — gửi câu hỏi đầu tiên.", disabled: true });
    dropdown(anchor, [
      ...items,
      { separator: true },
      { label: "Luồng mới", icon: "plus", onSelect: () => setThread(tkey, NEW_THREAD) },
      { label: "Đổi tên luồng này", icon: "pen", disabled: !cur, onSelect: () => cur && renameThread(tkey, cur) },
      { label: "Xoá luồng này", icon: "trash", tone: "danger", disabled: !cur, onSelect: () => cur && deleteThread(tkey, cur) },
    ], { align: "end", width: 280, className: "rs-thread-menu" });
  }

  async function sendQuestion(key, scope, id, question, quote, threadId) {
    const chat = chatOf(key);
    const q = String(question || "").trim();
    if (!q || chat.ctrl) return;
    const ai = { role: "ai", text: "", sources: [], papers: {}, live: true, error: null, question: q, quote: quote || null, node: null, frame: 0 };
    chat.msgs.push({ role: "user", text: q, quote: quote || null }, ai);
    chat.draft = "";
    if (scope === "paper") S.quoteCtx = null;
    const ctrl = new AbortController();
    chat.ctrl = ctrl;
    const stopOnLeave = () => ctrl.abort();
    if (V) V.ctx.signal.addEventListener("abort", stopOnLeave, { once: true });
    renderPanel();
    const tkey = threadKey(scope, id);
    try {
      await Shell.stream("/research/chat", { scope, id, question: q, quote: quote || undefined, thread_id: threadId || undefined, stream: true }, {
        signal: ctrl.signal, hints: ERROR_VI,
        on(type, data) {
          if (type === "meta") {
            ai.sources = Array.isArray(data.sources) ? data.sources.filter((s) => s && typeof s === "object") : [];
            ai.papers = data.papers && typeof data.papers === "object" ? data.papers : {};
            ai.model = data.model_used || null;
          } else if (type === "token") {
            ai.text += String(data.content ?? "");
            paintMsg(ai);
          }
        },
      });
    } catch (error) {
      if (isAbort(error)) ai.stopped = true;
      else if (routeMissing(error)) ai.missing = true;
      else {
        ai.error = say(error, "Không nhận được câu trả lời.");
        if (threadId && error && error.code === "RESEARCH_THREAD_NOT_FOUND") dropThread(tkey, threadId);
      }
    } finally {
      ai.live = false;
      chat.ctrl = null;
      if (V) V.ctx.signal.removeEventListener("abort", stopOnLeave);
    }
    if (V) renderPanel();
    // Sau tin đầu máy chủ đặt title + message_count: tải lại danh sách (lặng, không xoá list cũ).
    if (threadId && V) loadThreads(tkey, scope, id, { quiet: true });
  }

  function stopQuestion(key) {
    const chat = S.chats.get(key);
    if (chat && chat.ctrl) chat.ctrl.abort();
  }

  /* Vẽ lại chữ của một câu trả lời đang stream (gộp theo khung hình). */
  function paintMsg(ai) {
    if (!ai.node || !ai.node.isConnected || ai.frame) return;
    ai.frame = requestAnimationFrame(() => { ai.frame = 0; if (ai.node && ai.node.isConnected) fillMsgText(ai.node, ai); });
  }

  /* Chữ + chip trích dẫn: "[Source N]" / "[Nguồn N]" / "[N]" (N ≤ số nguồn) → [Paper · tr.N]; **đậm** → strong. */
  const CITE_RE = /\[\s*(?:Source|Ngu[oồ]n)?\s*(\d{1,3})\s*\]/gi;
  function fillMsgText(node, ai) {
    node.replaceChildren();
    const text = ai.text || "";
    let last = 0;
    const pushText = (chunk) => {
      if (!chunk) return;
      const parts = chunk.split(/(\*\*[^*]+\*\*)/g);
      for (const part of parts) {
        if (!part) continue;
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4) node.append(h("strong", null, part.slice(2, -2)));
        else node.append(document.createTextNode(part));
      }
    };
    CITE_RE.lastIndex = 0;
    let match;
    while ((match = CITE_RE.exec(text))) {
      const n = Number(match[1]);
      const explicit = /source|ngu/i.test(match[0]);
      if (!explicit && !(n >= 1 && n <= ai.sources.length)) continue;
      pushText(text.slice(last, match.index));
      node.append(citeChip(ai, n));
      last = match.index + match[0].length;
    }
    pushText(text.slice(last));
    node.classList.toggle("is-live", Boolean(ai.live));
  }

  function sourcePaper(ai, src) {
    // Nguồn đã lưu (GET /research/threads/{id}) mang sẵn paper_id / short_name / color_index.
    if (src && typeof src.paper_id === "string") {
      const row = paperById(src.paper_id);
      const ci = Number(src.color_index);
      return { id: src.paper_id, short: src.short_name || shortOf(row), color: ci >= 1 ? `var(--c${clamp(ci, 1, 5)})` : colorOf(row) };
    }
    const docId = src && src.document_id;
    const fromMeta = docId && ai.papers && ai.papers[docId];
    if (fromMeta && fromMeta.paper_id) return { id: fromMeta.paper_id, short: fromMeta.short_name || shortOf(paperById(fromMeta.paper_id)), color: fromMeta.color_index ? `var(--c${clamp(Number(fromMeta.color_index), 1, 5)})` : colorOf(paperById(fromMeta.paper_id)) };
    const row = docId ? paperByDoc(docId) : null;
    return row ? { id: row.id, short: shortOf(row), color: colorOf(row) } : null;
  }
  const pageOf = (src) => { const p = Number(src && (src.page ?? (Array.isArray(src.pages) ? src.pages[0] : null))); return Number.isFinite(p) && p > 0 ? p : null; };

  function citeChip(ai, n) {
    const src = ai.sources[n - 1];
    const paper = src ? sourcePaper(ai, src) : null;
    if (!paper) return h("span", { class: "rs-cite is-plain", title: src ? (src.filename || "") : "Nguồn không có trong luồng" }, `[${n}]`);
    const page = pageOf(src);
    const heading = Array.isArray(src.heading_path) && src.heading_path.length ? src.heading_path[src.heading_path.length - 1] : (typeof src.heading_path === "string" ? src.heading_path : "");
    const where = page ? `tr.${page}` : (heading ? heading.slice(0, 24) : "");
    return h("button", {
      type: "button", class: "rs-cite", title: [src.filename, heading, page ? `trang ${page}` : null].filter(Boolean).join(" · "),
      // Chỉ nhảy tới trang; giữ nguyên panel đang mở (Hỏi paper / Hỏi cả dự án) để còn đọc tiếp câu trả lời.
      onClick: () => openPaper(paper.id, { page }),
    }, where ? `${paper.short} · ${where}` : paper.short);
  }

  function distinctPapers(ai) {
    const seen = new Map();
    for (const src of ai.sources || []) { const p = sourcePaper(ai, src); if (p && !seen.has(p.id)) seen.set(p.id, p); }
    return [...seen.values()];
  }

  async function saveToNote(paperId, ai) {
    if (!paperId) { toast("Chưa mở paper nào để lưu ghi chú.", "danger"); return; }
    const d = await ensureDetail(paperId);
    if (!d.data) { toast("Chưa tải được paper này.", "danger"); return; }
    const block = `\n\n> ${ai.question}\n\n${ai.text.trim()}\n`;
    const note = `${d.data.note_md || ""}${block}`.replace(/^\n+/, "");
    try {
      await patchPaper(paperId, { note_md: note });
      d.data.note_md = note;
      toast("Đã lưu vào ghi chú.");
      if (S.tool === "notes") renderPanel();
    } catch (error) {
      toast(say(error, "Không lưu được ghi chú."), "danger");
    }
  }

  function buildChatPanel(scope, cp) {
    const targetId = scope === "paper" ? cp.id : S.pid;
    const tkey = threadKey(scope, targetId);
    const T = threadsOf(tkey);
    // Khóa chat đổi theo luồng đang mở; panel được tái dùng (renderPanel → refresh) nên luôn tra lại.
    const key = () => `${tkey}:${currentThreadId(tkey)}`;
    const chat = () => chatOf(key());
    let shownKey = key();
    const indexedCount = papers().filter((p) => p.indexed).length;
    const list = h("div", { class: "rs-msgs" });
    const quoteBox = h("div", { class: "rs-quote", hidden: true });
    const threadBox = h("div", { class: "rs-thread-row" });
    const threadState = h("div", { class: "rs-thread-state", hidden: true });
    if (!T.missing) loadThreads(tkey, scope, targetId, { quiet: T.list !== null });

    const renderThreadRow = () => {
      threadBox.hidden = T.missing;
      threadState.hidden = true;
      threadState.replaceChildren();
      if (T.missing) {
        threadState.hidden = false;
        threadState.append(missingApiState({ feature: "luồng chat lưu được", endpoint: "GET /research/threads", text: "Lịch sử hỏi đáp chỉ sống trong phiên này." }));
        return;
      }
      const cur = currentThread(tkey);
      const isNew = currentThreadId(tkey) === NEW_THREAD;
      const titleText = T.list === null && T.busy ? "Đang tải luồng…" : isNew ? "Luồng mới" : threadTitle(cur);
      const menuBtn = h("button", { type: "button", class: "rs-ibtn", title: "Luồng chat", "aria-label": "Luồng chat", "aria-haspopup": "menu", disabled: T.list === null && T.busy, onClick: () => threadMenu(menuBtn, tkey) }, icon("more-horizontal", { size: 14 }));
      threadBox.replaceChildren(...[
        h("span", { class: ["rs-thread-title", isNew && "is-new"], title: titleText }, titleText),
        cur && Number(cur.message_count) ? h("span", { class: "rs-thread-meta" }, `${cur.message_count} tin`) : null,
        menuBtn,
        h("button", { type: "button", class: "rs-btn rs-thread-new", title: "Bắt đầu luồng chat mới", disabled: isNew && !chat().msgs.length, onClick: () => setThread(tkey, NEW_THREAD) }, icon("plus", { size: 12, sw: 2.4 }), "Luồng mới"),
      ].filter(Boolean));
      if (T.error) {
        threadState.hidden = false;
        threadState.append(h("div", { class: "rs-msg-err" }, say(T.error, "Không tải được danh sách luồng."),
          h("button", { type: "button", class: "rs-btn", style: { height: "24px", fontSize: "11px" }, onClick: () => loadThreads(tkey, scope, targetId) }, icon("retry", { size: 12 }), "Thử lại")));
      }
    };

    const renderMsgs = () => {
      const c = chat();
      const tid = currentThreadId(tkey);
      if (tid !== NEW_THREAD && tid !== SESSION_THREAD && !c.loaded && !c.loading && !c.loadError && !c.ctrl) loadThreadMessages(tkey, tid);
      if (c.loading && !c.msgs.length) {
        list.replaceChildren(h("div", { class: "rs-msg-user" }, skeleton({ w: "60%", h: 30, r: 12 })), skeleton({ w: "95%", h: 12 }), skeleton({ w: "88%", h: 12 }), skeleton({ w: "70%", h: 12 }));
        return;
      }
      if (c.loadError && !c.msgs.length) {
        list.replaceChildren(h("div", { class: "rs-msg-err" }, say(c.loadError, "Không tải được lịch sử luồng."),
          h("button", { type: "button", class: "rs-btn", style: { height: "24px", fontSize: "11px" }, onClick: () => { c.loadError = null; refresh(); } }, icon("retry", { size: 12 }), "Thử lại")));
        return;
      }
      list.replaceChildren(...c.msgs.map((m) => {
        if (m.role === "user") return h("div", { class: "rs-msg-user" }, h("div", null, m.quote ? h("div", { class: "rs-quote", style: { marginBottom: "6px", background: "var(--surface)" } }, icon("quote", { size: 12 }), h("span", null, m.quote)) : null, m.text));
        const text = h("div", { class: "rs-msg-text" });
        m.node = text;
        fillMsgText(text, m);
        const nodes = [text];
        if (m.live && !m.text) nodes.unshift(h("div", { class: "rs-typing", "aria-label": "Đang trả lời" }, h("i"), h("i"), h("i")));
        if (m.missing) nodes.push(missingApiState({ feature: "hỏi đáp trong Không gian Nghiên cứu", endpoint: "POST /research/chat" }));
        else if (m.error) nodes.push(h("div", { class: "rs-msg-err" }, m.error, h("button", { type: "button", class: "rs-btn", style: { height: "24px", fontSize: "11px" }, onClick: () => retry(m) }, icon("retry", { size: 12 }), "Thử lại")));
        else if (m.stopped && !m.text) nodes.push(h("div", { class: "rs-chat-note" }, "Đã dừng."));
        if (!m.live && m.sources.length) {
          const ps = distinctPapers(m);
          if (ps.length) nodes.push(h("div", { class: "rs-sources" }, h("small", null, "Nguồn đã dùng:"), ...ps.map((p) => h("button", { type: "button", class: "rs-src", onClick: () => openPaper(p.id) }, h("i", { style: { background: p.color } }), p.short))));
        }
        if (!m.live && m.text) {
          const ps = distinctPapers(m);
          nodes.push(h("div", { class: "rs-msg-acts" },
            h("button", { type: "button", onClick: () => copyText(m.text) }, "Sao chép"),
            h("button", { type: "button", onClick: () => saveToNote(scope === "paper" ? cp.id : currentPaperId(), m) }, "Lưu vào ghi chú"),
            scope === "project" && ps.length >= 2 ? h("button", { type: "button", class: "is-accent", onClick: () => { S.sel2 = new Set(ps.map((p) => p.id)); S.tool = "compare"; saveSession(); renderAll(); } }, `So sánh ${ps.length} paper này →`) : null));
        }
        return h("div", { class: "rs-msg-ai" }, ...nodes);
      }));
    };
    const retry = (m) => { chat().draft = m.question; input.value = m.question; send(); };

    const input = h("textarea", { class: "rs-ask-input", rows: "1", placeholder: scope === "paper" ? "Hỏi về paper này…" : `Hỏi về ${indexedCount} paper trong dự án…`, "aria-label": "Câu hỏi", maxlength: "4000" });
    input.value = chat().draft || "";
    const sendBtn = h("button", { type: "button", title: "Gửi (Enter)" }, icon("send", { size: 13, sw: 2.2 }));
    const autosize = () => { input.style.height = "auto"; input.style.height = `${Math.min(120, input.scrollHeight)}px`; };
    input.addEventListener("input", () => { chat().draft = input.value; autosize(); });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); send(); }
    });
    let creating = false;
    const send = async () => {
      const k = key();
      const c = chat();
      if (c.ctrl) { stopQuestion(k); return; }
      if (creating) return;
      const quote = scope === "paper" && S.quoteCtx && S.quoteCtx.paperId === cp.id ? S.quoteCtx.text : null;
      const q = input.value.trim();
      if (!q) return;
      if (scope === "project" && !indexedCount) { toast("Chưa paper nào lập chỉ mục xong để hỏi.", "danger"); return; }
      if (scope === "paper" && cp && cp.indexed === false) { toast(ERROR_VI.RESEARCH_NOT_INDEXED, "danger"); return; }
      let tid = currentThreadId(tkey);
      if (tid === NEW_THREAD) {
        if (T.list === null && T.busy) { toast("Đang tải danh sách luồng, thử lại sau một nhịp.", "danger"); return; }
        // Tin đầu của luồng mới: tạo luồng trước rồi gửi kèm thread_id.
        creating = true;
        sendBtn.disabled = true;
        try {
          tid = (await createThread(tkey, scope, targetId)).id;
        } catch (error) {
          if (routeMissing(error)) { T.missing = true; tid = SESSION_THREAD; }
          else { toast(say(error, "Không tạo được luồng chat."), "danger"); return; }
        } finally {
          creating = false;
          sendBtn.disabled = false;
        }
        if (!el.isConnected) return;
      }
      input.value = "";
      autosize();
      sendQuestion(key(), scope, targetId, q, quote, tid === SESSION_THREAD ? null : tid);
    };
    sendBtn.addEventListener("click", send);
    const syncSend = () => {
      const busy = Boolean(chat().ctrl);
      sendBtn.classList.toggle("is-stop", busy);
      sendBtn.replaceChildren(busy ? icon("stop", { size: 12 }) : icon("send", { size: 13, sw: 2.2 }));
      sendBtn.title = busy ? "Dừng" : "Gửi (Enter)";
    };
    const renderQuote = () => {
      const qc = scope === "paper" && S.quoteCtx && S.quoteCtx.paperId === cp.id ? S.quoteCtx : null;
      quoteBox.hidden = !qc;
      if (qc) quoteBox.replaceChildren(icon("quote", { size: 12 }), h("span", { title: qc.text }, qc.text),
        h("button", { type: "button", class: "rs-ibtn", title: "Bỏ đoạn trích", onClick: () => { S.quoteCtx = null; renderQuote(); } }, icon("x", { size: 11, sw: 2.4 })));
    };

    const hints = (scope === "paper" ? CHAT_HINTS_PAPER : CHAT_HINTS_PROJECT).map((t) => h("button", { type: "button", class: "rs-hint", onClick: () => { input.value = t; chat().draft = t; autosize(); input.focus(); } }, t));
    const note = scope === "project"
      ? h("div", { class: "rs-chat-note" }, "Trả lời dựa trên ", h("strong", null, `${indexedCount} paper`), ` đã lập chỉ mục trong dự án${indexedCount < papers().length ? ` (${papers().length - indexedCount} paper còn đang xử lý)` : ""}. Mỗi khẳng định có nhãn [paper · trang]; bấm để mở đúng chỗ.`)
      : (cp && cp.indexed === false ? h("div", { class: "rs-chat-note" }, ERROR_VI.RESEARCH_NOT_INDEXED) : null);
    const el = h("div", { class: "rs-panel-body rs-chat" }, threadBox, threadState, note, quoteBox, list,
      h("div", { class: "rs-hints" }, ...hints),
      h("div", { class: "rs-ask" }, input, sendBtn));
    const refresh = () => {
      // Đổi luồng: cất bản nháp đang gõ vào luồng cũ, lấy bản nháp của luồng mới.
      const k = key();
      if (k !== shownKey) { const old = S.chats.get(shownKey); if (old) old.draft = input.value; shownKey = k; input.value = chat().draft || ""; autosize(); }
      renderThreadRow(); renderMsgs(); renderQuote(); syncSend();
      requestAnimationFrame(() => { if (el.isConnected) el.scrollTop = el.scrollHeight; });
    };
    refresh();
    requestAnimationFrame(autosize);
    if (scope === "paper" && S.quoteCtx && S.quoteCtx.paperId === cp.id) requestAnimationFrame(() => input.focus());
    return { el, refresh };
  }

  /* ══════════════════════════════════════════════════════════════
     PANEL: Tóm tắt AI
     ══════════════════════════════════════════════════════════════ */
  async function generateSummary(id) {
    const d = detailOf(id);
    if (d.sumBusy) return;
    d.sumBusy = true;
    d.sumError = null;
    d.sumTried = true;
    renderPanel();
    try {
      const res = await Shell.api(`/research/papers/${enc(id)}/summary`, { method: "POST", headers: JSON_HEADERS, body: "{}", signal: V ? V.ctx.signal : undefined });
      if (!d.data) await ensureDetail(id);
      if (d.data && res) { d.data.summary = res.summary || null; d.data.summary_model = res.summary_model || null; d.data.summary_at = res.summary_at || null; }
      const row = paperById(id);
      if (row) { row.has_summary = Boolean(d.data && d.data.summary); if (row.stages) row.stages.summary = "done"; }
    } catch (error) {
      if (isAbort(error)) return;
      d.sumError = error;
    } finally {
      d.sumBusy = false;
    }
    renderAll();
  }

  function buildSummaryPanel(cp) {
    const d = detailOf(cp.id);
    const body = h("div", { class: "rs-panel-body" });
    if (!d.data) {
      if (d.error) body.append(errorState(d.error, () => ensureDetail(cp.id, { force: true })));
      else { ensureDetail(cp.id); body.append(skeleton({ w: "100%", h: 64, r: 11 }), skeleton({ w: "100%", h: 80, r: 11 }), skeleton({ w: "100%", h: 80, r: 11 })); }
      return { el: body };
    }
    const sum = d.data.summary;
    if (!sum) {
      if (d.sumBusy) {
        body.append(h("div", { class: "rs-sum-wait" },
          h("div", { class: "rs-sum-wait-text" }, icon("spark", { size: 14 }), `Đang đọc ${totalPages(cp) || "các"} trang… model 9b mất 30–120 giây.`),
          skeleton({ w: "100%", h: 64, r: 11 }), skeleton({ w: "100%", h: 80, r: 11 }), skeleton({ w: "90%", h: 80, r: 11 }), skeleton({ w: "100%", h: 80, r: 11 })));
        return { el: body };
      }
      if (d.sumError) {
        if (routeMissing(d.sumError)) body.append(missingApiState({ feature: "tóm tắt AI", endpoint: "POST /research/papers/{id}/summary" }));
        else body.append(errorState(d.sumError, () => generateSummary(cp.id)));
        return { el: body };
      }
      if (cp.indexed === false) {
        body.append(emptyState({ icon: "spark", title: "Chưa tóm tắt được", text: "Paper chưa lập chỉ mục xong (chưa có chữ). Tóm tắt sẽ tạo được khi OCR hoàn tất." }));
        return { el: body };
      }
      if (!d.sumTried) queueMicrotask(() => generateSummary(cp.id));
      body.append(emptyState({ icon: "spark", tone: "accent", title: "Chưa có tóm tắt", text: "AI đọc 3 trang đầu + 2 trang cuối rồi rút ra vấn đề, ý tưởng, kết quả, hạn chế.", action: { label: "Tạo tóm tắt AI", icon: "spark", onClick: () => generateSummary(cp.id) } }));
      return { el: body };
    }
    body.append(h("div", { class: "rs-brief" }, h("div", { class: "rs-label" }, "Tóm tắt một dòng"), h("div", null, sum.brief || "—")));
    for (const [key, label, cls] of SUM_CARDS) {
      body.append(h("div", { class: ["rs-sumcard", cls] }, h("div", { class: "rs-label" }, label), h("div", null, sum[key] || "—")));
    }
    const qs = Array.isArray(sum.questions) ? sum.questions.filter(Boolean).slice(0, 3) : [];
    if (qs.length) {
      body.append(h("div", null, h("div", { class: "rs-label rs-sub" }, "Câu hỏi gợi ý"), h("div", { class: "rs-stack" }, ...qs.map((q) => h("button", {
        type: "button", class: "rs-starter", onClick: () => { chatOf(chatKey("paper", cp.id)).draft = String(q); S.tool = "chat"; saveSession(); renderAll(); },
      }, icon("chat", { size: 12 }), String(q))))));
    }
    const rel = edges().filter((e) => e.a_paper_id === cp.id || e.b_paper_id === cp.id);
    if (rel.length) {
      body.append(h("div", null, h("div", { class: "rs-label rs-sub" }, "Liên quan trong kho"), h("div", { class: "rs-stack" }, ...rel.map((e) => {
        const otherId = e.a_paper_id === cp.id ? e.b_paper_id : e.a_paper_id;
        const other = paperById(otherId);
        const t = EDGE[e.type] || EDGE.builds;
        return h("button", { type: "button", class: "rs-rel", onClick: () => openPaper(otherId) },
          edgeLine(t, 16, 8), h("strong", null, shortOf(other)), h("span", null, t.label), h("small", null, "mở →"));
      }))));
    }
    body.append(h("div", { class: "rs-sum-meta" }, [d.data.summary_model, d.data.summary_at ? fmtRelative(d.data.summary_at) : null].filter(Boolean).join(" · "),
      h("button", { type: "button", class: "btn-link", disabled: d.sumBusy, onClick: () => generateSummary(cp.id) }, d.sumBusy ? "Đang tạo lại…" : "Tạo lại")));
    return { el: body };
  }

  function edgeLine(t, w, hgt) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", String(w)); svg.setAttribute("height", String(hgt)); svg.setAttribute("viewBox", `0 0 ${w} ${hgt}`);
    const line = document.createElementNS(ns, "line");
    const arrow = w > 20;
    line.setAttribute("x1", "0"); line.setAttribute("y1", String(hgt / 2)); line.setAttribute("x2", String(arrow ? w - 6 : w)); line.setAttribute("y2", String(hgt / 2));
    line.setAttribute("stroke", t.color); line.setAttribute("stroke-width", "2");
    if (t.dash) line.setAttribute("stroke-dasharray", t.dash);
    svg.append(line);
    if (arrow) {
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", `M${w - 8} 1l6 ${hgt / 2 - 1}-6 ${hgt / 2 - 1}`); path.setAttribute("fill", "none"); path.setAttribute("stroke", t.color); path.setAttribute("stroke-width", "2");
      svg.append(path);
    }
    return svg;
  }

  /* ══════════════════════════════════════════════════════════════
     PANEL: So sánh — 4 hàng dựng từ summary của các paper đã tick
     ══════════════════════════════════════════════════════════════ */
  const CMP_ROWS = [
    ["Phương pháp chính", "var(--accent)", (s) => s.idea],
    ["Tính toán", "var(--text-2)", (s) => [s.compute, s.input].filter(Boolean).join(" · ")],
    ["Kết quả", "var(--ok)", (s) => s.result],
    ["Hạn chế", "var(--warn)", (s) => s.limits],
  ];
  function compareIds(cp) {
    const ids = [...S.sel2].filter((id) => paperById(id));
    if (ids.length) return ids;
    return cp ? [cp.id] : [];
  }
  function buildComparePanel(cp) {
    const ids = compareIds(cp);
    const body = h("div", { class: "rs-panel-body" });
    for (const id of ids) ensureDetail(id);
    body.append(h("div", { class: "rs-cmp-chips" }, ...ids.map((id) => {
      const p = paperById(id);
      return h("span", { class: "rs-cmp-chip" }, h("i", { class: "rs-dot", style: { background: colorOf(p) } }), shortOf(p),
        h("button", { type: "button", class: "rs-ibtn", title: "Bỏ khỏi so sánh", onClick: () => { S.sel2.delete(id); renderAll(); } }, icon("x", { size: 9 })));
    }), h("small", null, ids.length < 2 ? "tick ≥ 2 paper ở thanh trái để so sánh" : "tick thêm ở thanh trái")));
    if (!ids.length) {
      body.append(emptyState({ icon: "columns", title: "Chưa chọn paper nào", text: "Tick ô vuông cạnh tên paper ở thanh trái, rồi bấm So sánh." }));
      return { el: body };
    }
    for (const [label, color, pick] of CMP_ROWS) {
      const row = h("div", { class: "rs-cmp-row" }, h("div", { class: "rs-cmp-head", style: { color } }, label));
      for (const id of ids) {
        const p = paperById(id);
        const d = detailOf(id);
        let content;
        if (!d.data && d.busy) content = h("span", { class: "rs-skel-text" }, skeleton({ w: "90%", h: 10 }), skeleton({ w: "60%", h: 10 }));
        else if (!d.data && d.error) content = h("span", null, h("strong", null, shortOf(p)), " · ", say(d.error, "không tải được"), " ", h("button", { type: "button", class: "btn-link", onClick: () => ensureDetail(id, { force: true }) }, "Thử lại"));
        else if (d.data && d.data.summary) content = h("span", null, h("strong", null, shortOf(p)), ` · ${pick(d.data.summary) || "—"}`);
        else if (d.sumBusy) content = h("span", null, h("strong", null, shortOf(p)), " · đang tạo tóm tắt…");
        else content = h("span", null, h("strong", null, shortOf(p)), " · chưa có tóm tắt · ", h("button", { type: "button", class: "btn-link", disabled: p.indexed === false, title: p.indexed === false ? ERROR_VI.RESEARCH_NOT_INDEXED : "", onClick: () => generateSummary(id) }, "Tạo"));
        row.append(h("div", { class: "rs-cmp-cell" }, h("i", { class: "rs-dot", style: { background: colorOf(p) } }), content));
      }
      body.append(row);
    }
    body.append(h("div", { class: "rs-row-btns" },
      h("button", { type: "button", class: "rs-btn", onClick: () => exportCompare(ids) }, "Xuất Markdown"),
      ids.length >= 2 ? h("button", { type: "button", class: "rs-btn", onClick: () => { S.split = true; S.active = ids[0]; S.second = ids[1]; for (const id of ids.slice(0, 2)) if (!S.tabs.includes(id)) S.tabs.push(id); S.focused = 0; saveSession(); renderAll(); syncUrl(); } }, "Mở 2 paper đầu cạnh nhau") : null));
    return { el: body };
  }

  function exportCompare(ids) {
    const lines = [`# So sánh ${ids.length} paper`, ""];
    for (const [label, , pick] of CMP_ROWS) {
      lines.push(`## ${label}`, "");
      for (const id of ids) {
        const p = paperById(id);
        const d = S.details.get(id);
        lines.push(`- **${shortOf(p)}** — ${d && d.data && d.data.summary ? (pick(d.data.summary) || "—") : "(chưa có tóm tắt)"}`);
      }
      lines.push("");
    }
    downloadBlob(new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" }), "so-sanh.md");
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = h("a", { href: url, download: filename, style: "display:none" });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  /* ══════════════════════════════════════════════════════════════
     PANEL: Highlight & ghi chú
     ══════════════════════════════════════════════════════════════ */
  async function deleteAnnotation(paperId, anno) {
    const ok = await confirmDialog({ title: "Xoá highlight?", body: `«${(anno.quote || "").slice(0, 80)}…» sẽ bị xoá cùng ghi chú của nó.`, confirmLabel: "Xoá", signal: V ? V.ctx.signal : undefined });
    if (!ok) return;
    try {
      await Shell.api(`/research/annotations/${enc(anno.id)}`, { method: "DELETE" });
      const d = detailOf(paperId);
      if (d.data) d.data.annotations = (d.data.annotations || []).filter((a) => a.id !== anno.id);
      const row = paperById(paperId);
      if (row) row.annotation_count = (annotationsOf(paperId) || []).length;
      repaintPaper(paperId);
      renderAll();
    } catch (error) {
      toast(say(error, "Không xoá được highlight."), "danger");
    }
  }

  async function saveAnnotationNote(paperId, anno, note) {
    try {
      const res = await Shell.api(`/research/annotations/${enc(anno.id)}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ note }) });
      Object.assign(anno, res && res.id ? res : { note });
      repaintPaper(paperId);
      return true;
    } catch (error) {
      toast(say(error, "Không lưu được ghi chú."), "danger");
      return false;
    }
  }

  function mentionsOf(text) {
    const out = [];
    for (const m of String(text || "").matchAll(/@([\p{L}\p{N}_.-]+)/gu)) {
      const key = fold(m[1]);
      const p = papers().find((x) => fold(x.short_name) === key || fold(x.short_name).replace(/[\s-]/g, "") === key.replace(/[\s-]/g, ""));
      if (p && !out.includes(p)) out.push(p);
    }
    return out;
  }

  function buildNotesPanel(cp) {
    const d = detailOf(cp.id);
    const body = h("div", { class: "rs-panel-body" });
    if (!d.data) {
      if (d.error) body.append(errorState(d.error, () => ensureDetail(cp.id, { force: true })));
      else { ensureDetail(cp.id); body.append(skeleton({ w: "80%", h: 24, r: 12 }), skeleton({ w: "100%", h: 70, r: 10 }), skeleton({ w: "100%", h: 70, r: 10 })); }
      return { el: body };
    }
    const all = d.data.annotations || [];
    const filters = [{ id: "all", label: `Tất cả · ${all.length}` }, { id: "noted", label: "Có ghi chú" }, ...HL.map((c) => ({ id: c.color, label: c.name, swatch: c.color }))];
    const chips = h("div", { class: "rs-chips" }, ...filters.map((f) => h("button", {
      type: "button", class: ["rs-chip", S.noteFilter === f.id && "is-on"], onClick: () => { S.noteFilter = f.id; renderPanel(); },
    }, f.swatch ? h("i", { style: { background: f.swatch } }) : null, f.label)));
    const shown = all.filter((a) => S.noteFilter === "all" || (S.noteFilter === "noted" ? Boolean(a.note) : (a.color || "").toLowerCase() === S.noteFilter));
    const sorted = [...shown].sort((a, b) => (a.page - b.page) || ((a.rects && a.rects[0] ? a.rects[0].y : 0) - (b.rects && b.rects[0] ? b.rects[0].y : 0)));
    const cards = sorted.map((a) => {
      const editing = S.focusAnno === a.id;
      const quote = h("span", { class: "rs-anno-quote" }, `«${(a.quote || "").slice(0, 220)}${(a.quote || "").length > 220 ? "…" : ""}»`);
      let noteEl = null;
      if (editing) {
        const ta = h("textarea", { placeholder: "Ghi chú cho đoạn này…", "aria-label": "Ghi chú" });
        ta.value = a.note || "";
        const finish = async () => {
          const value = ta.value.trim();
          if (value !== (a.note || "")) await saveAnnotationNote(cp.id, a, value);
          if (S.focusAnno === a.id) S.focusAnno = null;
          renderPanel();
        };
        ta.addEventListener("blur", finish);
        ta.addEventListener("keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); ta.blur(); } if (event.key === "Escape") { ta.value = a.note || ""; ta.blur(); } });
        ta.addEventListener("click", (event) => event.stopPropagation());
        ta.addEventListener("mousedown", (event) => event.stopPropagation());
        noteEl = ta;
        requestAnimationFrame(() => ta.focus());
      } else if (a.note) noteEl = h("span", { class: "rs-anno-note" }, a.note);
      const card = h("div", {
        class: "rs-anno", style: { borderLeftColor: a.color || S.hl }, role: "button", tabindex: "0",
        onClick: () => { const pane = V && V.panes.get(cp.id); if (pane) goPage(pane, Number(a.page) || 1); },
        onKeydown: (event) => { if (event.key === "Enter" && event.target === card) { const pane = V && V.panes.get(cp.id); if (pane) goPage(pane, Number(a.page) || 1); } },
      }, quote, noteEl,
      h("span", { class: "rs-anno-meta" }, `tr. ${a.page}${a.section ? ` · ${a.section}` : ""}`, h("span", { class: "spacer" }),
        h("span", { class: "rs-anno-act" },
          h("button", { type: "button", class: "rs-ibtn", title: a.note ? "Sửa ghi chú" : "Thêm ghi chú", onClick: (event) => { event.stopPropagation(); S.focusAnno = a.id; renderPanel(); } }, icon("pen", { size: 12 })),
          h("button", { type: "button", class: "rs-ibtn", title: "Xoá highlight", onClick: (event) => { event.stopPropagation(); deleteAnnotation(cp.id, a); } }, icon("trash", { size: 12 })))));
      return card;
    });
    const noteArea = h("textarea", { class: "rs-note", rows: "5", placeholder: "Markdown… gõ @Tên để gắn paper khác", "aria-label": "Ghi chú tự do" });
    noteArea.value = d.data.note_md || "";
    const state = h("div", { class: "rs-note-state" }, d.noteState || "");
    const mentions = h("div", { class: "rs-mentions", hidden: true });
    const renderMentions = () => {
      const ms = mentionsOf(noteArea.value);
      mentions.hidden = !ms.length;
      mentions.replaceChildren("Gắn với:", ...ms.map((p) => h("button", { type: "button", class: "rs-mention", onClick: () => openPaper(p.id) }, `@${shortOf(p)} →`)));
    };
    const save = debounce(async () => {
      const value = noteArea.value;
      if (value === (d.data.note_md || "")) return;
      d.noteState = "Đang lưu…"; state.textContent = d.noteState; state.classList.remove("is-error");
      try {
        await patchPaper(cp.id, { note_md: value });
        d.data.note_md = value;
        d.noteState = `Đã lưu ${fmtClock(new Date(), { seconds: false })}`;
      } catch (error) {
        d.noteState = say(error, "Không lưu được ghi chú.");
        state.classList.add("is-error");
      }
      state.textContent = d.noteState;
    }, NOTE_MS);
    noteArea.addEventListener("input", () => { renderMentions(); save(); });
    noteArea.addEventListener("blur", () => save.flush());
    renderMentions();
    body.append(chips,
      ...(cards.length ? cards : [h("div", { class: "rs-chat-note" }, all.length ? "Không có highlight nào khớp bộ lọc." : "Chưa có highlight. Bôi đen chữ trong trang rồi bấm Highlight.")]),
      h("div", { class: "rs-label", style: { marginTop: "4px" } }, "Ghi chú tự do"), mentions, noteArea, state,
      h("button", { type: "button", class: "rs-btn", style: { alignSelf: "flex-start" }, onClick: (event) => exportNotes(cp, event.currentTarget) }, "Xuất highlight → Markdown"));
    return { el: body };
  }

  async function exportNotes(cp, button) {
    if (button) button.disabled = true;
    try {
      const blob = await Shell.fetchBlob(`/research/papers/${enc(cp.id)}/export.md`);
      downloadBlob(blob, `${(cp.short_name || "paper").replace(/[^\w.-]+/g, "_")}.md`);
    } catch (error) {
      if (routeMissing(error)) toast("Máy chủ chưa hỗ trợ xuất Markdown (GET /research/papers/{id}/export.md).", "danger");
      else toast(say(error, "Không xuất được."), "danger");
    } finally {
      if (button && button.isConnected) button.disabled = false;
    }
  }

  /* ══════════════════════════════════════════════════════════════
     PANEL: Mục lục & hình
     ══════════════════════════════════════════════════════════════ */
  async function ensureOutline(id, { force = false } = {}) {
    const d = detailOf(id);
    if ((d.outline && !force) || d.outlineBusy) return;
    d.outlineBusy = true;
    d.outlineError = null;
    try {
      const data = await Shell.api(`/research/papers/${enc(id)}/outline`, { signal: V ? V.ctx.signal : undefined });
      d.outline = { toc: Array.isArray(data && data.toc) ? data.toc : [], figures: Array.isArray(data && data.figures) ? data.figures : [] };
    } catch (error) {
      if (isAbort(error)) return;
      d.outlineError = error;
    } finally {
      d.outlineBusy = false;
    }
    if (V && S.tool === "outline") renderPanel();
  }

  function buildOutlinePanel(cp) {
    const d = detailOf(cp.id);
    const body = h("div", { class: "rs-panel-body" });
    if (!d.outline) {
      if (d.outlineError) body.append(routeMissing(d.outlineError) ? missingApiState({ feature: "mục lục & hình", endpoint: "GET /research/papers/{id}/outline" }) : errorState(d.outlineError, () => ensureOutline(cp.id, { force: true })));
      else { ensureOutline(cp.id); body.append(...[80, 60, 70, 50, 65].map((w) => skeleton({ w: `${w}%`, h: 12 }))); }
      return { el: body };
    }
    const pane = V && V.panes.get(cp.id);
    const cur = pane ? pane.cur : 1;
    const toc = d.outline.toc;
    let activeAt = -1;
    toc.forEach((t, i) => { if (Number(t.page) <= cur) activeAt = i; });
    const go = (page) => { if (pane) goPage(pane, Number(page) || 1); };
    if (toc.length) {
      body.append(h("div", { class: "rs-toc" }, ...toc.map((t, i) => h("button", {
        type: "button", class: ["rs-toc-item", Number(t.level) > 0 && "is-sub", i === activeAt && "is-active"], onClick: () => go(t.page),
      }, h("span", null, t.title || "—"), h("small", null, t.page ?? "")))));
    } else body.append(h("div", { class: "rs-chat-note" }, "Paper không có mục lục và máy chủ không dò được tiêu đề mục."));
    const figs = d.outline.figures;
    body.append(h("div", { class: "rs-label", style: { marginTop: "8px" } }, "Hình & bảng"));
    if (figs.length) {
      body.append(h("div", { class: "rs-figs" }, ...figs.map((f) => h("button", { type: "button", class: "rs-fig", onClick: () => go(f.page) },
        h("span", { class: "rs-fig-thumb" }), h("span", null, f.label || "Hình"), h("small", null, `tr. ${f.page ?? "?"}`)))));
    } else body.append(h("div", { class: "rs-chat-note" }, "Không thấy nhãn Fig./Table nào ở đầu dòng."));
    return { el: body };
  }

  /* ══════════════════════════════════════════════════════════════
     PANEL: Thông tin & trạng thái
     ══════════════════════════════════════════════════════════════ */
  function editable(value, { placeholder = "—", onSave, type = "text", width } = {}) {
    const text = String(value ?? "").trim();
    const btn = h("button", { type: "button", class: ["rs-edit", !text && "is-empty"], title: "Bấm để sửa", style: width ? { maxWidth: width } : null }, text || placeholder);
    btn.addEventListener("click", () => {
      const input = h("input", { class: "rs-edit-input", type, value: text, "aria-label": "Sửa giá trị" });
      let done = false;
      const finish = async (commit) => {
        if (done) return;
        done = true;
        const next = input.value.trim();
        if (commit && next !== text) {
          try { await onSave(next); } catch (error) { toast(say(error, "Không lưu được."), "danger"); }
        }
        renderPanel();
      };
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") { event.preventDefault(); finish(true); }
        else if (event.key === "Escape") { event.preventDefault(); finish(false); }
      });
      input.addEventListener("blur", () => finish(true));
      btn.replaceWith(input);
      input.focus();
      input.select();
    });
    return btn;
  }

  function bibtex(p) {
    const key = (p.short_name || "paper").replace(/[^A-Za-z0-9]+/g, "") + (p.year || "");
    const lines = [`@article{${key},`, `  title = {${p.title || ""}},`, `  author = {${p.authors || ""}},`];
    if (p.year) lines.push(`  year = {${p.year}},`);
    if (p.venue) lines.push(`  journal = {${p.venue}},`);
    if (p.arxiv_id) lines.push(`  eprint = {${p.arxiv_id}},`, "  archivePrefix = {arXiv},");
    if (p.doi) lines.push(`  doi = {${p.doi}},`);
    if (p.url) lines.push(`  url = {${p.url}},`);
    lines.push("}");
    return lines.join("\n");
  }

  async function downloadSource(p, button) {
    if (button) button.disabled = true;
    try {
      const blob = await Shell.fetchBlob(`/documents/${enc(p.document_id)}/source`);
      downloadBlob(blob, `${(p.short_name || "paper").replace(/[^\w.-]+/g, "_")}.pdf`);
    } catch (error) {
      if (routeMissing(error)) toast("Máy chủ chưa hỗ trợ tải tệp gốc (GET /documents/{id}/source).", "danger");
      else toast(say(error, "Không tải được PDF."), "danger");
    } finally {
      if (button && button.isConnected) button.disabled = false;
    }
  }

  async function removePaper(p) {
    const ok = await confirmDialog({ title: "Gỡ paper khỏi dự án?", body: `«${p.title || shortOf(p)}» sẽ rời dự án cùng highlight và ghi chú của nó. Tài liệu gốc vẫn còn trong mục Tài liệu.`, confirmLabel: "Gỡ", signal: V ? V.ctx.signal : undefined });
    if (!ok) return;
    try {
      await Shell.api(`/research/papers/${enc(p.id)}`, { method: "DELETE" });
      if (S.project) S.project.papers = papers().filter((x) => x.id !== p.id);
      S.details.delete(p.id);
      S.sel2.delete(p.id);
      if (V) destroyPane(p.id);
      pruneTabs();
      toast("Đã gỡ paper khỏi dự án.");
      saveSession();
      renderAll();
      syncUrl();
      loadProject(S.pid, { quiet: true });
    } catch (error) {
      toast(say(error, "Không gỡ được paper."), "danger");
    }
  }

  function buildInfoPanel(cp) {
    const d = detailOf(cp.id);
    ensureDetail(cp.id);
    const sum = d.data && d.data.summary;
    const body = h("div", { class: "rs-panel-body" });
    const save = (key) => async (value) => { await patchPaper(cp.id, { [key]: key === "year" ? (value ? Number(value) : null) : (value || null) }); renderAll(); };
    body.append(h("div", { class: "rs-info-title" }, editable(cp.title, { placeholder: "Tiêu đề", onSave: save("title") })));
    body.append(h("div", { class: "rs-info-meta" }, editable(cp.authors, { placeholder: "Tác giả", onSave: save("authors") })));
    const seg = h("div", { class: "rs-seg" }, ...Object.entries(STATUS).map(([value, st]) => h("button", {
      type: "button", class: cp.status === value && "is-active", onClick: async () => { try { await patchPaper(cp.id, { status: value }); renderAll(); } catch (error) { toast(say(error, "Không đổi được trạng thái."), "danger"); } },
    }, st.label)));
    const stars = h("div", { class: "rs-stars", role: "radiogroup", "aria-label": "Đánh giá sao" }, ...[1, 2, 3, 4, 5].map((n) => h("button", {
      type: "button", class: n <= (Number(cp.stars) || 0) && "is-on", title: `${n} sao`, "aria-label": `${n} sao`,
      onClick: async () => { try { await patchPaper(cp.id, { stars: n === Number(cp.stars) ? 0 : n }); renderAll(); } catch (error) { toast(say(error, "Không lưu được sao."), "danger"); } },
    }, icon("star", { size: 15 }))));
    body.append(h("div", { class: "rs-info-row" }, seg, stars));
    const clusterSel = h("select", { "aria-label": "Cụm" }, h("option", { value: "" }, "Chưa xếp cụm"), ...clusters().map((c) => h("option", { value: c.id }, c.name)));
    clusterSel.value = cp.cluster_id || "";
    clusterSel.addEventListener("change", async () => { try { await patchPaper(cp.id, { cluster_id: clusterSel.value || null }); renderAll(); } catch (error) { toast(say(error, "Không đổi được cụm."), "danger"); renderPanel(); } });
    const stage = stageInfo(cp);
    const grid = h("div", { class: "rs-grid" },
      h("span", null, "Tên ngắn"), editable(cp.short_name, { placeholder: "Tên ngắn", onSave: save("short_name") }),
      h("span", null, "Cụm"), h("span", null, h("i", { class: "rs-dot", style: { background: colorOf(cp) } }), clusterSel),
      h("span", null, "Hội nghị"), editable(cp.venue, { placeholder: "Venue", onSave: save("venue") }),
      h("span", null, "Năm"), editable(cp.year, { placeholder: "Năm", onSave: save("year"), type: "number" }),
      h("span", null, "Đầu vào"), h("span", null, (sum && sum.input) || "—"),
      h("span", null, "Tính toán"), h("span", null, (sum && sum.compute) || "—"),
      h("span", null, "Dataset"), h("span", null, (sum && sum.datasets) || "—"),
      h("span", null, "Code"), h("span", { class: sum && sum.code && !/không|no\b/i.test(sum.code) && "is-ok" }, (sum && sum.code) || "—"),
      h("span", null, "arXiv"), editable(cp.arxiv_id, { placeholder: "arXiv id", onSave: save("arxiv_id") }),
      h("span", null, "Trang"), h("span", null, totalPages(cp) ? `${cp.last_page || 1} / ${totalPages(cp)}` : "—"),
      h("span", null, "Thêm"), h("span", null, cp.added_at ? fmtDate(cp.added_at) : "—"));
    body.append(grid);
    body.append(h("div", { class: "rs-info-stage" },
      ...["ocr", "metadata", "outline", "summary"].map((k) => { const v = cp.stages && cp.stages[k]; return h("span", { class: v === "running" || v === "pending" ? "is-run" : v === "failed" ? "is-fail" : null }, h("b", null, STAGE_LABEL[k]), ` ${v === "done" ? "xong" : v === "failed" ? "lỗi" : v === "running" ? "đang chạy" : v === "pending" ? "chờ" : "—"}`); }),
      stage.failed ? h("span", { class: "is-fail" }, stage.text) : null));
    const tags = Array.isArray(cp.tags) ? cp.tags : [];
    const setTags = async (next) => { try { await patchPaper(cp.id, { tags: next }); renderAll(); } catch (error) { toast(say(error, "Không lưu được tag."), "danger"); } };
    body.append(h("div", null, h("div", { class: "rs-label rs-sub" }, "Tag"), h("div", { class: "rs-tags" },
      ...tags.map((t) => h("span", { class: "rs-tag" }, t, h("button", { type: "button", title: "Bỏ tag", "aria-label": `Bỏ tag ${t}`, onClick: () => setTags(tags.filter((x) => x !== t)) }, icon("x", { size: 9, sw: 2.6 })))),
      h("button", {
        type: "button", class: "rs-tag-add", onClick: async () => {
          const value = await dialog({ icon: "tag", title: "Thêm tag", input: { placeholder: "vd. 3DGS, SLAM" }, confirmLabel: "Thêm", signal: V ? V.ctx.signal : undefined });
          if (!value) return;
          const add = value.split(/[,;]/).map((x) => x.trim()).filter(Boolean);
          const merged = [...tags];
          for (const t of add) if (!merged.some((x) => x.toLocaleLowerCase("vi") === t.toLocaleLowerCase("vi"))) merged.push(t);
          setTags(merged);
        },
      }, "+ tag"))));
    body.append(h("div", { class: "rs-row-btns", style: { marginTop: "4px" } },
      h("button", { type: "button", class: "rs-btn", onClick: () => copyText(bibtex(cp)) }, "Sao chép BibTeX"),
      h("button", { type: "button", class: "rs-btn", onClick: (event) => downloadSource(cp, event.currentTarget) }, "Tải PDF"),
      h("button", { type: "button", class: "rs-btn is-danger", onClick: () => removePaper(cp) }, "Gỡ khỏi dự án")));
    return { el: body };
  }

  /* ══════════════════════════════════════════════════════════════
     PANEL + RAIL — khung chung
     ══════════════════════════════════════════════════════════════ */
  function renderPanel() {
    if (!V) return;
    const cp = currentPaper();
    const reading = S.active !== "overview";
    const show = reading && Boolean(S.tool) && !S.focusMode ? Boolean(cp) : false;
    V.panel.hidden = !show;
    if (!show) { V.panelKey = null; V.panelRefresh = null; V.panelBody.replaceChildren(); return; }
    const tool = TOOLS.find((t) => t.id === S.tool);
    V.panelTitle.textContent = tool.label;
    V.panelOf.hidden = !S.split;
    if (S.split) V.panelOf.replaceChildren("theo ô: ", h("strong", null, shortOf(cp)));
    const key = `${S.tool}:${cp.id}:${S.pid}`;
    if (V.panelKey === key && V.panelRefresh) { V.panelRefresh(); return; }
    const built = S.tool === "project" ? buildChatPanel("project", cp)
      : S.tool === "chat" ? buildChatPanel("paper", cp)
        : S.tool === "summary" ? buildSummaryPanel(cp)
          : S.tool === "compare" ? buildComparePanel(cp)
            : S.tool === "notes" ? buildNotesPanel(cp)
              : S.tool === "outline" ? buildOutlinePanel(cp)
                : buildInfoPanel(cp);
    V.panelKey = key;
    V.panelRefresh = built.refresh || null;
    V.panelBody.replaceWith(built.el);
    V.panelBody = built.el;
  }

  function renderRail() {
    if (!V) return;
    const reading = S.active !== "overview";
    V.rail.hidden = !reading;
    if (!reading) return;
    const cp = currentPaper();
    for (const t of TOOLS) {
      const btn = V.tools.get(t.id);
      btn.classList.toggle("is-active", S.tool === t.id);
      const badge = t.id === "compare" ? S.sel2.size : t.id === "notes" && cp ? annoCount(cp) : 0;
      btn.badge.textContent = badge ? String(badge) : "";
      btn.badge.hidden = !badge;
    }
  }

  /* ══════════════════════════════════════════════════════════════
     TỔNG QUAN
     ══════════════════════════════════════════════════════════════ */
  async function generateInsights() {
    if (S.insightsBusy || !S.pid) return;
    S.insightsBusy = true;
    S.insightsError = null;
    renderBody();
    try {
      const res = await Shell.api(`/research/projects/${enc(S.pid)}/insights`, { method: "POST", headers: JSON_HEADERS, body: "{}", signal: V ? V.ctx.signal : undefined });
      if (S.project) { S.project.insights = (res && (res.insights || res)) || null; S.project.insights_at = (res && res.insights_at) || new Date().toISOString(); }
    } catch (error) {
      if (isAbort(error)) return;
      S.insightsError = error;
    } finally {
      S.insightsBusy = false;
    }
    renderBody();
  }

  /* Đoạn văn có **đậm** và *nghiêng* → nodes (không HTML thô). */
  function richText(text) {
    const out = [];
    for (const part of String(text || "").split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g)) {
      if (!part) continue;
      if (part.startsWith("**") && part.endsWith("**")) out.push(h("strong", null, part.slice(2, -2)));
      else if (part.startsWith("*") && part.endsWith("*") && part.length > 2) out.push(h("em", null, part.slice(1, -1)));
      else out.push(document.createTextNode(part));
    }
    return out;
  }

  function buildOverview() {
    const proj = S.project;
    const rows = papers();
    const readCount = rows.filter((p) => p.status === "read").length;
    const hlCount = rows.reduce((n, p) => n + annoCount(p), 0);
    const meta = [`${rows.length} paper`, `${clusters().length} cụm`, `${readCount} đã đọc`, `${hlCount} highlight`, proj.updated_at ? `cập nhật ${fmtRelative(proj.updated_at)}` : null].filter(Boolean).join(" · ");
    const askBtn = h("button", { type: "button", class: "rs-btn rs-ov-ask", onClick: () => openProjectChat() }, icon("project", { size: 14 }), "Hỏi cả dự án");

    // AI đọc gì từ kho này
    const ins = proj.insights && typeof proj.insights === "object" ? proj.insights : null;
    const hasSummary = rows.some((p) => p.has_summary);
    let insightsEl;
    if (ins && (ins.overview || ins.central || ins.trend || ins.gap)) {
      insightsEl = h("section", { class: "rs-card rs-insights" },
        h("div", null, h("div", { class: "rs-insights-label" }, "AI đọc gì từ kho này"), h("p", null, ...richText(ins.overview || ""))),
        h("div", { class: "rs-insights-side" },
          ...[["Paper trung tâm:", ins.central, "var(--accent)"], ["Xu hướng:", ins.trend, "var(--c4)"], ["Khoảng trống:", ins.gap, "var(--c5)"]].filter(([, v]) => v).map(([k, v, color]) =>
            h("div", { class: "rs-insight" }, h("span", { class: "rs-dot", style: { background: color } }), h("span", null, h("strong", null, k), " ", ...richText(v))))),
        h("div", { class: "rs-insights-foot" }, proj.insights_at ? `phân tích ${fmtRelative(proj.insights_at)}` : "", h("button", { type: "button", class: "btn-link", disabled: S.insightsBusy, onClick: generateInsights }, S.insightsBusy ? "Đang phân tích lại…" : "Phân tích lại")));
    } else {
      let inner;
      if (S.insightsBusy) inner = h("div", { class: "rs-insights-empty" }, h("span", null, h("div", { class: "rs-sum-wait-text" }, icon("spark", { size: 14 }), "AI đang đọc tóm tắt của các paper trong kho… (30–120 giây)")), skeleton({ w: 180, h: 12 }));
      else if (S.insightsError) {
        const missing = routeMissing(S.insightsError);
        inner = h("div", { class: "rs-insights-empty" }, h("span", { style: missing ? null : { color: "var(--danger)" } }, missing ? "Máy chủ chưa hỗ trợ phân tích kho (POST /research/projects/{id}/insights)." : say(S.insightsError, "Không phân tích được.")),
          missing ? null : h("button", { type: "button", class: "rs-btn", onClick: generateInsights }, icon("retry", { size: 13 }), "Thử lại"));
      } else if (!rows.length) inner = h("div", { class: "rs-insights-empty" }, h("span", null, "Thêm paper vào kho rồi AI sẽ đọc tóm tắt của chúng để rút ra dòng chính, paper trung tâm, xu hướng và khoảng trống."));
      else if (!hasSummary) inner = h("div", { class: "rs-insights-empty" }, h("span", null, "Chưa paper nào có tóm tắt AI, nên chưa có gì để phân tích. Mở một paper → Tóm tắt AI (tạo một lần, lưu lại), rồi quay lại đây."), h("button", { type: "button", class: "rs-btn", disabled: true }, icon("spark", { size: 13 }), "Phân tích kho"));
      else inner = h("div", { class: "rs-insights-empty" }, h("span", null, `AI sẽ đọc tóm tắt của ${rows.filter((p) => p.has_summary).length}/${rows.length} paper để rút ra dòng chính, paper trung tâm, xu hướng và khoảng trống.`), h("button", { type: "button", class: "rs-btn is-primary", onClick: generateInsights }, icon("spark", { size: 13 }), "Phân tích kho"));
      insightsEl = h("section", { class: "rs-card rs-insights" }, h("div", { style: { gridColumn: "1 / -1" } }, h("div", { class: "rs-insights-label" }, "AI đọc gì từ kho này")), inner);
    }

    // Tiếp tục đọc
    const reading = rows.filter((p) => p.status === "reading").sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || ""))).slice(0, 3);
    const resume = h("div", null, h("div", { class: "rs-sec-head" }, h("h2", null, "Tiếp tục đọc"), h("span", null, "chỗ bạn dừng lại")),
      reading.length ? h("div", { class: "rs-resume" }, ...reading.map((p) => {
        const total = totalPages(p);
        const pct = total ? Math.round(((Number(p.last_page) || 1) / total) * 100) : 0;
        return h("button", { type: "button", class: "rs-resume-card", onClick: () => openPaper(p.id, { page: p.last_page || 1 }) },
          h("span", { class: "rs-resume-name" }, h("i", { class: "rs-dot", style: { background: colorOf(p) } }), shortOf(p)),
          h("span", { class: "rs-resume-where" }, total ? `tr. ${p.last_page || 1} / ${total}` : "chưa đọc trang nào", venueText(p) ? ` · ${venueText(p)}` : ""),
          h("span", { class: "rs-resume-bar" }, h("span", { style: { width: `${pct}%`, background: colorOf(p) } })));
      })) : h("div", { class: "rs-chat-note" }, "Chưa có paper nào ở trạng thái Đang đọc — đổi trạng thái trong Thông tin & trạng thái của paper."));

    // Cụm chủ đề
    const groups = [...clusters()].sort((a, b) => (a.position ?? 0) - (b.position ?? 0)).map((c) => ({ cluster: c, items: rows.filter((p) => p.cluster_id === c.id) }));
    const loose = rows.filter((p) => !p.cluster_id || !clusterById(p.cluster_id));
    if (loose.length) groups.push({ cluster: null, items: loose });
    const clusterCards = groups.map(({ cluster, items }) => {
      const ys = items.map((p) => Number(p.year)).filter((y) => Number.isFinite(y) && y > 0);
      const span = ys.length ? (Math.min(...ys) === Math.max(...ys) ? String(ys[0]) : `${Math.min(...ys)}–${Math.max(...ys)}`) : "";
      return h("section", { class: "rs-card rs-cluster" },
        h("div", { class: "rs-cluster-head" }, h("i", { class: "rs-dot", style: { background: cluster ? clusterColor(cluster) : "var(--text-3)" } }),
          h("strong", null, cluster ? cluster.name : "Chưa xếp cụm"), h("small", null, [items.length, span].filter(Boolean).join(" · ")),
          cluster ? h("button", { type: "button", class: "rs-ibtn", title: "Đổi tên / màu / xoá cụm", "aria-label": `Tuỳ chọn cụm ${cluster.name}`, onClick: (event) => clusterMenu(cluster, event.currentTarget) }, icon("dots", { size: 14, sw: 2.6 })) : null),
        h("div", { class: "rs-cluster-body" }, items.length ? items.map((p) => h("button", { type: "button", class: "rs-cluster-paper", onClick: () => openPaper(p.id) },
          h("span", { class: "rs-dot", style: { background: statusOf(p).color } }), h("span", null, shortOf(p)), h("small", null, p.year || ""))) : h("div", { class: "rs-cluster-empty" }, "Chưa có paper — gán trong Thông tin & trạng thái.")));
    });
    const clustersEl = h("div", null, h("div", { class: "rs-sec-head" }, h("h2", null, "Cụm chủ đề"), h("span", null, "bấm paper để mở tab · cụm do bạn gán tay (AI chưa tự gộp)"),
      h("button", { type: "button", class: "rs-btn", onClick: () => editCluster(null) }, icon("plus", { size: 13 }), "Cụm")),
      groups.length ? h("div", { class: "rs-clusters" }, ...clusterCards) : emptyState({ icon: "folder", title: "Chưa có cụm nào", text: "AI chưa tự gộp cụm — tạo cụm rồi gán paper trong Thông tin & trạng thái.", action: { label: "Tạo cụm", icon: "plus", onClick: () => editCluster(null) } }));

    // Kết nối
    const edgeRows = edges().map((e) => {
      const a = paperById(e.a_paper_id);
      const b = paperById(e.b_paper_id);
      if (!a || !b) return null;
      const t = EDGE[e.type] || EDGE.builds;
      const open = S.openEdge === e.id;
      return h("div", { class: ["rs-edge", open && "is-open"] },
        h("button", { type: "button", class: "rs-edge-row", "aria-expanded": open, onClick: () => { S.openEdge = open ? null : e.id; renderBody(); } },
          h("span", { class: "rs-edge-node" }, h("i", { class: "rs-dot", style: { background: colorOf(a) } }), h("span", null, shortOf(a))),
          edgeLine(t, 34, 10),
          h("span", { class: "rs-edge-node" }, h("i", { class: "rs-dot", style: { background: colorOf(b) } }), h("span", null, shortOf(b))),
          h("span", { class: "spacer" }), h("span", { class: "rs-edge-type", style: { color: t.color } }, t.label), icon("chevron-down", { size: 14 })),
        open ? h("div", { class: "rs-edge-body" }, h("span", { class: "rs-edge-ai", style: e.source === "ai" ? null : { background: "var(--surface-3)" }, title: e.source === "ai" ? "AI gán" : "Gán tay" }),
          h("div", { class: "rs-edge-text" }, e.explain || `${shortOf(b)} ${e.type === "builds" ? "xây trên" : e.type === "competes" ? "giải cùng bài toán với" : "dùng chung phương pháp lõi với"} ${shortOf(a)}. (${e.source === "ai" ? "AI gán" : "gán tay, chưa có giải thích"})`,
            e.quote ? h("div", { class: "rs-edge-quote" }, `«${e.quote}»`, h("div", { class: "rs-edge-src" }, e.quote_src || "", " · ", h("button", { type: "button", class: "btn-link", onClick: () => openPaper(b.id, { page: pageFromSrc(e.quote_src), tool: "summary" }) }, "mở đúng trang →"))) : null,
            h("div", { style: { marginTop: "8px", display: "flex", gap: "6px" } },
              h("button", { type: "button", class: "rs-btn", style: { height: "24px", fontSize: "11px", padding: "0 8px" }, onClick: () => openPaper(b.id, { tool: "summary" }) }, `Mở ${shortOf(b)}`),
              h("button", { type: "button", class: "rs-btn is-danger", onClick: () => deleteEdge(e) }, icon("trash", { size: 12 }), "Xoá kết nối")))) : null);
    }).filter(Boolean);
    const edgesEl = h("div", null, h("div", { class: "rs-sec-head" }, h("h2", null, "Kết nối giữa các paper"), h("span", null, "bấm để đọc giải thích · AI chưa tự gán nhãn, thêm tay"),
      h("button", { type: "button", class: "rs-btn", disabled: rows.length < 2, onClick: addEdge }, icon("plus", { size: 13 }), "Kết nối")),
      edgeRows.length ? h("section", { class: "rs-card rs-edges" }, ...edgeRows) : emptyState({ icon: "activity", title: "Chưa có kết nối nào", text: "AI chưa tự gán quan hệ giữa các paper (chờ chốt) — thêm tay: A → B, loại Xây trên / Cùng bài toán / Chung backbone.", action: rows.length >= 2 ? { label: "Thêm kết nối", icon: "plus", onClick: addEdge } : null }));

    return h("div", { class: "rs-ov-inner" },
      h("div", { class: "rs-ov-head" }, h("div", null, h("h1", null, proj.name || "Dự án"), h("p", null, proj.description ? `${proj.description} · ${meta}` : meta)), askBtn),
      insightsEl, resume, clustersEl, edgesEl);
  }
  const pageFromSrc = (src) => { const m = /tr\.?\s*(\d+)/i.exec(String(src || "")); return m ? Number(m[1]) : null; };

  function openProjectChat() {
    if (!papers().length) { toast("Thêm paper vào dự án trước.", "danger"); return; }
    const first = S.tabs[0] || (papers().find((p) => p.indexed) || papers()[0]).id;
    openPaper(first, { tool: "project" });
  }

  /* ── cụm: tạo / đổi tên / màu / xoá ──────────────────────────── */
  async function editCluster(cluster) {
    const result = await dialog({
      icon: "folder", title: cluster ? "Sửa cụm" : "Tạo cụm chủ đề", body: cluster ? null : "Cụm do bạn đặt tay; AI chưa tự gộp (chờ chốt).",
      fields: [
        { name: "name", label: "Tên cụm", value: cluster ? cluster.name : "", placeholder: "vd. GS-SLAM RGB-D", required: true, maxlength: 80 },
        { name: "color_index", label: "Màu", type: "select", value: cluster ? String(cluster.color_index || 1) : String((clusters().length % 5) + 1), options: [1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: `Màu ${n}` })) },
      ],
      confirmLabel: cluster ? "Lưu" : "Tạo", signal: V ? V.ctx.signal : undefined,
      validate: async (values) => {
        const body = { name: values.name, color_index: Number(values.color_index) || 1 };
        try {
          if (cluster) {
            const res = await Shell.api(`/research/clusters/${enc(cluster.id)}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body) });
            Object.assign(cluster, res && res.id ? res : body);
          } else {
            const res = await Shell.api(`/research/projects/${enc(S.pid)}/clusters`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
            if (S.project) S.project.clusters = [...clusters(), res && res.id ? res : { id: `tmp-${Date.now()}`, position: clusters().length, ...body }];
          }
          return null;
        } catch (error) {
          return routeMissing(error) ? "Máy chủ chưa hỗ trợ cụm (POST /research/projects/{id}/clusters)." : say(error, "Không lưu được cụm.");
        }
      },
    });
    if (result) { renderAll(); loadProject(S.pid, { quiet: true }); }
  }

  function clusterMenu(cluster, anchor) {
    dropdown(anchor, [
      { label: "Đổi tên / màu", icon: "pen", onSelect: () => editCluster(cluster) },
      { separator: true },
      { label: "Xoá cụm", icon: "trash", tone: "danger", onSelect: async () => {
        const n = papers().filter((p) => p.cluster_id === cluster.id).length;
        const ok = await confirmDialog({ title: "Xoá cụm?", body: `«${cluster.name}» sẽ bị xoá${n ? `; ${n} paper trong cụm chuyển về "Chưa xếp cụm"` : ""}. Paper không bị gỡ.`, confirmLabel: "Xoá", signal: V ? V.ctx.signal : undefined });
        if (!ok) return;
        try {
          await Shell.api(`/research/clusters/${enc(cluster.id)}`, { method: "DELETE" });
          if (S.project) { S.project.clusters = clusters().filter((c) => c.id !== cluster.id); for (const p of papers()) if (p.cluster_id === cluster.id) p.cluster_id = null; }
          renderAll();
          loadProject(S.pid, { quiet: true });
        } catch (error) { toast(say(error, "Không xoá được cụm."), "danger"); }
      } },
    ], { align: "end", width: 190 });
  }

  /* ── kết nối: thêm / xoá ─────────────────────────────────────── */
  async function addEdge() {
    const opts = papers().map((p) => ({ value: p.id, label: shortOf(p) }));
    if (opts.length < 2) return;
    const cp = currentPaper();
    const result = await dialog({
      icon: "activity", title: "Thêm kết nối giữa hai paper", body: "A → B: B xây trên A · cùng bài toán · chung backbone. Nhãn do bạn gán; AI chưa tự gán (chờ chốt).",
      fields: [
        { name: "a", label: "Paper A", type: "select", value: cp ? cp.id : opts[0].value, options: opts },
        { name: "b", label: "Paper B", type: "select", value: (opts.find((o) => o.value !== (cp ? cp.id : opts[0].value)) || opts[1]).value, options: opts },
        { name: "type", label: "Loại", type: "select", value: "builds", options: Object.entries(EDGE).map(([value, t]) => ({ value, label: t.label })) },
        { name: "explain", label: "Giải thích (tuỳ chọn)", placeholder: "B lấy gì từ A / khác nhau ở đâu", maxlength: 500 },
      ],
      confirmLabel: "Thêm", signal: V ? V.ctx.signal : undefined,
      validate: async (values) => {
        if (values.a === values.b) return "Chọn hai paper khác nhau.";
        try {
          const res = await Shell.api(`/research/projects/${enc(S.pid)}/edges`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ a_paper_id: values.a, b_paper_id: values.b, type: values.type, explain: values.explain || undefined }) });
          if (S.project) S.project.edges = [...edges(), res && res.id ? res : { id: `tmp-${Date.now()}`, a_paper_id: values.a, b_paper_id: values.b, type: values.type, explain: values.explain, source: "manual" }];
          return null;
        } catch (error) {
          return routeMissing(error) ? "Máy chủ chưa hỗ trợ kết nối (POST /research/projects/{id}/edges)." : say(error, "Không thêm được kết nối.");
        }
      },
    });
    if (result) { renderAll(); loadProject(S.pid, { quiet: true }); }
  }

  async function deleteEdge(e) {
    const ok = await confirmDialog({ title: "Xoá kết nối?", body: "Chỉ xoá nhãn quan hệ, không đụng tới paper.", confirmLabel: "Xoá", signal: V ? V.ctx.signal : undefined });
    if (!ok) return;
    try {
      await Shell.api(`/research/edges/${enc(e.id)}`, { method: "DELETE" });
      if (S.project) S.project.edges = edges().filter((x) => x.id !== e.id);
      S.openEdge = null;
      renderAll();
    } catch (error) { toast(say(error, "Không xoá được kết nối."), "danger"); }
  }

  /* ══════════════════════════════════════════════════════════════
     DỰ ÁN: chọn / tạo / đổi tên / xoá — và THÊM PAPER
     ══════════════════════════════════════════════════════════════ */
  function switchProject(pid, { navigate = true } = {}) {
    if (!pid) return;
    if (S.pid === pid && S.project) return;
    if (V) for (const id of [...V.panes.keys()]) destroyPane(id);
    S.pid = pid;
    S.project = null;
    S.projError = null;
    S.insightsError = null;
    S.search = "";
    S.filter = "all";
    loadSession(pid);
    saveSession();
    if (V && V.search) V.search.value = "";
    if (navigate) {
      const hash = S.active === "overview" ? projHash(pid) : paperHash(pid, S.active);
      if (location.hash !== hash) Router.replace(hash, { silent: true });
    }
    loadProject(pid);
  }

  async function createProjectDialog() {
    const name = await dialog({ icon: "folder-plus", title: "Tạo dự án nghiên cứu", input: { placeholder: "vd. 3DGS / 2DGS cho SLAM", maxlength: 120 }, confirmLabel: "Tạo", signal: V ? V.ctx.signal : undefined,
      validate: async (value) => { try { await createProject(value); return null; } catch (error) { return routeMissing(error) ? "Máy chủ chưa hỗ trợ Không gian Nghiên cứu (POST /research/projects)." : say(error, "Không tạo được dự án."); } } });
    return Boolean(name);
  }

  async function createProject(name) {
    const row = await Shell.api("/research/projects", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ name }) });
    S.projects = [row, ...(S.projects || []).filter((p) => p.id !== row.id)];
    switchProject(row.id);
    renderAll();
    return row;
  }

  function projectMenu(anchor) {
    const list = (S.projects || []).map((p) => ({
      label: p.name, icon: p.id === S.pid ? "check" : "folder", hint: `${p.paper_count ?? 0} paper`,
      onSelect: () => { if (p.id !== S.pid) { switchProject(p.id); renderAll(); } },
    }));
    dropdown(anchor, [...list, list.length ? { separator: true } : null,
      { label: "Tạo dự án mới…", icon: "folder-plus", onSelect: () => createProjectDialog() },
      { label: "Đổi tên", icon: "pen", disabled: !S.project, onSelect: renameProject },
      { label: "Xoá dự án", icon: "trash", tone: "danger", disabled: !S.project, onSelect: deleteProject },
    ].filter(Boolean), { align: "start", width: 268, className: "rs-proj-menu" });
  }

  async function renameProject() {
    if (!S.project) return;
    const result = await dialog({ icon: "pen", title: "Đổi tên dự án", fields: [
      { name: "name", label: "Tên", value: S.project.name || "", required: true, maxlength: 120 },
      { name: "description", label: "Mô tả (tuỳ chọn)", value: S.project.description || "", maxlength: 300 },
    ], confirmLabel: "Lưu", signal: V ? V.ctx.signal : undefined,
    validate: async (values) => {
      try {
        const res = await Shell.api(`/research/projects/${enc(S.pid)}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ name: values.name, description: values.description || null }) });
        Object.assign(S.project, res && res.id ? { name: res.name, description: res.description } : { name: values.name, description: values.description });
        const row = (S.projects || []).find((p) => p.id === S.pid);
        if (row) Object.assign(row, { name: S.project.name, description: S.project.description });
        return null;
      } catch (error) { return say(error, "Không đổi tên được."); }
    } });
    if (result) renderAll();
  }

  async function deleteProject() {
    if (!S.project) return;
    const ok = await confirmDialog({ title: "Xoá dự án?", body: `«${S.project.name}» cùng highlight, ghi chú, cụm và kết nối sẽ bị xoá. Các tài liệu PDF vẫn còn trong mục Tài liệu.`, confirmLabel: "Xoá dự án", signal: V ? V.ctx.signal : undefined });
    if (!ok) return;
    try {
      await Shell.api(`/research/projects/${enc(S.pid)}`, { method: "DELETE" });
      const gone = S.pid;
      S.projects = (S.projects || []).filter((p) => p.id !== gone);
      if (V) for (const id of [...V.panes.keys()]) destroyPane(id);
      S.pid = null;
      S.project = null;
      const all = readStoreAll();
      if (all.projects) delete all.projects[gone];
      if (all.lastProject === gone) all.lastProject = null;
      try { localStorage.setItem(STORE_KEY, JSON.stringify(all)); } catch { /* ignore */ }
      toast("Đã xoá dự án.");
      const next = S.projects[0];
      if (next) switchProject(next.id);
      else { Router.replace("#/research", { silent: true }); renderAll(); }
    } catch (error) { toast(say(error, "Không xoá được dự án."), "danger"); }
  }

  /* Thêm paper: dán link/DOI/tiêu đề (máy chủ offline → 501, hiện câu của máy chủ) hoặc thả nhiều PDF
     (POST multipart từng tệp qua Shell.api với FormData — không tự đặt Content-Type). */
  async function addPaperDialog(initialFiles) {
    if (!S.pid) return;
    const link = h("input", { class: "input", placeholder: "Dán link arXiv, DOI hoặc tiêu đề…", "aria-label": "Link, DOI hoặc tiêu đề", autocomplete: "off" });
    const fileInput = h("input", { type: "file", accept: ".pdf,application/pdf", multiple: true });
    const filesEl = h("div", { class: "rs-files" });
    const queue = [];
    const addFiles = (list) => {
      for (const f of [...(list || [])]) {
        if (!/\.pdf$/i.test(f.name) && f.type !== "application/pdf") { toast(`«${f.name}» không phải PDF.`, "danger"); continue; }
        if (queue.some((q) => q.file.name === f.name && q.file.size === f.size)) continue;
        queue.push({ file: f, state: "queued", message: "" });
      }
      renderFiles();
    };
    const renderFiles = () => {
      filesEl.replaceChildren(...queue.map((q) => h("div", { class: ["rs-file", q.state === "uploading" && "is-busy", q.state === "done" && "is-done", q.state === "error" && "is-error"] },
        typeBadge(q.file.name, 24), h("span", { class: "rs-file-name", title: q.file.name }, q.file.name),
        h("span", { class: "rs-file-state" }, q.state === "queued" ? fmtBytes(q.file.size) : q.state === "uploading" ? "đang tải…" : q.state === "done" ? "đã thêm" : q.message || "lỗi"),
        q.state === "queued" ? h("button", { type: "button", class: "rs-ibtn", title: "Bỏ tệp", onClick: () => { queue.splice(queue.indexOf(q), 1); renderFiles(); } }, icon("x", { size: 11 })) : null)));
      filesEl.hidden = !queue.length;
    };
    fileInput.addEventListener("change", () => { addFiles(fileInput.files); fileInput.value = ""; });
    const drop = h("label", { class: "rs-drop" }, h("span", null, h("strong", null, "hoặc thả PDF"), " · nhiều tệp"), h("small", null, "Xử lý nền: OCR → metadata → outline → tóm tắt. Đọc được ngay khi OCR xong."), fileInput);
    drop.addEventListener("dragover", (event) => { event.preventDefault(); drop.classList.add("is-drag"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("is-drag"));
    drop.addEventListener("drop", (event) => { event.preventDefault(); drop.classList.remove("is-drag"); addFiles(event.dataTransfer && event.dataTransfer.files); });
    addFiles(initialFiles);
    const content = h("div", { class: "rs-add-body" }, link, drop, filesEl);
    // dialog() chỉ tự focus ô `input`/`fields`; ô link nằm trong `content` nên tự đưa con trỏ vào.
    requestAnimationFrame(() => { if (link.isConnected) link.focus(); });
    // Enter trong ô link = bấm nút chính của hộp thoại (dialog chỉ nối Enter cho ô input/fields của nó).
    link.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing) return;
      event.preventDefault();
      const ok = link.closest(".dialog")?.querySelector(".dialog-actions .btn-primary");
      if (ok && !ok.disabled) ok.click();
    });
    const result = await dialog({
      icon: "plus", title: "Thêm paper", content, confirmLabel: "Thêm", signal: V ? V.ctx.signal : undefined,
      validate: async () => {
        const text = link.value.trim();
        const pending = queue.filter((q) => q.state !== "done");
        if (!text && !pending.length) return "Dán link hoặc thả ít nhất một tệp PDF.";
        let failures = 0;
        let added = 0;
        if (text) {
          const body = /^https?:\/\//i.test(text) ? { url: text } : /^10\.\d{4,}\//.test(text) ? { doi: text } : { title: text };
          try {
            const rows = await Shell.api(`/research/projects/${enc(S.pid)}/papers`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
            added += Array.isArray(rows) ? rows.length : 1;
            link.value = "";
          } catch (error) {
            if (!pending.length) return routeMissing(error) ? "Máy chủ chưa hỗ trợ thêm paper (POST /research/projects/{id}/papers)." : say(error, "Không thêm được từ link.");
            failures += 1;
            toast(say(error, "Không thêm được từ link."), "danger");
          }
        }
        for (const q of pending) {
          q.state = "uploading"; renderFiles();
          const form = new FormData();
          form.append("files", q.file, q.file.name);
          try {
            await Shell.api(`/research/projects/${enc(S.pid)}/papers`, { method: "POST", body: form });
            q.state = "done"; added += 1;
          } catch (error) {
            q.state = "error"; q.message = routeMissing(error) ? "máy chủ chưa hỗ trợ" : say(error, "lỗi"); failures += 1;
          }
          renderFiles();
        }
        if (added) { loadProject(S.pid, { quiet: true }); loadProjects(); }
        if (failures) return added ? `Đã thêm ${added}; ${failures} mục lỗi (xem dòng đỏ).` : "Không thêm được tệp nào — xem lỗi từng dòng.";
        return null;
      },
    });
    if (result) toast("Đã thêm paper — đang xử lý nền (OCR → metadata → outline → tóm tắt).");
  }

  /* ══════════════════════════════════════════════════════════════
     SIDEBAR + TAB BAR + THÂN — vẽ
     ══════════════════════════════════════════════════════════════ */
  function visiblePapers() {
    const q = fold(S.search.trim());
    return papers().filter((p) => (S.filter === "all" || (p.status || "unread") === S.filter)
      && (!q || fold(p.short_name).includes(q) || fold(p.title).includes(q) || fold(p.authors).includes(q) || fold(p.venue).includes(q)));
  }

  function renderSidebar() {
    if (!V) return;
    const side = V.side;
    side.hidden = S.focusMode;
    const proj = S.project;
    const row = (S.projects || []).find((p) => p.id === S.pid);
    V.projName.textContent = proj ? proj.name : row ? row.name : (S.projBusy ? "Đang tải…" : "Dự án");
    const rows = papers();
    V.projMeta.textContent = proj ? `${rows.length} paper · ${rows.filter((p) => p.status === "read").length} đã đọc` : (row ? `${row.paper_count ?? 0} paper` : "");
    for (const [value, btn] of V.filterBtns) btn.classList.toggle("is-active", S.filter === value);

    const list = V.list;
    list.classList.toggle("has-sel", S.sel2.size > 0);
    if (!proj) {
      list.replaceChildren(S.projError ? errorState(S.projError, () => loadProject(S.pid)) : h("div", { class: "rs-side-skel" }, ...[0, 1, 2, 3, 4, 5].map(() => h("div", { class: "rs-skel-row" }, skeleton({ w: 16, h: 16, r: 4 }), h("div", { style: { flex: 1, display: "flex", flexDirection: "column", gap: "6px" } }, skeleton({ w: "60%", h: 11 }), skeleton({ w: "40%", h: 9 }))))));
    } else {
      const shown = visiblePapers();
      const groups = [...clusters()].sort((a, b) => (a.position ?? 0) - (b.position ?? 0)).map((c) => ({ key: c.id, name: c.name, color: clusterColor(c), items: shown.filter((p) => p.cluster_id === c.id) }));
      const loose = shown.filter((p) => !p.cluster_id || !clusterById(p.cluster_id));
      if (loose.length) groups.push({ key: "__none", name: "Chưa xếp cụm", color: "var(--text-3)", items: loose });
      const nodes = [];
      for (const g of groups) {
        if (!g.items.length) continue;
        const open = !S.collapsed[g.key];
        nodes.push(h("button", { type: "button", class: ["rs-group", open && "is-open"], "aria-expanded": open, onClick: () => { S.collapsed = { ...S.collapsed, [g.key]: open }; saveSession(); renderSidebar(); } },
          icon("chevron-right", { size: 10 }), h("i", { class: "rs-dot", style: { background: g.color } }), g.name, h("span", { class: "n" }, String(g.items.length))));
        if (!open) continue;
        nodes.push(h("div", { class: "rs-group-body" }, ...g.items.map((p) => {
          const active = S.active === p.id || (S.split && secondId() === p.id);
          const selected = S.sel2.has(p.id);
          const st = statusOf(p);
          const stage = stageInfo(p);
          const n = annoCount(p);
          return h("div", { class: "rs-item" },
            h("button", { type: "button", class: ["rs-check", selected && "is-on"], title: "Chọn để so sánh", "aria-pressed": selected, "aria-label": `Chọn ${shortOf(p)} để so sánh`, onClick: (event) => { event.stopPropagation(); if (selected) S.sel2.delete(p.id); else S.sel2.add(p.id); renderAll(); } }, selected ? icon("check", { size: 10, sw: 3 }) : null),
            h("button", { type: "button", class: ["rs-paper", active && "is-active", S.tabs.includes(p.id) && "is-open"], title: p.title || "", onClick: () => openPaper(p.id) },
              h("span", { class: "rs-dot", title: st.label, style: { background: st.color } }),
              h("span", { class: "rs-paper-text" }, h("span", { class: "rs-paper-name" }, shortOf(p)),
                h("span", { class: "rs-paper-sub" }, [venueText(p) || null, n ? `${n} highlight` : null].filter(Boolean).join(" · ") || "—"),
                stage.busy ? h("span", { class: "rs-paper-bar" }, h("span", { style: { width: `${stage.pct}%` } })) : null,
                stage.busy || stage.failed ? h("span", { class: ["rs-paper-stage", stage.failed && "is-failed"] }, stage.text) : null),
              S.tabs.includes(p.id) && !active ? h("span", { class: "rs-paper-open", title: "Đang mở trong tab" }) : null));
        })));
      }
      if (!nodes.length) nodes.push(h("div", { class: "rs-list-empty" }, rows.length ? "Không paper nào khớp bộ lọc." : "Kho trống — bấm Thêm paper để thả PDF vào."));
      list.replaceChildren(...nodes);
    }
    V.selbar.hidden = !S.sel2.size;
    if (S.sel2.size) V.selCount.textContent = `${S.sel2.size} paper đã chọn`;
    const dark = document.documentElement.dataset.theme === "dark";
    V.themeBtn.replaceChildren(icon(dark ? "sun" : "moon", { size: 15, sw: 1.9 }));
    V.themeBtn.title = dark ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối";
  }

  function renderTabs() {
    if (!V) return;
    V.showSideBtn.hidden = !S.focusMode;
    const overview = h("button", { type: "button", class: ["rs-tab", "is-overview", S.active === "overview" && "is-active"], role: "tab", "aria-selected": S.active === "overview", onClick: () => setActive("overview") }, icon("grid", { size: 14 }), h("span", null, "Tổng quan"));
    const tabs = S.tabs.map((id) => {
      const p = paperById(id);
      if (!p) return null;
      const active = S.active === id;
      const tab = h("div", { class: ["rs-tab", active && "is-active"], role: "tab", tabindex: "0", "aria-selected": active, title: p.title || "", onClick: () => setActive(id),
        onKeydown: (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setActive(id); } } },
      icon("file-corner", { size: 13 }), h("span", null, shortOf(p)),
      h("button", { type: "button", class: "rs-tab-x", title: `Đóng (${MOD}+W)`, "aria-label": `Đóng tab ${shortOf(p)}`, onClick: (event) => { event.stopPropagation(); closeTab(id); } }, icon("x", { size: 10 })));
      tab.querySelector(".ico").style.color = colorOf(p);
      return tab;
    }).filter(Boolean);
    V.tabs.replaceChildren(overview, ...tabs);
    V.splitBtn.classList.toggle("is-on", S.split);
    V.splitBtn.setAttribute("aria-pressed", String(S.split));
    V.syncBtn.hidden = !S.split;
    V.syncBtn.classList.toggle("is-on", S.sync);
    V.syncBtn.setAttribute("aria-pressed", String(S.sync));
    V.focusBtn.classList.toggle("is-on", S.focusMode);
    V.focusBtn.setAttribute("aria-pressed", String(S.focusMode));
  }

  function renderBody() {
    if (!V) return;
    const reading = S.active !== "overview" && Boolean(paperById(S.active));
    if (!reading && S.active !== "overview") { S.active = "overview"; }
    V.ov.hidden = reading;
    V.reader.hidden = !reading;
    if (!reading) {
      const top = V.ov.scrollTop;
      V.ov.replaceChildren(S.project ? buildOverview()
        : S.projError ? h("div", { class: "rs-ov-inner" }, errorState(S.projError, () => loadProject(S.pid)))   // dự án đã xoá / id lạ trên URL
          : h("div", { class: "rs-ov-inner" }, skeleton({ w: 320, h: 26, r: 8 }), skeleton({ w: "100%", h: 120, r: 14 }), skeleton({ w: "100%", h: 90, r: 14 })));
      V.ov.scrollTop = top;
    } else renderPanes();
    V.root.classList.toggle("is-focus-mode", S.focusMode);
  }

  function renderPanes() {
    const ids = [S.active, S.split ? secondId() : null].filter(Boolean);
    const all = papers().map((p) => ({ id: p.id, short: shortOf(p) }));
    ids.forEach((id, idx) => {
      let pane = V.panes.get(id);
      if (!pane) { pane = createPane(id); V.panes.set(id, pane); V.reader.append(pane.el); ensureDetail(id); }
      else buildPages(pane);
      pane.idx = idx;
      pane.el.style.order = String(idx);
      if (pane.el.hidden) { pane.el.hidden = false; pane.scroll.scrollTop = pane.savedTop; }
      pane.el.classList.toggle("is-focus", S.split && S.focused === idx);
      pane.el.classList.toggle("no-anno", !S.showAnno);
      pane.name.hidden = S.split;
      pane.select.hidden = !S.split;
      if (S.split) {
        pane.select.replaceChildren(...all.map((o) => h("option", { value: o.id }, o.short)));
        pane.select.value = id;
      }
      pane.close.hidden = !S.split;
      pane.syncBadge.hidden = !(S.split && S.sync);
      const paper = paperById(id);
      pane.syncBadge.textContent = `cuộn đồng bộ · ${pane.cur}/${totalPages(paper) || "?"}`;
      pane.pageLabel.textContent = `${pane.cur} / ${totalPages(paper) || "?"}`;
      pane.hlSwatch.style.background = S.hl;
      for (const sw of pane.swatches) sw.classList.toggle("is-on", sw.dataset.color === S.hl);
      pane.eye.classList.toggle("is-on", S.showAnno);
      pane.eye.title = S.showAnno ? "Ẩn ghi chú bên lề" : "Hiện ghi chú bên lề";
      if (pane.lastPatchPage === null) {
        // lần đầu mở: cuộn tới last_page đã lưu
        const last = Number(paper && paper.last_page) || 1;
        pane.lastPatchPage = last;
        if (last > 1) requestAnimationFrame(() => { goPage(pane, last, { instant: true }); });
      }
      paintAll(pane);
    });
    for (const [id, pane] of V.panes) {
      if (ids.includes(id) || pane.el.hidden) continue;
      pane.savedTop = pane.scroll.scrollTop;
      pane.el.hidden = true;
      hideSelMenu(pane);
    }
  }

  function renderKeys() {
    if (!V) return;
    V.keys.hidden = !S.keysOpen;
  }

  function renderState() {
    if (!V) return;
    const center = V.center;
    const show = (node) => { center.hidden = false; center.replaceChildren(node); V.side.hidden = true; V.main.hidden = true; };
    if (S.projectsMissing) { show(missingApiState({ feature: "Không gian Nghiên cứu", endpoint: "GET /research/projects" })); return false; }
    if (S.projects === null) {
      if (S.projectsError) { show(errorState(S.projectsError, () => { S.projectsError = null; boot(); })); return false; }
      show(h("div", { class: "rs-empty" }, skeleton({ w: 60, h: 60, r: 18 }), skeleton({ w: 240, h: 20 }), skeleton({ w: 300, h: 12 })));
      return false;
    }
    if (!S.pid) {
      const input = h("input", { class: "input", placeholder: "Tên dự án, vd. 3DGS / 2DGS cho SLAM", "aria-label": "Tên dự án", maxlength: 120, required: true });
      const btn = h("button", { type: "submit", class: "btn btn-38 btn-primary btn-glow" }, icon("plus", { size: 14 }), "Tạo dự án");
      const form = h("form", null, input, btn);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const name = input.value.trim();
        if (!name) { input.focus(); return; }
        btn.disabled = true;
        try { await createProject(name); } catch (error) { toast(routeMissing(error) ? "Máy chủ chưa hỗ trợ Không gian Nghiên cứu (POST /research/projects)." : say(error, "Không tạo được dự án."), "danger"); btn.disabled = false; }
      });
      show(h("div", { class: "rs-empty" }, h("span", { class: "logo logo-40" }, icon("book", { size: 20, sw: 1.9 })),
        h("h2", null, S.projects.length ? "Chọn hoặc tạo dự án" : "Tạo dự án nghiên cứu đầu tiên"),
        h("p", null, "Một dự án = một kho paper PDF: AI tóm tắt từng bài, bạn highlight, ghi chú, so sánh và hỏi đáp trên cả kho."),
        S.projects.length ? h("div", { class: "rs-stack", style: { width: "100%" } }, ...S.projects.map((p) => h("button", { type: "button", class: "rs-starter", onClick: () => { switchProject(p.id); renderAll(); } }, icon("folder", { size: 13 }), p.name, h("span", { style: { marginLeft: "auto", color: "var(--text-3)", fontSize: "11.5px" } }, `${p.paper_count ?? 0} paper`)))) : null,
        form, h("a", { href: "#/chat", class: "btn-link" }, "← Về Local AI Core")));
      requestAnimationFrame(() => input.focus({ preventScroll: true }));
      return false;
    }
    center.hidden = true;
    V.main.hidden = false;
    V.side.hidden = S.focusMode;
    return true;
  }

  function renderAll() {
    if (!V) return;
    if (!renderState()) return;
    renderSidebar();
    renderTabs();
    renderBody();
    renderPanel();
    renderRail();
    renderKeys();
    renderDrawer();
    // GET project vừa xong mà URL đang trỏ tới một paper → mở nó (openPaper tự vẽ lại).
    if (S.project && S.pendingOpen) applyPendingOpen();
  }

  /* ══════════════════════════════════════════════════════════════
     PHÍM TẮT
     ══════════════════════════════════════════════════════════════ */
  function onKeydown(event) {
    if (!V || event.defaultPrevented) return;
    if (document.querySelector(".dialog-overlay, #menu-root .menu")) return;
    const mod = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    const inField = /^(input|textarea|select)$/i.test(event.target.tagName) || event.target.isContentEditable;
    const reading = S.active !== "overview" && S.pid && S.project;
    const pane = reading ? V.panes.get(currentPaperId()) : null;
    if (event.key === "Escape") {
      if (S.drawerOpen) { setDrawer(false); event.preventDefault(); return; }
      if (S.keysOpen) { S.keysOpen = false; renderKeys(); event.preventDefault(); return; }
      if (pane && pane.menu) { hideSelMenu(pane); event.preventDefault(); }
      return;
    }
    if (mod && !event.altKey && !event.shiftKey) {
      if (key === "k") { event.preventDefault(); if (S.focusMode) toggleFocusMode(); V.search.focus(); V.search.select(); return; }
      if (key === "\\") { event.preventDefault(); if (S.project) toggleSplit(); return; }
      if (key === ".") { event.preventDefault(); if (reading) toggleFocusMode(); return; }
      if (key === "f" && pane) { event.preventDefault(); askFind(pane); return; }
      if (key === "w" && reading) { event.preventDefault(); closeTab(S.active); return; }
      if (S.pendingSel && (key === "h" || key === "e" || key === "a" || key === "t")) {
        event.preventDefault();
        selAction(key === "h" ? "highlight" : key === "e" ? "note" : key === "a" ? "ask" : "translate");
        return;
      }
      return;
    }
    if (event.ctrlKey && event.key === "Tab" && S.tabs.length) {
      event.preventDefault();
      const order = ["overview", ...S.tabs];
      const at = order.indexOf(S.active);
      setActive(order[(at + (event.shiftKey ? -1 : 1) + order.length) % order.length]);
      return;
    }
    if (!inField && pane && (event.key === "ArrowLeft" || event.key === "ArrowRight") && !mod) {
      event.preventDefault();
      goPage(pane, pane.cur + (event.key === "ArrowRight" ? 1 : -1));
    }
  }

  /* ══════════════════════════════════════════════════════════════
     MOUNT / UPDATE / UNMOUNT
     ══════════════════════════════════════════════════════════════ */
  function buildShell(ctx) {
    const search = h("input", { placeholder: "Tìm paper, tác giả…", "aria-label": "Tìm paper trong kho", autocomplete: "off", spellcheck: "false" });
    search.addEventListener("input", debounce(() => { S.search = search.value; renderSidebar(); }, 120));
    const projBtn = h("button", { type: "button", class: "rs-proj", "aria-haspopup": "menu", title: "Đổi dự án" }, h("span", { class: "rs-proj-text" }, h("span", { class: "rs-proj-name" }), h("span", { class: "rs-proj-meta" })), icon("chevrons", { size: 14 }));
    projBtn.addEventListener("click", () => projectMenu(projBtn));
    const filterBtns = new Map(FILTERS.map(([value, label]) => [value, h("button", { type: "button", onClick: () => { S.filter = value; renderSidebar(); } }, label)]));
    const list = h("div", { class: "rs-list", role: "list" });
    const selCount = h("span", null, "");
    const selbar = h("div", { class: "rs-selbar", hidden: true }, selCount,
      h("button", { type: "button", onClick: () => { S.sel2.clear(); renderAll(); } }, "Bỏ"),
      h("button", { type: "button", class: "is-primary", onClick: () => { if (S.active === "overview") { const first = [...S.sel2][0] || S.tabs[0]; if (first) { openPaper(first, { tool: "compare" }); return; } } S.tool = "compare"; saveSession(); renderAll(); } }, "So sánh"));
    const themeBtn = h("button", { type: "button", class: "rs-theme", "aria-label": "Đổi giao diện sáng/tối" });
    themeBtn.addEventListener("click", () => { prefs.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; safeSavePrefs(); applyTheme(); renderSidebar(); });
    const side = h("aside", { class: "rs-side", "aria-label": "Kho paper" },
      h("div", { class: "rs-side-head" }, h("a", { class: "rs-back", href: "#/chat", title: "Về Local AI Core", "aria-label": "Về Local AI Core" }, icon("arrow-left", { size: 14 })), projBtn),
      h("div", { class: "rs-side-tools" }, h("div", { class: "rs-search" }, icon("search", { size: 14 }), search, h("kbd", null, `${MOD}+K`)), h("div", { class: "rs-filters", role: "group", "aria-label": "Lọc trạng thái" }, ...filterBtns.values())),
      list, selbar,
      h("div", { class: "rs-side-foot" }, h("button", { type: "button", class: "rs-add", onClick: () => addPaperDialog() }, icon("plus", { size: 14, sw: 2.2 }), "Thêm paper"), themeBtn));

    // Điện thoại: ☰ mở kho paper (drawer) — CSS chỉ hiện ở ≤768.
    const menuBtn = h("button", { type: "button", class: "rs-ibtn rs-ibtn-30 rs-menu-btn", title: "Kho paper", "aria-label": "Mở kho paper", "aria-expanded": false, onClick: () => setDrawer(!S.drawerOpen) }, icon("menu", { size: 16 }));
    const backdrop = h("div", { class: "rs-side-backdrop", hidden: true, onClick: () => setDrawer(false) });
    const showSideBtn = h("button", { type: "button", class: "rs-ibtn rs-ibtn-30", title: "Hiện thanh bên", "aria-label": "Thoát chế độ tập trung", hidden: true, onClick: toggleFocusMode }, icon("panel", { size: 14 }));
    const tabs = h("div", { class: "rs-tabs", role: "tablist" });
    const splitBtn = h("button", { type: "button", class: "rs-btn", title: `Chia đôi (${MOD}+\\)`, onClick: toggleSplit }, icon("split", { size: 14 }), "Chia đôi");
    const syncBtn = h("button", { type: "button", class: "rs-btn is-sync", title: "Cuộn đồng bộ hai ô (theo tỉ lệ)", hidden: true, onClick: toggleSync }, icon("sync", { size: 14 }), "Cuộn đồng bộ");
    const focusBtn = h("button", { type: "button", class: "rs-ibtn rs-ibtn-30", title: `Chế độ tập trung (${MOD}+.)`, "aria-label": "Chế độ tập trung", onClick: () => { if (S.active === "overview") { toast("Mở một paper rồi bật Tập trung.", "danger"); return; } toggleFocusMode(); } }, icon("scan-frame", { size: 14 }));
    const keysBtn = h("button", { type: "button", class: "rs-ibtn rs-ibtn-30 rs-keys-btn", title: "Phím tắt", "aria-label": "Phím tắt", onClick: () => { S.keysOpen = !S.keysOpen; renderKeys(); } }, "?");
    const tabbar = h("div", { class: "rs-tabbar" }, menuBtn, showSideBtn, tabs, h("div", { class: "rs-tabbar-right" }, splitBtn, syncBtn, focusBtn, keysBtn));

    const ov = h("div", { class: "rs-ov", hidden: true });
    const reader = h("div", { class: "rs-reader", hidden: true });
    const panelTitle = h("span", { class: "rs-panel-title" });
    const panelOf = h("span", { class: "rs-panel-of", hidden: true });
    const panelBody = h("div", { class: "rs-panel-body" });
    const panel = h("aside", { class: "rs-panel", hidden: true, "aria-label": "Panel công cụ" },
      h("div", { class: "rs-panel-head" }, panelTitle, panelOf, h("button", { type: "button", class: "rs-ibtn", title: "Đóng panel", "aria-label": "Đóng panel", onClick: () => { S.tool = null; saveSession(); renderAll(); } }, icon("x", { size: 12, sw: 2.4 }))),
      panelBody);
    const tools = new Map();
    const rail = h("nav", { class: "rs-rail", hidden: true, "aria-label": "Công cụ" }, ...TOOLS.map((t) => {
      const badge = h("span", { class: "rs-tool-badge", hidden: true });
      const btn = h("button", { type: "button", class: "rs-tool", title: t.label, "aria-label": t.label, onClick: () => setTool(t.id) }, icon(t.icon, { size: 17 }), badge);
      btn.badge = badge;
      tools.set(t.id, btn);
      return btn;
    }));
    const keys = h("div", { class: "rs-keys", hidden: true, onClick: () => { S.keysOpen = false; renderKeys(); } },
      h("div", { class: "rs-keys-box", role: "dialog", "aria-label": "Phím tắt", onClick: (event) => event.stopPropagation() },
        h("h2", null, "Phím tắt"),
        h("div", { class: "rs-keys-grid" }, ...KEYS.flatMap(([label, k]) => [h("span", null, label), h("kbd", null, k)])),
        h("div", { class: "rs-keys-note" }, `Trình duyệt giữ ${MOD}+W và Ctrl+Tab cho chính nó; dùng nút × trên tab khi phím không tác dụng.`)));
    const body = h("div", { class: "rs-body" }, ov, reader, panel, rail, keys);
    const main = h("div", { class: "rs-main" }, tabbar, body);
    const center = h("div", { class: "rs-center", hidden: true });
    const root = h("div", { class: "rs" }, side, backdrop, main, center);
    ctx.root.append(root);
    V = {
      ctx, root, side, main, center, search, menuBtn, backdrop, projName: projBtn.querySelector(".rs-proj-name"), projMeta: projBtn.querySelector(".rs-proj-meta"), filterBtns, list, selbar, selCount, themeBtn,
      showSideBtn, tabs, splitBtn, syncBtn, focusBtn, ov, reader, panel, panelTitle, panelOf, panelBody, panelKey: null, panelRefresh: null, rail, tools, keys, panes: new Map(),
    };
  }

  /* Áp route vào trạng thái: #/research → dự án gần nhất; #/research/<pid>[/p/<paperId>?page=&tool=]. */
  function applyRoute(ctx) {
    const [pid, kind, paperId] = ctx.params;
    const page = Number(ctx.query.get("page")) || null;
    const tool = ctx.query.get("tool");
    const wanted = pid || S.pid || lastProject() || ((S.projects || [])[0] || {}).id || null;
    if (wanted && (S.projects || []).some((p) => p.id === wanted)) {
      if (wanted !== S.pid || !S.project) switchProject(wanted, { navigate: !pid });
    } else if (wanted && pid) {
      // id lạ trên URL: để GET project tự báo 404
      if (wanted !== S.pid) switchProject(wanted, { navigate: false });
    } else S.pid = null;
    if (kind === "p" && paperId) S.pendingOpen = { paperId, page, tool: TOOLS.some((t) => t.id === tool) ? tool : undefined };
    else if (pid) S.pendingOpen = { paperId: null };
    else S.pendingOpen = null;
    applyPendingOpen();
  }

  function applyPendingOpen() {
    const want = S.pendingOpen;
    if (!want || !S.project) return;
    S.pendingOpen = null;
    if (want.paperId) {
      if (paperById(want.paperId)) openPaper(want.paperId, { page: want.page, tool: want.tool });
      else { toast(ERROR_VI.RESEARCH_PAPER_NOT_FOUND, "danger"); setActive("overview"); }
    } else if (S.active !== "overview") setActive("overview");
  }

  async function boot() {
    if (!V) return;
    const ctx = V.ctx;
    renderAll();
    if (S.projects === null) await loadProjects();
    if (!V || V.ctx !== ctx) return;
    applyRoute(ctx);
    renderAll();
  }

  function mount(ctx) {
    Shell.setLayout("full");
    ctx.setHeader("Nghiên cứu", "");
    buildShell(ctx);
    ctx.on(document, "keydown", onKeydown);
    let selTimer = 0;
    ctx.on(document, "selectionchange", () => {
      if (!V) return;
      const sel = window.getSelection();
      clearTimeout(selTimer);
      if (!sel || sel.isCollapsed) {
        // bỏ chọn bằng bàn phím / bấm ra ngoài → ẩn menu. Cảm ứng: chạm vào nút menu cũng làm vùng chọn
        // sập TRƯỚC khi click tới nơi → chờ một nhịp cho click chạy rồi mới ẩn.
        const hide = () => { if (V) for (const pane of V.panes.values()) if (pane.menu && !pane.menu.matches(":hover")) hideSelMenu(pane); };
        if (isPhone()) selTimer = setTimeout(hide, 350);
        else hide();
        return;
      }
      // Cảm ứng: kéo chốt chọn không có mouseup → đọc lại vùng chọn sau khi tay ngừng (gộp 250 ms).
      if (!isPhone() || !sel.rangeCount) return;
      selTimer = setTimeout(() => {
        if (!V) return;
        const node = sel.rangeCount ? sel.getRangeAt(0).commonAncestorContainer : null;
        for (const pane of V.panes.values()) if (node && pane.scroll.contains(node)) readSelection(pane);
      }, 250);
    });
    // Đổi ngưỡng điện thoại: nghe cả MediaQueryList lẫn resize (một số WebView không bắn "change").
    let wasPhone = isPhone();
    const onPhoneMaybe = () => { const now = isPhone(); if (now !== wasPhone) { wasPhone = now; applyPhone(); } };
    if (PHONE_MQ) ctx.on(PHONE_MQ, "change", onPhoneMaybe);
    ctx.on(window, "resize", debounce(onPhoneMaybe, 80));
    if (wasPhone) applyPhone();
    // Nút mặt trời/mặt trăng ở chân thanh bên theo data-theme (Cài đặt ở thẻ khác cũng đổi được); gỡ ở unmount.
    V.themeObserver = new MutationObserver(() => { if (V) renderSidebar(); });
    V.themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    ctx.every(() => {
      if (document.hidden || !S.pid || S.projBusy) return;
      if (papers().some(isWorking)) loadProject(S.pid, { quiet: true });
    }, POLL_MS);
    // Thả PDF vào bất kỳ đâu = mở hộp Thêm paper với tệp đó
    const hasFiles = (event) => Boolean(event.dataTransfer) && [...(event.dataTransfer.types || [])].includes("Files");
    ctx.on(window, "dragover", (event) => { if (hasFiles(event) && !event.defaultPrevented) { event.preventDefault(); } });
    ctx.on(window, "drop", (event) => {
      if (!hasFiles(event) || event.defaultPrevented) return;
      event.preventDefault();
      if (S.pid && !document.querySelector(".dialog-overlay")) addPaperDialog(event.dataTransfer.files);
    });
    boot();
  }

  function update(ctx) {
    if (!V || V.ctx !== ctx) return false;
    if (S.projects === null) { boot(); return true; }
    applyRoute(ctx);
    renderAll();
    return true;
  }

  function unmount() {
    if (V && V.themeObserver) V.themeObserver.disconnect();
    if (V) for (const id of [...V.panes.keys()]) destroyPane(id);
    for (const chat of S.chats.values()) if (chat.ctrl) chat.ctrl.abort();
    S.pendingSel = null;
    S.keysOpen = false;
    S.focusMode = false;
    S.drawerOpen = false;
    V = null;
  }

  Router.register("research", { admin: false, mount, update, unmount });
})();
