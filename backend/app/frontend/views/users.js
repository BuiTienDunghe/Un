/* ══════════════════════════════════════════════════════════════════
   /ui/views/users.js — màn hình "Người dùng" (#/users, chỉ quản trị
   viên — router tự chặn thành viên).

   Một IIFE, không tên top-level. Gồm:
     - chế độ TẮT TÀI KHOẢN (máy thật hôm nay): GET /auth/users trả 409
       AUTH_DISABLED → card nói thẳng máy chủ đang chạy một người dùng,
       kèm 2 card mô tả quyền ở dưới;
     - chế độ BẬT TÀI KHOẢN: thanh công cụ (ô tìm lọc theo tên đăng nhập,
       "N tài khoản · k quản trị viên", nút "Thêm người dùng"), bảng tài
       khoản, và 2 card mô tả quyền.

   Hợp đồng API: research/api-core.md §2.
     GET  /auth/users            → [{id, username, role, created_at,
                                     last_login_at, disabled?}] theo created_at tăng dần
     POST /auth/users            {username, password, role} → 201 | 409 USERNAME_TAKEN
                                 | 422 INVALID_INPUT
     PATCH /auth/users/{id}      backend hôm nay CHỈ nhận {role} (thiếu role → 422);
                                 spec F5 thêm {password} và {disabled}.
   Vì vậy: KHÔNG BAO GIỜ gửi role chung một body với password/disabled — gửi
   kèm role sẽ vừa đổi vai trò vừa làm việc khác, còn gửi riêng thì backend cũ
   trả 422 và UI nói thật là "chưa hỗ trợ" (isUnsupportedField).

   Dữ liệu không có: API không có tên hiển thị (chỉ username), không có cột
   quyền chi tiết. Tên hàng = username; cột "Quyền" là mô tả cố định theo vai
   trò. Trường `disabled` chỉ có khi máy chủ đã hỗ trợ F5.

   Gọi mạng: chỉ Shell.api. V là DOM + dữ liệu của lần mount đang sống, null
   khi đã rời view — mọi việc bất đồng bộ kiểm tra live(v) trước khi vẽ.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  const JSON_HEADERS = { "Content-Type": "application/json" };

  /* Quy tắc tên đăng nhập của backend (services/auth_service.py:31):
     chuẩn hóa strip().lower() rồi khớp ^[a-z0-9][a-z0-9_.-]{2,63}$. */
  const USERNAME_RE = /^[a-z0-9][a-z0-9_.-]{2,63}$/;
  const NAME_HINT = "3–64 ký tự: chữ thường, số và . _ - ; ký tự đầu phải là chữ hoặc số. Chữ hoa tự chuyển thành chữ thường.";
  const PASSWORD_HINT = "Tối thiểu 8 ký tự.";

  const MISSING_PASSWORD = "Máy chủ chưa hỗ trợ đặt lại mật khẩu.";
  const MISSING_LOCK = "Máy chủ chưa hỗ trợ khóa tài khoản.";

  /* Câu 422 chung của pydantic (app/main.py): backend chưa biết khóa vừa gửi.
     Backend đã hỗ trợ khóa đó chỉ trả 422 khi GIÁ TRỊ sai, kèm câu tiếng Việt
     cụ thể — câu ấy phải được giữ nguyên chứ không nói nhầm là "chưa hỗ trợ". */
  const GENERIC_422 = "request input is invalid";

  const ROLE_CARDS = [
    {
      title: "Quản trị viên",
      text: "Toàn quyền: tải/xóa tài liệu, duyệt ghi nhớ, điều khiển bot, đổi phiên bản model, quản lý tài khoản, xem chỉ số hệ thống.",
    },
    {
      title: "Thành viên",
      text: "Chat, hỏi đáp tài liệu, tải tài liệu lên, xem ghi nhớ của mình và bảng điều khiển ở chế độ chỉ đọc. Không xóa tài liệu chung, không đổi cấu hình.",
    },
  ];

  const OFF_TEXT = "Máy chủ đang chạy chế độ một người dùng: ai mở được trang này đều có toàn quyền. "
    + "Đặt LOCAL_AI_AUTH_ENABLED=true trong .env rồi khởi động lại backend để quản lý tài khoản.";

  let V = null;

  /* ── tiện ích ────────────────────────────────────────────────── */

  const isAbort = (error) => Boolean(error) && error.name === "AbortError";
  const live = (v) => Boolean(v) && V === v && !v.ctx.signal.aborted;

  const isAdminRole = (user) => Boolean(user) && user.role === "admin";
  const isLocked = (user) => Boolean(user) && user.disabled === true;

  /* Hàng của chính người đang đăng nhập (tắt tài khoản thì Shell.user là null). */
  function isSelf(user) {
    const me = Shell.user;
    return Boolean(me) && Boolean(user) && me.id === user.id;
  }

  /* 409 AUTH_DISABLED: máy chủ tắt chế độ tài khoản (không phải lỗi). */
  const isAuthOff = (error) => Boolean(error) && error.code === "AUTH_DISABLED";

  /* 401 cuối cùng (refresh cũng hỏng): Shell đã hiện màn đăng nhập. View phải im
     lặng — thêm toast hay khung lỗi ở đây chỉ nằm đè lên màn đăng nhập và nhắc lại
     đúng câu màn đó đã nói. Router.pause() KHÔNG gỡ view nên live(v) vẫn true. */
  const isExpired = (error) => Boolean(error) && error.status === 401 && Shell.authEnabled;

  /* …nhưng phải nhớ là mình đang cầm dữ liệu dở dang: Router.resume() sau khi đăng nhập
     lại KHÔNG mount lại view khi vai trò không đổi (shell.js:718), nên nếu không tự đọc
     lại thì màn hình nằm im ở khung xương cũ. Đồng hồ ctx.every không tick lúc đang dừng,
     nên cờ này chỉ được xử lý sau khi đăng nhập xong. */
  function expired(v, error) {
    if (!isExpired(error)) return false;
    v.needsReload = true;
    return true;
  }

  /* Lỗi 500 của backend trả câu tiếng Anh "An unexpected server error occurred"
     (main.py) và bảng ERROR_HINTS chưa có INTERNAL_ERROR, nên câu ấy lọt thẳng ra
     màn hình. Nói lại bằng tiếng Việt cho tới khi bảng chung có mục này. */
  function errText(error, fallback) {
    if (error && error.code === "INTERNAL_ERROR") return "Máy chủ gặp lỗi nội bộ. Xem log backend rồi thử lại.";
    return (error && error.message) || fallback;
  }

  /* errorState() đọc error.message — bọc lại lỗi khi câu của máy chủ không dùng được. */
  function viewError(error, fallback) {
    const text = errText(error, fallback);
    if (error && text === error.message) return error;
    const wrapped = new Error(text);
    if (error) { wrapped.code = error.code; wrapped.status = error.status; }
    return wrapped;
  }

  /* 422 trên PATCH: khóa vừa gửi backend chưa biết → câu "chưa hỗ trợ";
     còn nếu máy chủ trả câu cụ thể thì hiện đúng câu của máy chủ. */
  function fieldMessage(error, missingText, fallback) {
    const message = String((error && error.message) || "").trim();
    if (!isUnsupportedField(error)) return message || fallback;
    return !message || message.toLowerCase() === GENERIC_422 ? missingText : message;
  }

  /* ── nội dung từng ô ─────────────────────────────────────────── */

  /* Cột "Quyền": API không có quyền chi tiết, chỉ có vai trò — mô tả theo vai trò. */
  function permsText(user) {
    return isAdminRole(user) ? "Toàn quyền" : "Chat · tải tài liệu";
  }

  /* Cột "Hoạt động": chính mình thì đang mở trang này; còn lại đọc last_login_at. */
  function activityText(user) {
    if (isSelf(user)) return "đang online";
    if (!user.last_login_at) return "chưa đăng nhập";
    return fmtRelative(user.last_login_at);
  }

  /* ── dựng bảng ───────────────────────────────────────────────── */

  function userCell(user) {
    const color = avatarColor(user.username);
    const locked = isLocked(user);
    const admin = isAdminRole(user);
    // Quản trị viên: nền accent chữ trắng. Đã khóa: xám hẳn (như prototype).
    // Còn lại: màu cố định theo tên đăng nhập.
    const style = admin || locked ? null : { background: color.bg, color: color.color };
    return h("div", { class: "usr-user" },
      h("span", { class: ["avatar", "usr-avatar", admin && "is-admin", locked && "is-off"], style, "aria-hidden": "true" },
        initials(user.username)),
      h("div", { class: "usr-user-main" },
        h("div", { class: "usr-name", title: user.username }, user.username),
        // "@tên" tách riêng: trên màn rất hẹp nó bị giấu (nhắc lại đúng dòng ngay trên),
        // còn ngày tạo — thông tin duy nhất không có ở chỗ khác — vẫn còn.
        h("div", { class: "usr-meta" },
          h("span", { class: "usr-at" }, `@${user.username} · `),
          `tạo ${fmtDate(user.created_at)}`)));
  }

  function roleCell(user) {
    return isAdminRole(user)
      ? pill("Quản trị viên", "accent", { dot: false, size: "sm", bold: true })
      : pill("Thành viên", "muted", { dot: false, size: "sm", bold: true });
  }

  /* Cột "Trạng thái": chỉ đọc được khi máy chủ trả `disabled` (F5).
     Chưa có trường đó thì mọi tài khoản đều mở — nói rõ trong tooltip. */
  function statusCell(user, knowsLock) {
    const locked = isLocked(user);
    return h("span", {
      class: ["status-text", "usr-status", locked ? "is-off" : "is-ok"],
      title: knowsLock ? null : "Máy chủ này chưa hỗ trợ khóa tài khoản, nên mọi tài khoản đều đang mở.",
    }, locked ? "Đã khóa" : "Hoạt động");
  }

  function buildRow(v, user, knowsLock) {
    const menuBtn = h("button", {
      type: "button", class: "icon-btn icon-btn-28 row-act usr-more",
      "aria-haspopup": "menu", "aria-label": `Tùy chọn cho ${user.username}`,
      // dropdown() chỉ đặt aria-expanded từ lần mở đầu tiên trở đi; khai sẵn "false"
      // để trình đọc màn hình nói "thu gọn" ngay từ lần vẽ đầu.
      "aria-expanded": "false",
      title: "Tùy chọn",
      onClick: (event) => openMenu(v, user, event.currentTarget, knowsLock),
    }, icon("dots", { size: 16, sw: 2.6 }));

    return h("tr", null,
      h("td", null, userCell(user)),
      h("td", null, roleCell(user)),
      h("td", { class: "usr-perms" }, permsText(user)),
      h("td", { class: "usr-activity" }, activityText(user)),
      h("td", null, statusCell(user, knowsLock)),
      h("td", { class: "usr-act-cell" }, Shell.isAdmin() ? menuBtn : null));
  }

  function tableShell(body) {
    const head = h("thead", { class: "usr-thead" }, h("tr", null,
      h("th", { scope: "col" }, "Người dùng"),
      h("th", { scope: "col" }, "Vai trò"),
      h("th", { scope: "col", class: "usr-col-perms" }, "Quyền"),
      h("th", { scope: "col", class: "usr-col-activity" }, "Hoạt động"),
      h("th", { scope: "col" }, "Trạng thái"),
      h("th", { class: "col-act", "aria-label": "Tùy chọn" })));
    return h("div", { class: "card card-flush" },
      // Màn hẹp: bảng cuộn ngang bên trong card. Vùng cuộn phải tự nhận focus
      // (tabindex) thì người chỉ dùng bàn phím mới cuộn tới 2 cột cuối được.
      h("div", { class: "usr-table-wrap", tabindex: "0", role: "group", "aria-label": "Bảng tài khoản" },
        h("table", { class: "table table-inset table-roomy usr-table" }, head, body)));
  }

  function skelRow() {
    const cell = (node) => h("td", null, node);
    return h("tr", { "aria-hidden": "true" },
      cell(h("div", { class: "usr-user" }, skeleton({ w: 32, h: 32, r: 16 }),
        h("div", { class: "usr-user-main usr-skel-lines" }, skeleton({ w: 96, h: 12 }), skeleton({ w: 148, h: 10 })))),
      cell(skeleton({ w: 82, h: 22, r: 11 })),
      // Cùng lớp với hàng thật để màn hẹp giấu đúng những cột ấy (users.css @600).
      h("td", { class: "usr-perms" }, skeleton({ w: 104, h: 12 })),
      h("td", { class: "usr-activity" }, skeleton({ w: 72, h: 12 })),
      cell(skeleton({ w: 80, h: 12 })),
      h("td", { class: "usr-act-cell" }));
  }

  /* ── vẽ ──────────────────────────────────────────────────────── */

  function matches(user, needle) {
    return !needle || String(user.username || "").toLowerCase().includes(needle);
  }

  /* Câu đếm luôn nói về CẢ danh sách ("N tài khoản · k quản trị viên", đúng
     README/P:540). Trước đây khi đang lọc nó đổi thành "<hiện>/<tổng>", tức là hai
     con số đếm hai tập khác nhau trong cùng một câu; bảng bên dưới đã cho thấy kết
     quả lọc rồi. Nhờ vậy vùng role="status" cũng không bị đọc lại sau mỗi phím. */
  function paintCount(v) {
    const users = v.users || [];
    const admins = users.filter(isAdminRole).length;
    v.count.textContent = `${users.length} tài khoản · ${admins} quản trị viên`;
  }

  function paintRows(v) {
    const users = v.users || [];
    const needle = v.search.trim().toLowerCase();
    const shown = users.filter((user) => matches(user, needle));
    // `disabled` chỉ xuất hiện khi máy chủ đã hỗ trợ F5 — dùng để nói thật ở cột Trạng thái.
    const knowsLock = users.some((user) => typeof user.disabled === "boolean");
    const head = v.body.querySelector(".usr-thead");
    paintCount(v);

    if (!shown.length) {
      const empty = users.length
        ? emptyState({ icon: "search", title: "Không có tài khoản nào khớp", text: `Không tìm thấy tên đăng nhập chứa «${v.search.trim()}».` })
        : emptyState({ icon: "users", title: "Chưa có tài khoản nào", text: "Bấm «Thêm người dùng» để tạo tài khoản đầu tiên." });
      // Giấu hàng tiêu đề: nó không còn gì để đặt tên, và một ô colspan=6 làm bảng
      // tự chia lại cột nên các tiêu đề nhảy chỗ so với lúc có dữ liệu.
      if (head) head.hidden = true;
      v.tbody.replaceChildren(h("tr", null, h("td", { colspan: "6", class: "usr-empty-cell" }, empty)));
      return;
    }
    if (head) head.hidden = false;
    v.tbody.replaceChildren(...shown.map((user) => buildRow(v, user, knowsLock)));
  }

  /* Khối 2 card mô tả quyền — có ở CẢ hai chế độ (bật và tắt tài khoản). */
  function roleCards() {
    return h("div", { class: "usr-roles" }, ROLE_CARDS.map((item) => h("section", { class: "card card-p" },
      h("strong", { class: "usr-role-title" }, item.title),
      h("p", { class: "usr-role-text" }, item.text))));
  }

  /* Chế độ tắt tài khoản: không có gì để tìm hay thêm, nên giấu hẳn thanh công cụ. */
  function paintAuthOff(v) {
    v.ctx.setHeader("Người dùng & phân quyền", "Chưa bật tài khoản · một người dùng toàn quyền");
    v.toolbar.hidden = true;
    v.count.textContent = "";
    v.loaded = false;
    v.body.replaceChildren(
      h("div", { class: "card" }, emptyState({ icon: "users", title: "Chưa bật tài khoản", text: OFF_TEXT })),
      roleCards());
  }

  function paintUsers(v) {
    v.ctx.setHeader("Người dùng & phân quyền", "Tài khoản nội bộ · 2 vai trò");
    v.toolbar.hidden = false;
    // Lần vẽ đầu (hoặc sau khung xương / lỗi): dựng lại khung bảng quanh chính tbody này.
    if (!v.body.contains(v.tbody)) v.body.replaceChildren(tableShell(v.tbody), roleCards());
    paintRows(v);
  }

  /* ── tải dữ liệu ─────────────────────────────────────────────── */

  async function load(v, { first = false } = {}) {
    if (!live(v)) return;
    v.seq += 1;
    const my = v.seq;

    /* LUÔN hỏi máy chủ, kể cả khi Shell đang cho là tắt tài khoản: Shell.authEnabled
       cũng bằng false khi /auth/config không kịp trả lời lúc khởi động (configUnknown),
       và lúc đó câu "máy chủ đang chạy một người dùng" là một khẳng định chưa kiểm
       chứng. 409 AUTH_DISABLED bên dưới mới là bằng chứng; 401 thì Shell tự hỏi lại
       /auth/config. Chỉ bỏ khung xương, vì hầu như chắc chắn sẽ không có bảng. */
    const expectTable = Shell.authEnabled;
    if (first) {
      v.loaded = false;
      v.toolbar.hidden = !expectTable;
      v.count.textContent = expectTable ? "đang đọc danh sách…" : "";
      if (expectTable) {
        v.body.replaceChildren(tableShell(h("tbody", null, skelRow(), skelRow(), skelRow())), roleCards());
      } else {
        v.body.replaceChildren(roleCards());
      }
    }

    let data;
    try {
      data = await Shell.api("/auth/users", { signal: v.ctx.signal });
    } catch (error) {
      if (isAbort(error) || !live(v) || my !== v.seq) return;
      if (isAuthOff(error)) { paintAuthOff(v); return; }
      // Phiên hết hạn: màn đăng nhập đang che trang, đừng dựng khung lỗi sau lưng nó
      // với một nút "Thử lại" chắc chắn lại 401.
      if (expired(v, error)) return;
      v.toolbar.hidden = true;
      v.count.textContent = "";
      v.loaded = false;
      v.body.replaceChildren(
        h("div", { class: "card" },
          errorState(viewError(error, "Không tải được danh sách tài khoản."), () => load(v, { first: true }))),
        roleCards());
      return;
    }
    if (!live(v) || my !== v.seq) return;
    v.users = Array.isArray(data) ? data : [];
    v.loaded = true;
    paintUsers(v);
  }

  /* ── menu ⋯ của một hàng ─────────────────────────────────────── */

  /* Không bao giờ mời tự hạ quyền hay tự khóa: mất quyền giữa chừng là hỏng phiên
     làm việc, và người cuối cùng còn quyền quản trị thì backend cũng chặn (LAST_ADMIN). */
  function openMenu(v, user, anchor, knowsLock) {
    if (!live(v) || !Shell.isAdmin()) return;
    const self = isSelf(user);
    const admin = isAdminRole(user);
    const locked = isLocked(user);
    const items = [];

    if (!(self && admin)) {
      items.push({
        label: admin ? "Đổi thành Thành viên" : "Đổi thành Quản trị viên",
        icon: admin ? "user" : "shield",
        onSelect: () => changeRole(v, user, admin ? "member" : "admin"),
      });
    }
    /* Mật khẩu của CHÍNH MÌNH đi đường riêng: spec F5＋ là POST /auth/me/password
       (có bước nhập mật khẩu hiện tại) và màn Cài đặt đã cài đúng endpoint đó. Đặt
       lại qua PATCH /auth/users/{id} ở đây sẽ là hai hợp đồng cho cùng một việc và
       bỏ mất bước xác nhận, nên hàng của mình chỉ dẫn sang Cài đặt. */
    items.push(self
      ? { label: "Đổi mật khẩu của tôi…", icon: "key", onSelect: () => Router.go("#/settings") }
      : { label: "Đặt lại mật khẩu…", icon: "key", onSelect: () => resetPassword(v, user) });
    if (!self) {
      // Đã biết máy chủ không có trường `disabled` thì đừng mời bấm vào ngõ cụt:
      // mỗi lần bấm là một vòng mạng hỏng và một toast đỏ nói đúng câu ghi sẵn đây.
      items.push({
        label: locked ? "Mở khóa tài khoản" : "Khóa tài khoản",
        icon: locked ? "unlock" : "lock",
        tone: !locked && knowsLock ? "danger" : undefined,
        disabled: !knowsLock,
        hint: knowsLock ? undefined : "chưa hỗ trợ",
        onSelect: () => setLocked(v, user, !locked),
      });
    }
    // width cố định: 3 mục có độ dài rất khác nhau, để menu tự co thì nó nhảy mỗi lần mở.
    // Rộng hơn khi mục khóa mang chữ "chưa hỗ trợ", nếu không nhãn bị cắt cụt.
    dropdown(anchor, items, { align: "end", width: knowsLock ? 226 : 268 });
  }

  /* ── đổi vai trò (PATCH {role}) ──────────────────────────────── */

  /* Không hỏi xác nhận: README §8 và brief đều mô tả đây là một mục menu bấm phát
     gửi luôn, và đổi ngược lại cũng chỉ một lần bấm ở đúng menu đó. */
  async function changeRole(v, user, role) {
    if (!live(v)) return;
    const up = role === "admin";
    try {
      await Shell.api(`/auth/users/${encodeURIComponent(user.id)}`, {
        method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ role }), signal: v.ctx.signal,
      });
    } catch (error) {
      if (isAbort(error) || expired(v, error) || !live(v)) return;
      toast(error.code === "LAST_ADMIN"
        ? "Không thể hạ quyền quản trị viên cuối cùng."
        : errText(error, "Không đổi được vai trò."), "danger");
      return;
    }
    toast(up ? `${user.username} đã là quản trị viên.` : `${user.username} đã chuyển thành thành viên.`);
    load(v);
  }

  /* ── đặt lại mật khẩu (PATCH {password} — F5) ────────────────── */

  async function resetPassword(v, user) {
    if (!live(v)) return;
    const result = await dialog({
      tone: "accent", icon: "key", title: `Đặt lại mật khẩu cho ${user.username}`,
      body: "Máy chủ đặt mật khẩu mới cho tài khoản này; bạn phải báo lại cho người dùng qua kênh khác.",
      /* maxlength 128 = giới hạn của schema backend. Thiếu nó thì một mật khẩu dài
         hơn bị máy chủ trả 422 INVALID_INPUT với đúng câu pydantic chung, không phân
         biệt được với "máy chủ chưa biết khóa password" — và UI sẽ nói oan rằng máy
         chủ không hỗ trợ đặt lại mật khẩu. */
      fields: [{
        name: "password", label: "Mật khẩu mới", type: "password", required: true,
        minlength: 8, maxlength: 128, autocomplete: "new-password", hint: PASSWORD_HINT,
      }],
      confirmLabel: "Đặt lại mật khẩu", cancelLabel: "Hủy", signal: v.ctx.signal,
    });
    if (!result || !live(v)) return;
    // Độ dài đã được dialog kiểm (required + minlength) TRƯỚC khi đóng; kiểm lại ở đây
    // chỉ có thể báo bằng toast sau khi dialog biến mất, nên bỏ.
    const password = String(result.password || "");
    try {
      // CHỈ password: kèm role sẽ đổi luôn vai trò của người ta.
      await Shell.api(`/auth/users/${encodeURIComponent(user.id)}`, {
        method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ password }), signal: v.ctx.signal,
      });
    } catch (error) {
      if (isAbort(error) || expired(v, error) || !live(v)) return;
      toast(fieldMessage(error, MISSING_PASSWORD, "Không đặt lại được mật khẩu."), "danger");
      return;
    }
    toast(`Đã đặt mật khẩu mới cho ${user.username}.`);
    load(v);
  }

  /* ── khóa / mở khóa (PATCH {disabled} — F5) ──────────────────── */

  async function setLocked(v, user, locked) {
    if (!live(v)) return;
    if (locked) {
      const ok = await confirmDialog({
        title: `Khóa tài khoản ${user.username}?`,
        body: "Tài khoản bị khóa không đăng nhập được nữa. Dữ liệu và hội thoại vẫn giữ nguyên; mở khóa lại lúc nào cũng được.",
        confirmLabel: "Khóa tài khoản", tone: "danger", icon: "lock", signal: v.ctx.signal,
      });
      if (!ok || !live(v)) return;
    }
    try {
      await Shell.api(`/auth/users/${encodeURIComponent(user.id)}`, {
        method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ disabled: locked }), signal: v.ctx.signal,
      });
    } catch (error) {
      if (isAbort(error) || expired(v, error) || !live(v)) return;
      toast(error.code === "LAST_ADMIN"
        ? "Không thể khóa quản trị viên cuối cùng."
        : fieldMessage(error, MISSING_LOCK, locked ? "Không khóa được tài khoản." : "Không mở khóa được tài khoản."), "danger");
      return;
    }
    toast(locked ? `Đã khóa ${user.username}.` : `Đã mở khóa ${user.username}.`);
    load(v);
  }

  /* ── thêm người dùng (POST /auth/users) ──────────────────────── */

  async function addUser(v) {
    if (!live(v) || !Shell.isAdmin() || v.adding) return;
    // Lớp phủ dialog đã đặt inert lên #app nên chuột/bàn phím thật không bấm lại được
    // nút này; cờ để một lời gọi bằng mã cũng không dựng được hai form giống hệt nhau.
    v.adding = true;
    let created = null;
    let result;
    try {
      result = await dialog({
        tone: "accent", icon: "user-plus", title: "Thêm người dùng",
        body: "Tài khoản mới đăng nhập được ngay bằng mật khẩu bạn đặt ở đây.",
        fields: [
          { name: "username", label: "Tên đăng nhập", placeholder: "vi-du.ten", required: true, maxlength: 64, hint: NAME_HINT },
          {
            name: "password", label: "Mật khẩu", type: "password", required: true,
            minlength: 8, maxlength: 128, autocomplete: "new-password", hint: PASSWORD_HINT,
          },
          {
            name: "role", label: "Vai trò", type: "select", value: "member",
            options: [{ value: "member", label: "Thành viên" }, { value: "admin", label: "Quản trị viên" }],
          },
        ],
        confirmLabel: "Tạo tài khoản", cancelLabel: "Hủy", signal: v.ctx.signal,
        /* Gửi ngay trong validate: lỗi của máy chủ (tên trùng, tên/mật khẩu sai quy tắc)
           hiện trong dialog, người dùng sửa tại chỗ thay vì gõ lại từ đầu. */
        validate: async (values) => {
          const username = String(values.username || "").trim().toLowerCase();
          const password = String(values.password || "");
          const role = values.role === "admin" ? "admin" : "member";
          // Câu quy tắc đã nằm ngay dưới ô nhập (hint) — nhắc lại ở dòng lỗi chỉ làm
          // dialog dài thêm hai dòng mà không nói thêm điều gì.
          if (!USERNAME_RE.test(username)) return "Tên đăng nhập không hợp lệ.";
          if ([...password].length < 8) return "Mật khẩu cần tối thiểu 8 ký tự.";
          try {
            created = await Shell.api("/auth/users", {
              method: "POST", headers: JSON_HEADERS,
              body: JSON.stringify({ username, password, role }), signal: v.ctx.signal,
            });
          } catch (error) {
            /* Rời màn hình, hoặc phiên hết hạn (Shell vừa dựng màn đăng nhập): trả null
               để dialog ĐÓNG. Giữ nó mở là tai hại — lớp phủ dialog đặt inert lên cả
               #login-root, nên người dùng không gõ lại được tài khoản, chỉ thoát bằng
               Esc. `created` vẫn null nên phần sau của addUser tự dừng. */
            if (isAbort(error) || isExpired(error)) return null;
            if (error.code === "USERNAME_TAKEN") return `Tên đăng nhập «${username}» đã có người dùng. Chọn tên khác.`;
            if (isAuthOff(error)) return "Máy chủ đang tắt chế độ tài khoản — không tạo được tài khoản.";
            return errText(error, "Không tạo được tài khoản.");
          }
          return null;
        },
      });
    } finally {
      v.adding = false;
    }
    if (!result || !created || !live(v)) return;
    const name = String(created.username || "");
    toast(`Đã tạo tài khoản ${name}.`);
    // Ô tìm đang lọc mất hàng vừa tạo thì xóa bộ lọc, nếu không người dùng tưởng nó không được tạo.
    if (v.search.trim() && !matches(created, v.search.trim().toLowerCase())) {
      v.search = "";
      v.searchInput.value = "";
    }
    load(v);
  }

  /* ── vòng đời ────────────────────────────────────────────────── */

  function mount(ctx) {
    ctx.setHeader("Người dùng & phân quyền", "Tài khoản nội bộ · 2 vai trò");

    const searchInput = h("input", {
      type: "text", placeholder: "Tìm người dùng…", "aria-label": "Tìm theo tên đăng nhập",
      autocomplete: "off", spellcheck: "false",
      // Gõ khi danh sách chưa về: chỉ nhớ chữ, không vẽ lại (bảng đang là khung xương,
      // vẽ bây giờ sẽ ghi đè "đang đọc danh sách…" bằng "0/0 tài khoản").
      onInput: (event) => {
        if (!V) return;
        V.search = event.target.value;
        if (V.loaded) paintRows(V);
      },
      onKeydown: (event) => {
        if (event.key === "Escape" && event.target.value) {
          event.preventDefault();
          event.target.value = "";
          if (V) { V.search = ""; if (V.loaded) paintRows(V); }
        }
      },
    });
    const count = h("span", { class: "usr-count", role: "status" }, "đang đọc danh sách…");
    const addBtn = h("button", {
      type: "button", class: "btn btn-36 btn-primary btn-lift btn-glow usr-add",
      onClick: () => { if (V) addUser(V); },
    }, icon("plus", { size: 15, sw: 2.2 }), "Thêm người dùng");
    const toolbar = h("div", { class: "toolbar" },
      h("label", { class: "search usr-search" }, icon("search", { size: 15 }), searchInput),
      count, h("span", { class: "spacer" }), Shell.isAdmin() ? addBtn : null);

    const body = h("div", { class: "usr-body" });
    const tbody = h("tbody");
    ctx.root.append(h("div", { class: "page" }, h("div", { class: "page-inner w-1000" }, toolbar, body)));

    const v = {
      ctx, toolbar, searchInput, count, body, tbody,
      users: [], search: "", loaded: false, seq: 0, adding: false, needsReload: false,
    };
    V = v;
    /* Nhịp duy nhất của màn hình này: không poll danh sách (tài khoản không tự đổi),
       chỉ đọc lại sau khi một thao tác bị phiên hết hạn cắt ngang. Lúc màn đăng nhập
       còn hiện thì Router đang dừng và every() không chạy, nên nó chỉ nổ sau khi
       người dùng vào lại. */
    ctx.every(() => {
      if (!v.needsReload || !live(v)) return;
      v.needsReload = false;
      load(v, { first: true });
    }, 3000);
    load(v, { first: true });
  }

  /* Router.go lại đúng #/users (cùng hash) → đọc lại danh sách, không dựng lại. */
  function update(ctx, info) {
    if (!V || V.ctx !== ctx) return false;
    if (info && info.same) load(V);
    return true;
  }

  function unmount() {
    V = null;
  }

  Router.register("users", { admin: true, mount, update, unmount });
})();
