/* ══════════════════════════════════════════════════════════════════
   /ui/views/settings.js — màn hình "Cài đặt" (#/settings, mọi vai trò).

   Một IIFE, không tên top-level. Bốn section card:
     - Giao diện: chủ đề (segmented Sáng | Hệ thống | Tối) và hiệu ứng động;
     - Trò chuyện: Enter để gửi · Ghi nhớ mặc định · Hiện độ bám nguồn;
     - Bảo mật: khóa truy cập LOCAL_AI_API_KEY lưu trong trình duyệt này;
     - Tài khoản & riêng tư: người đang đăng nhập, đổi mật khẩu, đăng xuất.

   Tất cả lựa chọn ở đây là của TRÌNH DUYỆT, không phải của máy chủ: chúng
   nằm trong localStorage (lac.prefs, lac.apikey) nên đổi là có hiệu lực
   ngay, không cần gọi mạng và không đồng bộ sang máy khác.

   Chỉ một chỗ gọi mạng: GET /auth/me (lấy last_login_at cho dòng "đăng nhập
   … trước") và POST /auth/me/password (spec F5 — backend hôm nay CHƯA có,
   404 ⇒ nói thẳng "Máy chủ chưa hỗ trợ đổi mật khẩu." và khóa nút lại).

   Hành vi cũ (research/old-chat.md): 104 (mở là đọc lại prefs hiện tại),
   105 (đổi chủ đề có hiệu lực ngay, lưu prefs.theme, "Hệ thống" bám theo hệ
   điều hành), 106 (ô khóa luôn trống, dòng trạng thái cho biết đã có khóa
   hay chưa, để trống + Lưu = xóa, Enter cũng lưu, có toast).
   Mục 107 (Model), 108 (tìm ghi nhớ) và 109 (sức khỏe hệ thống) của trang
   Cài đặt cũ đã chuyển sang #/models, #/memory và #/dashboard.

   Trang này phải phản ánh prefs kể cả khi nơi khác đổi (nút chủ đề ở chân
   thanh bên, hệ điều hành đổi sáng/tối): MutationObserver trên data-theme /
   data-motion của <html> là tín hiệu duy nhất chung cho cả ba đường đó.

   V là DOM của lần mount đang sống, null khi đã rời view — mọi việc bất
   đồng bộ kiểm tra live(v) trước khi vẽ.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  const JSON_HEADERS = { "Content-Type": "application/json" };

  const MISSING_PASSWORD = "Máy chủ chưa hỗ trợ đổi mật khẩu.";
  const WRONG_PASSWORD = "Mật khẩu hiện tại không đúng.";
  const FAILED_PASSWORD = "Không đổi được mật khẩu.";
  const MIN_PASSWORD = 8;

  /* Bật tài khoản mà lưu khóa truy cập là tự đăng xuất: máy chủ đọc
     X-API-Key TRƯỚC Bearer (research/api-core.md §1.1), nên khóa đúng thì
     mọi request sau đó là danh tính "service" và /auth/me trả 401. */
  const KEY_LOGOUT_WARNING =
    "Máy chủ đọc khóa truy cập trước tài khoản đang đăng nhập. Nếu khóa này đúng,"
    + " bạn sẽ bị đăng xuất và phải xóa khóa mới đăng nhập lại được.";

  /* Ba công tắc của mục "Trò chuyện" (P:576). Mặc định của showGrounding là
     BẬT nên đọc bằng `!== false` — pref này không có trong lac.prefs cũ. */
  const CHAT_SWITCHES = [
    {
      key: "enterToSend",
      title: "Enter để gửi",
      sub: "Tắt nếu bạn muốn Enter xuống dòng và gửi bằng nút.",
      get: () => prefs.enterToSend !== false,
    },
    {
      key: "memoryDefault",
      title: "Ghi nhớ mặc định",
      sub: "Tự bật «Ghi nhớ» khi mở cuộc trò chuyện mới.",
      get: () => prefs.memoryDefault === true,
    },
    {
      key: "showGrounding",
      title: "Hiện độ bám nguồn",
      sub: "Nhãn tự kiểm tra câu trả lời có bám theo nguồn đã trích.",
      get: () => prefs.showGrounding !== false,
    },
  ];

  const THEMES = [
    { value: "light", label: "Sáng" },
    { value: "system", label: "Hệ thống" },
    { value: "dark", label: "Tối" },
  ];

  let V = null;
  /* Nhớ ở phạm vi module (như shell.js state.countMissing): máy chủ đã trả 404
     cho F5 một lần thì lần mount sau không mời người dùng thử lại nữa. */
  let passwordMissing = false;

  const isAbort = (error) => Boolean(error) && error.name === "AbortError";
  const live = (v) => Boolean(v) && V === v && !v.ctx.signal.aborted;

  const roleText = (role) => (role === "admin" ? "Quản trị viên" : "Thành viên");

  /* localStorage có thể ném (hết hạn mức, trình duyệt chặn dữ liệu trang).
     Lưu hỏng thì vẫn áp lựa chọn cho phiên này — giống safeSavePrefs của shell. */
  function storePrefs() {
    try { savePrefs(); } catch (error) { console.warn("[settings] không lưu được lac.prefs", error); }
  }

  /* lac.prefs hỏng (theme lạ) thì segmented không có mục nào sáng: coi như "Hệ thống". */
  const themeValue = () => (THEMES.some((t) => t.value === prefs.theme) ? prefs.theme : "system");

  /* ── khung chung ─────────────────────────────────────────────── */

  /* Một section card: đầu nhãn uppercase + phần thân truyền vào (P:570).
     Nhãn là <h2> chứ không phải <div> như prototype: người dùng trình đọc
     màn hình nhảy giữa bốn mục bằng danh sách tiêu đề (nhìn thì y hệt). */
  function section(label, ...body) {
    return h("section", { class: "card card-flush" },
      h("h2", { class: "section-label section-label-wide set-head" }, label),
      ...body);
  }

  /* Một hàng "nhãn + mô tả + điều khiển" (P:571). flush = bỏ gạch dưới.
     `key` gắn mô tả vào chính điều khiển bằng aria-describedby: câu giải thích
     hệ quả (nhất là "hệ điều hành đang bật giảm chuyển động") chỉ nằm cạnh công
     tắc thì trình đọc màn hình không đọc tới. Thuần thuộc tính, không đổi pixel. */
  function settingRow(title, sub, control, { flush = false, key } = {}) {
    const subId = key ? `set-sub-${key}` : null;
    if (subId && control && control.setAttribute) control.setAttribute("aria-describedby", subId);
    return h("div", { class: ["setting-row", flush && "set-row-flush"] },
      h("div", { class: "set-main" },
        h("div", { class: "set-title" }, title),
        h("div", { class: "set-sub", id: subId }, sub)),
      control);
  }

  /* ── Giao diện ───────────────────────────────────────────────── */

  const MOTION_SUB = "Tắt nếu máy yếu hoặc bạn thích giao diện tĩnh.";
  const MOTION_SUB_REDUCED = "Hệ điều hành đang bật «giảm chuyển động» nên hiệu ứng vẫn tắt.";

  function syncMotionSub(v) {
    if (!live(v) || !v.motionSub) return;
    v.motionSub.textContent = v.reduced.matches ? MOTION_SUB_REDUCED : MOTION_SUB;
  }

  function appearanceCard(v) {
    /* lac.prefs mang giá trị lạ (file hỏng, bản cũ) thì common.js đã gán
       <html data-theme="…"> vô nghĩa và cả ba nút cùng xám: chữa ngay ở đây,
       đây đúng là màn hình để sửa chuyện đó. */
    if (prefs.theme !== themeValue()) {
      prefs.theme = themeValue();
      storePrefs();
      applyTheme();
    }

    /* Đổi chủ đề: lưu prefs rồi applyTheme() — common.js tự bám theo hệ điều
       hành khi chọn "Hệ thống" (prototype để nút này trơ, bản này chạy thật). */
    v.themeSeg = segmented(THEMES, themeValue(), (value) => {
      prefs.theme = value;
      storePrefs();
      applyTheme();
    }, { label: "Chủ đề" });
    v.themeSeg.classList.add("set-seg");

    /* Hiệu ứng động: html[data-motion="off"] tắt mọi animation/transition
       (styles.css), nên hiệu lực ngay khi bấm, không cần vẽ lại gì. */
    v.motionSwitch = switchEl({
      checked: prefs.motion !== false,
      label: "Hiệu ứng động",
      onChange: (on) => {
        prefs.motion = on;
        document.documentElement.dataset.motion = on ? "on" : "off";
        storePrefs();
      },
    });

    /* Hệ điều hành bật "giảm chuyển động" thì styles.css tắt hiệu ứng bất kể
       công tắc này — nói thẳng thay vì để người dùng bật mà không thấy gì đổi. */
    const row = settingRow("Hiệu ứng động", MOTION_SUB, v.motionSwitch, { flush: true, key: "motion" });
    v.motionSub = row.querySelector(".set-sub");
    v.reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    syncMotionSub(v);
    v.ctx.on(v.reduced, "change", () => syncMotionSub(v));

    return section("Giao diện",
      settingRow("Chủ đề", "Sáng, tối hoặc theo hệ thống.", v.themeSeg, { key: "theme" }),
      row);
  }

  /* ── Trò chuyện ──────────────────────────────────────────────── */

  function chatCard(v) {
    const rows = CHAT_SWITCHES.map((item) => {
      const control = switchEl({
        checked: item.get(),
        label: item.title,
        onChange: (on) => { prefs[item.key] = on; storePrefs(); },
      });
      v.chatSwitches.push({ item, control });
      return settingRow(item.title, item.sub, control, { key: item.key });
    });
    return section("Trò chuyện", ...rows);
  }

  /* ── Bảo mật ─────────────────────────────────────────────────── */

  /* Dòng trạng thái + placeholder luôn kể đúng chuyện localStorage đang có
     gì; ô nhập LUÔN trống (không bao giờ vẽ lại khóa đã lưu — old-chat 106). */
  function syncKeyState(v) {
    const saved = Boolean(getApiKey());
    v.keyInput.value = "";
    v.keyInput.placeholder = saved ? "Dán khóa mới để thay" : "Dán khóa truy cập";
    v.keyState.replaceChildren(saved
      ? h("span", { class: "set-key-ok" }, icon("check", { size: 12, sw: 2.5 }), "Đã lưu trong trình duyệt này")
      : h("span", { class: "set-sub" }, "Chưa nhập khóa"));
  }

  /* Lưu xong thì ô bị xóa trắng (old-chat 106), nên cú bấm — hoặc Enter — THỨ HAI
     của cùng một thao tác đọc ô trống và rơi vào nhánh xóa: mất đúng khóa vừa dán.
     Chặn bằng v.keySaved, cờ này tắt ngay khi người dùng gõ lại, nên "để trống +
     Lưu = xóa" vẫn còn nguyên. v.keyBusy chặn mở hai hộp xác nhận. */
  async function saveKey(v) {
    if (v.keyBusy) return;
    const value = v.keyInput.value;
    if (!value.trim() && v.keySaved) return;

    if (value.trim() && Shell.authEnabled) {
      v.keyBusy = true;
      let go = false;
      try {
        go = await confirmDialog({
          title: "Lưu khóa truy cập?", body: KEY_LOGOUT_WARNING, confirmLabel: "Vẫn lưu",
          tone: "warn", icon: "shield", signal: v.ctx.signal,
        });
      } finally {
        v.keyBusy = false;
      }
      if (!go || !live(v)) return;
    }

    setApiKey(value);
    const saved = Boolean(getApiKey());
    syncKeyState(v);
    v.keySaved = true;
    toast(saved ? "Đã lưu khóa truy cập." : "Đã xóa khóa truy cập.");
  }

  function securityCard(v) {
    v.keyState = h("div");
    v.keyInput = h("input", {
      type: "password", class: "input input-34 set-key-input", "aria-label": "Khóa truy cập",
      autocomplete: "off", spellcheck: "false",
      onInput: () => { v.keySaved = false; },
      onKeydown: (event) => {
        if (event.key !== "Enter" || event.isComposing) return;
        event.preventDefault();
        saveKey(v);
      },
    });

    const row = h("div", { class: "set-key" },
      h("div", { class: "set-main set-key-main" },
        h("div", { class: "set-title" }, "Khóa truy cập"),
        v.keyState),
      v.keyInput,
      h("button", { type: "button", class: "btn btn-34 px-14 btn-primary", onClick: () => saveKey(v) }, "Lưu"));

    syncKeyState(v);
    return section("Bảo mật",
      h("div", { class: "set-body" },
        h("p", { class: "set-para" },
          "Máy chủ có thể yêu cầu khóa truy cập cho mọi thao tác ghi và xóa (",
          h("code", { class: "code" }, "LOCAL_AI_API_KEY"),
          "). Khóa chỉ lưu trong trình duyệt này."),
        row));
  }

  /* ── Tài khoản & riêng tư ────────────────────────────────────── */

  /* Lỗi nào cũng phải ra tiếng Việt: common.js dựng message từ
     ERROR_HINTS[code] || data.message, nên một lỗi không có mã (500 chẳng hạn)
     mang nguyên câu tiếng Anh của máy chủ. Mã lỗi vẫn hiện trong ngoặc để
     quản trị viên đối chiếu log. */
  function passwordError(error) {
    if (!error) return FAILED_PASSWORD;
    if (error.code === "PASSWORD_INVALID") return WRONG_PASSWORD;
    if (error.code && ERROR_HINTS[error.code]) return error.message;
    if (error.status === undefined) return error.message || FAILED_PASSWORD;  // mất kết nối: câu đã tiếng Việt
    if (error.status >= 500) return `${FAILED_PASSWORD} Máy chủ gặp lỗi.`;
    return `${FAILED_PASSWORD} Máy chủ từ chối (${error.code || `HTTP ${error.status}`}).`;
  }

  /* F5: POST /auth/me/password. Kiểm tra tại chỗ trước (đỡ một vòng mạng),
     rồi gọi máy chủ NGAY TRONG validate() để sai mật khẩu hiện tại thì
     dialog ở nguyên và người dùng gõ lại, không phải mở lại từ đầu.
     outcome mang kết quả ra ngoài vì validate chỉ nói được "lỗi gì". */
  async function changePassword(v) {
    if (v.pwOpen || passwordMissing) return;   // một cú bấm = một hộp thoại
    v.pwOpen = true;
    let outcome = null;
    let attempt = null;   // lời gọi F5 đang bay, để chờ tiếp sau khi dialog đóng

    /* KHÔNG truyền ctx.signal vào lời gọi này: đổi mật khẩu là thao tác ghi
       thông tin đăng nhập. Người dùng bấm xong rồi chuyển màn hình mà request
       bị hủy giữa chừng thì không ai biết mật khẩu hiện tại là cái nào. Cho
       chạy tới cùng rồi báo bằng toast — toast là của khung, không của view. */
    const send = async (values) => {
      try {
        await Shell.api("/auth/me/password", {
          method: "POST", headers: JSON_HEADERS,
          body: JSON.stringify({ current_password: values.current, new_password: values.next }),
        });
        outcome = "ok";
        return null;
      } catch (error) {
        /* 401 chung cuộc: Shell đã dựng màn đăng nhập, mà dialog còn mở thì
           #login-root bị đánh inert — người dùng nhìn thấy form nhưng không gõ
           được. Nhường màn hình y như khi bị hủy. */
        if (isAbort(error) || (error && error.status === 401)) { outcome = "gone"; return null; }
        if (isMissingApi(error)) { outcome = "missing"; return null; }
        return passwordError(error);
      }
    };

    try {
      await dialog({
        tone: "accent", icon: "lock", title: "Đổi mật khẩu",
        body: `Mật khẩu mới cần tối thiểu ${MIN_PASSWORD} ký tự.`,
        fields: [
          { name: "current", label: "Mật khẩu hiện tại", type: "password", required: true, autocomplete: "current-password" },
          { name: "next", label: "Mật khẩu mới", type: "password", required: true, minlength: MIN_PASSWORD, autocomplete: "new-password" },
          { name: "confirm", label: "Nhập lại mật khẩu mới", type: "password", required: true, autocomplete: "new-password" },
        ],
        confirmLabel: "Đổi mật khẩu",
        signal: v.ctx.signal,
        validate: (values) => {
          if (values.next !== values.confirm) return "Hai ô mật khẩu mới không giống nhau.";
          if (values.next === values.current) return "Mật khẩu mới trùng mật khẩu hiện tại.";
          attempt = send(values);
          return attempt;
        },
      });
    } finally {
      v.pwOpen = false;
    }

    /* Dialog có thể đã đóng trước khi máy chủ trả lời (rời màn hình, Back). */
    if (attempt) await attempt;
    if (outcome === "ok") { toast("Đã đổi mật khẩu."); return; }
    if (outcome !== "missing") return;   // null = Hủy/Esc, "gone" = hết phiên hoặc hủy

    /* Chưa có endpoint: nhớ lại cho những lần mount sau và nói ra bằng chữ. */
    passwordMissing = true;
    toast(MISSING_PASSWORD, "danger");
    if (live(v)) syncPasswordMissing(v);
  }

  /* aria-disabled chứ không phải disabled: nút vẫn nhận được focus nên bàn phím
     không bị rơi về <body> sau khi dialog trả focus về đây, và câu giải thích
     nằm ở dòng chữ dưới tên (tooltip trên nút disabled không bao giờ hiện). */
  function syncPasswordMissing(v) {
    if (!v.passwordBtn) return;
    if (passwordMissing) {
      v.passwordBtn.setAttribute("aria-disabled", "true");
      v.passwordBtn.title = MISSING_PASSWORD;
    } else {
      v.passwordBtn.removeAttribute("aria-disabled");
      v.passwordBtn.removeAttribute("title");
    }
    if (v.passwordNote) v.passwordNote.hidden = !passwordMissing;
  }

  /* Dòng dưới tên: vai trò + lần đăng nhập gần nhất (GET /auth/me). Lúc mount
     mới chỉ có vai trò (Shell.user), thời điểm đăng nhập điền vào sau. */
  function accountSub(role, lastLogin) {
    if (!lastLogin) return roleText(role);
    return `${roleText(role)} · đăng nhập ${fmtRelative(lastLogin)}`;
  }

  function accountCard(v) {
    const user = Shell.user;

    if (!Shell.authEnabled || !user) {
      /* Tắt tài khoản: không có ai để đổi mật khẩu hay đăng xuất cả. */
      return section("Tài khoản & riêng tư",
        h("div", { class: "setting-row set-acct" },
          h("span", { class: "avatar avatar-38", "aria-hidden": "true" }, icon("user", { size: 16 })),
          h("div", { class: "set-main" },
            h("div", { class: "set-title" }, "Người dùng cục bộ"),
            h("div", { class: "set-sub" }, "Chưa bật tài khoản — mọi thao tác chạy với toàn quyền"))),
        privacyPara());
    }

    v.accountSub = h("div", { class: "set-sub" }, accountSub(user.role, null));
    /* Máy chủ chưa có F5 thì nói ra bằng chữ, kèm endpoint như missingApiState. */
    v.passwordNote = h("div", { class: "set-sub set-miss" },
      MISSING_PASSWORD, " ", h("code", { class: "code" }, "POST /auth/me/password"));
    v.passwordBtn = h("button", {
      type: "button", class: "btn btn-32 btn-outline hover-bg", onClick: () => changePassword(v),
    }, "Đổi mật khẩu");
    syncPasswordMissing(v);

    return section("Tài khoản & riêng tư",
      h("div", { class: "setting-row set-acct" },
        h("span", { class: "avatar avatar-38", "aria-hidden": "true" }, initials(user.username)),
        h("div", { class: "set-main" },
          h("div", { class: "set-title", title: user.username }, user.username),
          v.accountSub,
          v.passwordNote),
        v.passwordBtn,
        h("button", {
          type: "button", class: "btn btn-32 btn-ghost-danger", onClick: () => { Shell.logout(); },
        }, "Đăng xuất")),
      privacyPara());
  }

  function privacyPara() {
    return h("p", { class: "set-para set-para-row" },
      "Toàn bộ dữ liệu nằm trên máy chủ nội bộ: hội thoại và tài liệu trong PostgreSQL, vector tìm kiếm trong"
      + " Qdrant. Không có dữ liệu nào gửi ra dịch vụ bên ngoài. Ghi nhớ chỉ dùng những gì đã được duyệt ở mục ",
      h("a", { href: "#/memory" }, "Ghi nhớ"), ".");
  }

  /* last_login_at chỉ có ở /auth/me, Shell.user không mang theo. Hỏng thì
     im lặng: dòng vai trò vẫn đúng, không có lý do bày lỗi ra cả trang. */
  async function loadMe(v) {
    if (!Shell.authEnabled || !Shell.user) return;
    try {
      const me = await Shell.api("/auth/me", { signal: v.ctx.signal });
      if (!live(v) || !v.accountSub || !me) return;
      /* Vai trò lấy từ Shell (nguồn duy nhất cho nav + chân thanh bên): nếu máy
         chủ vừa đổi vai trò thì thẻ này không được nói khác với menu bên trái.
         Ở đây chỉ cần last_login_at — thứ Shell.user không mang theo. */
      v.accountSub.textContent = accountSub(Shell.user.role, me.last_login_at);
    } catch (error) {
      if (!live(v) || isAbort(error)) return;
      console.warn("Không đọc được /auth/me:", error && error.message);
    }
  }

  /* ── đồng bộ khi nơi khác đổi prefs ──────────────────────────── */

  function syncFromPrefs(v) {
    if (!live(v)) return;
    v.themeSeg.setValue(themeValue());
    v.motionSwitch.checked = prefs.motion !== false;
    for (const { item, control } of v.chatSwitches) control.checked = item.get();
  }

  /* ── vòng đời ────────────────────────────────────────────────── */

  Router.register("settings", {
    admin: false,
    mount(ctx) {
      ctx.setHeader("Cài đặt", "Giao diện, trò chuyện, bảo mật, tài khoản");

      const v = { ctx, chatSwitches: [] };
      V = v;

      ctx.root.append(h("div", { class: "page" },
        h("div", { class: "page-inner w-820 gap-14 set-page" },
          appearanceCard(v), chatCard(v), securityCard(v), accountCard(v))));

      /* Nút chủ đề ở chân thanh bên và hệ điều hành đổi sáng/tối đều đi qua
         applyTheme() → đổi thuộc tính trên <html>. Đó là tín hiệu để vẽ lại
         segmented cho khớp. ctx.every/on không nhận MutationObserver nên gỡ
         thủ công theo ctx.signal. */
      const observer = new MutationObserver(() => syncFromPrefs(v));
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-motion"] });
      ctx.signal.addEventListener("abort", () => observer.disconnect(), { once: true });

      loadMe(v);
    },
    unmount() {
      V = null;
    },
  });
})();
