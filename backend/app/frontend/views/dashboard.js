/* ══════════════════════════════════════════════════════════════════
   /ui/views/dashboard.js — màn hình "Bảng điều khiển" (#/dashboard).

   Một IIFE, không tên top-level. Từ trên xuống:
     - dải lỗi đỏ + "Thử lại" khi CẢ /api/dashboard/stats, /health lẫn /metrics cùng hỏng;
     - dải "chỉ đọc" cho thành viên (bật tài khoản, vai trò member);
     - 6 thẻ số: hội thoại / tin nhắn web, phiên / lượt Discord (stats), tài liệu đã index và job
       lỗi (metrics); "k đang xử lý" đếm từ /documents theo đúng luật của màn Tài liệu;
     - 2 biểu đồ SVG 14 ngày (câu hỏi + lỗi; độ trễ p50/p95) từ /api/dashboard/timeseries;
     - nhật ký hành động agent (/agent/activity: 5 dòng hoặc cả 50) — quản trị viên thu hồi được
       ghi nhớ còn hiệu lực ngay trên dòng, như bảng điều khiển cũ;
     - sức khỏe hệ thống (13 khóa của /health) + 3 thanh hàng đợi (metrics.queue_length).

   Làm mới: 6 yêu cầu chạy song song, phần nào về trước vẽ phần đó; Promise.allSettled chờ đủ rồi
   mới ghi "Cập nhật HH:mm:ss" lên header và quyết định dải lỗi. Chạy mỗi 20 giây (bỏ qua khi tab
   ẩn), ngay khi tab hiện lại, và khi bấm nút làm mới trên header. Số liệu lần trước KHÔNG bị xóa
   khi lần sau hỏng (parity 20); số chỉ đếm lên khi giá trị thật sự đổi.

   Thành viên: máy chủ hiện trả 403 cho mọi mục trừ /health và /documents (F9 chưa có) → mục bị
   chặn hiện một dòng khóa nói thật, không phải lỗi. 401 cuối cùng: Shell.api đưa về màn đăng nhập.
   Hợp đồng API: research/api-admin.md §1, spec F9. Gọi mạng: chỉ Shell.api.
   Trạng thái S sống qua các lần mount (vẽ ngay số cũ rồi làm mới); V là DOM của lần mount đang
   sống, null khi đã rời view — mọi kết quả bất đồng bộ kiểm tra V / số thứ tự trước khi vẽ.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  /* ── hằng số ─────────────────────────────────────────────────── */
  const REFRESH_MS = 20000;        // như bảng điều khiển cũ (parity 10)
  const TIMEOUT_MS = 15000;        // một yêu cầu treo không giữ cả lượt làm mới mãi
  const DAYS = 14;
  const ACTIVITY_LIMIT = 50;       // mặc định của máy chủ (api-admin §1.3)
  const ACTIVITY_SHORT = 5;        // số dòng khi thu gọn (prototype P:415)
  const SVG_NS = "http://www.w3.org/2000/svg";
  /* Hình học biểu đồ của prototype (P:392-408, P:742-749): viewBox 560×190, lề 26, đáy cột y=164,
     chiều cao vẽ 150, lưới ngang y 36/76/116/164, nhãn ngày y 182. Cột 18 + cột lỗi 7 tính cho 14 ngày. */
  const W = 560;
  const H = 190;
  const PAD = 26;
  const BASE = H - 26;
  const SPAN = H - 40;
  const GRID_Y = [36, 76, 116, 164];
  const BAND14 = (W - PAD * 2) / 14;

  const SOURCES = {
    stats: { path: "/api/dashboard/stats", endpoint: "GET /api/dashboard/stats", feature: "số liệu hội thoại và Discord" },
    metrics: { path: "/metrics", endpoint: "GET /metrics", feature: "số liệu vận hành" },
    series: { path: `/api/dashboard/timeseries?days=${DAYS}`, endpoint: "GET /api/dashboard/timeseries", feature: "biểu đồ theo ngày" },
    activity: { path: `/agent/activity?limit=${ACTIVITY_LIMIT}`, endpoint: "GET /agent/activity", feature: "nhật ký hành động agent" },
    health: { path: "/health", endpoint: "GET /health", feature: "trạng thái hệ thống" },
    docs: { path: "/documents", endpoint: "GET /documents", feature: "danh sách tài liệu" },
  };
  const KEYS = Object.keys(SOURCES);
  const CORE = ["stats", "health", "metrics"];   // cả ba hỏng → dải lỗi (như dashboard cũ)
  /* nguồn vừa về → phần cần vẽ lại */
  const PAINT = { stats: ["stats"], metrics: ["stats", "queue"], docs: ["stats"], series: ["series"], activity: ["activity"], health: ["health"] };

  /* 13 khóa trạng thái của /health theo thứ tự + nhãn của dashboard cũ; khóa khác (status, service,
     memory_queue, backup_age_hours, checked_at) không phải thành phần nên không vẽ. */
  const HEALTH = [
    ["postgres", "PostgreSQL"], ["redis", "Redis"], ["qdrant", "Qdrant"], ["ollama", "Ollama"],
    ["worker_ocr", "Worker OCR"], ["worker_index", "Worker Index"], ["worker_memory", "Worker Memory"],
    ["outbox_dispatcher", "Outbox"], ["cleanup_worker", "Cleanup"], ["backup", "Sao lưu"],
    ["backup_worker", "Worker sao lưu"], ["memory_ingestion", "Nạp ghi nhớ"], ["model_fallback", "Model dự phòng"],
  ];
  const HEALTH_HINT = {
    ok: "đang chạy bình thường", disabled: "đã tắt trong cấu hình", pending: "còn việc đang chờ xử lý",
    unavailable: "không phản hồi", fallback: "một vai trò đang chạy bản dự phòng (xem trang Model)",
  };
  /* "pending" của khóa backup không cùng nghĩa với outbox: operational_service._backup_status() coi
     pending = chưa có bản dump nào (chưa có điểm phục hồi), không phải việc đang xếp hàng. */
  const healthHint = (key, value) => (key === "backup" && value === "pending" ? "chưa có bản sao lưu nào" : HEALTH_HINT[value]);
  const QUEUES = [["ocr", "Hàng đợi OCR"], ["index", "Hàng đợi index"], ["memory", "Hàng đợi memory"]];
  const TURN_LABELS = { queued: "đang chờ", running: "đang chạy", completed: "hoàn tất", failed: "thất bại", cancelled: "đã hủy" };
  const WORKING = new Set(["queued", "running", "retrying", "cancel_requested"]);
  const TONE_COLOR = { ok: "var(--ok)", warn: "var(--warn)", danger: "var(--danger)", muted: "var(--text-3)" };

  /* 6 thẻ số (P:386-388, dữ liệu P:829-831). Chấm màu là màu nhóm như prototype: web/tài liệu
     accent, Discord ok, job lỗi danger. Không có dòng "+12 tuần này": máy chủ không có số đó. */
  const CARDS = [
    { id: "conv", label: "Hội thoại web", dot: "var(--accent)", src: "stats" },
    { id: "msg", label: "Tin nhắn web", dot: "var(--accent)", src: "stats" },
    { id: "sess", label: "Phiên Discord", dot: "var(--ok)", src: "stats", pair: true },
    { id: "turns", label: "Lượt Discord", dot: "var(--ok)", src: "stats" },
    { id: "docs", label: "Tài liệu đã index", dot: "var(--accent)", src: "metrics" },
    { id: "jobs", label: "Job lỗi", dot: "var(--danger)", src: "metrics" },
  ];

  /* ── trạng thái sống qua các lần mount ───────────────────────── */
  function newSources() {
    const out = {};
    // state: idle | ok | error | missing (route chưa có — cả hai giữ số của lần trước nếu có) |
    //        locked (403 thành viên: xóa số, người này không được đọc)
    for (const key of KEYS) out[key] = { data: null, state: "idle", error: null, at: 0 };
    return out;
  }

  const S = {
    role: null,              // "admin" | "member": vai trò lúc tải dữ liệu bên dưới
    src: newSources(),
    seq: 0,                  // số thứ tự lượt làm mới: kết quả của lượt cũ bị bỏ
    busy: false,
    again: false,            // có yêu cầu làm mới trong lúc đang bận → chạy thêm một lượt sau
    tick: 0,                 // lúc bắt đầu lượt làm mới gần nhất (chặn bật/tắt tab dồn dập)
    updatedAt: 0,            // lần làm mới gần nhất mà dữ liệu lõi về được
    open: false,             // nhật ký: đang mở "Xem tất cả"
    reverting: new Set(),    // candidate_id đang gửi thu hồi
  };
  let V = null;

  /* ── tiện ích ────────────────────────────────────────────────── */
  const isNum = (value) => typeof value === "number" && Number.isFinite(value);
  const asObj = (value) => (value && typeof value === "object" && !Array.isArray(value) ? value : null);
  const count = (value) => (isNum(value) ? Math.max(0, value) : null);
  const isAbort = (error) => Boolean(error) && error.name === "AbortError";
  const oneLine = (text, max = 300) => String(text ?? "").replace(/\s+/g, " ").trim().slice(0, max);

  function toDate(value) {
    if (value === null || value === undefined || value === "") return null;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  /* "2026-09-12" → "12/09" (nhãn trục ngày; ngày theo lịch máy chủ nên không đổi qua Date). */
  function dayLabel(date) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(date || ""));
    return m ? `${m[3]}/${m[2]}` : String(date || "");
  }

  /* 12.4 → "12.4s"; dưới 1 giây giữ 2 chữ số lẻ để "0.05s" không thành "0.0s". */
  function secText(seconds) {
    if (!isNum(seconds)) return "—";
    return seconds >= 1 ? `${seconds.toFixed(1)}s` : `${seconds.toFixed(2)}s`;
  }

  /* Giờ của nhật ký: hôm nay "HH:mm", hôm qua "hôm qua", còn lại "dd/mm". */
  function activityTime(value) {
    const d = toDate(value);
    if (!d) return "—";
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return fmtClock(d, { seconds: false });
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return "hôm qua";
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getDate())}/${p(d.getMonth() + 1)}`;
  }

  /* Lời lỗi để hiện: sendJson đã dịch mã quen (ERROR_HINTS) và lỗi mạng; 500 thì máy chủ chỉ có câu
     tiếng Anh chung chung → nói bằng tiếng Việt. */
  function errText(error) {
    if (!error) return "Đã xảy ra lỗi không xác định.";
    if (error.timedOut) return `Máy chủ không trả lời sau ${TIMEOUT_MS / 1000} giây.`;
    if (error.code === "INTERNAL_ERROR") return "Máy chủ gặp lỗi không mong muốn (500).";
    return error.message || "Đã xảy ra lỗi không xác định.";
  }

  /* Khóa truy cập thiếu/sai (máy chủ bật LOCAL_AI_API_KEY): chỉ đường tới nơi nhập khóa. */
  const needsKey = (error) => Boolean(error) && (error.code === "API_KEY_REQUIRED" || error.code === "API_KEY_INVALID");

  /* Phần tử SVG (h() của components.js chỉ dựng HTML). Chữ luôn là text node. */
  function svgEl(tag, attrs, ...children) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      node.setAttribute(key, String(value));
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  /* Trần "đẹp" ≥ v cho trục số câu hỏi: bước = 1/5 bậc thập phân (tối thiểu 1) → 36.3 → 38, 5.5 → 6. */
  function niceCeil(value) {
    if (!(value > 0)) return 1;
    const step = Math.max(1, 10 ** Math.floor(Math.log10(value)) / 5);
    return Math.ceil(value / step) * step;
  }

  /* Trần trục độ trễ (giây): ≥ 1 s → số nguyên kế tiếp (12.4 → 13 như prototype); dưới 1 s → bước 0.1. */
  function latencyTop(maxSec) {
    if (maxSec >= 1) return Math.ceil(maxSec + 0.05);
    return Math.max(0.1, Math.ceil(maxSec * 1.05 * 10) / 10);
  }

  /* ── làm sạch dữ liệu máy chủ ────────────────────────────────── */
  function clean(key, data) {
    if (key === "stats") {
      const root = asObj(data) || {};
      return { web: asObj(root.web) || {}, discord: asObj(root.discord) || {} };
    }
    if (key === "series") {
      const days = Array.isArray(asObj(data) && data.days) ? data.days : [];
      return days.filter(asObj).map((d) => ({
        date: String(d.date ?? ""),
        questions: count(d.questions) ?? 0,
        errors: count(d.errors) ?? 0,
        p50: count(d.p50_ms),
        p95: count(d.p95_ms),
      }));
    }
    if (key === "activity") return Array.isArray(data) ? data.filter(asObj) : [];
    if (key === "docs") {
      // Như màn Tài liệu (bộ lọc "Đang xử lý"): uploaded + processing.
      const rows = Array.isArray(data) ? data.filter(asObj) : [];
      return { processing: rows.filter((doc) => doc.status === "uploaded" || doc.status === "processing").length };
    }
    return asObj(data) || {};
  }

  /* ── làm mới ─────────────────────────────────────────────────── */
  function requestSignal(signal) {
    const timer = typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(TIMEOUT_MS) : null;
    const combined = timer && typeof AbortSignal.any === "function" ? AbortSignal.any([signal, timer]) : signal;
    return { signal: combined, timer };
  }

  async function refresh({ manual = false } = {}) {
    if (!V) return;
    if (S.busy) {
      // Bấm "Làm mới" lúc đang chạy: xếp thêm một lượt VÀ giữ icon quay, không thì nút trông như chết.
      if (manual) {
        S.again = true;
        setSpinning(true);
      }
      return;
    }
    const ctx = V.ctx;
    const my = ++S.seq;
    S.busy = true;
    S.again = false;
    S.tick = Date.now();
    setSpinning(manual);
    const { signal, timer } = requestSignal(ctx.signal);
    const jobs = KEYS.map((key) => Shell.api(SOURCES[key].path, { signal }).then(
      (data) => settle(key, my, ctx, true, data, timer),
      (error) => settle(key, my, ctx, false, error, timer)));
    try {
      await Promise.allSettled(jobs);
    } finally {
      if (my === S.seq) S.busy = false;
    }
    if (my !== S.seq || !V || V.ctx !== ctx || ctx.signal.aborted) return;
    finish();
    if (S.again) {
      // Lượt xếp hàng cũng là do người dùng bấm → vẫn là "manual": icon quay tiếp, không tắt rồi bật lại.
      S.again = false;
      ctx.after(() => refresh({ manual: true }), 0);
    } else {
      setSpinning(false);
    }
  }

  function settle(key, my, ctx, ok, value, timer) {
    if (my !== S.seq || !V || V.ctx !== ctx || ctx.signal.aborted) return;
    const src = S.src[key];
    if (ok) {
      src.data = clean(key, value);
      src.state = "ok";
      src.error = null;
      src.at = Date.now();
    } else {
      let error = value;
      if (timer && timer.aborted) {
        error = new Error("timeout");
        error.timedOut = true;
      } else if (isAbort(error)) {
        return;
      }
      // Bật tài khoản mà phiên hết hạn: Shell đã hiện màn đăng nhập — giữ nguyên số cũ phía sau.
      if (error && error.status === 401 && Shell.authEnabled) return;
      if (error && error.status === 403 && !Shell.isAdmin()) {
        // F9 chưa có: thành viên bị chặn đọc — trạng thái khóa, không phải lỗi.
        src.state = "locked";
        src.data = null;
        src.error = null;
      } else if (isMissingApi(error)) {
        // Route biến mất giữa phiên (đổi cấu hình máy chủ): vẫn giữ số của lần trước như mọi lỗi
        // khác (parity 20) — khung nào có số cũ thì hiện chip "chưa làm mới được", khung nào chưa
        // từng có thì hiện câu "Máy chủ chưa hỗ trợ …".
        src.state = "missing";
        src.error = error;
      } else {
        src.state = "error";   // data của lần trước (nếu có) vẫn giữ
        src.error = error;
      }
    }
    // Chỉ vẽ lại phần của nguồn vừa về: vẽ lại thẻ số của nguồn khác sẽ cắt ngang hiệu ứng đếm lên
    // (countUp ghi giá trị đích ngay khi bắt đầu, gọi lại với cùng đích = nhảy thẳng).
    for (const part of PAINT[key]) paint(part, { srcs: new Set([key]) });
  }

  /* Sau khi cả 6 yêu cầu đã xong: dòng phụ đề + dải lỗi. */
  function finish() {
    const failed = KEYS.filter((key) => S.src[key].state === "error");
    const coreDown = CORE.every((key) => S.src[key].state === "error");
    if (!coreDown) S.updatedAt = Date.now();
    paintSubtitle(coreDown, failed.length > 0);
    paintBanner(coreDown);
  }

  function paintSubtitle(coreDown, partial) {
    if (!V) return;
    const every = coreDown ? "tự thử lại mỗi 20 giây" : "tự làm mới mỗi 20 giây";
    let text;
    if (coreDown) text = S.updatedAt ? `Mất kết nối · số liệu lúc ${fmtClock(S.updatedAt)} · ${every}` : `Mất kết nối · ${every}`;
    else if (!S.updatedAt) text = "Đang tải…";
    else text = `Cập nhật ${fmtClock(S.updatedAt)}${partial ? " · một phần dữ liệu lỗi" : ""} · ${every}`;
    V.ctx.setHeader("Bảng điều khiển", text);
  }

  function paintBanner(coreDown) {
    if (!V) return;
    V.banner.hidden = !coreDown;
    if (!coreDown) return;
    const first = CORE.map((key) => S.src[key].error).find(Boolean);
    V.bannerText.textContent = `Không tải được dữ liệu từ máy chủ. ${errText(first)}`;
    // Thiếu khóa truy cập thì "Thử lại" không bao giờ thành công: đổi sang lối vào Cài đặt,
    // giống các dòng khóa bên dưới.
    const key = needsKey(first);
    V.bannerRetry.hidden = key;
    V.bannerSettings.hidden = !key;
  }

  /* ── dữ liệu cũ còn trên màn nhưng lần làm mới này hỏng ──────── */
  const isStale = (key) => Boolean(S.src[key].data) && (S.src[key].state === "error" || S.src[key].state === "missing");

  function staleTitle(key, what) {
    const src = S.src[key];
    const why = src.state === "missing"
      ? `Máy chủ chưa hỗ trợ ${SOURCES[key].feature} (${SOURCES[key].endpoint}).`
      : errText(src.error);
    return `${why} — đang hiện ${what} lúc ${fmtClock(src.at)}.`;
  }

  /* Chip "chưa làm mới được" của một khung: hiện khi khung còn số cũ mà nguồn của nó vừa hỏng. */
  function setStale(el, keys, what) {
    const bad = keys.filter(isStale);
    el.hidden = !bad.length;
    // Ba nguồn cùng hỏng vì một lý do (máy chủ sập) thì chỉ nói một lần.
    if (bad.length) el.title = [...new Set(bad.map((key) => staleTitle(key, what)))].join("\n");
    else el.removeAttribute("title");
  }

  function setSpinning(on) {
    if (!V) return;
    V.refreshBtn.classList.toggle("is-busy", Boolean(on));
    V.refreshBtn.setAttribute("aria-busy", String(Boolean(on)));
  }

  function paint(part, opts) {
    if (!V) return;
    if (part === "stats") paintStats(opts);
    else if (part === "queue") paintQueue();
    else if (part === "series") paintSeries();
    else if (part === "activity") paintActivity();
    else if (part === "health") paintHealth();
  }

  /* ── trạng thái nhỏ trong một khung (khóa / lỗi / chưa hỗ trợ / rỗng) ── */
  function retryButton() {
    return h("button", { type: "button", class: "dash-retry", onClick: () => refresh({ manual: true }) }, "Thử lại");
  }

  function settingsLink() {
    return h("a", { class: "dash-retry", href: "#/settings" }, "Mở Cài đặt");
  }

  /* Nội dung trạng thái cho nguồn không có dữ liệu. kind: locked | missing | error | empty. */
  function stateParts(kind, { source, text, emptyIcon = "info" } = {}) {
    if (kind === "locked") {
      return { icon: "lock", tone: "is-locked", nodes: ["Chỉ quản trị viên xem được mục này."] };
    }
    if (kind === "missing") {
      const cfg = SOURCES[source];
      return { icon: "lock", tone: "is-missing", nodes: [`Máy chủ chưa hỗ trợ ${cfg.feature}.`, h("code", { class: "code" }, cfg.endpoint)] };
    }
    if (kind === "error") {
      const error = S.src[source].error;
      return { icon: "alert", tone: "is-error", nodes: [text || "Không tải được dữ liệu.", h("span", { class: "dash-state-sub" }, errText(error)), needsKey(error) ? settingsLink() : retryButton()] };
    }
    return { icon: emptyIcon, tone: "is-empty", nodes: [text] };
  }

  /* Dòng trạng thái nằm trong khung (nhật ký, lưới sức khỏe, hàng đợi, dải thẻ số). */
  /* role: dải lỗi trên cùng là "alert" duy nhất — máy chủ sập làm cả 6 khung cùng báo lỗi, sáu vùng
     assertive cùng lúc là sáu lần đọc cùng một câu. Trong khung dùng "status" (đọc lịch sự). */
  function stateBox(kind, opts = {}) {
    const parts = stateParts(kind, opts);
    return h("div", { class: ["dash-state", parts.tone, opts.cls], role: kind === "error" ? "status" : null },
      icon(parts.icon, { size: 15 }), h("div", { class: "dash-state-text" }, parts.nodes));
  }

  /* Chú thích nổi giữa biểu đồ (lưới vẫn vẽ phía sau). */
  function noteBox(kind, opts = {}) {
    const parts = stateParts(kind, opts);
    return h("div", { class: ["dash-note-box", parts.tone], role: kind === "error" ? "status" : null },
      icon(parts.icon, { size: 14 }), parts.nodes);
  }

  /* ── thẻ số ──────────────────────────────────────────────────── */
  function buildCard(spec) {
    const valueEl = h("div", { class: "stat-value" });
    const parts = spec.pair ? [h("span"), h("span")] : [valueEl];
    if (spec.pair) valueEl.append(parts[0], "/", parts[1]);
    const deltaEl = h("div", { class: "stat-delta" });
    const node = h("div", { class: "stat stat-dash dash-stat", dataset: { card: spec.id } },
      h("div", { class: "stat-label" }, h("span", { class: "dot", style: { background: spec.dot } }), spec.label),
      valueEl, deltaEl);
    return { spec, node, valueEl, parts, deltaEl };
  }

  /* Mô hình hiển thị của một thẻ từ dữ liệu: {values: [n] | [a, b], delta, tone, title}. */
  function cardModel(id) {
    const stats = S.src.stats.data;
    const metrics = S.src.metrics.data;
    const web = stats ? stats.web : {};
    const discord = stats ? stats.discord : {};
    if (id === "conv") {
      const last = toDate(web.last_activity_at);
      // Quá 7 ngày thì fmtRelative trả về ngày tháng — thêm "ngày" để dòng không đọc thành
      // "hoạt động 26/08/2026" cụt lủn (vẫn đủ ngắn cho thẻ 150px).
      const rel = last ? fmtRelative(last) : "";
      const relText = /^\d{2}\/\d{2}\/\d{4}$/.test(rel) ? `ngày ${rel}` : rel;
      return {
        values: [count(web.conversation_count)],
        delta: last ? `hoạt động ${relText}` : "chưa có hoạt động", tone: "muted",
        title: last ? `Hội thoại web cập nhật gần nhất: ${fmtDate(last, { time: true })}` : null,
      };
    }
    if (id === "msg") {
      return { values: [count(web.message_count)], delta: "người dùng + trợ lý", tone: "muted", title: "Tổng tin nhắn trong mọi hội thoại web, gồm cả câu hỏi lẫn câu trả lời" };
    }
    if (id === "sess") {
      const last = toDate(discord.last_activity_at);
      const sent = count(discord.delivery_count);
      const bits = [];
      if (last) bits.push(`Hoạt động Discord gần nhất: ${fmtRelative(last)}`);
      if (sent !== null) bits.push(`${fmtNumber(sent)} tin đã gửi lên Discord`);
      return { values: [count(discord.active_session_count), count(discord.session_count)], delta: "active / tổng", tone: "muted", title: bits.join(" · ") || null };
    }
    if (id === "turns") {
      // Không có turn_counts (khuôn dữ liệu lạ) thì không đếm được: "—", chứ không phải 0 và
      // không khẳng định "không lỗi" về thứ máy chủ chưa gửi.
      const turns = asObj(discord.turn_counts);
      const entries = turns ? Object.entries(turns).filter(([, n]) => isNum(n)) : [];
      const total = turns ? entries.reduce((sum, [, n]) => sum + Math.max(0, n), 0) : null;
      const failed = turns ? count(turns.failed) || 0 : null;
      const title = entries.length ? entries.map(([k, n]) => `${TURN_LABELS[k] || k}: ${fmtNumber(n)}`).join(" · ")
        : (turns ? "Chưa có lượt nào" : "Máy chủ không trả về số lượt Discord");
      let delta = "không lỗi";
      if (failed === null) delta = "chưa có số liệu";
      else if (failed > 0) delta = `${fmtNumber(failed)} thất bại`;
      return { values: [total], delta, tone: failed ? "warn" : "muted", title };
    }
    if (id === "docs") {
      const docs = S.src.docs;
      let delta;
      let tone = "muted";
      let deltaTitle = null;
      if (docs.data) delta = `${fmtNumber(docs.data.processing)} đang xử lý`;
      else if (docs.state === "idle") delta = null;
      else {
        delta = "chưa đếm được";
        deltaTitle = docs.state === "locked" ? "Chỉ quản trị viên xem được mục này." : `Không đếm được tài liệu đang xử lý: ${errText(docs.error)}`;
        tone = "muted";
      }
      const bits = [];
      if (metrics && isNum(metrics.runs_completed)) bits.push(`${fmtNumber(metrics.runs_completed)} lượt ingest hoàn tất`);
      if (metrics && isNum(metrics.active_chunks)) bits.push(`${fmtNumber(metrics.active_chunks)} đoạn đang dùng`);
      if (deltaTitle) bits.push(deltaTitle);
      return { values: [metrics ? count(metrics.documents_indexed) : null], delta, tone, title: bits.join(" · ") || null };
    }
    // jobs
    const failed = metrics ? count(metrics.jobs_failed) : null;
    const retrying = metrics ? count(metrics.jobs_retrying) : null;
    const stale = metrics ? count(metrics.jobs_stale) : null;
    let delta = "không có";
    let tone = "ok";
    if (failed === null) {           // máy chủ không gửi jobs_failed: không nói "không có"
      delta = "chưa có số liệu";
      tone = "muted";
    } else if (failed > 0) {
      delta = "cần xem lại";
      tone = "danger";
    }
    return {
      values: [failed], delta, tone,
      title: `Đang thử lại: ${fmtNumber(retrying ?? 0)} · Kẹt (worker giữ việc quá lâu): ${fmtNumber(stale ?? 0)}`,
    };
  }

  function setDelta(card, text, tone, extra) {
    card.deltaEl.replaceChildren(...(extra ? [extra] : []), text ?? "");
    card.deltaEl.style.color = TONE_COLOR[tone] || TONE_COLOR.muted;
  }

  function setSkeleton(card) {
    card.node.classList.remove("is-locked");
    card.node.removeAttribute("title");
    for (const el of card.parts) {
      if (el._countUpStop) el._countUpStop();
      el._countValue = undefined;
    }
    card.valueEl.replaceChildren(skeleton({ w: card.spec.pair ? 70 : 56, h: 22, r: 6 }));
    card.valueEl.firstChild.classList.add("dash-skel-inline");
    card.deltaEl.replaceChildren(skeleton({ w: 84, h: 9, r: 4 }));
    card.deltaEl.firstChild.classList.add("dash-skel-inline");
  }

  /* Gắn lại phần tử số (sau skeleton) và đếm lên. quiet = vẽ lại số đã có (mount lại) → không đếm. */
  function setValues(card, values, quiet) {
    if (card.spec.pair) {
      if (card.valueEl.childNodes.length !== 3 || card.valueEl.firstChild !== card.parts[0]) {
        card.valueEl.replaceChildren(card.parts[0], "/", card.parts[1]);
      }
    } else if (card.valueEl.querySelector(".skeleton")) {
      card.valueEl.replaceChildren();
    }
    card.parts.forEach((el, i) => countUp(el, values[i] ?? null, quiet ? { duration: 0 } : undefined));
  }

  /* srcs = tập nguồn vừa đổi (null = vẽ tất cả). Thẻ "Tài liệu đã index" lấy số từ /metrics nhưng
     dòng delta lấy từ /documents, nên nguồn "docs" chỉ làm mới dòng delta của thẻ đó. */
  function paintStats({ quiet = false, srcs = null } = {}) {
    const P = V.stats;
    // Dải thẻ số không có đầu khung riêng: chip "chưa làm mới được" nằm ngay trên dải, để sáu con
    // số đông cứng không trông như số mới (các khung khác đã có chip của mình).
    setStale(P.stale, ["stats", "metrics", "docs"], "số liệu");
    P.staleBox.hidden = P.stale.hidden;
    const locked = S.src.stats.state === "locked" && S.src.metrics.state === "locked";
    P.grid.hidden = locked;
    P.locked.hidden = !locked;
    if (locked) return;
    for (const card of P.cards) {
      const src = S.src[card.spec.src];
      const valueDirty = !srcs || srcs.has(card.spec.src);
      if (!valueDirty && !(card.spec.id === "docs" && srcs.has("docs") && src.data)) continue;
      if (src.data) {
        const model = cardModel(card.spec.id);
        card.node.classList.remove("is-locked");
        if (valueDirty) setValues(card, model.values, quiet);
        if (model.delta === null) {
          card.deltaEl.replaceChildren(skeleton({ w: 84, h: 9, r: 4 }));
          card.deltaEl.firstChild.classList.add("dash-skel-inline");
        } else {
          setDelta(card, model.delta, model.tone);
        }
        if (model.title) card.node.title = model.title;
        else card.node.removeAttribute("title");
      } else if (src.state === "idle") {
        setSkeleton(card);
      } else {
        // Chưa từng có số: "—" + lý do (khóa / lỗi / chưa hỗ trợ). Có số cũ thì đã rơi vào nhánh trên.
        setValues(card, card.spec.pair ? [null, null] : [null], true);
        if (src.state === "locked") {
          card.node.classList.add("is-locked");
          setDelta(card, "chỉ quản trị viên", "muted", icon("lock", { size: 11 }));
          card.node.title = "Chỉ quản trị viên xem được mục này.";
        } else {
          card.node.classList.remove("is-locked");
          setDelta(card, src.state === "missing" ? "máy chủ chưa hỗ trợ" : "không tải được", src.state === "missing" ? "muted" : "danger");
          card.node.title = src.state === "missing" ? `Máy chủ chưa hỗ trợ ${SOURCES[card.spec.src].feature} (${SOURCES[card.spec.src].endpoint}).` : errText(src.error);
        }
      }
    }
  }

  /* ── biểu đồ ─────────────────────────────────────────────────── */
  function gridLines() {
    return GRID_Y.map((y) => svgEl("line", { class: "dash-grid-line", x1: PAD, x2: W - PAD, y1: y, y2: y }));
  }

  /* Nhãn ngày cách một: tính từ ngày mới nhất về trước để hôm nay luôn có nhãn. Chữ thật trong <text>. */
  function xLabels(days, band) {
    const n = days.length;
    return days.map((d, i) => ((n - 1 - i) % 2 === 0
      ? svgEl("text", { class: "dash-xl", x: (PAD + (i + 0.5) * band).toFixed(1), y: 182 }, dayLabel(d.date))
      : null)).filter(Boolean);
  }

  /* Ô trong suốt theo từng ngày: di chuột thấy số của ngày đó (<title>). */
  function hitRects(days, band, titleOf) {
    return days.map((d, i) => svgEl("rect", { class: "dash-hit", x: (PAD + i * band).toFixed(1), y: 20, width: band.toFixed(1), height: 150 },
      svgEl("title", null, titleOf(d))));
  }

  function chartNote(P, node) {
    P.note.replaceChildren(...(node ? [node] : []));
    P.note.hidden = !node;
  }

  function drawQuestions(P, days, animate) {
    const n = days.length;
    const band = (W - PAD * 2) / n;
    const k = band / BAND14;
    const maxV = Math.max(0, ...days.map((d) => Math.max(d.questions, d.errors)));
    const top = niceCeil(maxV * 1.1);
    const hOf = (v) => (v > 0 ? Math.max(2, (v / top) * SPAN) : 0);
    const bars = [];
    const errs = [];
    days.forEach((d, i) => {
      if (d.questions > 0) {
        const hh = hOf(d.questions);
        bars.push(svgEl("rect", {
          class: "dash-bar", x: (PAD + i * band + 6 * k).toFixed(1), y: (BASE - hh).toFixed(1), width: (18 * k).toFixed(1),
          height: hh.toFixed(1), rx: 3, style: `animation-delay:${i * 40}ms`,
        }));
      }
      if (d.errors > 0) {
        const hh = hOf(d.errors);
        errs.push(svgEl("rect", {
          class: "dash-err", x: (PAD + i * band + 26 * k).toFixed(1), y: (BASE - hh).toFixed(1), width: (7 * k).toFixed(1),
          height: hh.toFixed(1), rx: 2, style: `animation-delay:${i * 40 + 200}ms`,
        }));
      }
    });
    const totalQ = days.reduce((s, d) => s + d.questions, 0);
    const totalE = days.reduce((s, d) => s + d.errors, 0);
    const peak = days.reduce((best, d) => (d.questions > best.questions ? d : best), days[0]);
    P.svg.replaceChildren(...gridLines(), ...bars, ...errs, ...xLabels(days, band),
      ...hitRects(days, band, (d) => `${dayLabel(d.date)}: ${fmtNumber(d.questions)} câu hỏi · ${fmtNumber(d.errors)} lỗi`));
    P.svg.classList.toggle("dash-still", !animate);
    P.svg.setAttribute("aria-label", totalQ || totalE
      ? `Câu hỏi ${n} ngày: tổng ${fmtNumber(totalQ)} câu hỏi, ${fmtNumber(totalE)} lỗi; nhiều nhất ${fmtNumber(peak.questions)} câu hỏi ngày ${dayLabel(peak.date)}.`
      : `Câu hỏi ${n} ngày: chưa có câu hỏi nào.`);
    chartNote(P, totalQ || totalE ? null : noteBox("empty", { text: `Chưa có câu hỏi nào trong ${n} ngày qua.`, emptyIcon: "chat" }));
  }

  function polylineLength(points) {
    let len = 0;
    for (let i = 1; i < points.length; i++) len += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    return len;
  }

  function drawLatency(P, days, animate) {
    const n = days.length;
    const band = (W - PAD * 2) / n;
    const values = days.flatMap((d) => [d.p50, d.p95]).filter(isNum);
    const nodes = [...gridLines()];
    if (!values.length) {
      P.svg.replaceChildren(...nodes, ...xLabels(days, band));
      P.svg.setAttribute("aria-label", "Độ trễ trả lời: chưa có số đo.");
      chartNote(P, noteBox("empty", { text: `Chưa có số đo độ trễ trong ${n} ngày qua.`, emptyIcon: "clock" }));
      return;
    }
    const maxSec = Math.max(...values) / 1000;
    const top = latencyTop(maxSec);
    const pointsOf = (key) => days.map((d, i) => (isNum(d[key])
      ? [PAD + (i + 0.5) * band, BASE - (d[key] / 1000 / top) * SPAN] : null)).filter(Boolean);
    const fmtPts = (pts) => pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const p50 = pointsOf("p50");
    const p95 = pointsOf("p95");
    if (p50.length >= 2) {
      // vùng dưới đường p50 (P:403): từ đáy dưới điểm đầu tới đáy dưới điểm cuối
      const area = `${p50[0][0].toFixed(1)},${BASE} ${fmtPts(p50)} ${p50[p50.length - 1][0].toFixed(1)},${BASE}`;
      nodes.push(svgEl("polygon", { class: "dash-area", points: area }));
    }
    const line = (pts, cls) => {
      if (pts.length === 1) return svgEl("circle", { class: `dash-dot ${cls}`, cx: pts[0][0].toFixed(1), cy: pts[0][1].toFixed(1), r: 3 });
      if (!pts.length) return null;
      const len = Math.max(1400, Math.ceil(polylineLength(pts)) + 2);
      return svgEl("polyline", { class: `dash-line ${cls}`, points: fmtPts(pts), style: `--dash-len:${len}` });
    };
    nodes.push(line(p95, "is-p95"), line(p50, "is-p50"));
    nodes.push(svgEl("text", { class: "dash-cap", x: 28, y: 14 }, `tối đa ${secText(maxSec)}`));
    const p50Max = Math.max(...days.map((d) => d.p50).filter(isNum), -1);
    const p95Max = Math.max(...days.map((d) => d.p95).filter(isNum), -1);
    P.svg.replaceChildren(...nodes.filter(Boolean), ...xLabels(days, band),
      ...hitRects(days, band, (d) => (isNum(d.p50) || isNum(d.p95)
        ? `${dayLabel(d.date)}: p50 ${secText(isNum(d.p50) ? d.p50 / 1000 : null)} · p95 ${secText(isNum(d.p95) ? d.p95 / 1000 : null)}`
        : `${dayLabel(d.date)}: chưa có câu trả lời thành công`)));
    P.svg.classList.toggle("dash-still", !animate);
    P.svg.setAttribute("aria-label", `Độ trễ trả lời ${n} ngày: p50 cao nhất ${secText(p50Max >= 0 ? p50Max / 1000 : null)}, p95 cao nhất ${secText(p95Max >= 0 ? p95Max / 1000 : null)}.`);
    chartNote(P, null);
  }

  /* Chưa có dữ liệu ngày nào: chỉ lưới + chú thích trạng thái. */
  function drawBare(P, node, label) {
    P.svg.replaceChildren(...gridLines());
    P.svg.setAttribute("aria-label", label);
    P.sig = null;
    chartNote(P, node);
  }

  function paintSeries() {
    const src = S.src.series;
    const days = src.data;
    for (const P of [V.charts.q, V.charts.l]) {
      setStale(P.stale, ["series"], "số liệu");
      if (days && days.length) {
        const sig = JSON.stringify(days);
        if (P.sig === sig) continue;
        // Hiệu ứng mọc cột / vẽ đường chỉ ở lần vẽ đầu của mỗi lần mở màn hình; số mới sau đó thay tại chỗ.
        const animate = !P.drawn;
        P.sig = sig;
        P.drawn = true;
        if (P === V.charts.q) drawQuestions(P, days, animate);
        else drawLatency(P, days, animate);
      } else if (days) {
        drawBare(P, noteBox("empty", { text: "Máy chủ không trả về ngày nào.", emptyIcon: "info" }), P.title);
      } else if (src.state === "idle") {
        drawBare(P, skeleton({ w: "46%", h: 12 }), P.title);
      } else {
        drawBare(P, noteBox(src.state, { source: "series", text: "Không tải được dữ liệu." }), P.title);
      }
    }
  }

  function buildChart(title, legend) {
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": title, focusable: "false" }, ...gridLines());
    const note = h("div", { class: "dash-note", hidden: true });
    const stale = h("span", { class: "dash-stale", hidden: true }, icon("alert", { size: 12 }), "chưa làm mới được");
    const node = h("section", { class: "card card-p dash-card", "aria-label": title },
      h("div", { class: "dash-head is-chart" }, h("strong", null, title), stale, legend),
      h("div", { class: "dash-chart" }, svg, note));
    return { node, svg, note, stale, title, sig: null, drawn: false };
  }

  /* ── nhật ký hành động agent ─────────────────────────────────── */
  /* "dashboard" = quản trị viên duyệt trên web (máy chủ ghi reviewed_by="dashboard") — như màn Ghi nhớ. */
  function actorLabel(actor) {
    const text = oneLine(actor, 60);
    return text === "dashboard" ? "admin" : text;
  }

  function statusTone(status) {
    if (status === "completed" || status === "applied") return "ok";
    if (WORKING.has(status)) return "warn";
    if (status === "failed") return "danger";
    return "muted";   // rejected, cancelled, "<n> lượt công cụ", lạ
  }

  /* Mô hình một dòng: nhãn loại, icon + tông ô icon (P:835-839). */
  function activityModel(item) {
    const kind = String(item.kind || "");
    const status = oneLine(item.status, 40);
    if (kind === "agent_answer") {
      const m = /^(\d+)/.exec(status);
      const tools = m ? Number(m[1]) : 0;
      return { label: tools >= 1 ? "Trả lời bằng công cụ" : "Trả lời", icon: "zap", tile: "accent", status };
    }
    if (kind === "memory_apply") return { label: "Nhớ", icon: "bulb", tile: "accent", status };
    if (kind === "memory_revert") return { label: "Thu hồi ghi nhớ", icon: "retry", tile: "muted", status };
    if (kind === "memory_reject") return { label: "Từ chối đề xuất", icon: "ban", tile: "muted", status };
    if (kind === "job") {
      if (status === "completed") return { label: "Việc nền", icon: "check", tile: "ok", status };
      if (status === "failed") return { label: "Việc nền", icon: "alert", tile: "danger", status };
      if (WORKING.has(status)) return { label: "Việc nền", icon: "retry", tile: "warn", status };
      return { label: "Việc nền", icon: "x", tile: "muted", status };
    }
    return { label: oneLine(kind, 40) || "Hoạt động", icon: "activity", tile: "muted", status };
  }

  function canRevert(item) {
    return Shell.isAdmin() && item.revertable === true && item.candidate_id !== null && item.candidate_id !== undefined && item.candidate_id !== "";
  }

  function activityRow(item) {
    const model = activityModel(item);
    const actor = actorLabel(item.actor);
    const title = oneLine(item.title, 300);
    const at = toDate(item.at);
    let revertBtn = null;
    if (canRevert(item)) {
      const id = String(item.candidate_id);
      const busy = S.reverting.has(id);
      // aria-disabled chứ không phải disabled: nút vẫn giữ được focus bàn phím trong lúc gửi, không
      // thì danh sách vẽ lại là focus rơi về "Xem tất cả" và không quay lại. revert() tự chặn bấm lại.
      revertBtn = h("button", {
        type: "button", class: "btn btn-28 btn-outline hover-danger dash-revert",
        "aria-disabled": busy ? "true" : null, dataset: { candidate: id },
        title: "Thu hồi ghi nhớ này — agent thôi dùng nó",
        onClick: () => revert(item),
      }, busy ? "Đang thu hồi…" : "Thu hồi");
    }
    const statusPill = model.status ? pill(model.status, statusTone(model.status), { dot: false }) : null;
    if (statusPill) statusPill.classList.add("pill-auto");
    return h("div", { class: "dash-act", role: "listitem" },
      h("span", { class: ["icon-tile", `tone-${model.tile}`] }, icon(model.icon, { size: 14 })),
      h("div", { class: "dash-act-body" },
        h("div", { class: "dash-act-kind" }, model.label, actor ? h("span", null, ` · ${actor}`) : null),
        h("div", { class: "dash-act-title", title: title || null }, title || "(không có nội dung)")),
      revertBtn,
      statusPill,
      h("span", { class: "dash-act-time", title: at ? fmtDate(at, { time: true }) : null }, activityTime(item.at)));
  }

  function skeletonRows(n) {
    return Array.from({ length: n }, () => h("div", { class: "dash-act", "aria-hidden": "true" },
      skeleton({ w: 30, h: 30, r: 9 }),
      h("div", { class: "dash-act-body dash-skel-col" }, skeleton({ w: "55%", h: 11 }), skeleton({ w: "35%", h: 10 }))));
  }

  function paintActivity() {
    const src = S.src.activity;
    const P = V.act;
    const rows = src.data;
    setStale(P.stale, ["activity"], "nhật ký");
    const many = Boolean(rows) && rows.length > ACTIVITY_SHORT;
    P.more.hidden = !many;
    P.more.textContent = S.open ? "Thu gọn" : "Xem tất cả →";
    P.more.setAttribute("aria-expanded", String(S.open && many));
    // Mở ra là một vùng cuộn được: phần lớn dòng không có nút nào, nên chính khối này phải nhận
    // được focus, không thì bàn phím không cuộn tới dòng thứ 6 trở đi (WCAG 2.1.1).
    const scrollable = S.open && many;
    P.list.classList.toggle("is-open", scrollable);
    if (scrollable) P.list.setAttribute("tabindex", "0");
    else P.list.removeAttribute("tabindex");
    let sig;
    let build;
    if (!rows) {
      sig = `state:${src.state}:${src.error ? errText(src.error) : ""}`;
      build = () => (src.state === "idle" ? skeletonRows(ACTIVITY_SHORT)
        : [stateBox(src.state, { source: "activity", text: "Không tải được nhật ký." })]);
    } else if (!rows.length) {
      sig = "empty";
      build = () => [stateBox("empty", { text: "Chưa có hành động tự hành nào.", emptyIcon: "activity" })];
    } else {
      const shown = S.open ? rows : rows.slice(0, ACTIVITY_SHORT);
      sig = JSON.stringify([shown, [...S.reverting], Shell.isAdmin(), new Date().toDateString()]);
      build = () => shown.map(activityRow);
    }
    if (P.sig === sig) return;
    P.sig = sig;
    // Giữ focus bàn phím khi danh sách vẽ lại: nút "Thu hồi" cùng ứng viên, không thì nút "Xem tất cả".
    const at = document.activeElement;
    const hadFocus = Boolean(at) && P.list.contains(at);
    const focusId = hadFocus && at.dataset ? at.dataset.candidate : null;
    const nodes = build();
    P.list.setAttribute("role", rows && rows.length ? "list" : "presentation");
    P.list.replaceChildren(...nodes);
    if (hadFocus) {
      const target = (focusId && [...P.list.querySelectorAll(".dash-revert")].find((b) => b.dataset.candidate === focusId))
        || (P.more.hidden ? null : P.more);
      if (target) target.focus({ preventScroll: true });
    }
  }

  /* Thu hồi ghi nhớ từ nhật ký (như dashboard cũ, không hỏi lại — cùng cách với màn Ghi nhớ). */
  async function revert(item) {
    if (!V || !Shell.isAdmin()) return;
    const id = String(item.candidate_id);
    if (S.reverting.has(id)) return;
    const ctx = V.ctx;
    S.reverting.add(id);
    paintActivity();
    try {
      // Không truyền ctx.signal: hủy một lệnh GHI giữa chừng thì không biết máy chủ đã làm hay chưa.
      // Vì thế toast cũng nằm ngoài guard V/ctx bên dưới — việc đã chạy xong thật, người dùng có
      // rời màn hình thì vẫn phải biết kết quả.
      await Shell.api(`/api/memory-review/candidates/${encodeURIComponent(id)}/revert`, { method: "POST" });
      toast("Đã thu hồi — agent thôi dùng ghi nhớ này.");
    } catch (error) {
      if (!isAbort(error)) toast(revertMessage(error), "danger");
    } finally {
      S.reverting.delete(id);
    }
    if (!V || V.ctx !== ctx) return;
    paintActivity();
    refresh({ manual: true });
  }

  function revertMessage(error) {
    const raw = String((error && error.message) || "");
    if (error && error.code === "CANDIDATE_NOT_FOUND") return "Không còn ghi nhớ này — có thể đã được thu hồi ở nơi khác.";
    if (error && error.code === "MEMORY_MIRROR_FAILED") return "Đã thu hồi nhưng chưa gỡ được bản sao trên web — bấm Thu hồi lần nữa.";
    if (/only applied candidates can be reverted/i.test(raw)) return "Chỉ thu hồi được ghi nhớ đã được áp dụng.";
    if (/memory is already/i.test(raw)) return "Ghi nhớ này không còn hiệu lực — có thể đã được thu hồi ở nơi khác.";
    return errText(error);
  }

  /* ── sức khỏe hệ thống + hàng đợi ────────────────────────────── */
  function healthDot(value) {
    if (value === "ok") return "var(--ok)";
    if (value === "disabled") return "var(--border-2)";
    if (value === "pending") return "var(--warn)";
    return "var(--danger)";   // unavailable, fallback, giá trị lạ
  }

  function paintHealth() {
    const src = S.src.health;
    const P = V.health;
    const data = src.data;
    setStale(P.stale, ["health"], "trạng thái");
    let sig;
    let build;
    let summary = null;
    if (!data) {
      sig = `state:${src.state}:${src.error ? errText(src.error) : ""}`;
      build = () => (src.state === "idle"
        ? Array.from({ length: 12 }, () => h("div", { class: "health-cell", "aria-hidden": "true" }, skeleton({ w: "62%", h: 10 })))
        : [stateBox(src.state, { source: "health", text: "Không tải được trạng thái hệ thống.", cls: "dash-span" })]);
    } else {
      const present = HEALTH.filter(([key]) => typeof data[key] === "string");
      const ok = present.filter(([key]) => data[key] === "ok").length;
      // Màu của con số đếm theo thứ THẬT SỰ hỏng: "disabled" là cấu hình bình thường (tắt nạp ghi
      // nhớ), không phải sự cố — README §4 hiện "11/13 ok" màu --ok trên đúng dữ liệu ấy. Nếu đếm
      // disabled là chưa ok thì mọi máy tắt một thành phần sẽ cam vĩnh viễn.
      const bad = present.filter(([key]) => data[key] !== "ok" && data[key] !== "disabled");
      summary = present.length ? { ok, total: present.length, bad } : null;
      sig = JSON.stringify(present.map(([key]) => [key, data[key]]).concat([["age", data.backup_age_hours]]));
      build = () => (present.length ? present.map(([key, label]) => {
        const value = oneLine(data[key], 40);
        const hint = healthHint(key, value);
        let title = `${label}: ${value}${hint ? ` — ${hint}` : ""}`;
        const age = Number(data.backup_age_hours);
        // "pending" = chưa có bản dump nào, nên không kèm tuổi bản sao lưu (máy chủ thật trả null).
        if (key === "backup" && value !== "pending" && data.backup_age_hours !== undefined && data.backup_age_hours !== null && Number.isFinite(age)) {
          title += ` · bản sao lưu gần nhất cách đây ${age.toLocaleString("vi-VN", { maximumFractionDigits: 1 })} giờ`;
        }
        return h("div", { class: "health-cell", role: "listitem", title },
          h("span", { class: "dot", style: { background: healthDot(value) } }),
          h("span", { class: "dash-hname" }, label),
          h("span", { class: "dash-hstate" }, value));
      }) : [stateBox("empty", { text: "Máy chủ không báo trạng thái thành phần nào.", cls: "dash-span" })]);
    }
    P.count.hidden = !summary;
    if (summary) {
      const off = summary.total - summary.ok - summary.bad.length;
      P.count.classList.toggle("is-warn", summary.bad.length > 0);
      P.countText.textContent = `${summary.ok}/${summary.total} ok`;
      P.count.title = summary.bad.length
        ? `Chưa ổn: ${summary.bad.map(([key, label]) => `${label} (${oneLine(data[key], 40)})`).join(" · ")}`
        : (off ? `Mọi thành phần đang bật đều ổn · ${off} thành phần đã tắt trong cấu hình` : "Mọi thành phần đều ổn");
    }
    if (P.sig === sig) return;
    P.sig = sig;
    const cells = build();
    // role="list" chỉ đúng khi trong lưới là các ô thành phần (không phải skeleton / dòng trạng thái)
    P.grid.setAttribute("role", data && cells.length && cells[0].classList.contains("health-cell") ? "list" : "presentation");
    P.grid.replaceChildren(...cells);
  }

  function paintQueue() {
    const src = S.src.metrics;
    const P = V.queue;
    const data = src.data;
    if (!data) {
      P.rows.forEach((row) => { row.node.hidden = true; });
      const key = `state:${src.state}:${src.error ? errText(src.error) : ""}`;
      if (P.stateSig !== key) {
        P.stateSig = key;
        P.state.replaceChildren(...(src.state === "idle"
          ? [skeleton({ w: "100%", h: 10 }), skeleton({ w: "80%", h: 10 }), skeleton({ w: "90%", h: 10 })]
          : [stateBox(src.state, { source: "metrics", text: "Không tải được hàng đợi." })]));
      }
      P.state.hidden = false;
      return;
    }
    P.state.hidden = true;
    P.stateSig = null;
    const q = asObj(data.queue_length) || {};
    const values = QUEUES.map(([key]) => count(q[key]));
    const scale = Math.max(5, ...values.filter((v) => v !== null));
    P.rows.forEach((row, i) => {
      const n = values[i];
      row.node.hidden = false;
      row.fill.style.width = n === null ? "0%" : `${Math.min(100, (n / scale) * 100)}%`;
      row.num.textContent = n === null ? "—" : fmtNumber(n);
      row.node.title = n === null
        ? `${row.label}: không đọc được (Redis không trả lời)`
        : `${row.label}: ${fmtNumber(n)} việc đang chờ trong hàng đợi (chưa tính việc đang chạy)`;
    });
  }

  /* ── mount ───────────────────────────────────────────────────── */
  function buildQueue() {
    const rows = QUEUES.map(([, label]) => {
      const fill = h("div", { class: "fill", style: { width: "0%" } });
      const num = h("span", { class: "dash-q-n" }, "—");
      const node = h("div", { class: "dash-q", hidden: true }, h("span", { class: "dash-q-label" }, label), h("div", { class: "progress" }, fill), num);
      return { node, fill, num, label };
    });
    const state = h("div", { class: "dash-q-state" });
    return { node: h("div", { class: "dash-queue", "aria-label": "Hàng đợi" }, rows.map((r) => r.node), state), rows, state, stateSig: null };
  }

  function mount(ctx) {
    const role = Shell.isAdmin() ? "admin" : "member";
    if (S.role !== role) {
      // Vai trò khác lần trước (đăng nhập lại): không giữ số liệu đã tải bằng vai trò cũ.
      S.src = newSources();
      S.updatedAt = 0;
      S.reverting.clear();
      S.role = role;
    }
    // Lượt làm mới của lần mount trước đã bị hủy theo ctx.signal nhưng chưa kịp về: bỏ kết quả của nó.
    S.seq += 1;
    S.busy = false;
    S.again = false;
    S.open = false;

    const refreshBtn = h("button", {
      type: "button", class: "icon-btn icon-btn-36 icon-btn-outline text-2 dash-refresh",
      title: "Làm mới ngay", "aria-label": "Làm mới bảng điều khiển", onClick: () => refresh({ manual: true }),
    }, icon("refresh", { size: 17, sw: 1.9 }));
    ctx.setActions([refreshBtn]);

    const bannerText = h("span", { class: "dash-error-text" });
    const bannerRetry = h("button", { type: "button", class: "btn btn-28 btn-outline-danger", onClick: () => refresh({ manual: true }) },
      icon("retry", { size: 13 }), "Thử lại");
    const bannerSettings = h("a", { class: "btn btn-28 btn-outline-danger", href: "#/settings", hidden: true },
      icon("key", { size: 13 }), "Mở Cài đặt");
    const banner = h("div", { class: "dash-error", role: "alert", hidden: true },
      icon("alert", { size: 15 }), bannerText, bannerRetry, bannerSettings);
    const member = Shell.authEnabled && !Shell.isAdmin()
      ? h("div", { class: "banner-warn" }, icon("shield", { size: 15 }), "Bạn đang xem ở chế độ chỉ đọc (thành viên).")
      : null;

    const cards = CARDS.map(buildCard);
    const statsStale = h("span", { class: "dash-stale", hidden: true }, icon("alert", { size: 12 }), "chưa làm mới được");
    const stats = {
      cards,
      stale: statsStale,
      staleBox: h("div", { class: "dash-stats-note", hidden: true }, statsStale),
      grid: h("div", { class: "dash-stats" }, cards.map((c) => c.node)),
      locked: h("div", { class: "dash-strip", hidden: true },
        stateBox("locked", { cls: "dash-state-strip" })),
    };

    const q = buildChart("Câu hỏi 14 ngày", h("span", { class: "legend" },
      h("span", null, h("i", { class: "swatch", style: { background: "var(--accent)" } }), "câu hỏi"),
      h("span", null, h("i", { class: "swatch", style: { background: "var(--danger)" } }), "lỗi")));
    const l = buildChart("Độ trễ trả lời (giây)", h("span", { class: "legend" },
      h("span", null, h("i", { class: "swatch-line", style: { background: "var(--accent)" } }), "p50"),
      h("span", null, h("i", { class: "swatch-line", style: { background: "var(--warn)" } }), "p95")));

    const actList = h("div", { class: "dash-act-list", id: "dash-activity", role: "list", "aria-label": "Nhật ký hành động agent" });
    const actMore = h("button", {
      type: "button", class: "dash-more", "aria-controls": "dash-activity", "aria-expanded": false, hidden: true,
      onClick: () => {
        S.open = !S.open;
        paintActivity();
        if (!S.open) actList.scrollTop = 0;
      },
    }, "Xem tất cả →");
    const actStale = h("span", { class: "dash-stale", hidden: true }, icon("alert", { size: 12 }), "chưa làm mới được");
    const act = { list: actList, more: actMore, stale: actStale, sig: null };
    const actCard = h("section", { class: "card card-p dash-card", "aria-label": "Nhật ký hành động agent" },
      h("div", { class: "dash-head" }, h("strong", null, "Nhật ký hành động agent"), actStale, actMore), actList);

    const countText = h("span");
    const healthCount = h("span", { class: "dash-hcount", hidden: true }, h("span", { class: "dot" }), countText);
    const healthStale = h("span", { class: "dash-stale", hidden: true }, icon("alert", { size: 12 }), "chưa làm mới được");
    const health = { grid: h("div", { class: "dash-health", role: "list", "aria-label": "Thành phần hệ thống" }), count: healthCount, countText, stale: healthStale, sig: null };
    const queue = buildQueue();
    const healthCard = h("section", { class: "card card-p dash-card", "aria-label": "Sức khỏe hệ thống" },
      h("div", { class: "dash-head" }, h("strong", null, "Sức khỏe hệ thống"), healthStale, healthCount), health.grid, queue.node);

    const page = h("div", { class: "page dash-page" },
      h("div", { class: "page-inner w-1120" },
        banner, member, stats.staleBox, stats.grid, stats.locked,
        h("div", { class: "dash-charts" }, q.node, l.node),
        h("div", { class: "dash-lower" }, actCard, healthCard)));
    ctx.root.append(page);
    V = { ctx, page, refreshBtn, banner, bannerText, bannerRetry, bannerSettings, stats, charts: { q, l }, act, health, queue };

    // Vẽ ngay số của lần trước (nếu có) — không đếm lại — rồi làm mới.
    paintStats({ quiet: true });
    paintQueue();
    paintSeries();
    paintActivity();
    paintHealth();
    const failed = KEYS.some((key) => S.src[key].state === "error");
    const coreDown = CORE.every((key) => S.src[key].state === "error");
    paintSubtitle(coreDown, failed);
    paintBanner(coreDown);

    // 20 giây/lần khi đang xem (Router tự dừng nhịp khi màn đăng nhập hiện); tab hiện lại → làm mới ngay.
    ctx.every(() => { if (!document.hidden) refresh(); }, REFRESH_MS);
    ctx.on(document, "visibilitychange", () => {
      if (document.hidden || Router.paused) return;
      // Bật/tắt tab liên tục không nhân 6 yêu cầu lên mỗi lần: vừa chạy xong dưới 2 giây thì thôi.
      if (S.tick && Date.now() - S.tick < 2000) return;
      refresh();
    });
    refresh();
  }

  /* Router.go lại đúng #/dashboard (cùng hash) → làm mới, không dựng lại. */
  function update(ctx, info) {
    if (!V || V.ctx !== ctx) return false;
    if (info && info.same) refresh({ manual: true });
    return true;
  }

  function unmount() {
    V = null;
  }

  Router.register("dashboard", { admin: false, mount, update, unmount });
})();
