/* ══════════════════════════════════════════════════════════════════
   /ui/views/chat.js — màn hình Chat (#/chat, #/chat/<conversationId>).

   Một IIFE, không tên top-level. Gồm:
     - khối "HỘI THOẠI" ở sidebar (Shell.setSidebarPanel, dựng MỘT lần và
       dùng lại qua mọi lần mount): tìm, nhóm Đã ghim / theo ngày, ghim,
       thư mục (F1), đổi tên, xóa, menu chuột phải;
     - cột chat: trạng thái trống + gợi ý, transcript (markdown escape-first
       của app cũ, đã sửa D1), khối đang trả lời, bước agent, chip nguồn,
       nhãn bám nguồn, composer; popup trích dẫn (F3 xem trước trang);
     - drawer "Phạm vi hỏi đáp" 340px: chọn tài liệu (lac.docsel) + tải lên
       nhiều tệp qua Uploads (uploads.js).

   Gọi mạng: Shell.api / Shell.fetchBlob; NGOẠI LỆ DUY NHẤT là luồng SSE của
   /chat và /rag/chat (streamChat) — chỗ gọi mạng thô duy nhất của file này,
   vì cần đọc body từng mảnh + AbortController + tự refresh token một lần.

   Trạng thái S sống qua các lần mount (danh sách hội thoại, tài liệu, lựa
   chọn, chế độ…); V là DOM của lần mount đang sống, null khi đã rời view —
   mọi việc bất đồng bộ kiểm tra V trước khi vẽ.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  /* ── hằng số ─────────────────────────────────────────────────── */
  const NEAR_BOTTOM = 130;
  const JSON_HEADERS = { "Content-Type": "application/json" };
  const MOBILE = window.matchMedia("(max-width: 960px)");
  const OFFLINE = "Không kết nối được máy chủ. Kiểm tra backend đang chạy.";
  const MAX_DOCS = 100;              // rag_schema.py: document_ids tối đa 100 → chặn trước khi gửi
  const FOLDER_RETRY_MS = 300000;    // máy chủ chưa có /folders: 5 phút mới dò lại một lần

  /* Mã lỗi backend chưa có câu tiếng Việt trong ERROR_HINTS (common.js) nhưng gặp thường ở màn chat:
     thông điệp gốc là tiếng Anh, không hiện thẳng cho người dùng. */
  const CHAT_HINTS = {
    STREAM_FAILED: "Máy chủ mất kết nối với mô hình khi đang trả lời. Thử lại sau giây lát.",
    INTERNAL_ERROR: "Máy chủ gặp lỗi không xác định. Xem log backend để biết chi tiết.",
  };

  /* Thẻ gợi ý: chữ hiển thị theo prototype (P:793-797), chữ điền vào ô soạn theo app cũ (app.js:1294-1299). */
  const SUGGESTIONS = [
    { icon: "spark", title: "Giải thích khái niệm", body: "RAG là gì và khi nào nên dùng?", fill: "Giải thích cho tôi RAG là gì và khi nào nên dùng?" },
    { icon: "pen", title: "Soạn thảo nội dung", body: "Soạn email báo giá chuyên nghiệp bằng tiếng Việt.", fill: "Soạn giúp tôi một email báo giá chuyên nghiệp bằng tiếng Việt." },
    { icon: "book", title: "Hỏi đáp tài liệu", body: "Chọn tài liệu rồi hỏi, có trích dẫn nguồn.", docs: true },
    { icon: "list", title: "Tóm tắt văn bản", body: "Tóm tắt thành 5 ý chính, giữ số liệu quan trọng.", fill: "Tóm tắt văn bản sau thành 5 ý chính, giữ nguyên số liệu quan trọng:\n\n" },
  ];

  const FOLDER_COLORS = [
    { value: "#0ea5e9", label: "Xanh dương" }, { value: "#f59e0b", label: "Cam" }, { value: "#22c55e", label: "Xanh lá" },
    { value: "#ef4444", label: "Đỏ" }, { value: "#a855f7", label: "Tím" }, { value: "#64748b", label: "Xám" },
  ];

  /* ── trạng thái sống qua các lần mount ───────────────────────── */
  const S = {
    panel: null, side: {},
    convs: [], convsLoaded: false, convsError: null, convsSeq: 0, query: "",
    folders: [], foldersMissing: false, foldersCheckedAt: 0,
    pinMissing: false, pinBusy: new Set(),   // máy chủ đã từ chối ghim / id đang chờ PATCH {pinned}
    colorSeq: 0,
    titles: readTitles(),
    docs: [], docsLoaded: false, docsError: null, docsSeq: 0, docsBusy: false,
    reindexing: new Set(),   // document_id đang chờ POST /documents/index trả lời (chặn bấm đúp)
    selected: new Set(),
    mode: prefs.mode === "rag" ? "rag" : "general",
    memoryOn: Boolean(prefs.memoryDefault),
    toolsOn: Boolean(prefs.toolsOn),
    docsOpen: false,
    model: null, modelsBusy: false,
    uploads: [],
    cur: { id: null, title: null, seq: 0 },
    gen: null,
    citeSeq: 0,
  };
  let V = null;
  const msgSources = new WeakMap();   // nút .msg-assistant → mảng nguồn của CHÍNH câu trả lời đó

  /* ── tiện ích ────────────────────────────────────────────────── */
  const enc = (value) => encodeURIComponent(String(value));
  const isAbort = (error) => Boolean(error) && error.name === "AbortError";
  const viewSignal = () => (V ? V.ctx.signal : undefined);   // dialog tự đóng khi rời màn hình

  /* Đặt con của parent đúng thứ tự `nodes` mà KHÔNG tháo nút đã đứng đúng chỗ: nút đang giữ
     focus (hoặc đang làm mốc cho menu chuột phải) không bị gỡ ra rồi gắn lại nên không mất focus,
     và hiệu ứng xuất hiện của nó không chạy lại. */
  function reconcile(parent, nodes) {
    const keep = new Set(nodes);
    for (const child of [...parent.childNodes]) if (!keep.has(child)) child.remove();
    let at = parent.firstChild;
    for (const node of nodes) {
      if (node === at) { at = at.nextSibling; continue; }
      parent.insertBefore(node, at);
    }
  }

  /* Câu tiếng Việt của một lỗi: common.js đã dịch phần lớn mã lỗi, CHAT_HINTS bù hai mã hay gặp ở
     màn chat (500 và luồng đứt). Không mã nào khớp thì giữ nguyên thông điệp của máy chủ. */
  function viError(error) {
    return (error && CHAT_HINTS[error.code]) || (error && error.message) || "Yêu cầu thất bại.";
  }

  function safeSavePrefs() {
    try { savePrefs(); } catch { /* localStorage bị chặn: chỉ mất phần ghi nhớ lựa chọn */ }
  }

  function readTitles() {
    try {
      const raw = JSON.parse(localStorage.getItem("lac.titles") || "{}");
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
      const out = {};
      for (const [id, title] of Object.entries(raw)) if (typeof title === "string" && title) out[id] = title;
      return out;
    } catch {
      return {};
    }
  }

  function saveTitles() {
    try { localStorage.setItem("lac.titles", JSON.stringify(S.titles)); } catch { /* bộ nhớ bị chặn */ }
  }

  function saveSelection() {
    Uploads.saveSelection([...S.selected]);
  }

  function announce(text) {
    const node = document.getElementById("sr-status");
    if (node) node.textContent = text;
  }

  /* Thứ tự ưu tiên của app cũ: tiêu đề máy chủ → cache lac.titles → "Trò chuyện <ngày tạo>". */
  function titleFor(conv) {
    if (!conv) return "Hội thoại";
    const date = new Date(conv.created_at);
    return conv.title || S.titles[conv.id] || `Trò chuyện ${Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString("vi-VN")}`.trim();
  }

  /* Nhóm theo ngày lịch địa phương của updated_at, đúng mốc groupLabel cũ (app.js:691-700). */
  function dayGroup(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Cũ hơn";
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const days = Math.round((today - day) / 86400000);
    if (days <= 0) return "Hôm nay";
    if (days === 1) return "Hôm qua";
    if (days < 7) return "7 ngày qua";
    if (days < 30) return "30 ngày qua";
    return "Cũ hơn";
  }

  function rowById(id) {
    return S.convs.find((row) => row.id === id) || null;
  }

  function safeColor(color) {
    return /^#[0-9a-f]{3,8}$/i.test(String(color || "")) ? color : "var(--text-3)";
  }

  function headingText(path) {
    if (Array.isArray(path)) return path.filter(Boolean).join(" > ") || null;
    return path ? String(path) : null;
  }

  function lastHeading(path) {
    const text = headingText(path);
    if (!text) return null;
    const parts = text.split(" > ").map((part) => part.trim()).filter(Boolean);
    return parts[parts.length - 1] || text;
  }

  function pagesText(src) {
    const start = src.page_start ?? src.page;
    if (start === null || start === undefined) return null;
    const end = src.page_end;
    return end && end !== start ? `trang ${start}–${end}` : `trang ${start}`;
  }

  /* ── markdown (escape-first; port app.js:172-253, sửa D1) ────── */
  function inlineMd(text) {
    let html = esc(text);
    html = html.replace(/`([^`]+)`/g, (_, code) => `<code>${code}</code>`);
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
    // URL không được chứa [ ] < > (và dừng ở ")"): nếu không, bước thay marker trích dẫn bên dưới
    // (hoặc thẻ <code>/<strong> vừa chèn) lọt vào giữa href và phá cấu trúc thẻ <a>.
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)[\]<>]+)\)/g,
      (_, label, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`);
    // Marker trích dẫn: prompt buộc "[Source N]", model hay tự dịch thành "[Nguồn N]".
    html = html.replace(/\[\s*(?:Source|Ngu[oồ]n)\s*(\d+)\s*\]/gi,
      (_, number) => `<button type="button" class="cite" data-cite="${number}" title="Xem nguồn ${number}">${number}</button>`);
    return html;
  }

  /* Dòng mở khối mã: ``` + tên ngôn ngữ (chấp nhận c++, c#, " python").
     Sửa D1: dòng bắt đầu bằng ``` mà không phải rào hợp lệ (````, ```a``` chữ)
     giờ là chữ thường của đoạn văn — vòng lặp đoạn văn luôn nuốt ít nhất một
     dòng nên không bao giờ đứng yên (bản cũ treo tab ở đây). */
  const FENCE = /^```\s*([\w+#.-]*)\s*$/;
  const FENCE_END = /^```\s*$/;

  function isBlockStart(line) {
    return /^\s*$/.test(line) || FENCE.test(line) || /^(#{1,4})\s/.test(line) || /^\s*[-*+]\s+/.test(line)
      || /^\s*\d+[.)]\s+/.test(line) || /^\s*>\s?/.test(line) || /^(?:-{3,}|\*{3,})\s*$/.test(line);
  }

  function renderMarkdown(text) {
    const lines = String(text).split("\n");
    const out = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      const fence = FENCE.exec(line);
      if (fence) {
        const body = [];
        index += 1;
        while (index < lines.length && !FENCE_END.test(lines[index])) { body.push(lines[index]); index += 1; }
        index += 1; // bỏ dòng ``` đóng (hoặc hết chuỗi khi đang stream → vẫn vẽ thành khối mã)
        out.push(`<div class="codeblock"><div class="codeblock-head"><span class="codeblock-lang">${esc(fence[1] || "text")}</span>`
          + `<button type="button" class="codeblock-copy">Sao chép</button></div><pre><code>${esc(body.join("\n"))}</code></pre></div>`);
        continue;
      }
      if (/^\s*$/.test(line)) { index += 1; continue; }
      const heading = line.match(/^(#{1,4})\s+(.*)$/);
      if (heading) {
        const level = heading[1].length;
        out.push(`<h${level}>${inlineMd(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }
      if (/^(?:-{3,}|\*{3,})\s*$/.test(line)) { out.push("<hr>"); index += 1; continue; }
      if (/^\s*>\s?/.test(line)) {
        const body = [];
        while (index < lines.length && /^\s*>\s?/.test(lines[index])) { body.push(lines[index].replace(/^\s*>\s?/, "")); index += 1; }
        out.push(`<blockquote>${body.map(inlineMd).join("<br>")}</blockquote>`);
        continue;
      }
      if (/^\s*[-*+]\s+/.test(line)) {
        const items = [];
        while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) { items.push(lines[index].replace(/^\s*[-*+]\s+/, "")); index += 1; }
        out.push(`<ul>${items.map((item) => `<li>${inlineMd(item)}</li>`).join("")}</ul>`);
        continue;
      }
      if (/^\s*\d+[.)]\s+/.test(line)) {
        const items = [];
        while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) { items.push(lines[index].replace(/^\s*\d+[.)]\s+/, "")); index += 1; }
        out.push(`<ol>${items.map((item) => `<li>${inlineMd(item)}</li>`).join("")}</ol>`);
        continue;
      }
      const paragraph = [line];
      index += 1;
      while (index < lines.length && !isBlockStart(lines[index])) { paragraph.push(lines[index]); index += 1; }
      out.push(`<p>${paragraph.map(inlineMd).join("<br>")}</p>`);
    }
    return out.join("");
  }

  /* ══════════════════════════════════════════════════════════════
     SIDEBAR — khối "HỘI THOẠI"
     ══════════════════════════════════════════════════════════════ */
  function ensurePanel() {
    if (S.panel) return S.panel;
    const search = h("input", {
      type: "text", placeholder: "Tìm hội thoại…", "aria-label": "Tìm hội thoại", autocomplete: "off", spellcheck: "false",
    });
    const list = h("div", { class: "chat-side-list", role: "group", "aria-label": "Danh sách hội thoại" });
    const panel = h("div", { class: "chat-side" },
      h("div", { class: "chat-side-head" },
        h("span", { class: "section-label section-label-wide" }, "Hội thoại"),
        h("button", {
          type: "button", class: "chat-new", title: "Cuộc trò chuyện mới", "aria-label": "Cuộc trò chuyện mới",
          onClick: () => Router.go("#/chat"),
        }, icon("plus", { size: 15 }))),
      h("div", { class: "chat-side-search" }, h("label", { class: "search search-soft" }, icon("search", { size: 14 }), search)),
      list);
    search.addEventListener("input", debounce(() => { S.query = search.value; renderConvList(); }, 120));
    S.panel = panel;
    S.side = { list, search, items: new Map(), heads: new Map() };
    return panel;
  }

  /* Mỗi hội thoại giữ MỘT nút DOM suốt phiên (S.side.items): tải lại danh sách chỉ vẽ lại phần bên
     trong khi dữ liệu đổi, nên focus bàn phím và mốc của menu chuột phải không bị thay mất.
     Mục là role="link" (mở một địa chỉ #/chat/<id>) — khác role="button", link không biến các nút
     ghim/đổi tên/xóa bên trong thành "trình bày" với trình đọc màn hình. */
  function convNode(id) {
    let ref = S.side.items.get(id);
    if (ref) return ref;
    const node = h("div", { class: "conv-item", role: "link", tabindex: "0", dataset: { id } });
    const open = () => Router.go(`#/chat/${enc(id)}`);
    node.addEventListener("click", (event) => { if (!event.target.closest("button")) open(); });
    node.addEventListener("keydown", (event) => {
      if (event.target !== node) return;
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
      else if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) { event.preventDefault(); openConvMenu(id, node); }
    });
    node.addEventListener("contextmenu", (event) => { event.preventDefault(); openConvMenu(id, node); });
    ref = { node, sig: null };
    S.side.items.set(id, ref);
    return ref;
  }

  function convItem(conv) {
    const ref = convNode(conv.id);
    const active = conv.id === S.cur.id;
    const title = titleFor(conv);
    const folder = conv.folder_id ? S.folders.find((f) => f.id === conv.folder_id) : null;
    // Nút ghim chỉ hiện khi máy chủ có F1 (dòng mang `pinned`); không có thì hàng giữ 2 nút như README,
    // còn "Ghim" vẫn nằm trong menu chuột phải (máy chủ từ chối → báo "chưa hỗ trợ").
    const canPin = typeof conv.pinned === "boolean";
    const sig = JSON.stringify([active, title, conv.message_count ?? 0, folder ? safeColor(folder.color) : null,
      conv.pinned === true, canPin, conv.has_sources === true]);
    if (ref.sig === sig) return ref.node;
    ref.sig = sig;
    const node = ref.node;
    const stop = (fn) => (event) => { event.stopPropagation(); fn(); };
    const acts = active ? h("span", { class: "conv-acts" },
      canPin ? h("button", {
        type: "button", class: "icon-btn icon-btn-24", title: conv.pinned === true ? "Bỏ ghim" : "Ghim",
        "aria-label": conv.pinned === true ? "Bỏ ghim hội thoại" : "Ghim hội thoại", onClick: stop(() => togglePin(conv.id)),
      }, conv.pinned === true ? icon("pin-off", { size: 12 }) : icon("pin", { size: 12 })) : null,
      h("button", {
        type: "button", class: "icon-btn icon-btn-24", title: "Đổi tên", "aria-label": "Đổi tên hội thoại", onClick: stop(() => renameConv(conv.id)),
      }, icon("pen", { size: 12 })),
      h("button", {
        type: "button", class: "icon-btn icon-btn-24 is-delete", title: "Xóa", "aria-label": "Xóa hội thoại", onClick: stop(() => deleteConv(conv.id)),
      }, icon("trash", { size: 12 }))) : null;
    node.className = active ? "conv-item is-active" : "conv-item";
    node.title = `${title} · ${conv.message_count ?? 0} tin nhắn`;
    node.setAttribute("aria-label", title);   // tên đọc = tiêu đề, không lẫn nhãn các nút bên trong
    if (active) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
    node.replaceChildren(...[
      folder ? h("span", { class: "folder-dot", style: { background: safeColor(folder.color) }, "aria-hidden": "true" }) : null,
      h("span", { class: "title" }, title),
      acts,
      conv.has_sources === true ? icon("book", { size: 12, cls: "conv-rag" }) : null,
    ].filter(Boolean));
    return node;
  }

  /* Tiêu đề nhóm cũng dùng lại nút cũ; nhãn lặp lại trong CÙNG một lần vẽ (danh sách không theo
     thứ tự ngày) thì dựng nút mới, vì một nút DOM chỉ đứng được một chỗ. */
  function groupHead(label, pinned, used) {
    const key = pinned ? "pinned:" : label;
    let node = used.has(key) ? null : S.side.heads.get(key);
    if (!node) {
      node = h("div", { class: "group-label conv-group" }, pinned ? icon("pin", { size: 11, sw: 2.2 }) : null, label);
      if (!used.has(key)) S.side.heads.set(key, node);
    }
    used.add(key);
    return node;
  }

  function renderConvList() {
    const list = S.side.list;
    if (!list) return;
    const focusedId = list.contains(document.activeElement) ? document.activeElement.closest(".conv-item")?.dataset.id : null;
    if (S.convsError) {
      list.replaceChildren(h("div", { class: "conv-error", role: "alert" },
        h("span", null, "Không tải được danh sách hội thoại."),
        h("button", { type: "button", class: "btn btn-28 btn-outline", onClick: () => loadConversations() }, icon("retry", { size: 13 }), "Thử lại")));
      return;
    }
    if (!S.convsLoaded) {
      list.replaceChildren(...[0, 1, 2].map(() => h("div", { class: "conv-skel" }, skeleton({ h: 14, w: "70%" }))));
      return;
    }
    // Nút của hội thoại đã biến mất khỏi máy chủ thì bỏ khỏi bộ nhớ đệm.
    const alive = new Set(S.convs.map((conv) => conv.id));
    for (const id of [...S.side.items.keys()]) if (!alive.has(id)) S.side.items.delete(id);
    const query = S.query.trim().toLowerCase();
    const rows = S.convs.filter((conv) => !query || titleFor(conv).toLowerCase().includes(query));
    if (!rows.length) {
      list.replaceChildren(h("div", { class: "conv-empty" },
        query ? "Không có hội thoại khớp từ khóa." : "Chưa có hội thoại nào. Bắt đầu cuộc trò chuyện đầu tiên!"));
      return;
    }
    const out = [];
    const used = new Set();
    const pinned = rows.filter((conv) => conv.pinned === true);
    if (pinned.length) {
      out.push(groupHead("Đã ghim", true, used));
      for (const conv of pinned) out.push(convItem(conv));
    }
    let group = null;
    for (const conv of rows) {
      if (conv.pinned === true) continue;
      const label = dayGroup(conv.updated_at);
      if (label !== group) { out.push(groupHead(label, false, used)); group = label; }
      out.push(convItem(conv));
    }
    reconcile(list, out);
    // Focus nằm trên một nút con vừa được vẽ lại (vd. nút đổi tên) → trả về chính mục đó.
    if (focusedId && !list.contains(document.activeElement)) {
      const again = S.side.items.get(focusedId);
      if (again && again.node.isConnected) again.node.focus({ preventScroll: true });
    }
  }

  async function loadConversations({ quiet = false } = {}) {
    const seq = ++S.convsSeq;
    if (!quiet && !S.convs.length && !S.convsLoaded) renderConvList();
    // Máy chủ chưa có /folders thì thôi hỏi lại mỗi lần tải danh sách (đổi tên, xóa, thử lại… đều
    // sinh thêm một 404 trong console) — chỉ dò lại sau 5 phút, đủ để thấy backend vừa nâng cấp.
    const wantFolders = !S.foldersMissing || Date.now() - S.foldersCheckedAt > FOLDER_RETRY_MS;
    const [rows, folders] = await Promise.allSettled([
      Shell.api("/conversations"),
      wantFolders ? Shell.api("/folders") : Promise.resolve(null),
    ]);
    if (seq !== S.convsSeq) return;
    if (rows.status === "fulfilled") {
      S.convs = Array.isArray(rows.value) ? rows.value.filter((row) => row && row.id) : [];
      S.convsLoaded = true;
      S.convsError = null;
      // Tên đặt cục bộ (lac.titles) của hội thoại máy chủ không còn trả về thì xóa, để cache không phình mãi.
      const alive = new Set(S.convs.map((row) => row.id));
      let pruned = false;
      for (const id of Object.keys(S.titles)) if (!alive.has(id)) { delete S.titles[id]; pruned = true; }
      if (pruned) saveTitles();
    } else {
      S.convsError = rows.reason || new Error("Không tải được danh sách hội thoại.");
    }
    if (folders.status === "fulfilled" && folders.value !== null) {
      S.folders = Array.isArray(folders.value) ? folders.value.filter((f) => f && f.id) : [];
      S.foldersMissing = false;
      S.foldersCheckedAt = Date.now();
    } else if (folders.status === "rejected" && isMissingApi(folders.reason)) {
      S.folders = [];
      S.foldersMissing = true;
      S.foldersCheckedAt = Date.now();
    }
    renderConvList();
    setHeaderTitle();
  }

  /* ── hành động trên một hội thoại ────────────────────────────── */

  /* F1: PATCH chỉ mang {pinned} — KHÔNG kèm title (gửi title là đổi tên).
     Backend chưa có F1 bắt buộc title → 422 INVALID_INPUT = "chưa hỗ trợ". */
  async function togglePin(id) {
    const conv = rowById(id);
    if (!conv) return;
    if (S.pinBusy.has(id)) return;   // bấm đúp: một yêu cầu thôi, lần hai sẽ lật ngược ý người dùng
    S.pinBusy.add(id);
    const next = conv.pinned !== true;
    try {
      await Shell.api(`/conversations/${enc(id)}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ pinned: next }) });
      const row = rowById(id);
      if (row) row.pinned = next;
      renderConvList();
      loadConversations({ quiet: true });
    } catch (error) {
      if (isUnsupportedField(error) || isMissingApi(error)) {
        S.pinMissing = true;   // menu chuột phải khóa mục Ghim từ đây trở đi (khỏi bấm vào chỗ chắc lỗi)
        toast("Máy chủ chưa hỗ trợ ghim hội thoại.", "danger");
      } else {
        toast(viError(error), "danger");
        if (error.status === 404) loadConversations({ quiet: true });
      }
    } finally {
      S.pinBusy.delete(id);
    }
  }

  async function renameConv(id) {
    const conv = rowById(id);
    if (!conv) return;
    let saved = null;
    await dialog({
      tone: "accent", icon: "pen", title: "Đổi tên hội thoại",
      body: "Tên hiển thị lưu trên máy chủ, đồng bộ mọi trình duyệt.",
      input: { value: titleFor(conv), maxlength: 200, label: "Tên hội thoại" },
      confirmLabel: "Lưu", signal: viewSignal(),
      validate: async (name) => {
        try {
          await Shell.api(`/conversations/${enc(id)}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ title: name }) });
          saved = name;
          return null;
        } catch (error) {
          return viError(error);
        }
      },
    });
    if (saved === null) return;
    const row = rowById(id);
    if (row) row.title = saved;
    if (S.cur.id === id) S.cur.title = saved;
    delete S.titles[id];
    saveTitles();
    renderConvList();
    setHeaderTitle();
    toast("Đã đổi tên hội thoại.");
  }

  async function deleteConv(id) {
    const conv = rowById(id);
    if (!conv) return;
    const yes = await confirmDialog({
      title: "Xóa hội thoại?",
      body: `«${titleFor(conv)}» và toàn bộ tin nhắn trong đó sẽ bị xóa vĩnh viễn khỏi máy chủ.`,
      signal: viewSignal(),
    });
    if (!yes) return;
    let gone = false;
    try {
      await Shell.api(`/conversations/${enc(id)}`, { method: "DELETE" });
      toast("Đã xóa hội thoại.");
      gone = true;
    } catch (error) {
      if (error.status === 404) gone = true;   // đã bị xóa ở nơi khác: im lặng
      else toast(viError(error), "danger");     // 500 / mất mạng: hội thoại vẫn còn → ở lại trong đó
    }
    if (gone) {
      delete S.titles[id];
      saveTitles();
      // replace, KHÔNG go: hội thoại vừa xóa không được ở lại trong lịch sử trình duyệt, vì bấm Back
      // sẽ mở nó rồi bật toast 404 (app cũ cũng dùng replaceState ở đây).
      if (S.cur.id === id && V) Router.replace("#/chat");
    }
    loadConversations();
  }

  async function moveToFolder(id, folderId) {
    const conv = rowById(id);
    if (!conv || (conv.folder_id || null) === (folderId || null)) return;
    try {
      await Shell.api(`/conversations/${enc(id)}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ folder_id: folderId || null }) });
      const row = rowById(id);
      if (row) row.folder_id = folderId || null;
      renderConvList();
      loadConversations({ quiet: true });
    } catch (error) {
      if (isUnsupportedField(error) || isMissingApi(error)) toast("Máy chủ chưa hỗ trợ thư mục hội thoại.", "danger");
      else toast(viError(error), "danger");
    }
  }

  function folderNameField(value) {
    return [{ name: "name", label: "Tên thư mục", value: value || "", placeholder: "Dự án", maxlength: 64, required: true }];
  }

  /* Màu thư mục = 6 ô màu bấm được, không phải danh sách TÊN màu trong <select>: người dùng phải
     THẤY màu mình chọn (README: lựa chọn trong dialog là thẻ, không phải chữ). Toàn bộ là phần tử
     inline nên nằm vừa trong đoạn mô tả <p> của dialog(). */
  function folderColorPicker(initial) {
    const name = `folder-color-${++S.colorSeq}`;
    const radios = FOLDER_COLORS.map((color) => h("input", {
      type: "radio", name, class: "swatch-radio", value: color.value, title: color.label,
      "aria-label": `Màu ${color.label.toLowerCase()}`, style: { background: color.value },
      checked: color.value === initial,
    }));
    if (!radios.some((radio) => radio.checked)) radios[0].checked = true;
    const row = h("span", { class: "folder-swatches", role: "radiogroup", "aria-label": "Màu thư mục" }, radios);
    return { row, get value() { return (radios.find((radio) => radio.checked) || radios[0]).value; } };
  }

  function folderBody(text, picker) {
    return h("span", { class: "folder-body" }, text, picker.row);
  }

  async function createFolderFor(id) {
    let created = null;
    const picker = folderColorPicker(FOLDER_COLORS[0].value);
    await dialog({
      tone: "accent", icon: "folder-plus", title: "Thư mục mới",
      body: folderBody("Gom các hội thoại liên quan; màu hiện thành chấm nhỏ cạnh tên hội thoại.", picker),
      fields: folderNameField(), confirmLabel: "Tạo", signal: viewSignal(),
      validate: async (values) => {
        if (!values.name) return "Nhập tên thư mục.";
        try {
          created = await Shell.api("/folders", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ name: values.name, color: picker.value }) });
          return null;
        } catch (error) {
          return isMissingApi(error) ? "Máy chủ chưa hỗ trợ thư mục hội thoại." : viError(error);
        }
      },
    });
    if (!created || !created.id) return;
    S.folders = [...S.folders, created];
    await moveToFolder(id, created.id);
  }

  async function manageFolders() {
    if (!S.folders.length) return;
    const count = (fid) => S.convs.filter((conv) => conv.folder_id === fid).length;
    const pick = await dialog({
      tone: "accent", icon: "folder", title: "Quản lý thư mục", body: "Chọn thư mục để đổi tên, đổi màu hoặc xóa.",
      options: S.folders.map((f) => ({ value: f.id, title: f.name, sub: `${count(f.id)} hội thoại` })),
      cancelLabel: "Đóng", signal: viewSignal(),
    });
    const folder = S.folders.find((f) => f.id === pick);
    if (!folder) return;
    const action = await dialog({
      tone: "accent", icon: "folder", title: `Thư mục «${folder.name}»`, body: "Chọn việc cần làm với thư mục này.",
      options: [
        { value: "edit", title: "Đổi tên hoặc màu", sub: "Hội thoại trong thư mục giữ nguyên" },
        { value: "delete", title: "Xóa thư mục", sub: "Hội thoại trong đó chuyển về không thư mục, không bị xóa" },
      ],
      signal: viewSignal(),
    });
    if (action === "edit") {
      let saved = null;
      const picker = folderColorPicker(folder.color);
      await dialog({
        tone: "accent", icon: "pen", title: "Sửa thư mục",
        body: folderBody("Đổi tên hoặc chọn màu khác; hội thoại trong thư mục giữ nguyên.", picker),
        fields: folderNameField(folder.name), confirmLabel: "Lưu", signal: viewSignal(),
        validate: async (values) => {
          if (!values.name) return "Nhập tên thư mục.";
          try {
            saved = await Shell.api(`/folders/${enc(folder.id)}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ name: values.name, color: picker.value }) });
            return null;
          } catch (error) {
            return isMissingApi(error) ? "Máy chủ chưa hỗ trợ thư mục hội thoại." : viError(error);
          }
        },
      });
      if (saved) {
        S.folders = S.folders.map((f) => (f.id === folder.id ? { ...f, ...saved } : f));
        renderConvList();
        toast("Đã lưu thư mục.");
      }
    } else if (action === "delete") {
      const yes = await confirmDialog({
        title: "Xóa thư mục?",
        body: `«${folder.name}» sẽ bị xóa; ${count(folder.id)} hội thoại trong đó chuyển về không thư mục.`,
        signal: viewSignal(),
      });
      if (!yes) return;
      try {
        await Shell.api(`/folders/${enc(folder.id)}`, { method: "DELETE" });
        toast("Đã xóa thư mục.");
      } catch (error) {
        toast(isMissingApi(error) ? "Máy chủ chưa hỗ trợ thư mục hội thoại." : viError(error), "danger");
      }
      loadConversations();
    }
  }

  function openConvMenu(id, anchor) {
    const conv = rowById(id);
    if (!conv) return;
    const pinned = conv.pinned === true;
    // Dòng không mang `pinned` VÀ máy chủ đã từ chối một lần → khóa như mục "Thư mục": hai chức năng
    // cùng thuộc F1 thì cùng một cách nói, không dẫn người dùng vào cú bấm chắc chắn lỗi (C-V8).
    const pinOff = typeof conv.pinned !== "boolean" && S.pinMissing;
    const items = [
      {
        label: pinned ? "Bỏ ghim" : "Ghim", icon: pinned ? "pin-off" : "pin",
        disabled: pinOff, hint: pinOff ? "máy chủ chưa hỗ trợ" : null, onSelect: () => togglePin(id),
      },
      { label: "Đổi tên", icon: "pen", onSelect: () => renameConv(id) },
      { separator: true },
    ];
    if (S.foldersMissing) {
      items.push({ label: "Thư mục", icon: "folder", hint: "máy chủ chưa hỗ trợ", disabled: true });
    } else {
      for (const folder of S.folders) {
        const here = folder.id === conv.folder_id;
        items.push({ label: folder.name, icon: here ? "check" : "folder", hint: here ? "đang ở đây" : null, onSelect: () => moveToFolder(id, folder.id) });
      }
      items.push({ label: "Bỏ khỏi thư mục", icon: "minus", disabled: !conv.folder_id, onSelect: () => moveToFolder(id, null) });
      items.push({ label: "Thư mục mới…", icon: "folder-plus", onSelect: () => createFolderFor(id) });
      if (S.folders.length) items.push({ label: "Quản lý thư mục…", icon: "gear", onSelect: () => manageFolders() });
    }
    items.push({ separator: true }, { label: "Xóa", icon: "trash", tone: "danger", onSelect: () => deleteConv(id) });
    dropdown(anchor, items, { align: "start", width: 232 });
  }

  /* ══════════════════════════════════════════════════════════════
     HEADER
     ══════════════════════════════════════════════════════════════ */
  function headerTitle() {
    if (!S.cur.id) return "Cuộc trò chuyện mới";
    const row = rowById(S.cur.id);
    if (row) return titleFor(row);
    return S.cur.title || S.titles[S.cur.id] || "Hội thoại";
  }

  function headerSub() {
    if (S.mode === "rag") return "Hỏi đáp theo tài liệu · có trích dẫn nguồn";
    return S.model ? `Trò chuyện tổng quát với ${S.model}` : "Trò chuyện tổng quát";
  }

  function setHeaderTitle() {
    if (V) V.ctx.setHeader(headerTitle(), headerSub());
  }

  async function loadModels() {
    if (S.modelsBusy) return;
    S.modelsBusy = true;
    try {
      const data = await Shell.api("/models");
      const name = data && data.models && data.models.general && data.models.general.name;
      S.model = typeof name === "string" && name ? name : null;
    } catch { /* không có tên model: phụ đề và composer để trống phần tên */ }
    finally { S.modelsBusy = false; }
    if (V) V.model.textContent = S.model || "";
    setHeaderTitle();
  }

  /* ══════════════════════════════════════════════════════════════
     TRANSCRIPT
     ══════════════════════════════════════════════════════════════ */
  function nearBottom() {
    const box = V && V.scroll;
    return !box || box.scrollHeight - box.scrollTop - box.clientHeight < NEAR_BOTTOM;
  }

  /* Màn hình thấp (800×600 trở xuống) thì riêng khối gợi ý của trạng thái rỗng đã cuộn được, nên
     nearBottom() là false và nút "Tin mới nhất" hiện lên trong cuộc trò chuyện CHƯA CÓ tin nhắn nào.
     Không có transcript thì không có "tin mới nhất" để nhảy tới. */
  function syncJump() {
    if (V) V.jump.hidden = V.transcript.hidden || nearBottom();
  }

  function scrollToBottom(force = false) {
    if (!V) return;
    if (force || nearBottom()) V.scroll.scrollTop = V.scroll.scrollHeight;
    syncJump();
  }

  function showEmpty() {
    if (!V) return;
    V.msgs.replaceChildren();
    V.empty.hidden = false;
    V.transcript.hidden = true;
    syncJump();
  }

  function showTranscript() {
    if (!V) return;
    V.empty.hidden = true;
    V.transcript.hidden = false;
  }

  function renderModeChip() {
    if (!V) return;
    const rag = S.mode === "rag";
    V.modeRow.hidden = !rag;
    if (!rag) return;
    let detail;
    if (!S.selected.size) detail = "chưa chọn tài liệu";
    else if (!S.docsLoaded) detail = `${S.selected.size} tài liệu`;
    else {
      const names = S.docs.filter((doc) => S.selected.has(doc.document_id)).map((doc) => doc.filename || "?");
      detail = !names.length ? `${S.selected.size} tài liệu`
        : names.length > 3 ? `${names.slice(0, 3).join(", ")} +${names.length - 3}` : names.join(", ");
    }
    V.modeChip.textContent = `Chế độ Tài liệu · ${detail}`;
    V.modeChip.title = V.modeChip.textContent;
  }

  function fillComposer(text) {
    if (!V) return;
    V.input.value = text;
    autosize();
    syncSend();
    V.input.focus();
    V.input.setSelectionRange(text.length, text.length);
  }

  function addUserMessage(text) {
    const node = h("div", { class: "msg msg-user" },
      h("div", { class: "bubble-wrap" },
        h("div", { class: "bubble-actions" },
          h("button", { type: "button", class: "icon-btn icon-btn-28", title: "Sao chép tin nhắn", "aria-label": "Sao chép tin nhắn", onClick: () => copyText(text) },
            icon("copy", { size: 14, sw: 1.9 })),
          h("button", { type: "button", class: "icon-btn icon-btn-28", title: "Sửa và gửi lại", "aria-label": "Sửa và gửi lại", onClick: () => fillComposer(text) },
            icon("pen", { size: 14, sw: 1.9 }))),
        h("div", { class: "bubble" }, text)));
    V.msgs.append(node);
    return node;
  }

  function groundingChip(grounding) {
    if (!grounding || !grounding.label || grounding.label === "unjudged") return null;
    const pct = Math.round((Number(grounding.grounded_ratio) || 0) * 100);
    let text;
    let tone;
    if (grounding.label === "grounded") { text = `bám nguồn ${pct}%`; tone = "tone-ok"; }
    else if (grounding.label === "weak") { text = grounding.language_mismatch ? "bám nguồn: khác ngôn ngữ nguồn" : `bám nguồn một phần (${pct}%)`; tone = "tone-warn"; }
    else { text = `${grounding.ungrounded ?? 0} câu không có nguồn`; tone = "tone-danger"; }
    const gaps = (Array.isArray(grounding.sentences) ? grounding.sentences : []).map((item) => `• ${item && item.text}`).join("\n");
    // Biểu tượng lấy từ bộ icon nét của thiết kế (theo màu chữ của nhãn), không dùng emoji màu:
    // ký tự ⚠ của app cũ rơi về phông emoji của hệ điều hành và vẽ một tam giác nhiều màu.
    const mark = grounding.label === "grounded" ? "check" : grounding.label === "ungrounded" ? "alert" : null;
    return h("span", {
      class: ["grounding", tone], title: gaps ? `Câu chưa đủ nguồn:\n${gaps}` : "Mọi câu đều có từ ngữ bám theo nguồn đã trích.",
    }, mark ? icon(mark, { size: 11, sw: 2.5 }) : null, text);
  }

  /* Kết quả công cụ (JSON có thể bị bọc marker chống injection và bị cắt 2400 ký tự)
     → một dòng tóm tắt; không đọc được thì 300 ký tự đầu như app cũ. */
  function toolSummary(content) {
    const text = String(content ?? "").replace(/^\s*<<<[^\n]*>>>\s*/, "").replace(/\s*<<<[^\n]*>>>\s*$/, "").trim();
    let data;
    try { data = JSON.parse(text); } catch { return { text: text.slice(0, 300), tone: "muted" }; }
    if (Array.isArray(data)) {
      const names = [...new Set(data.map((row) => row && (row.filename || row.document)).filter(Boolean))];
      return { text: names.length ? `${data.length} đoạn từ ${names.join(", ")}` : `${data.length} kết quả`, tone: "accent" };
    }
    if (data && typeof data === "object") {
      if (data.error) return { text: `Lỗi: ${data.error}`, tone: "danger" };
      if (typeof data.result === "string") return { text: data.result, tone: "muted" };
      const skip = new Set(["status", "service", "memory_queue", "checked_at", "backup_age_hours"]);
      const first = ["postgres", "qdrant", "redis", "ollama"];
      const pairs = Object.entries(data).filter(([key, value]) => !skip.has(key) && ["string", "number", "boolean"].includes(typeof value));
      pairs.sort((a, b) => (first.indexOf(a[0]) === -1 ? 99 : first.indexOf(a[0])) - (first.indexOf(b[0]) === -1 ? 99 : first.indexOf(b[0])));
      const shown = pairs.slice(0, 4).map(([key, value]) => `${key} ${value}`).join(" · ");
      return { text: pairs.length > 4 ? `${shown} · …` : shown, tone: "muted" };
    }
    return { text: String(data).slice(0, 300), tone: "muted" };
  }

  /* Tổng thời gian: mọi tool_result + mỗi vòng model một lần (các tool_call
     cùng một vòng lặp lại cùng latency_ms — agent_service.py:151,164) + final. */
  function stepsTotal(steps) {
    let total = 0;
    let any = false;
    let round = null;
    for (const step of steps) {
      if (!step || typeof step.latency_ms !== "number") continue;
      any = true;
      if (step.kind === "tool_call") {
        if (round !== step.latency_ms) total += step.latency_ms;
        round = step.latency_ms;
      } else {
        total += step.latency_ms;
        if (step.kind === "final") round = null;
      }
    }
    return any ? total : null;
  }

  function stepsPanel(steps) {
    const list = (Array.isArray(steps) ? steps : []).filter(Boolean);
    const calls = list.filter((step) => step.kind === "tool_call");
    if (!calls.length) return null;
    const used = new Set();
    const rows = calls.map((call, order) => {
      const from = list.indexOf(call);
      let result = null;
      for (let j = from + 1; j < list.length; j++) {
        const step = list[j];
        if (step.kind === "tool_result" && !used.has(j) && (step.tool_name || null) === (call.tool_name || null)) { result = step; used.add(j); break; }
      }
      const summary = result ? toolSummary(result.content) : null;
      const query = call.arguments && call.arguments.query != null ? String(call.arguments.query).slice(0, 80) : "";
      const tone = summary && summary.tone === "danger" ? "tone-danger" : /^search/.test(call.tool_name || "") ? null : "tone-muted";
      return h("div", { class: "step" },
        h("span", { class: ["num-badge", "num-badge-step", tone] }, order + 1),
        h("div", { class: "step-main" },
          h("div", { class: "step-line" },
            h("code", { class: "step-tool" }, call.tool_name || "?"),
            query ? h("span", { class: "step-arg" }, `«${query}»`) : null,
            result && typeof result.latency_ms === "number" ? h("span", { class: "step-ms" }, fmtDuration(result.latency_ms)) : null),
          summary && summary.text ? h("div", { class: "step-result" }, summary.text) : null));
    });
    const total = stepsTotal(list);
    return h("details", { class: "steps" },
      h("summary", null, icon("zap", { size: 14 }), `Agent đã dùng ${calls.length} lượt công cụ`,
        total !== null ? h("span", { class: "dur" }, fmtDuration(total)) : null),
      rows);
  }

  function sourceChip(src, n) {
    // Chip chỉ mang MỤC CUỐI của heading_path (prototype P:792 cũng dùng nhãn ngắn): cắt cả đường
    // mục ở 220px sẽ giấu đúng phần cụ thể nhất và đẩy chip xuống hai hàng. Đường đầy đủ nằm ở
    // tooltip và ở đầu popup trích dẫn.
    const where = pagesText(src) || lastHeading(src.heading_path);
    const tip = [src.filename || "?", headingText(src.heading_path), pagesText(src)].filter(Boolean).join(" · ");
    return h("button", { type: "button", class: "source-chip", title: tip, onClick: (event) => openCite(src, n, event.currentTarget) },
      h("span", { class: "num-badge" }, n),
      h("span", { class: "file" }, src.filename || "?"),
      where ? h("span", { class: "where" }, where) : null);
  }

  /* Một câu trả lời của trợ lý → handle; live = đang stream (có khối "đang trả lời"). */
  function addAssistantMessage({ live = true, pendingText = "" } = {}) {
    const avatar = h("div", { class: ["avatar-bot", live && "is-thinking"], "aria-hidden": "true" }, icon("spark", { size: 15, sw: 1.9 }));
    const pending = live ? h("div", { class: "msg-pending" },
      h("div", { class: "typing-row" }, h("span", { class: "typing-dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")), h("span", null, pendingText)),
      skeleton({ w: "70%", h: 12 }), skeleton({ w: "45%", h: 12 })) : null;
    const md = h("div", { class: "msg-md", hidden: live });
    const err = h("p", { class: "msg-error", hidden: true });
    const sourcesEl = h("div", { class: "sources", hidden: true });
    const meta = h("div", { class: "answer-meta", hidden: true });
    const body = h("div", { class: "msg-body" }, pending, md, err, sourcesEl, meta);
    const node = h("div", { class: "msg msg-assistant" }, avatar, body);
    if (V) V.msgs.append(node);
    let raw = "";
    let frame = 0;
    let dirty = false;   // raw đã đổi mà md chưa vẽ lại
    let stepsEl = null;
    // Nguồn về từ sự kiện `meta`, tức TRƯỚC token đầu tiên. Khối "đang tìm trong N tài liệu…" mà đã
    // có chip trích dẫn xong bên dưới thì trạng thái chờ tự mâu thuẫn (thiết kế P:191-198 chỉ có 2
    // vạch mờ) → giữ chip ẩn tới khi lượt bắt đầu chảy chữ / kết thúc / lỗi.
    let sourcesOn = !live;
    const revealSources = () => { sourcesOn = true; sourcesEl.hidden = !sourcesEl.childNodes.length; };
    msgSources.set(node, []);

    // Chỉ lượt đang chờ và còn nằm trên màn hình mới được đọc cho trình đọc màn hình: không đọc lịch
    // sử vừa mở, không đọc câu trả lời đã bỏ dở khi người dùng chuyển hội thoại hay rời trang.
    const attached = () => Boolean(V && V.msgs.contains(node));
    const say = (text) => { if (live && attached()) announce(text); };
    const paint = () => {
      frame = 0;
      dirty = false;
      md.innerHTML = renderMarkdown(raw);
      if (attached()) scrollToBottom();
    };
    const settle = () => {
      if (frame) { cancelAnimationFrame(frame); frame = 0; }
      avatar.classList.remove("is-thinking");
      md.classList.remove("is-streaming");
      if (pending) pending.remove();
    };
    const flush = () => {
      if (raw && dirty) md.innerHTML = renderMarkdown(raw);
      dirty = false;
    };
    const iconButton = (name, label, onClick) => h("button", { type: "button", class: "icon-btn icon-btn-28", title: label, "aria-label": label, onClick },
      icon(name, { size: 14, sw: 1.9 }));

    return {
      node,
      get text() { return raw; },
      setRaw(text) {
        raw = String(text ?? "");
        dirty = false;
        md.hidden = !raw;
        md.innerHTML = renderMarkdown(raw);
      },
      start() {
        if (pending) pending.remove();
        revealSources();
        md.hidden = false;
        md.classList.add("is-streaming");
        say("Đang trả lời…");
      },
      append(token) {
        raw += String(token ?? "");
        dirty = true;
        if (!frame) frame = requestAnimationFrame(paint);
      },
      setSteps(steps) {
        const panel = stepsPanel(steps);
        if (stepsEl) stepsEl.remove();
        stepsEl = panel;
        if (panel) body.insertBefore(panel, sourcesEl);
      },
      setSources(list) {
        const sources = (Array.isArray(list) ? list : []).filter((src) => src && typeof src === "object");
        msgSources.set(node, sources);
        sourcesEl.replaceChildren(...sources.map((src, i) => sourceChip(src, i + 1)));
        sourcesEl.hidden = !sourcesOn || !sources.length;
      },
      finish({ model = null, seconds = null, stopped = false, retry = null, grounding = null } = {}) {
        settle();
        revealSources();
        md.hidden = !raw;
        flush();   // lịch sử đã vẽ ở setRaw → không vẽ lần hai
        const text = [model, seconds !== null ? `${seconds}s` : null, stopped ? "đã dừng" : null].filter(Boolean).join(" · ");
        const actions = [];
        if (raw) actions.push(iconButton("copy", "Sao chép câu trả lời", () => copyText(raw)));
        if (retry) actions.push(iconButton("retry", "Tạo câu trả lời khác (thêm lượt mới)", retry));
        // replaceChildren(null) chèn chữ "null" → lọc trước.
        meta.replaceChildren(...[
          text ? h("span", null, text) : null,
          prefs.showGrounding !== false ? groundingChip(grounding) : null,
          actions.length ? h("span", { class: "answer-actions" }, actions) : null,
        ].filter(Boolean));
        meta.hidden = !meta.childNodes.length;
        if (raw && !stopped) say(`Trợ lý: ${md.textContent}`);
        else if (stopped) say("Đã dừng trả lời.");
        if (attached()) scrollToBottom();
      },
      fail(message, retry) {
        settle();
        revealSources();
        md.hidden = !raw;
        flush();
        node.classList.add("is-error");
        err.textContent = `⚠ ${message}`;
        err.hidden = false;
        if (retry) meta.replaceChildren(h("button", { type: "button", class: "btn btn-28 btn-outline", onClick: retry }, icon("retry", { size: 13 }), "Thử lại"));
        else meta.replaceChildren();
        meta.hidden = !retry;
        say(`Lỗi: ${message}`);
        if (attached()) scrollToBottom();
      },
    };
  }

  /* Hội thoại đã lưu: không có giây, không tạo lại, không nhãn bám nguồn, không bước agent (API không trả). */
  function renderHistory(messages) {
    if (!V) return;
    V.msgs.replaceChildren();
    if (!messages.length) { showEmpty(); return; }
    showTranscript();
    renderModeChip();
    for (const message of messages) {
      if (message.role === "user") {
        addUserMessage(String(message.content ?? ""));
      } else {
        const handle = addAssistantMessage({ live: false });
        handle.setRaw(message.content);
        handle.setSources(message.sources || []);
        handle.finish({ model: message.model_used || null });
      }
    }
    requestAnimationFrame(() => scrollToBottom(true));
  }

  /* ══════════════════════════════════════════════════════════════
     MỞ / TẠO HỘI THOẠI + URL
     ══════════════════════════════════════════════════════════════ */

  /* Ghi id vào URL không thêm lịch sử và không dựng lại view (update() thấy id trùng → giữ nguyên). */
  function replaceUrl(id) {
    if (!V || !Router.current || Router.current.name !== "chat") return;
    const hash = id ? `#/chat/${enc(id)}` : "#/chat";
    // silent: chỉ ghi hash + Router.current, không phát "lac:route" — shell không đóng sidebar di động
    // người dùng vừa mở chỉ vì câu trả lời nhận được id.
    if (location.hash !== hash) Router.replace(hash, { silent: true });
  }

  /* Nhả trạng thái "đang sinh" NGAY khi hủy: lượt cũ dù còn nhận byte nào cũng chỉ ghi vào tin nhắn
     đã tách khỏi trang và không được nhận id (S.gen !== turn), còn composer dùng được liền. */
  function abortTurn() {
    const turn = S.gen;
    if (!turn) return;
    S.gen = null;
    turn.controller.abort();
    setGenerating();
  }

  function newChat({ focus = true } = {}) {
    abortTurn();
    S.cur = { id: null, title: null, seq: S.cur.seq + 1 };
    S.memoryOn = Boolean(prefs.memoryDefault);
    closeCite({ restore: false });
    if (MOBILE.matches) setDocsOpen(false);
    showEmpty();
    syncChips();
    setHeaderTitle();
    renderConvList();
    if (focus && V) V.input.focus({ preventScroll: true });
  }

  /* S.cur.loading: đang chờ lịch sử — chưa cho gửi, vì lịch sử về sau sẽ vẽ đè lượt vừa gửi.
     S.cur.failed: tải lỗi (không phải 404) — giữ id như app cũ, nhưng bấm lại hội thoại là tải lại. */
  async function openConversation(id, { force = false } = {}) {
    const v = V;
    if (!v) return;
    if (!force && S.cur.id === id) {
      if (MOBILE.matches) setDocsOpen(false);
      return;
    }
    abortTurn();
    const seq = S.cur.seq + 1;
    S.cur = { id, title: null, seq, loading: true, failed: false };
    closeCite({ restore: false });
    if (MOBILE.matches) setDocsOpen(false);
    setHeaderTitle();
    renderConvList();
    showTranscript();
    renderModeChip();
    syncSend();
    v.msgs.replaceChildren(...[72, 48, 60].map((height) => h("div", { class: "msg-skel" }, skeleton({ h: height, r: 12 }))));
    try {
      const detail = await Shell.api(`/conversations/${enc(id)}`, { signal: v.ctx.signal });
      if (V !== v || S.cur.seq !== seq) return;
      S.cur.loading = false;
      S.cur.title = (detail && detail.title) || null;
      const messages = Array.isArray(detail && detail.messages) ? detail.messages : [];
      renderHistory(messages);
      if (!S.cur.title && !S.titles[id] && messages.length) {
        // Hội thoại cũ tạo trước khi máy chủ lưu tiêu đề: đặt tên cục bộ theo câu hỏi đầu (≤60 ký tự).
        const first = messages.find((message) => message.role === "user");
        if (first) { S.titles[id] = String(first.content || "").slice(0, 60); saveTitles(); renderConvList(); }
      }
      setHeaderTitle();
      syncSend();
    } catch (error) {
      if (V !== v || S.cur.seq !== seq || v.ctx.signal.aborted) return;
      S.cur.loading = false;
      syncSend();
      if (error.status === 404) {
        showEmpty();
        toast(error.message, "danger");
        S.cur = { id: null, title: null, seq: S.cur.seq + 1 };
        replaceUrl(null);
        setHeaderTitle();
        loadConversations();
        return;
      }
      // 500 / mất mạng / hết phiên: không giả làm cuộc trò chuyện mới — báo lỗi ngay trong khung chat.
      S.cur.failed = true;
      const box = emptyState({
        icon: "alert", tone: "danger", title: "Không tải được hội thoại", text: viError(error),
        action: { label: "Thử lại", icon: "retry", onClick: () => openConversation(id, { force: true }) },
      });
      box.classList.add("is-error", "chat-load-error");
      box.setAttribute("role", "alert");
      v.msgs.replaceChildren(box);
      // Hết phiên: shell đã dừng router và hiện màn đăng nhập; after() được hoãn tới khi đăng nhập
      // lại (Router.resume) → tự tải lại hội thoại, người dùng không phải bấm gì thêm.
      if (error.status === 401 && Router.paused) {
        v.ctx.after(() => { if (V === v && S.cur.failed && S.cur.id === id && !S.gen) openConversation(id, { force: true }); }, 0);
      }
    }
  }

  /* ══════════════════════════════════════════════════════════════
     LUỒNG SSE — chỗ gọi mạng thô duy nhất của view
     ══════════════════════════════════════════════════════════════ */
  function streamError(data, status) {
    const code = data && data.error_code;
    const error = new Error(ERROR_HINTS[code] || CHAT_HINTS[code] || (data && data.message) || `Yêu cầu thất bại (${status}).`);
    error.code = data && data.error_code;
    error.status = status;
    return error;
  }

  /* Khối "event: X\ndata: {…}" → {type, data}. Tách dòng CHỈ theo "\n" (sửa D9:
     regex với "." của bản cũ cắt dữ liệu tại U+2028/U+2029 và làm hỏng cả lượt). */
  function parseBlock(block) {
    let type = "message";
    const data = [];
    for (const rawLine of block.split("\n")) {
      const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
      if (line.startsWith("event:")) type = line.slice(6).replace(/^ /, "");
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (!data.length) return null;
    try {
      return { type, data: JSON.parse(data.join("\n")) };
    } catch {
      throw new Error("Luồng trả lời từ máy chủ bị lỗi định dạng.");
    }
  }

  async function streamChat(path, body, signal, on) {
    const send = () => fetch(path, { method: "POST", headers: authHeaders(JSON_HEADERS), body: JSON.stringify(body), signal });
    let response;
    try {
      response = await send();
      if (response.status === 401 && (await refreshAccessToken())) response = await send();
    } catch (error) {
      if (isAbort(error)) throw error;
      throw new Error(OFFLINE); // sửa D8: không để lộ "Failed to fetch"
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      if (response.status === 401 && Shell.authEnabled) {
        // Refresh hỏng: nhờ shell mở màn đăng nhập (Shell.api tự làm việc đó khi gặp 401 cuối).
        Shell.api("/auth/me").catch(() => {});
      }
      throw streamError(data, response.status);
    }
    if (!response.body || typeof response.body.getReader !== "function") throw new Error("Trình duyệt không đọc được luồng trả lời.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const dispatch = (block) => {
      const event = parseBlock(block);
      if (!event) return;
      const data = event.data || {};
      if (event.type === "meta") on.meta(data);
      else if (event.type === "steps") on.steps(Array.isArray(data.steps) ? data.steps : []);
      else if (event.type === "token") on.token(data.content);
      else if (event.type === "done") on.done(data);
      else if (event.type === "error") throw streamError(data, 200);
    };
    try {
      for (;;) {
        let chunk;
        try {
          chunk = await reader.read();
        } catch (error) {
          if (isAbort(error) || (signal && signal.aborted)) throw Object.assign(new Error("Đã dừng."), { name: "AbortError" });
          throw new Error("Mất kết nối khi đang nhận câu trả lời.");
        }
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        let match;
        while ((match = /\r?\n\r?\n/.exec(buffer))) {
          const block = buffer.slice(0, match.index);
          buffer = buffer.slice(match.index + match[0].length);
          dispatch(block);
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) dispatch(buffer);
    } catch (error) {
      reader.cancel().catch(() => {});   // sự kiện error / lỗi định dạng: đóng luồng, không đọc tiếp
      throw error;
    }
    // Luồng đóng mà không có "done" vẫn coi là xong (D10, giữ như app cũ).
  }

  /* Phạm vi hỏi đáp phải hợp lệ trước khi gửi → câu cần báo, hoặc null khi gửi được.
     Trần 100 tài liệu là của máy chủ (rag_schema.py): gửi quá sẽ nhận 422 tiếng Anh khó hiểu. */
  function ragScopeProblem() {
    if (S.mode !== "rag") return null;
    if (!S.selected.size) return "Hãy chọn ít nhất một tài liệu đã lập chỉ mục trước.";
    if (S.selected.size > MAX_DOCS) return `Chỉ hỏi được tối đa ${MAX_DOCS} tài liệu một lượt — bỏ bớt lựa chọn.`;
    return null;
  }

  function pendingText() {
    if (S.mode === "rag") return `Đang tìm trong ${S.selected.size} tài liệu…`;
    return S.toolsOn ? "Agent đang dùng công cụ…" : "Đang suy nghĩ…";
  }

  async function sendPrompt(prompt) {
    if (S.gen || !V || S.cur.loading) return;
    const scope = ragScopeProblem();
    if (scope) {
      toast(scope, "danger");
      setDocsOpen(true);
      return;
    }
    const mode = S.mode;
    closeCite({ restore: false });
    // Bỏ khung "Không tải được hội thoại" MỘT lần, trước lượt mới. Xóa cờ ngay tại đây: nếu không,
    // mọi lượt sau cũng tháo sạch .msgs và người dùng thấy hội thoại của mình biến mất (C-V1).
    if (S.cur.failed) { S.cur.failed = false; V.msgs.replaceChildren(); }
    showTranscript();
    renderModeChip();
    addUserMessage(prompt);
    const handle = addAssistantMessage({ live: true, pendingText: pendingText() });
    scrollToBottom(true);
    const controller = new AbortController();
    const turn = { controller, startedAt: performance.now() };
    S.gen = turn;
    setGenerating();
    const started = performance.now();
    const startingId = S.cur.id;
    const startingSeq = S.cur.seq;
    const isNew = !startingId;
    let streamId = startingId;
    let model = null;
    let grounding = null;
    let firstToken = false;
    const body = mode === "general"
      ? { message: prompt, conversation_id: startingId, use_memory: S.memoryOn, use_tools: S.toolsOn, stream: true }
      : { message: prompt, document_ids: [...S.selected], conversation_id: startingId, stream: true };
    const retry = () => sendPrompt(prompt);
    try {
      await streamChat(mode === "general" ? "/chat" : "/rag/chat", body, controller.signal, {
        meta(data) {
          model = data.model_used || null;
          if (data.conversation_id) {
            streamId = data.conversation_id;
            // Chỉ nhận id khi lượt này vẫn là lượt hiện hành và người dùng chưa mở hội thoại khác:
            // meta đến muộn của một luồng đã hủy không bao giờ được ghi đè hội thoại đang mở.
            if (S.gen === turn && S.cur.id === startingId && startingId !== streamId) {
              S.cur = { ...S.cur, id: streamId };
              replaceUrl(streamId);
              loadConversations({ quiet: true });
            }
          }
          if (mode === "rag") handle.setSources(data.sources || []);
        },
        steps(steps) { handle.setSteps(steps); },
        token(text) {
          if (!firstToken) { firstToken = true; handle.start(); }
          handle.append(text);
        },
        done(data) { grounding = (data && data.grounding) || null; },
      });
      handle.finish({ model, seconds: ((performance.now() - started) / 1000).toFixed(1), retry, grounding: mode === "rag" ? grounding : null });
      if (isNew && streamId) {
        S.titles[streamId] = prompt.slice(0, 60);
        saveTitles();
      }
      // Tải lại danh sách rồi đặt tiêu đề header theo tên máy chủ (sửa D12).
      loadConversations({ quiet: true });
    } catch (error) {
      // Máy chủ giữ phần đã stream; nhưng lượt MỚI hỏng/dừng khi chưa có token nào thì hội thoại mà
      // meta vừa báo đã bị máy chủ xóa → bỏ id, URL và dòng ở thanh bên (lần gửi sau tạo hội thoại mới).
      const dropNew = () => {
        // Lượt MỚI HƠN đã bắt đầu (hoặc người dùng đã mở/tạo hội thoại khác) thì im lặng: một lượt bị
        // dừng không được rút id, URL và dòng thanh bên ra từ dưới chân câu trả lời đang chạy (B-V1).
        if (S.gen || S.cur.seq !== startingSeq) return;
        if (isNew && !handle.text && streamId && S.cur.id === streamId) {
          S.cur = { id: null, title: null, seq: S.cur.seq + 1 };
          replaceUrl(null);
          setHeaderTitle();
          renderConvList();
        }
      };
      if (isAbort(error) || controller.signal.aborted) {
        dropNew();
        handle.finish({ model, stopped: true });
        loadConversations({ quiet: true });
      } else if (error.code === "CONVERSATION_NOT_FOUND") {
        if (S.cur.id === startingId) {
          S.cur = { id: null, title: null, seq: S.cur.seq + 1 };
          replaceUrl(null);
          setHeaderTitle();
        }
        handle.fail(`${error.message} Tin nhắn tiếp theo sẽ tạo cuộc trò chuyện mới.`, retry);
        loadConversations();
      } else {
        dropNew();
        handle.fail(error.message || "Lỗi khi sinh phản hồi.", retry);
        if (streamId) loadConversations({ quiet: true });   // meta đã đến: danh sách đổi (xóa / thêm phần dở)
      }
    } finally {
      if (S.gen === turn) {
        S.gen = null;
        setGenerating();
      }
    }
  }

  /* ══════════════════════════════════════════════════════════════
     COMPOSER
     ══════════════════════════════════════════════════════════════ */
  function autosize() {
    if (!V) return;
    const input = V.input;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
  }

  function syncSend() {
    if (!V) return;
    const btn = V.send;
    const busy = Boolean(S.gen);
    const want = busy ? "stop" : "send";
    if (btn.dataset.mode !== want) {
      btn.dataset.mode = want;
      btn.replaceChildren(busy ? icon("stop", { size: 14 }) : icon("send", { size: 16, sw: 2.2 }));
      btn.classList.toggle("is-stop", busy);
    }
    if (busy) {
      btn.disabled = false;
      btn.title = "Dừng trả lời";
      btn.setAttribute("aria-label", "Dừng trả lời");
    } else {
      btn.disabled = !V.input.value.trim() || Boolean(S.cur.loading);
      btn.title = S.cur.loading ? "Đang tải hội thoại…"
        : prefs.enterToSend !== false ? "Gửi (Enter) · Shift+Enter xuống dòng" : "Bấm nút gửi · Enter xuống dòng";
      btn.setAttribute("aria-label", "Gửi");
    }
  }

  function setGenerating() {
    if (!V) return;
    for (const item of V.seg.querySelectorAll(".seg-item")) item.disabled = Boolean(S.gen);
    syncSend();
  }

  function submit() {
    if (!V) return;
    const prompt = V.input.value.trim();
    // Đang sinh hoặc đang tải lịch sử: bỏ qua, giữ nguyên chữ đang gõ để gửi sau.
    if (!prompt || S.gen || S.cur.loading) return;
    // Kiểm trước khi xóa ô soạn: người dùng không bao giờ mất tin đang gõ.
    const scope = ragScopeProblem();
    if (scope) {
      toast(scope, "danger");
      setDocsOpen(true);
      return;
    }
    V.input.value = "";
    autosize();
    syncSend();
    sendPrompt(prompt);
  }

  function setMode(mode) {
    if (S.gen) return;
    S.mode = mode === "rag" ? "rag" : "general";
    prefs.mode = S.mode;
    safeSavePrefs();
    if (V) V.seg.setValue(S.mode);
    syncChips();
    setHeaderTitle();
  }

  function syncChips() {
    if (!V) return;
    const rag = S.mode === "rag";
    V.input.placeholder = rag ? "Hỏi về nội dung tài liệu đã chọn…" : "Nhập tin nhắn…";
    V.docsChip.hidden = !rag;
    V.memChip.hidden = rag;
    V.memChip.setActive(S.memoryOn);
    V.memChip.setLabel(S.memoryOn ? "Ghi nhớ: bật" : "Ghi nhớ: tắt");
    V.toolsChip.setActive(S.toolsOn);
    V.toolsChip.setLabel(S.toolsOn ? "Công cụ: bật" : "Công cụ: tắt");
    renderModeChip();
  }

  function buildComposer() {
    const input = h("textarea", {
      class: "composer-input", rows: "1", maxlength: "10000", autocomplete: "off", "aria-label": "Tin nhắn",
      placeholder: S.mode === "rag" ? "Hỏi về nội dung tài liệu đã chọn…" : "Nhập tin nhắn…",
    });
    const send = h("button", { type: "button", class: "icon-btn-primary composer-send" });
    const seg = segmented([
      { value: "general", label: "Trò chuyện", icon: "chat" },
      { value: "rag", label: "Tài liệu", icon: "book" },
    ], S.mode, setMode, { label: "Chế độ trò chuyện" });
    const docsChip = chip("Chọn tài liệu", { icon: "book", onClick: () => setDocsOpen(!S.docsOpen) });
    docsChip.classList.add("hover-accent");
    docsChip.removeAttribute("aria-pressed");
    const memChip = chip("Ghi nhớ: tắt", {
      icon: "lightbulb", active: S.memoryOn, title: "Dùng ghi nhớ đã lưu cho câu hỏi này (chỉ trong phiên này)",
      onClick: () => { S.memoryOn = !S.memoryOn; syncChips(); },
    });
    const toolsChip = chip("Công cụ: tắt", {
      icon: "zap", active: S.toolsOn, title: "Cho agent dùng công cụ (tìm tài liệu, trạng thái hệ thống) — chỉ áp dụng ở chế độ Trò chuyện",
      onClick: () => { S.toolsOn = !S.toolsOn; prefs.toolsOn = S.toolsOn; safeSavePrefs(); syncChips(); },
    });
    const model = h("span", { class: "composer-model" }, S.model || "");
    const jump = h("button", { type: "button", class: "jump-latest", hidden: true, onClick: () => scrollToBottom(true) },
      icon("chevron-down", { size: 14 }), "Tin mới nhất");
    const wrap = h("div", { class: "composer-wrap" }, jump,
      h("div", { class: "composer" },
        h("div", { class: "composer-row" }, input, send),
        h("div", { class: "composer-tools" }, seg, docsChip, memChip, toolsChip, h("span", { class: "spacer" }), model)));

    // syncJump: ô soạn cao lên (tới 200px) đẩy tin nhắn cuối ra khỏi tầm nhìn mà không có sự kiện
    // cuộn nào — không gọi ở đây thì nút "Tin mới nhất" đứng im cho tới lần cuộn kế tiếp.
    input.addEventListener("input", () => { autosize(); syncSend(); syncJump(); });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && prefs.enterToSend !== false && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault();
        submit();
      }
    });
    send.addEventListener("click", (event) => {
      if (!S.gen) { submit(); return; }
      // Nút Gửi vừa hóa thành nút Dừng ngay dưới con trỏ: cú bấm thứ hai của một cú nhấp đúp (hoặc
      // bấm liền tay trong 0,4 giây) không được dừng câu trả lời vừa gửi. Bấm Dừng sau đó vẫn dừng.
      if (event.detail > 1 || performance.now() - S.gen.startedAt < 400) return;
      abortTurn();
    });
    return { wrap, input, send, seg, docsChip, memChip, toolsChip, model, jump };
  }

  function buildEmpty() {
    return h("section", { class: "empty chat-empty" },
      h("div", { class: "empty-logo" }, icon("spark", { size: 28, sw: 1.8 })),
      h("h2", null, "Tôi có thể giúp gì cho bạn?"),
      h("p", null, "Trò chuyện với mô hình chạy trên máy nội bộ, hoặc hỏi đáp theo tài liệu đã tải lên với trích dẫn nguồn rõ ràng."),
      h("div", { class: "empty-grid" }, SUGGESTIONS.map((s) => h("button", {
        type: "button", class: "suggestion",
        onClick: () => {
          if (s.docs) { setMode("rag"); setDocsOpen(true); }
          else fillComposer(s.fill);
        },
      }, h("span", { class: "icon-tile tone-accent" }, icon(s.icon, { size: 15 })), h("span", null, h("strong", null, s.title), s.body)))));
  }

  /* ══════════════════════════════════════════════════════════════
     POPUP TRÍCH DẪN
     ══════════════════════════════════════════════════════════════ */
  function closeCite({ restore = true } = {}) {
    S.citeSeq += 1;
    const cite = V && V.cite;
    if (!cite) return;
    V.cite = null;
    cite.abort.abort();   // đóng popup là bỏ luôn ảnh trang đang tải dở, không tải xong rồi vứt
    cite.pop.remove();
    cite.catcher.remove();
    for (const url of cite.urls) URL.revokeObjectURL(url);
    if (restore && cite.opener && cite.opener.isConnected) cite.opener.focus({ preventScroll: true });
  }

  function citePlaceholder(box, text) {
    box.className = "cite-preview page-placeholder";
    box.replaceChildren(h("span", { class: "label" }, text));
  }

  async function loadPreview(src, box, seq, signal) {
    const page = src.page_start ?? src.page ?? null;
    if (/\.(md|markdown|txt)$/i.test(src.filename || "")) { citePlaceholder(box, "Tài liệu văn bản — không có trang"); return; }
    if (page === null || !src.document_id) { citePlaceholder(box, "Đoạn này không có số trang"); return; }
    box.className = "cite-preview is-loading";
    box.replaceChildren(skeleton({ w: 120, h: 168, r: 4 }));
    try {
      const blob = await Shell.fetchBlob(`/documents/${enc(src.document_id)}/pages/${enc(page)}.png`, { signal });
      if (seq !== S.citeSeq || !V || !V.cite) return;
      const url = URL.createObjectURL(blob);
      V.cite.urls.push(url);
      const frame = h("div", { class: "cite-page" }, h("img", { src: url, alt: `Trang ${page} của ${src.filename || "tài liệu"}` }));
      box.className = "cite-preview has-page";
      box.replaceChildren(frame);
      if (!src.chunk_id) return;
      try {
        const data = await Shell.api(`/documents/${enc(src.document_id)}/pages/${enc(page)}/boxes?chunk_id=${enc(src.chunk_id)}`, { signal });
        if (seq !== S.citeSeq) return;
        const unit = (n) => Number.isFinite(Number(n)) ? Math.max(0, Math.min(1, Number(n))) : null;
        for (const b of (data && Array.isArray(data.boxes) ? data.boxes : [])) {
          const [x, y, w, hh] = [unit(b.x), unit(b.y), unit(b.w), unit(b.h)];
          if ([x, y, w, hh].some((n) => n === null) || !w || !hh) continue;
          frame.append(h("span", { class: "cite-box", style: { left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${hh * 100}%` } }));
        }
      } catch { /* chưa có vùng đánh dấu: vẫn xem được trang */ }
    } catch (error) {
      if (seq !== S.citeSeq || (signal && signal.aborted)) return;
      citePlaceholder(box, isMissingApi(error) ? "Chưa có ảnh xem trước trang" : "Không tải được ảnh trang");
    }
  }

  function openCite(src, n, opener) {
    const v = V;
    if (!v || !src) return;
    closeCite({ restore: false });
    const seq = S.citeSeq;
    const docId = src.document_id || null;
    // Đường mục dài thì cắt, còn trang + version luôn thấy được.
    const path = headingText(src.heading_path);
    const tail = [pagesText(src), src.index_version != null ? `version ${src.index_version}` : null].filter(Boolean).join(" · ");
    const where = path || tail ? h("div", { class: "cite-where" },
      path ? h("span", { class: "cite-path", title: path }, path) : null,
      tail ? h("span", { class: "cite-tail" }, path ? ` · ${tail}` : tail) : null) : null;
    const excerpt = String(src.content || src.excerpt || "").trim();
    const foot = [];
    if (Number.isInteger(src.chunk_index)) foot.push(h("span", null, `đoạn #${src.chunk_index}`));
    if (Number.isFinite(src.token_count)) foot.push(h("span", null, `${fmtNumber(src.token_count)} token`));
    if (docId) foot.push(h("a", { href: `#/chunks/${enc(docId)}` }, "Xem tất cả đoạn →"));
    const footNodes = foot.flatMap((node, i) => (i ? [h("span", { "aria-hidden": "true" }, "·"), node] : [node]));
    const preview = h("div", { class: "cite-preview" });
    const pop = h("div", { class: "popover cite-pop", role: "dialog", "aria-label": `Nguồn ${n}: ${src.filename || "?"}`, tabindex: "-1" },
      h("div", { class: "popover-head" },
        h("span", { class: "num-badge num-badge-24" }, n),
        h("div", { class: "cite-title" },
          h("div", { class: "cite-file" }, src.filename || "?"),
          where),
        docId ? h("a", { class: "cite-open", href: `#/documents?doc=${enc(docId)}` }, "Mở tài liệu", icon("external-link", { size: 12 })) : null,
        h("button", { type: "button", class: "icon-btn icon-btn-30", title: "Đóng", "aria-label": "Đóng", onClick: () => closeCite() }, icon("x", { size: 15 }))),
      h("div", { class: "cite-body" },
        preview,
        h("div", { class: "cite-excerpt" },
          h("div", { class: "section-label" }, "Đoạn được trích"),
          h("p", null, excerpt ? h("mark", { class: "hl" }, excerpt) : h("span", { class: "cite-none" }, "Máy chủ không trả nội dung đoạn này.")),
          footNodes.length ? h("div", { class: "cite-foot" }, footNodes) : null)));
    const catcher = h("div", { class: "popover-catcher", onClick: () => closeCite() });
    // Lớp chắn nuốt mọi cú chuột ra ngoài popup, nên phím Tab cũng không được lang thang ra sau nó:
    // popup là hộp thoại thật (aria-modal) và giữ vòng Tab bên trong, Esc/X/bấm ra ngoài mới thoát.
    pop.setAttribute("aria-modal", "true");
    pop.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const stops = [...pop.querySelectorAll("button, a[href], input, [tabindex]:not([tabindex='-1'])")]
        .filter((node) => !node.disabled && !node.hidden && node.getClientRects().length > 0);
      if (!stops.length) { event.preventDefault(); pop.focus({ preventScroll: true }); return; }
      const first = stops[0];
      const last = stops[stops.length - 1];
      const at = document.activeElement;
      if (event.shiftKey && (at === first || at === pop)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && at === last) { event.preventDefault(); first.focus(); }
    });
    v.col.append(catcher, pop);
    v.cite = { pop, catcher, opener: opener || null, urls: [], abort: new AbortController() };
    loadPreview(src, preview, seq, v.cite.abort.signal);
    pop.focus({ preventScroll: true });
  }

  /* ══════════════════════════════════════════════════════════════
     DRAWER "PHẠM VI HỎI ĐÁP" + TẢI LÊN
     ══════════════════════════════════════════════════════════════ */
  function indexedDocs() {
    return S.docs.filter((doc) => doc.status === "indexed");
  }

  function pruneSelection() {
    // Chỉ bỏ id vắng mặt trong một lần tải THÀNH CÔNG (lỗi mạng không được xóa lựa chọn đã lưu), và
    // tài liệu đang xóa (đã rời truy xuất, sắp biến mất). Tài liệu đang lập chỉ mục lại vẫn được giữ:
    // xong là dùng lại được ngay.
    const alive = new Set(S.docs.filter((doc) => doc.status !== "deleting").map((doc) => doc.document_id));
    let changed = false;
    for (const id of [...S.selected]) if (!alive.has(id)) { S.selected.delete(id); changed = true; }
    if (changed) saveSelection();
  }

  async function loadDocuments() {
    const seq = ++S.docsSeq;
    S.docsBusy = true;
    try {
      const rows = await Shell.api("/documents");
      if (seq !== S.docsSeq) return;
      S.docs = Array.isArray(rows) ? rows.filter((doc) => doc && doc.document_id) : [];
      S.docsLoaded = true;
      S.docsError = null;
      pruneSelection();
    } catch (error) {
      if (seq !== S.docsSeq) return;
      S.docsError = error;   // giữ nguyên lựa chọn đã lưu khi backend tạm lỗi
    } finally {
      if (seq === S.docsSeq) S.docsBusy = false;
    }
    renderDocsList();
    syncDocsUi();
  }

  function syncDocsUi() {
    if (!V) return;
    const count = S.selected.size;
    V.badge.textContent = String(count);
    V.badge.hidden = !count;
    V.docsBtn.classList.toggle("is-active", S.docsOpen);
    V.docsChip.setLabel(count ? `${count} tài liệu` : "Chọn tài liệu");
    for (const node of [V.docsBtn, V.docsChip]) {
      node.setAttribute("aria-expanded", String(S.docsOpen));
      // aria-controls chỉ trỏ tới #chat-docs khi drawer thật sự có trong trang.
      if (S.docsOpen) node.setAttribute("aria-controls", "chat-docs");
      else node.removeAttribute("aria-controls");
    }
    const d = V.drawer;
    if (d) {
      const indexed = indexedDocs();
      d.count.textContent = `Đã lập chỉ mục · ${indexed.length}`;
      d.all.checked = indexed.length > 0 && indexed.every((doc) => S.selected.has(doc.document_id));
      d.all.indeterminate = count > 0 && !d.all.checked;
      d.all.disabled = !indexed.length;
    }
    renderModeChip();
  }

  function toggleDoc(id, on) {
    if (on) S.selected.add(id);
    else S.selected.delete(id);
    saveSelection();
    syncDocCards();   // chỉ đổi trạng thái thẻ, không dựng lại danh sách → focus bàn phím đứng yên
    syncDocsUi();
  }

  async function reindex(doc) {
    const id = doc.document_id;
    if (S.reindexing.has(id)) return;   // bấm đúp: chỉ một yêu cầu (lần hai sẽ nhận 409)
    S.reindexing.add(id);
    renderDocsList();
    try {
      await Shell.api("/documents/index", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ document_id: id }) });
      toast(`Đã gửi lập chỉ mục «${doc.filename}».`);
    } catch (error) {
      toast(viError(error), "danger");
    }
    await loadDocuments();   // nút chỉ bấm lại được khi đã thấy trạng thái mới của tài liệu
    S.reindexing.delete(id);
    renderDocsList();
  }

  function docMeta(doc) {
    const admin = Shell.isAdmin();
    const busy = S.reindexing.has(doc.document_id);
    const action = (label) => h("button", {
      type: "button", class: "doc-retry", disabled: busy, "aria-busy": busy ? "true" : null,
      onClick: (event) => { event.preventDefault(); event.stopPropagation(); reindex(doc); },
    }, label);
    if (doc.status === "indexed") {
      return h("span", { class: "doc-meta" }, `${fmtNumber(doc.chunks_count ?? 0)} đoạn · v${doc.active_index_version ?? "?"}`);
    }
    if (doc.status === "failed") {
      return h("span", { class: "doc-meta tone-text-danger", title: doc.error_message || null }, "lỗi index", admin ? [" · ", action("thử lại")] : null);
    }
    if (doc.status === "uploaded") {
      // Quản trị viên tự lập được; thành viên chỉ chờ (backend chỉ cho admin gọi /documents/index).
      return admin ? h("span", { class: "doc-meta tone-text-warn" }, "chưa lập chỉ mục · ", action("lập ngay"))
        : h("span", { class: "doc-meta tone-text-warn" }, "chờ lập chỉ mục");
    }
    if (doc.status === "deleting") return h("span", { class: "doc-meta" }, "đang xóa…");
    return h("span", { class: "doc-meta tone-text-warn" }, "đang xử lý…");
  }

  /* Thẻ tài liệu → {node, box, sig}; trạng thái chọn (checked / .is-selected) do syncDocCards đặt. */
  function docCard(doc) {
    const id = doc.document_id;
    const name = doc.filename || "?";
    const box = h("input", {
      type: "checkbox", class: "check-15", disabled: doc.status !== "indexed",
      "aria-label": `Dùng ${name} cho hỏi đáp`, onChange: () => toggleDoc(id, box.checked),
    });
    const node = h("label", { class: "select-card doc-card", dataset: { id } },
      box, typeBadge(doc.filename, 28),
      h("span", { class: "doc-text" }, h("span", { class: "doc-name", title: name }, name), docMeta(doc)));
    return { node, box, sig: null };
  }

  function docSig(doc) {
    return JSON.stringify([doc.filename, doc.status, doc.chunks_count ?? null, doc.active_index_version ?? null,
      doc.error_message || null, S.reindexing.has(doc.document_id), Shell.isAdmin()]);
  }

  function syncDocCards() {
    const d = V && V.drawer;
    if (!d) return;
    for (const [id, ref] of d.cards) {
      const on = S.selected.has(id);
      if (ref.box.checked !== on) ref.box.checked = on;
      ref.node.classList.toggle("is-selected", on);
    }
  }

  /* Dựng lại CHỈ thẻ nào đổi dữ liệu; thẻ không đổi giữ nguyên nút DOM, nên poll 4 giây hay chọn tài
     liệu không làm rơi focus bàn phím và không làm nhảy danh sách. */
  function renderDocsList() {
    const d = V && V.drawer;
    if (!d) return;
    if (!S.docsLoaded || !S.docs.length) {
      d.cards.clear();
      d.list.replaceChildren(...(!S.docsLoaded
        ? S.docsError
          ? [h("div", { class: "docs-note is-error" }, "Không tải được danh sách tài liệu. Mở lại bảng này để thử lại.")]
          : [0, 1, 2].map(() => h("div", { class: "select-card doc-skel" }, skeleton({ w: 28, h: 28, r: 8 }),
            h("span", { class: "doc-text" }, skeleton({ w: "70%", h: 12 }), skeleton({ w: "40%", h: 10 }))))
        : [h("div", { class: "docs-note" }, "Chưa có tài liệu nào. Tải tệp lên để bắt đầu hỏi đáp theo tài liệu.")]));
      return;
    }
    const focusedId = d.list.contains(document.activeElement) ? document.activeElement.closest(".doc-card")?.dataset.id : null;
    const seen = new Set();
    const nodes = S.docs.map((doc) => {
      const id = doc.document_id;
      seen.add(id);
      const sig = docSig(doc);
      let ref = d.cards.get(id);
      if (!ref || ref.sig !== sig) {
        ref = docCard(doc);
        ref.sig = sig;
        d.cards.set(id, ref);
      }
      return ref.node;
    });
    for (const id of [...d.cards.keys()]) if (!seen.has(id)) d.cards.delete(id);
    reconcile(d.list, nodes);
    syncDocCards();
    // Thẻ đang giữ focus vừa được dựng lại (trạng thái đổi) → trả focus về ô chọn của thẻ mới.
    if (focusedId && !d.list.contains(document.activeElement)) {
      const again = d.cards.get(focusedId);
      const target = again && (again.box.disabled ? again.node.querySelector(".doc-retry:not(:disabled)") : again.box);
      if (target) target.focus({ preventScroll: true });
    }
  }

  const UPLOAD_LABEL = {
    queued: "Đang chờ", uploading: "Đang tải lên", conflict: "Chờ bạn chọn", indexing: "Đang lập chỉ mục", done: "Xong",
    error: "Lỗi", cancelled: "Đã hủy", uploaded: "Chờ quản trị viên", background: "Đang lập chỉ mục",
  };

  /* Cập nhật tại chỗ (không dựng lại, không gắn lại) để thanh 4px trượt mượt và hiệu ứng xuất hiện
     của dòng chỉ chạy một lần, thay vì chạy lại từ đầu mỗi lần poll. */
  function renderUploads() {
    const d = V && V.drawer;
    if (!d) return;
    const rows = d.rows;
    const keep = new Set(S.uploads.map((item) => item.id));
    for (const id of [...rows.keys()]) if (!keep.has(id)) rows.delete(id);
    const order = [];
    for (const item of S.uploads) {
      let ref = rows.get(item.id);
      if (!ref) {
        const name = h("span", { class: "upload-name", title: item.name }, item.name);
        const state = h("span", { class: "upload-state" });
        const fill = h("div", { class: "fill" });
        const stage = h("div", { class: "upload-stage" });
        const dismiss = h("button", {
          type: "button", class: "icon-btn icon-btn-24 upload-x", title: "Ẩn dòng này", "aria-label": `Ẩn dòng tải lên ${item.name}`,
          onClick: () => { S.uploads = S.uploads.filter((x) => x !== item); renderUploads(); },
        }, icon("x", { size: 12 }));
        const node = h("div", { class: "upload-row" }, h("div", { class: "upload-top" }, typeBadge(item.name, 22), name, state, dismiss),
          h("div", { class: "progress progress-4" }, fill), stage);
        ref = { node, state, fill, stage, dismiss };
        rows.set(item.id, ref);
      }
      const tone = item.status === "done" ? "is-done" : item.status === "error" ? "is-error"
        : ["uploaded", "background", "cancelled", "conflict"].includes(item.status) ? "is-warn" : null;
      ref.node.className = ["upload-row", tone].filter(Boolean).join(" ");
      ref.state.textContent = UPLOAD_LABEL[item.status] || item.status;
      ref.fill.style.width = `${Math.max(0, Math.min(100, Number(item.percent) || 0))}%`;
      ref.stage.textContent = item.stage || "";
      ref.dismiss.hidden = !item.finished;
      order.push(ref.node);
    }
    reconcile(d.uploads, order);
    d.uploads.hidden = !S.uploads.length;
  }

  function onUploadUpdate(item) {
    if (item.finished) {
      // Uploads đã tự THÊM tài liệu vừa xong vào lac.docsel. Ở đây chỉ đọc lại: ghi nguyên tập
      // S.selected xuống sẽ xóa mất lựa chọn mà màn hình Tài liệu vừa đặt, khi lượt tải lên kết
      // thúc lúc người dùng đã rời màn chat.
      if ((item.status === "done" || item.status === "background") && item.documentId) {
        S.selected = new Set(Uploads.readSelection());
        syncDocCards();
      }
      loadDocuments();
    }
    renderUploads();
    syncDocsUi();
  }

  function startUploads(files) {
    const list = Array.from(files || []);
    if (!list.length) return;
    // Không gắn ctx.signal: tải lên chạy tiếp khi rời màn hình, xong thì toast báo (Uploads tự lo).
    const run = Uploads.start(list, { onUpdate: onUploadUpdate });
    S.uploads.push(...run.items);
    renderUploads();
  }

  function buildDrawer() {
    const fileInput = h("input", {
      type: "file", multiple: true, accept: Uploads.accept, hidden: true, tabindex: "-1", "aria-hidden": "true",
      onChange: (event) => { startUploads(event.target.files); event.target.value = ""; },
    });
    const zone = h("div", { class: "dropzone", role: "button", tabindex: "0", "aria-label": "Tải tệp lên: thả tệp vào đây hoặc bấm để chọn" },
      icon("upload", { size: 20, sw: 1.9 }),
      h("span", null, h("strong", null, "Thả tệp"), " hoặc bấm để chọn"),
      h("span", { class: "hint" }, "PDF, DOCX, TXT, MD · nhiều tệp · tối đa 50 MB"));
    zone.addEventListener("click", () => fileInput.click());
    zone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileInput.click(); }
    });
    for (const type of ["dragenter", "dragover"]) {
      zone.addEventListener(type, (event) => { event.preventDefault(); zone.classList.add("is-drag"); });
    }
    zone.addEventListener("dragleave", (event) => { if (!zone.contains(event.relatedTarget)) zone.classList.remove("is-drag"); });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("is-drag");
      startUploads(event.dataTransfer && event.dataTransfer.files);
    });
    const count = h("span", { class: "section-label" }, "Đã lập chỉ mục · 0");
    const all = h("input", {
      type: "checkbox", "aria-label": "Chọn tất cả tài liệu đã lập chỉ mục",
      onChange: (event) => {
        for (const doc of indexedDocs()) {
          if (event.target.checked) S.selected.add(doc.document_id);
          else S.selected.delete(doc.document_id);
        }
        saveSelection();
        syncDocCards();
        syncDocsUi();
      },
    });
    const uploads = h("div", { class: "upload-list", hidden: true });
    const list = h("div", { class: "docs-list" });
    const closeBtn = h("button", {
      type: "button", class: "icon-btn icon-btn-30", title: "Đóng", "aria-label": "Đóng phạm vi hỏi đáp",
      onClick: () => setDocsOpen(false, { restoreFocus: true }),
    }, icon("x", { size: 15 }));
    const aside = h("aside", { class: "drawer chat-drawer", id: "chat-docs", "aria-label": "Phạm vi hỏi đáp" },
      h("div", { class: "drawer-head" },
        h("strong", { class: "drawer-title" }, "Phạm vi hỏi đáp"),
        h("a", { class: "drawer-link", href: "#/documents" }, "Thư viện →"),
        closeBtn),
      h("div", { class: "drawer-body" },
        zone, fileInput, uploads,
        h("div", { class: "docs-head" }, count, h("label", { class: "docs-all" }, all, "Tất cả")),
        list));
    const backdrop = h("div", { class: "drawer-backdrop", onClick: () => setDocsOpen(false, { restoreFocus: true }) });
    return { aside, backdrop, closeBtn, count, all, uploads, list, rows: new Map(), cards: new Map() };
  }

  function renderDrawer() {
    if (!V) return;
    if (S.docsOpen && !V.drawer) {
      V.drawer = buildDrawer();
      V.root.append(V.drawer.backdrop, V.drawer.aside);
      renderDocsList();
      renderUploads();
    } else if (!S.docsOpen && V.drawer) {
      V.drawer.aside.remove();
      V.drawer.backdrop.remove();
      V.drawer = null;
    }
  }

  /* restoreFocus (nút X, lớp nền, Esc): đưa focus về nút đã mở drawer. Đóng vì lý do khác mà focus
     đang nằm trong drawer cũng vậy — drawer bị tháo khỏi trang thì focus không được rơi về <body>. */
  function setDocsOpen(open, { restoreFocus = false } = {}) {
    const next = Boolean(open);
    const changed = next !== S.docsOpen;
    const focusInside = Boolean(V && V.drawer && V.drawer.aside.contains(document.activeElement));
    S.docsOpen = next;
    renderDrawer();
    syncDocsUi();
    syncDrawerModal();
    // Trên màn hẹp drawer phủ kín nội dung: đưa focus vào trong, nền đã inert nên Tab không lọt ra sau.
    if (next && changed && MOBILE.matches && V && V.drawer) V.drawer.closeBtn.focus({ preventScroll: true });
    if (!next && changed && (restoreFocus || focusInside)) focusDocsOpener();
    // Mỗi lần mở đều tải lại danh sách: trạng thái lập chỉ mục có thể đã đổi ở màn hình khác.
    if (next && changed) loadDocuments();
  }

  /* Drawer là lớp phủ (≤960px) → phần còn lại của màn hình không được Tab tới; rộng ra thì trả lại
     ngay, kể cả khi drawer vẫn mở (shell làm y hệt cho sidebar di động). */
  function syncDrawerModal() {
    if (!V) return;
    V.col.inert = Boolean(S.docsOpen && V.drawer && MOBILE.matches);
  }

  function focusDocsOpener() {
    if (!V) return;
    const target = [V.docsBtn, V.docsChip].find((node) => node.isConnected && !node.hidden && node.getClientRects().length > 0);
    if (target) target.focus({ preventScroll: true });
  }

  /* ══════════════════════════════════════════════════════════════
     VÒNG ĐỜI VIEW
     ══════════════════════════════════════════════════════════════ */
  function mount(ctx) {
    Shell.setSidebarPanel(ensurePanel());   // đồng bộ, trước mọi await (hợp đồng của router)
    S.selected = new Set(Uploads.readSelection());
    S.mode = prefs.mode === "rag" ? "rag" : "general";
    S.toolsOn = Boolean(prefs.toolsOn);

    const composer = buildComposer();
    const empty = buildEmpty();
    const modeChip = h("span", { class: "chip-info" });
    const modeRow = h("div", { class: "mode-chip-row" }, modeChip);
    const msgs = h("div", { class: "msgs" });
    const transcript = h("div", { class: "transcript", hidden: true }, modeRow, msgs);
    const scroll = h("div", { class: "chat-scroll", tabindex: "-1" }, empty, transcript, h("div", { class: "chat-spacer" }));
    const col = h("div", { class: "chat-col" }, scroll, composer.wrap);
    const badge = h("span", { class: "badge-count", hidden: true }, "0");
    const docsBtn = h("button", {
      type: "button", class: "btn btn-36 btn-toggle px-12", "aria-expanded": "false",
      title: "Chọn tài liệu cho hỏi đáp", onClick: () => setDocsOpen(!S.docsOpen),
    }, icon("book-pages", { size: 16, sw: 1.9 }), "Tài liệu", badge);

    ctx.root.append(col);
    V = { ctx, root: ctx.root, col, scroll, empty, transcript, modeRow, modeChip, msgs, badge, docsBtn, drawer: null, cite: null, ...composer };
    ctx.setActions([docsBtn]);

    // Trích dẫn [n] và nút "Sao chép" của khối mã: ủy quyền ở transcript vì câu trả lời được vẽ lại liên tục khi stream.
    msgs.addEventListener("click", (event) => {
      const cite = event.target.closest(".cite[data-cite]");
      if (cite) {
        event.preventDefault();   // huy hiệu trích dẫn không bao giờ điều hướng, kể cả khi nằm trong <a>
        const sources = msgSources.get(cite.closest(".msg-assistant")) || [];
        const n = Number(cite.dataset.cite);
        if (sources[n - 1]) openCite(sources[n - 1], n, cite);   // [Source 99] không có nguồn: bỏ qua
        return;
      }
      const copy = event.target.closest(".codeblock-copy");
      if (copy) copyText(copy.closest(".codeblock").querySelector("code").textContent);
    });
    scroll.addEventListener("scroll", syncJump, { passive: true });
    ctx.on(document, "keydown", (event) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (V && V.cite) { event.preventDefault(); closeCite(); return; }
      if (S.docsOpen && MOBILE.matches) { event.preventDefault(); setDocsOpen(false, { restoreFocus: true }); }
    });
    // Tệp thả trượt ra ngoài vùng thả: trình duyệt sẽ mở tệp thay cho ứng dụng (mất luôn câu trả lời
    // đang chạy) → chặn. Vùng thả của drawer đã tự preventDefault nên không bị ảnh hưởng.
    const hasFiles = (event) => Boolean(event.dataTransfer) && [...(event.dataTransfer.types || [])].includes("Files");
    ctx.on(window, "dragover", (event) => {
      if (event.defaultPrevented || !hasFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "none";
    });
    ctx.on(window, "drop", (event) => { if (!event.defaultPrevented && hasFiles(event)) event.preventDefault(); });
    // Màn Tài liệu (hoặc Chat) ở THẺ KHÁC đổi lac.docsel → phạm vi hỏi đáp ở đây theo ngay.
    // Không đồng bộ thì thẻ này gửi document_ids cũ cho /rag/chat. documents.js:1464 làm y hệt.
    ctx.on(window, "storage", (event) => {
      if (event.key !== null && event.key !== "lac.docsel") return;
      S.selected = new Set(Uploads.readSelection());
      syncDocCards();
      syncDocsUi();
    });
    // Mỗi 4 giây khi drawer mở và còn tài liệu chưa xong thì tải lại trạng thái — trừ khi thẻ trình
    // duyệt đang ẩn hoặc lần tải trước chưa trả lời.
    ctx.every(() => {
      if (!S.docsOpen || document.hidden || S.docsBusy) return;
      if (S.docs.some((doc) => doc.status === "uploaded" || doc.status === "processing")) loadDocuments();
    }, 4000);

    // Drawer là lớp phủ trên màn hẹp: quay lại chat thì không tự bật lại che nội dung.
    if (MOBILE.matches) S.docsOpen = false;
    syncChips();
    syncSend();
    syncDocsUi();
    renderDrawer();
    syncDrawerModal();
    ctx.on(MOBILE, "change", syncDrawerModal);   // xoay ngang / kéo rộng cửa sổ: trả lại nền cho bàn phím
    const id = ctx.params[0] || null;
    if (id) openConversation(id, { force: true });
    else {
      S.cur = { id: null, title: null, seq: S.cur.seq + 1 };
      showEmpty();
    }
    setHeaderTitle();
    renderConvList();
    loadConversations({ quiet: S.convsLoaded });
    loadDocuments();
    if (!S.model) loadModels();
  }

  function update(ctx, { same = false } = {}) {
    if (!V || V.ctx !== ctx) return false;
    const id = ctx.params[0] || null;
    if (id) {
      if (id !== S.cur.id) openConversation(id);
      // Hội thoại đang mở mà lần tải trước hỏng (500, mất mạng, hết phiên): bấm lại = tải lại.
      // Đang trả lời thì không: bấm lại hội thoại đang mở không bao giờ cắt câu trả lời.
      else if (S.cur.failed && !S.gen && !S.cur.loading) openConversation(id, { force: true });
      else if (same && MOBILE.matches) setDocsOpen(false);   // bấm lại hội thoại đang mở; id do view tự ghi (meta) → không đụng gì
      return true;
    }
    // #/chat: bấm "+" (cùng hash) hoặc quay lại từ một hội thoại → cuộc mới; URL do chính view ghi → giữ nguyên.
    if (same || S.cur.id !== null) newChat();
    return true;
  }

  function unmount() {
    abortTurn();
    closeCite({ restore: false });
    V = null;
  }

  Router.register("chat", { admin: false, mount, update, unmount });
})();
