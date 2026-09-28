/* ══════════════════════════════════════════════════════════════════
   /ui/uploads.js — tải tài liệu lên rồi lập chỉ mục (global duy nhất: Uploads).

   Dùng chung cho drawer "Phạm vi hỏi đáp" của Chat và màn hình Tài liệu.
   Module này chỉ lo LUỒNG; màn hình nào gọi thì tự vẽ tiến trình từ
   onUpdate — không có DOM nào ở đây ngoài dialog()/toast() dùng chung.

     Uploads.start(files, {onUpdate, signal, notify}) → Promise<items[]> (+ .items)
       Mỗi tệp một mục {id, file, name, size, status, stage, percent, message,
       documentId, runId, finished}. Các tệp chạy LẦN LƯỢT trong một hàng đợi
       chung của trang: hai lần gọi liền nhau không bao giờ mở hai dialog
       trùng lặp chồng lên nhau.
       status: queued → uploading → (conflict) → indexing → done
               | error | cancelled | uploaded (chờ admin) | background (đang index sẵn)

   Luồng mỗi tệp (giữ đúng app cũ app.js — thứ tự request, chuỗi decision, văn bản trạng thái):
     POST /documents/upload (multipart "file") → còn action_required thì hỏi
     người dùng rồi gửi lại tệp kèm "decision" → cancelled thì dừng →
     processing + run_id thì theo dõi run → trạng thái khác indexed/processing
     thì POST /documents/index → theo dõi GET /documents/ingestions/<run>
     mỗi 700 ms, bỏ cuộc sau 900 lần liên tiếp không đổi.

   Không có lời gọi mạng thô nào: mọi request đi qua Shell.api (401 → refresh
   → màn đăng nhập) để tệp tải lên cũng mang X-API-Key / Bearer như mọi nơi.
   ══════════════════════════════════════════════════════════════════ */
"use strict";

const Uploads = (() => {
  /* Kiểu MIME mà backend so KHỚP CHÍNH XÁC với phần multipart
     (postgres_document_service.py:47,100-103). Trình duyệt trên Windows
     thường gửi "" cho .md → 415 nếu gửi nguyên. */
  const TYPES = {
    pdf: "application/pdf",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    txt: "text/plain",
    md: "text/markdown",
  };
  const MARKDOWN_OK = new Set(["text/markdown", "text/plain"]);
  const MAX_BYTES = 52428800; // config/settings.py:196 — backend trả 413 nếu vượt
  const POLL_MS = 700;
  const IDLE_LIMIT = 900;     // ~10,5 phút không tiến triển
  const SELECTION_KEY = "lac.docsel";
  const TERMINAL = new Set(["completed", "failed", "cancelled"]);
  const FINISHED = new Set(["done", "error", "cancelled", "uploaded", "background"]);
  const STAGES = {
    queued: "Đang chờ", parsing: "Đọc tệp", ocr: "OCR", chunking: "Cắt đoạn", embedding: "Tạo vector",
    qdrant_upsert: "Ghi chỉ mục", activating: "Kích hoạt", completed: "Hoàn tất", failed: "Thất bại", cancelled: "Đã hủy",
  };
  const RUN_STATUS = { failed: "thất bại", cancelled: "đã hủy" };

  const queue = [];
  const jobs = new WeakMap();   // mục → {opts, items, resolve}
  let running = false;
  let seq = 0;

  /* ── lựa chọn tài liệu cho hỏi đáp (lac.docsel) ──────────────── */

  /* Mảng document_id. Giá trị hỏng hoặc localStorage bị chặn → [] (sửa D14:
     app cũ JSON.parse thẳng ở top-level, một giá trị hỏng là chết cả trang). */
  function readSelection() {
    try {
      const raw = JSON.parse(localStorage.getItem(SELECTION_KEY) || "[]");
      if (!Array.isArray(raw)) return [];
      return [...new Set(raw.filter((id) => typeof id === "string" && id))];
    } catch {
      return [];
    }
  }

  function saveSelection(ids) {
    try {
      localStorage.setItem(SELECTION_KEY, JSON.stringify([...new Set([...ids].filter((id) => typeof id === "string" && id))]));
    } catch { /* bộ nhớ trình duyệt bị chặn: lựa chọn chỉ sống trong phiên */ }
  }

  function selectDocument(id) {
    if (!id) return;
    const ids = readSelection();
    if (!ids.includes(id)) saveSelection([...ids, id]);
  }

  /* ── tiện ích ────────────────────────────────────────────────── */
  function extOf(name) {
    const at = String(name || "").lastIndexOf(".");
    return at === -1 ? "" : String(name).slice(at + 1).toLowerCase();
  }

  /* Tệp có kiểu MIME đúng như backend chờ; gói lại thành File mới khi trình
     duyệt đưa "" / octet-stream (hoặc text/x-markdown cho .md). */
  function asUploadable(file) {
    const ext = extOf(file.name);
    const want = TYPES[ext === "markdown" ? "md" : ext];
    if (!want) return file;
    const ok = want === "text/markdown" ? MARKDOWN_OK.has(file.type) : file.type === want;
    if (ok) return file;
    try {
      return new File([file], file.name, { type: want, lastModified: file.lastModified });
    } catch {
      return file;
    }
  }

  function abortError() {
    const error = new Error("Đã hủy.");
    error.name = "AbortError";
    return error;
  }

  function sleep(ms, signal) {
    return new Promise((resolve, reject) => {
      if (signal && signal.aborted) { reject(abortError()); return; }
      const timer = setTimeout(() => { if (signal) signal.removeEventListener("abort", onAbort); resolve(); }, ms);
      function onAbort() { clearTimeout(timer); reject(abortError()); }
      if (signal) signal.addEventListener("abort", onAbort, { once: true });
    });
  }

  function mb(size) {
    return `${(Number(size || 0) / 1048576).toFixed(2)} MB`;
  }

  function stageText(run) {
    const label = STAGES[run.stage] || run.stage || "Đang xử lý";
    if (run.stage === "ocr" && run.total_pages) return `${label} ${run.processed_pages ?? 0}/${run.total_pages} trang`;
    return `${label} · ${run.vectors_count ?? 0}/${run.chunks_count || "?"} vector`;
  }

  function emit(item) {
    const job = jobs.get(item);
    if (!job || typeof job.opts.onUpdate !== "function") return;
    try { job.opts.onUpdate(item, job.items); } catch (error) { console.error("[uploads] onUpdate", error); }
  }

  function set(item, patch) {
    Object.assign(item, patch);
    item.finished = FINISHED.has(item.status);
    emit(item);
  }

  /* ── hỏi người dùng khi trùng lặp ────────────────────────────── */

  /* → decision (chuỗi chữ thường đúng như backend so) hoặc "cancel".
     Ba nhánh của README/prototype với chữ nút của app cũ; nhánh thứ tư
     content_owned_by_another_document chỉ còn "cancel" nên hiện lời giải
     thích với một nút Đóng thay vì hủy câm (sửa D4). */
  async function askConflict(upload, uploadName) {
    const existing = upload.filename || uploadName;
    let spec = null;
    if (upload.conflict === "same_name_same_hash") {
      spec = {
        body: `«${existing}» đã tồn tại với nội dung giống hệt. Chọn cách xử lý:`,
        options: [{ value: "use_existing", title: "Dùng tài liệu hiện có", sub: "Không tạo tệp, version hay vector mới" }],
      };
    } else if (upload.conflict === "new_name_existing_hash") {
      spec = {
        body: `Nội dung này đang thuộc tài liệu «${existing}». Chọn cách xử lý:`,
        options: [{ value: "rename", title: `Đổi tên thành "${uploadName}"`, sub: `Tài liệu «${existing}» mang tên mới, nội dung giữ nguyên` }],
      };
    } else if (upload.conflict === "same_name_different_hash") {
      const suggested = upload.suggested_filename || uploadName;
      spec = {
        body: `«${existing}» đã tồn tại nhưng nội dung khác. Chọn cách xử lý:`,
        options: [
          { value: "replace", title: "Thay thế (tạo version mới)", sub: "Version cũ vẫn dùng được cho tới khi bản mới index xong" },
          { value: "keep_both", title: `Giữ cả hai («${suggested}»)`, sub: `Lưu tệp này thành «${suggested}», tài liệu cũ giữ nguyên` },
        ],
      };
    } else if (upload.conflict === "content_owned_by_another_document") {
      await dialog({
        tone: "warn", icon: "file", title: "Tài liệu trùng lặp",
        body: `Nội dung của «${uploadName}» đang thuộc tài liệu khác là «${existing}», nên không dùng được để thay «${uploadName}». Tải lên bị hủy, dữ liệu không thay đổi.`,
        cancelLabel: "Đóng",
      });
      return "cancel";
    }
    if (!spec) return "cancel";
    const allowed = Array.isArray(upload.available_actions) ? upload.available_actions : null;
    const options = allowed ? spec.options.filter((o) => allowed.includes(o.value)) : spec.options;
    if (!options.length) return "cancel";
    const choice = await dialog({ tone: "warn", icon: "file", title: "Tài liệu trùng lặp", body: spec.body, options });
    return choice || "cancel";
  }

  /* ── một tệp ─────────────────────────────────────────────────── */
  function post(file, decision, signal) {
    const form = new FormData();
    form.append("file", file, file.name);
    if (decision) form.append("decision", decision);
    return Shell.api("/documents/upload", { method: "POST", body: form, signal });
  }

  /* Gửi lại tệp kèm quyết định của người dùng. "replace" trên một tài liệu ĐANG lập chỉ mục làm
     backend ném DocumentAlreadyIndexingError không được map (api-core.md §6.2) → 500 INTERNAL_ERROR
     với câu tiếng Anh. Nói lại bằng tiếng Việt theo nguyên nhân gần như chắc chắn của nhánh này. */
  async function postDecision(file, decision, signal) {
    try {
      return await post(file, decision, signal);
    } catch (error) {
      if (decision === "replace" && error && error.status === 500) {
        throw new Error("Chưa thay thế được — tài liệu này có thể đang được lập chỉ mục. Thử lại sau khi chạy xong.");
      }
      throw error;
    }
  }

  async function waitRun(runId, item, signal) {
    let idle = 0;
    let last = "";
    while (idle < IDLE_LIMIT) {
      const run = await Shell.api(`/documents/ingestions/${encodeURIComponent(runId)}`, { signal });
      set(item, {
        status: "indexing", runId, stage: stageText(run),
        percent: Math.max(8, Math.min(100, Number(run.progress_percent) || 0)),
      });
      if (TERMINAL.has(run.status)) return run;
      const snapshot = `${run.stage}|${run.progress_percent}|${run.processed_pages}|${run.vectors_count}`;
      if (snapshot === last) idle += 1;
      else { idle = 0; last = snapshot; }
      await sleep(POLL_MS, signal);
    }
    throw new Error("Quá trình lập chỉ mục không tiến triển.");
  }

  async function runItem(item, job) {
    const { signal, notify = true } = job.opts;
    const ext = extOf(item.name);
    if (!TYPES[ext === "markdown" ? "md" : ext]) throw Object.assign(new Error(ERROR_HINTS.UNSUPPORTED_FILE_TYPE), { code: "UNSUPPORTED_FILE_TYPE" });
    if (item.size > MAX_BYTES) throw Object.assign(new Error(ERROR_HINTS.DOCUMENT_TOO_LARGE), { code: "DOCUMENT_TOO_LARGE" });

    const file = asUploadable(item.file);
    set(item, { status: "uploading", stage: "Đang tải lên…", percent: 4 });
    let upload = await post(file, null, signal);
    while (upload && upload.action_required) {
      set(item, { status: "conflict", stage: "Tệp trùng với tài liệu đã có — chờ bạn chọn cách xử lý…" });
      const decision = await askConflict(upload, item.name);
      if (signal && signal.aborted) throw abortError();
      set(item, { status: "uploading", stage: decision === "cancel" ? "Đang hủy…" : "Đang tải lên…", percent: 4 });
      upload = await postDecision(file, decision, signal);
    }
    item.documentId = (upload && upload.document_id) || null;
    if (!upload || upload.cancelled) {
      set(item, { status: "cancelled", stage: "Đã hủy. Dữ liệu không thay đổi.", percent: 0 });
      return;
    }

    let run = null;
    if (upload.status === "processing" && upload.run_id) {
      run = await waitRun(upload.run_id, item, signal);
    } else if (upload.status === "processing") {
      // use_existing/rename trên tài liệu đang index: không POST /documents/index nữa (409).
      // Sửa D6: không báo "đã sẵn sàng" khi việc lập chỉ mục vẫn đang chạy.
      selectDocument(item.documentId);
      set(item, { status: "background", stage: "Tài liệu đang được lập chỉ mục sẵn. Theo dõi ở danh sách bên dưới.", percent: 50 });
      return;
    } else if (upload.status === "deleting") {
      // Hàng đang chờ dọn (tới ~24 giờ) vẫn giữ tên và hash; index lúc này có thể làm sống lại tài liệu đã xóa.
      throw new Error("Tài liệu trùng tên đang được xóa trên máy chủ. Thử lại sau khi dọn xong.");
    } else if (upload.status !== "indexed") {
      set(item, { status: "indexing", stage: "Đang gửi yêu cầu lập chỉ mục…", percent: 6 });
      let index;
      try {
        index = await Shell.api("/documents/index", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ document_id: upload.document_id }), signal,
        });
      } catch (error) {
        if (error && error.status === 403) {
          // Thành viên: backend chỉ cho admin lập chỉ mục (D5 / F10) — tài liệu vẫn nằm đó ở trạng thái "uploaded".
          set(item, { status: "uploaded", stage: "Đã tải lên. Cần quản trị viên lập chỉ mục tài liệu này.", percent: 100 });
          return;
        }
        if (error && error.code === "DOCUMENT_ALREADY_INDEXING") {
          selectDocument(item.documentId);
          set(item, { status: "background", stage: error.message, percent: 50 });
          return;
        }
        throw error;
      }
      run = await waitRun(index.ingestion_run_id, item, signal);
    }
    if (run && run.status !== "completed") {
      throw new Error(run.error_message || `Lập chỉ mục ${RUN_STATUS[run.status] || run.status}.`);
    }
    const stage = upload.renamed ? `Đã đổi tên tài liệu hiện có thành ${upload.filename}.`
      : run ? `Hoàn tất · ${run.chunks_count ?? 0} đoạn đã sẵn sàng.` : "Tài liệu đã có sẵn trong hệ thống.";
    selectDocument(item.documentId);
    set(item, { status: "done", stage, percent: 100, message: null });
    if (notify) toast("Tài liệu đã sẵn sàng cho hỏi đáp.");
  }

  /* Hủy qua signal SAU khi tệp đã lên máy chủ chỉ là ngừng theo dõi: tài liệu vẫn nằm đó, và nếu
     đã gửi lập chỉ mục thì máy chủ vẫn chạy tiếp — nói đúng như vậy thay vì "Đã hủy.". */
  function abortedPatch(item) {
    if (item.runId) {
      return { status: "cancelled", stage: "Đã ngừng theo dõi — máy chủ vẫn tiếp tục lập chỉ mục tài liệu này.", percent: item.percent };
    }
    if (item.documentId) {
      return { status: "cancelled", stage: "Đã ngừng — tệp đã nằm trên máy chủ nhưng có thể chưa được lập chỉ mục.", percent: 0 };
    }
    return { status: "cancelled", stage: "Đã hủy.", percent: 0 };
  }

  /* ── hàng đợi chung ──────────────────────────────────────────── */
  async function pump() {
    if (running) return;
    running = true;
    try {
      while (queue.length) {
        const item = queue.shift();
        const job = jobs.get(item);
        const { signal, notify = true } = job.opts;
        if (signal && signal.aborted) {
          set(item, { status: "cancelled", stage: "Đã hủy.", percent: 0 });
        } else {
          try {
            await runItem(item, job);
          } catch (error) {
            if ((signal && signal.aborted) || (error && error.name === "AbortError")) {
              set(item, abortedPatch(item));
            } else {
              const message = (error && error.message) || "Tải lên thất bại.";
              set(item, { status: "error", stage: `Lỗi: ${message}`, message, percent: 0 });
              if (notify) toast(message, "danger");
            }
          }
        }
        job.left -= 1;
        if (job.left <= 0) job.resolve(job.items);
      }
    } finally {
      running = false;
    }
  }

  function start(files, opts = {}) {
    const list = Array.from(files || []).filter((file) => file && typeof file.name === "string" && typeof file.size === "number");
    const items = list.map((file) => ({
      id: `up-${++seq}`, file, name: file.name, size: file.size, status: "queued",
      stage: `Đã chọn: ${file.name} · ${mb(file.size)}`, percent: 0, message: null,
      documentId: null, runId: null, finished: false,
    }));
    let resolve;
    const promise = new Promise((done) => { resolve = done; });
    const job = { opts: opts || {}, items, left: items.length, resolve };
    for (const item of items) {
      jobs.set(item, job);
      queue.push(item);
    }
    for (const item of items) emit(item);
    if (!items.length) resolve(items);
    else pump();
    promise.items = items;
    return promise;
  }

  return {
    start,
    readSelection,
    saveSelection,
    selectDocument,
    isFinished: (item) => Boolean(item && FINISHED.has(item.status)),
    get busy() { return running || queue.length > 0; },
    accept: ".pdf,.docx,.txt,.md",
    maxBytes: MAX_BYTES,
  };
})();
