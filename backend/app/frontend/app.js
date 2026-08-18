/* ══════════════════════════════════════════════════════════════════
   Local AI Core — web app
   Vanilla JS, không build step. Cấu trúc:
     utils → state/prefs → theme → markdown → toast/dialog → messages
     → streaming → chat flow → conversations → documents → settings
     → health → composer/shell → init
   Mọi nội dung động đi qua textContent hoặc esc() trước khi vào DOM.
   ══════════════════════════════════════════════════════════════════ */
"use strict";

/* ── Utils ─────────────────────────────────────────────────────── */
const $ = (id) => document.getElementById(id);

const ERROR_HINTS = {
  OLLAMA_UNAVAILABLE: "Không kết nối được Ollama. Hãy kiểm tra Ollama đang chạy rồi thử lại.",
  MODEL_NOT_LOADED: "Mô hình chưa được nạp. Kiểm tra Ollama và cấu hình models.yaml.",
  MODEL_TIMEOUT: "Mô hình trả lời quá chậm. Hãy rút ngắn câu hỏi hoặc thử lại.",
  QDRANT_UNAVAILABLE: "Chỉ mục tìm kiếm (Qdrant) không phản hồi. Hãy kiểm tra Docker.",
  INSUFFICIENT_CONTEXT: "Chưa tìm được ngữ cảnh phù hợp trong tài liệu đã chọn.",
  CONVERSATION_NOT_FOUND: "Cuộc trò chuyện không còn tồn tại trên máy chủ.",
  DOCUMENT_TOO_LARGE: "Tệp vượt quá giới hạn 50 MB.",
  UNSUPPORTED_FILE_TYPE: "Chỉ hỗ trợ PDF, DOCX, TXT và Markdown.",
  DOCUMENT_ALREADY_INDEXING: "Tài liệu đang được lập chỉ mục. Vui lòng chờ hoàn tất.",
  API_KEY_REQUIRED: "Máy chủ này yêu cầu khóa truy cập. Mở Cài đặt → Bảo mật để nhập khóa.",
  API_KEY_INVALID: "Khóa truy cập không đúng. Kiểm tra lại trong Cài đặt → Bảo mật.",
};

/* Khóa truy cập tùy chọn: chỉ những máy chủ có cấu hình khóa mới cần. */
const getApiKey = () => localStorage.getItem("lac.apikey") || "";
const setApiKey = (value) => {
  const key = value.trim();
  if (key) localStorage.setItem("lac.apikey", key);
  else localStorage.removeItem("lac.apikey");
};

/* Gắn khóa vào mọi request; header rỗng thì bỏ hẳn để không đổi hành vi khi
   máy chủ không bật xác thực. */
function withApiKey(headers = {}) {
  const key = getApiKey();
  return key ? { ...headers, "X-API-Key": key } : headers;
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { ...options, headers: withApiKey(options.headers) });
  } catch {
    throw new Error("Không kết nối được máy chủ. Kiểm tra backend đang chạy.");
  }
  const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(ERROR_HINTS[data.error_code] || data.message || "Yêu cầu thất bại.");
    error.code = data.error_code;
    error.status = response.status;
    throw error;
  }
  return data;
}

function esc(text) {
  return String(text)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function iconBtn(icon, label, extraClass = "") {
  const button = el("button", `btn icon ghost ${extraClass}`.trim());
  button.type = "button";
  button.setAttribute("aria-label", label);
  button.title = label;
  button.innerHTML = `<svg width="15" height="15"><use href="#i-${icon}"/></svg>`;
  return button;
}

function debounce(fn, ms) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

async function copyText(text, doneMessage = "Đã sao chép.") {
  try {
    await navigator.clipboard.writeText(text);
    toast(doneMessage, "ok");
  } catch {
    toast("Không sao chép được (trình duyệt chặn clipboard).", "error");
  }
}

/* ── Prefs & state ─────────────────────────────────────────────── */
function readStore(key, fallback) {
  try { return { ...fallback, ...JSON.parse(localStorage.getItem(key) || "{}") }; }
  catch { return { ...fallback }; }
}
const prefs = readStore("lac.prefs", { theme: "system", enterToSend: true, memoryDefault: false });
const savePrefs = () => localStorage.setItem("lac.prefs", JSON.stringify(prefs));

const titles = readStore("lac.titles", {});
const saveTitles = () => localStorage.setItem("lac.titles", JSON.stringify(titles));

const state = {
  conversationId: null,
  mode: "general",           // general | rag
  memoryOn: prefs.memoryDefault,
  generating: false,
  abort: null,
  conversations: [],
  conversationsError: false,
  documents: [],
  selectedDocs: new Set(JSON.parse(localStorage.getItem("lac.docsel") || "[]")),
  lastPrompt: null,
};
const saveDocSelection = () =>
  localStorage.setItem("lac.docsel", JSON.stringify([...state.selectedDocs]));

/* ── Theme ─────────────────────────────────────────────────────── */
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
function applyTheme() {
  const resolved = prefs.theme === "system" ? (systemDark.matches ? "dark" : "light") : prefs.theme;
  document.documentElement.dataset.theme = resolved;
}
systemDark.addEventListener("change", applyTheme);

/* ── Markdown (escape-first, an toàn XSS) ──────────────────────── */
function inlineMd(text) {
  let html = esc(text);
  html = html.replace(/`([^`]+)`/g, (_, code) => `<code>${code}</code>`);
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (_, label, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`);
  return html;
}

function renderMarkdown(text) {
  const lines = String(text).split("\n");
  const out = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const fence = line.match(/^```(\w*)\s*$/);
    if (fence) {
      const body = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index])) { body.push(lines[index]); index += 1; }
      index += 1; // bỏ dòng ``` đóng (hoặc EOF khi đang stream)
      const lang = fence[1] || "text";
      out.push(
        `<div class="codeblock"><div class="codeblock-head"><span class="codeblock-lang">${esc(lang)}</span>` +
        `<button type="button" class="btn ghost codeblock-copy">Sao chép</button></div>` +
        `<pre><code>${esc(body.join("\n"))}</code></pre></div>`
      );
      continue;
    }
    if (/^\s*$/.test(line)) { index += 1; continue; }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      out.push(`<h${heading[1].length + 0}>${inlineMd(heading[2])}</h${heading[1].length}>`);
      index += 1; continue;
    }
    if (/^(?:-{3,}|\*{3,})\s*$/.test(line)) { out.push("<hr>"); index += 1; continue; }
    if (/^\s*>\s?/.test(line)) {
      const body = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        body.push(lines[index].replace(/^\s*>\s?/, "")); index += 1;
      }
      out.push(`<blockquote>${body.map(inlineMd).join("<br>")}</blockquote>`);
      continue;
    }
    if (/^\s*[-*+]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*+]\s+/, "")); index += 1;
      }
      out.push(`<ul>${items.map((item) => `<li>${inlineMd(item)}</li>`).join("")}</ul>`);
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+[.)]\s+/, "")); index += 1;
      }
      out.push(`<ol>${items.map((item) => `<li>${inlineMd(item)}</li>`).join("")}</ol>`);
      continue;
    }
    const paragraph = [];
    while (
      index < lines.length && !/^\s*$/.test(lines[index]) &&
      !/^```/.test(lines[index]) && !/^(#{1,4})\s/.test(lines[index]) &&
      !/^\s*[-*+]\s+/.test(lines[index]) && !/^\s*\d+[.)]\s+/.test(lines[index]) &&
      !/^\s*>\s?/.test(lines[index]) && !/^(?:-{3,}|\*{3,})\s*$/.test(lines[index])
    ) { paragraph.push(lines[index]); index += 1; }
    out.push(`<p>${paragraph.map(inlineMd).join("<br>")}</p>`);
  }
  return out.join("");
}

function bindCodeCopy(root) {
  for (const button of root.querySelectorAll(".codeblock-copy")) {
    button.onclick = () => copyText(button.closest(".codeblock").querySelector("code").textContent);
  }
}

/* ── Toast & dialogs ───────────────────────────────────────────── */
function toast(message, kind = "") {
  const root = $("toast-root");
  const node = el("div", `toast ${kind}`.trim(), message);
  root.append(node);
  // Popover đưa toast lên top layer để hiện trên cả dialog đang mở.
  if (root.showPopover) {
    try { root.hidePopover(); } catch { /* chưa mở */ }
    try { root.showPopover(); } catch { /* trình duyệt cũ */ }
  }
  setTimeout(() => { node.style.opacity = "0"; node.style.transition = "opacity .3s"; }, 3200);
  setTimeout(() => {
    node.remove();
    if (root.showPopover && !root.childElementCount) {
      try { root.hidePopover(); } catch { /* đã đóng */ }
    }
  }, 3600);
}

function announce(text) { $("sr-status").textContent = text; }

function confirmAction({ title, body, okText = "Xóa" }) {
  return new Promise((resolve) => {
    const dialog = $("confirm-dialog");
    $("confirm-title").textContent = title;
    $("confirm-body").textContent = body;
    $("confirm-ok").textContent = okText;
    const done = (value) => { dialog.close(); resolve(value); };
    $("confirm-ok").onclick = () => done(true);
    $("confirm-cancel").onclick = () => done(false);
    dialog.oncancel = () => resolve(false);
    dialog.showModal();
  });
}

function promptRename(current) {
  return new Promise((resolve) => {
    const dialog = $("rename-dialog");
    const input = $("rename-input");
    input.value = current;
    const done = (value) => { dialog.close(); resolve(value); };
    $("rename-ok").onclick = () => done(input.value.trim() || null);
    $("rename-cancel").onclick = () => done(null);
    input.onkeydown = (event) => { if (event.key === "Enter") { event.preventDefault(); done(input.value.trim() || null); } };
    dialog.oncancel = () => resolve(null);
    dialog.showModal();
    setTimeout(() => { input.focus(); input.select(); }, 30);
  });
}

/* ── Scroll manager ────────────────────────────────────────────── */
const chatScroll = () => $("chat-scroll");
const nearBottom = () => {
  const box = chatScroll();
  return box.scrollHeight - box.scrollTop - box.clientHeight < 130;
};
function scrollToBottom(force = false) {
  if (force || nearBottom()) chatScroll().scrollTop = chatScroll().scrollHeight;
  syncJumpButton();
}
function syncJumpButton() { $("jump-latest").hidden = nearBottom(); }

/* ── Messages ──────────────────────────────────────────────────── */
function showEmptyState(show) { $("empty-state").hidden = !show; }

function clearMessages() {
  $("messages").replaceChildren();
  showEmptyState(true);
}

function addUserMessage(text) {
  const wrap = el("div", "msg user");
  const body = el("div", "msg-body");
  const content = el("div", "msg-content", text);
  const meta = el("div", "msg-meta");
  const actions = el("div", "msg-actions");
  const copyBtn = iconBtn("copy", "Sao chép tin nhắn");
  copyBtn.onclick = () => copyText(text);
  const editBtn = iconBtn("edit", "Sửa và gửi lại");
  editBtn.onclick = () => {
    const input = $("composer-input");
    input.value = text;
    autoSizeComposer();
    syncSendState();
    input.focus();
  };
  actions.append(copyBtn, editBtn);
  meta.append(actions);
  body.append(content, meta);
  wrap.append(body);
  $("messages").append(wrap);
  showEmptyState(false);
  scrollToBottom(true);
}

function addAssistantMessage() {
  const wrap = el("div", "msg assistant");
  wrap.innerHTML =
    `<div class="msg-avatar"><svg width="15" height="15"><use href="#i-spark"/></svg></div>` +
    `<div class="msg-body"><div class="msg-content"><span class="typing" role="img" aria-label="Đang xử lý"><i></i><i></i><i></i></span></div>` +
    `<div class="msg-meta" hidden></div></div>`;
  const content = wrap.querySelector(".msg-content");
  const metaRow = wrap.querySelector(".msg-meta");
  $("messages").append(wrap);
  showEmptyState(false);
  scrollToBottom(true);

  let raw = "";
  let renderQueued = false;
  const paint = () => {
    renderQueued = false;
    content.innerHTML = renderMarkdown(raw);
    bindCodeCopy(content);
    scrollToBottom();
  };
  const handle = {
    node: wrap,
    get text() { return raw; },
    start() { wrap.classList.add("streaming"); announce("Đang trả lời…"); },
    append(token) {
      raw += token;
      if (!renderQueued) { renderQueued = true; requestAnimationFrame(paint); }
    },
    setSources(sources) {
      if (!sources?.length) return;
      const details = el("details", "sources");
      details.innerHTML =
        `<summary><svg width="14" height="14"><use href="#i-book"/></svg>` +
        `${sources.length} nguồn trích dẫn` +
        `<svg class="chev" width="14" height="14"><use href="#i-chev"/></svg></summary>`;
      sources.forEach((source, order) => {
        const item = el("div", "source-item");
        const head = el("div", "source-head");
        head.append(el("span", "n", String(order + 1)), el("span", "source-file", source.filename || "?"));
        const pageStart = source.page_start ?? source.page;
        if (pageStart != null) {
          const pageEnd = source.page_end;
          head.append(el("span", "source-page",
            pageEnd && pageEnd !== pageStart ? `trang ${pageStart}–${pageEnd}` : `trang ${pageStart}`));
        }
        if (source.heading_path) head.append(el("span", "source-page", source.heading_path));
        item.append(head);
        const excerpt = source.excerpt || source.content;
        if (excerpt) item.append(el("div", "source-excerpt", String(excerpt).slice(0, 400)));
        details.append(item);
      });
      wrap.querySelector(".msg-body").insertBefore(details, metaRow);
    },
    finish({ model, seconds, stopped = false, retry = null } = {}) {
      wrap.classList.remove("streaming");
      if (!raw) content.innerHTML = "";
      paint();
      metaRow.hidden = false;
      const parts = [];
      if (model) parts.push(model);
      if (seconds != null) parts.push(`${seconds}s`);
      if (stopped) parts.push("đã dừng");
      if (parts.length) metaRow.append(el("span", "", parts.join(" · ")));
      if (raw) announce(`Trợ lý: ${content.textContent}`);
      const actions = el("div", "msg-actions");
      const copyBtn = iconBtn("copy", "Sao chép câu trả lời");
      copyBtn.onclick = () => copyText(raw);
      actions.append(copyBtn);
      if (retry) {
        const retryBtn = iconBtn("retry", "Tạo câu trả lời khác (thêm lượt mới)");
        retryBtn.onclick = retry;
        actions.append(retryBtn);
      }
      metaRow.append(actions);
      scrollToBottom();
    },
    fail(message, retry) {
      wrap.classList.remove("streaming");
      wrap.classList.add("error-msg");
      if (raw) { paint(); content.append(el("p", "", "")); }
      const errorLine = el("p", "", `⚠ ${message}`);
      raw ? content.append(errorLine) : (content.replaceChildren(errorLine));
      announce(`Lỗi: ${message}`);
      metaRow.hidden = false;
      if (retry) {
        const retryBtn = el("button", "btn ghost");
        retryBtn.type = "button";
        retryBtn.innerHTML = `<svg width="14" height="14"><use href="#i-retry"/></svg> Thử lại`;
        retryBtn.onclick = retry;
        metaRow.append(retryBtn);
      }
      scrollToBottom();
    },
  };
  return handle;
}

/* Render một hội thoại đã lưu */
function renderHistory(messages) {
  clearMessages();
  if (!messages.length) return;
  showEmptyState(false);
  for (const message of messages) {
    if (message.role === "user") {
      addUserMessage(message.content);
    } else {
      const handle = addAssistantMessage();
      handle.append(message.content);
      // Nguồn được lưu cùng câu trả lời, nên hội thoại RAG mở lại vẫn đủ dẫn chứng.
      handle.setSources(message.sources || []);
      handle.finish({ model: message.model_used || null });
    }
  }
  requestAnimationFrame(() => scrollToBottom(true));
}

/* ── SSE streaming ─────────────────────────────────────────────── */
async function streamChat(path, payload, { onMeta, onToken }, signal) {
  const response = await fetch(path, {
    method: "POST",
    headers: withApiKey({ "Content-Type": "application/json" }),
    body: JSON.stringify({ ...payload, stream: true }),
    signal,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(ERROR_HINTS[data.error_code] || data.message || "Mô hình không phản hồi.");
    error.code = data.error_code;
    throw error;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop();
    for (const rawEvent of events) {
      const type = rawEvent.match(/^event: (.+)$/m)?.[1];
      const raw = rawEvent.match(/^data: (.+)$/m)?.[1];
      if (!raw) continue;
      const data = JSON.parse(raw);
      if (type === "meta") onMeta?.(data);
      else if (type === "token") onToken?.(data.content);
      else if (type === "error") throw new Error(ERROR_HINTS[data.error_code] || data.message || "Lỗi khi sinh phản hồi.");
    }
  }
}

/* ── Chat flow ─────────────────────────────────────────────────── */
function setGenerating(on) {
  state.generating = on;
  $("composer-form").classList.toggle("generating", on);
  $("stop-btn").hidden = !on;
  $("send-btn").hidden = on;
  $("composer-input").disabled = false;
  for (const radio of document.querySelectorAll('#mode-seg input')) radio.disabled = on;
  syncSendState();
}

async function sendPrompt(prompt) {
  if (state.generating) return;
  if (state.mode === "rag" && !state.selectedDocs.size) {
    toast("Hãy chọn ít nhất một tài liệu đã lập chỉ mục trước.", "error");
    openDocs(true);
    return;
  }
  state.lastPrompt = prompt;
  addUserMessage(prompt);

  const handle = addAssistantMessage();
  const controller = new AbortController();
  state.abort = controller;
  setGenerating(true);
  const started = performance.now();
  let model = null;
  let firstToken = false;
  const isNewConversation = !state.conversationId;

  const payload =
    state.mode === "general"
      ? { message: prompt, conversation_id: state.conversationId, use_memory: state.memoryOn }
      : { message: prompt, document_ids: [...state.selectedDocs], conversation_id: state.conversationId };

  const retry = () => sendPrompt(prompt);
  try {
    await streamChat(state.mode === "general" ? "/chat" : "/rag/chat", payload, {
      onMeta: (meta) => {
        model = meta.model_used || null;
        if (meta.conversation_id) state.conversationId = meta.conversation_id;
        if (state.mode === "rag") handle.setSources(meta.sources || []);
      },
      onToken: (token) => {
        if (!firstToken) { firstToken = true; handle.start(); }
        handle.append(token);
      },
    }, controller.signal);
    handle.finish({
      model,
      seconds: ((performance.now() - started) / 1000).toFixed(1),
      retry,
    });
    if (isNewConversation && state.conversationId) {
      // Backend tự đặt title từ tin nhắn đầu; giữ bản localStorage làm
      // hiển thị tức thời cho tới khi danh sách tải lại.
      titles[state.conversationId] = prompt.slice(0, 60);
      saveTitles();
      setTopbarTitle();
      loadConversations();
    } else {
      loadConversations(true);
    }
  } catch (error) {
    if (error.name === "AbortError") {
      // Lượt bị dừng: backend giữ phần đã stream; chỉ khi CHƯA có token nào
      // thì conversation mới tạo bị xóa phía server — bỏ ID để tránh 404.
      if (isNewConversation && !handle.text) state.conversationId = null;
      handle.finish({ model, stopped: true });
      loadConversations(true);
    } else if (error.code === "CONVERSATION_NOT_FOUND") {
      state.conversationId = null;
      handle.fail(`${error.message} Tin nhắn tiếp theo sẽ tạo cuộc trò chuyện mới.`, retry);
      loadConversations();
    } else {
      handle.fail(error.message, retry);
    }
  } finally {
    state.abort = null;
    setGenerating(false);
  }
}

/* ── Conversations ─────────────────────────────────────────────── */
function titleFor(conversation) {
  // Server-side title là nguồn chính; localStorage chỉ còn là fallback cho
  // hội thoại cũ tạo trước khi backend có cột title.
  return conversation.title || titles[conversation.id] ||
    `Trò chuyện ${new Date(conversation.created_at).toLocaleDateString("vi-VN")}`;
}

function groupLabel(dateText) {
  const date = new Date(dateText);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Math.floor((today - new Date(date.getFullYear(), date.getMonth(), date.getDate())) / 86400000);
  if (days <= 0) return "Hôm nay";
  if (days === 1) return "Hôm qua";
  if (days < 7) return "7 ngày qua";
  if (days < 30) return "30 ngày qua";
  return "Cũ hơn";
}

function renderConversations() {
  const list = $("conv-list");
  list.replaceChildren();
  if (state.conversationsError) {
    const box = el("div", "conv-error", "Không tải được danh sách hội thoại.");
    const retryBtn = el("button", "btn ghost", "Thử lại");
    retryBtn.onclick = () => loadConversations();
    box.append(retryBtn);
    list.append(box);
    return;
  }
  const query = $("conv-search").value.trim().toLowerCase();
  const items = state.conversations.filter((conversation) =>
    !query || titleFor(conversation).toLowerCase().includes(query));
  if (!items.length) {
    list.append(el("div", "conv-empty",
      query ? "Không có hội thoại khớp từ khóa." : "Chưa có hội thoại nào. Bắt đầu cuộc trò chuyện đầu tiên!"));
    return;
  }
  let currentGroup = null;
  for (const conversation of items) {
    const label = groupLabel(conversation.updated_at);
    if (label !== currentGroup) { list.append(el("div", "conv-group", label)); currentGroup = label; }
    const item = el("div", "conv-item" + (conversation.id === state.conversationId ? " active" : ""));
    item.setAttribute("role", "button");
    item.tabIndex = 0;
    const title = el("span", "conv-item-title", titleFor(conversation));
    title.title = `${titleFor(conversation)} · ${conversation.message_count} tin nhắn`;
    const actions = el("span", "conv-item-actions");
    const renameBtn = iconBtn("edit", "Đổi tên hội thoại");
    renameBtn.onclick = async (event) => {
      event.stopPropagation();
      const name = await promptRename(titleFor(conversation));
      if (!name) return;
      try {
        await api(`/conversations/${conversation.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: name }),
        });
        conversation.title = name;
        delete titles[conversation.id];
        saveTitles();
      } catch (error) {
        toast(error.message, "error");
        return;
      }
      renderConversations();
      setTopbarTitle();
    };
    const deleteBtn = iconBtn("trash", "Xóa hội thoại");
    deleteBtn.onclick = async (event) => {
      event.stopPropagation();
      const yes = await confirmAction({
        title: "Xóa hội thoại?",
        body: `«${titleFor(conversation)}» và toàn bộ tin nhắn trong đó sẽ bị xóa vĩnh viễn khỏi máy chủ.`,
      });
      if (!yes) return;
      try {
        await api(`/conversations/${conversation.id}`, { method: "DELETE" });
        delete titles[conversation.id]; saveTitles();
        if (state.conversationId === conversation.id) newChat();
        toast("Đã xóa hội thoại.", "ok");
      } catch (error) {
        if (error.status !== 404) toast(error.message, "error");
      }
      loadConversations();
    };
    actions.append(renameBtn, deleteBtn);
    item.append(title, actions);
    const open = () => openConversation(conversation.id);
    item.onclick = open;
    item.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    };
    list.append(item);
  }
}

async function loadConversations(quiet = false) {
  if (!quiet && !state.conversations.length) {
    $("conv-list").replaceChildren(
      ...[64, 64, 64].map((height) => {
        const skeleton = el("div", "skeleton");
        skeleton.style.cssText = `height:38px;margin:6px 8px`;
        return skeleton;
      }));
  }
  try {
    state.conversations = await api("/conversations");
    state.conversationsError = false;
  } catch {
    state.conversationsError = true;
  }
  renderConversations();
}

async function openConversation(id) {
  // Bấm lại hội thoại đang mở là no-op: không được phép hủy stream đang chạy.
  if (state.conversationId === id) { closeDrawers(); return; }
  if (state.generating) state.abort?.abort();
  state.conversationId = id;
  setMode("general");
  setTopbarTitle();
  renderConversations();
  closeDrawers();
  $("messages").replaceChildren(
    ...[72, 48, 60].map((height) => {
      const skeleton = el("div", "skeleton");
      skeleton.style.cssText = `height:${height}px;margin:0 0 18px`;
      return skeleton;
    }));
  showEmptyState(false);
  try {
    // encodeURIComponent là no-op với UUID; chặn ký tự điều hướng từ deep-link.
    const detail = await api(`/conversations/${encodeURIComponent(id)}`);
    if (state.conversationId !== id) return; // đã chuyển đi nơi khác
    renderHistory(detail.messages);
    if (!detail.title && !titles[id] && detail.messages.length) {
      // Hội thoại cũ chưa có title server-side: suy ra tên hiển thị cục bộ.
      const firstUser = detail.messages.find((message) => message.role === "user");
      if (firstUser) { titles[id] = firstUser.content.slice(0, 60); saveTitles(); renderConversations(); setTopbarTitle(); }
    }
  } catch (error) {
    if (state.conversationId !== id) return; // đã chuyển sang hội thoại khác
    clearMessages();
    toast(error.message, "error");
    if (error.status === 404) {
      state.conversationId = null;
      setTopbarTitle();
      loadConversations();
    }
  }
}

function newChat() {
  state.abort?.abort();
  state.conversationId = null;
  clearMessages();
  state.memoryOn = prefs.memoryDefault;
  syncMemoryChip();
  setTopbarTitle();
  renderConversations();
  closeDrawers();
  $("composer-input").focus();
}

function setTopbarTitle() {
  const conversation = state.conversations.find((item) => item.id === state.conversationId);
  $("topbar-title").textContent = state.conversationId
    ? (titles[state.conversationId] || (conversation ? titleFor(conversation) : "Hội thoại"))
    : "Cuộc trò chuyện mới";
}

/* ── Documents ─────────────────────────────────────────────────── */
function docsOpen() { return document.getElementById("app").classList.contains("docs-open"); }
function openDocs(open) {
  $("app").classList.toggle("docs-open", open);
  $("docs-panel").setAttribute("aria-hidden", String(!open));
  if (open) {
    loadDocuments();
    if (window.innerWidth <= 960) showBackdrop(true);
  } else if (!$("app").classList.contains("sidebar-open-mobile")) showBackdrop(false);
}

function renderDocuments() {
  const list = $("doc-list");
  list.replaceChildren();
  if (!state.documents.length) {
    list.append(el("div", "conv-empty", "Chưa có tài liệu nào. Tải tệp lên để bắt đầu hỏi đáp theo tài liệu."));
    syncDocsUi();
    return;
  }
  for (const doc of state.documents) {
    const row = el("div", "doc");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedDocs.has(doc.document_id);
    checkbox.disabled = doc.status !== "indexed";
    checkbox.setAttribute("aria-label", `Dùng ${doc.filename} cho hỏi đáp`);
    checkbox.onchange = () => {
      checkbox.checked ? state.selectedDocs.add(doc.document_id) : state.selectedDocs.delete(doc.document_id);
      saveDocSelection();
      syncDocsUi();
    };
    const main = el("div", "doc-main");
    main.append(el("div", "doc-name", doc.filename));
    const metaClass =
      doc.status === "indexed" ? "" : doc.status === "failed" ? " failed" : " processing";
    const metaText =
      doc.status === "indexed"
        ? `${doc.chunks_count} đoạn · ${doc.source_available ? "còn file gốc" : "không còn file gốc"}`
        : doc.status === "failed"
          ? `lỗi: ${doc.error_message || "index thất bại"}`
          : `đang xử lý (${doc.status})`;
    main.append(el("div", `doc-meta${metaClass}`, metaText));
    main.onclick = () => { if (!checkbox.disabled) { checkbox.checked = !checkbox.checked; checkbox.onchange(); } };
    const deleteBtn = iconBtn("trash", `Xóa tài liệu ${doc.filename}`);
    deleteBtn.onclick = async () => {
      const yes = await confirmAction({
        title: "Xóa tài liệu?",
        body: `«${doc.filename}» cùng toàn bộ chỉ mục của nó sẽ bị xóa. Không thể hoàn tác.`,
      });
      if (!yes) return;
      try {
        await api(`/documents/${doc.document_id}`, { method: "DELETE" });
        state.selectedDocs.delete(doc.document_id);
        saveDocSelection();
        toast("Đã xóa tài liệu.", "ok");
      } catch (error) { toast(error.message, "error"); }
      loadDocuments();
    };
    row.append(checkbox, main, deleteBtn);
    list.append(row);
  }
  syncDocsUi();
}

function syncDocsUi() {
  const indexed = state.documents.filter((doc) => doc.status === "indexed");
  // Chỉ prune ID đã biến mất hẳn; tài liệu đang re-index tạm thời không
  // "indexed" nhưng lựa chọn của người dùng phải được giữ.
  for (const id of [...state.selectedDocs]) {
    if (!state.documents.some((doc) => doc.document_id === id)) state.selectedDocs.delete(id);
  }
  saveDocSelection();
  const count = state.selectedDocs.size;
  const badge = $("docs-badge");
  badge.hidden = !count;
  badge.textContent = String(count);
  $("docs-chip-text").textContent = count ? `${count} tài liệu` : "Chọn tài liệu";
  const selectAll = $("select-all-docs");
  selectAll.checked = indexed.length > 0 && indexed.every((doc) => state.selectedDocs.has(doc.document_id));
  selectAll.indeterminate = count > 0 && !selectAll.checked;
  updateModeUi();
}

async function loadDocuments() {
  try {
    state.documents = await api("/documents");
  } catch {
    // Giữ nguyên state (đặc biệt là selectedDocs) khi backend tạm lỗi;
    // wipe ở đây sẽ xóa vĩnh viễn lựa chọn RAG đã lưu trong localStorage.
    if (!state.documents.length) {
      $("doc-list").replaceChildren(el("div", "conv-empty", "Không tải được danh sách tài liệu. Mở lại bảng này để thử lại."));
    }
    return;
  }
  renderDocuments();
}

/* Upload */
let selectedFile = null;
let uploading = false;
function chooseFile(file) {
  if (!file || uploading) return;
  selectedFile = file;
  $("upload-btn").disabled = false;
  showUploadStatus(`Đã chọn: ${file.name} · ${(file.size / 1048576).toFixed(2)} MB`, 0);
}
function showUploadStatus(text, percent) {
  $("upload-status").hidden = false;
  $("upload-status-text").textContent = text;
  $("upload-progress").style.width = `${Math.max(0, Math.min(100, percent))}%`;
}

function conflictDecision(upload, uploadName) {
  const options =
    upload.conflict === "same_name_same_hash"
      ? { body: `«${upload.filename}» đã tồn tại với nội dung giống hệt.`, actions: [["Dùng tài liệu hiện có", "use_existing"]] }
      : upload.conflict === "new_name_existing_hash"
        ? { body: `Nội dung này đang thuộc tài liệu «${upload.filename}».`, actions: [[`Đổi tên thành "${uploadName}"`, "rename"]] }
        : upload.conflict === "same_name_different_hash"
          ? { body: `«${upload.filename}» đã tồn tại nhưng nội dung khác.`, actions: [["Thay thế (tạo version mới)", "replace"], [`Giữ cả hai («${upload.suggested_filename}»)`, "keep_both"]] }
          : null;
  if (!options) return Promise.resolve("cancel");
  return new Promise((resolve) => {
    const dialog = $("conflict-dialog");
    $("conflict-body").textContent = options.body;
    const actionRow = $("conflict-actions");
    actionRow.replaceChildren();
    const done = (value) => { dialog.close(); resolve(value); };
    const cancel = el("button", "btn ghost", "Hủy");
    cancel.type = "button";
    cancel.onclick = () => done("cancel");
    actionRow.append(cancel);
    for (const [label, action] of options.actions) {
      const button = el("button", "btn primary", label);
      button.type = "button";
      button.onclick = () => done(action);
      actionRow.append(button);
    }
    dialog.oncancel = () => resolve("cancel");
    dialog.showModal();
  });
}

async function waitForIngestion(runId) {
  let idle = 0, last = "";
  while (idle < 900) {
    const run = await api(`/documents/ingestions/${runId}`);
    showUploadStatus(`${run.stage} · ${run.vectors_count}/${run.chunks_count || "?"} vector`, run.progress_percent || 0);
    if (["completed", "failed", "cancelled"].includes(run.status)) return run;
    const snapshot = `${run.stage}|${run.progress_percent}|${run.processed_pages}|${run.vectors_count}`;
    if (snapshot === last) idle += 1; else { idle = 0; last = snapshot; }
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
  throw new Error("Quá trình lập chỉ mục không tiến triển.");
}

async function uploadFlow() {
  if (!selectedFile || uploading) return;
  // Snapshot: đổi lựa chọn tệp giữa chừng không được ảnh hưởng flow đang chạy.
  const file = selectedFile;
  uploading = true;
  $("upload-btn").disabled = true;
  showUploadStatus("Đang tải lên…", 4);
  try {
    const form = () => {
      const data = new FormData();
      data.append("file", file);
      return data;
    };
    let upload = await api("/documents/upload", { method: "POST", body: form() });
    while (upload.action_required) {
      const decision = await conflictDecision(upload, file.name);
      const data = form();
      data.append("decision", decision);
      upload = await api("/documents/upload", { method: "POST", body: data });
    }
    if (upload.cancelled) { showUploadStatus("Đã hủy. Dữ liệu không thay đổi.", 0); return; }
    let run = null;
    if (upload.status === "processing" && upload.run_id) {
      run = await waitForIngestion(upload.run_id);
    } else if (upload.status === "processing") {
      // use_existing/rename trên tài liệu đang index: run có sẵn nhưng không
      // trả run_id — tuyệt đối không POST /documents/index lần nữa (409).
      showUploadStatus("Tài liệu đang được lập chỉ mục sẵn. Theo dõi ở danh sách bên dưới.", 50);
    } else if (upload.status !== "indexed") {
      const index = await api("/documents/index", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: upload.document_id }),
      });
      run = await waitForIngestion(index.ingestion_run_id);
    }
    if (run && run.status !== "completed") throw new Error(run.error_message || `Lập chỉ mục ${run.status}.`);
    showUploadStatus(
      upload.renamed ? `Đã đổi tên tài liệu hiện có thành ${upload.filename}.`
        : run ? `Hoàn tất · ${run.chunks_count} đoạn đã sẵn sàng.` : "Tài liệu đã có sẵn trong hệ thống.",
      100);
    state.selectedDocs.add(upload.document_id);
    saveDocSelection();
    toast("Tài liệu đã sẵn sàng cho hỏi đáp.", "ok");
    selectedFile = null;
  } catch (error) {
    showUploadStatus(`Lỗi: ${error.message}`, 0);
    toast(error.message, "error");
  } finally {
    uploading = false;
    $("upload-btn").disabled = !selectedFile;
    loadDocuments();
  }
}

/* ── Settings ──────────────────────────────────────────────────── */
function openSettings() {
  const dialog = $("settings-dialog");
  for (const radio of document.querySelectorAll('#settings-dialog input[name="theme"]')) {
    radio.checked = radio.value === prefs.theme;
  }
  $("set-enter").checked = prefs.enterToSend;
  $("set-memory").checked = prefs.memoryDefault;
  syncApiKeyState();
  dialog.showModal();
  loadModelsInfo();
  loadSystemInfo();
}

/* Không hiển thị lại khóa đã lưu: ô nhập luôn trống, dòng trạng thái cho biết
   đã có khóa hay chưa. */
function syncApiKeyState() {
  const stored = getApiKey();
  $("set-api-key").value = "";
  $("set-api-key").placeholder = stored ? "Đã lưu — dán khóa mới để thay" : "Dán khóa truy cập";
  $("api-key-state").textContent = stored
    ? "Đã lưu khóa trong trình duyệt này. Để trống rồi bấm Lưu để xóa."
    : "Chưa nhập khóa. Chỉ cần khi máy chủ bật xác thực.";
}

async function loadModelsInfo() {
  const box = $("models-info");
  try {
    const { models } = await api("/models");
    const labels = { general: "Trò chuyện & RAG", embedding: "Embedding", vision: "Vision", ocr: "OCR" };
    box.replaceChildren();
    for (const [key, label] of Object.entries(labels)) {
      const config = models[key];
      if (!config) continue;
      const row = el("div", "kv");
      row.append(el("b", "", label));
      const detail = [config.name, config.provider && config.provider !== "ollama" ? `qua ${config.provider}` : null]
        .filter(Boolean).join(" · ");
      row.append(el("span", "", key === "ocr" && config.enabled === false ? `${detail} (tắt)` : detail));
      box.append(row);
    }
  } catch {
    box.replaceChildren(el("p", "muted", "Không đọc được cấu hình mô hình."));
  }
}

async function loadSystemInfo() {
  const box = $("system-info");
  try {
    const health = await api("/health");
    box.replaceChildren();
    const overall = el("div", "kv");
    overall.append(el("b", "", "Trạng thái"));
    overall.append(el("span", "", health.status === "ok" ? "Hoạt động bình thường" : "Suy giảm một phần"));
    box.append(overall);
    const componentLabels = { postgres: "PostgreSQL", redis: "Redis", qdrant: "Qdrant", ollama: "Ollama" };
    for (const [key, label] of Object.entries(componentLabels)) {
      if (!(key in health)) continue;
      const row = el("div", "kv");
      row.append(el("b", "", label));
      row.append(el("span", "", health[key] === "ok" ? "✓ sẵn sàng" : health[key]));
      box.append(row);
    }
  } catch {
    box.replaceChildren(el("p", "muted", "Không kết nối được máy chủ."));
  }
}

async function searchMemories(query) {
  const box = $("mem-results");
  if (!query.trim()) {
    box.replaceChildren(el("p", "muted", "Nhập từ khóa để tìm trong các ghi nhớ đã lưu."));
    return;
  }
  box.replaceChildren(el("div", "skeleton"));
  box.firstChild.style.height = "56px";
  try {
    const results = await api("/memory/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, top_k: 10 }),
    });
    box.replaceChildren();
    if (!results.length) {
      box.append(el("p", "muted", "Không tìm thấy ghi nhớ nào khớp."));
      return;
    }
    for (const memory of results) {
      const item = el("div", "mem-item");
      const body = el("div", "mem-content", memory.content);
      body.append(el("div", "mem-meta", `${memory.memory_type || "ghi nhớ"} · độ quan trọng ${memory.importance ?? "?"}`));
      const deleteBtn = iconBtn("trash", "Xóa ghi nhớ này");
      deleteBtn.onclick = async () => {
        const yes = await confirmAction({ title: "Xóa ghi nhớ?", body: "Trợ lý sẽ không dùng ghi nhớ này nữa." });
        if (!yes) return;
        try {
          await api(`/memory/${memory.memory_id || memory.id}`, { method: "DELETE" });
          item.remove();
          toast("Đã xóa ghi nhớ.", "ok");
        } catch (error) { toast(error.message, "error"); }
      };
      item.append(body, deleteBtn);
      box.append(item);
    }
  } catch (error) {
    box.replaceChildren(el("p", "muted", error.message));
  }
}

/* ── Health ────────────────────────────────────────────────────── */
async function pollHealth() {
  const dot = $("health-dot");
  try {
    const health = await api("/health");
    if (health.status === "ok") {
      dot.dataset.state = "ok";
      $("health-text").textContent = "Hệ thống sẵn sàng";
    } else {
      dot.dataset.state = "degraded";
      const bad = ["postgres", "redis", "qdrant", "ollama"]
        .filter((key) => key in health && health[key] !== "ok");
      $("health-text").textContent = bad.length ? `Suy giảm: ${bad.join(", ")}` : "Suy giảm một phần";
    }
  } catch {
    dot.dataset.state = "down";
    $("health-text").textContent = "Mất kết nối backend";
  }
}

/* ── Composer & shell ──────────────────────────────────────────── */
function autoSizeComposer() {
  const input = $("composer-input");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
}

function syncSendState() {
  $("send-btn").disabled = state.generating || !$("composer-input").value.trim();
}

function syncMemoryChip() {
  const chip = $("memory-chip");
  chip.setAttribute("aria-pressed", String(state.memoryOn));
  chip.lastChild.textContent = state.memoryOn ? " Ghi nhớ: bật" : " Ghi nhớ: tắt";
}

const MODE_TEXT = {
  general: { sub: "", placeholder: "Nhập tin nhắn…" },
  rag: { sub: "Hỏi đáp theo tài liệu, có trích dẫn nguồn, lưu vào hội thoại", placeholder: "Hỏi về nội dung tài liệu đã chọn…" },
};

function setMode(mode) {
  state.mode = mode;
  for (const radio of document.querySelectorAll('#mode-seg input')) radio.checked = radio.value === mode;
  updateModeUi();
}

function updateModeUi() {
  const mode = state.mode;
  $("docs-chip").hidden = mode !== "rag";
  $("memory-chip").hidden = mode !== "general";
  $("topbar-sub").textContent = MODE_TEXT[mode].sub;
  $("composer-input").placeholder = MODE_TEXT[mode].placeholder;
}

function showBackdrop(show) { $("backdrop").hidden = !show; }
function closeDrawers() {
  $("app").classList.remove("sidebar-open-mobile");
  if (window.innerWidth <= 960) openDocs(false);
  showBackdrop(false);
}

const SUGGESTIONS = [
  { title: "Giải thích khái niệm", body: "Giải thích cho tôi RAG là gì và khi nào nên dùng?" },
  { title: "Soạn thảo nội dung", body: "Soạn giúp tôi một email báo giá chuyên nghiệp bằng tiếng Việt." },
  { title: "Hỏi đáp tài liệu", body: "__docs__" },
  { title: "Tóm tắt văn bản", body: "Tóm tắt văn bản sau thành 5 ý chính, giữ nguyên số liệu quan trọng:\n\n" },
];

function renderSuggestions() {
  const wrap = $("suggestions");
  wrap.replaceChildren();
  for (const suggestion of SUGGESTIONS) {
    const card = el("button", "suggestion");
    card.type = "button";
    card.setAttribute("role", "listitem");
    card.append(el("strong", "", suggestion.title));
    if (suggestion.body === "__docs__") {
      card.append(document.createTextNode("Tải tài liệu lên rồi hỏi đáp có trích dẫn nguồn."));
      card.onclick = () => { setMode("rag"); openDocs(true); };
    } else {
      card.append(document.createTextNode(suggestion.body));
      card.onclick = () => {
        const input = $("composer-input");
        input.value = suggestion.body;
        autoSizeComposer();
        syncSendState();
        input.focus();
      };
    }
    wrap.append(card);
  }
}

/* ── Bind events ───────────────────────────────────────────────── */
function bindEvents() {
  // Composer
  const input = $("composer-input");
  input.addEventListener("input", () => { autoSizeComposer(); syncSendState(); });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && prefs.enterToSend && !event.isComposing) {
      event.preventDefault();
      $("composer-form").requestSubmit();
    }
  });
  $("composer-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const prompt = input.value.trim();
    if (!prompt || state.generating) return;
    // Validate trước khi xóa input: người dùng không bao giờ mất tin đang gõ.
    if (state.mode === "rag" && !state.selectedDocs.size) {
      toast("Hãy chọn ít nhất một tài liệu đã lập chỉ mục trước.", "error");
      openDocs(true);
      return;
    }
    input.value = "";
    autoSizeComposer();
    syncSendState();
    sendPrompt(prompt);
  });
  $("stop-btn").onclick = () => state.abort?.abort();

  // Mode & chips
  for (const radio of document.querySelectorAll('#mode-seg input')) {
    radio.addEventListener("change", () => { if (radio.checked) setMode(radio.value); });
  }
  $("memory-chip").onclick = () => { state.memoryOn = !state.memoryOn; syncMemoryChip(); };
  $("docs-chip").onclick = () => openDocs(!docsOpen());

  // Sidebar
  $("new-chat").onclick = newChat;
  $("conv-search").addEventListener("input", debounce(renderConversations, 120));
  $("sidebar-collapse").onclick = () => {
    // Trong drawer mobile, nút này đóng drawer thay vì thu gọn vĩnh viễn.
    if (window.innerWidth <= 960) { closeDrawers(); return; }
    $("app").classList.add("sidebar-hidden");
    $("sidebar-reopen").hidden = false;
  };
  $("sidebar-reopen").onclick = () => {
    $("app").classList.remove("sidebar-hidden");
    $("sidebar-reopen").hidden = true;
  };
  $("sidebar-open").onclick = () => {
    $("app").classList.add("sidebar-open-mobile");
    showBackdrop(true);
  };
  $("backdrop").onclick = closeDrawers;
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    // Dialog đang mở: để native <dialog> tự xử lý Esc, đừng đóng drawer phía sau.
    if (document.querySelector("dialog[open]")) return;
    closeDrawers();
  });

  // Docs
  $("open-docs").onclick = () => openDocs(!docsOpen());
  $("docs-close").onclick = () => openDocs(false);
  const zone = $("dropzone");
  zone.addEventListener("click", () => $("file-input").click());
  zone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); $("file-input").click(); }
  });
  zone.tabIndex = 0;
  $("file-input").onchange = (event) => chooseFile(event.target.files[0]);
  for (const type of ["dragenter", "dragover"]) {
    zone.addEventListener(type, (event) => { event.preventDefault(); zone.classList.add("drag"); });
  }
  for (const type of ["dragleave", "drop"]) {
    zone.addEventListener(type, (event) => { event.preventDefault(); zone.classList.remove("drag"); });
  }
  zone.addEventListener("drop", (event) => chooseFile(event.dataTransfer.files[0]));
  $("upload-btn").onclick = uploadFlow;
  $("select-all-docs").onchange = (event) => {
    for (const doc of state.documents) {
      if (doc.status !== "indexed") continue;
      event.target.checked ? state.selectedDocs.add(doc.document_id) : state.selectedDocs.delete(doc.document_id);
    }
    saveDocSelection();
    renderDocuments();
  };

  // Scroll
  chatScroll().addEventListener("scroll", syncJumpButton, { passive: true });
  $("jump-latest").onclick = () => scrollToBottom(true);

  // Settings
  $("open-settings").onclick = openSettings;
  $("settings-close").onclick = () => $("settings-dialog").close();
  for (const radio of document.querySelectorAll('#settings-dialog input[name="theme"]')) {
    radio.addEventListener("change", () => {
      if (radio.checked) { prefs.theme = radio.value; savePrefs(); applyTheme(); }
    });
  }
  $("set-enter").onchange = (event) => {
    prefs.enterToSend = event.target.checked;
    savePrefs();
    $("composer-hint").textContent = prefs.enterToSend
      ? "Enter để gửi · Shift+Enter xuống dòng" : "Bấm nút gửi · Enter xuống dòng";
  };
  $("set-memory").onchange = (event) => { prefs.memoryDefault = event.target.checked; savePrefs(); };
  $("api-key-save").onclick = () => {
    setApiKey($("set-api-key").value);
    syncApiKeyState();
    toast(getApiKey() ? "Đã lưu khóa truy cập." : "Đã xóa khóa truy cập.", "ok");
  };
  $("set-api-key").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); $("api-key-save").click(); }
  });
  $("mem-search").addEventListener("input", debounce((event) => searchMemories(event.target.value), 400));
}

/* ── Init ──────────────────────────────────────────────────────── */
function init() {
  applyTheme();
  renderSuggestions();
  bindEvents();
  syncMemoryChip();
  updateModeUi();
  syncSendState();
  clearMessages();
  $("composer-hint").textContent = prefs.enterToSend
    ? "Enter để gửi · Shift+Enter xuống dòng" : "Bấm nút gửi · Enter xuống dòng";
  // Deep-link từ dashboard: /ui/#c=<conversation_id> mở thẳng hội thoại.
  const deepLink = location.hash.match(/^#c=(.+)$/);
  loadConversations().then(() => {
    if (!deepLink) return;
    let id;
    try { id = decodeURIComponent(deepLink[1]); } catch { return; }
    openConversation(id);
  });
  loadDocuments();
  pollHealth();
  setInterval(pollHealth, 60000);
}

init();
