/* ══════════════════════════════════════════════════════════════════
   /ui/views/ocr.js — màn hình OCR (#/ocr, #/ocr?job=<id>). Chỉ quản trị viên.

   Một IIFE, không tên top-level. Gồm:
     - "Chạy OCR mới": vùng thả tệp (PDF/PNG/JPG/WEBP — đúng thứ máy chủ
       nhận), DPI 150/200/300, tên model OCR, nút Bắt đầu →
       POST /api/ocr/jobs?dpi=… (multipart "file") rồi mở job vừa tạo;
     - "Job đang chạy": tiến độ, 4 bước Tải lên/Render/OCR/Kết quả, nhật ký
       sự kiện, Hủy job / Đưa thành tài liệu / Tải kết quả (zip);
     - kết quả nhận dạng từng trang (như hộp kết quả của trang cũ, cắt ở
       6000 ký tự);
     - "Lịch sử OCR": bảng mọi lần chạy, Xem (mở vào thẻ bên phải qua
       ?job=) / Xóa (DELETE /api/ocr/history/<id>, chỉ quản trị viên).

   Hợp đồng API: research/api-admin.md §2. Vài điều của máy chủ phải nhớ:
     - mỗi lúc chỉ một job chạy; job thứ hai quay về stage "Rejected"
       (status failed) và dòng lịch sử của nó kẹt ở "queued" mãi;
     - lịch sử là ẢNH CHỤP lúc tạo và lúc kết thúc: job đang chạy đọc ra
       "queued" — nên dòng của job đang mở được phủ trạng thái sống lên;
     - job bị API khởi động lại giữa chừng nằm im ở "queued" vĩnh viễn →
       2 phút không đổi gì thì ngừng hỏi và nói thẳng (đừng hỏi mãi như
       trang cũ);
     - k/N trang tin được = pages.length/total_pages, KHÔNG phải
       current_page (current_page là số trang trong PDF, lệch khi có
       page_range).

   Gọi mạng: Shell.api (JSON, multipart) và Shell.fetchBlob (tệp zip).
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  /* ── hằng số ─────────────────────────────────────────────────── */
  const POLL_MS = 2500;            // như trang cũ (ocr.js: setTimeout 2500)
  const STUCK_MS = 120000;         // 2 phút không đổi gì → coi như job bị bỏ dở
  const FAIL_LIMIT = 4;            // số lần hỏi hỏng liên tiếp rồi mới chịu dừng
  const PREVIEW_LIMIT = 6000;      // số ký tự kết quả hiện ra (như trang cũ)
  const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp";
  const EXTENSIONS = new Set(["pdf", "png", "jpg", "jpeg", "webp"]);
  const FORMATS = "PDF, PNG, JPG, WEBP";
  const DPIS = [150, 200, 300];
  const ACTIVE = new Set(["queued", "running"]);
  const STEP_LABELS = ["Tải lên", "Render", "OCR", "Kết quả"];
  const REJECTED_TEXT = "Đang có job OCR khác chạy — chờ xong rồi thử lại.";
  /* Máy chủ chỉ chạy một job mỗi lúc: dòng ngắn hiện ra dưới nút, câu đầy đủ nằm ở title. */
  const BUSY_TEXT = "Máy chủ chỉ chạy một job OCR mỗi lúc.";
  const BUSY_TITLE = "Máy chủ chỉ chạy một job OCR mỗi lúc — chờ job bên phải xong (hoặc hủy nó) rồi bắt đầu lần mới.";
  const STUCK_TEXT = "Không thấy tiến triển trong 2 phút. Nếu API vừa khởi động lại thì job này đã bị bỏ dở và sẽ không chạy tiếp; còn tệp lớn thì bước render có thể lâu hơn thế.";

  /* status của máy chủ → nhãn + màu (pill lịch sử dùng chung bảng này). */
  const STATUS = {
    queued: { label: "đang chờ", tone: "warn" },
    running: { label: "đang chạy", tone: "warn" },
    completed: { label: "hoàn tất", tone: "ok" },
    failed: { label: "thất bại", tone: "danger" },
    cancelled: { label: "đã hủy", tone: "muted" },
  };
  /* stage của máy chủ (chuỗi tiếng Anh tự do) → bước nào trong 4 bước. */
  const STAGE_STEP = new Map([["Queued", 0], ["Reading document", 1], ["OCR inference", 2], ["Completed", 3]]);
  /* stage → chữ ngắn trong nhật ký (prototype: upload / render / ocr). */
  const STAGE_TOKEN = new Map([
    ["Queued", "queue"], ["Reading document", "render"], ["OCR inference", "ocr"], ["Completed", "done"],
    ["Failed", "error"], ["Cancelling", "cancel"], ["Cancelled", "cancel"], ["Rejected", "reject"],
  ]);
  /* Lời máy chủ (tiếng Anh, cố định trong ocr_job_service.py) → tiếng Việt.
     Lời lạ (văn bản ngoại lệ) giữ nguyên để còn lần ra lỗi thật. */
  const MESSAGES = [
    [/^File accepted$/i, () => "đã nhận tệp"],
    [/^Processing page (\d+)\/(\d+)$/i, (m) => `đang xử lý trang ${m[1]}/${m[2]}`],
    [/^All selected pages processed$/i, () => "đã xử lý xong mọi trang"],
    [/^Stopped at safe page boundary$/i, () => "đã dừng ở ranh giới trang an toàn"],
    [/^Cancellation requested$/i, () => "đã nhận yêu cầu hủy"],
    [/^Another OCR job is currently running$/i, () => "đang có job OCR khác chạy"],
    [/^Page range must be within 1-(\d+)$/i, (m) => `khoảng trang phải nằm trong 1–${m[1]}`],
  ];

  /* ── trạng thái sống qua các lần mount ───────────────────────── */
  const S = {
    dpi: 200,            // lựa chọn DPI trong phiên (trang cũ không lưu gì)
    file: null,          // tệp đang chọn
    model: null,         // {name, enabled} của models.ocr
    runs: [],            // lịch sử đã tải lần gần nhất
    runsLoaded: false,
    lastActive: null,    // job đang chạy gần nhất → quay lại #/ocr là mở lại
    beforeUpload: null,  // job đang chạy ngay trước lần gửi mới (để quay về khi bị từ chối)
    promoted: new Map(), // id job → kết quả promote (máy chủ không ghi nhớ việc này)
  };
  let V = null;          // DOM + trạng thái của lần mount đang sống

  /* ── tiện ích ────────────────────────────────────────────────── */
  const enc = (value) => encodeURIComponent(String(value));
  const isAbort = (error) => Boolean(error) && error.name === "AbortError";
  const alive = (ctx) => Boolean(V) && V.ctx === ctx && !ctx.signal.aborted;
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
  const isActive = (job) => Boolean(job) && ACTIVE.has(job.status);

  function extOf(name) {
    const text = String(name || "").toLowerCase();
    const at = text.lastIndexOf(".");
    return at >= 0 ? text.slice(at + 1) : "";
  }

  /* ocr_0db91d0db9f748d2ca1c446d15ea61d0 → ocr_0db91d (như prototype). */
  function shortId(id) {
    const match = /^(ocr_[0-9a-f]{6})[0-9a-f]{4,}$/i.exec(String(id || ""));
    return match ? match[1] : String(id || "—");
  }

  /* Số trang ĐÃ XONG / tổng. pages[] là nguồn đáng tin; dòng lịch sử không có
     pages[] nên suy từ progress (10 + 80·(i-1)/N khi đang OCR, (i-1)/N·100 khi hủy). */
  function pageCounts(job) {
    const total = Math.max(0, Math.round(Number(job && job.total_pages) || 0));
    let done;
    if (Array.isArray(job && job.pages)) done = job.pages.length;
    else if (job && job.status === "completed") done = total;
    else {
      const progress = clamp(Math.round(Number(job && job.progress) || 0), 0, 100);
      if (job && job.stage === "Cancelled") done = Math.round((progress * total) / 100);
      else if (progress >= 10 && job && job.stage !== "Queued") done = Math.round(((progress - 10) * total) / 80);
      else done = 0;
    }
    done = Math.max(0, total ? Math.min(done, total) : done);
    return { done, total };
  }

  /* "7/12", và "0/?" khi máy chủ chưa biết tổng số trang (hành vi cũ #73).
     MỘT chỗ duy nhất viết k/N: thẻ job, dòng lịch sử và ghi chú hủy đều gọi hàm này,
     nếu không thì cùng một job đọc ra hai kiểu ("0/?" ở thẻ, "—" ở bảng). */
  function pagesText(job) {
    const { done, total } = pageCounts(job);
    return `${fmtNumber(done)}/${total ? fmtNumber(total) : "?"}`;
  }

  /* "200 dpi", hoặc null khi máy chủ không trả dpi (đừng hiện "— dpi"). */
  function dpiText(value) {
    return value == null || value === "" ? null : `${fmtNumber(value)} dpi`;
  }

  /* Nhãn trạng thái: stage nói rõ hơn status ở hai chỗ (bị từ chối, đang hủy). */
  function statusOf(job) {
    const status = String((job && job.status) || "");
    const stage = String((job && job.stage) || "");
    if (stage === "Rejected") return { label: "bị từ chối", tone: "danger" };
    if (stage === "Cancelling" && ACTIVE.has(status)) return { label: "đang hủy", tone: "warn" };
    return STATUS[status] || { label: status || "không rõ", tone: "muted" };
  }

  function tileOf(job) {
    if (isActive(job)) return { tone: "accent", icon: "retry", spin: true };
    if (job.status === "completed") return { tone: "ok", icon: "check" };
    if (job.status === "failed") return { tone: "danger", icon: job.stage === "Rejected" ? "ban" : "alert" };
    if (job.status === "cancelled") return { tone: "muted", icon: "ban" };
    return { tone: "muted", icon: "ocr" };
  }

  /* Bước đang làm dở (0-3). Job hỏng/hủy: lấy theo sự kiện cuối còn "đang làm". */
  function currentStep(job) {
    if (job.status === "completed") return 3;
    if (job.stage === "Rejected") return 0;
    if (STAGE_STEP.has(job.stage) && job.stage !== "Completed") return STAGE_STEP.get(job.stage);
    if (Array.isArray(job.pages) && job.pages.length) return 2;
    const events = Array.isArray(job.events) ? job.events : [];
    for (let i = events.length - 1; i >= 0; i--) {
      const stage = events[i] && events[i].stage;
      if (stage === "OCR inference") return 2;
      if (stage === "Reading document") return 1;
    }
    return 0;
  }

  /* 4 bước: done (xong) · active/indet (đang làm, có/không đo được) · danger ·
     muted (dừng vì hủy) · pending. fill = phần đã chạy của bước đang làm. */
  function stepModel(job) {
    const step = currentStep(job);
    const { done, total } = pageCounts(job);
    const frac = total > 0 ? clamp(done / total, 0, 1) : 0;
    return STEP_LABELS.map((label, i) => {
      if (job.status === "completed" || i < step) return { label, state: "done" };
      if (i > step) return { label, state: "pending" };
      if (job.status === "failed") return { label, state: "danger" };
      if (job.status === "cancelled") return { label, state: "muted", fill: i === 2 ? frac : 1 };
      if (i === 2 && total > 0) return { label, state: "active", fill: frac };
      return { label, state: "indet" };
    });
  }

  function eventLine(event) {
    const stage = String((event && event.stage) || "");
    const raw = String((event && event.message) || "");
    const level = String((event && event.level) || "").toUpperCase();
    let text = raw;
    for (const [pattern, translate] of MESSAGES) {
      const match = pattern.exec(raw);
      if (match) { text = translate(match); break; }
    }
    const token = /^File accepted$/i.test(raw) ? "upload" : (STAGE_TOKEN.get(stage) || stage.toLowerCase() || "—");
    const cls = level === "ERROR" ? "is-error" : level === "WARNING" ? "is-warn" : null;
    // fmtClock() không tham số = bây giờ, và fmtClock(null) = 1970 → chặn cả hai.
    const at = event && event.at != null && event.at !== "" ? fmtClock(event.at) : "—";
    return h("div", { class: cls },
      h("span", { class: "t" }, at), " ",
      h("span", { class: "s" }, token), " ", text);
  }

  function lastErrorText(job) {
    const events = Array.isArray(job.events) ? job.events : [];
    for (let i = events.length - 1; i >= 0; i--) {
      const event = events[i];
      if (event && String(event.level || "").toUpperCase() === "ERROR" && event.message) return String(event.message);
    }
    return "";
  }

  /* Lời lỗi: sendJson đã dịch mã quen; vài mã của OCR chỉ có chuỗi mã trần. */
  function errText(error, fallback) {
    if (error && error.code === "INTERNAL_ERROR") return "Máy chủ gặp lỗi không mong muốn (500). Thử lại sau.";
    return (error && error.message) || fallback;
  }

  function uploadError(error) {
    const raw = String((error && error.message) || "");
    if (error && error.code === "INVALID_OCR_INPUT") {
      if (/UNSUPPORTED_OCR_FILE/i.test(raw)) return `Máy chủ không nhận định dạng này — OCR chỉ đọc ${FORMATS}.`;
      if (/EMPTY_FILE/i.test(raw)) return "Tệp rỗng — chọn tệp khác.";
      if (/INVALID_OCR_FILE_CONTENT/i.test(raw)) return "Nội dung tệp không khớp đuôi tệp (tệp hỏng hoặc bị đổi đuôi).";
    }
    return errText(error, "Không tạo được job OCR.");
  }

  function promoteError(error) {
    const raw = String((error && error.message) || "");
    if (error && error.code === "OCR_PROMOTION_NOT_AVAILABLE") {
      if (/not completed/i.test(raw)) return "Job chưa hoàn tất nên chưa đưa thành tài liệu được.";
      if (/no pages/i.test(raw)) return "Job không có trang nào để đưa thành tài liệu.";
    }
    if (error && error.code === "OCR_JOB_NOT_FOUND") return "Máy chủ không còn giữ job này (có thể API đã khởi động lại).";
    return errText(error, "Không đưa được vào pipeline tài liệu.");
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = h("a", { href: url, download: filename, style: "display:none" });
    document.body.append(link);
    link.click();
    link.remove();
    // Hẹn giờ thường (không phải ctx.after): việc dọn này phải sống lâu hơn màn hình.
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  /* ── tải dữ liệu ─────────────────────────────────────────────── */
  async function loadModel() {
    const ctx = V.ctx;
    try {
      const data = await Shell.api("/models", { signal: ctx.signal });
      const ocr = data && data.models && data.models.ocr;
      if (!alive(ctx) || !ocr) return;
      S.model = { name: String(ocr.name || ""), enabled: ocr.enabled !== false };
      renderForm();
    } catch (error) {
      // Tên model chỉ là thông tin phụ: hỏng thì để trống, không phá màn hình.
      if (!isAbort(error)) console.warn("[ocr] không đọc được /models", error);
    }
  }

  async function loadHistory() {
    if (!V) return;
    const ctx = V.ctx;
    const my = ++V.hist.seq;
    V.hist.loading = true;
    if (!S.runsLoaded) renderHistory();
    try {
      const data = await Shell.api("/api/ocr/history", { signal: ctx.signal });
      if (!alive(ctx) || my !== V.hist.seq) return;
      const runs = data && Array.isArray(data.runs) ? data.runs : [];
      S.runs = runs.filter((run) => run && typeof run === "object" && run.id);
      S.runsLoaded = true;
      V.hist.error = null;
    } catch (error) {
      if (!alive(ctx) || my !== V.hist.seq || isAbort(error)) return;
      if (S.runsLoaded) toast(errText(error, "Không tải lại được lịch sử OCR."), "danger");
      else V.hist.error = error;
    } finally {
      if (alive(ctx) && my === V.hist.seq) {
        V.hist.loading = false;
        renderHistory();
      }
    }
  }

  /* Mở một job vào thẻ bên phải (null = trạng thái rỗng). seed = dữ liệu job
     vừa nhận từ POST, để không phải chờ vòng hỏi đầu tiên. */
  function openJob(id, { seed = null } = {}) {
    if (!V) return;
    V.seq += 1;
    V.jobId = id || null;
    V.job = null;
    V.loadError = null;
    V.gone = false;
    V.pollError = null;
    V.pollStopped = false;
    V.failures = 0;
    V.stuck = false;
    V.sig = null;
    V.changedAt = Date.now();
    V.card = null;
    V.resultKey = null;
    V.polling = Boolean(id);
    V.inflight = null;
    V.busy = { cancel: false, promote: false, export: false };
    V.jobBody.replaceChildren();
    renderJobArea();
    renderResult();      // job khác = kết quả cũ phải biến mất ngay, đừng chờ vòng hỏi
    paintStart();
    renderHistory();     // bảng bỏ lớp phủ trạng thái sống của job cũ
    if (!id) return;
    if (seed && seed.id === id) applyJob(seed);
    poll();
  }

  async function poll() {
    // V.inflight giữ số thứ tự của lần hỏi đang bay: đổi job thì lần hỏi cũ
    // không chặn lần mới, và lần cũ về muộn cũng không xóa cờ của lần mới.
    if (!V || !V.jobId || V.inflight === V.seq) return;
    const ctx = V.ctx;
    const id = V.jobId;
    const my = V.seq;
    V.inflight = my;
    try {
      const job = await Shell.api(`/api/ocr/jobs/${enc(id)}`, { signal: ctx.signal });
      if (!alive(ctx) || my !== V.seq) return;
      V.failures = 0;
      V.pollError = null;
      V.pollStopped = false;
      V.gone = false;
      applyJob(job);
    } catch (error) {
      if (!alive(ctx) || my !== V.seq || isAbort(error)) return;
      if (!V.job) {
        V.loadError = error;
        V.polling = false;
        // Máy chủ nói job không còn: đừng ghim nó làm "job đang chạy gần nhất" nữa,
        // nếu không mỗi lần quay lại #/ocr lại tự mở lại một job đã chết.
        if (error.status === 404 && S.lastActive === id) S.lastActive = null;
        renderJobArea();
        return;
      }
      V.pollError = error;
      if (error.status === 404) {
        V.gone = true;
        V.polling = false;
        if (S.lastActive === id) S.lastActive = null;
      } else {
        V.failures += 1;
        if (V.failures >= FAIL_LIMIT) {
          V.polling = false;
          V.pollStopped = true;
        }
      }
      paintNotes();
      paintActions();   // job biến mất giữa chừng: các nút cần nó phải tắt theo
      paintStart();
    } finally {
      if (V && V.inflight === my) V.inflight = null;
    }
  }

  /* Nhận một bản job mới (từ vòng hỏi, từ POST tạo job hoặc từ hủy job). */
  function applyJob(job) {
    if (!V || !job || !job.id) return;
    if (V.jobId && job.id !== V.jobId) return;
    const previous = V.job;
    V.jobId = job.id;
    V.job = job;
    V.loadError = null;

    const signature = JSON.stringify([job.status, job.stage, job.progress,
      (job.events || []).length, (job.pages || []).length, job.total_pages, job.current_page]);
    const now = Date.now();
    if (signature !== V.sig) {
      V.sig = signature;
      V.changedAt = now;
      V.stuck = false;
    } else if (isActive(job) && now - V.changedAt >= STUCK_MS) {
      V.stuck = true;
    }
    V.polling = isActive(job) && !V.stuck;

    if (isActive(job)) {
      S.lastActive = job.id;
    } else {
      if (S.lastActive === job.id) S.lastActive = null;
      // Job mới bị từ chối vì job cũ còn chạy: giữ lối quay lại job cũ.
      if (job.stage === "Rejected" && S.beforeUpload && S.beforeUpload !== job.id) S.lastActive = S.beforeUpload;
    }

    renderJobArea();
    renderResult();
    paintStart();       // job đang chạy = nút "Bắt đầu OCR" phải khóa theo
    updateLiveRow();
    // Job vừa kết thúc: ảnh chụp trong lịch sử mới được ghi lúc này.
    if (previous && isActive(previous) && !isActive(job)) loadHistory();
  }

  /* ── vùng "Job đang chạy" ────────────────────────────────────── */
  function renderJobArea() {
    if (!V) return;
    const box = V.jobBody;
    V.jobSection.classList.toggle("is-empty", !V.job);
    if (!V.jobId) {
      V.card = null;
      box.replaceChildren(emptyState({
        icon: "ocr",
        title: "Chưa mở job nào",
        text: "Chọn tệp bên trái rồi bấm «Bắt đầu OCR», hoặc bấm «Xem» ở lịch sử để mở lại một lần chạy.",
      }));
      return;
    }
    if (!V.job) {
      V.card = null;
      if (V.loadError) {
        const missing = V.loadError.status === 404;
        box.replaceChildren(missing
          ? emptyState({
            icon: "ban", tone: "danger", title: "Không tìm thấy job này",
            text: `Job ${shortId(V.jobId)} không còn trên máy chủ — có thể đã bị xóa khỏi lịch sử.`,
            action: {
              label: "Đóng", icon: "x",
              onClick: () => { S.lastActive = null; Router.go("#/ocr"); },
            },
          })
          : errorState({ message: errText(V.loadError, "Không tải được job này.") }, () => openJob(V.jobId)));
      } else {
        box.replaceChildren(h("div", { class: "ocr-job-loading", "aria-busy": "true" },
          h("div", { class: "ocr-job-head" },
            skeleton({ w: 34, h: 34, r: 10 }),
            h("div", { class: "ocr-job-main" }, skeleton({ w: "58%", h: 14 }), skeleton({ w: "38%", h: 12 }))),
          skeleton({ w: "100%", h: 8, r: 4 }),
          skeleton({ w: "100%", h: 96, r: 10 })));
      }
      return;
    }
    if (!V.card) {
      V.card = buildJobCard();
      box.replaceChildren(...V.card.nodes);
    }
    paintJob();
  }

  function buildJobCard() {
    const card = {};
    card.tile = h("span", { class: "icon-tile icon-tile-34 tone-accent" });
    card.name = h("div", { class: "ocr-job-name" });
    card.meta = h("div", { class: "ocr-job-meta" });
    card.pct = h("span", { class: "ocr-job-pct" });
    card.fill = h("div", { class: "fill" });
    card.fill.addEventListener("animationend", () => card.fill.classList.add("is-settled"), { once: true });
    // KHÔNG dùng lớp .brand của primitive .progress-8.brand: .brand trong styles.css
    // cũng là khối thương hiệu ở thanh bên (padding 16px 16px 12px) nên thanh 8px bị
    // đẩy cao 28px và ruột thành 0. Nền gradient + animation nằm ở views/ocr.css.
    card.bar = h("div", {
      class: "progress progress-8 ocr-bar", role: "progressbar",
      "aria-label": "Tiến độ OCR", "aria-valuemin": "0", "aria-valuemax": "100",
    }, card.fill);
    card.steps = STEP_LABELS.map((label) => {
      const bar = h("div", { class: "stage-bar" });
      const text = h("div", { class: "ocr-step-label" }, label);
      return { el: h("div", { class: "ocr-step" }, bar, text) };
    });
    card.caret = h("div", { class: "ocr-caret-line" }, h("span", { class: "caret" }));
    card.log = h("div", {
      class: "log ocr-log", tabindex: "0", role: "log", "aria-label": "Nhật ký job OCR",
    }, card.caret);
    card.logCount = 0;
    card.notes = h("div", { class: "ocr-notes", hidden: true });
    card.cancel = h("button", { type: "button", class: "btn btn-32 btn-outline-danger", onClick: cancelJob }, "Hủy job");
    card.promote = h("button", { type: "button", class: "btn btn-32 btn-outline", onClick: promoteJob }, "Đưa thành tài liệu");
    card.export = h("button", { type: "button", class: "btn btn-32 btn-outline", onClick: exportZip }, "Tải kết quả (zip)");
    card.nodes = [
      h("div", { class: "ocr-job-head" }, card.tile, h("div", { class: "ocr-job-main" }, card.name, card.meta), card.pct),
      card.bar,
      // Dải 4 bước chỉ vẽ lại điều thanh tiến độ đã nói (aria-valuetext mang cả tên
      // bước): để nguyên thì trình đọc màn hình đọc "Tải lên Render OCR Kết quả" trống rỗng.
      h("div", { class: "ocr-steps", "aria-hidden": "true" }, card.steps.map((step) => step.el)),
      card.log,
      card.notes,
      h("div", { class: "ocr-actions" }, card.cancel, h("span", { class: "spacer" }), card.promote, card.export),
    ];
    return card;
  }

  function paintJob() {
    const job = V.job;
    const card = V.card;
    const tile = tileOf(job);
    const tileKey = `${tile.tone}:${tile.icon}:${tile.spin ? 1 : 0}`;
    card.tile.className = `icon-tile icon-tile-34 tone-${tile.tone}`;
    if (card.tileKey !== tileKey) {
      card.tileKey = tileKey;
      card.tile.replaceChildren(icon(tile.icon, { size: 16, cls: tile.spin ? "ocr-spin" : null }));
    }
    const name = job.filename || job.id;
    card.name.textContent = name;
    card.name.title = name;
    const status = statusOf(job);
    card.meta.textContent = `job ${shortId(job.id)} · ${status.label} · trang ${pagesText(job)}`;
    card.meta.title = [`job ${job.id}`, dpiText(job.dpi)].filter(Boolean).join(" · ");
    const percent = clamp(Math.round(Number(job.progress) || 0), 0, 100);
    card.pct.textContent = `${percent}%`;
    card.pct.className = `ocr-job-pct is-${job.status === "completed" ? "ok" : job.status === "failed" ? "danger" : job.status === "cancelled" ? "muted" : "accent"}`;
    card.fill.style.width = `${percent}%`;
    card.bar.setAttribute("aria-valuenow", String(percent));
    card.bar.setAttribute("aria-valuetext",
      `${percent}% · ${status.label} · bước ${STEP_LABELS[currentStep(job)]} · trang ${pagesText(job)}`);
    card.bar.classList.toggle("is-danger", job.status === "failed");
    card.bar.classList.toggle("is-muted", job.status === "cancelled");

    stepModel(job).forEach((model, i) => {
      const step = V.card.steps[i].el;
      step.className = `ocr-step is-${model.state}`;
      if (model.fill == null) step.style.removeProperty("--fill");
      else step.style.setProperty("--fill", `${Math.round(model.fill * 100)}%`);
    });

    paintLog(job);
    paintNotes();
    paintActions();
  }

  function paintLog(job) {
    const card = V.card;
    const events = Array.isArray(job.events) ? job.events : [];
    const box = card.log;
    // Chỉ bám đáy khi job còn chạy (còn dòng mới để đuổi theo). Job đã xong/hỏng/hủy
    // mở ra ở đầu nhật ký như prototype, thay vì cắt ngang dòng đầu ở mép hộp.
    const stick = isActive(job) && (card.logCount === 0 || box.scrollHeight - box.scrollTop - box.clientHeight < 12);
    if (events.length < card.logCount) {
      // Danh sách ngắn lại (job khác được nạp vào cùng thẻ): dựng lại từ đầu.
      box.replaceChildren(card.caret);
      card.logCount = 0;
    }
    for (let i = card.logCount; i < events.length; i++) box.insertBefore(eventLine(events[i]), card.caret);
    card.logCount = events.length;
    if (!events.length && !card.empty) {
      card.empty = h("div", { class: "ocr-log-empty" }, "Chưa có sự kiện nào.");
      box.insertBefore(card.empty, card.caret);
    }
    if (events.length && card.empty) {
      card.empty.remove();
      card.empty = null;
    }
    card.caret.hidden = !isActive(job);
    if (stick) box.scrollTop = box.scrollHeight;
  }

  function noteNode({ tone = "muted", icon: iconName, text, action, link, role }) {
    return h("div", { class: `note tone-${tone} ocr-note`, role },
      iconName ? icon(iconName, { size: 14 }) : null,
      h("span", { class: "ocr-note-text" }, text),
      action ? h("button", { type: "button", class: "btn-link ocr-note-act", onClick: action.onClick }, action.label) : null,
      link ? h("a", { class: "ocr-note-act", href: link.href }, link.label) : null);
  }

  function paintNotes() {
    if (!V || !V.card || !V.job) return;
    const job = V.job;
    const notes = [];
    if (job.stage === "Rejected") {
      const back = S.lastActive && S.lastActive !== job.id ? S.lastActive : null;
      notes.push({
        tone: "danger", icon: "ban", text: REJECTED_TEXT, role: "alert",
        action: back ? { label: "Mở job đang chạy", onClick: () => Router.go(`#/ocr?job=${enc(back)}`) } : null,
      });
    } else if (job.status === "failed") {
      // Lý do là lời máy chủ (thường tiếng Anh, là văn bản ngoại lệ): để trong ngoặc
      // kép và nói rõ ai đang nói, đừng ghép thẳng vào câu tiếng Việt.
      const why = lastErrorText(job);
      notes.push({ tone: "danger", icon: "alert", role: "alert", text: why ? `OCR thất bại — máy chủ báo: «${why}»` : "OCR thất bại — máy chủ không ghi lý do." });
    } else if (job.status === "cancelled") {
      notes.push({ tone: "muted", icon: "ban", text: `Đã hủy theo yêu cầu — ${pagesText(job)} trang đã nhận dạng vẫn nằm trên máy chủ.` });
    }
    if (V.stuck && isActive(job)) {
      notes.push({ tone: "warn", icon: "clock", role: "status", text: STUCK_TEXT, action: { label: "Theo dõi tiếp", onClick: resumeWatch } });
    }
    if (V.gone) {
      notes.push({ tone: "warn", icon: "alert", role: "alert", text: "Máy chủ không còn giữ job này (404) — có thể nó vừa bị xóa khỏi lịch sử." });
    } else if (V.pollError) {
      notes.push({
        tone: "warn", icon: "alert", text: `Không cập nhật được trạng thái: ${errText(V.pollError, "máy chủ không trả lời.")}`,
        // Đã ngừng hỏi = màn hình đứng im: phải báo ngay ("alert"), không chờ lượt đọc.
        role: V.pollStopped ? "alert" : "status",
        action: V.pollStopped ? { label: "Thử lại", onClick: resumeWatch } : null,
      });
    }
    const promoted = S.promoted.get(job.id);
    if (promoted) {
      notes.push({
        tone: "ok", icon: "check",
        text: promoted.duplicate ? "Tài liệu này đã có trong thư viện." : "Đã gửi vào pipeline tài liệu.",
        link: promoted.document_id ? { label: "Mở trong Tài liệu →", href: `#/documents?doc=${enc(promoted.document_id)}` } : null,
      });
    }
    V.card.notes.replaceChildren(...notes.map(noteNode));
    V.card.notes.hidden = notes.length === 0;
  }

  function paintActions() {
    if (!V || !V.card || !V.job) return;
    const job = V.job;
    const card = V.card;
    // V.gone = máy chủ trả 404 giữa chừng: cả ba nút đều cần job đó, tắt hết.
    const cancellable = isActive(job) && job.stage !== "Cancelling" && !V.gone;
    card.cancel.disabled = !cancellable || V.busy.cancel;
    card.cancel.textContent = V.busy.cancel || job.stage === "Cancelling" ? "Đang hủy…" : "Hủy job";
    const pages = Array.isArray(job.pages) ? job.pages.length : 0;
    const completed = job.status === "completed" && !V.gone;
    card.promote.disabled = !completed || !pages || V.busy.promote;
    card.promote.textContent = V.busy.promote ? "Đang gửi…" : "Đưa thành tài liệu";
    if (completed && !pages) card.promote.title = "Job không có trang nào để đưa thành tài liệu.";
    else card.promote.removeAttribute("title");
    card.export.disabled = !completed || V.busy.export;
    card.export.textContent = V.busy.export ? "Đang tải…" : "Tải kết quả (zip)";
  }

  function resumeWatch() {
    if (!V || !V.jobId) return;
    V.stuck = false;
    V.gone = false;
    V.pollError = null;
    V.pollStopped = false;
    V.failures = 0;
    V.changedAt = Date.now();
    V.polling = true;
    if (V.card && V.job) paintNotes();
    paintStart();
    poll();
  }

  /* ── hành động trên job ──────────────────────────────────────── */
  async function cancelJob() {
    if (!V || !V.job || V.busy.cancel) return;
    const ctx = V.ctx;
    const id = V.job.id;
    V.busy.cancel = true;
    paintActions();
    try {
      const job = await Shell.api(`/api/ocr/jobs/${enc(id)}/cancel`, { method: "POST", signal: ctx.signal });
      if (!alive(ctx)) return;
      toast("Đã yêu cầu hủy — job dừng ở ranh giới trang kế tiếp.");
      if (V.jobId === id) applyJob(job);
    } catch (error) {
      if (!alive(ctx) || isAbort(error)) return;
      toast(error.status === 404
        ? "Máy chủ không còn giữ job này nên không hủy được (có thể API đã khởi động lại)."
        : errText(error, "Không hủy được job."), "danger");
    } finally {
      if (alive(ctx)) {
        V.busy.cancel = false;
        if (V.card && V.job) paintActions();
      }
    }
  }

  async function promoteJob() {
    if (!V || !V.job || V.busy.promote) return;
    const ctx = V.ctx;
    const id = V.job.id;
    V.busy.promote = true;
    paintActions();
    try {
      const result = await Shell.api(`/api/ocr/jobs/${enc(id)}/promote`, { method: "POST", signal: ctx.signal });
      if (!alive(ctx)) return;
      const duplicate = Boolean(result && result.duplicate);
      S.promoted.set(id, { duplicate, document_id: result && result.document_id });
      toast(duplicate ? "Tài liệu này đã có trong thư viện" : "Đã gửi vào pipeline tài liệu");
      if (V.card && V.job) paintNotes();
    } catch (error) {
      if (!alive(ctx) || isAbort(error)) return;
      toast(promoteError(error), "danger");
    } finally {
      if (alive(ctx)) {
        V.busy.promote = false;
        if (V.card && V.job) paintActions();
      }
    }
  }

  async function exportZip() {
    if (!V || !V.job || V.busy.export) return;
    const ctx = V.ctx;
    const id = V.job.id;
    V.busy.export = true;
    paintActions();
    try {
      // Không gắn ctx.signal: rời màn hình giữa chừng thì tệp vẫn nên tải xong.
      const blob = await Shell.fetchBlob(`/api/ocr/jobs/${enc(id)}/export`);
      saveBlob(blob, `${id}.zip`);
    } catch (error) {
      if (isAbort(error)) return;
      toast(error && error.status === 404
        ? "Máy chủ không còn giữ job này nên chưa đóng gói được (mở lại job rồi thử tiếp)."
        : errText(error, "Không tải được tệp zip."), "danger");
    } finally {
      if (alive(ctx)) {
        V.busy.export = false;
        if (V.card && V.job) paintActions();
      }
    }
  }

  /* ── kết quả nhận dạng (hộp kết quả của trang cũ) ────────────── */
  function renderResult() {
    if (!V) return;
    const job = V.job;
    const pages = job && job.status === "completed" && Array.isArray(job.pages) ? job.pages : [];
    if (!pages.length) {
      V.result.hidden = true;
      V.result.replaceChildren();
      V.resultKey = null;
      return;
    }
    const key = `${job.id}:${pages.length}`;
    if (V.resultKey === key) return;
    V.resultKey = key;

    const full = pages.map((page) => `── Trang ${page.page} ──\n${String(page.text ?? "")}`).join("\n\n");
    let budget = PREVIEW_LIMIT;
    let cut = false;
    const blocks = [];
    for (const page of pages) {
      if (budget <= 0) { cut = true; break; }
      let text = String(page.text ?? "");
      if (text.length > budget) {
        text = text.slice(0, budget);
        cut = true;
      }
      budget -= text.length;
      const duration = page.duration_seconds == null ? NaN : Number(page.duration_seconds);
      const meta = [Number.isFinite(duration) ? fmtDuration(duration * 1000) : null, page.cache_hit ? "lấy từ bộ nhớ đệm" : null]
        .filter(Boolean).join(" · ");
      blocks.push(h("div", { class: "ocr-page" },
        h("div", { class: "ocr-page-head" },
          h("span", { class: "section-label" }, `Trang ${page.page ?? "?"}`),
          meta ? h("span", { class: "ocr-page-meta" }, meta) : null),
        text
          ? h("div", { class: "ocr-page-text" }, text)
          : h("div", { class: "ocr-page-text is-blank" }, "(trang này không có chữ nào)")));
      if (cut) break;
    }
    if (cut) blocks.push(h("p", { class: "ocr-result-cut" }, "…(đã cắt bớt) — bản đầy đủ nằm trong tệp zip."));

    const total = job.timings && job.timings.total_seconds;
    const seconds = total == null ? NaN : Number(total);
    const meta = [`${fmtNumber(pages.length)} trang`, dpiText(job.dpi),
      Number.isFinite(seconds) ? fmtDuration(seconds * 1000) : null, job.model || null].filter(Boolean).join(" · ");
    V.result.replaceChildren(
      h("div", { class: "card-head ocr-result-head" },
        h("h2", { class: "card-title" }, "Kết quả nhận dạng"),
        h("span", { class: "card-meta" }, meta),
        h("button", {
          type: "button", class: "btn btn-28 btn-outline hover-bg", onClick: () => copyText(full),
        }, icon("copy", { size: 13, sw: 1.9 }), "Sao chép")),
      h("div", { class: "ocr-result-body" }, blocks));
    V.result.hidden = false;
  }

  /* ── form "Chạy OCR mới" ─────────────────────────────────────── */
  /* Vùng nhắn tin dưới nút Bắt đầu. Giữ NGUYÊN role="status" (đổi role giữa chừng
     thì trình đọc màn hình dựng lại vùng sống và bỏ qua nội dung mới); mức khẩn cấp
     đổi bằng aria-live, và phải hiện vùng ra TRƯỚC khi ghi chữ mới có tiếng đọc. */
  function setMessage(text, kind) {
    if (!V) return;
    const el = V.form.msg;
    el.className = `ocr-msg${kind === "error" ? " is-error" : ""}`;
    el.setAttribute("aria-live", kind === "error" ? "assertive" : "polite");
    el.hidden = !text;
    el.textContent = text || "";
  }

  /* Tệp vừa chọn bị loại: tệp CŨ vẫn còn đó, phải nói ra — nếu không màn hình vừa
     báo đỏ "không hỗ trợ" vừa để nút Bắt đầu sáng cho một tệp khác. */
  function rejectPick(reason) {
    setMessage(S.file ? `${reason} Vẫn đang chọn «${S.file.name}».` : reason, "error");
  }

  function pickFile(list) {
    const files = list ? [...list] : [];
    if (!files.length) return;
    const file = files[0];
    if (!EXTENSIONS.has(extOf(file.name))) {
      rejectPick(`Tệp «${file.name}» không được hỗ trợ — OCR chỉ nhận ${FORMATS}.`);
      return;
    }
    if (!file.size) {
      rejectPick(`Tệp «${file.name}» rỗng — chọn tệp khác.`);
      return;
    }
    S.file = file;
    setMessage(files.length > 1 ? `Mỗi lần chỉ nhận dạng được một tệp — đã lấy «${file.name}».` : "");
    renderForm();
  }

  function renderForm() {
    if (!V) return;
    const form = V.form;
    const file = S.file;
    form.zone.classList.toggle("has-file", Boolean(file));
    form.zone.replaceChildren(...(file
      ? [
        typeBadge(file.name, 34),
        h("strong", { class: "ocr-drop-name" }, file.name),
        h("span", { class: "hint" }, `${fmtBytes(file.size)} · bấm hoặc thả tệp khác để đổi`),
      ]
      : [
        icon("ocr", { size: 26, sw: 1.8 }),
        h("span", null, h("strong", null, "Thả PDF hoặc ảnh"), " để nhận dạng"),
        h("span", { class: "hint" }, FORMATS),
      ]));
    form.zone.setAttribute("aria-label", file
      ? `Đã chọn ${file.name} (${fmtBytes(file.size)}). Bấm để chọn tệp khác.`
      : `Chọn tệp để nhận dạng: ${FORMATS}`);
    form.model.textContent = S.model && S.model.name
      ? `model ${S.model.name}${S.model.enabled === false ? " (tắt)" : ""}`
      : "";
    paintStart();
  }

  /* Chỉ nút Bắt đầu + dòng nhắc của nó. Tách khỏi renderForm() vì trạng thái này đổi
     theo mỗi vòng hỏi job, mà renderForm() dựng lại cả vùng thả tệp (mất focus). */
  function paintStart() {
    if (!V) return;
    const form = V.form;
    // Máy chủ chỉ chạy một job mỗi lúc: bấm thêm không xếp hàng mà bị từ chối, và
    // dòng lịch sử của lần bị từ chối kẹt ở "đang chờ" vĩnh viễn (api-admin §2.3).
    // Job kẹt 2 phút hoặc đã 404: chỗ chạy coi như trống lại — đừng khóa nút vĩnh viễn.
    const busy = isActive(V.job) && !V.stuck && !V.gone;
    form.start.disabled = !S.file || V.uploading || busy;
    form.start.textContent = V.uploading ? "Đang tải lên…" : "Bắt đầu OCR";
    const title = busy ? BUSY_TITLE : !S.file ? "Chọn một tệp PDF hoặc ảnh trước." : "";
    if (title) form.start.title = title;
    else form.start.removeAttribute("title");
    // Chuột mới thấy title: lý do đang khóa nút phải hiện thành chữ — nhưng chỉ khi đã
    // chọn tệp, tức là lúc người dùng thật sự định bấm. Chưa chọn tệp thì đó là tin thừa.
    const explain = busy && Boolean(S.file);
    form.hint.textContent = explain ? BUSY_TEXT : "";
    form.hint.hidden = !explain;
  }

  async function startJob() {
    if (!V || !S.file || V.uploading) return;
    const ctx = V.ctx;
    const file = S.file;
    const dpi = S.dpi;
    V.uploading = true;
    setMessage("");
    renderForm();
    S.beforeUpload = isActive(V.job) ? V.job.id : S.lastActive;
    try {
      const body = new FormData();
      body.append("file", file, file.name);
      // KHÔNG gắn ctx.signal: rời màn hình giữa chừng mà máy chủ đã nhận tệp thì job
      // vẫn chạy — hủy request chỉ làm mất id, và lần sau người dùng chỉ thấy "bị từ chối".
      const job = await Shell.api(`/api/ocr/jobs?dpi=${enc(dpi)}`, { method: "POST", body });
      if (job && job.id && isActive(job)) S.lastActive = job.id;   // giữ lối quay lại, kể cả khi đã rời màn hình
      if (!alive(ctx)) return;
      if (job && job.id) {
        V.seed = job;
        Router.go(`#/ocr?job=${enc(job.id)}`);
        loadHistory();
      }
    } catch (error) {
      if (!alive(ctx) || isAbort(error)) return;
      setMessage(uploadError(error), "error");
    } finally {
      if (alive(ctx)) {
        V.uploading = false;
        renderForm();
      }
    }
  }

  /* ── lịch sử ─────────────────────────────────────────────────── */
  function viewRun(run) {
    Router.go(`#/ocr?job=${enc(run.id)}`);
    if (!V) return;
    const box = V.jobSection.getBoundingClientRect();
    if (box.top < 0 || box.bottom > window.innerHeight) {
      V.jobSection.scrollIntoView({ block: "nearest", behavior: Shell.motionOn() ? "smooth" : "auto" });
    }
  }

  async function removeRun(run, button) {
    if (!V || V.deleting.has(run.id)) return;
    const ctx = V.ctx;
    const shown = liveOverlay(run);
    const name = run.filename || run.id;
    const risky = ACTIVE.has(shown.status);
    const ok = await confirmDialog({
      title: "Xóa lần chạy OCR?",
      body: `«${name}» cùng ảnh trang và văn bản đã nhận dạng sẽ bị xóa khỏi máy chủ, không hoàn tác được.${risky
        ? " Job này đang ở trạng thái chưa xong: nếu nó thật sự còn chạy, xóa KHÔNG dừng được nó — job sẽ quay lại lịch sử với trạng thái thất bại. Hãy hủy job trước."
        : ""}`,
      confirmLabel: "Xóa",
      signal: ctx.signal,
    });
    if (!ok || !alive(ctx)) return;
    V.deleting.add(run.id);
    if (button && button.isConnected) button.disabled = true;
    try {
      await Shell.api(`/api/ocr/history/${enc(run.id)}`, { method: "DELETE", signal: ctx.signal });
      if (!alive(ctx)) return;
      toast("Đã xóa lần chạy OCR.");
      if (S.lastActive === run.id) S.lastActive = null;
      S.promoted.delete(run.id);
      if (V.jobId === run.id) Router.go("#/ocr");
    } catch (error) {
      if (!alive(ctx) || isAbort(error)) return;
      toast(errText(error, "Không xóa được lần chạy này."), "danger");
    } finally {
      if (alive(ctx)) {
        V.deleting.delete(run.id);
        loadHistory();
      }
    }
  }

  /* Dòng lịch sử của job đang mở được phủ trạng thái sống (lịch sử chỉ là ảnh
     chụp lúc tạo/lúc xong: job đang chạy đọc ra "queued"). */
  function liveOverlay(run) {
    const job = V && V.job;
    if (!job || job.id !== run.id) return run;
    return {
      ...run,
      status: job.status, stage: job.stage, progress: job.progress,
      current_page: job.current_page, total_pages: job.total_pages, pages: job.pages,
    };
  }

  function historyRow(run) {
    const name = run.filename || run.id;
    const time = run.created_at;
    const total = run.timings && run.timings.total_seconds;
    const seconds = total == null ? NaN : Number(total);
    const title = [time == null ? null : fmtDate(time, { time: true }), dpiText(run.dpi),
      Number.isFinite(seconds) ? `chạy ${fmtDuration(seconds * 1000)}` : null].filter(Boolean).join(" · ");
    const view = h("button", {
      type: "button", class: "btn btn-28 btn-outline hover-bg", "aria-label": `Xem ${name}`,
      dataset: { run: run.id, act: "view" }, onClick: () => viewRun(run),
    }, "Xem");
    const remove = Shell.isAdmin()
      ? h("button", {
        type: "button", class: "btn btn-28 btn-ghost-quiet", "aria-label": `Xóa ${name}`,
        dataset: { run: run.id, act: "remove" },
        onClick: (event) => removeRun(run, event.currentTarget),
      }, "Xóa")
      : null;
    const statusTd = h("td");
    const pagesTd = h("td", { class: "ocr-td-pages" });
    const rec = {
      run,
      statusTd,
      pagesTd,
      remove,
      tr: h("tr", null,
        h("td", { class: "ocr-td-file" }, h("span", { class: "ocr-file-name", title: name }, name)),
        statusTd, pagesTd,
        h("td", { class: "ocr-td-model" }, run.model || "—"),
        h("td", { class: "ocr-td-time", title }, fmtRelative(time)),
        h("td", { class: "ocr-td-act" }, view, " ", remove)),
    };
    paintRow(rec);
    return rec;
  }

  /* Cột trạng thái / trang / nút Xóa của một dòng — vẽ tại chỗ để nút đang được
     focus không bị thay mất mỗi vòng hỏi 2,5 giây. */
  function paintRow(rec) {
    const shown = liveOverlay(rec.run);
    const status = statusOf(shown);
    rec.statusTd.replaceChildren(pill(status.label, status.tone));
    rec.pagesTd.textContent = pagesText(shown);
    if (!rec.remove) return;
    const live = V.job && V.job.id === rec.run.id && isActive(V.job);
    rec.remove.disabled = Boolean(live) || V.deleting.has(rec.run.id);
    if (live) rec.remove.title = "Job đang chạy — hủy job trước rồi mới xóa.";
    else rec.remove.removeAttribute("title");
  }

  function renderHistory() {
    if (!V) return;
    const body = V.hist.body;
    V.hist.meta.textContent = S.runsLoaded ? `${fmtNumber(S.runs.length)} lần chạy` : "";
    V.hist.rows = new Map();
    if (!S.runsLoaded) {
      body.replaceChildren(V.hist.error
        ? errorState({ message: errText(V.hist.error, "Không tải được lịch sử OCR.") }, () => loadHistory())
        : h("div", { class: "ocr-hist-loading", "aria-busy": "true" },
          skeleton({ w: "100%", h: 16 }), skeleton({ w: "100%", h: 16 }), skeleton({ w: "100%", h: 16 })));
      return;
    }
    if (!S.runs.length) {
      body.replaceChildren(emptyState({
        icon: "ocr", title: "Chưa có lần chạy nào.",
        text: "Mỗi lần nhận dạng sẽ được lưu ở đây cùng ảnh trang và văn bản kết quả.",
      }));
      return;
    }
    // Giữ lại focus của bàn phím khi bảng được dựng lại (làm mới sau mỗi job).
    const focused = document.activeElement;
    const keep = focused && focused.dataset && focused.dataset.run ? { run: focused.dataset.run, act: focused.dataset.act } : null;
    const rows = S.runs.map((run) => {
      const rec = historyRow(run);
      V.hist.rows.set(run.id, rec);
      return rec.tr;
    });
    body.replaceChildren(h("div", { class: "ocr-hist-wrap" },
      h("table", { class: "table table-inset table-roomy table-head-10 ocr-hist" },
        h("thead", null, h("tr", null,
          h("th", { scope: "col" }, "Tệp"),
          h("th", { scope: "col" }, "Trạng thái"),
          h("th", { scope: "col" }, "Trang"),
          h("th", { scope: "col" }, "Model"),
          h("th", { scope: "col" }, "Thời gian"),
          h("th", { scope: "col" }, h("span", { class: "sr-only" }, "Hành động")))),
        h("tbody", null, rows))));
    if (keep) {
      const again = body.querySelector(`[data-run="${CSS.escape(keep.run)}"][data-act="${keep.act}"]`);
      if (again && !again.disabled) again.focus({ preventScroll: true });
    }
  }

  /* Chỉ vẽ lại dòng của job đang mở (đừng dựng lại cả bảng mỗi 2,5 giây). */
  function updateLiveRow() {
    if (!V || !V.job || !V.hist.rows) return;
    const rec = V.hist.rows.get(V.job.id);
    if (rec && rec.tr.isConnected) paintRow(rec);
  }

  /* ── vòng đời ────────────────────────────────────────────────── */

  /* Job nào phải nằm trong thẻ bên phải cho hash hiện tại. #/ocr trống trong khi vẫn
     còn một job đang chạy = mở lại job đó (S.lastActive chỉ sống khi job còn chạy;
     job xong, bị xóa hay 404 thì nó đã bị xóa). MỘT quy tắc cho cả mount lẫn update:
     trước đây bấm mục "OCR" ở thanh bên thì job biến mất, còn đi vòng qua màn hình
     khác rồi quay lại thì nó hiện ra — cùng một địa chỉ, hai kết quả. */
  function wantedJob(ctx) {
    const id = ctx.query.get("job") || null;
    if (id || !S.lastActive) return id;
    Router.replace(`#/ocr?job=${enc(S.lastActive)}`, { silent: true });
    return S.lastActive;
  }

  function tick() {
    if (!V || !V.jobId || !V.polling || document.hidden) return;
    poll();
  }

  function mount(ctx) {
    ctx.setHeader("OCR Console", "Nhận dạng chữ trong PDF/ảnh rồi đưa thành tài liệu");

    const jobId = wantedJob(ctx);

    const fileInput = h("input", {
      type: "file", accept: ACCEPT, hidden: true, tabindex: "-1", "aria-hidden": "true",
      onChange: (event) => { pickFile(event.target.files); event.target.value = ""; },
    });
    const zone = h("div", { class: "dropzone dropzone-lg ocr-drop", role: "button", tabindex: "0" });
    zone.addEventListener("click", () => fileInput.click());
    zone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        fileInput.click();
      }
    });
    for (const type of ["dragenter", "dragover"]) {
      zone.addEventListener(type, (event) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        zone.classList.add("is-drag");
      });
    }
    zone.addEventListener("dragleave", (event) => {
      if (!zone.contains(event.relatedTarget)) zone.classList.remove("is-drag");
    });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("is-drag");
      pickFile(event.dataTransfer && event.dataTransfer.files);
    });

    const dpiSeg = segmented(DPIS.map((value) => ({ value, label: String(value) })), S.dpi,
      (value) => { S.dpi = Number(value); }, { size: "sm", label: "Độ phân giải quét (DPI)" });
    const model = h("span", { class: "ocr-model" });
    const start = h("button", { type: "button", class: "btn btn-38 btn-primary btn-glow btn-block", onClick: startJob }, "Bắt đầu OCR");
    const hint = h("p", { class: "ocr-msg ocr-hint", hidden: true });
    const msg = h("p", { class: "ocr-msg", role: "status", "aria-live": "polite", hidden: true });
    const newPanel = h("section", { class: "card card-p18 ocr-panel" },
      h("h2", { class: "card-title" }, "Chạy OCR mới"),
      zone, fileInput,
      h("div", { class: "ocr-dpi" }, h("span", { class: "ocr-dpi-label" }, "DPI"), dpiSeg, model),
      start, hint, msg);

    const jobBody = h("div", { class: "ocr-job-body" });
    const jobSection = h("section", { class: "card card-p18 ocr-job", "aria-label": "Job OCR đang mở" }, jobBody);

    const histMeta = h("span", { class: "card-meta" });
    const histBody = h("div", { class: "ocr-hist-body" });
    const history = h("section", { class: "card card-flush ocr-hist-card" },
      h("div", { class: "card-head" }, h("h2", { class: "card-title" }, "Lịch sử OCR"), histMeta),
      histBody);

    const result = h("section", { class: "card card-flush ocr-result", hidden: true });

    const page = h("div", { class: "page" },
      h("div", { class: "page-inner w-1080" },
        h("div", { class: "ocr-grid" }, newPanel, jobSection),
        result, history));
    ctx.root.append(page);

    V = {
      ctx, page, jobSection, jobBody, result, resultKey: null,
      form: { zone, fileInput, model, start, hint, msg },
      hist: { body: histBody, meta: histMeta, rows: new Map(), seq: 0, loading: false, error: null },
      deleting: new Set(),
      busy: { cancel: false, promote: false, export: false },
      uploading: false, seed: null, card: null,
      jobId: null, job: null, seq: 0, inflight: false, polling: false,
      failures: 0, pollError: null, pollStopped: false, gone: false, loadError: null,
      stuck: false, sig: null, changedAt: Date.now(),
    };

    // Thả tệp ra ngoài vùng thả: trình duyệt sẽ mở tệp đó thay cho ứng dụng → chặn.
    ctx.on(window, "dragover", (event) => {
      if (event.defaultPrevented || !hasFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "none";
    });
    ctx.on(window, "drop", (event) => { if (!event.defaultPrevented && hasFiles(event)) event.preventDefault(); });
    ctx.every(tick, POLL_MS);
    ctx.on(document, "visibilitychange", () => { if (!document.hidden) tick(); });

    renderForm();
    renderHistory();
    openJob(jobId);
    loadModel();
    loadHistory();
  }

  function hasFiles(event) {
    return Boolean(event.dataTransfer) && [...(event.dataTransfer.types || [])].includes("Files");
  }

  /* #/ocr?job=… đổi job tại chỗ; cùng hash (bấm lại "Xem") = hỏi lại ngay. */
  function update(ctx, info) {
    if (!V || V.ctx !== ctx) return false;
    const id = wantedJob(ctx);
    if (id !== V.jobId) {
      const seed = V.seed && V.seed.id === id ? V.seed : null;
      V.seed = null;
      openJob(id, { seed });
    } else if (info && info.same) {
      loadHistory();
      poll();
    }
    return true;
  }

  function unmount() {
    V = null;
  }

  Router.register("ocr", { admin: true, mount, update, unmount });
})();
