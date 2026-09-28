/* ══════════════════════════════════════════════════════════════════
   /ui/views/memory.js — màn hình Ghi nhớ (#/memory, #/memory?tab=pending|applied|condense).

   Một IIFE, không tên top-level. Gồm:
     - thanh công cụ: tab Chờ duyệt | Đang hiệu lực | Tóm tắt hội thoại, mỗi tab
       một số đếm = số hàng ĐÃ TẢI ("50+" khi còn trang sau; tooltip nói tổng thật
       nếu F8 /count trả lời); ô tìm bên phải → POST /memory/search (trễ 400 ms),
       còn chữ thì kết quả tìm thay chỗ nội dung tab, xóa chữ thì về lại tab;
     - Chờ duyệt: lưới thẻ đề xuất, Duyệt / Từ chối, "Tải thêm" 50 hàng/lần;
     - Đang hiệu lực: danh sách ghi nhớ agent đang dùng (máy chủ tự cắt ở 20), Thu hồi;
     - Tóm tắt hội thoại: thẻ ngang từng bản rút gọn, Tạo lại / Xóa, "Tải thêm" 20/lần.
   Thành viên: chỉ tab Đang hiệu lực, không nút ghi. Máy chủ hiện trả 403 cho
   thành viên (F9 chưa có) → trạng thái khóa nói thật, không phải lỗi chung.

   Hợp đồng API: research/api-admin.md §4-5, api-core.md §9, spec F8 (đếm cho badge)
   và F9. Tự làm mới 20 giây/lần như bảng điều khiển cũ, nhưng KHÔNG thu gọn các
   trang người dùng đã "Tải thêm" (parity 43): trang 1 thay phần đầu, phần sau giữ.
   Gọi mạng: chỉ Shell.api. Trạng thái S sống qua các lần mount (vẽ ngay dữ liệu
   cũ rồi làm mới); V là DOM của lần mount đang sống, null khi đã rời view — mọi
   việc bất đồng bộ kiểm tra V / số thứ tự trước khi vẽ.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  /* ── hằng số ─────────────────────────────────────────────────── */
  const JSON_HEADERS = { "Content-Type": "application/json" };
  const REFRESH_MS = 20000;      // như bảng điều khiển cũ (parity: nhịp làm mới)
  const SEARCH_DELAY = 400;      // như ô tìm ghi nhớ trong Cài đặt cũ
  const KINDS = ["pending", "applied", "condense"];
  const TAB_LABEL = { pending: "Chờ duyệt", applied: "Đang hiệu lực", condense: "Tóm tắt hội thoại" };

  /* Mỗi danh sách: cỡ trang (0 = không phân trang), khóa hàng, thứ tự máy chủ (mới nhất trước). */
  const LISTS = {
    pending: {
      page: 50,
      key: (row) => String(row.candidate_id),
      order: (row) => Date.parse(row.created_at) || 0,
      url: (limit, offset) => `/api/memory-review/candidates?limit=${limit}&offset=${offset}`,
      endpoint: "GET /api/memory-review/candidates",
      feature: "hàng đề xuất chờ duyệt",
      errorTitle: "Không tải được danh sách đề xuất.",
    },
    applied: {
      page: 0,
      key: (row) => String(row.candidate_id),
      order: () => 0,
      url: () => "/api/memory-review/applied",
      endpoint: "GET /api/memory-review/applied",
      feature: "danh sách ghi nhớ đang hiệu lực",
      errorTitle: "Không tải được danh sách ghi nhớ.",
    },
    condense: {
      page: 20,
      key: (row) => String(row.batch_id),
      order: (row) => Number(row.batch_id) || 0,
      url: (limit, offset) => `/api/condensations?limit=${limit}&offset=${offset}`,
      endpoint: "GET /api/condensations",
      feature: "danh sách tóm tắt hội thoại",
      errorTitle: "Không tải được danh sách tóm tắt.",
    },
  };

  const INTRO = {
    pending: "Đề xuất dưới ngưỡng tin cậy chờ bạn quyết định; đề xuất trên ngưỡng được agent tự áp dụng. Từ chối chỉ ghi lại quyết định, không xóa gì.",
    condense: "Bản rút gọn do bộ tóm tắt tạo từ tin nhắn thật trong kênh, dùng để bot nhớ mạch chuyện — không bao giờ trở thành fact.",
  };
  const EMPTY = {
    pending: { icon: "check", title: "Không có đề xuất nào chờ duyệt.", text: "Đề xuất dưới ngưỡng tin cậy từ Discord sẽ hiện ở đây để bạn quyết định." },
    applied: { icon: "lightbulb", title: "Agent chưa nhớ điều gì.", text: "Ghi nhớ được duyệt hoặc agent tự áp dụng sẽ nằm ở đây." },
    condense: { icon: "list", title: "Chưa có bản tóm tắt nào.", text: "Bộ rút gọn chạy khi kênh dồn đủ tin chưa xử lý." },
  };

  /* Từ vựng máy chủ → lời tiếng Việt (api-admin §4-5). */
  const DECISION = {
    pending: "vẫn đang chờ", deferred: "vẫn đang chờ", approved: "đã được duyệt", rejected: "đã bị từ chối",
    applied: "đã được áp dụng", no_op: "không cần áp dụng", expired: "đã hết hạn", failed: "đã lỗi",
  };
  const MEMORY_STATUS = { active: "đang hiệu lực", superseded: "đã bị phiên bản mới thay", deleted: "đã bị xóa" };
  /* Pill trạng thái bản tóm tắt: chữ là giá trị gốc của máy chủ (như prototype P:370 và bảng cũ),
     màu theo nhóm, lời giải thích tiếng Việt nằm ở tooltip. */
  const BATCH = {
    completed: { tone: "ok", hint: "Đã tóm tắt xong" },
    pending: { tone: "warn", hint: "Chờ bộ tóm tắt xử lý" },
    running: { tone: "warn", hint: "Bộ tóm tắt đang xử lý" },
    failed: { tone: "danger", hint: "Tóm tắt thất bại" },
    stale: { tone: "muted", hint: "Tin gốc bị sửa sau khi tóm tắt; bản này không tự tạo lại — bấm Tạo lại" },
  };
  const BATCH_ERROR = { attempts_exhausted: "hết số lần thử", empty_span: "đoạn tin rỗng", condenser_error: "bộ tóm tắt báo lỗi" };

  /* ── trạng thái sống qua các lần mount ───────────────────────── */
  function newList() {
    return {
      rows: [], loaded: false, loading: false, error: null, stale: null, locked: false, missing: false,
      hasMore: false, more: false, moreError: null, seq: 0, mut: 0,
    };
  }

  const S = {
    role: null,                 // "admin" | "member": vai trò lúc tải dữ liệu bên dưới
    tab: "pending",
    lists: { pending: newList(), applied: newList(), condense: newList() },
    busy: new Map(),            // "<loại>:<id>" → hành động đang gửi
    notes: new Map(),           // "<loại>:<id>" → {tone, text}: lỗi / lời nhắc hiện ngay trên thẻ
    retry: new Map(),           // "<loại>:<id>" → hàng: máy chủ đã ghi nhưng đồng bộ hỏng (502) — giữ lại để bấm lần nữa
    countMissing: false,        // F8 GET /api/memory-review/count chưa có trên máy chủ
    pendingTotal: null,         // tổng hàng chờ duyệt do F8 trả về (null = chưa biết)
    query: "",
    search: { seq: 0, status: "idle", query: "", rows: [], error: null },
    refreshedAt: 0,
  };
  let V = null;

  /* ── tiện ích ────────────────────────────────────────────────── */
  const enc = (value) => encodeURIComponent(String(value));
  const isAbort = (error) => Boolean(error) && error.name === "AbortError";
  const isAdmin = () => Shell.isAdmin();
  const allowedTabs = () => (isAdmin() ? KINDS.slice() : ["applied"]);
  const fullKey = (kind, key) => `${kind}:${key}`;
  const searchKey = (row) => String(row.memory_id || row.id || "");

  /* ?tab= hợp lệ với vai trò hiện tại; mặc định: admin → Chờ duyệt, thành viên → Đang hiệu lực. */
  function pickTab(query) {
    const allowed = allowedTabs();
    const want = query ? query.get("tab") : null;
    return allowed.includes(want) ? want : allowed[0];
  }

  /* 0..1 → phần trăm làm tròn; null/không phải số → null. */
  function percent(value) {
    const n = Number(value);
    if (value === null || value === undefined || value === "" || !Number.isFinite(n)) return null;
    return Math.max(0, Math.min(100, Math.round(n * 100)));
  }

  function toDate(value) {
    if (value === null || value === undefined || value === "") return null;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  /* "14/09 20:10 → 21:45"; khác ngày → "14/09 23:40 → 15/09 00:20"; năm khác năm nay thì ghi thêm năm. */
  function spanText(from, to) {
    const a = toDate(from);
    const b = toDate(to);
    const p = (n) => String(n).padStart(2, "0");
    const thisYear = new Date().getFullYear();
    const day = (d) => `${p(d.getDate())}/${p(d.getMonth() + 1)}${d.getFullYear() !== thisYear ? `/${d.getFullYear()}` : ""}`;
    const clock = (d) => fmtClock(d, { seconds: false });
    if (!a && !b) return "—";
    if (!a) return `… → ${day(b)} ${clock(b)}`;
    if (!b) return `${day(a)} ${clock(a)} → …`;
    const sameDay = a.toDateString() === b.toDateString();
    return `${day(a)} ${clock(a)} → ${sameDay ? "" : `${day(b)} `}${clock(b)}`;
  }

  /* Hàng thật của máy chủ (không tính hàng giữ lại sau lỗi 502) — dùng làm offset của "Tải thêm". */
  function serverRows(kind) {
    const cfg = LISTS[kind];
    return S.lists[kind].rows.filter((row) => !S.retry.has(fullKey(kind, cfg.key(row))));
  }

  /* Số trên tab: số hàng đã tải, "+" khi trang cuối vừa tải còn đầy (máy chủ không trả tổng). */
  function countText(kind) {
    const list = S.lists[kind];
    if (!list.loaded || list.locked || list.missing) return null;
    return `${fmtNumber(list.rows.length)}${list.hasMore ? "+" : ""}`;
  }

  /* Số trên tab là số hàng ĐÃ TẢI (api-admin §4-5: danh sách không trả tổng). Tab Chờ duyệt có
     ngoại lệ: F8 GET /api/memory-review/count trả tổng thật (cũng là số trên badge thanh bên), nên
     khi còn trang sau thì tooltip nói "đã tải N trong M" thay vì nói máy chủ không có tổng. */
  function countHint(kind) {
    const list = S.lists[kind];
    if (!list.loaded || list.locked || list.missing) return null;
    const n = fmtNumber(list.rows.length);
    if (kind === "pending") {
      if (!list.hasMore) return `${n} đề xuất đang chờ duyệt.`;
      return S.pendingTotal === null
        ? `Đã tải ${n} đề xuất và vẫn còn trang sau — máy chủ không trả tổng số.`
        : `Đã tải ${n} trong ${fmtNumber(S.pendingTotal)} đề xuất đang chờ duyệt.`;
    }
    if (kind === "applied") return `${n} ghi nhớ máy chủ trả về (máy chủ chỉ trả tối đa 20 hàng).`;
    return list.hasMore
      ? `Đã tải ${n} bản tóm tắt và vẫn còn trang sau — máy chủ không trả tổng số.`
      : `${n} bản tóm tắt.`;
  }

  /* Lời lỗi để hiện: sendJson đã dịch mã quen (ERROR_HINTS) và lỗi mạng; 500 INTERNAL_ERROR thì máy
     chủ chỉ có câu tiếng Anh chung chung → nói bằng tiếng Việt. */
  function errText(error, fallback = "Đã xảy ra lỗi không xác định.") {
    if (error && error.code === "INTERNAL_ERROR") return "Máy chủ gặp lỗi không mong muốn (500). Thử lại sau.";
    return (error && error.message) || fallback;
  }

  /* Lời máy chủ (tiếng Anh, api-admin §4.3) → tiếng Việt; lỗi khác giữ lời của sendJson. */
  function reviewMessage(error, fallback) {
    if (error && error.code === "INTERNAL_ERROR") return errText(error);
    const raw = String((error && error.message) || "");
    let m = /candidate is already (\w+)/i.exec(raw);
    if (m) return `Đề xuất này ${DECISION[m[1]] || m[1]} ở nơi khác.`;
    if (/no extractor proposal/i.test(raw)) {
      return "Đề xuất này không mang nội dung ghi nhớ (đề xuất xóa) nên không duyệt được — chỉ có thể từ chối.";
    }
    m = /memory is already (\w+)/i.exec(raw);
    if (m) return `Ghi nhớ này ${MEMORY_STATUS[m[1]] || m[1]} — hãy thu hồi phiên bản đang hiệu lực.`;
    if (/only applied candidates can be reverted/i.test(raw)) return "Chỉ thu hồi được ghi nhớ đã được áp dụng.";
    if (error && error.code === "MEMORY_CONFLICT") {
      return "Ghi nhớ cùng chủ đề vừa thay đổi ở nơi khác — đã tải lại danh sách, xem lại rồi duyệt.";
    }
    return raw || fallback;
  }

  /* ── nạp dữ liệu ─────────────────────────────────────────────── */
  function cleanRows(kind, data) {
    const cfg = LISTS[kind];
    if (!Array.isArray(data)) return [];
    const seen = new Set();
    const out = [];
    for (const row of data) {
      if (!row || typeof row !== "object") continue;
      const key = cfg.key(row);
      if (key === "undefined" || key === "null" || seen.has(key)) continue;
      seen.add(key);
      out.push(row);
    }
    return out;
  }

  /* Trang 1 vừa tải → danh sách mới. Người dùng đã "Tải thêm" (nhiều hơn một trang) mà trang 1
     còn đầy: trang 1 thay phần đầu, phần sau giữ nguyên — không thu gọn (parity 43).
     Mốc là hàng cuối trang 1. Giữ hàng cũ hơn mốc (so mốc thời gian nên hàng MỚI chèn thêm ở đầu
     đẩy hàng cũ xuống vẫn đúng). Hai chỗ mốc thời gian không quyết được, và trước đây làm mất hàng:
       - BẰNG mốc: máy chủ ghi created_at tới micro-giây, JS chỉ đọc tới mili-giây, nên hai đề xuất
         tạo trong cùng một mili-giây là bằng nhau → dựa vào vị trí cũ (đã nằm sau trang 1 thì giữ);
       - mốc không đọc được (created_at hỏng/thiếu → 0): bỏ hẳn cách so thời gian, chỉ dựa vị trí.
     Hàng giữ lại sau lỗi 502 luôn nằm đầu danh sách cho tới khi bấm lại thành công. */
  function applyPage(kind, page) {
    const list = S.lists[kind];
    const cfg = LISTS[kind];
    const old = serverRows(kind);
    let rows = page;
    if (cfg.page && list.loaded && page.length >= cfg.page && old.length > cfg.page) {
      const ids = new Set(page.map(cfg.key));
      const last = cfg.order(page[page.length - 1]);
      rows = page.concat(old.filter((row, at) => {
        if (ids.has(cfg.key(row))) return false;
        if (!last) return at >= page.length;
        const order = cfg.order(row);
        return order < last || (order === last && at >= page.length);
      }));
    } else {
      list.hasMore = Boolean(cfg.page) && page.length >= cfg.page;
    }
    const have = new Set(rows.map(cfg.key));
    const kept = [];
    for (const [key, row] of S.retry) {
      if (key.startsWith(`${kind}:`) && !have.has(cfg.key(row))) kept.push(row);
    }
    list.rows = kept.concat(rows);
  }

  async function load(kind, { quiet = false } = {}) {
    if (!V) return;
    const ctx = V.ctx;
    const list = S.lists[kind];
    const cfg = LISTS[kind];
    const my = ++list.seq;
    const mut = list.mut;
    list.loading = true;
    if (!quiet) {
      list.error = null;
      list.locked = false;
      list.missing = false;
      render();
    }
    let outcome = "render";   // "stale" = kết quả đã cũ, bỏ; "again" = hỏi lại
    try {
      const data = await Shell.api(cfg.page ? cfg.url(cfg.page, 0) : cfg.url(), { signal: ctx.signal });
      if (my !== list.seq || ctx.signal.aborted) {
        outcome = "stale";
      } else if (list.mut !== mut) {
        // Một hành động vừa đổi danh sách trong lúc chờ: kết quả này có thể còn hàng vừa bỏ → hỏi lại.
        outcome = "again";
      } else {
        applyPage(kind, cleanRows(kind, data));
        list.loaded = true;
        list.error = null;
        list.stale = null;
        list.moreError = null;   // lần tải này thành công → lời lỗi "Tải thêm" lần trước hết hiệu lực
        list.locked = false;
        list.missing = false;
        if (kind === "pending" && isAdmin()) syncBadge({ fallback: false });
      }
    } catch (error) {
      if (my !== list.seq || isAbort(error) || ctx.signal.aborted) {
        outcome = "stale";
      } else if (error && error.status === 403 && !isAdmin()) {
        // F9 chưa có: thành viên bị chặn đọc — trạng thái khóa, không phải lỗi mạng.
        list.locked = true;
        list.loaded = false;
        list.rows = [];
        list.stale = null;
      } else if (isMissingApi(error)) {
        list.missing = true;
        list.loaded = false;
        list.rows = [];
        list.stale = null;
      } else if (list.loaded) {
        list.stale = error;
      } else {
        list.error = error;
      }
    } finally {
      if (my === list.seq) list.loading = false;
    }
    if (outcome === "stale") return;
    if (outcome === "again") {
      if (V && V.ctx === ctx) ctx.after(() => load(kind, { quiet: true }), 0);
      return;
    }
    render();
  }

  function refreshAll({ quiet = true } = {}) {
    S.refreshedAt = Date.now();
    for (const kind of allowedTabs()) {
      const list = S.lists[kind];
      if (list.loading || list.more) continue;
      load(kind, { quiet: quiet && list.loaded });
    }
  }

  function refreshQuiet(kind) {
    if (V && allowedTabs().includes(kind)) load(kind, { quiet: true });
  }

  async function loadMore(kind) {
    const list = S.lists[kind];
    const cfg = LISTS[kind];
    if (!V || !cfg.page || list.more || !list.hasMore) return;
    const ctx = V.ctx;
    list.more = true;
    list.moreError = null;
    render();
    try {
      // parity 41: offset = số hàng (thật) đã tải; hàng bị bỏ ở đây cũng đã rời danh sách của máy chủ.
      const data = await Shell.api(cfg.url(cfg.page, serverRows(kind).length), { signal: ctx.signal });
      if (ctx.signal.aborted) return;
      const page = cleanRows(kind, data);
      const have = new Set(list.rows.map(cfg.key));
      list.rows = list.rows.concat(page.filter((row) => !have.has(cfg.key(row))));
      list.hasMore = page.length >= cfg.page;
      if (kind === "pending" && isAdmin()) syncBadge({ fallback: false });
    } catch (error) {
      if (isAbort(error) || ctx.signal.aborted) return;
      // parity 42: app cũ im lặng khi "Tải thêm" hỏng — ở đây báo ngay dưới nút.
      list.moreError = error;
    } finally {
      list.more = false;
    }
    render();
  }

  /* Tổng hàng chờ duyệt: cùng lúc là badge "Ghi nhớ" ở thanh bên và tooltip của tab (để hai con số
     cạnh nhau không nói hai chuyện khác nhau). */
  function setPendingTotal(n) {
    Shell.setNavBadge("memory", n);
    if (S.pendingTotal === n) return;
    S.pendingTotal = n;
    render();
  }

  /* Đã tải hết hàng chờ → đếm tại chỗ (chính xác); còn trang sau → F8 GET /api/memory-review/count,
     máy chủ chưa có thì chỉ đếm trang ≤100 cho badge như khung app (không đủ chắc để gọi là tổng).
     fallback=false (gọi sau mỗi lần tải danh sách): máy chủ chưa có F8 thì thôi, không gọi thêm
     candidates?limit=100 mỗi 20 giây — khung app vẫn tự poll mỗi 60 giây. */
  async function syncBadge({ fallback = true } = {}) {
    if (!isAdmin()) return;
    const ctx = V ? V.ctx : null;
    const init = ctx ? { signal: ctx.signal } : undefined;
    const list = S.lists.pending;
    if (list.loaded && !list.hasMore) {
      setPendingTotal(serverRows("pending").length);
      return;
    }
    if (!S.countMissing) {
      try {
        const data = await Shell.api("/api/memory-review/count", init);
        const n = Number(data && data.pending);
        if (Number.isFinite(n)) setPendingTotal(n);
        return;
      } catch (error) {
        if (!isMissingApi(error)) return;
        S.countMissing = true;
        S.pendingTotal = null;
      }
    }
    if (!fallback) return;
    try {
      const rows = await Shell.api("/api/memory-review/candidates?limit=100", init);
      if (Array.isArray(rows)) Shell.setNavBadge("memory", rows.length);
    } catch { /* lần poll kế tiếp của khung app tự sửa */ }
  }

  /* ── hành động trên từng thẻ ─────────────────────────────────── */
  /* Bỏ một hàng khỏi danh sách (máy chủ cũng đã bỏ); mut tăng để kết quả làm mới đang bay về bị hỏi lại.
     Focus do restoreFocus() lo sau khi vẽ lại. */
  function dropRow(kind, key) {
    const list = S.lists[kind];
    const cfg = LISTS[kind];
    const index = list.rows.findIndex((row) => cfg.key(row) === key);
    if (index === -1) return;
    list.rows = list.rows.filter((row) => cfg.key(row) !== key);
    list.mut += 1;
    S.notes.delete(fullKey(kind, key));
    S.retry.delete(fullKey(kind, key));
  }

  /* Gửi một hành động ghi: khóa hai nút của thẻ, nhớ focus có đang ở thẻ không (để trả lại sau).
     Hành động ghi KHÔNG bị hủy khi rời màn hình (máy chủ đã nhận), nhưng phần việc trên màn hình thì
     có: nếu lúc kết quả về mà view đã rời hoặc đã mount lại (DOM khác), out.stale = true — trạng thái
     S và toast vẫn cập nhật, riêng focus thì không được đụng vào màn hình khác. */
  async function send(kind, key, action, path, init) {
    const id = fullKey(kind, key);
    if (S.busy.has(id)) return null;
    const ctx = V ? V.ctx : null;
    const entry = V && V.parts[kind] ? V.parts[kind].nodes.get(key) : null;
    const hadFocus = Boolean(entry && entry.node.contains(document.activeElement));
    S.busy.set(id, action);
    S.notes.delete(id);
    render();
    let out;
    try {
      out = { ok: true, data: await Shell.api(path, init) };
    } catch (error) {
      out = { ok: false, error };
    } finally {
      S.busy.delete(id);
    }
    out.stale = !ctx || !V || V.ctx !== ctx;
    out.hadFocus = hadFocus && !out.stale;
    out.index = out.stale || !V.parts[kind] ? -1 : [...V.parts[kind].listEl.children].indexOf(entry ? entry.node : null);
    return out;
  }

  /* Sau khi vẽ lại: trả focus cho nút vừa bấm, hoặc thẻ đứng vào chỗ thẻ vừa bỏ, hoặc tab đang chọn. */
  function restoreFocus(kind, key, action, out) {
    if (!V || !out || out.stale || !out.hadFocus) return;
    const at = document.activeElement;
    if (at && at !== document.body && V.page.contains(at) && at.isConnected) return;
    const P = V.parts[kind];
    const entry = P.nodes.get(key);
    if (entry && entry.focus(action)) return;
    const nodes = [...P.listEl.children];
    const next = nodes[Math.min(Math.max(out.index, 0), nodes.length - 1)];
    const target = next && next.querySelector("button:not(:disabled)");
    if (target) target.focus({ preventScroll: true });
    else if (V.seg) (V.seg.querySelector(".seg-item.is-active") || V.input).focus({ preventScroll: true });
  }

  async function approve(row) {
    const key = LISTS.pending.key(row);
    const id = fullKey("pending", key);
    const out = await send("pending", key, "approve", `/api/memory-review/candidates/${enc(row.candidate_id)}/approve`, { method: "POST" });
    if (!out) return;
    const error = out.error;
    if (out.ok) {
      dropRow("pending", key);
      toast("Đã duyệt — agent sẽ dùng ghi nhớ này.");
      refreshQuiet("applied");
      syncBadge();
    } else if (error.code === "MEMORY_MIRROR_FAILED") {
      // Đã ghi vào sổ ghi nhớ nhưng bản sao trên web hỏng; duyệt lại chỉ thử đồng bộ lại (idempotent).
      S.retry.set(id, row);
      S.notes.set(id, { tone: "warn", text: "Đã duyệt nhưng chưa đồng bộ được — bấm Duyệt lần nữa." });
      refreshQuiet("applied");
    } else if (error.code === "CANDIDATE_NOT_FOUND" || (error.code === "CANDIDATE_NOT_REVIEWABLE" && /already/i.test(error.message))) {
      dropRow("pending", key);
      toast(error.code === "CANDIDATE_NOT_FOUND" ? "Không còn đề xuất này — có thể đã được xử lý ở nơi khác." : reviewMessage(error), "danger");
      refreshQuiet("applied");
      syncBadge();
    } else if (error.code === "MEMORY_CONFLICT") {
      S.notes.set(id, { tone: "danger", text: reviewMessage(error) });
      refreshQuiet("pending");
      refreshQuiet("applied");
    } else {
      S.notes.set(id, { tone: "danger", text: reviewMessage(error, "Không duyệt được đề xuất.") });
    }
    render();
    restoreFocus("pending", key, "approve", out);
  }

  async function reject(row) {
    const key = LISTS.pending.key(row);
    const id = fullKey("pending", key);
    const out = await send("pending", key, "reject", `/api/memory-review/candidates/${enc(row.candidate_id)}/reject`, { method: "POST" });
    if (!out) return;
    const error = out.error;
    if (out.ok) {
      dropRow("pending", key);
      toast("Đã từ chối đề xuất.");
      syncBadge();
    } else if (error.code === "CANDIDATE_NOT_FOUND" || (error.code === "CANDIDATE_NOT_REVIEWABLE" && /already/i.test(error.message))) {
      dropRow("pending", key);
      toast(error.code === "CANDIDATE_NOT_FOUND" ? "Không còn đề xuất này — có thể đã được xử lý ở nơi khác." : reviewMessage(error), "danger");
      refreshQuiet("applied");
      syncBadge();
    } else {
      S.notes.set(id, { tone: "danger", text: reviewMessage(error, "Không từ chối được đề xuất.") });
    }
    render();
    restoreFocus("pending", key, "reject", out);
  }

  /* Thu hồi: như bảng điều khiển cũ — không hỏi lại (parity 47). */
  async function revert(row) {
    if (!isAdmin()) return;
    const key = LISTS.applied.key(row);
    const id = fullKey("applied", key);
    const out = await send("applied", key, "revert", `/api/memory-review/candidates/${enc(row.candidate_id)}/revert`, { method: "POST" });
    if (!out) return;
    const error = out.error;
    if (out.ok) {
      dropRow("applied", key);
      toast("Đã thu hồi — agent thôi dùng ghi nhớ này.");
    } else if (error.code === "MEMORY_MIRROR_FAILED") {
      // Sổ ghi nhớ đã thu hồi, bản sao trên web chưa gỡ được; thu hồi lại là idempotent.
      S.retry.set(id, row);
      S.notes.set(id, { tone: "warn", text: "Đã thu hồi nhưng chưa gỡ được bản sao trên web — bấm Thu hồi lần nữa." });
    } else if (error.code === "CANDIDATE_NOT_FOUND") {
      dropRow("applied", key);
      toast("Không còn ghi nhớ này — có thể đã được thu hồi ở nơi khác.", "danger");
    } else {
      S.notes.set(id, { tone: "danger", text: reviewMessage(error, "Không thu hồi được ghi nhớ.") });
      if (error.code === "CANDIDATE_NOT_REVIEWABLE") refreshQuiet("applied");
    }
    render();
    restoreFocus("applied", key, "revert", out);
  }

  /* "Tạo lại" và "Xóa" cùng gọi delete_batch trên máy chủ (api-admin §5): bản tóm tắt biến mất, tin gốc
     được trả về hàng chờ; bộ tóm tắt (nếu đang bật) tạo lại khi kênh đủ tin. */
  async function regenerate(row) {
    if (!isAdmin()) return;
    const key = LISTS.condense.key(row);
    const out = await send("condense", key, "regenerate", `/api/condensations/${enc(row.batch_id)}/regenerate`, { method: "POST" });
    if (!out) return;
    // Lời toast nói đúng như tooltip của nút: bộ tóm tắt mặc định TẮT (api-admin §5), nên không hứa
    // chắc là sẽ có bản mới.
    finishBatch(key, out, "Đã trả đoạn tin về hàng chờ — bộ tóm tắt sẽ tạo lại nếu đang bật.", "Không tạo lại được bản tóm tắt.");
    restoreFocus("condense", key, "regenerate", out);
  }

  async function removeBatch(row) {
    if (!isAdmin() || !V) return;
    const ok = await confirmDialog({
      title: "Xóa bản tóm tắt?",
      body: `Bản rút gọn ${spanText(row.from_sent_at, row.to_sent_at)} cùng các mệnh đề của nó bị xóa; tin nhắn gốc được trả về hàng chờ để bộ tóm tắt xử lý lại.`,
      confirmLabel: "Xóa",
      signal: V.ctx.signal,
    });
    if (!ok) return;
    const key = LISTS.condense.key(row);
    const out = await send("condense", key, "remove", `/api/condensations/${enc(row.batch_id)}`, { method: "DELETE" });
    if (!out) return;
    finishBatch(key, out, "Đã xóa bản tóm tắt.", "Không xóa được bản tóm tắt.");
    restoreFocus("condense", key, "remove", out);
  }

  function finishBatch(key, out, okText, failText) {
    const error = out.error;
    if (out.ok) {
      dropRow("condense", key);
      toast(okText);
    } else if (error.code === "CONDENSATION_NOT_FOUND") {
      dropRow("condense", key);
      toast("Không còn bản tóm tắt này — có thể đã được xử lý ở nơi khác.", "danger");
    } else {
      S.notes.set(fullKey("condense", key), { tone: "danger", text: errText(error, failText) });
    }
    render();
  }

  /* ── tìm ghi nhớ (POST /memory/search, parity 108 của Cài đặt cũ) ── */
  function setQuery(value) {
    S.query = value;
    S.search.seq += 1;   // mọi kết quả đang bay về đều đã cũ
    if (V) {
      V.clear.hidden = !value;
      if (V.stopSearch) { V.stopSearch(); V.stopSearch = null; }
    }
    const q = value.trim();
    if (!q) {
      S.search.status = "idle";
      S.search.query = "";
      S.search.rows = [];
      S.search.error = null;
    } else {
      if (S.search.status === "idle" || S.search.status === "error") S.search.status = "loading";
      if (V) V.stopSearch = V.ctx.after(() => runSearch(q), SEARCH_DELAY);
    }
    render();
  }

  async function runSearch(q) {
    if (!V) return;
    const ctx = V.ctx;
    const my = ++S.search.seq;
    S.search.status = "loading";
    S.search.error = null;
    render();
    try {
      const data = await Shell.api("/memory/search", {
        method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ query: q, top_k: 10 }), signal: ctx.signal,
      });
      if (my !== S.search.seq || ctx.signal.aborted) return;
      S.search.rows = Array.isArray(data) ? data.filter((row) => row && typeof row === "object" && searchKey(row)) : [];
      S.search.query = q;
      S.search.status = "ok";
    } catch (error) {
      if (my !== S.search.seq || isAbort(error) || ctx.signal.aborted) return;
      S.search.status = "error";
      S.search.error = error;
      S.search.query = q;
    }
    render();
  }

  function clearSearch({ focus = false } = {}) {
    if (!V) return;
    V.input.value = "";
    setQuery("");
    if (focus) V.input.focus({ preventScroll: true });
  }

  /* Xóa ghi nhớ (admin): hỏi → DELETE /memory/{memory_id} → bỏ khỏi kết quả + toast (parity 108).
     Lời hỏi giữ nguyên câu của trang cũ; bản sao "mem_dc_…" của ghi nhớ Discord nói thêm một câu vì
     xóa chỉ gỡ khỏi trò chuyện web — bot Discord đọc sổ ghi nhớ gốc (discord_turn_service). */
  async function deleteMemory(row) {
    if (!isAdmin() || !V) return;
    const key = searchKey(row);
    if (!key) return;
    const mirror = key.startsWith("mem_dc_");
    const ok = await confirmDialog({
      title: "Xóa ghi nhớ?",
      body: mirror
        ? "Trợ lý sẽ không dùng ghi nhớ này nữa. Đây là bản sao trên web của một ghi nhớ Discord: bot Discord vẫn dùng bản gốc — muốn thu hồi hẳn, dùng «Thu hồi» ở tab Đang hiệu lực."
        : "Trợ lý sẽ không dùng ghi nhớ này nữa.",
      confirmLabel: "Xóa",
      signal: V.ctx.signal,
    });
    if (!ok || !V) return;
    const ctx = V.ctx;
    const id = fullKey("search", key);
    if (S.busy.has(id)) return;
    // confirmDialog trả focus về nút "Xóa" của hàng; hàng sắp biến mất nên nhớ chỗ để trả focus lại.
    const P = V.parts.search;
    const entry = P.nodes.get(key);
    const out = {
      hadFocus: Boolean(entry && entry.node.contains(document.activeElement)),
      index: [...P.listEl.children].indexOf(entry ? entry.node : null),
    };
    S.busy.set(id, "delete");
    render();
    try {
      // Không truyền signal: rời màn hình không được hủy một lệnh xóa đã gửi đi (như send()).
      await Shell.api(`/memory/${enc(key)}`, { method: "DELETE" });
      S.search.rows = S.search.rows.filter((item) => searchKey(item) !== key);
      toast("Đã xóa ghi nhớ.");
    } catch (error) {
      if (error && error.code === "MEMORY_NOT_FOUND") {
        S.search.rows = S.search.rows.filter((item) => searchKey(item) !== key);
        toast("Ghi nhớ này không còn nữa.", "danger");
      } else if (!isAbort(error)) {
        toast(errText(error, "Không xóa được ghi nhớ."), "danger");
      }
    } finally {
      S.busy.delete(id);
    }
    out.stale = !V || V.ctx !== ctx;
    if (out.stale) out.hadFocus = false;
    render();
    restoreFocus("search", key, "delete", out);
  }

  /* ── dựng thẻ / hàng ─────────────────────────────────────────── */
  /* Một vùng aria-live duy nhất cho cả màn hình. Ghi chú lỗi trên thẻ, biển "đang hiện dữ liệu lần
     trước" và lỗi "Tải thêm" đều nằm trong khối có thể đang ẩn (hoặc thuộc tab khác): ghi chữ vào một
     nút đang display:none thì đọc màn hình không đọc. Nên chữ hiện ở đâu thì cũng báo qua đây, và chỉ
     báo khi nội dung ĐỔI. Toast do khung app tự đọc. */
  function announce(text) {
    if (!V || !text) return;
    if (V.live.textContent === text) V.live.textContent = "";
    V.live.textContent = text;
  }

  /* Mỗi thẻ trả về {node, sync(), focus(action)}: sync() áp trạng thái đang gửi + ghi chú mà không dựng lại. */
  function noteEl() {
    return h("p", { class: "note mv-note" });
  }

  /* Không dùng [hidden]: khối rỗng tự ẩn bằng CSS (.mv-note:empty) để nút luôn nằm trong DOM. */
  function syncNote(el, note) {
    const text = note ? note.text : "";
    if (el.textContent !== text) {
      el.textContent = text;
      announce(text);
    }
    el.classList.toggle("tone-danger", Boolean(note) && note.tone === "danger");
    el.classList.toggle("tone-warn", Boolean(note) && note.tone === "warn");
  }

  function setLabel(button, state, busyText, idle) {
    if (button._state === state) return;
    button._state = state;
    button.replaceChildren(...(state === "busy" ? [busyText] : idle()));
  }

  function buildCandidate(row, key) {
    const id = fullKey("pending", key);
    const conf = percent(row.confidence);
    const tone = conf === null ? null : conf < 70 ? "warn" : "ok";
    const fact = String(row.canonical_fact ?? "").trim();
    const author = String(row.author_display_name || row.author_id || "?");
    const evidence = row.evidence_text ? String(row.evidence_text) : "";
    const source = row.source_text ? String(row.source_text) : "";
    const channel = String(row.channel_id || "");
    const when = row.created_at ? fmtDate(row.created_at, { time: true }) : null;

    const approveBtn = h("button", { type: "button", class: "btn btn-34 btn-primary btn-flex", onClick: () => approve(row) });
    const rejectBtn = h("button", { type: "button", class: "btn btn-34 btn-outline btn-flex", onClick: () => reject(row) });
    const note = noteEl();
    const node = h("article", { class: "card card-p16 mv-cand", dataset: { key }, "aria-label": fact || "Đề xuất xóa ghi nhớ" },
      h("div", { class: "mv-cand-head" },
        h("span", { class: "tag", title: row.scope ? `Phạm vi: ${row.scope}` : null }, row.memory_type || "?"),
        h("span", {
          class: "mv-cand-author",
          title: [author, when && `đề xuất ${when}`, channel && `kênh …${channel.slice(-6)}`].filter(Boolean).join(" · "),
        }, `${author} · Discord`),
        h("span", {
          class: ["mv-conf", tone && `is-${tone}`],
          title: conf === null ? "Máy chủ không ghi độ tin cậy" : `Độ tin cậy ${conf}%`,
        }, conf === null ? "—" : `${conf}%`)),
      fact
        ? h("div", { class: "mv-fact" }, fact)
        : h("div", { class: "mv-fact is-empty" }, "(đề xuất xóa ghi nhớ)"),
      evidence || source
        ? h("div", { class: "quote mv-evidence" },
          evidence ? `«${evidence}»` : null,
          source ? h("div", { class: ["mv-source", !evidence && "is-first"] }, `tin gốc: ${source}`) : null)
        : null,
      h("div", { class: "progress progress-4", "aria-hidden": "true" },
        conf === null ? null : h("div", { class: "fill", style: { width: `${conf}%`, background: `var(--${tone})` } })),
      h("div", { class: "mv-cand-actions" }, approveBtn, rejectBtn),
      note);

    return {
      node,
      sync() {
        const busy = S.busy.get(id);
        approveBtn.disabled = Boolean(busy);
        rejectBtn.disabled = Boolean(busy);
        node.setAttribute("aria-busy", String(Boolean(busy)));
        setLabel(approveBtn, busy === "approve" ? "busy" : "idle", "Đang duyệt…",
          () => [icon("check", { size: 13, sw: 2.5 }), "Duyệt"]);
        setLabel(rejectBtn, busy === "reject" ? "busy" : "idle", "Đang từ chối…", () => ["Từ chối"]);
        syncNote(note, S.notes.get(id));
      },
      focus(action) {
        const target = action === "reject" ? rejectBtn : approveBtn;
        if (target.disabled || !target.isConnected) return false;
        target.focus({ preventScroll: true });
        return true;
      },
    };
  }

  /* "🤖 agent · 88%" khi agent tự áp dụng; "👤 admin" khi duyệt trên web (máy chủ ghi "dashboard");
     giá trị khác (vd. "e2e-eval") hiện nguyên văn. */
  function appliedBy(row) {
    const by = String(row.applied_by || "");
    const conf = percent(row.confidence);
    const confText = conf === null ? "" : ` · độ tin cậy ${conf}%`;
    if (by === "agent") return { text: conf === null ? "🤖 agent" : `🤖 agent · ${conf}%`, title: `Agent tự áp dụng${confText}` };
    if (by === "dashboard") return { text: "👤 admin", title: `Quản trị viên duyệt trên web${confText}` };
    return { text: `👤 ${by || "?"}`, title: `Duyệt bởi ${by || "không rõ"}${confText}` };
  }

  function buildApplied(row, key) {
    const id = fullKey("applied", key);
    const fact = String(row.canonical_fact ?? "").trim();
    const meta = [
      row.memory_type || "?",
      row.version !== null && row.version !== undefined ? `v${row.version}` : null,
      row.author_display_name || row.author_id || null,
      row.applied_at ? fmtDate(row.applied_at) : null,
    ].filter(Boolean).join(" · ");
    const by = appliedBy(row);
    const note = noteEl();
    const revertBtn = isAdmin()
      ? h("button", { type: "button", class: "btn btn-30 btn-outline hover-danger", onClick: () => revert(row) })
      : null;
    const node = h("div", { class: "mv-row", dataset: { key } },
      h("span", { class: "icon-tile icon-tile-34 tone-accent" }, icon("lightbulb", { size: 16 })),
      h("div", { class: "mv-row-text" },
        h("div", { class: ["mv-row-fact", !fact && "is-empty"] }, fact || "(không có nội dung)"),
        h("div", { class: "mv-row-meta" }, meta),
        note),
      h("span", { class: "chip-meta", title: by.title }, by.text),
      revertBtn);
    return {
      node,
      sync() {
        const busy = S.busy.get(id);
        node.setAttribute("aria-busy", String(Boolean(busy)));
        if (revertBtn) {
          revertBtn.disabled = Boolean(busy);
          setLabel(revertBtn, busy ? "busy" : "idle", "Đang thu hồi…", () => ["Thu hồi"]);
        }
        syncNote(note, S.notes.get(id));
      },
      focus() {
        if (!revertBtn || revertBtn.disabled || !revertBtn.isConnected) return false;
        revertBtn.focus({ preventScroll: true });
        return true;
      },
    };
  }

  function batchTitle(row) {
    const st = BATCH[row.status];
    const parts = [st ? st.hint : `Trạng thái: ${row.status || "?"}`];
    if (row.error_code) parts.push(`lỗi: ${BATCH_ERROR[row.error_code] ? `${BATCH_ERROR[row.error_code]} (${row.error_code})` : row.error_code}`);
    if (row.model_used) parts.push(`model ${row.model_used}`);
    return parts.join(" · ");
  }

  function buildBatch(row, key) {
    const id = fullKey("condense", key);
    const st = BATCH[row.status] || { tone: "muted" };
    const channel = String(row.channel_id || "");
    const props = Array.isArray(row.propositions) ? row.propositions.filter((p) => p && typeof p === "object") : [];
    const status = pill(String(row.status || "?"), st.tone, { dot: false, size: "sm" });
    status.classList.add("pill-auto", "mv-batch-pill");
    status.title = batchTitle(row);
    const note = noteEl();
    const regenBtn = h("button", {
      type: "button", class: "btn btn-30 btn-outline hover-bg", onClick: () => regenerate(row),
      title: "Bỏ bản này và trả tin nhắn về hàng chờ; bộ tóm tắt (nếu đang bật) tạo lại khi kênh đủ tin.",
    });
    const delBtn = h("button", { type: "button", class: "btn btn-30 btn-ghost-danger", onClick: () => removeBatch(row) });
    // message_count thiếu/null → "?" như nửa "kênh ?" bên cạnh, chứ không phải "0 tin" (Number(null) = 0).
    const count = row.message_count === null || row.message_count === undefined ? NaN : Number(row.message_count);
    const node = h("article", { class: "card card-p14 mv-batch", dataset: { key } },
      h("div", { class: "mv-batch-side" },
        h("div", { class: "mv-batch-span" }, spanText(row.from_sent_at, row.to_sent_at)),
        h("div", { class: "mv-batch-meta", title: channel ? `Kênh ${channel}` : null },
          `${Number.isFinite(count) ? fmtNumber(count) : "?"} tin · kênh ${channel ? `…${channel.slice(-6)}` : "?"}`),
        status),
      h("div", { class: "mv-batch-body" },
        props.length
          ? h("ul", { class: "mv-props" }, props.map((p) => h("li", null,
            String(p.content ?? ""), " ", h("span", { class: "mv-speaker" }, `— ${p.speaker || p.speaker_id || "?"}`))))
          : h("p", { class: "mv-props is-empty" }, row.error_code ? `lỗi: ${row.error_code}` : "không có mệnh đề nào"),
        note),
      isAdmin() ? h("div", { class: "mv-batch-actions" }, regenBtn, delBtn) : null);
    return {
      node,
      sync() {
        const busy = S.busy.get(id);
        node.setAttribute("aria-busy", String(Boolean(busy)));
        regenBtn.disabled = Boolean(busy);
        delBtn.disabled = Boolean(busy);
        setLabel(regenBtn, busy === "regenerate" ? "busy" : "idle", "Đang xử lý…", () => ["Tạo lại"]);
        setLabel(delBtn, busy === "remove" ? "busy" : "idle", "Đang xử lý…", () => ["Xóa"]);
        syncNote(note, S.notes.get(id));
      },
      focus(action) {
        const target = action === "remove" ? delBtn : regenBtn;
        if (target.disabled || !target.isConnected) return false;
        target.focus({ preventScroll: true });
        return true;
      },
    };
  }

  function buildResult(row, key) {
    const id = fullKey("search", key);
    const imp = Number(row.importance);
    const importance = row.importance === null || row.importance === undefined || !Number.isFinite(imp)
      ? "?" : fmtNumber(Math.round(imp * 100) / 100);
    const mirror = key.startsWith("mem_dc_");
    const delBtn = isAdmin()
      ? h("button", { type: "button", class: "btn btn-30 btn-ghost-danger", onClick: () => deleteMemory(row) })
      : null;
    const content = String(row.content ?? "").trim();
    const node = h("div", { class: "mv-row", dataset: { key } },
      h("span", { class: "icon-tile icon-tile-34 tone-accent" }, icon("lightbulb", { size: 16 })),
      h("div", { class: "mv-row-text" },
        h("div", { class: ["mv-row-fact", !content && "is-empty"] }, content || "(không có nội dung)"),
        h("div", { class: "mv-row-meta" }, `${row.memory_type || "ghi nhớ"} · độ quan trọng ${importance}`)),
      mirror ? h("span", { class: "chip-meta", title: "Bản sao trên web của một ghi nhớ Discord đã áp dụng" }, "từ Discord") : null,
      delBtn);
    return {
      node,
      sync() {
        if (!delBtn) return;
        const busy = S.busy.get(id);
        delBtn.disabled = Boolean(busy);
        setLabel(delBtn, busy ? "busy" : "idle", "Đang xóa…", () => ["Xóa"]);
      },
      focus() {
        if (!delBtn || delBtn.disabled || !delBtn.isConnected) return false;
        delBtn.focus({ preventScroll: true });
        return true;
      },
    };
  }

  const BUILD = { pending: buildCandidate, applied: buildApplied, condense: buildBatch, search: buildResult };

  /* Chữ ký một hàng = ĐÚNG những trường mà thẻ vẽ ra. Trường khác đổi (vd. validation_status, hay
     mốc thời gian máy chủ tính lại mỗi lần gọi) thì không dựng lại thẻ: không chạy lại hiệu ứng vào
     và không cướp focus của người đang duyệt giữa chừng. */
  const SIG = {
    pending: (row) => JSON.stringify([row.memory_type, row.scope, row.author_display_name, row.author_id,
      row.created_at, row.channel_id, row.confidence, row.canonical_fact, row.evidence_text, row.source_text]),
    applied: (row) => JSON.stringify([row.canonical_fact, row.memory_type, row.version, row.author_display_name,
      row.author_id, row.applied_at, row.applied_by, row.confidence]),
    condense: (row) => JSON.stringify([row.status, row.error_code, row.model_used, row.channel_id,
      row.message_count, row.from_sent_at, row.to_sent_at,
      (Array.isArray(row.propositions) ? row.propositions : []).map((p) => (p ? [p.content, p.speaker, p.speaker_id] : null))]),
    search: (row) => JSON.stringify([row.content, row.memory_type, row.importance]),
  };

  /* ── khung chờ / trạng thái ──────────────────────────────────── */
  function skeletonFor(kind) {
    if (kind === "pending") {
      return h("div", { class: "mv-grid", "aria-hidden": "true" }, [0, 1].map(() => h("div", { class: "card card-p16 mv-cand mv-skel" },
        skeleton({ w: "55%", h: 14 }), skeleton({ w: "85%", h: 16 }), skeleton({ w: "70%", h: 12 }),
        skeleton({ w: "100%", h: 4, r: 2 }),
        h("div", { class: "mv-cand-actions" }, skeleton({ w: "50%", h: 34, r: 9 }), skeleton({ w: "50%", h: 34, r: 9 })))));
    }
    if (kind === "condense") {
      return h("div", { class: "mv-stack", "aria-hidden": "true" }, [0, 1].map(() => h("div", { class: "card card-p14 mv-batch mv-skel" },
        h("div", { class: "mv-batch-side mv-skel-col" }, skeleton({ w: "80%", h: 13 }), skeleton({ w: "60%", h: 11 }), skeleton({ w: 64, h: 20, r: 999 })),
        h("div", { class: "mv-batch-body mv-skel-col" }, skeleton({ w: "75%", h: 13 }), skeleton({ w: "50%", h: 13 })))));
    }
    return h("div", { class: "card card-flush", "aria-hidden": "true" }, [0, 1, 2].map(() => h("div", { class: "mv-row mv-skel" },
      skeleton({ w: 34, h: 34, r: 10 }),
      h("div", { class: "mv-row-text mv-skel-col" }, skeleton({ w: "55%", h: 13 }), skeleton({ w: "35%", h: 11 })))));
  }

  function stateCard(node) {
    return h("div", { class: "card mv-state" }, node);
  }

  function errorCard(title, error, onRetry) {
    const node = emptyState({
      icon: "alert", tone: "danger", title, text: errText(error),
      action: { label: "Thử lại", icon: "retry", onClick: onRetry },
    });
    node.classList.add("is-error");
    node.setAttribute("role", "alert");
    return stateCard(node);
  }

  /* Thành viên bị 403: nói thêm một câu về ô tìm, vì ô tìm (POST /memory/search) chỉ cần quyền đọc
     nên vẫn tra được đúng những ghi nhớ này — để hai thứ trên cùng màn hình không nói ngược nhau. */
  function lockedCard(kind) {
    const node = emptyState({
      icon: "lock",
      title: "Chỉ quản trị viên xem được danh sách này.",
      text: "Máy chủ chưa mở quyền đọc cho thành viên. Ô tìm bên trên vẫn tra được từng ghi nhớ.",
    });
    node.append(h("code", { class: "code" }, LISTS[kind].endpoint));
    node.classList.add("is-missing");
    return stateCard(node);
  }

  /* ── vẽ ──────────────────────────────────────────────────────── */
  /* Giữ nguyên nút DOM của hàng không đổi (không chạy lại hiệu ứng vào, không mất focus). */
  function reconcile(part, rows, keyOf, kind) {
    const seen = new Set();
    let at = 0;
    for (const row of rows) {
      const key = keyOf(row);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      const sig = SIG[kind](row);
      let entry = part.nodes.get(key);
      if (entry && entry.sig !== sig) {
        entry.node.remove();
        entry = null;
      }
      if (!entry) {
        entry = BUILD[kind](row, key);
        entry.sig = sig;
        part.nodes.set(key, entry);
      }
      entry.sync();
      const current = part.listEl.children[at];
      if (current !== entry.node) part.listEl.insertBefore(entry.node, current || null);
      at += 1;
    }
    for (const [key, entry] of part.nodes) {
      if (!seen.has(key)) {
        entry.node.remove();
        part.nodes.delete(key);
      }
    }
  }

  /* Đổi khối nội dung khi trạng thái đổi (đang tải / lỗi / khóa / rỗng / danh sách). */
  function showState(part, state, build, token) {
    if (part.state === state && part.token === token) return;
    part.state = state;
    part.token = token;
    part.body.replaceChildren(build());
  }

  function renderTabs() {
    let changed = V.shownTab !== S.tab;
    for (const item of V.tabItems) {
      const text = countText(item.value);
      if (item.badge.textContent !== (text ?? "")) {
        item.badge.textContent = text ?? "";
        changed = true;
      }
      // Chưa biết số (đang tải / khóa / chưa có API): để trống nhưng GIỮ CHỖ — [hidden] sẽ bỏ khối
      // khỏi luồng và dải tab nhảy ngang ~75px mỗi lần vào màn hình.
      item.badge.classList.toggle("is-blank", text === null);
      const hint = countHint(item.value);
      if (hint) item.badge.title = hint;
      else item.badge.removeAttribute("title");
    }
    if (V.seg.value !== S.tab) V.seg.setValue(S.tab);
    V.shownTab = S.tab;
    if (changed) revealTab();
  }

  /* Màn hẹp: dải tab cuộn ngang trong khung của nó — kéo tab đang chọn vào tầm nhìn khi tab hoặc số
     đếm đổi (không đụng cuộn dọc của trang như scrollIntoView). Đang cuộn được thì gắn .is-scrollable
     để CSS làm mờ hai mép: thanh cuộn bị giấu nên nếu không có dấu hiệu gì, chữ bị cắt trông như lỗi
     vẽ chứ không ra "còn tab nữa bên cạnh". */
  function revealTab() {
    const seg = V.seg;
    const scrollable = seg.scrollWidth > seg.clientWidth + 1;
    seg.classList.toggle("is-scrollable", scrollable);
    if (!scrollable) return;
    const item = seg.querySelector(".seg-item.is-active");
    if (!item) return;
    const box = seg.getBoundingClientRect();
    const at = item.getBoundingClientRect();
    if (at.left < box.left) seg.scrollLeft -= box.left - at.left + 4;
    else if (at.right > box.right) seg.scrollLeft += at.right - box.right + 4;
  }

  function renderList(kind) {
    const part = V.parts[kind];
    const list = S.lists[kind];
    const cfg = LISTS[kind];
    const staleText = list.stale ? `Không làm mới được — đang hiện dữ liệu lần trước. ${errText(list.stale, "")}`.trim() : "";
    part.stale.hidden = !staleText;
    if (part.staleText.textContent !== staleText) {
      part.staleText.textContent = staleText;
      announce(staleText);
    }

    let state;
    if (list.locked) state = "locked";
    else if (list.missing) state = "missing";
    else if (!list.loaded && list.error) state = "error";
    else if (!list.loaded) state = "loading";
    else if (!list.rows.length) state = "empty";
    else state = "list";

    if (state === "locked") showState(part, state, () => lockedCard(kind));
    else if (state === "missing") showState(part, state, () => stateCard(missingApiState({ feature: cfg.feature, endpoint: cfg.endpoint })));
    else if (state === "error") showState(part, state, () => errorCard(cfg.errorTitle, list.error, () => load(kind)), list.error);
    else if (state === "loading") showState(part, state, () => skeletonFor(kind));
    else if (state === "empty") showState(part, state, () => stateCard(emptyState({ ...EMPTY[kind], tone: kind === "pending" ? "ok" : "muted" })));
    else {
      showState(part, state, () => part.listEl);
      reconcile(part, list.rows, cfg.key, kind);
    }
    part.body.setAttribute("aria-busy", String(state === "loading"));

    if (part.more) {
      const show = state === "list" && (list.hasMore || Boolean(list.moreError));
      part.more.hidden = !show;
      part.moreBtn.hidden = !list.hasMore;
      part.moreBtn.disabled = list.more;
      part.moreBtn.textContent = list.more ? "Đang tải…" : "Tải thêm";
      const moreText = list.moreError ? `Không tải thêm được: ${errText(list.moreError, "lỗi không xác định")}` : "";
      part.moreErr.hidden = !moreText;
      if (part.moreErr.textContent !== moreText) {
        part.moreErr.textContent = moreText;
        announce(moreText);
      }
    }
    if (part.intro) part.intro.hidden = state === "locked";
  }

  function renderSearch() {
    const part = V.parts.search;
    const st = S.search;
    const q = S.query.trim();
    const n = st.rows.length;
    let head;
    if (st.status === "loading") head = ["Đang tìm ", h("strong", null, `«${q}»`), "…"];
    else if (st.status === "ok") head = n ? [`${fmtNumber(n)} ghi nhớ khớp `, h("strong", null, `«${st.query}»`)] : ["Không có ghi nhớ nào khớp ", h("strong", null, `«${st.query}»`)];
    else if (st.status === "error") head = ["Tìm ", h("strong", null, `«${st.query}»`), " không thành công"];
    else head = [];
    part.head.replaceChildren(...head);

    let state;
    if (st.status === "error") state = "error";
    else if (st.status === "loading" && !n) state = "loading";
    else if (st.status === "ok" && !n) state = "empty";
    else state = "list";
    if (state === "error") showState(part, state, () => errorCard("Không tìm được ghi nhớ.", st.error, () => runSearch(S.query.trim())), st.error);
    else if (state === "loading") showState(part, state, () => skeletonFor("search"));
    else if (state === "empty") {
      showState(part, state, () => stateCard(emptyState({
        icon: "search", title: "Không tìm thấy ghi nhớ nào khớp.", text: "Tìm theo nghĩa trong các ghi nhớ đã lưu, gồm cả bản sao của ghi nhớ Discord.",
      })));
    } else {
      showState(part, state, () => part.listEl);
      reconcile(part, st.rows, searchKey, "search");
    }
    part.body.setAttribute("aria-busy", String(st.status === "loading"));
    part.listEl.classList.toggle("is-busy", st.status === "loading");
  }

  function render() {
    if (!V) return;
    renderTabs();
    const searching = Boolean(S.query.trim());
    for (const kind of KINDS) V.panels[kind].hidden = searching || S.tab !== kind;
    V.panels.search.hidden = !searching;
    if (searching) renderSearch();
    else renderList(S.tab);
  }

  /* ── mount ───────────────────────────────────────────────────── */
  function buildPanel(kind) {
    const staleText = h("span");
    const part = {
      intro: INTRO[kind] ? h("p", { class: "mv-intro" }, INTRO[kind]) : null,
      // Không gắn role=status ở đây: khối này có lúc bị ẩn / thuộc tab khác → báo qua V.live.
      stale: h("div", { class: "banner-warn mv-stale", hidden: true }, icon("alert", { size: 15 }), staleText),
      staleText,
      body: h("div", { class: "mv-body" }),
      listEl: kind === "pending" ? h("div", { class: "mv-grid" })
        : kind === "condense" ? h("div", { class: "mv-stack" })
          : h("div", { class: "card card-flush mv-list" }),
      nodes: new Map(),
      state: null,
      token: null,
      more: null,
    };
    if (LISTS[kind].page) {
      part.moreBtn = h("button", { type: "button", class: "btn btn-34 btn-outline px-16", onClick: () => loadMore(kind) }, "Tải thêm");
      part.moreErr = h("p", { class: "mv-more-error", hidden: true });
      part.more = h("div", { class: "mv-more", hidden: true }, part.moreBtn, part.moreErr);
    }
    const panel = h("section", { class: "mv-panel", "aria-label": TAB_LABEL[kind], hidden: true },
      part.intro, part.stale, part.body, part.more);
    return { panel, part };
  }

  function mount(ctx) {
    ctx.setHeader("Ghi nhớ", "Điều agent nhớ và dùng ở cả web lẫn Discord");
    const role = isAdmin() ? "admin" : "member";
    if (S.role !== role) {
      // Vai trò khác lần trước (đăng nhập lại): không giữ dữ liệu / trạng thái đã tải bằng vai trò cũ.
      S.lists = { pending: newList(), applied: newList(), condense: newList() };
      S.busy.clear();
      S.notes.clear();
      S.retry.clear();
      S.pendingTotal = null;
      S.role = role;
    }
    // Yêu cầu của lần mount trước đã bị hủy theo ctx.signal nhưng promise chưa kịp về: đừng để cờ
    // "đang tải" cũ chặn lần tải mới (kết quả cũ tự bị bỏ nhờ số thứ tự).
    for (const kind of KINDS) {
      S.lists[kind].loading = false;
      S.lists[kind].more = false;
    }
    // Ghi chú lỗi thuộc về lần bấm sinh ra nó: rời màn hình rồi quay lại thì một lỗi 500 mười phút
    // trước không được hiện như vừa xảy ra. Riêng hàng 502 chưa đồng bộ xong là việc còn dở thật —
    // giữ lại, nhưng nói rõ là chuyện của lần trước.
    S.notes.clear();
    for (const id of S.retry.keys()) {
      S.notes.set(id, id.startsWith("pending:")
        ? { tone: "warn", text: "Lần trước đã duyệt nhưng chưa đồng bộ được — bấm Duyệt lần nữa." }
        : { tone: "warn", text: "Lần trước đã thu hồi nhưng chưa gỡ được bản sao trên web — bấm Thu hồi lần nữa." });
    }
    S.tab = pickTab(ctx.query);
    S.query = "";
    S.search = { seq: S.search.seq + 1, status: "idle", query: "", rows: [], error: null };

    const tabs = allowedTabs();
    const seg = segmented(tabs.map((value) => ({ value, label: TAB_LABEL[value], badge: "" })), S.tab, (value) => {
      // Chọn ngay (seg không nhảy về tab cũ khi vẽ lại trước hashchange), rồi ghi vào URL: update() lo phần còn lại.
      S.tab = value;
      if (S.query) clearSearch();
      else render();
      if (V) V.page.scrollTop = 0;
      Router.go(`#/memory?tab=${value}`);
    }, { variant: "bordered", size: "lg", label: "Nhóm ghi nhớ" });
    seg.classList.add("mv-tabs");
    // Đang tìm mà bấm lại chính tab đang chọn: về nội dung tab (seg không gọi onChange khi giá trị không đổi).
    seg.addEventListener("click", (event) => {
      const item = event.target.closest(".seg-item");
      if (item && item.classList.contains("is-active") && S.query) clearSearch();
    });
    const tabItems = [...seg.querySelectorAll(".seg-item")].map((item, i) => ({ value: tabs[i], badge: item.querySelector(".badge-count") }));

    const input = h("input", {
      type: "text", placeholder: "Tìm ghi nhớ…", "aria-label": "Tìm ghi nhớ", autocomplete: "off", spellcheck: "false", maxlength: 10000,
      onInput: (event) => setQuery(event.target.value),
      onKeydown: (event) => {
        if (event.key === "Escape" && event.target.value) {
          event.preventDefault();
          clearSearch();
        }
      },
    });
    const clear = h("button", {
      type: "button", class: "mv-search-clear", title: "Xóa ô tìm", "aria-label": "Xóa ô tìm", hidden: true,
      onClick: () => clearSearch({ focus: true }),
    }, icon("x", { size: 13 }));
    /* Không dùng <label> bọc: nút "Xóa ô tìm" nằm bên trong sẽ nhận thêm một cú nhấp
       thứ hai do nhãn chuyển tiếp vào ô nhập (cùng mẫu đã sửa ở views/documents.js). */
    const toolbar = h("div", { class: "toolbar mv-toolbar" },
      seg, h("div", {
        class: "search mv-search",
        onClick: (event) => { if (!event.target.closest("button, input")) input.focus(); },
      }, icon("search", { size: 15 }), input, clear));

    const panels = {};
    const parts = {};
    for (const kind of KINDS) {
      const built = buildPanel(kind);
      panels[kind] = built.panel;
      parts[kind] = built.part;
    }
    const searchHead = h("p", { class: "mv-search-head", role: "status" });
    parts.search = {
      head: searchHead, body: h("div", { class: "mv-body" }), listEl: h("div", { class: "card card-flush mv-list" }),
      nodes: new Map(), state: null, token: null,
    };
    panels.search = h("section", { class: "mv-panel", "aria-label": "Kết quả tìm ghi nhớ", hidden: true }, searchHead, parts.search.body);

    const live = h("p", { class: "sr-only", role: "status" });
    const page = h("div", { class: "page mv-page" },
      h("div", { class: "page-inner w-980" }, toolbar, panels.pending, panels.applied, panels.condense, panels.search, live));
    ctx.root.append(page);
    V = { ctx, page, seg, tabItems, input, clear, panels, parts, live, stopSearch: null, shownTab: null };

    // 20 giây/lần khi đang xem (như bảng điều khiển cũ); không làm mới lúc đang gửi một hành động.
    ctx.every(() => {
      if (document.hidden || S.busy.size) return;
      refreshAll();
    }, REFRESH_MS);
    ctx.on(document, "visibilitychange", () => {
      if (!document.hidden && !S.busy.size && Date.now() - S.refreshedAt >= REFRESH_MS) refreshAll();
    });
    // Đổi bề ngang có thể làm dải tab thôi/bắt đầu cuộn được → xét lại dấu hiệu cuộn.
    ctx.on(window, "resize", () => { if (V) revealTab(); });

    render();
    syncTabUrl(ctx, S.tab);
    refreshAll();
  }

  /* Vai trò hiện tại không được xem ?tab= đang ghi trên URL (vd. thành viên mở ?tab=pending): đã hạ
     xuống tab khác thì ghi lại URL cho khớp thứ đang hiện, để link chia sẻ / tải lại không còn sai. */
  function syncTabUrl(ctx, tab) {
    const want = ctx.query.get("tab");
    if (want === null || want === tab) return;
    ctx.after(() => { if (V && V.ctx === ctx) Router.replace(`#/memory?tab=${tab}`); }, 0);
  }

  /* #/memory?tab=… đổi tab tại chỗ, không mount lại. Cùng hash (Router.go lại) → làm mới. */
  function update(ctx, info) {
    if (!V || V.ctx !== ctx) return false;
    const tab = pickTab(ctx.query);
    if (tab !== S.tab) {
      S.tab = tab;
      V.page.scrollTop = 0;
      // Back/Forward đổi tab cũng bỏ ô tìm, như khi bấm thẳng vào tab — nếu không thì kết quả tìm
      // vẫn che nội dung tab vừa chuyển tới.
      if (S.query) clearSearch();
    }
    syncTabUrl(ctx, tab);
    if (info && info.same) refreshAll();
    render();
    return true;
  }

  function unmount() {
    V = null;
  }

  Router.register("memory", { admin: false, mount, update, unmount });
})();
