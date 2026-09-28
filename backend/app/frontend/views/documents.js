/* ══════════════════════════════════════════════════════════════════
   /ui/views/documents.js — màn hình Tài liệu (#/documents, #/documents?doc=<id>).

   Một IIFE, không tên top-level. Gồm:
     - thanh công cụ: ô tìm (tên tệp + tag, lọc tại trình duyệt), lọc
       trạng thái Tất cả | Đã index | Đang xử lý | Lỗi, nút "Tải lên" nhiều
       tệp qua Uploads (uploads.js) + danh sách tiến trình từng tệp;
     - 4 thẻ số: Tài liệu, Đoạn đã index, Đang xử lý, Dung lượng (F2);
     - bảng tài liệu: ô chọn = phạm vi hỏi đáp dùng chung với Chat
       (lac.docsel), tên + "dung lượng · trang", tag (F2), trạng thái, số
       đoạn, version, cập nhật / tiến trình, menu ⋯;
     - panel chi tiết 380px (?doc=<id>, đổi qua update() không mount lại):
       xem trước trang 1 (F3), tag (F2), version + lịch sử xử lý (F3, thiếu
       thì suy ra từ lần xử lý gần nhất), tải tệp gốc (F3), xóa.

   Hợp đồng API: spec.md F2/F3/F10 + research/api-core.md §6. Endpoint cả
   tuyến chưa có (404/405 KHÔNG kèm mã lỗi — xem routeMissing) → trạng thái
   "Máy chủ chưa hỗ trợ …", KHÔNG giả vờ thành công; còn 404 kèm mã lỗi là
   chuyện của riêng MỘT tài liệu, chỉ tài liệu đó báo lỗi. Không bao giờ mời
   "Lập chỉ mục lại" cho tài liệu đang xóa (api-core §6.3: index một hàng
   deleting còn run queued làm tài liệu sống lại) hay cho tài liệu đã gỡ tệp
   gốc (409 SOURCE_UNAVAILABLE).

   Gọi mạng: Shell.api (JSON) và Shell.fetchBlob (ảnh trang, tệp gốc).
   Trạng thái S sống qua các lần mount (danh sách, bộ lọc, tải lên đang
   chạy…); V là DOM của lần mount đang sống, null khi đã rời view — mọi
   việc bất đồng bộ kiểm tra V / số thứ tự trước khi vẽ.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  /* ── hằng số ─────────────────────────────────────────────────── */
  const JSON_HEADERS = { "Content-Type": "application/json" };
  const POLL_MS = 5000;          // làm mới danh sách khi máy chủ đang thực sự làm việc (processing)
  const SLOW_POLL_MS = 30000;    // chỉ còn hàng chờ người/chờ dọn: hỏi lại thưa hơn (xem needsPoll)
  const RUN_POLL_MS = 1000;      // theo dõi lần lập chỉ mục do chính màn hình này gửi
  const RUN_IDLE_LIMIT = 900;    // như Uploads: ~15 phút không tiến triển thì thôi theo dõi
  const REFRESH_MS = 30000;      // vẽ lại nhãn thời gian tương đối ("2 phút trước")
  const PENDING = new Set(["uploaded", "processing", "deleting"]);
  const TERMINAL = new Set(["completed", "failed", "cancelled"]);
  const NO_PAGES_EXT = new Set(["md", "markdown", "txt", "docx", "doc"]);   // không có phân trang cố định
  const PLAIN_EXT = new Set(["md", "markdown", "txt"]);                      // không có ảnh trang để xem trước

  /* Nhãn trạng thái (pill 24px có chấm). "uploaded" = đã tải lên nhưng chưa ai
     lập chỉ mục (thành viên tải lên, F10) — nói đúng là đang CHỜ, không phải đang xử lý. */
  const STATUS = {
    indexed: { label: "Đã index", tone: "ok" },
    processing: { label: "Đang xử lý", tone: "warn" },
    uploaded: { label: "Chờ index", tone: "warn" },
    failed: { label: "Lỗi", tone: "danger" },
    deleting: { label: "Đang xóa", tone: "muted" },
  };
  const STAGE = {
    queued: "đang chờ", parsing: "đọc tệp", ocr: "OCR", chunking: "cắt đoạn", embedding: "tạo vector",
    qdrant_upsert: "ghi chỉ mục", activating: "kích hoạt", completed: "hoàn tất", failed: "thất bại", cancelled: "đã hủy",
  };
  const FILTERS = [
    { value: "all", label: "Tất cả" },
    { value: "indexed", label: "Đã index" },
    { value: "processing", label: "Đang xử lý" },
    { value: "failed", label: "Lỗi" },
  ];
  const VERSION_LABEL = {
    active: "active", archived: "lưu trữ", staging: "đang index", failed: "lỗi",
    pending: "chưa index", deleting: "sẽ bị xóa",
  };
  /* Mã lỗi backend chưa có trong ERROR_HINTS của common.js (common.js không được sửa) — nói bằng tiếng
     Việt thay vì đưa nguyên câu tiếng Anh của máy chủ vào giao diện tiếng Việt. */
  const ERROR_VI = {
    SOURCE_UNAVAILABLE: "Tệp gốc đã bị gỡ khỏi máy chủ — tải lại bản gốc trước khi lập chỉ mục.",
    DOCUMENT_NOT_FOUND: "Tài liệu không còn trên máy chủ.",
    DOCUMENT_PARSE_FAILED: "Máy chủ không đọc được nội dung tệp này.",
    VECTOR_DIMENSION_MISMATCH: "Số chiều vector không khớp chỉ mục hiện có — cần lập chỉ mục lại toàn bộ.",
    INTERNAL_ERROR: "Máy chủ gặp lỗi nội bộ.",
  };
  const UPLOAD_LABEL = {
    queued: "Đang chờ", uploading: "Đang tải lên", conflict: "Chờ bạn chọn", indexing: "Đang lập chỉ mục", done: "Xong",
    error: "Lỗi", cancelled: "Đã hủy", uploaded: "Chờ quản trị viên", background: "Đang lập chỉ mục",
  };
  const MISSING_TEXT = {
    tags: "Máy chủ chưa hỗ trợ gắn tag.",
    source: "Máy chủ chưa hỗ trợ tải tệp gốc.",
  };

  /* ── trạng thái sống qua các lần mount ───────────────────────── */
  const S = {
    docs: [], loaded: false, error: null, stale: null, seq: 0, busy: false,
    filter: "all", search: "", tag: null, tagRows: null, tagsSeen: false,
    selected: new Set(),
    openId: null, focusDetail: false, fromList: false,
    uploads: [], fading: new WeakSet(),
    runs: new Map(),          // document_id → {runId, run, idle, snap}: lập chỉ mục lại do màn hình này gửi
    missing: { versions: false, history: false, pages: false, source: false, tags: false },
    detail: null,             // dữ liệu F3 của tài liệu đang mở: {id, key, seq, versions, history, preview}
  };
  let V = null;

  /* ── tiện ích ────────────────────────────────────────────────── */
  const enc = (value) => encodeURIComponent(String(value));
  const isAbort = (error) => Boolean(error) && error.name === "AbortError";
  const docHash = (id) => `#/documents?doc=${enc(id)}`;
  const findDoc = (id) => S.docs.find((doc) => doc.document_id === id) || null;

  function extOf(name) {
    const text = String(name || "");
    const at = text.lastIndexOf(".");
    return at === -1 ? "" : text.slice(at + 1).toLowerCase();
  }

  /* So khớp không phân biệt hoa thường và dấu: "phap ly" tìm được "pháp lý". */
  function fold(text) {
    return String(text ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[\u0111\u0110]/g, "d").toLowerCase();
  }

  /* Định danh một tag: giữ dấu ("bán" ≠ "bạn", "màu" ≠ "mẫu"), chỉ bỏ qua hoa/thường như máy chủ
     (casefold). Dùng cho khử trùng lặp và cho bộ lọc theo tag — KHÔNG dùng fold() ở đây, vì fold()
     bỏ dấu nên sẽ nuốt mất một tag tiếng Việt khác hẳn. */
  function tagKey(tag) {
    return String(tag ?? "").trim().toLocaleLowerCase("vi");
  }

  /* "Máy chủ chưa có endpoint này" (cả tuyến) ≠ "tài liệu này không có" (một tài liệu).
     isMissingApi() cũng nhận 404 kèm HTTP_ERROR, mà backend trả đúng envelope đó cho "Document not
     found" — nên chỉ coi là thiếu API khi lỗi KHÔNG mang mã nào (404/405 trơn của Starlette). */
  function routeMissing(error) {
    return isMissingApi(error) && !(error && error.code);
  }

  /* Câu lỗi cho người dùng: ưu tiên bảng tiếng Việt ở trên, rồi tới câu ERROR_HINTS mà common.js đã
     dịch, cuối cùng mới là câu của máy chủ (tiếng Anh) nhưng có lời dẫn tiếng Việt. */
  function say(error, fallback) {
    if (!error) return fallback;
    if (error.code && ERROR_VI[error.code]) return ERROR_VI[error.code];
    if (!error.message) return fallback;
    if (error.code && !ERROR_HINTS[error.code]) return `Máy chủ báo lỗi: ${error.message}`;
    return error.message;
  }

  function safeSavePrefs() {
    try { savePrefs(); } catch { /* localStorage bị chặn: chế độ chỉ sống trong phiên */ }
  }

  function hasTags(doc) {
    return Boolean(doc) && Array.isArray(doc.tags);
  }

  /* F2 có mặt khi ít nhất một tài liệu mang mảng tags (máy chủ cũ không trả khóa này).
     Lúc chưa có dữ liệu thì dùng câu trả lời của lần tải trước (S.tagsSeen) chứ không đoán "có":
     trên máy chủ thật (chưa có F2) khung xương từng hiện cột TAG rồi cột đó biến mất, cả bảng nhảy. */
  function tagsSupported() {
    return !S.missing.tags && (S.loaded ? S.docs.some(hasTags) : S.tagsSeen);
  }

  function sizeText(doc) {
    return typeof doc.file_size === "number" && Number.isFinite(doc.file_size) ? fmtBytes(doc.file_size) : null;
  }

  /* "12 trang" từ F2 total_pages; thiếu thì PDF lấy ingestion.total_pages. MD/TXT/DOCX không có
     phân trang (docx_parser.py: "Pages stay None") nên là "1 tệp" — ingestion.total_pages = 1 của
     chúng chỉ là số khối bộ đọc trả về, in "1 trang" là sai. */
  function pagesText(doc) {
    const pages = Number(doc.total_pages);
    if (doc.total_pages != null && Number.isFinite(pages) && pages > 0) return `${fmtNumber(pages)} trang`;
    if (NO_PAGES_EXT.has(extOf(doc.filename))) return "1 tệp";
    const fromRun = Number(doc.ingestion && doc.ingestion.total_pages);
    return Number.isFinite(fromRun) && fromRun > 0 ? `${fmtNumber(fromRun)} trang` : null;
  }

  /* Parity 75: app cũ ghi "còn/không còn file gốc" ở mỗi hàng — giữ phần đáng biết (đã gỡ tệp gốc). */
  function metaText(doc) {
    const gone = doc.source_available === false && doc.status !== "deleting" ? "không còn tệp gốc" : null;
    return [sizeText(doc), pagesText(doc), gone].filter(Boolean).join(" · ") || "—";
  }

  function chunksText(doc) {
    const n = Number(doc.chunks_count) || 0;
    return doc.status === "indexed" || n > 0 ? fmtNumber(n) : "—";
  }

  /* Số version của tài liệu (brief + prototype: cột Version = v<active_index_version>). api-core
     §6.1: khi chưa có version nào active thì số này là của run gần nhất — nên nhãn ở panel nói rõ
     nó đang ở trạng thái nào (active / đang index / chưa index / lỗi) thay vì luôn nói "active".
     HÀNG và PANEL dùng chung hàm này, khỏi chỗ in "—" chỗ in "v0". */
  function versionNumber(doc) {
    const n = Number(doc.active_index_version);
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  function versionText(doc) {
    const n = versionNumber(doc);
    return n === null ? "—" : `v${n}`;
  }

  /* Tiến trình của một run: "đang OCR 7/12" hoặc "<giai đoạn> <n>%". */
  function progressText(run) {
    if (!run) return "đang xử lý";
    const stage = run.stage || run.current_stage;
    if (stage === "ocr" && Number(run.total_pages) > 0) return `đang OCR ${run.processed_pages ?? 0}/${run.total_pages}`;
    if (stage === "queued" || !stage) return "đang chờ";
    const pct = Number(run.progress_percent);
    const label = STAGE[stage] || "đang xử lý";
    return Number.isFinite(pct) && pct > 0 && pct < 100 ? `${label} ${Math.round(pct)}%` : label;
  }

  function runOf(doc) {
    const mine = S.runs.get(doc.document_id);
    return (mine && mine.run) || doc.ingestion || null;
  }

  function isWorking(doc) {
    return doc.status === "processing" || S.runs.has(doc.document_id);
  }

  function updatedText(doc) {
    if (isWorking(doc)) return progressText(runOf(doc));
    return doc.updated_at ? fmtRelative(doc.updated_at) : "—";
  }

  function inFilter(doc, filter) {
    if (filter === "indexed") return doc.status === "indexed";
    if (filter === "processing") return doc.status === "uploaded" || doc.status === "processing";
    if (filter === "failed") return doc.status === "failed";
    return true;
  }

  /* Hàng sau ô tìm / tag, TRƯỚC bộ lọc trạng thái (số đếm trên các nút lọc tính từ đây). */
  function baseRows() {
    if (S.tag) {
      const wanted = tagKey(S.tag);
      // Máy chủ thật bỏ qua ?tag= (trả cả danh sách) → luôn lọc lại ở đây.
      return (S.tagRows || S.docs).filter((doc) => hasTags(doc) && doc.tags.some((t) => tagKey(t) === wanted));
    }
    const q = fold(S.search.trim());
    if (!q) return S.docs;
    return S.docs.filter((doc) => fold(doc.filename).includes(q) || (hasTags(doc) && doc.tags.some((t) => fold(t).includes(q))));
  }

  function visibleRows() {
    return baseRows().filter((doc) => inFilter(doc, S.filter));
  }

  function stats() {
    let total = 0, chunks = 0, working = 0, failed = 0, bytes = 0, sized = false;
    for (const doc of S.docs) {
      if (doc.status !== "deleting") total += 1;
      if (doc.status === "indexed") chunks += Number(doc.chunks_count) || 0;
      if (doc.status === "uploaded" || doc.status === "processing") working += 1;
      if (doc.status === "failed") failed += 1;
      if (typeof doc.file_size === "number" && Number.isFinite(doc.file_size)) { bytes += doc.file_size; sized = true; }
    }
    return { total, chunks, working, failed, bytes: sized ? bytes : null };
  }

  /* Nhịp hỏi lại danh sách. "processing" là máy chủ đang thực sự chạy → 5 giây. "uploaded" (chờ quản
     trị viên) và "deleting" (chờ dọn, api-core §6.1: tới ~24 giờ) tự nó không đổi gì → 30 giây, khỏi
     gửi ~17.000 GET /documents mỗi ngày cho một hàng đứng yên. */
  function needsPoll() {
    if (S.runs.size || S.docs.some((doc) => doc.status === "processing")) return "fast";
    return S.docs.some((doc) => PENDING.has(doc.status)) ? "slow" : null;
  }

  /* ── lựa chọn cho hỏi đáp (lac.docsel, dùng chung với Chat) ──── */
  /* prune: bỏ id không còn trong một lần tải THÀNH CÔNG của cả danh sách (parity 79/80). */
  function syncSelection(prune = false) {
    let ids = Uploads.readSelection();
    if (prune && S.loaded) {
      const known = new Set(S.docs.map((doc) => doc.document_id));
      const kept = ids.filter((id) => known.has(id));
      if (kept.length !== ids.length) {
        Uploads.saveSelection(kept);
        ids = kept;
      }
    }
    S.selected = new Set(ids);
  }

  function setSelected(ids) {
    Uploads.saveSelection([...ids]);
    S.selected = new Set(Uploads.readSelection());
    renderAll();
  }

  function toggleSelect(id, on) {
    const ids = new Set(Uploads.readSelection());
    if (on) ids.add(id);
    else ids.delete(id);
    setSelected(ids);
  }

  /* Ô chọn ở tiêu đề bảng: mọi tài liệu ĐÃ INDEX đang hiện (không lọc thì = tất cả đã index). */
  function toggleAll(on) {
    const ids = new Set(Uploads.readSelection());
    for (const doc of visibleRows()) {
      if (doc.status !== "indexed") continue;
      if (on) ids.add(doc.document_id);
      else ids.delete(doc.document_id);
    }
    setSelected(ids);
  }

  /* ── tải danh sách ───────────────────────────────────────────── */
  async function load({ quiet = false } = {}) {
    const my = ++S.seq;
    const signal = V ? V.ctx.signal : undefined;
    const tag = S.tag;
    S.busy = true;
    if (!quiet) renderAll();
    try {
      const [all, tagged] = await Promise.all([
        Shell.api("/documents", { signal }),
        // F2: GET /documents?tag= — lỗi hay máy chủ chưa hỗ trợ đều không chặn cả trang.
        tag ? Shell.api(`/documents?tag=${enc(tag)}`, { signal }).catch((error) => (isAbort(error) ? Promise.reject(error) : null)) : null,
      ]);
      if (my !== S.seq) return;
      S.docs = Array.isArray(all) ? all.filter((doc) => doc && typeof doc.document_id === "string") : [];
      S.loaded = true;
      S.error = null;
      S.stale = null;
      S.tagsSeen = S.docs.some(hasTags);
      S.tagRows = tag && tag === S.tag && Array.isArray(tagged) ? tagged : null;
      syncSelection(true);
      // Run đã xong / tài liệu đã biến mất: thôi coi là "đang lập chỉ mục lại". Lưới an toàn cho
      // trường hợp vòng theo dõi run chết giữa chừng: danh sách đã báo run kết thúc thì bỏ entry
      // (nếu vòng theo dõi của lần mount này còn sống thì để nó tự kết thúc, giữ toast "đã xong").
      for (const [id, entry] of [...S.runs]) {
        const doc = findDoc(id);
        if (!doc) { S.runs.delete(id); continue; }
        if (V && entry.pollCtx === V.ctx) continue;
        const run = doc.ingestion;
        if (entry.runId && run && run.id === entry.runId && TERMINAL.has(run.status)) S.runs.delete(id);
      }
    } catch (error) {
      if (my !== S.seq || isAbort(error) || (signal && signal.aborted)) return;
      // Đã có dữ liệu: giữ nguyên, báo "không làm mới được"; lần đầu: trạng thái lỗi + "Thử lại".
      if (S.loaded) S.stale = error;
      else S.error = error;
    } finally {
      if (my === S.seq) S.busy = false;
    }
    renderAll();
  }

  function applyTag(tag) {
    S.tag = tag;
    S.search = "";
    S.tagRows = null;
    if (V) {
      V.search.value = tag;
      V.page.scrollTop = 0;
    }
    renderAll();
    load({ quiet: true });
  }

  function setSearch(text) {
    S.search = text;
    S.tag = null;
    S.tagRows = null;
    renderAll();
  }

  /* ── hành động trên một tài liệu ─────────────────────────────── */
  function openDoc(id) {
    S.focusDetail = true;
    Router.go(docHash(id));
  }

  /* Đóng panel không được đẻ thêm mục lịch sử (Back sẽ thành nút "mở lại panel vừa đóng").
     Mở từ danh sách trong chính lần mount này (S.fromList) → lùi đúng mục vừa đẩy; còn lại (vào
     thẳng bằng đường dẫn, đổi từ tài liệu này sang tài liệu khác) → thay tại chỗ. */
  function closeDetail() {
    if (S.fromList) {
      S.fromList = false;
      history.back();
      return;
    }
    Router.replace("#/documents");
  }

  /* Sau khi panel biến mất, người dùng bàn phím không được rơi về <body>. */
  function focusAfterClose(id) {
    if (!V) return;
    const ref = V.rows.get(id);
    const link = ref && ref.tr.querySelector(".dv-name");
    const next = link || (V.rows.size ? [...V.rows.values()][0].tr.querySelector(".dv-name") : null);
    (next || V.upload).focus({ preventScroll: true });
  }

  /* "Hỏi tài liệu này": phạm vi hỏi đáp chỉ còn tệp này, chế độ Tài liệu, sang Chat. */
  function askDoc(doc) {
    if (!doc || doc.status !== "indexed") return;
    Uploads.saveSelection([doc.document_id]);
    prefs.mode = "rag";
    safeSavePrefs();
    Router.go("#/chat");
  }

  function viewChunks(doc) {
    if (doc && doc.status === "indexed") Router.go(`#/chunks/${enc(doc.document_id)}`);
  }

  /* api-core §6.3: POST /documents/index trả 409 SOURCE_UNAVAILABLE khi bản gốc đã bị gỡ → khóa nút
     thay vì mời bấm rồi báo lỗi. Hàng đang xóa: KHÔNG BAO GIỜ mời (bug làm tài liệu sống lại). */
  function canReindex(doc) {
    return Boolean(doc) && Shell.isAdmin() && doc.status !== "deleting" && doc.source_available !== false;
  }

  async function reindex(doc) {
    if (!canReindex(doc) || isWorking(doc)) return;
    const id = doc.document_id;
    const name = doc.filename;
    S.runs.set(id, { runId: null, run: { status: "queued", stage: "queued", progress_percent: 0 }, idle: 0, snap: "" });
    renderAll();
    try {
      const res = await Shell.api("/documents/index", {
        method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ document_id: id }),
      });
      const entry = S.runs.get(id);
      if (!entry) return;
      entry.runId = res && res.ingestion_run_id ? res.ingestion_run_id : null;
      toast(`Đã gửi lập chỉ mục «${name}».`);
      if (entry.runId) pollRun(id);
      else S.runs.delete(id);
    } catch (error) {
      S.runs.delete(id);
      toast(say(error, "Không gửi được yêu cầu lập chỉ mục."), "danger");
    }
    load({ quiet: true });
  }

  /* Theo dõi run do màn hình này gửi (1 giây/lần). Rời view thì dừng; mount lại thì chạy tiếp. */
  async function pollRun(id) {
    const entry = S.runs.get(id);
    if (!entry || !entry.runId || !V) return;
    const ctx = V.ctx;
    // Gắn vòng theo dõi vào chính lần mount này. Cờ boolean cũ kẹt vĩnh viễn khi view được dựng lại
    // (Router.reload / Shell.resume) đúng lúc một request đang bay: lần mount mới thấy polling=true
    // rồi thoát, còn request cũ hủy xong thì không hẹn lại → hàng đứng "đang xử lý" tới khi tải trang.
    if (entry.pollCtx === ctx) return;
    entry.pollCtx = ctx;
    let again = true;
    try {
      const run = await Shell.api(`/documents/ingestions/${enc(entry.runId)}`, { signal: ctx.signal });
      if (S.runs.get(id) !== entry) { again = false; return; }
      entry.run = run;
      entry.errors = 0;
      if (TERMINAL.has(run.status)) {
        again = false;
        S.runs.delete(id);
        const doc = findDoc(id);
        const name = doc ? doc.filename : "tài liệu";
        if (run.status === "completed") toast(`Đã lập chỉ mục xong «${name}» · ${fmtNumber(run.chunks_count ?? 0)} đoạn.`);
        else toast(`Lập chỉ mục «${name}» ${run.status === "cancelled" ? "đã hủy" : "thất bại"}${run.error_message ? `: ${run.error_message}` : "."}`, "danger");
        load({ quiet: true });
        return;
      }
      const snap = `${run.stage}|${run.progress_percent}|${run.processed_pages}|${run.vectors_count}`;
      entry.idle = snap === entry.snap ? entry.idle + 1 : 0;
      entry.snap = snap;
      if (entry.idle >= RUN_IDLE_LIMIT) {
        again = false;
        S.runs.delete(id);
        toast("Quá trình lập chỉ mục không tiến triển.", "danger");
      }
      renderAll();
    } catch (error) {
      if (isAbort(error) || ctx.signal.aborted) { again = false; return; }
      entry.errors = (entry.errors || 0) + 1;
      if (entry.errors >= 5) {
        again = false;
        S.runs.delete(id);
        renderAll();
      }
    } finally {
      if (entry.pollCtx === ctx) entry.pollCtx = null;
      if (again && S.runs.get(id) === entry && V && V.ctx === ctx) ctx.after(() => pollRun(id), RUN_POLL_MS);
    }
  }

  async function downloadSource(doc, button) {
    if (!doc) return;
    if (S.missing.source) { toast(MISSING_TEXT.source, "danger"); return; }
    if (button) button.disabled = true;
    try {
      const blob = await Shell.fetchBlob(`/documents/${enc(doc.document_id)}/source`);
      const url = URL.createObjectURL(blob);
      const link = h("a", { href: url, download: doc.filename || "tai-lieu", style: "display:none" });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) {
      // Chỉ 404/405 TRƠN mới là "máy chủ chưa có endpoint"; 404 kèm mã lỗi là chuyện của riêng
      // tài liệu này (đã bị xóa ở thẻ khác…) và không được khóa nút của mọi tài liệu khác.
      if (routeMissing(error)) {
        S.missing.source = true;
        toast(MISSING_TEXT.source, "danger");
      } else {
        toast(say(error, "Không tải được tệp gốc."), "danger");
      }
    } finally {
      if (button && button.isConnected) button.disabled = false;
      renderAll();
    }
  }

  /* Parity 94: hỏi "Xóa tài liệu?" → DELETE → bỏ khỏi lựa chọn → toast → tải lại (kể cả khi lỗi). */
  async function deleteDoc(doc) {
    if (!doc || !Shell.isAdmin()) return;
    const ok = await confirmDialog({
      title: "Xóa tài liệu?",
      body: `«${doc.filename}» cùng toàn bộ chỉ mục của nó sẽ bị xóa. Không thể hoàn tác.`,
      confirmLabel: "Xóa",
      signal: V ? V.ctx.signal : undefined,
    });
    if (!ok) return;
    const id = doc.document_id;
    try {
      await Shell.api(`/documents/${enc(id)}`, { method: "DELETE" });
      Uploads.saveSelection(Uploads.readSelection().filter((x) => x !== id));
      S.selected.delete(id);
      S.runs.delete(id);
      toast("Đã xóa tài liệu.");
      if (S.openId === id && V) {
        closeDetail();
        focusAfterClose(id);   // nút "Xóa tài liệu" biến mất cùng panel: đừng bỏ focus lại <body>
      }
    } catch (error) {
      toast(say(error, "Không xóa được tài liệu."), "danger");
    }
    load({ quiet: true });
  }

  /* F2: PATCH /documents/{id}/tags {tags} → Document. */
  function parseTags(text) {
    return String(text || "").split(/[,;\n]/).map((t) => t.trim().replace(/\s+/g, " ")).filter(Boolean);
  }

  function mergeTags(...lists) {
    const out = [];
    const seen = new Set();
    for (const tag of lists.flat()) {
      const key = tagKey(tag);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(tag);
    }
    return out;
  }

  async function saveTags(doc, tags) {
    const res = await Shell.api(`/documents/${enc(doc.document_id)}/tags`, {
      method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ tags }),
    });
    // Cập nhật tại chỗ ngay (khỏi chờ lần tải lại) rồi tải lại cho chắc.
    const at = S.docs.findIndex((d) => d.document_id === doc.document_id);
    if (at !== -1) S.docs[at] = res && res.document_id ? res : { ...S.docs[at], tags };
    return res;
  }

  function tagError(error) {
    if (routeMissing(error)) {
      S.missing.tags = true;
      return null;
    }
    if (error && error.status === 422) return "Tag không hợp lệ (quá dài hoặc quá nhiều tag).";
    return say(error, "Không lưu được tag.");
  }

  async function addTags(doc) {
    if (!doc) return;
    if (!hasTags(doc) || S.missing.tags) { toast(MISSING_TEXT.tags, "danger"); return; }
    let missing = false;
    let added = 0;
    const value = await dialog({
      tone: "accent", icon: "tag", title: "Thêm tag",
      body: `Gắn tag cho «${doc.filename}». Nhiều tag cách nhau bằng dấu phẩy.`,
      input: { value: "", placeholder: "vd. hợp đồng, 2026", maxlength: 200, label: "Tag mới" },
      confirmLabel: "Lưu",
      signal: V ? V.ctx.signal : undefined,
      validate: async (text) => {
        const fresh = parseTags(text);
        if (!fresh.length) return "Nhập ít nhất một tag.";
        const current = findDoc(doc.document_id) || doc;
        const before = hasTags(current) ? current.tags : [];
        const merged = mergeTags(before, fresh);
        added = merged.length - before.length;
        try {
          await saveTags(current, merged);
          return null;
        } catch (error) {
          const message = tagError(error);
          if (message === null) missing = true;
          return message;
        }
      },
    });
    if (missing) toast(MISSING_TEXT.tags, "danger");
    // Không báo "đã lưu" khi chẳng có tag nào mới (mọi tag gõ vào đều đã có sẵn trên tài liệu).
    else if (value !== null) toast(added > 0 ? "Đã lưu tag." : "Tag đã có sẵn trên tài liệu.");
    renderAll();
    if (value !== null || missing) load({ quiet: true });
  }

  async function removeTag(doc, tag) {
    if (!doc || !hasTags(doc)) return;
    try {
      await saveTags(doc, doc.tags.filter((t) => t !== tag));
      toast(`Đã bỏ tag «${tag}».`);
    } catch (error) {
      const message = tagError(error);
      toast(message === null ? MISSING_TEXT.tags : message, "danger");
    }
    renderAll();
    load({ quiet: true });
  }

  function openTagMenu(anchor, doc, tag) {
    dropdown(anchor, [
      { label: "Lọc danh sách theo tag này", icon: "search", onSelect: () => applyTag(tag) },
      { label: "Bỏ tag khỏi tài liệu", icon: "x", onSelect: () => removeTag(doc, tag) },
    ], { align: "start" });
  }

  function openRowMenu(anchor, id) {
    const doc = findDoc(id);
    if (!doc) return;
    const admin = Shell.isAdmin();
    const indexed = doc.status === "indexed";
    const deleting = doc.status === "deleting";
    const items = [
      { label: "Hỏi tài liệu này", icon: "chat", disabled: !indexed, onSelect: () => askDoc(doc) },
      { label: "Xem đoạn", icon: "list", disabled: !indexed, onSelect: () => viewChunks(doc) },
    ];
    if (admin && !deleting) {
      const noSource = doc.source_available === false;
      items.push({
        label: doc.status === "uploaded" ? "Lập chỉ mục" : "Lập chỉ mục lại", icon: "retry",
        disabled: isWorking(doc) || noSource,
        hint: noSource ? "đã gỡ tệp gốc" : null,
        onSelect: () => reindex(doc),
      });
    }
    items.push({
      label: "Tải file gốc", icon: "download",
      disabled: deleting || doc.source_available === false || S.missing.source,
      hint: S.missing.source ? "chưa hỗ trợ" : doc.source_available === false ? "đã gỡ" : null,
      onSelect: () => downloadSource(doc),
    });
    if (admin && !deleting) {
      items.push({ separator: true }, { label: "Xóa", icon: "trash", tone: "danger", onSelect: () => deleteDoc(doc) });
    }
    dropdown(anchor, items, { align: "end", width: 210 });
  }

  /* ── tải lên (Uploads: hàng đợi chung, dialog trùng lặp, lập chỉ mục) ── */
  function startUploads(files) {
    const list = Array.from(files || []);
    if (!list.length) return;
    // Không gắn ctx.signal: tải lên chạy tiếp khi rời màn hình, xong thì Uploads tự toast.
    const run = Uploads.start(list, { onUpdate: onUploadUpdate });
    S.uploads.push(...run.items);
    renderUploads();
  }

  function onUploadUpdate(item) {
    if (item.finished) load({ quiet: true });
    // Dòng "Xong" tự dọn sau 8 giây (tài liệu đã nằm trong bảng ngay bên dưới); dòng lỗi / chờ
    // quản trị viên / đã hủy ở lại để người dùng còn đọc được.
    if (item.status === "done" && V && !S.fading.has(item)) {
      S.fading.add(item);
      V.ctx.after(() => {
        S.uploads = S.uploads.filter((x) => x !== item);
        renderUploads();
      }, 8000);
    }
    renderUploads();
  }

  /* ── vẽ ──────────────────────────────────────────────────────── */
  function renderAll() {
    if (!V) return;
    renderHeader();
    renderToolbar();
    renderStats();
    renderTable();
    renderUploads();
    renderDetail();
  }

  function renderHeader() {
    if (!S.loaded) {
      V.ctx.setHeader("Tài liệu", S.error ? "Không tải được danh sách tài liệu" : "Đang tải danh sách…");
      return;
    }
    const st = stats();
    V.ctx.setHeader("Tài liệu", `${fmtNumber(st.total)} tài liệu · ${fmtNumber(st.working)} đang xử lý · ${fmtNumber(st.failed)} lỗi`);
  }

  function renderToolbar() {
    // "Tất cả" đếm như thẻ số và như tiêu đề: KHÔNG tính hàng đang xóa (hàng đó vẫn hiện trong bảng
    // với pill "Đang xóa", nhưng nó không còn là tài liệu bạn đang có).
    const base = baseRows().filter((doc) => doc.status !== "deleting");
    FILTERS.forEach((f, i) => {
      const node = V.counts[i];
      if (node) node.textContent = S.loaded ? fmtNumber(base.filter((doc) => inFilter(doc, f.value)).length) : "";
    });
    V.seg.setValue(S.filter);
    const text = S.tag ?? S.search;
    if (document.activeElement !== V.search && V.search.value !== text) V.search.value = text;
    V.clear.hidden = !V.search.value;
    V.search.placeholder = tagsSupported() ? "Tìm tài liệu, tag…" : "Tìm tài liệu…";
    V.stale.hidden = !S.stale;
    if (S.stale) V.staleText.textContent = `Không làm mới được danh sách: ${S.stale.message || "lỗi không rõ"}. Đang thử lại…`;
  }

  function renderStats() {
    const st = S.loaded ? stats() : null;
    V.stat.total.textContent = st ? fmtNumber(st.total) : "—";
    V.stat.chunks.textContent = st ? fmtNumber(st.chunks) : "—";
    V.stat.working.textContent = st ? fmtNumber(st.working) : "—";
    V.stat.size.textContent = st && st.bytes !== null ? fmtBytes(st.bytes) : "—";
    const noSize = S.loaded && (!st || st.bytes === null);
    V.stat.sizeCard.title = noSize ? "Máy chủ chưa trả dung lượng tệp" : "";
    if (!noSize) V.stat.sizeCard.removeAttribute("title");
  }

  function skeletonRows(showTags) {
    return [0, 1, 2, 3, 4].map((i) => h("tr", { class: "dv-skel", "aria-hidden": "true" },
      h("td", { class: "col-check" }, skeleton({ w: 13, h: 13, r: 3 })),
      h("td", null, h("div", { class: "dv-file" }, skeleton({ w: 30, h: 30, r: 8 }),
        h("div", { class: "dv-skel-text" }, skeleton({ w: 150 - i * 12, h: 12 }), skeleton({ w: 80, h: 10 })))),
      showTags ? h("td", { class: "dv-col-tag" }, skeleton({ w: 56, h: 18, r: 999 })) : null,
      h("td", null, skeleton({ w: 72, h: 22, r: 999 })),
      h("td", { class: "num" }, h("div", { class: "dv-skel-num" }, skeleton({ w: 22, h: 12 }))),
      h("td", null, skeleton({ w: 20, h: 12 })),
      h("td", null, skeleton({ w: 64, h: 12 })),
      h("td", { class: "col-act" })));
  }

  function rowSig(doc, showTags) {
    const id = doc.document_id;
    return JSON.stringify([
      showTags, doc.filename, doc.status, doc.chunks_count, versionText(doc), showTags && hasTags(doc) ? doc.tags : null,
      metaText(doc), updatedText(doc), doc.updated_at, doc.error_message, doc.source_available, S.selected.has(id), id === S.openId,
    ]);
  }

  function buildRow(doc, showTags) {
    const id = doc.document_id;
    const indexed = doc.status === "indexed";
    const st = STATUS[doc.status] || { label: doc.status || "?", tone: "muted" };
    const status = pill(st.label, st.tone);
    if (doc.status === "failed" && doc.error_message) status.title = doc.error_message;
    else if (indexed && doc.error_message) status.title = `Lần lập chỉ mục lại gần nhất lỗi: ${doc.error_message}`;
    else if (doc.status === "uploaded") status.title = "Đã tải lên, chưa lập chỉ mục";
    else if (doc.status === "deleting") status.title = "Đang chờ dọn khỏi máy chủ (có thể tới 24 giờ)";

    const check = h("input", {
      type: "checkbox", checked: S.selected.has(id), disabled: !indexed, dataset: { focus: "check" },
      "aria-label": `Dùng ${doc.filename} cho hỏi đáp`,
      title: indexed ? "Chọn cho hỏi đáp (dùng chung với Chat)" : "Chỉ chọn được tài liệu đã lập chỉ mục",
      onChange: (event) => toggleSelect(id, event.target.checked),
    });
    const tagCell = showTags ? h("td", { class: "dv-col-tag" },
      h("div", { class: "dv-tags" }, hasTags(doc) ? doc.tags.map((tag) => h("button", {
        type: "button", class: "tag dv-tag", title: `Lọc theo tag «${tag}»`, onClick: () => applyTag(tag),
      }, tag)) : null)) : null;
    const updated = updatedText(doc);
    const tr = h("tr", { class: id === S.openId ? "is-selected" : null, dataset: { id } },
      h("td", { class: "col-check" }, check),
      h("td", null, h("div", { class: "dv-file" }, typeBadge(doc.filename, 30),
        h("div", { class: "dv-file-text" },
          h("a", { class: "dv-name", href: docHash(id), title: doc.filename, dataset: { focus: "name" } }, doc.filename || "(không tên)"),
          h("div", { class: "dv-meta" }, metaText(doc))))),
      tagCell,
      h("td", null, status),
      h("td", { class: "num dv-num" }, chunksText(doc)),
      h("td", { class: "dv-ver" }, versionText(doc)),
      h("td", { class: "dv-upd", title: !isWorking(doc) && doc.updated_at ? fmtDate(doc.updated_at, { time: true }) : null }, updated),
      h("td", { class: "col-act" }, h("button", {
        type: "button", class: "icon-btn icon-btn-28 row-act", title: "Thao tác", "aria-label": `Thao tác với ${doc.filename}`,
        dataset: { focus: "more" }, onClick: (event) => openRowMenu(event.currentTarget, id),
      }, icon("dots", { size: 16, sw: 2.6 }))));
    return tr;
  }

  /* Khối dưới bảng (lỗi / rỗng): chỉ dựng lại khi chữ ký đổi — nếu không, mỗi nhịp poll sẽ thay nút
     "Xóa bộ lọc" bằng nút mới và focus bàn phím rơi về <body>. */
  function setBox(sig, build) {
    if (V.boxSig === sig) return;
    V.boxSig = sig;
    const node = build();
    V.box.replaceChildren(...(node ? [node] : []));
    V.box.hidden = !node;
  }

  /* Hàng giữ theo document_id; chỉ dựng lại hàng có dữ liệu đổi, và giữ focus bàn phím trong hàng đó
     (poll không được làm mất focus hay đóng menu ⋯ đang mở). */
  function renderTable() {
    const showTags = tagsSupported();
    V.thTag.hidden = !showTags;
    const tbody = V.tbody;
    if (!S.loaded) {
      V.rows.clear();
      setBox(S.error ? `error|${S.error.message}` : "none", () => (S.error ? errorState(S.error, () => { S.error = null; load(); }) : null));
      if (S.error) tbody.replaceChildren();
      else if (!tbody.querySelector(".dv-skel")) tbody.replaceChildren(...skeletonRows(showTags));
      syncHeadCheck([]);
      return;
    }
    tbody.querySelectorAll(".dv-skel").forEach((node) => node.remove());
    const list = visibleRows();
    const keep = new Set(list.map((doc) => doc.document_id));
    for (const [id, ref] of V.rows) {
      if (!keep.has(id)) { ref.tr.remove(); V.rows.delete(id); }
    }
    const menuAnchor = dropdown.open ? dropdown.open.anchor : null;
    list.forEach((doc, index) => {
      const id = doc.document_id;
      const sig = rowSig(doc, showTags);
      let ref = V.rows.get(id);
      if (!ref) {
        ref = { tr: buildRow(doc, showTags), sig };
        V.rows.set(id, ref);
      } else if (ref.sig !== sig && !(menuAnchor && ref.tr.contains(menuAnchor))) {
        const focused = ref.tr.contains(document.activeElement) ? document.activeElement.dataset.focus : null;
        const fresh = buildRow(doc, showTags);
        ref.tr.replaceWith(fresh);
        ref.tr = fresh;
        ref.sig = sig;
        if (focused) fresh.querySelector(`[data-focus="${focused}"]`)?.focus({ preventScroll: true });
      }
      const at = tbody.children[index];
      if (at !== ref.tr) tbody.insertBefore(ref.tr, at || null);
    });

    setBox(list.length ? "none" : JSON.stringify(["empty", S.docs.length > 0, S.tag, S.search, S.filter]), () => {
      if (list.length) return null;
      return S.docs.length > 0
        ? emptyState({
          icon: "search", title: "Không có tài liệu nào khớp",
          text: S.tag ? `Không tài liệu nào mang tag «${S.tag}» ở bộ lọc này.` : "Thử từ khóa khác hoặc chọn bộ lọc «Tất cả».",
          action: { label: "Xóa bộ lọc", icon: "x", onClick: clearFilters },
        })
        : emptyState({
          icon: "docs", title: "Chưa có tài liệu nào",
          text: "Tải tệp PDF, DOCX, TXT hoặc Markdown lên để bắt đầu hỏi đáp theo tài liệu.",
          action: { label: "Tải lên", icon: "upload", onClick: () => V && V.fileInput.click() },
        });
    });
    syncHeadCheck(list);
  }

  function syncHeadCheck(list) {
    const indexed = list.filter((doc) => doc.status === "indexed");
    const on = indexed.filter((doc) => S.selected.has(doc.document_id)).length;
    V.headCheck.disabled = !indexed.length;
    V.headCheck.checked = indexed.length > 0 && on === indexed.length;
    V.headCheck.indeterminate = on > 0 && on < indexed.length;
  }

  function clearFilters() {
    S.filter = "all";
    S.search = "";
    S.tag = null;
    S.tagRows = null;
    if (V) V.search.value = "";
    renderAll();
  }

  /* Danh sách tiến trình từng tệp dưới thanh công cụ: cập nhật tại chỗ để thanh 4px trượt mượt. */
  function renderUploads() {
    if (!V) return;
    const rows = V.upRows;
    const keep = new Set(S.uploads.map((item) => item.id));
    for (const [id, ref] of rows) if (!keep.has(id)) { ref.node.remove(); rows.delete(id); }
    for (const item of S.uploads) {
      let ref = rows.get(item.id);
      if (!ref) {
        const state = h("span", { class: "dv-up-state" });
        const fill = h("div", { class: "fill" });
        const stage = h("div", { class: "dv-up-stage" });
        const dismiss = h("button", {
          type: "button", class: "icon-btn icon-btn-24 dv-up-x", title: "Ẩn dòng này", "aria-label": `Ẩn dòng tải lên ${item.name}`,
          onClick: () => { S.uploads = S.uploads.filter((x) => x !== item); renderUploads(); },
        }, icon("x", { size: 12 }));
        const node = h("div", { class: "dv-up" },
          typeBadge(item.name, 22),
          h("div", { class: "dv-up-text" }, h("div", { class: "dv-up-name", title: item.name }, item.name), stage),
          h("div", { class: "progress progress-4 dv-up-bar" }, fill),
          state, dismiss);
        ref = { node, state, fill, stage, dismiss };
        rows.set(item.id, ref);
      }
      const tone = item.status === "done" ? "is-done" : item.status === "error" ? "is-error"
        : ["uploaded", "background", "cancelled", "conflict"].includes(item.status) ? "is-warn" : null;
      ref.node.className = ["dv-up", tone].filter(Boolean).join(" ");
      ref.state.textContent = UPLOAD_LABEL[item.status] || item.status;
      ref.fill.style.width = `${Math.max(0, Math.min(100, Number(item.percent) || 0))}%`;
      ref.stage.textContent = item.stage || "";
      ref.stage.title = item.stage || "";
      ref.dismiss.hidden = !item.finished;
      if (ref.node.parentNode !== V.uploads) V.uploads.append(ref.node);
    }
    V.uploads.hidden = !S.uploads.length;
  }

  /* ── panel chi tiết ──────────────────────────────────────────── */
  function detailKey(doc) {
    const run = doc.ingestion || {};
    return [doc.document_id, doc.status, doc.active_version_id, doc.chunks_count, run.id, run.status].join("|");
  }

  function revokePreview() {
    const d = S.detail;
    if (d && d.preview && d.preview.url) {
      URL.revokeObjectURL(d.preview.url);
      d.preview.url = null;
    }
  }

  /* Dữ liệu F3 của tài liệu đang mở: tải khi mở tài liệu khác hoặc khi trạng thái/version của nó đổi. */
  function ensureDetailData(doc) {
    const id = doc.document_id;
    const key = detailKey(doc);
    let d = S.detail;
    if (d && d.id === id && d.key === key) return;
    if (!d || d.id !== id) {
      revokePreview();
      d = S.detail = { id, key, seq: 0, versions: { state: "loading" }, history: { state: "loading" }, preview: { state: "idle", version: null } };
    } else {
      d.key = key;
    }
    const my = ++d.seq;
    const live = doc.status !== "deleting";   // F3 trả 404 cho hàng đang xóa: khỏi hỏi
    for (const part of ["versions", "history"]) {
      if (!live) d[part] = { state: "skip" };
      else if (S.missing[part]) d[part] = { state: "missing" };
      else fetchPart(part, d, my);
    }
    const version = doc.active_version_id || doc.content_hash || "";
    if (!live || PLAIN_EXT.has(extOf(doc.filename))) {
      revokePreview();
      d.preview = { state: live ? "text" : "skip", version };
    } else if (S.missing.pages) {
      d.preview = { state: "missing", version };
    } else if (d.preview.version !== version || d.preview.state === "idle") {
      loadPreview(d, id, version);
    }
  }

  async function fetchPart(part, d, my) {
    const signal = V ? V.ctx.signal : undefined;
    try {
      const rows = await Shell.api(`/documents/${enc(d.id)}/${part}`, { signal });
      if (S.detail !== d || d.seq !== my) return;
      d[part] = { state: "ok", rows: Array.isArray(rows) ? rows : [] };
    } catch (error) {
      if (isAbort(error) || S.detail !== d || d.seq !== my) return;
      // Chỉ 404/405 TRƠN mới nói lên "máy chủ chưa có endpoint này". 404 kèm mã lỗi (HTTP_ERROR
      // "Document not found") là chuyện của riêng tài liệu này → chỉ tài liệu này hỏng, và KHÔNG
      // suy ra gì cho /source: đó là endpoint khác, có thể vẫn chạy.
      if (routeMissing(error)) {
        S.missing[part] = true;
        d[part] = { state: "missing" };
      } else {
        d[part] = { state: "error", error };
      }
    }
    if (V) renderAll();
  }

  async function loadPreview(d, id, version) {
    if (d.preview.url) URL.revokeObjectURL(d.preview.url);
    d.preview = { state: "loading", version, url: null };
    const signal = V ? V.ctx.signal : undefined;
    let next;
    try {
      const blob = await Shell.fetchBlob(`/documents/${enc(id)}/pages/1.png`, { signal });
      if (!blob || (blob.type && !blob.type.startsWith("image/"))) throw new Error("Máy chủ không trả ảnh trang.");
      next = { state: "ok", version, url: URL.createObjectURL(blob) };
    } catch (error) {
      if (isAbort(error)) return;
      // Như trên: một tài liệu chưa dựng xong ảnh trang (404 kèm mã) không được tắt xem trước của
      // mọi tài liệu khác trong cả phiên.
      if (routeMissing(error)) {
        S.missing.pages = true;
        next = { state: "missing", version };
      } else {
        next = { state: "error", version, error };
      }
    }
    if (S.detail !== d || d.preview.version !== version) {
      if (next.url) URL.revokeObjectURL(next.url);
      return;
    }
    d.preview = next;
    if (V) renderAll();
  }

  function buildDetail() {
    const name = h("div", { class: "dv-d-name", id: "dv-detail-name" });
    const meta = h("div", { class: "dv-d-meta" });
    const badge = h("span", { class: "type-badge type-badge-34 type-txt" });
    const closeBtn = h("button", {
      type: "button", class: "icon-btn icon-btn-30", title: "Đóng", "aria-label": "Đóng chi tiết tài liệu", onClick: closeDetail,
    }, icon("x", { size: 15 }));
    const head = h("div", { class: "drawer-head" }, badge, h("div", { class: "dv-d-title" }, name, meta), closeBtn);
    const slot = (cls) => h("div", { class: cls, hidden: true });
    const D = {
      id: null, sigs: {}, badge, name, meta, closeBtn,
      actions: slot("dv-d-actions"),
      progress: slot("dv-d-progress"),
      notice: slot("dv-d-notice"),
      preview: slot("dv-d-preview"),
      tags: slot("dv-d-section"),
      versions: slot("dv-d-section"),
      history: slot("dv-d-section"),
      foot: slot("dv-d-foot"),
      empty: slot("dv-d-empty"),
    };
    // Tiến trình cập nhật tại chỗ (không dựng lại) để thanh 4px trượt, không nháy.
    D.prog = {
      title: h("span", { class: "dv-d-progress-title" }),
      pct: h("span", { class: "dv-d-progress-pct" }),
      fill: h("div", { class: "fill" }),
      sub: h("div", { class: "dv-d-progress-sub" }),
    };
    D.progress.append(h("div", { class: "dv-d-progress-top" }, D.prog.title, D.prog.pct),
      h("div", { class: "progress progress-4" }, D.prog.fill), D.prog.sub);
    D.body = h("div", { class: "drawer-body" }, D.actions, D.progress, D.notice, D.preview, D.tags, D.versions, D.history, D.foot, D.empty);
    D.aside = h("aside", { class: "drawer drawer-380 dv-detail", id: "dv-detail", "aria-labelledby": "dv-detail-name" }, head, D.body);
    D.backdrop = h("div", { class: "drawer-backdrop", onClick: closeDetail });
    return D;
  }

  /* Thay nội dung một khối chỉ khi chữ ký dữ liệu đổi; giữ focus nếu nó đang ở trong khối. */
  function fill(D, key, sig, build) {
    const node = D[key];
    if (D.sigs[key] === sig) return;
    D.sigs[key] = sig;
    const focused = node.contains(document.activeElement) ? document.activeElement.dataset.focus : null;
    const children = build();
    node.replaceChildren(...(children || []).filter(Boolean));
    node.hidden = !node.childNodes.length;
    if (focused) node.querySelector(`[data-focus="${focused}"]`)?.focus({ preventScroll: true });
  }

  function sectionLabel(text) {
    return h("div", { class: "section-label dv-d-label" }, text);
  }

  function hint(text, tone) {
    return text ? h("div", { class: ["dv-hint", tone && `is-${tone}`] }, text) : null;
  }

  function versionCard({ n, hash, date, status }) {
    const hashText = hash ? `sha256 …${String(hash).slice(-4)}` : "sha256 —";
    const when = date ? fmtRelative(date) : null;
    return h("div", {
      class: ["version-card", "dv-v", status === "active" && "is-active", `is-${status || "unknown"}`],
      title: [hash ? `sha256 ${hash}` : null, date ? fmtDate(date, { time: true }) : null].filter(Boolean).join("\n") || null,
    },
    h("span", { class: "dv-v-n" }, `v${n ?? "?"}`),
    h("span", { class: "dv-v-meta" }, [hashText, when].filter(Boolean).join(" · ")),
    h("span", { class: "dv-v-label" }, VERSION_LABEL[status] || status || ""));
  }

  function fallbackVersionStatus(doc) {
    if (doc.status === "deleting") return "deleting";   // đang dọn khỏi máy chủ: gọi là "active" thì sai
    if (doc.active_version_id) return "active";
    if (doc.status === "failed") return "failed";
    if (doc.status === "processing") return "staging";
    return "pending";                                   // đã tải lên, chưa lần nào lập chỉ mục
  }

  function timelineItem({ title, sub, dot, at }) {
    return h("div", { class: "timeline-item", title: at ? fmtDate(at, { time: true }) : null },
      h("span", { class: ["timeline-dot", `dv-dot-${dot}`] }),
      h("div", { class: "timeline-title" }, title),
      sub ? h("div", { class: "timeline-sub" }, sub) : null);
  }

  /* Không có /history (F3): suy ra từ lần xử lý gần nhất trong payload Document. */
  function derivedHistory(doc) {
    const run = runOf(doc);
    const items = [];
    if (isWorking(doc)) {
      const stage = run && (run.stage || run.current_stage);
      const pages = run && Number(run.total_pages) > 0 ? ` · ${run.processed_pages ?? 0}/${run.total_pages} trang` : "";
      items.push({ title: S.runs.has(doc.document_id) ? "Đang lập chỉ mục lại" : "Đang xử lý", sub: `${STAGE[stage] || "đang chờ"}${pages}`, dot: "warn" });
    } else if (run && run.status === "completed") {
      const ocr = Number(run.ocr_pages) > 0 ? ` · OCR ${fmtNumber(run.ocr_pages)} trang` : "";
      items.push({ title: "Index hoàn tất", sub: `${fmtNumber(run.chunks_count ?? doc.chunks_count ?? 0)} đoạn${ocr}`, dot: "ok" });
    } else if (run && run.status === "failed") {
      items.push({ title: "Lỗi", sub: run.error_message || doc.error_message || "Lập chỉ mục thất bại", dot: "danger" });
    } else if (run && run.status === "cancelled") {
      items.push({ title: "Đã hủy lập chỉ mục", sub: run.error_message || null, dot: "muted" });
    } else if (doc.status === "uploaded") {
      items.push({ title: "Chờ lập chỉ mục", sub: "chưa có lần xử lý nào", dot: "warn" });
    }
    if (doc.status === "indexed" && doc.error_message && !(run && run.status === "failed")) {
      items.unshift({ title: "Lỗi lập chỉ mục lại", sub: doc.error_message, dot: "danger" });
    }
    items.push({ title: "Tải lên", sub: [sizeText(doc), doc.created_at ? fmtRelative(doc.created_at) : null].filter(Boolean).join(" · ") || null, dot: "muted", at: doc.created_at });
    return items;
  }

  function renderDetail() {
    if (!V) return;
    const id = S.openId;
    if (!id) {
      if (V.detail) {
        V.detail.aside.remove();
        V.detail.backdrop.remove();
        V.detail = null;
      }
      revokePreview();
      S.detail = null;
      return;
    }
    let D = V.detail;
    if (!D) {
      D = V.detail = buildDetail();
      V.ctx.root.append(D.backdrop, D.aside);
    }
    const doc = S.loaded ? findDoc(id) : null;
    if (D.id !== id) {
      D.id = id;
      D.sigs = {};
      D.body.scrollTop = 0;
    }
    if (!doc) {
      // Chưa tải xong / không có trong danh sách (đã xóa hẳn, id sai).
      const state = S.loaded ? "gone" : S.error ? "error" : "loading";
      const newBadge = typeBadge("?", 34);
      if (D.badge.textContent !== "?") { D.badge.replaceWith(newBadge); D.badge = newBadge; }
      D.name.textContent = state === "loading" ? "Đang tải…" : "Không tìm thấy tài liệu";
      D.name.removeAttribute("title");
      D.meta.textContent = id;
      for (const key of ["actions", "progress", "notice", "preview", "tags", "versions", "history", "foot"]) {
        D[key].hidden = true;
        D.sigs[key] = null;
      }
      fill(D, "empty", `empty|${state}`, () => [state === "loading"
        ? h("div", { class: "dv-d-skel" }, skeleton({ h: 34, r: 9 }), skeleton({ h: 150, r: 12 }), skeleton({ w: "60%", h: 12 }), skeleton({ w: "80%", h: 12 }))
        : state === "error"
          ? errorState(S.error, () => { S.error = null; load(); })
          : emptyState({ icon: "file", title: "Không tìm thấy tài liệu này", text: "Tài liệu có thể đã bị xóa khỏi máy chủ, hoặc đường dẫn sai.", action: { label: "Đóng", icon: "x", onClick: closeDetail } })]);
      return;
    }
    if (D.sigs.empty) {
      D.empty.replaceChildren();
      D.empty.hidden = true;
      D.sigs.empty = null;
    }
    ensureDetailData(doc);
    const d = S.detail;
    const admin = Shell.isAdmin();
    const indexed = doc.status === "indexed";
    const deleting = doc.status === "deleting";
    const working = isWorking(doc);

    // Đầu panel: badge 34 + tên 13.5/700 + "dung lượng · trang · N đoạn".
    const ext = extOf(doc.filename);
    if (D.badge.dataset.ext !== ext || D.badge.textContent === "?") {
      const newBadge = typeBadge(doc.filename, 34);
      newBadge.dataset.ext = ext;
      D.badge.replaceWith(newBadge);
      D.badge = newBadge;
    }
    D.name.textContent = doc.filename || "(không tên)";
    D.name.title = doc.filename || "";
    const n = Number(doc.chunks_count) || 0;
    D.meta.textContent = [sizeText(doc), pagesText(doc), indexed || n > 0 ? `${fmtNumber(n)} đoạn` : null].filter(Boolean).join(" · ") || "—";

    const canIndex = canReindex(doc);
    fill(D, "actions", JSON.stringify([id, doc.status, admin, working, canIndex, doc.source_available]), () => [
      h("button", {
        type: "button", class: "btn btn-34 btn-primary dv-ask", disabled: !indexed, dataset: { focus: "ask" },
        title: indexed ? "Chat chế độ Tài liệu, chỉ hỏi trong tệp này" : "Chỉ hỏi được tài liệu đã lập chỉ mục",
        onClick: () => askDoc(findDoc(id)),
      }, "Hỏi tài liệu này"),
      h("button", {
        type: "button", class: "btn btn-34 btn-outline", disabled: !indexed, dataset: { focus: "chunks" },
        title: indexed ? null : "Chỉ xem được đoạn của tài liệu đã lập chỉ mục", onClick: () => viewChunks(findDoc(id)),
      }, "Xem đoạn"),
      admin && !deleting ? h("button", {
        type: "button", class: "btn btn-34 btn-outline", disabled: working || !canIndex, dataset: { focus: "reindex" },
        title: working ? "Tài liệu đang được xử lý"
          : canIndex ? null : "Tệp gốc đã bị gỡ khỏi máy chủ — tải lại bản gốc trước khi lập chỉ mục.",
        onClick: () => reindex(findDoc(id)),
      }, doc.status === "uploaded" ? "Lập chỉ mục" : "Lập chỉ mục lại") : null,
    ]);

    // Tiến trình: run do màn hình này gửi (1 giây/lần) hoặc ingestion trong danh sách (5 giây/lần).
    if (working) {
      const run = runOf(doc);
      const pct = Math.max(0, Math.min(100, Math.round(Number(run && run.progress_percent) || 0)));
      D.prog.title.textContent = S.runs.has(id) ? "Đang lập chỉ mục lại" : "Đang xử lý";
      D.prog.pct.textContent = `${pct}%`;
      D.prog.fill.style.width = `${Math.max(4, pct)}%`;
      D.prog.sub.textContent = progressText(run);
      D.progress.hidden = false;
    } else {
      D.progress.hidden = true;
    }

    fill(D, "notice", JSON.stringify([doc.status, doc.error_message, doc.source_available, admin]), () => {
      if (deleting) return [h("div", { class: "note tone-muted" }, "Tài liệu đang được dọn khỏi máy chủ. Hàng này tự biến mất khi xong (có thể tới 24 giờ); trong lúc đó tên và nội dung vẫn bị coi là trùng khi tải lên lại.")];
      if (doc.status === "uploaded") {
        return [h("div", { class: "note tone-warn" }, admin
          ? "Tài liệu đã tải lên nhưng chưa lập chỉ mục — bấm «Lập chỉ mục» để dùng cho hỏi đáp."
          : "Tài liệu đã tải lên nhưng chưa lập chỉ mục. Cần quản trị viên lập chỉ mục trước khi hỏi đáp.")];
      }
      return null;
    });

    // Xem trước trang 1 (F3): ảnh PNG thật; MD/TXT không có trang → ô sọc với lời nói thật.
    const pv = d.preview;
    fill(D, "preview", JSON.stringify([id, pv.state, pv.url || null]), () => {
      D.preview.className = ["dv-d-preview", pv.state === "ok" ? "has-img" : "page-placeholder", pv.state === "loading" && "is-loading"].filter(Boolean).join(" ");
      if (pv.state === "ok") return [h("img", { src: pv.url, alt: `Trang 1 của ${doc.filename}`, draggable: "false" })];
      const label = {
        text: "tệp văn bản · không có ảnh trang",
        skip: "tài liệu đang xóa",
        missing: "máy chủ chưa hỗ trợ xem trước trang",
        error: pv.error && pv.error.status === 404 ? "không có ảnh trang 1" : "không tải được trang 1",
        loading: "đang tải trang 1…",
        idle: "đang tải trang 1…",
      }[pv.state] || "xem trước trang 1";
      return [h("span", { class: "label", title: pv.state === "missing" ? "GET /documents/{id}/pages/1.png" : pv.error ? pv.error.message : null }, label)];
    });

    // Tag (F2).
    const tagsOk = hasTags(doc) && !S.missing.tags;
    fill(D, "tags", JSON.stringify([id, tagsOk, hasTags(doc) ? doc.tags : null, deleting]), () => {
      // Tài liệu đang xóa mà không có tag nào: không dựng mục "Tag" rỗng (fill() tự ẩn khối rỗng).
      if (deleting && !(tagsOk && doc.tags.length)) return [];
      return [
        sectionLabel("Tag"),
        h("div", { class: "dv-d-tags" },
          tagsOk ? doc.tags.map((tag, i) => h("button", {
            type: "button", class: "tag tag-lg dv-d-tag", dataset: { focus: `tag-${i}` },
            title: deleting ? `Lọc theo tag «${tag}»` : `Tag «${tag}»`,
            // Đang xóa: máy chủ không nhận sửa tag nữa → chip chỉ còn lọc danh sách.
            onClick: (event) => (deleting ? applyTag(tag) : openTagMenu(event.currentTarget, findDoc(id) || doc, tag)),
          }, tag)) : null,
          // Máy chủ chưa hỗ trợ tag: hiện lời giải thích, KHÔNG mời bấm một nút chắc chắn lỗi.
          tagsOk && !deleting ? h("button", {
            type: "button", class: "tag-add", dataset: { focus: "tag-add" }, onClick: () => addTags(findDoc(id) || doc),
          }, "+ thêm tag") : null),
        tagsOk ? null : hint("Máy chủ chưa hỗ trợ tag tài liệu."),
      ];
    });

    // Version (F3 /versions; thiếu thì một thẻ "active" từ payload Document).
    const vs = d.versions;
    fill(D, "versions", JSON.stringify([id, vs.state, vs.rows || null, doc.active_index_version, doc.content_hash, doc.active_version_id, doc.status]), () => {
      let cards;
      let note = null;
      if (vs.state === "loading") {
        cards = [h("div", { class: "version-card dv-v is-loading" }, skeleton({ w: 22, h: 12 }), skeleton({ w: "55%", h: 12 }))];
      } else if (vs.state === "ok" && vs.rows.length) {
        cards = vs.rows.map((row) => versionCard({ n: row.index_version, hash: row.content_hash, date: row.created_at, status: row.status }));
      } else {
        // Cùng con số với cột Version của bảng (chỗ này từng in "v0" trong khi hàng in "—"),
        // nhãn nói đúng trạng thái: active / đang index / chưa index / lỗi / sẽ bị xóa.
        const n = versionNumber(doc);
        cards = n === null ? [] : [versionCard({ n, hash: doc.content_hash, date: null, status: fallbackVersionStatus(doc) })];
        if (vs.state === "error") note = `Không tải được danh sách version: ${say(vs.error, "lỗi không rõ")}`;
        else if (!cards.length) note = "Tài liệu chưa có version nào.";
        else if (vs.state === "missing") note = "Máy chủ chưa trả danh sách version — chỉ hiện version hiện tại.";
      }
      return [sectionLabel("Version"), h("div", { class: "dv-versions" }, cards), hint(note, vs.state === "error" ? "danger" : null)];
    });

    // Lịch sử xử lý (F3 /history mới nhất trước; thiếu thì suy ra từ lần xử lý gần nhất).
    const hs = d.history;
    const derived = hs.state === "ok" && hs.rows.length ? null : derivedHistory(doc);
    fill(D, "history", JSON.stringify([id, hs.state, hs.rows || null, derived]), () => {
      let items;
      let note = null;
      if (hs.state === "loading") {
        items = [0, 1].map(() => h("div", { class: "timeline-item" }, h("span", { class: "timeline-dot dv-dot-muted" }),
          h("div", { class: "dv-skel-text" }, skeleton({ w: "45%", h: 12 }), skeleton({ w: "70%", h: 10 }))));
      } else if (!derived) {
        items = hs.rows.map((row) => timelineItem({
          title: row.title || row.kind || "Sự kiện",
          sub: row.detail || null,
          dot: row.ok === false || row.kind === "failed" ? "danger" : row.kind === "upload" || row.kind === "replace" ? "muted" : "ok",
          at: row.at,
        }));
      } else {
        items = derived.map(timelineItem);
        if (hs.state === "missing") note = "Máy chủ chưa hỗ trợ lịch sử xử lý — suy ra từ lần xử lý gần nhất.";
        else if (hs.state === "error") note = `Không tải được lịch sử: ${say(hs.error, "lỗi không rõ")}`;
      }
      return [sectionLabel("Lịch sử xử lý"), h("div", { class: "timeline" }, items), hint(note, hs.state === "error" ? "danger" : null)];
    });

    // Chân panel: tải tệp gốc (F3) + xóa (admin).
    const srcOff = deleting || doc.source_available === false || S.missing.source;
    fill(D, "foot", JSON.stringify([id, srcOff, S.missing.source, doc.source_available, admin, deleting]), () => [
      h("button", {
        type: "button", class: "btn btn-32 btn-outline hover-bg", disabled: srcOff, dataset: { focus: "source" },
        title: S.missing.source ? `${MISSING_TEXT.source} (GET /documents/{id}/source)`
          : doc.source_available === false ? "Tệp gốc đã được gỡ khỏi máy chủ (chỉ còn chỉ mục)."
            : deleting ? "Tài liệu đang xóa" : null,
        onClick: (event) => downloadSource(findDoc(id), event.currentTarget),
      }, "Tải file gốc"),
      h("span", { class: "spacer" }),
      admin && !deleting ? h("button", {
        type: "button", class: "btn btn-32 btn-ghost-danger", dataset: { focus: "delete" }, onClick: () => deleteDoc(findDoc(id)),
      }, "Xóa tài liệu") : null,
    ]);
  }

  /* ── dựng màn hình ───────────────────────────────────────────── */
  function buildStat(label, iconName, tone) {
    const value = h("div", { class: "stat-value" }, "—");
    const card = h("div", { class: "stat stat-doc" },
      h("span", { class: ["icon-tile", "icon-tile-34", `tone-${tone}`] }, icon(iconName, { size: 16 })),
      h("div", null, value, h("div", { class: "stat-label" }, label)));
    return { card, value };
  }

  function mount(ctx) {
    S.openId = ctx.query.get("doc") || null;
    S.focusDetail = false;
    S.fromList = false;
    // Dòng tải lên đã xong không sống qua một lần rời/vào màn hình (dòng lỗi thì còn để đọc lại).
    S.uploads = S.uploads.filter((item) => item.status !== "done");
    syncSelection(false);

    const fileInput = h("input", {
      type: "file", multiple: true, accept: Uploads.accept, hidden: true, tabindex: "-1", "aria-hidden": "true",
      onChange: (event) => { startUploads(event.target.files); event.target.value = ""; },
    });
    const search = h("input", {
      type: "text", placeholder: "Tìm tài liệu, tag…", "aria-label": "Tìm tài liệu theo tên hoặc tag",
      autocomplete: "off", spellcheck: "false", value: S.tag ?? S.search,
      onInput: (event) => setSearch(event.target.value),
      onKeydown: (event) => {
        if (event.key === "Escape" && event.target.value) {
          event.preventDefault();
          event.target.value = "";
          setSearch("");
        }
      },
    });
    const clear = h("button", {
      type: "button", class: "dv-search-clear", title: "Xóa ô tìm", "aria-label": "Xóa ô tìm", hidden: true,
      onClick: () => { search.value = ""; setSearch(""); search.focus(); },
    }, icon("x", { size: 13 }));
    const seg = segmented(FILTERS.map((f) => ({ value: f.value, label: f.label, count: "" })), S.filter, (value) => {
      S.filter = value;
      renderAll();
    }, { variant: "bordered", label: "Lọc theo trạng thái" });
    const counts = [...seg.querySelectorAll(".seg-item .count")];
    const uploadBtn = h("button", {
      type: "button", class: "btn btn-36 btn-primary btn-lift btn-glow dv-upload", onClick: () => fileInput.click(),
      title: "PDF, DOCX, TXT, MD · nhiều tệp · tối đa 50 MB",
    }, icon("upload", { size: 15, sw: 2.1 }), "Tải lên");
    // <div> chứ không phải <label>: nội dung của <label> không được chứa phần tử gán nhãn khác (ở
    // đây là nút xóa ô tìm) — HTML không hợp lệ, vài trình đọc màn hình gộp chữ của nút vào tên ô
    // nhập. Bấm vào khung (icon, khoảng trống) vẫn đưa con trỏ vào ô nhập như <label> vẫn làm.
    const searchBox = h("div", {
      class: "search dv-search", onClick: (event) => { if (!event.target.closest("button, input")) search.focus(); },
    }, icon("search", { size: 15 }), search, clear);
    const toolbar = h("div", { class: "toolbar" },
      searchBox, seg, h("span", { class: "spacer" }), uploadBtn, fileInput);

    const staleText = h("span");
    const stale = h("div", { class: "banner-warn dv-stale", role: "status", hidden: true }, icon("alert", { size: 15 }), staleText);
    const uploads = h("div", { class: "dv-uploads", hidden: true, "aria-label": "Tiến trình tải lên" });

    const total = buildStat("Tài liệu", "file", "accent");
    const chunks = buildStat("Đoạn đã index", "list", "accent");
    const working = buildStat("Đang xử lý", "retry", "warn");
    const size = buildStat("Dung lượng", "zap", "muted");
    const statsRow = h("div", { class: "dv-stats" }, total.card, chunks.card, working.card, size.card);

    const headCheck = h("input", {
      type: "checkbox", "aria-label": "Chọn mọi tài liệu đã lập chỉ mục đang hiện cho hỏi đáp",
      title: "Chọn cho hỏi đáp mọi tài liệu đã lập chỉ mục đang hiện (dùng chung với Chat)",
      onChange: (event) => toggleAll(event.target.checked),
    });
    const thTag = h("th", { class: "dv-col-tag" }, "Tag");
    const tbody = h("tbody");
    const table = h("table", { class: "table table-click dv-table", "aria-label": "Danh sách tài liệu" },
      h("thead", null, h("tr", null,
        h("th", { class: "col-check" }, headCheck),
        h("th", null, "Tên"),
        thTag,
        h("th", null, "Trạng thái"),
        h("th", { class: "num" }, "Đoạn"),
        h("th", null, "Version"),
        h("th", null, "Cập nhật"),
        h("th", { class: "col-act" }, h("span", { class: "sr-only" }, "Thao tác")))),
      tbody);
    const box = h("div", { class: "dv-box", hidden: true });
    const card = h("div", { class: "card card-flush dv-card" }, h("div", { class: "dv-scroll" }, table), box);

    // Bấm vào hàng (ngoài ô chọn / tag / nút / tên) = mở chi tiết; tên là link thật cho bàn phím.
    tbody.addEventListener("click", (event) => {
      const tr = event.target.closest("tr[data-id]");
      if (!tr) return;
      // Tên là <a href="#/documents?doc=…">: để trình duyệt tự điều hướng, chỉ đánh dấu đưa focus vào panel.
      if (event.target.closest(".dv-name")) { S.focusDetail = tr.dataset.id !== S.openId; return; }
      if (event.target.closest("a, button, input, label, select, textarea")) return;
      // Cả ô chọn là vùng bấm của checkbox (bấm hụt cạnh ô chọn không mở panel).
      const cell = event.target.closest("td.col-check");
      if (cell) {
        const box = cell.querySelector("input[type=checkbox]");
        if (box && !box.disabled) box.click();
        return;
      }
      openDoc(tr.dataset.id);
    });

    const page = h("div", { class: "page dv-page" },
      h("div", { class: "page-inner dv-inner" }, toolbar, stale, uploads, statsRow, card));

    // Thả tệp vào bất kỳ đâu trên trang = tải lên (như dropzone của Chat).
    const hasFiles = (event) => Boolean(event.dataTransfer) && [...(event.dataTransfer.types || [])].includes("Files");
    let dragDepth = 0;
    page.addEventListener("dragenter", (event) => { if (!hasFiles(event)) return; event.preventDefault(); dragDepth += 1; page.classList.add("is-drop"); });
    page.addEventListener("dragover", (event) => { if (hasFiles(event)) event.preventDefault(); });
    page.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) page.classList.remove("is-drop"); });
    page.addEventListener("drop", (event) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      dragDepth = 0;
      page.classList.remove("is-drop");
      startUploads(event.dataTransfer.files);
    });

    ctx.root.append(page);
    V = {
      ctx, page, search, clear, seg, counts, fileInput, upload: uploadBtn, stale, staleText, uploads, upRows: new Map(),
      stat: { total: total.value, chunks: chunks.value, working: working.value, size: size.value, sizeCard: size.card },
      headCheck, thTag, tbody, box, boxSig: null, rows: new Map(), detail: null,
    };

    ctx.on(document, "keydown", (event) => {
      if (event.key !== "Escape" || event.defaultPrevented || !S.openId) return;
      if (document.querySelector(".dialog-overlay, #menu-root .menu")) return;
      event.preventDefault();
      const id = S.openId;
      closeDetail();
      focusAfterClose(id);   // trả focus về tên của hàng vừa đóng, không rơi về <body>
    });
    // Tệp thả trượt ra ngoài .page (panel chi tiết, header, thanh bên): trình duyệt sẽ MỞ tệp đó
    // thay cho ứng dụng và hàng đợi tải lên đang chạy mất luôn → chặn, như Chat đã làm.
    ctx.on(window, "dragover", (event) => {
      if (event.defaultPrevented || !hasFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "none";
    });
    ctx.on(window, "drop", (event) => { if (!event.defaultPrevented && hasFiles(event)) event.preventDefault(); });
    // Chat ở thẻ khác đổi lựa chọn → ô chọn ở đây theo.
    ctx.on(window, "storage", (event) => {
      if (event.key === null || event.key === "lac.docsel") { syncSelection(false); renderAll(); }
    });
    // 5 giây/lần khi máy chủ đang xử lý (hoặc lần làm mới trước bị lỗi); 30 giây/lần khi chỉ còn
    // hàng "Chờ index" / "Đang xóa" — hai trạng thái tự nó không đổi (xem needsPoll).
    let slowWait = 0;
    ctx.every(() => {
      if (document.hidden || S.busy || !S.loaded) return;
      const need = needsPoll();
      if (S.stale || need === "fast") { slowWait = 0; load({ quiet: true }); return; }
      if (!need) { slowWait = 0; return; }
      slowWait += POLL_MS;
      if (slowWait >= SLOW_POLL_MS) { slowWait = 0; load({ quiet: true }); }
    }, POLL_MS);
    ctx.every(() => { if (!document.hidden) renderAll(); }, REFRESH_MS);

    renderAll();
    load({ quiet: S.loaded });
    for (const id of S.runs.keys()) pollRun(id);
  }

  /* #/documents?doc=<id> ↔ #/documents: chỉ mở/đổi/đóng panel, không mount lại. Mở do người dùng bấm
     (S.focusDetail) → focus vào nút đóng của panel; Back/Forward thì không kéo focus. */
  function update(ctx) {
    if (!V || V.ctx !== ctx) return false;
    const id = ctx.query.get("doc") || null;
    const focus = S.focusDetail;   // true = do openDoc / bấm tên gây ra, tức là vừa đẩy một mục lịch sử
    S.focusDetail = false;
    if (id !== S.openId) {
      // Chỉ khi mở từ chính danh sách thì mục lịch sử ngay trước mới chắc chắn là "#/documents".
      S.fromList = Boolean(focus && id && S.openId === null);
      S.openId = id;
      renderAll();
      if (focus && id && V && V.detail) V.detail.closeBtn.focus({ preventScroll: true });
    }
    return true;
  }

  function unmount() {
    revokePreview();
    S.detail = null;
    S.fromList = false;
    V = null;
  }

  Router.register("documents", { admin: false, mount, update, unmount });
})();
