/* ══════════════════════════════════════════════════════════════════
   /ui/common.js — bộ helper dùng chung cho MỌI trang (nợ T8)

   Trước bản này, bốn trang (`app.js`, `dashboard.js`, `ocr.js`,
   `chunks.js`) mỗi trang tự chép một bản `$`, `el`, theme và hàm gắn
   header xác thực. Bốn bản đó **không giống nhau**, và chính chỗ lệch
   là nguồn gốc lỗi thật: dashboard từng quên hẳn `X-API-Key`, rồi khi
   có rồi thì vẫn thiếu refresh token nên hết hạn phiên là văng thẳng
   về trang đăng nhập giữa lúc đang xem. Sửa một bản không sửa ba bản
   kia — đó là định nghĩa của nợ này.

   Script thường, KHÔNG `type="module"`: bốn trang đều là script cổ
   điển dùng chung phạm vi global, đổi sang module sẽ khiến mọi khai
   báo top-level thôi là global và phải viết lại cả bốn file. Thứ tự
   nạp là hợp đồng: common.js đứng TRƯỚC script của trang trong HTML
   (`defer` giữ nguyên thứ tự giữa các script defer).
   ══════════════════════════════════════════════════════════════════ */
"use strict";

/* ── DOM ───────────────────────────────────────────────────────── */
const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* Chỉ dùng khi buộc phải dựng chuỗi HTML; đường mặc định là el()/textContent. */
function esc(text) {
  return String(text)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

/* ── Prefs & theme (chung khóa lac.prefs với trang chat) ───────── */
function readStore(key, fallback) {
  try { return { ...fallback, ...JSON.parse(localStorage.getItem(key) || "{}") }; }
  catch { return { ...fallback }; }
}

const prefs = readStore("lac.prefs", {
  theme: "system", enterToSend: true, memoryDefault: false, mode: "general", toolsOn: false,
});
const savePrefs = () => localStorage.setItem("lac.prefs", JSON.stringify(prefs));

const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
function applyTheme() {
  document.documentElement.dataset.theme =
    prefs.theme === "system" ? (systemDark.matches ? "dark" : "light") : prefs.theme;
}
systemDark.addEventListener("change", applyTheme);
/* Gọi ngay lúc nạp, trước khi trang vẽ: nếu đợi tới init thì người dùng
   theme tối thấy một nháy sáng. Trang nào đổi theme trong Cài đặt vẫn
   gọi lại applyTheme() như cũ. */
applyTheme();

/* ── Xác thực ──────────────────────────────────────────────────── */
const getApiKey = () => localStorage.getItem("lac.apikey") || "";
const setApiKey = (value) => {
  const key = value.trim();
  if (key) localStorage.setItem("lac.apikey", key);
  else localStorage.removeItem("lac.apikey");
};

/* Gắn khóa vào mọi request; không có khóa thì không thêm header nào, để
   máy chủ không bật xác thực vẫn chạy y như trước.

   Bearer gắn vô điều kiện khi localStorage có token: máy chủ đọc header
   này SAU khi kiểm tra `auth_enabled` (app/security/auth.py), nên token
   cũ còn sót lại lúc chế độ tài khoản đang tắt bị bỏ qua hoàn toàn — ba
   trong bốn trang vốn đã làm đúng như vậy. */
function authHeaders(extra = {}) {
  const key = getApiKey();
  const result = key ? { ...extra, "X-API-Key": key } : { ...extra };
  const access = localStorage.getItem("lac.access");
  if (access) result.Authorization = `Bearer ${access}`;
  return result;
}

/* Một lần refresh cho cả trang, dù mười request cùng 401 một lúc: nếu
   không gom vào một promise thì mười lời gọi /auth/refresh chạy song
   song, chín cái mang refresh token đã bị xoay vòng và fail.
   Trả về payload (có .user) khi thành công, null khi không. */
let refreshInFlight = null;
async function refreshAccessToken() {
  const refresh = localStorage.getItem("lac.refresh");
  if (!refresh) return null;
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await fetch("/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
        if (!response.ok) return null;
        const data = await response.json();
        localStorage.setItem("lac.access", data.access_token);
        return data;
      } catch {
        return null;
      }
    })().finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
}

/* ── Gọi API ───────────────────────────────────────────────────── */
/* Máy chủ trả lỗi ở dạng phẳng {error, error_code, message, detail}
   (app/main.py http_error_handler), nên mã lỗi tra được bảng tiếng Việt
   dưới đây thay vì hiện số HTTP trần. */
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

/* Một lần gửi, không tự xử lý 401 — dành cho trang muốn tự quyết
   (app.js hiện overlay đăng nhập thay vì chuyển trang). */
async function sendJson(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { ...options, headers: authHeaders(options.headers) });
  } catch {
    throw new Error("Không kết nối được máy chủ. Kiểm tra backend đang chạy.");
  }
  const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(ERROR_HINTS[data.error_code] || data.message || `Yêu cầu thất bại (${response.status}).`);
    error.code = data.error_code;
    error.status = response.status;
    throw error;
  }
  return data;
}

/* Đường mặc định cho các trang phụ: 401 thì thử refresh MỘT lần rồi gửi
   lại. Trước T8 chỉ trang chat làm việc này, nên dashboard/ocr/chunks hết
   hạn access token là đá thẳng người dùng về đăng nhập dù refresh token
   vẫn còn hạn. */
async function requestJson(path, options = {}) {
  try {
    return await sendJson(path, options);
  } catch (error) {
    if (error.status === 401 && (await refreshAccessToken())) return sendJson(path, options);
    throw error;
  }
}
