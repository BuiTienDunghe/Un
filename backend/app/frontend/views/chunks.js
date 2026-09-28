/* ══════════════════════════════════════════════════════════════════
   /ui/views/chunks.js — màn hình "Đoạn" (#/chunks/<documentId>).

   Một IIFE, không tên top-level. Xem một tài liệu đã lập chỉ mục bị cắt
   thành những đoạn nào — đúng thứ bộ truy xuất đọc được, không phải bản
   gốc. Link cũ /ui/chunks.html?document_id=… đã được redirect sang đây.

   Hợp đồng API (research/api-core.md §6.3, §6.4) — không có endpoint mới:
     GET    /documents/{id}/status
            → Document (lấy tên tệp khi danh sách đoạn lỗi 409)
     GET    /documents/{id}/chunks?limit=50&offset=N
            → {document_id, version_id, version_number, filename, total_chunks,
               total_tokens, limit, offset, chunks:[{chunk_id, chunk_index,
               content, retrieval_context, token_count, page_start, page_end,
               heading_path[], section_title, block_type, locations[],
               content_hash, feedback:{label,note,created_at}|null}]}
              CHỈ phiên bản đang hoạt động, sắp theo chunk_index.
              404 HTTP_ERROR "Document not found" · 409 HTTP_ERROR
              "Document has no active indexed version yet" (mọi trạng thái
              khác "indexed", kể cả đang lập chỉ mục lại).
     POST   /documents/{id}/chunks/{chunk_id}/feedback {label:"bad", note}
            → 200 {chunk_id, chunk_uid, label, note} (admin; idempotent theo
              (chunk_uid,label) — gọi lại chỉ ghi đè ghi chú)
     DELETE /documents/{id}/chunks/{chunk_id}/feedback?label=bad → 204 (admin)

   404 ở đây KHÔNG phải "máy chủ chưa hỗ trợ" (isMissingApi sẽ nói nhầm vì
   mã lỗi là HTTP_ERROR): route có thật, chỉ là tài liệu không tồn tại.

   Dữ liệu không có: máy chủ không trả phần chồng lấn giữa hai đoạn, nên
   overlap được tính ở trình duyệt bằng đúng thuật toán của trang cũ
   (overlapPrefixLength, ≥20 ký tự, so với đoạn ĐÃ TẢI liền trước).

   Gọi mạng: chỉ Shell.api. V là DOM + dữ liệu của lần mount đang sống,
   null khi đã rời view — mọi việc bất đồng bộ kiểm tra live(v) trước khi vẽ.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  const PAGE_SIZE = 50;
  const JSON_HEADERS = { "Content-Type": "application/json" };

  const SUB = "Tài liệu bị cắt thành những đoạn nào — đúng như bộ truy xuất nhìn thấy";
  const TITLE_LOADING = "Đoạn tài liệu";

  const CTX_TIP = "Ngữ cảnh do model sinh lúc lập chỉ mục — bộ tìm kiếm nhìn thấy nó, câu trả lời thì không.";
  const OVERLAP_TIP = "Phần lặp lại từ đoạn trước (overlap của bộ cắt) — ranh giới cắt nằm ngay sau đây.";
  const NO_HEADING = "không thuộc mục nào";

  /* CHỈ bảng dùng font đơn cách (README §10 "bảng → mono", prototype P:712,
     trang cũ chỉ có `.ck-content.table`).
     KHÔNG dùng cho "mixed"/"formula": `mixed` chỉ nghĩa là đoạn gộp nhiều loại
     block — tiêu đề + đoạn văn cũng thành mixed (utils/chunking.py:326) — và
     `formula` là bất kỳ đoạn nào chứa = ≤ ∑ ∫ √ (…:336-339). Trên dữ liệu thật
     (10 tài liệu ở 127.0.0.1:8765) có 119 paragraph + 71 mixed, 0 table,
     0 formula: tô đơn cách theo "mixed" biến 37% văn xuôi thành font đơn cách.
     Bảng cũng không bao giờ được tô overlap — đúng như trang cũ: ranh giới bảng
     do bộ cắt quyết định, không phải chồng lấn. */
  const isTable = (chunk) => chunk.block_type === "table";

  let V = null;

  const enc = encodeURIComponent;
  const isAbort = (error) => Boolean(error) && error.name === "AbortError";
  const live = (v) => Boolean(v) && V === v && !v.ctx.signal.aborted;
  const message = (error) => String((error && error.message) || "").trim() || "lỗi không rõ";

  /* Nhóm endpoint đoạn trả lỗi dạng chuỗi → error_code luôn là "HTTP_ERROR",
     và common.js không có gợi ý cho HTTP_ERROR/INTERNAL_ERROR, nên `message`
     sẽ là nguyên văn tiếng Anh của máy chủ ("Document has no active indexed
     version yet"…). Dịch tại chỗ để mọi câu chữ trên màn hình là tiếng Việt
     (spec.md D8). Lỗi mạng đã được common.js dịch sẵn nên giữ nguyên. */
  function failText(error) {
    const status = error && error.status;
    if (status === 409) return "Tài liệu không còn phiên bản đang hoạt động — có thể đang được lập chỉ mục lại. Tải lại trang để xem phiên bản mới.";
    if (status === 404) return "Tài liệu hoặc đoạn không còn tồn tại trên máy chủ.";
    if (status === 403) return "Chỉ quản trị viên mới đánh dấu được đoạn.";
    if ((error && error.code === "INTERNAL_ERROR") || (typeof status === "number" && status >= 500)) {
      return "Máy chủ gặp lỗi nội bộ khi xử lý yêu cầu.";
    }
    return message(error);
  }

  /* ── thuật toán overlap (chép nguyên từ frontend/chunks.js:16-23) ──
     Prefix dài nhất của `content` mà cũng là hậu tố của đoạn trước, tối thiểu
     20 đơn vị mã UTF-16; ngắn hơn coi như trùng ngẫu nhiên → 0. Tính trên chữ
     chứ không trên `locations` (mảnh của bảng có vị trí chồng nhau). */
  function overlapPrefixLength(previousContent, content) {
    if (!previousContent || !content) return 0;
    const max = Math.min(previousContent.length, content.length);
    for (let length = max; length >= 20; length -= 1) {
      if (previousContent.endsWith(content.slice(0, length))) return length;
    }
    return 0;
  }

  /* ── chữ của từng ô ──────────────────────────────────────────── */

  function fileExt(name) {
    const raw = String(name || "").trim().toLowerCase();
    const at = raw.lastIndexOf(".");
    return at > 0 && at < raw.length - 1 ? raw.slice(at + 1) : "";
  }

  /* TXT/MD không có số trang: nói rõ vì sao thay vì để trống. */
  function pagesText(v, chunk) {
    const start = chunk.page_start;
    if (start == null) {
      const ext = fileExt(v.meta && v.meta.filename);
      return ext ? `không có số trang (${ext})` : "không có số trang";
    }
    const end = chunk.page_end;
    return end != null && end !== start ? `trang ${start}–${end}` : `trang ${start}`;
  }

  /* token_count có thể null ở hàng cũ (trước khi backend đếm token). */
  function tokensText(chunk) {
    return chunk.token_count == null ? "? token" : `${fmtNumber(chunk.token_count)} token`;
  }

  function headingText(chunk) {
    const path = Array.isArray(chunk.heading_path) ? chunk.heading_path.filter(Boolean) : [];
    return path.join(" › ");
  }

  /* Nhãn đánh dấu: UI chỉ tạo "bad" → "kém". Máy chủ không kiểm nhãn, nên
     nhãn lạ (do nơi khác ghi) hiện nguyên văn và cũng chính nó được dùng để xóa. */
  function feedbackLabel(chunk) {
    return (chunk.feedback && chunk.feedback.label) || "bad";
  }

  function badgeText(chunk) {
    const label = feedbackLabel(chunk);
    return label === "bad" ? "kém" : label;
  }

  /* ── dựng card ───────────────────────────────────────────────── */

  const sep = () => h("span", { "aria-hidden": "true" }, "·");

  /* Nội dung: prefix chồng lấn tô nền, phần còn lại là chữ thuần.
     `index` là vị trí trong mảng ĐÃ TẢI — bộ lọc không đổi cách tô. */
  function contentNodes(v, chunk, index) {
    const content = String(chunk.content ?? "");
    const previous = index > 0 ? v.chunks[index - 1] : null;
    const overlap = isTable(chunk) ? 0 : overlapPrefixLength(previous ? String(previous.content ?? "") : "", content);
    if (!overlap) return [content];
    return [
      h("span", { class: "ck-overlap", title: OVERLAP_TIP }, content.slice(0, overlap)),
      content.slice(overlap),
    ];
  }

  /* Chân card: nút đánh dấu (chỉ quản trị viên — backend cũng chặn member)
     + ghi chú. Thành viên chỉ thấy chân card khi có ghi chú để đọc. */
  function cardFoot(v, chunk) {
    const flagged = Boolean(chunk.feedback);
    const note = flagged && chunk.feedback.note ? `Ghi chú: ${chunk.feedback.note}` : "";
    const noteEl = note ? h("span", { class: "ck-note" }, note) : null;
    if (!Shell.isAdmin()) return noteEl ? h("div", { class: "ck-foot" }, noteEl) : null;
    const button = h("button", {
      type: "button",
      class: ["btn", "btn-28", "btn-outline", "hover-danger", "ck-flag", flagged && "is-flagged"],
      "aria-label": flagged
        ? `Bỏ đánh dấu kém cho đoạn #${chunk.chunk_index}`
        : `Đánh dấu đoạn #${chunk.chunk_index} là kém`,
      onClick: (event) => toggleFlag(v, chunk, event.currentTarget),
    }, flagged ? "Bỏ đánh dấu" : "Đánh dấu kém");
    return h("div", { class: "ck-foot" }, button, noteEl);
  }

  function buildCard(v, chunk, index) {
    const flagged = Boolean(chunk.feedback);
    const heading = headingText(chunk);
    const context = String(chunk.retrieval_context ?? "").trim();
    const mono = isTable(chunk);
    return h("article", { class: ["card", "card-p14", "ck-card", flagged && "is-flagged"] },
      h("div", { class: "ck-meta" },
        h("span", { class: "ck-idx" }, `#${chunk.chunk_index ?? "?"}`),
        sep(),
        h("span", null, pagesText(v, chunk)),
        sep(),
        h("span", null, tokensText(chunk)),
        h("span", { class: "tag tag-tight" }, chunk.block_type || "—"),
        flagged ? h("span", { class: "tag tag-tight tag-danger" }, badgeText(chunk)) : null,
        h("span", { class: ["ck-heading", !heading && "is-none"], title: heading || NO_HEADING },
          heading || NO_HEADING)),
      context ? h("div", { class: "ctx-block", title: CTX_TIP }, context) : null,
      h("div", { class: ["ck-content", mono && "is-mono"] }, contentNodes(v, chunk, index)),
      cardFoot(v, chunk));
  }

  function skelCard() {
    return h("div", { class: "card card-p14 ck-card ck-skel", "aria-hidden": "true" },
      h("div", { class: "ck-meta" },
        skeleton({ w: 26, h: 12, r: 4 }), skeleton({ w: 148, h: 12, r: 4 }),
        skeleton({ w: 62, h: 12, r: 4 }), skeleton({ w: 74, h: 17, r: 9 })),
      h("div", { class: "ck-skel-lines" },
        skeleton({ w: "100%", h: 12, r: 4 }), skeleton({ w: "94%", h: 12, r: 4 }), skeleton({ w: "58%", h: 12, r: 4 })));
  }

  /* ── lọc & đếm ───────────────────────────────────────────────── */

  /* Lọc tại chỗ trên những đoạn ĐÃ TẢI (máy chủ không có tìm kiếm theo từ
     khóa trong đoạn): khớp nội dung hoặc đường dẫn tiêu đề, không tính ngữ cảnh. */
  function matches(chunk, needle) {
    if (!needle) return true;
    if (String(chunk.content ?? "").toLowerCase().includes(needle)) return true;
    const path = Array.isArray(chunk.heading_path) ? chunk.heading_path : [];
    return path.join(" ").toLowerCase().includes(needle);
  }

  function totalChunks(v) {
    const n = Number(v.meta && v.meta.total_chunks);
    return Number.isFinite(n) && n >= 0 ? n : v.chunks.length;
  }

  function paintCount(v) {
    const loaded = v.chunks.length;
    const total = totalChunks(v);
    const needle = v.filter.trim().toLowerCase();
    if (!needle) {
      v.loaded.textContent = `${fmtNumber(loaded)}/${fmtNumber(total)} đoạn đã tải`;
      return;
    }
    const shown = v.chunks.filter((chunk) => matches(chunk, needle)).length;
    v.loaded.textContent = `${fmtNumber(shown)}/${fmtNumber(loaded)} đoạn khớp · ${fmtNumber(loaded)}/${fmtNumber(total)} đã tải`;
  }

  /* Card được dựng một lần rồi giữ trong v.nodes: đoạn chỉ được NỐI thêm nên
     card của đoạn thứ i không bao giờ đổi nghĩa (overlap tính với đoạn i-1 đã
     tải). Nhờ vậy gõ lọc và "Tải thêm" chỉ sắp lại các node có sẵn thay vì dựng
     lại 50·k card mỗi lần (trước đây là O(n²) theo số trang). */
  function cardFor(v, index) {
    const chunk = v.chunks[index];
    let node = v.nodes.get(chunk);
    if (!node) {
      node = buildCard(v, chunk, index);
      v.nodes.set(chunk, node);
    }
    return node;
  }

  /* Danh sách đang hiện đúng các node này rồi thì đừng thay: replaceChildren
     làm mất vùng văn bản đang bôi đen và neo cuộn. */
  function sameChildren(parent, cards) {
    if (parent.childElementCount !== cards.length) return false;
    for (let index = 0; index < cards.length; index += 1) {
      if (parent.children[index] !== cards[index]) return false;
    }
    return true;
  }

  function renderList(v) {
    const needle = v.filter.trim().toLowerCase();
    const cards = [];
    for (let index = 0; index < v.chunks.length; index += 1) {
      if (!matches(v.chunks[index], needle)) continue;
      cards.push(cardFor(v, index));
    }
    if (cards.length) {
      if (!sameChildren(v.list, cards)) v.list.replaceChildren(...cards);
      return;
    }
    v.list.replaceChildren(needle
      ? emptyState({
        icon: "search", title: "Không có đoạn nào khớp",
        text: `Trong ${fmtNumber(v.chunks.length)} đoạn đã tải không có đoạn nào chứa «${v.filter.trim()}». Tải thêm đoạn rồi lọc lại.`,
      })
      : emptyState({ icon: "list", title: "Phiên bản này không có đoạn nào", text: "Máy chủ trả về danh sách rỗng." }));
  }

  /* Vẽ lại đúng một card sau khi đánh dấu / bỏ đánh dấu (sửa lỗi cũ:
     badge "kém" chỉ đổi ở lần render sau). Card cũ mang theo nút vừa bấm nên
     tiêu điểm phải quay lại nút mới — nếu không, người dùng bàn phím rơi về
     <body> và mất chỗ đang đứng giữa hàng chục thẻ.
     `keepFocus` do nơi gọi truyền vào: `button.disabled = true` lúc gửi yêu cầu
     ĐÃ đẩy tiêu điểm về <body> rồi, nên đến đây không thể tự đoán được nữa. */
  function repaintCard(v, chunk, keepFocus) {
    const index = v.chunks.indexOf(chunk);
    if (index < 0) return;
    const old = v.nodes.get(chunk);
    const next = buildCard(v, chunk, index);
    v.nodes.set(chunk, next);
    if (!old || !old.isConnected) return;
    const hadFocus = keepFocus || old.contains(document.activeElement);
    old.replaceWith(next);
    if (!hadFocus) return;
    const button = next.querySelector(".ck-flag");
    if (button) button.focus({ preventScroll: true });
  }

  function paintFoot(v) {
    const remaining = Math.max(0, totalChunks(v) - v.chunks.length);
    /* Đặt lại nhãn TRƯỚC khi ẩn: trang cuối về tới lúc nút đang là "Đang tải…"
       thì nút bị giấu ở trạng thái cũ, lần hiện lại sau sẽ nói dối. */
    v.more.disabled = v.loading;
    v.more.textContent = v.loading ? "Đang tải…" : `Tải thêm ${fmtNumber(remaining)} đoạn`;
    v.foot.hidden = v.done || remaining === 0;
  }

  /* ── các trạng thái của trang ────────────────────────────────── */

  function showState(v, node) {
    v.legend.hidden = true;
    v.list.hidden = true;
    v.foot.hidden = true;
    v.state.hidden = false;
    v.state.replaceChildren(node);
  }

  /* Ô lọc bị vô hiệu phải TRÔNG khác ô dùng được (như .btn:disabled), nếu
     không người dùng bấm vào một ô có con trỏ chữ I mà không gõ được. */
  function setSearchEnabled(v, enabled) {
    v.search.disabled = !enabled;
    v.searchBox.classList.toggle("is-disabled", !enabled);
  }

  function showLoading(v) {
    v.top.hidden = false;
    v.searchBox.hidden = false;
    setSearchEnabled(v, false);
    v.badge.replaceChildren(skeleton({ w: 30, h: 30, r: 8 }));
    v.name.replaceChildren(skeleton({ w: 176, h: 13, r: 4 }));
    v.sub.replaceChildren(skeleton({ w: 320, h: 11, r: 4 }));
    v.legend.hidden = false;
    v.loaded.textContent = "đang tải…";
    v.state.hidden = true;
    v.state.replaceChildren();
    v.list.hidden = false;
    v.list.replaceChildren(skelCard(), skelCard(), skelCard());
    v.foot.hidden = true;
  }

  function paintHead(v) {
    const filename = String((v.meta && v.meta.filename) || (v.doc && v.doc.filename) || "");
    v.ctx.setHeader(filename ? `Đoạn của ${filename}` : TITLE_LOADING, SUB);
    /* Không biết tên tệp (tài liệu đang bị xóa) thì bỏ trống badge — khung xương
       ở đây sẽ nói dối là "đang tải". */
    v.badge.replaceChildren(filename ? typeBadge(filename, 30) : "");
    v.name.replaceChildren(filename || "Tài liệu");
    v.name.title = filename;
    if (!v.meta) { v.sub.replaceChildren(); return; }
    const version = v.meta.version_number == null ? "?" : v.meta.version_number;
    const tokens = v.meta.total_tokens == null ? "?" : fmtNumber(v.meta.total_tokens);
    v.sub.replaceChildren(`version ${version} · ${fmtNumber(totalChunks(v))} đoạn · ${tokens} token · đúng như bộ truy xuất nhìn thấy`);
  }

  function paintAll(v) {
    v.top.hidden = false;
    v.searchBox.hidden = false;
    setSearchEnabled(v, true);
    paintHead(v);
    v.state.hidden = true;
    v.state.replaceChildren();
    v.legend.hidden = false;
    v.list.hidden = false;
    renderList(v);
    paintCount(v);
    paintFoot(v);
  }

  /* Tên tệp + trạng thái tài liệu: CHỈ nhánh 409 cần (phản hồi 409 không có tên
     tệp), nên yêu cầu này nằm ở đây chứ không chạy song song mỗi lần mở trang —
     đường thành công giờ chỉ còn một yêu cầu, đúng như trang cũ. Lỗi được nuốt
     nhưng mã lỗi được giữ: 404 ở đây có nghĩa riêng (xem show409). */
  async function loadDocStatus(v) {
    try {
      v.doc = await Shell.api(`/documents/${enc(v.docId)}/status`, { signal: v.ctx.signal });
      v.docStatusCode = 200;
    } catch (statusError) {
      v.doc = null;
      v.docStatusCode = (statusError && statusError.status) || 0;
    }
  }

  function stateActions(v) {
    return h("div", { class: "ck-state-actions" },
      h("button", {
        type: "button", class: "btn btn-32 btn-outline",
        onClick: () => loadFirst(v),
      }, icon("retry", { size: 14 }), "Kiểm tra lại"),
      h("button", {
        type: "button", class: "btn btn-32 btn-outline",
        onClick: () => Router.go(`#/documents?doc=${enc(v.docId)}`),
      }, icon("docs", { size: 14 }), "Mở tài liệu"));
  }

  /* 409 = có hàng tài liệu nhưng không có phiên bản đang hoạt động: chưa index
     xong, index hỏng, đang index lại, hoặc đang bị xóa. */
  function show409(v) {
    const filename = String((v.doc && v.doc.filename) || "");
    // Không có đoạn nào để lọc: giấu hẳn ô lọc thay vì để một ô vô dụng. Hàng
    // đầu thì giữ lại kể cả khi không biết tên tệp — "← Tài liệu" là đường thoát.
    v.top.hidden = false;
    v.searchBox.hidden = true;
    setSearchEnabled(v, false);
    paintHead(v);
    const state = String((v.doc && v.doc.status) || "");
    /* /status trả 404 trong khi danh sách đoạn trả 409: hàng vẫn còn nhưng
       không đọc được nữa → tài liệu đang bị xóa (api-core §6.3). */
    const why = v.docStatusCode === 404 ? "Tài liệu đang được xóa nên không còn đoạn để xem."
      : state === "processing" ? "Tài liệu đang được lập chỉ mục — xong sẽ có đoạn để xem."
        : state === "failed" ? "Lần lập chỉ mục gần nhất thất bại nên chưa có phiên bản nào đang hoạt động."
          : state === "uploaded" ? "Tài liệu mới tải lên, chưa lập chỉ mục lần nào."
            : v.docStatusCode !== 200 ? "Không đọc được trạng thái tài liệu; chỉ phiên bản đang hoạt động mới có đoạn để xem."
              : "Chỉ phiên bản đang hoạt động mới có đoạn để xem.";
    showState(v, emptyState({
      icon: "clock", title: "Tài liệu chưa có phiên bản đã lập chỉ mục",
      text: `${filename ? `«${filename}»: ` : ""}${why}`,
      action: stateActions(v),
    }));
  }

  /* 404 = tài liệu không tồn tại (mã lỗi HTTP_ERROR nên isMissingApi sẽ nói
     nhầm là "máy chủ chưa hỗ trợ"). `my` là số thứ tự lần tải, vì nhánh 409
     còn phải chờ thêm một yêu cầu nữa. */
  async function showFailure(v, error, my) {
    const status = error && error.status;
    if (status === 409) {
      await loadDocStatus(v);
      if (!live(v) || my !== v.seq) return;
      show409(v);
      return;
    }
    v.top.hidden = true;
    if (status === 404) {
      showState(v, emptyState({
        icon: "alert", title: "Không tìm thấy tài liệu",
        text: `Máy chủ không có tài liệu nào mang mã «${v.docId}». Có thể tài liệu đã bị xóa.`,
        action: { label: "Về danh sách tài liệu", icon: "arrow-left", onClick: () => Router.go("#/documents") },
      }));
      return;
    }
    // errorState chỉ đọc .message: đưa bản tiếng Việt vào thay chuỗi của máy chủ.
    showState(v, errorState({ message: failText(error) }, () => loadFirst(v)));
  }

  /* ── tải dữ liệu ─────────────────────────────────────────────── */

  /* Một yêu cầu duy nhất trên đường thành công: danh sách đoạn đã mang theo
     `filename`. /status chỉ được gọi khi danh sách trả 409 (showFailure). */
  async function loadFirst(v) {
    if (!live(v)) return;
    v.seq += 1;
    const my = v.seq;
    v.loading = false;
    v.doc = null;
    v.docStatusCode = 0;
    showLoading(v);

    let data;
    try {
      data = await Shell.api(`/documents/${enc(v.docId)}/chunks?limit=${PAGE_SIZE}&offset=0`, { signal: v.ctx.signal });
    } catch (error) {
      if (isAbort(error) || !live(v) || my !== v.seq) return;
      await showFailure(v, error, my);
      return;
    }
    if (!live(v) || my !== v.seq) return;
    const page = Array.isArray(data.chunks) ? data.chunks : [];
    v.meta = data;
    v.chunks = page.slice();
    v.nodes = new Map();
    v.offset = page.length;
    v.done = v.offset >= totalChunks(v) || page.length === 0;
    paintAll(v);
  }

  /* Phân trang bằng offset = số đoạn đã tải. Cờ `loading` chặn bấm hai lần. */
  async function loadMore(v) {
    if (!live(v) || v.loading || v.done) return;
    v.loading = true;
    paintFoot(v);
    const my = v.seq;
    /* Khung xương chỉ có nghĩa khi danh sách đang là card thật; xếp nó dưới
       trạng thái rỗng "Không có đoạn nào khớp" thì vừa thừa vừa khó hiểu —
       nút đã ghi "Đang tải…" rồi. */
    const skeletons = v.list.querySelector(".ck-card") ? [skelCard(), skelCard()] : [];
    if (skeletons.length) v.list.append(...skeletons);

    let data;
    try {
      data = await Shell.api(`/documents/${enc(v.docId)}/chunks?limit=${PAGE_SIZE}&offset=${v.offset}`, { signal: v.ctx.signal });
    } catch (error) {
      if (isAbort(error) || !live(v) || my !== v.seq) return;
      v.loading = false;
      skeletons.forEach((node) => node.remove());
      paintFoot(v);
      toast(`Không tải thêm được: ${failText(error)}`, "danger");
      return;
    }
    if (!live(v) || my !== v.seq) return;
    v.loading = false;
    skeletons.forEach((node) => node.remove());
    /* Phiên bản đang hoạt động đổi giữa hai trang (index lại vừa xong) thì hai
       phiên bản sẽ bị nối vào nhau: chunk_index trùng, overlap ở chỗ nối sai.
       Bỏ hết và tải lại từ đầu. */
    if (v.meta && data.version_id && v.meta.version_id && data.version_id !== v.meta.version_id) {
      toast("Tài liệu vừa có phiên bản mới — đang tải lại từ đầu.");
      loadFirst(v);
      return;
    }
    const page = Array.isArray(data.chunks) ? data.chunks : [];
    v.meta = data;
    v.chunks = v.chunks.concat(page);
    v.offset += page.length;
    v.done = v.offset >= totalChunks(v) || page.length === 0;
    paintHead(v);
    renderList(v);
    paintCount(v);
    paintFoot(v);
  }

  /* ── đánh dấu kém / bỏ đánh dấu (admin) ──────────────────────── */

  function toggleFlag(v, chunk, button) {
    if (!live(v) || button.disabled) return;
    if (chunk.feedback) unflag(v, chunk, button);
    else flag(v, chunk, button);
  }

  async function flag(v, chunk, button) {
    const note = await dialog({
      tone: "danger", icon: "alert", title: `Đánh dấu đoạn #${chunk.chunk_index} là kém`,
      body: "Đánh dấu này chỉ để xem lại chất lượng cắt đoạn; nó không xóa đoạn và không đổi kết quả tìm kiếm. Ghi chú không bắt buộc.",
      input: { value: "", placeholder: "vd. cắt giữa bảng, mất tiêu đề cột", allowEmpty: true, label: "Ghi chú" },
      confirmLabel: "Đánh dấu kém", confirmTone: "danger", signal: v.ctx.signal,
    });
    if (note === null || !live(v)) return;
    // Ghi nhớ tiêu điểm TRƯỚC khi vô hiệu nút: vô hiệu một phần tử đang có tiêu
    // điểm là trình duyệt đẩy tiêu điểm về <body> ngay lúc đó.
    const hadFocus = document.activeElement === button;
    button.disabled = true;
    let data;
    try {
      data = await Shell.api(`/documents/${enc(v.docId)}/chunks/${enc(chunk.chunk_id)}/feedback`, {
        method: "POST", headers: JSON_HEADERS,
        body: JSON.stringify({ label: "bad", note: note.trim() || null }),
        signal: v.ctx.signal,
      });
    } catch (error) {
      if (isAbort(error) || !live(v)) return;
      button.disabled = false;
      toast(`Không lưu được đánh dấu: ${failText(error)}`, "danger");
      return;
    }
    if (!live(v)) return;
    chunk.feedback = { label: (data && data.label) || "bad", note: (data && data.note) ?? null, created_at: null };
    repaintCard(v, chunk, hadFocus);
    toast(`Đã đánh dấu đoạn #${chunk.chunk_index} là kém.`);
  }

  /* Một lần DELETE chỉ xóa MỘT dòng (khớp chunk_uid HOẶC content_hash), nên
     đoạn từng bị đánh dấu ở phiên bản trước có thể còn dấu sau khi xóa
     (api-core §6.4). Hỏi lại máy chủ đúng đoạn đó thay vì tự khẳng định đã sạch
     — nếu không, huy hiệu biến mất rồi lại hiện khi tải lại trang.
     offset = vị trí trong danh sách đã tải: danh sách sắp theo chunk_index và
     tải liên tục từ 0 nên hai con số này trùng nhau. */
  async function refetchChunk(v, chunk) {
    const at = v.chunks.indexOf(chunk);
    if (at < 0) return undefined;
    try {
      const data = await Shell.api(`/documents/${enc(v.docId)}/chunks?limit=1&offset=${at}`, { signal: v.ctx.signal });
      const row = Array.isArray(data && data.chunks) ? data.chunks[0] : null;
      return row && row.chunk_id === chunk.chunk_id ? (row.feedback || null) : undefined;
    } catch {
      return undefined;
    }
  }

  async function unflag(v, chunk, button) {
    const label = feedbackLabel(chunk);
    const hadFocus = document.activeElement === button;
    button.disabled = true;
    try {
      await Shell.api(`/documents/${enc(v.docId)}/chunks/${enc(chunk.chunk_id)}/feedback?label=${enc(label)}`, {
        method: "DELETE", signal: v.ctx.signal,
      });
    } catch (error) {
      if (isAbort(error) || !live(v)) return;
      button.disabled = false;
      toast(`Không bỏ được đánh dấu: ${failText(error)}`, "danger");
      return;
    }
    const fresh = await refetchChunk(v, chunk);
    if (!live(v)) return;
    chunk.feedback = fresh === undefined ? null : fresh;
    repaintCard(v, chunk, hadFocus);
    toast(chunk.feedback
      ? `Đã xóa một dấu, đoạn #${chunk.chunk_index} vẫn còn dấu «${badgeText(chunk)}» (dấu của phiên bản trước) — bấm lần nữa để xóa nốt.`
      : `Đã bỏ đánh dấu đoạn #${chunk.chunk_index}.`);
  }

  /* ── vòng đời ────────────────────────────────────────────────── */

  /* Vào thẳng #/chunks (không có mã tài liệu): không gọi gì cả, chỉ đường về.
     Link cũ /ui/chunks.html thiếu ?document_id= cũng rơi vào đây qua redirect. */
  function mountWithoutId(ctx) {
    ctx.setHeader(TITLE_LOADING, SUB);
    ctx.root.append(h("div", { class: "page" },
      h("div", { class: "page-inner w-900 gap-12" },
        emptyState({
          icon: "list", title: "Chưa chọn tài liệu",
          text: "Địa chỉ này cần mã tài liệu (#/chunks/<mã>). Mở từ nút «Xem đoạn» của một tài liệu đã lập chỉ mục.",
          action: { label: "Về danh sách tài liệu", icon: "arrow-left", onClick: () => Router.go("#/documents") },
        }))));
  }

  function mount(ctx) {
    const docId = ctx.params[0] || "";
    if (!docId) { mountWithoutId(ctx); return; }
    ctx.setHeader(TITLE_LOADING, SUB);

    const back = h("a", { class: "btn btn-32 btn-outline px-10 ck-back", href: `#/documents?doc=${enc(docId)}` },
      icon("arrow-left", { size: 14 }), "Tài liệu");
    const badge = h("span", { class: "ck-badge" });
    const name = h("div", { class: "ck-name" });
    const sub = h("div", { class: "ck-sub" });
    /* type=search như trang cũ: đúng ngữ nghĩa cho công nghệ trợ giúp và có
       nút xóa sẵn của trình duyệt. */
    const search = h("input", {
      type: "search", placeholder: "Lọc theo từ khoá…", "aria-label": "Lọc đoạn theo từ khoá (trên các đoạn đã tải)",
      autocomplete: "off", spellcheck: "false", disabled: true,
      onInput: (event) => {
        if (!V) return;
        V.filter = event.target.value;
        V.applyFilter();
      },
      /* Lớp khác (dialog, menu, thanh bên ≤960px) đã xử lý Esc thì đừng nuốt
         thêm: mỗi lần Esc chỉ đóng một lớp (foundation, mục Esc). */
      onKeydown: (event) => {
        if (event.key !== "Escape" || event.defaultPrevented || !event.target.value) return;
        event.preventDefault();
        event.target.value = "";
        if (!V) return;
        V.filter = "";
        V.applyFilter.cancel();
        renderList(V);
        paintCount(V);
      },
    });
    const searchBox = h("label", { class: "search search-34 ck-search" }, icon("search", { size: 14 }), search);
    const top = h("div", { class: "toolbar ck-top" },
      back, badge, h("div", { class: "ck-title" }, name, sub), searchBox);

    const loaded = h("span", { class: "ck-loaded", role: "status" }, "đang tải…");
    const legend = h("div", { class: "ck-legend" },
      h("span", null, h("i", { class: "ck-sw ck-sw-overlap", "aria-hidden": "true" }), "phần lặp từ đoạn trước (overlap)"),
      h("span", null, h("i", { class: "ck-sw ck-sw-ctx", "aria-hidden": "true" }), "ngữ cảnh do model sinh lúc index"),
      loaded);

    const list = h("section", { class: "ck-list", "aria-label": "Danh sách đoạn" });
    const more = h("button", { type: "button", class: "btn btn-34 btn-outline px-16", onClick: () => { if (V) loadMore(V); } }, "Tải thêm");
    const foot = h("div", { class: "ck-footrow", hidden: true }, more);
    const state = h("div", { class: "ck-state", hidden: true });

    ctx.root.append(h("div", { class: "page" },
      h("div", { class: "page-inner w-900 gap-12" }, top, legend, list, foot, state)));

    const v = {
      ctx, docId, top, badge, name, sub, search, searchBox, legend, loaded, list, foot, more, state,
      nodes: new Map(), chunks: [], meta: null, doc: null, docStatusCode: 0,
      offset: 0, done: false, loading: false, filter: "", seq: 0,
    };
    /* Gõ nhanh không dựng lại toàn bộ danh sách sau mỗi phím. */
    v.applyFilter = debounce(() => {
      if (!live(v)) return;
      renderList(v);
      paintCount(v);
    }, 140);
    V = v;
    loadFirst(v);
  }

  /* Cùng #/chunks/<id> → đọc lại; đổi sang tài liệu khác → để router mount lại. */
  function update(ctx, info) {
    if (!V || V.ctx !== ctx) return false;
    if ((ctx.params[0] || "") !== V.docId) return false;
    if (info && info.same) loadFirst(V);
    return true;
  }

  function unmount() {
    if (V && V.applyFilter) V.applyFilter.cancel();
    V = null;
  }

  Router.register("chunks", { admin: false, mount, update, unmount });
})();
