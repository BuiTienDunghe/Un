/* ══════════════════════════════════════════════════════════════════
   /ui/shell.js — khung app (global duy nhất: Shell).

   Khởi động ở DOMContentLoaded, tức SAU khi mọi views/*.js đã
   Router.register(): cờ hiệu ứng → /auth/config (lỗi = coi như tắt tài
   khoản, như app cũ) → nếu bật tài khoản: token → /auth/me, không được thì
   refresh → /auth/me, vẫn không được thì màn đăng nhập → vẽ nav theo vai
   trò, chân sidebar, dòng trạng thái /health, chuông thông báo, badge Ghi
   nhớ → Router.start().
   Màn đăng nhập hiện khi app đang chạy → Router.pause() (đăng xuất: gỡ view;
   phiên hết hạn: giữ view nhưng dừng poll/định tuyến) → đăng nhập lại cùng
   người → Router.resume(); người khác → nạp lại trang.

   Gọi mạng: sendJson/requestJson của common.js. Ngoại lệ duy nhất là
   Shell.fetchBlob (tải nhị phân có header xác thực) — chỗ gọi mạng thô
   duy nhất của file này.
   ══════════════════════════════════════════════════════════════════ */
"use strict";

const Shell = (() => {
  const NAV = [
    { name: "chat", label: "Chat", icon: "chat" },
    { name: "documents", label: "Tài liệu", icon: "docs" },
    { name: "memory", label: "Ghi nhớ", icon: "memory" },
    { name: "dashboard", label: "Bảng điều khiển", icon: "dash" },
    { name: "ocr", label: "OCR", icon: "ocr", admin: true },
    { name: "bot", label: "Bot Discord", icon: "bot", admin: true },
    { name: "models", label: "Model", icon: "cpu", admin: true },
    { name: "users", label: "Người dùng", icon: "users", admin: true },
    { name: "settings", label: "Cài đặt", icon: "gear" },
  ];
  /* route không có mục nav riêng → sáng mục nào */
  const NAV_ALIAS = { chunks: "documents" };
  const POLL_MS = 60000;
  const MISSING_POLL_MS = 10 * 60000;   // API chưa có (404): hỏi lại thưa hơn
  const CORE_HEALTH_KEYS = ["postgres", "redis", "qdrant", "ollama"];
  const NOT_STATUS_KEYS = new Set(["status", "service", "memory_queue", "backup_age_hours", "checked_at", "error"]);
  const DEFAULT_TITLE = "Local AI Core — Trợ lý AI";
  const LOGIN_TITLE = "Đăng nhập — Local AI Core";
  const EXPIRED = "Phiên đăng nhập đã hết hạn. Đăng nhập lại để tiếp tục.";

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const mobileQuery = window.matchMedia("(max-width: 960px)");

  const state = {
    user: null,
    authEnabled: false,
    hasUsers: true,
    started: false,
    loginVisible: false,
    meError: null,
    lastUserId: null,
    health: null,
    healthBusy: false,
    healthSubs: new Set(),
    badges: {},
    notif: { status: "idle", items: [], unread: 0, error: null },
    notifBusy: null,
    notifView: null,
    notifAt: 0,
    countMissing: false,
    panelTouched: false,
    lastTick: 0,
    loggingOut: false,
    authRecheck: null,
    configUnknown: false,   // /auth/config không trả lời lúc khởi động → đang ĐOÁN là tắt tài khoản
  };
  const dom = {};
  const navItems = new Map();

  /* Cờ hiệu ứng áp NGAY khi script chạy, trước khi view nào vẽ. */
  document.documentElement.dataset.motion = prefs.motion === false ? "off" : "on";

  /* ── tiện ích nội bộ ─────────────────────────────────────────── */
  function timeoutSignal(ms) {
    return typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(ms) : undefined;
  }

  function safeSavePrefs() {
    try { savePrefs(); } catch (error) { console.warn("[shell] không lưu được lac.prefs", error); }
  }

  function readToken(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  }

  /* refreshAccessToken() của common.js không có hạn chờ: quá `ms` thì coi như refresh hỏng,
     để khởi động và tải nhị phân không treo mãi khi /auth/refresh không trả lời. */
  function refreshSoon(ms = 8000) {
    return Promise.race([refreshAccessToken(), new Promise((resolve) => { setTimeout(() => resolve(null), ms); })]);
  }

  /* Cùng loại lỗi với fetchBlob khi signal bị hủy; lời tiếng Việt phòng khi view lỡ hiện ra. */
  function abortError() {
    try { return new DOMException("Đã hủy yêu cầu.", "AbortError"); } catch {
      const error = new Error("Đã hủy yêu cầu.");
      error.name = "AbortError";
      return error;
    }
  }

  function isAdmin() {
    return !state.authEnabled || (state.user && state.user.role === "admin") || false;
  }

  function motionOn() {
    return prefs.motion !== false && !reducedMotion.matches;
  }

  /* ── API ─────────────────────────────────────────────────────── */

  /* requestJson (401 → refresh 1 lần → gửi lại) + khi bật tài khoản mà vẫn 401 → màn đăng nhập.
     signal bị hủy (không phải hết giờ) → AbortError như fetchBlob, thay vì lỗi "Không kết nối…". */
  async function api(path, options = {}) {
    try {
      return await requestJson(path, options);
    } catch (error) {
      const signal = options && options.signal;
      if (signal && signal.aborted && !(signal.reason && signal.reason.name === "TimeoutError")) throw abortError();
      if (error && error.status === 401) onUnauthorized(error);
      throw error;
    }
  }

  /* 401 cuối cùng (refresh cũng hỏng). Bật tài khoản → màn đăng nhập. Đang chạy như TẮT tài khoản
     (vd. /auth/config quá chậm lúc khởi động) mà máy chủ đòi đăng nhập → hỏi lại /auth/config. */
  function onUnauthorized(error) {
    if (state.authEnabled) showLogin({ message: EXPIRED, rebuild: false });
    else if (error && (error.code === "AUTH_REQUIRED" || error.code === "TOKEN_INVALID")) recheckAuthMode();
  }

  function recheckAuthMode() {
    if (state.authRecheck || !state.started) return state.authRecheck;
    state.authRecheck = (async () => {
      try {
        const config = await sendJson("/auth/config", { signal: timeoutSignal(10000) });
        state.configUnknown = false;
        if (!config || !config.enabled || state.authEnabled) return;
        state.authEnabled = true;
        state.hasUsers = config.has_users !== false;
        const user = await resolveUser();
        if (!user) {
          renderUser();
          showLogin({ message: "Máy chủ đang bật tài khoản — đăng nhập để tiếp tục." });
          return;
        }
        state.user = user;
        state.lastUserId = user.id;
        renderUser();
        renderNav();
        refreshMemoryBadge();
        Router.resume({ force: true });   // chạy lại route theo vai trò thật (route admin → #/chat)
      } catch { /* vẫn không hỏi được: giữ nguyên */ } finally {
        state.authRecheck = null;
      }
    })();
    return state.authRecheck;
  }

  /* Tải nhị phân (ảnh trang, ảnh OCR, zip…) có header xác thực → Blob.
     401 → refresh một lần rồi gửi lại. Lỗi → Error có .status (0 = mất kết nối) và .code. */
  async function fetchBlob(path, options = {}) {
    const send = () => fetch(path, { ...options, headers: authHeaders(options.headers) });
    let response;
    try {
      response = await send();
      if (response.status === 401 && (await refreshSoon())) response = await send();
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      const failure = new Error("Không kết nối được máy chủ. Kiểm tra backend đang chạy.");
      failure.status = 0;
      throw failure;
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const error = new Error(ERROR_HINTS[data.error_code] || data.message || `Yêu cầu thất bại (${response.status}).`);
      error.code = data.error_code;
      error.status = response.status;
      if (response.status === 401) onUnauthorized(error);
      throw error;
    }
    return response.blob();
  }

  /* ── header / sidebar ────────────────────────────────────────── */
  function setHeader(title, sub) {
    dom.title.textContent = title == null ? "" : String(title);
    dom.sub.textContent = sub == null ? "" : String(sub);
    document.title = title ? `${title} — Local AI Core` : DEFAULT_TITLE;
  }

  function setHeaderActions(nodes) {
    const list = nodes == null ? [] : Array.isArray(nodes) ? nodes : [nodes];
    dom.actions.replaceChildren(...list.filter((n) => n instanceof Node));
  }

  function setSidebarPanel(node) {
    state.panelTouched = true;
    if (!(node instanceof Node)) {
      dom.panel.replaceChildren();
      dom.panel.hidden = true;
      dom.spacer.hidden = false;
      return;
    }
    if (dom.panel.childNodes.length !== 1 || dom.panel.firstChild !== node) dom.panel.replaceChildren(node);
    dom.panel.hidden = false;
    dom.spacer.hidden = true;
  }

  /* Router gọi quanh phần đồng bộ của mount(): view mới không đặt khối sidebar → dọn khối cũ. */
  function beginMount() { state.panelTouched = false; }
  function endMount() { if (!state.panelTouched) setSidebarPanel(null); }

  function setNavBadge(name, n) {
    state.badges[name] = n;
    const item = navItems.get(name);
    if (!item) return;
    let text = "";
    if (typeof n === "number" && Number.isFinite(n)) text = n <= 0 ? "" : n >= 100 ? "99+" : String(Math.round(n));
    else if (n != null && n !== false) text = String(n);
    item.badge.textContent = text;
    item.badge.hidden = !text;
    item.link.setAttribute("aria-label", text ? `${item.label} (${text})` : item.label);
  }

  function renderNav() {
    navItems.clear();
    const links = [];
    for (const entry of NAV) {
      if (entry.admin && !isAdmin()) continue;
      const badge = h("span", { class: "badge-count", hidden: true });
      const link = h("a", { class: "nav-item", href: `#/${entry.name}`, dataset: { nav: entry.name } },
        icon(entry.icon, { size: 18, sw: 1.8 }), h("span", { class: "label" }, entry.label), badge);
      link.addEventListener("click", () => setMobileSidebar(false));
      navItems.set(entry.name, { link, badge, label: entry.label });
      links.push(link);
    }
    dom.nav.replaceChildren(...links);
    for (const [name, value] of Object.entries(state.badges)) setNavBadge(name, value);
    syncActiveNav();
  }

  function syncActiveNav() {
    const cur = typeof Router !== "undefined" ? Router.current : null;
    const active = cur ? NAV_ALIAS[cur.name] || cur.name : null;
    for (const [name, { link }] of navItems) {
      const on = name === active;
      link.classList.toggle("is-active", on);
      if (on) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
  }

  function renderUser() {
    const user = state.user;
    if (state.authEnabled && user) {
      dom.avatar.textContent = initials(user.username);
      dom.userName.textContent = user.username;
      dom.userName.title = user.username;
      dom.userRole.textContent = user.role === "admin" ? "Quản trị viên" : "Thành viên";
      dom.logout.hidden = false;
    } else {
      dom.avatar.replaceChildren(icon("user", { size: 16 }));
      dom.userName.textContent = state.authEnabled ? "Chưa đăng nhập" : "Người dùng cục bộ";
      dom.userName.removeAttribute("title");
      dom.userRole.textContent = state.authEnabled ? "" : "Toàn quyền · chưa bật tài khoản";
      dom.logout.hidden = true;
    }
  }

  function syncThemeIcon() {
    const dark = document.documentElement.dataset.theme === "dark";
    const use = dom.themeBtn.querySelector("use");
    if (use) use.setAttribute("href", dark ? "#i-sun" : "#i-moon");
    dom.themeBtn.title = dark ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối";
    dom.themeBtn.setAttribute("aria-label", dom.themeBtn.title);
  }

  function toggleTheme() {
    prefs.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    safeSavePrefs();
    applyTheme();
  }

  function applySidebarPref() {
    dom.app.classList.toggle("sidebar-collapsed", prefs.sidebarOpen === false);
    syncToggleAria();
  }

  function setMobileSidebar(open) {
    const was = dom.app.classList.contains("sidebar-open-mobile");
    const on = Boolean(open) && mobileQuery.matches;
    dom.app.classList.toggle("sidebar-open-mobile", on);
    // Sidebar trượt vào che trang: phần sau lớp nền không Tab tới được.
    if (dom.main) dom.main.inert = on;
    syncToggleAria();
    if (open && !was && mobileQuery.matches) {
      const target = dom.nav.querySelector(".nav-item.is-active") || dom.nav.querySelector(".nav-item");
      if (target) target.focus({ preventScroll: true });
    }
  }

  function toggleSidebar() {
    if (mobileQuery.matches) {
      setMobileSidebar(!dom.app.classList.contains("sidebar-open-mobile"));
      return;
    }
    prefs.sidebarOpen = prefs.sidebarOpen === false;
    safeSavePrefs();
    applySidebarPref();
  }

  function syncToggleAria() {
    const expanded = mobileQuery.matches ? dom.app.classList.contains("sidebar-open-mobile") : prefs.sidebarOpen !== false;
    dom.toggle.setAttribute("aria-expanded", String(expanded));
  }

  /* ── /health ─────────────────────────────────────────────────── */
  async function pollHealth() {
    if (state.healthBusy) return;
    state.healthBusy = true;
    let health;
    try {
      const data = await sendJson("/health", { signal: timeoutSignal(10000) });
      health = { ...data, status: data && data.status === "ok" ? "ok" : "degraded" };
    } catch (error) {
      health = { status: "down", error: (error && error.message) || "Mất kết nối backend" };
    } finally {
      state.healthBusy = false;
    }
    state.health = health;
    renderHealth();
    for (const fn of [...state.healthSubs]) {
      try { fn(health); } catch (error) { console.error("[shell] onHealth", error); }
    }
  }

  function renderHealth() {
    const health = state.health;
    let dot = "unknown";
    let text = "Đang kiểm tra…";
    let title = "";
    if (health && health.status === "ok") {
      dot = "ok";
      text = "Hệ thống sẵn sàng";
    } else if (health && health.status === "down") {
      dot = "down";
      text = "Mất kết nối backend";
      title = health.error || "";
    } else if (health) {
      dot = "degraded";
      const bad = CORE_HEALTH_KEYS.filter((key) => key in health && health[key] !== "ok");
      text = bad.length ? `Suy giảm: ${bad.join(", ")}` : "Suy giảm một phần";
    }
    if (health && health.status !== "down") {
      const issues = Object.entries(health)
        .filter(([key, value]) => !NOT_STATUS_KEYS.has(key) && typeof value === "string" && value !== "ok" && value !== "disabled")
        .map(([key, value]) => `${key}: ${value}`);
      title = issues.length ? `Chưa ổn: ${issues.join(" · ")}` : "Mọi thành phần đang chạy đều ổn";
    }
    dom.healthDot.dataset.state = dot;
    dom.healthText.textContent = text;
    if (title) dom.healthStatus.title = title;
    else dom.healthStatus.removeAttribute("title");
  }

  function onHealth(fn, { signal } = {}) {
    if (typeof fn !== "function") return () => {};
    state.healthSubs.add(fn);
    const off = () => state.healthSubs.delete(fn);
    if (signal) {
      if (signal.aborted) { off(); return off; }
      signal.addEventListener("abort", off, { once: true });
    }
    if (state.health) queueMicrotask(() => { if (state.healthSubs.has(fn)) fn(state.health); });
    return off;
  }

  /* ── badge Ghi nhớ (admin) ───────────────────────────────────── */
  /* Hợp đồng F8: GET /api/memory-review/count → {pending}. Máy chủ chưa có (404 trơn) → đếm trang
     đầu candidates?limit=100 như app cũ, và từ đó không hỏi /count nữa. */
  async function refreshMemoryBadge() {
    if (!isAdmin() || state.loginVisible) { setNavBadge("memory", 0); return; }
    if (!state.countMissing) {
      try {
        const data = await api("/api/memory-review/count");
        const n = Number(data && data.pending);
        setNavBadge("memory", Number.isFinite(n) ? n : 0);
        return;
      } catch (error) {
        if (!isMissingApi(error)) { setNavBadge("memory", 0); return; }
        state.countMissing = true;
      }
    }
    try {
      const rows = await api("/api/memory-review/candidates?limit=100");
      setNavBadge("memory", Array.isArray(rows) ? rows.length : 0);
    } catch {
      setNavBadge("memory", 0);
    }
  }

  /* ── thông báo (hợp đồng F4) ─────────────────────────────────── */
  function refreshNotifications() {
    if (state.loginVisible) return Promise.resolve(state.notif);
    if (state.notifBusy) return state.notifBusy;
    state.notifAt = Date.now();
    state.notifBusy = (async () => {
      try {
        const data = await api("/notifications?unread=1");
        const items = Array.isArray(data && data.items) ? data.items : [];
        const count = Number(data && data.unread_count);
        state.notif = {
          status: "ok", items,
          unread: Number.isFinite(count) ? count : items.filter((item) => !item.read).length,
          error: null,
        };
      } catch (error) {
        if (isMissingApi(error)) state.notif = { status: "missing", items: [], unread: 0, error };
        else state.notif = { ...state.notif, status: state.notif.status === "ok" ? "ok" : "error", error };
      } finally {
        state.notifBusy = null;
      }
      renderBellDot();
      renderNotifList();
      return state.notif;
    })();
    return state.notifBusy;
  }

  function renderBellDot() {
    const show = state.notif.status === "ok" && state.notif.unread > 0;
    dom.bellDot.hidden = !show;
    dom.bell.setAttribute("aria-label", show ? `Thông báo (${state.notif.unread} chưa đọc)` : "Thông báo");
  }

  function notifIcon(item) {
    const kind = String(item.kind || "").toLowerCase();
    if (item.tone === "danger" || /fail|error|lỗi/.test(kind)) return "alert";
    if (kind.includes("memory")) return "bulb";
    if (kind.includes("bot")) return "bot";
    if (kind.includes("ocr")) return "ocr";
    if (kind.includes("user")) return "user";
    return item.tone === "accent" ? "bell" : "check";
  }

  /* Cột thời gian hẹp của dropdown (P:128): "vừa xong", "2 phút", "5 giờ", "1 ngày", rồi dd/mm/yyyy. */
  function notifTime(value) {
    const d = new Date(typeof value === "number" && Math.abs(value) < 1e12 ? value * 1000 : value);
    if (Number.isNaN(d.getTime())) return "";
    const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (sec < 60) return "vừa xong";
    if (sec < 3600) return `${Math.floor(sec / 60)} phút`;
    if (sec < 86400) return `${Math.floor(sec / 3600)} giờ`;
    if (sec < 7 * 86400) return `${Math.floor(sec / 86400)} ngày`;
    return fmtDate(d);
  }

  function openNotifLink(item) {
    const raw = String(item.link || "");
    const at = raw.indexOf("#/");
    if (at === -1) return false;
    if (typeof Router !== "undefined") Router.go(raw.slice(at));
    return true;
  }

  async function markRead(ids) {
    const body = ids && ids.length ? { ids } : {};
    await api("/notifications/read", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }

  function buildNotifPanel(close) {
    const markBtn = h("button", { type: "button", class: "btn-link" }, "Đánh dấu đã đọc");
    const list = h("div", { class: "notif-list" });
    markBtn.addEventListener("click", async () => {
      const ids = state.notif.items.filter((item) => !item.read && item.id != null).map((item) => item.id);
      markBtn.disabled = true;
      try {
        await markRead(ids);
        state.notif = { ...state.notif, items: state.notif.items.map((item) => ({ ...item, read: true })), unread: 0 };
        renderBellDot();
        renderNotifList();
      } catch (error) {
        if (isMissingApi(error)) {
          state.notif = { status: "missing", items: [], unread: 0, error };
          renderBellDot();
          renderNotifList();
        } else {
          markBtn.disabled = false;
          toast(error.message, "danger");
        }
      }
    });
    state.notifView = { list, markBtn, close };
    renderNotifList();
    return h("div", { class: "notif-panel", role: "region", "aria-label": "Thông báo" },
      h("div", { class: "dropdown-head" }, h("strong", null, "Thông báo"), markBtn), list);
  }

  function renderNotifList() {
    const view = state.notifView;
    if (!view) return;
    // Đã gắn vào panel nhưng không còn trong trang = dropdown đã đóng.
    if (view.list.parentNode && !view.list.isConnected) { state.notifView = null; return; }
    const { status, items, error } = state.notif;
    const { list, markBtn, close } = view;
    markBtn.hidden = status === "missing";
    markBtn.disabled = !items.some((item) => !item.read);
    if (status === "missing") {
      list.replaceChildren(h("div", { class: "notif-empty" },
        h("div", { class: "notif-empty-title" }, "Chưa có thông báo"),
        h("div", { class: "notif-empty-sub" }, "Máy chủ chưa hỗ trợ thông báo · ", h("span", { class: "mono" }, "GET /notifications"))));
      return;
    }
    if (status === "idle") {
      list.replaceChildren(...[0, 1].map(() => h("div", { class: "notif-skeleton" },
        skeleton({ w: 30, h: 30, r: 9 }),
        h("div", { style: { flex: "1", display: "flex", flexDirection: "column", gap: "6px", paddingTop: "3px" } },
          skeleton({ w: "75%", h: 11 }), skeleton({ w: "45%", h: 10 })))));
      return;
    }
    if (!items.length) {
      list.replaceChildren(h("div", { class: "notif-empty" },
        h("div", { class: "notif-empty-title" }, status === "error" ? "Không tải được thông báo" : "Không có thông báo mới"),
        status === "error" && error ? h("div", { class: "notif-empty-sub" }, error.message) : null));
      return;
    }
    list.replaceChildren(...items.map((item) => {
      const tone = ["ok", "accent", "danger", "muted"].includes(item.tone) ? item.tone : "muted";
      const hasLink = String(item.link || "").includes("#/");
      const row = h("div", {
        class: ["notif", !item.read && "is-unread", hasLink && "is-link"],
        role: hasLink ? "link" : null, tabindex: hasLink ? "0" : null,
      },
      h("span", { class: ["icon-tile", `tone-${tone}`] }, icon(notifIcon(item), { size: 15 })),
      h("div", { class: "notif-body" },
        h("div", { class: "notif-title" }, item.title || "Thông báo"),
        item.detail ? h("div", { class: "notif-sub" }, item.detail) : null),
      h("span", { class: "notif-time" }, item.created_at ? notifTime(item.created_at) : ""));
      if (hasLink) {
        const activate = () => {
          close();
          openNotifLink(item);
          if (!item.read && item.id != null) {
            markRead([item.id]).then(() => refreshNotifications(), () => {});
          }
        };
        row.addEventListener("click", activate);
        row.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); }
        });
      }
      return row;
    }));
  }

  function toggleBell() {
    const handle = dropdown(dom.bell, (close) => buildNotifPanel(close), { width: 360, offset: 8, align: "end", className: "notif-menu" });
    if (handle.el) refreshNotifications();
    else state.notifView = null;
  }

  /* ── đăng nhập ───────────────────────────────────────────────── */
  function fetchMe() {
    return sendJson("/auth/me", { signal: timeoutSignal(8000) });
  }

  async function resolveUser() {
    state.meError = null;
    if (readToken("lac.access")) {
      try { return await fetchMe(); } catch (error) { state.meError = error; }
    }
    const refreshed = await refreshSoon();
    if (refreshed) {
      try { return await fetchMe(); } catch (error) { state.meError = error; }
    }
    return null;
  }

  function friendlyAuthError(error) {
    if (!error) return "Đăng nhập thất bại.";
    if (error.code === "INVALID_INPUT" && /Request input is invalid/.test(error.message)) {
      return "Tên đăng nhập hoặc mật khẩu không hợp lệ.";
    }
    return error.message || "Đăng nhập thất bại.";
  }

  /* rebuild=false (401 từ api/fetchBlob): màn đăng nhập đang mở thì giữ nguyên — không dựng lại
     form (không xóa chữ đang gõ) và không ghi đè dòng lỗi (form sau khi đăng xuất chủ động không
     được hiện "hết hạn"; lỗi "sai mật khẩu" vừa hiện không bị che).
     App đang chạy → Router.pause(): view giữ nguyên (không mất chữ đang gõ) nhưng không poll, không
     định tuyến sau lưng form (Back/Forward trên màn đăng nhập không mount view, không bắn toast). */
  function showLogin({ message = "", rebuild = true } = {}) {
    if (!rebuild && state.loginVisible && dom.loginRoot.firstChild) return;
    if (dropdown.open) dropdown.open.close();
    setMobileSidebar(false);
    if (state.started && typeof Router !== "undefined") Router.pause();
    document.title = LOGIN_TITLE;
    const bootstrap = !state.hasUsers;
    const keyHint = Boolean(getApiKey()) && state.meError && state.meError.code === "AUTH_REQUIRED";
    state.loginVisible = true;

    const username = h("input", {
      class: "input input-42", name: "username", placeholder: "dung.bt", autocomplete: "username",
      autocapitalize: "none", spellcheck: "false", required: true, maxlength: 64,
    });
    const password = h("input", {
      class: "input input-42", name: "password", type: "password", placeholder: "Tối thiểu 8 ký tự",
      autocomplete: bootstrap ? "new-password" : "current-password", required: true, minlength: 8, maxlength: 128,
    });
    const submit = h("button", { type: "submit", class: "btn btn-44 btn-block btn-primary btn-lift btn-glow-lg" },
      bootstrap ? "Tạo tài khoản" : "Đăng nhập");
    const errorLine = h("p", { class: "login-error", role: "alert", hidden: !message }, message);
    const hint = keyHint ? h("div", { class: "note tone-warn login-hint" },
      h("span", null, "Trình duyệt này đang lưu một khóa truy cập (X-API-Key). Khi bật tài khoản, máy chủ ưu tiên khóa đó nên không nhận ra tài khoản của bạn — xóa khóa rồi đăng nhập lại."),
      h("button", { type: "button", class: "btn btn-32 btn-outline", onClick: clearSavedKey },
        icon("key", { size: 14 }), "Xóa khóa truy cập đã lưu")) : null;

    const form = h("form", { class: "login-card", "aria-labelledby": "login-title" },
      h("div", { class: "login-brand" },
        h("span", { class: "logo logo-40" }, icon("spark", { size: 20, sw: 1.9 })),
        h("div", null,
          h("div", { class: "login-brand-name" }, "Local AI Core"),
          h("div", { class: "login-brand-sub" }, "Trợ lý AI cục bộ · nhóm LAN"))),
      h("div", null,
        h("h1", { id: "login-title" }, bootstrap ? "Tạo tài khoản quản trị" : "Đăng nhập"),
        h("p", { class: "login-lead" }, bootstrap
          ? "Hệ thống chưa có tài khoản nào — tài khoản đầu tiên sẽ là quản trị viên."
          : "Dùng tài khoản do quản trị viên cấp.")),
      hint,
      h("label", { class: "field" }, "Tên đăng nhập", username),
      h("label", { class: "field" }, "Mật khẩu", password),
      submit,
      errorLine,
      h("p", { class: "login-privacy" }, "Toàn bộ dữ liệu nằm trên máy chủ nội bộ. Không có gì được gửi ra ngoài."));

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      errorLine.hidden = true;
      try {
        const data = await sendJson(bootstrap ? "/auth/register" : "/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: username.value.trim(), password: password.value }),
        });
        localStorage.setItem("lac.access", data.access_token);
        localStorage.setItem("lac.refresh", data.refresh_token);
        if (bootstrap) state.hasUsers = true;
        await afterLogin(data.user);
      } catch (error) {
        if (bootstrap && error && error.code === "REGISTRATION_CLOSED") {
          // Ai đó vừa tạo quản trị viên đầu tiên: chuyển sang form đăng nhập thay vì kẹt ở form tạo.
          state.hasUsers = true;
          showLogin({ message: "Hệ thống đã có tài khoản quản trị — đăng nhập bằng tài khoản được cấp." });
          return;
        }
        errorLine.textContent = friendlyAuthError(error);
        errorLine.hidden = false;
        submit.disabled = false;
        password.select();
      }
    });

    dom.loginRoot.replaceChildren(form);
    dom.loginRoot.hidden = false;
    dom.app.hidden = true;
    username.focus({ preventScroll: true });
  }

  function hideLogin() {
    state.loginVisible = false;
    dom.loginRoot.hidden = true;
    dom.loginRoot.replaceChildren();
    dom.app.hidden = false;
    const title = dom.title.textContent;
    document.title = title ? `${title} — Local AI Core` : DEFAULT_TITLE;
  }

  /* verified=true: loginUser vừa lấy từ /auth/me (resolveUser) — không hỏi lại lần hai. */
  async function afterLogin(loginUser, { verified = false } = {}) {
    let me = verified && loginUser ? loginUser : null;
    state.meError = null;
    if (!me) {
      try { me = await fetchMe(); } catch (error) { state.meError = error; }
    }
    if (!me) {
      if (getApiKey() && state.meError && state.meError.code === "AUTH_REQUIRED") {
        showLogin({ message: "Mật khẩu đúng, nhưng máy chủ vẫn nhận khóa truy cập đã lưu thay cho tài khoản của bạn." });
        return;
      }
      me = loginUser || null;
    }
    if (!me) {
      showLogin({ message: "Không đọc được thông tin tài khoản. Thử lại." });
      return;
    }
    const previousId = state.lastUserId;
    const previousRole = state.user ? state.user.role : null;
    state.user = me;
    state.lastUserId = me.id;
    if (!state.started) {
      hideLogin();
      startApp();
      return;
    }
    if (!previousId || previousId !== me.id) {
      // Tài khoản khác với phiên đang mở: nạp lại để không lẫn dữ liệu của người trước.
      location.reload();
      return;
    }
    hideLogin();
    renderUser();
    renderNav();
    refreshNotifications();
    refreshMemoryBadge();
    // Chạy tiếp view đã dừng; đổi vai trò (hoặc view đã bị gỡ khi đăng xuất) → mount lại.
    if (typeof Router !== "undefined") Router.resume({ force: previousRole !== me.role });
  }

  async function clearSavedKey(event) {
    const button = event && event.currentTarget instanceof HTMLButtonElement ? event.currentTarget : null;
    if (button) button.disabled = true;
    setApiKey("");
    state.meError = null;
    const user = await resolveUser();
    if (user) {
      toast("Đã xóa khóa truy cập.");
      await afterLogin(user, { verified: true });
      return;
    }
    toast("Đã xóa khóa truy cập. Đăng nhập lại để tiếp tục.");
    showLogin();
  }

  /* Đăng xuất chủ động: xóa token, gỡ view đang mở (không còn poll sau lưng form), hiện form
     sạch NGAY, rồi mới báo máy chủ thu hồi refresh token (tối đa 5 giây; lỗi vẫn coi là đã đăng xuất).
     /auth/logout chỉ cần refresh token trong body, không cần Bearer. */
  async function logout() {
    if (state.loggingOut) return;
    const refresh = readToken("lac.refresh");
    try {
      localStorage.removeItem("lac.access");
      localStorage.removeItem("lac.refresh");
    } catch { /* ignore */ }
    if (state.user) state.lastUserId = state.user.id;
    state.user = null;
    state.meError = null;
    if (state.authEnabled) {
      if (state.started && typeof Router !== "undefined") Router.pause({ unmount: true });
      renderUser();
      showLogin();
    }
    if (!refresh) return;
    state.loggingOut = true;
    try {
      await sendJson("/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
        signal: timeoutSignal(5000),
      });
    } catch { /* đăng xuất cục bộ vẫn tiếp tục */ } finally {
      state.loggingOut = false;
    }
  }

  /* ── vòng đời ────────────────────────────────────────────────── */
  function tick() {
    state.lastTick = Date.now();
    pollHealth();
    if (state.configUnknown && !state.authEnabled) recheckAuthMode();
    if (!state.loginVisible) {
      // /notifications chưa có trên máy chủ (404 trơn): hỏi lại mỗi 10 phút thay vì mỗi phút.
      if (state.notif.status !== "missing" || Date.now() - state.notifAt >= MISSING_POLL_MS) refreshNotifications();
      refreshMemoryBadge();
    }
  }

  function startApp() {
    if (state.started) return;
    state.started = true;
    hideLogin();
    renderUser();
    renderNav();
    tick();
    setInterval(() => { if (!document.hidden) tick(); }, POLL_MS);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && Date.now() - state.lastTick >= POLL_MS) tick();
    });
    Router.start();
  }

  function cacheDom() {
    Object.assign(dom, {
      app: $("app"), main: $("main"), sidebar: $("sidebar"), nav: $("nav"), panel: $("sidebar-panel"), spacer: $("sidebar-spacer"),
      backdrop: $("sidebar-backdrop"), avatar: $("user-avatar"), userName: $("user-name"), userRole: $("user-role"),
      themeBtn: $("theme-toggle"), logout: $("logout-btn"), toggle: $("sidebar-toggle"), title: $("header-title"),
      sub: $("header-sub"), actions: $("header-actions"), bell: $("bell-btn"), bellDot: $("bell-dot"),
      healthStatus: $("health-status"), healthDot: $("health-dot"), healthText: $("health-text"), loginRoot: $("login-root"),
    });
  }

  function bindChrome() {
    dom.toggle.addEventListener("click", toggleSidebar);
    dom.backdrop.addEventListener("click", () => setMobileSidebar(false));
    dom.themeBtn.addEventListener("click", toggleTheme);
    dom.logout.addEventListener("click", () => { logout(); });
    dom.bell.addEventListener("click", toggleBell);
    new MutationObserver(syncThemeIcon).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    mobileQuery.addEventListener("change", () => setMobileSidebar(false));
    window.addEventListener("lac:route", () => {
      syncActiveNav();
      setMobileSidebar(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !event.defaultPrevented && dom.app.classList.contains("sidebar-open-mobile")) {
        event.preventDefault();
        setMobileSidebar(false);
        dom.toggle.focus({ preventScroll: true });
      }
    });
    // Đăng nhập / đăng xuất ở thẻ khác (localStorage dùng chung): thẻ này không được hiện người A
    // trong khi mọi request đã mang token của người B.
    const onTokensChanged = debounce(() => {
      if (!state.authEnabled || (!state.started && !state.loginVisible)) return;
      if (!readToken("lac.access") && !readToken("lac.refresh")) {
        if (!state.loginVisible) showLogin({ message: "Bạn đã đăng xuất ở một thẻ khác." });
        return;
      }
      fetchMe().then((me) => {
        if (!me || me.id == null) return;
        if (state.loginVisible) afterLogin(me, { verified: true });   // thẻ khác vừa đăng nhập
        else if (me.id !== state.lastUserId) location.reload();
      }, () => { /* token mới chưa dùng được: request kế tiếp tự xử lý 401 */ });
    }, 150);
    window.addEventListener("storage", (event) => {
      if (event.key === null || event.key === "lac.access" || event.key === "lac.refresh") onTokensChanged();
    });
  }

  async function boot() {
    const root = document.documentElement;
    try {
      cacheDom();
      bindChrome();
      applySidebarPref();
      syncThemeIcon();
      let config = null;
      const first = timeoutSignal(6000);
      try { config = await sendJson("/auth/config", { signal: first }); } catch { config = null; }
      if (!config && first && first.aborted) {
        // Chậm chứ không hỏng: hỏi lại một lần, chờ lâu hơn — đoán sai thành "tắt tài khoản" thì cả
        // phiên sai vai trò (thành viên thấy menu admin, 401 không dẫn tới màn đăng nhập).
        try { config = await sendJson("/auth/config", { signal: timeoutSignal(15000) }); } catch { config = null; }
      }
      // Vẫn không trả lời: chạy như tắt tài khoản (app cũ cũng vậy) nhưng tick() sẽ hỏi lại.
      state.configUnknown = !config;
      state.authEnabled = Boolean(config && config.enabled);
      state.hasUsers = !config || config.has_users !== false;
      renderUser();
      if (state.authEnabled) {
        const user = await resolveUser();
        if (!user) {
          showLogin();
          return;
        }
        state.user = user;
        state.lastUserId = user.id;
      }
      startApp();
    } catch (error) {
      console.error("[shell] khởi động lỗi", error);
      if (!state.started && !state.loginVisible) {
        if (state.authEnabled) showLogin({ message: "Không khởi động được giao diện. Tải lại trang để thử lại." });
        else startApp();
      }
    } finally {
      delete root.dataset.booting;
      document.getElementById("boot-fail")?.remove();   // thông báo của watchdog trong index.html (nếu đã hiện)
    }
  }

  let booted = false;
  const bootOnce = () => { if (!booted) { booted = true; boot(); } };
  if (document.readyState === "complete") bootOnce();
  else {
    document.addEventListener("DOMContentLoaded", bootOnce, { once: true });
    window.addEventListener("load", bootOnce, { once: true });
  }

  return {
    get user() { return state.user ? { ...state.user } : null; },
    get authEnabled() { return state.authEnabled; },
    isAdmin,
    setHeader,
    setHeaderActions,
    setSidebarPanel,
    setNavBadge,
    get health() { return state.health; },
    onHealth,
    refreshNotifications,
    logout,
    motionOn,
    api,
    fetchBlob,
    _beginMount: beginMount,
    _endMount: endMount,
  };
})();
