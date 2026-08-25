/* P4-5: xem tài liệu bị cắt thành đoạn nào, đánh dấu đoạn kém.
   Trang tĩnh tải một lần; lọc client-side; không gọi model, không đụng /rag/*. */
"use strict";

/* $, el, theme/prefs và requestJson nằm ở /ui/common.js (T8), nạp trước file
   này — ghi chú cũ ở đây nói "hợp nhất là nợ T8"; nợ đó đã trả. */
const api = requestJson;

const documentId = new URLSearchParams(location.search).get("document_id");
const state = { chunks: [], meta: null, offset: 0, limit: 50, done: false };

/* Overlap với chunk TRƯỚC: phần đầu của content này xuất hiện ở cuối content
   trước (chunker chép nguyên block sang làm ngữ cảnh nối). So bằng text thay vì
   locations vì bảng không tham gia overlap và locations của fragment trùng
   nhau khi block bị cắt câu. Trả độ dài prefix trùng (0 = không overlap). */
function overlapPrefixLength(previousContent, content) {
  if (!previousContent || !content) return 0;
  const max = Math.min(previousContent.length, content.length);
  for (let length = max; length >= 20; length -= 1) {
    if (previousContent.endsWith(content.slice(0, length))) return length;
  }
  return 0;
}

function contentNode(chunk, previous) {
  const isTable = chunk.block_type === "table";
  const node = el("div", `ck-content${isTable ? " table" : ""}`);
  const overlap = isTable ? 0 : overlapPrefixLength(previous ? previous.content : "", chunk.content);
  if (overlap > 0) {
    const shared = el("span", "ck-overlap", chunk.content.slice(0, overlap));
    shared.title = "Phần lặp lại từ chunk trước (overlap của chunker) — ranh giới cắt nằm ngay sau đây";
    node.append(shared, document.createTextNode(chunk.content.slice(overlap)));
  } else {
    node.textContent = chunk.content;
  }
  return node;
}

function flagControls(chunk, card) {
  const wrap = el("div", "ck-actions");
  const button = el("button", "btn ghost");
  const note = el("span", "ck-note");
  const paint = () => {
    const flagged = Boolean(chunk.feedback);
    card.classList.toggle("flagged", flagged);
    button.textContent = flagged ? "Bỏ đánh dấu" : "Đánh dấu kém";
    note.textContent = flagged && chunk.feedback.note ? `Ghi chú: ${chunk.feedback.note}` : "";
  };
  button.onclick = async () => {
    button.disabled = true;
    try {
      if (chunk.feedback) {
        await api(`/documents/${documentId}/chunks/${chunk.chunk_id}/feedback`, { method: "DELETE" });
        chunk.feedback = null;
      } else {
        const text = prompt("Vì sao đoạn này kém? (bỏ trống nếu không cần ghi chú)") ?? null;
        if (text === null) { button.disabled = false; return; } // Cancel = không đánh dấu
        const saved = await api(`/documents/${documentId}/chunks/${chunk.chunk_id}/feedback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label: "bad", note: text.trim() || null }),
        });
        chunk.feedback = { label: saved.label, note: saved.note };
      }
      paint();
    } catch (error) {
      $("ck-notice").textContent = `Không lưu được đánh dấu: ${error.message} (cần API key + quyền admin — đặt trong trang Chat)`;
    }
    button.disabled = false;
  };
  paint();
  wrap.append(button, note);
  return wrap;
}

function card(chunk, previous) {
  const node = el("div", "ck-card");
  const meta = el("div", "ck-meta");
  const pages = chunk.page_start == null ? "không có số trang (docx)" :
    chunk.page_end && chunk.page_end !== chunk.page_start ? `trang ${chunk.page_start}–${chunk.page_end}` : `trang ${chunk.page_start}`;
  meta.append(
    el("span", "", `#${chunk.chunk_index}`),
    el("span", "", pages),
    el("span", "", chunk.token_count != null ? `${chunk.token_count} token` : "? token"),
    el("span", "", chunk.block_type),
  );
  if (chunk.feedback) meta.append(el("span", "ck-badge", "kém"));
  node.append(meta);
  const heading = chunk.heading_path && chunk.heading_path.length
    ? el("div", "ck-heading", chunk.heading_path.join(" › "))
    : el("div", "ck-heading none", "không thuộc mục nào");
  node.append(heading);
  if (chunk.retrieval_context) {
    const context = el("div", "ck-context", chunk.retrieval_context);
    context.title = "Ngữ cảnh do model sinh lúc index (P4-2) — chỉ mục tìm kiếm nhìn thấy nó, câu trả lời thì không";
    node.append(context);
  }
  node.append(contentNode(chunk, previous), flagControls(chunk, node));
  return node;
}

function render() {
  const list = $("ck-list");
  const query = $("ck-filter").value.trim().toLowerCase();
  list.replaceChildren();
  let shown = 0;
  state.chunks.forEach((chunk, index) => {
    if (query && !chunk.content.toLowerCase().includes(query) &&
        !(chunk.heading_path || []).join(" ").toLowerCase().includes(query)) return;
    list.append(card(chunk, index > 0 ? state.chunks[index - 1] : null));
    shown += 1;
  });
  const total = state.meta ? state.meta.total_chunks : state.chunks.length;
  $("ck-count").textContent = query
    ? `${shown}/${state.chunks.length} đoạn khớp (đã tải ${state.chunks.length}/${total})`
    : `${state.chunks.length}/${total} đoạn · ${state.meta ? state.meta.total_tokens : "?"} token`;
  $("ck-more").hidden = state.done;
}

/* Chan bam dup: hai lan bam lien tiep cung doc offset cu -> tai trung trang 1
   va nhay han trang 2. Co cua duy nhat, tha o finally de loi mang khong khoa
   nut vinh vien. */
let loading = false;
async function loadPage() {
  if (loading) return;
  loading = true;
  try { await loadPageOnce(); } finally { loading = false; }
}

async function loadPageOnce() {
  const data = await api(`/documents/${documentId}/chunks?limit=${state.limit}&offset=${state.offset}`);
  state.meta = data;
  state.chunks.push(...data.chunks);
  state.offset += data.chunks.length;
  state.done = state.offset >= data.total_chunks || data.chunks.length === 0;
  $("ck-title").textContent = data.filename;
  $("ck-sub").textContent = `version ${data.version_number} · ${data.total_chunks} đoạn · ${data.total_tokens} token`;
  document.title = `Chunks — ${data.filename}`;
  render();
}

async function start() {
  if (!documentId) {
    $("ck-notice").textContent = "Thiếu ?document_id= — mở trang này từ nút «Đoạn» cạnh tài liệu trong Chat.";
    return;
  }
  try { await loadPage(); }
  catch (error) { $("ck-notice").textContent = `Không tải được: ${error.message}`; }
}

$("ck-filter").addEventListener("input", render);
$("ck-more").onclick = () => loadPage().catch((error) => { $("ck-notice").textContent = error.message; });
start();
