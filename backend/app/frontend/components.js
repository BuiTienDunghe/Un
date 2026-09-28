/* ══════════════════════════════════════════════════════════════════
   /ui/components.js — primitives dựng DOM dùng chung cho mọi view.

   Script cổ điển, nạp SAU common.js và TRƯỚC router.js/shell.js/views.
   Mọi tên top-level ở đây là hàm công khai (danh sách ở spec.md mục
   Components); không có biến top-level nào khác — trạng thái riêng
   (toast đang mở, menu đang mở…) nằm trong DOM hoặc trên chính hàm.
   KHÔNG khai báo lại tên của common.js ($, el, esc, prefs…).
   Không dựng HTML thô: mọi chữ đi qua textContent.
   ══════════════════════════════════════════════════════════════════ */
"use strict";

/* ── DOM ───────────────────────────────────────────────────────── */

/* h("button", {class: ["btn", on && "is-active"], onClick, "aria-label": "…"}, icon("x"), "Đóng")
   props: class|className (chuỗi hoặc mảng, phần tử falsy bị bỏ), text, style (object|chuỗi;
   khóa "--x" → biến CSS), dataset, on<Event>: hàm, còn lại → attribute (true → "", false/null → bỏ;
   riêng trạng thái ARIA — aria-expanded/pressed/checked/selected/hidden/disabled/current/…: true/false →
   "true"/"false", vì aria-expanded="" hay thiếu hẳn đều sai nghĩa; aria-* kiểu id/chuỗi false → bỏ).
   value/checked/selected/indeterminate gán như property SAU khi đã gắn con (để <select> nhận value).
   children: Node | chuỗi | số | mảng lồng | null/false/true (bỏ qua). */
function h(tag, props, ...children) {
  const node = document.createElement(tag);
  if (props != null && (typeof props !== "object" || props instanceof Node || Array.isArray(props))) {
    children.unshift(props);
    props = null;
  }
  const late = [];
  for (const [key, value] of Object.entries(props || {})) {
    if (typeof value === "boolean" && /^aria-(expanded|pressed|checked|selected|hidden|disabled|current|busy|modal|invalid|readonly|required|multiselectable|multiline|atomic|grabbed)$/.test(key)) {
      node.setAttribute(key, String(value));
      continue;
    }
    if (value === undefined || value === null || value === false) continue;
    if (key === "class" || key === "className") {
      const cls = Array.isArray(value) ? value.flat(Infinity).filter(Boolean).join(" ") : String(value);
      if (cls) node.className = cls;
    } else if (key === "text") {
      node.textContent = String(value);
    } else if (key === "style") {
      if (typeof value === "string") node.style.cssText = value;
      else for (const [prop, v] of Object.entries(value)) {
        if (v == null || v === false) continue;
        if (prop.startsWith("--") || prop.includes("-")) node.style.setProperty(prop, String(v));
        else node.style[prop] = typeof v === "number" && !/^(opacity|zIndex|flex|flexGrow|flexShrink|order|fontWeight|lineHeight|zoom|scale|aspectRatio|columnCount|tabSize|fillOpacity|strokeOpacity|animationIterationCount|WebkitLineClamp|lineClamp|gridColumn|gridColumnStart|gridColumnEnd|gridRow|gridRowStart|gridRowEnd|gridArea)$/.test(prop) ? `${v}px` : String(v);
      }
    } else if (key === "dataset") {
      for (const [k, v] of Object.entries(value)) if (v != null) node.dataset[k] = String(v);
    } else if (/^on[A-Z]/.test(key) && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "value" || key === "checked" || key === "selected" || key === "indeterminate") {
      late.push([key, value]);
    } else {
      node.setAttribute(key, value === true ? "" : String(value));
    }
  }
  const append = (child) => {
    if (child == null || child === false || child === true) return;
    if (Array.isArray(child)) { child.forEach(append); return; }
    node.append(child instanceof Node ? child : String(child));
  };
  children.forEach(append);
  for (const [key, value] of late) node[key] = value;
  return node;
}

/* <svg class="ico"><use href="#i-name"/></svg>; sw = độ dày nét (mặc định 2 từ CSS). */
function icon(name, { size = 16, sw, cls } = {}) {
  const svgNs = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNs, "svg");
  svg.setAttribute("class", cls ? `ico ${Array.isArray(cls) ? cls.filter(Boolean).join(" ") : cls}` : "ico");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  if (sw != null) svg.style.setProperty("--ico-sw", String(sw));
  const use = document.createElementNS(svgNs, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

/* ── Toast ─────────────────────────────────────────────────────── */

/* Đáy giữa, tự ẩn sau `duration` ms (Infinity = đến khi gọi hàm trả về).
   Nhiều toast xếp chồng (tối đa 3, cũ nhất bị bỏ); cùng chữ + cùng loại thì
   thay bản cũ. Nằm trên dialog (z 90 > 80). Trả về hàm đóng toast. */
function toast(text, kind = "ok", { duration = 2800 } = {}) {
  let root = document.getElementById("toast-root");
  if (!root) {
    root = h("div", { id: "toast-root", class: "toast-root", role: "status", "aria-live": "polite" });
    document.body.append(root);
  }
  const danger = kind === "danger" || kind === "error";
  const key = `${danger ? "d" : "o"}:${text}`;
  for (const old of root.querySelectorAll(".toast")) {
    if (old.dataset.key === key) { clearTimeout(old._timer); old.remove(); }
  }
  const node = h("div", { class: "toast", dataset: { key } },
    h("span", { class: ["toast-icon", danger && "is-error"] }, icon(danger ? "alert" : "check", { size: 12, sw: 2.6 })),
    h("span", { class: "toast-text" }, String(text)));
  root.append(node);
  const all = root.querySelectorAll(".toast");
  for (let i = 0; i < all.length - 3; i++) { clearTimeout(all[i]._timer); all[i].remove(); }
  const close = () => { clearTimeout(node._timer); node.remove(); };
  if (Number.isFinite(duration)) node._timer = setTimeout(close, Math.max(0, duration));
  return close;
}

/* ── Dialog ────────────────────────────────────────────────────── */

/* dialog({tone, icon, title, body, content?, input?, fields?, options?, confirmLabel, confirmTone, cancelLabel, validate?})
   → Promise: input → chuỗi đã trim; fields → {name: value}; options → value của lựa chọn;
   xác nhận trơn → true; Hủy / Esc / bấm nền → null.
   input: chuỗi (giá trị ban đầu) hoặc {value, placeholder, maxlength, type, label, allowEmpty}.
   fields: [{name, label, type: "text"|"password"|"select", value, placeholder, options: [{value,label}],
            required, minlength, maxlength, autocomplete, hint}].
   options: [{value, title (hoặc label), sub (hoặc hint), icon, disabled}] — bấm là chọn ngay.
   content: một Node khối (không phải chuỗi) đặt ngay dưới phần đầu, chiếm hết bề ngang.
   Nút chính chỉ hiện khi có confirmLabel. validate(result) → chuỗi lỗi | falsy (có thể async).
   fields có required/minlength được kiểm trước validate (ô trống/quá ngắn → báo lỗi, không đóng).
   Tự đóng (→ null) khi hashchange (Back/Forward) hoặc khi signal abort — view truyền ctx.signal
   để dialog không sống lâu hơn màn hình mở nó. Mở dialog thì menu thả xuống đang mở bị đóng. */
function dialog(opts = {}) {
  const {
    tone = "accent", icon: iconName = "info", title = "", body, content, input, fields, options,
    confirmLabel, confirmTone, cancelLabel = "Hủy", validate, signal,
  } = opts;
  if (signal && signal.aborted) return Promise.resolve(null);
  // Menu nổi (z 85) nằm trên lớp phủ dialog (z 80): đóng trước, trả focus về nút đã mở menu.
  if (dropdown.open) dropdown.open.close({ restoreFocus: true });
  const root = document.getElementById("dialog-root") || document.body;
  const opener = document.activeElement;
  dialog.seq = (dialog.seq || 0) + 1;
  const uid = `dlg-${dialog.seq}`;

  return new Promise((resolve) => {
    let settled = false;
    let busy = false;
    const syncInert = () => {
      const overlays = [...document.querySelectorAll(".dialog-overlay")];
      const anyOpen = overlays.length > 0;
      for (const id of ["app", "login-root"]) {
        const node = document.getElementById(id);
        if (node) node.inert = anyOpen;
      }
      overlays.forEach((ov, i) => { ov.inert = i !== overlays.length - 1; });
    };

    const hasInput = input !== undefined && input !== null && input !== false;
    const inputCfg = hasInput ? (typeof input === "object" ? input : { value: input }) : null;
    const toneKey = ["accent", "warn", "danger", "ok", "muted"].includes(tone) ? tone : "accent";

    const titleEl = h("h2", { class: "dialog-title", id: `${uid}-title` }, title);
    const descEl = body != null && body !== "" ? h("p", { class: "dialog-desc", id: `${uid}-desc` }, body) : null;
    const box = h("div", {
      class: "dialog", role: toneKey === "danger" && !hasInput && !fields ? "alertdialog" : "dialog",
      "aria-modal": "true", "aria-labelledby": `${uid}-title`, "aria-describedby": descEl ? `${uid}-desc` : null, tabindex: "-1",
    }, h("div", { class: "dialog-head" },
      h("span", { class: ["icon-tile", "icon-tile-38", `tone-${toneKey}`] }, icon(iconName, { size: 18 })),
      h("div", null, titleEl, descEl)));
    // content: khối DOM (bảng, <pre>, danh sách) — con trực tiếp của .dialog, KHÔNG nhét vào
    // <p class="dialog-desc"> như `body` (div trong p là lồng sai, và aria-describedby sẽ đọc
    // cả khối dài đó làm mô tả). `body` giữ nguyên nghĩa cũ: một câu mô tả.
    if (content instanceof Node) box.append(content);

    let inputEl = null;
    if (inputCfg) {
      inputEl = h("input", {
        class: "input", type: inputCfg.type || "text", placeholder: inputCfg.placeholder, maxlength: inputCfg.maxlength,
        autocomplete: "off", spellcheck: "false", "aria-label": inputCfg.label || title, value: inputCfg.value ?? "",
      });
      box.append(inputEl);
    }

    const fieldEls = new Map();
    const fieldSpecs = new Map();
    if (Array.isArray(fields) && fields.length) {
      const wrap = h("div", { class: "dialog-fields" });
      for (const f of fields) {
        let control;
        if (f.type === "select") {
          control = h("select", { class: "input", name: f.name, required: f.required },
            (f.options || []).map((o) => (typeof o === "object"
              ? h("option", { value: String(o.value) }, o.label ?? String(o.value))
              : h("option", { value: String(o) }, String(o)))));
          control.value = f.value != null ? String(f.value) : control.value;
        } else {
          control = h("input", {
            class: "input", name: f.name, type: f.type || "text", placeholder: f.placeholder, required: f.required,
            minlength: f.minlength, maxlength: f.maxlength, autocomplete: f.autocomplete || "off", value: f.value ?? "",
          });
        }
        fieldEls.set(f.name, control);
        fieldSpecs.set(f.name, f);
        wrap.append(h("label", { class: "field" }, f.label ?? f.name, control, f.hint ? h("span", { class: "field-hint" }, f.hint) : null));
      }
      box.append(wrap);
    }

    const optionEls = [];
    if (Array.isArray(options) && options.length) {
      const wrap = h("div", { class: "dialog-options" });
      for (const o of options) {
        const btn = h("button", { type: "button", class: "dialog-option", disabled: o.disabled },
          o.icon ? icon(o.icon, { size: 16 }) : null,
          h("span", { class: "body" },
            h("span", { class: "t" }, o.title ?? o.label ?? ""),
            (o.sub ?? o.hint) ? h("span", { class: "s" }, o.sub ?? o.hint) : null),
          icon("chevron-right", { size: 14 }));
        btn.addEventListener("click", () => { if (!busy) finish(o.value); });
        optionEls.push(btn);
        wrap.append(btn);
      }
      box.append(wrap);
    }

    const errorEl = h("p", { class: "dialog-error", role: "alert", hidden: true });
    box.append(errorEl);

    const cancelBtn = h("button", { type: "button", class: "btn btn-36 btn-outline" }, cancelLabel || "Hủy");
    const okTone = confirmTone || (toneKey === "danger" ? "danger" : "accent");
    const okBtn = confirmLabel
      ? h("button", { type: "button", class: ["btn", "btn-36", "px-16", "btn-fade", okTone === "danger" ? "btn-danger" : "btn-primary"] }, confirmLabel)
      : null;
    box.append(h("div", { class: "dialog-actions" }, cancelBtn, okBtn));

    const overlay = h("div", { class: "dialog-overlay", role: "presentation" }, box);

    const collect = () => {
      if (inputEl) return inputEl.value.trim();
      if (fieldEls.size) {
        const out = {};
        for (const [name, control] of fieldEls) out[name] = control.type === "password" ? control.value : control.value.trim();
        return out;
      }
      return true;
    };
    const syncOk = () => {
      if (!okBtn) return;
      const emptyInput = inputEl && !inputCfg.allowEmpty && !inputEl.value.trim();
      okBtn.disabled = busy || Boolean(emptyInput);
    };
    const setBusy = (on) => {
      busy = on;
      cancelBtn.disabled = on;
      optionEls.forEach((b, i) => { b.disabled = on || Boolean(options[i].disabled); });
      syncOk();
    };
    const showError = (message) => {
      errorEl.textContent = message || "";
      errorEl.hidden = !message;
    };

    // Chỉ phần tử HTML (a[href], không phải <use href> của icon SVG) và đang hiển thị.
    const focusables = () => [...box.querySelectorAll("button, input, select, textarea, a[href], [tabindex]:not([tabindex='-1'])")]
      .filter((n) => n instanceof HTMLElement && !n.disabled && !n.hidden && n.getClientRects().length > 0);

    const onKey = (event) => {
      const overlays = document.querySelectorAll(".dialog-overlay");
      if (overlays[overlays.length - 1] !== overlay) return;
      if (event.key === "Escape") {
        // Esc đã có lớp khác nhận (menu mở trước), hoặc menu mở TỪ trong dialog tự đóng trước: mỗi Esc một lớp.
        if (event.defaultPrevented || document.querySelector("#menu-root .menu")) return;
        event.preventDefault();
        event.stopPropagation();
        if (!busy) finish(null);
      } else if (event.key === "Tab") {
        const list = focusables();
        if (!list.length) { event.preventDefault(); return; }
        const first = list[0];
        const last = list[list.length - 1];
        const at = document.activeElement;
        // Chính khung .dialog (tabindex -1) cũng có thể giữ focus sau khi bấm vào chữ: Shift+Tab từ đó về mục cuối.
        if (event.shiftKey && (at === first || at === box || !box.contains(at))) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (at === last || !box.contains(at))) {
          event.preventDefault(); first.focus();
        }
      } else if (event.key === "Enter" && !event.isComposing) {
        const target = event.target;
        const isField = target === inputEl || [...fieldEls.values()].includes(target);
        if (isField && okBtn) { event.preventDefault(); submit(); }
      }
    };

    /* required / minlength của fields (thuộc tính HTML thôi thì không chặn được nút chính). */
    const fieldProblem = () => {
      for (const [name, control] of fieldEls) {
        const f = fieldSpecs.get(name) || {};
        const label = f.label ?? name;
        const raw = String(control.value ?? "");
        const text = control.type === "password" ? raw : raw.trim();
        if (f.required && !text) return { control, message: `Chưa nhập «${label}».` };
        const min = Number(f.minlength);
        if (text && Number.isFinite(min) && min > 0 && [...text].length < min) {
          return { control, message: `«${label}» cần tối thiểu ${min} ký tự.` };
        }
      }
      return null;
    };

    async function submit() {
      if (!okBtn || okBtn.disabled || busy) return;
      const problem = fieldProblem();
      if (problem) {
        showError(problem.message);
        problem.control.focus();
        return;
      }
      const result = collect();
      if (typeof validate === "function") {
        setBusy(true);
        showError("");
        let message = null;
        try {
          message = await validate(result);
        } catch (error) {
          message = (error && error.message) || String(error);
        }
        if (settled) return;
        setBusy(false);
        if (message) {
          showError(String(message));
          (inputEl || fieldEls.values().next().value || okBtn).focus();
          return;
        }
      }
      finish(result);
    }

    /* Back/Forward (hashchange) hoặc view mở dialog đã rời màn hình (signal) → đóng như bấm Hủy.
       Router.replace (view tự ghi lại URL, không có hashchange) không đóng dialog. */
    const onLeave = () => { if (!busy) finish(null); };

    function finish(value) {
      if (settled) return;
      settled = true;
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("hashchange", onLeave);
      if (signal) signal.removeEventListener("abort", onLeave);
      overlay.remove();
      syncInert();
      if (opener && typeof opener.focus === "function" && opener.isConnected && !document.querySelector(".dialog-overlay")) {
        try { opener.focus({ preventScroll: true }); } catch { /* phần tử không nhận focus */ }
      }
      resolve(value);
    }

    let downOnOverlay = false;
    /* Nền vừa hiện ra ngay dưới con trỏ: cú bấm thứ hai của một lần nhấp đúp vào nút đã mở hộp thoại
       sẽ rơi vào nền và đóng hộp ngay lập tức (người dùng chỉ thấy chớp một cái). Bỏ qua cú bấm vào
       nền trong khoảnh khắc đầu; bấm ra ngoài để đóng vẫn hoạt động như cũ. */
    const openedAt = Date.now();
    overlay.addEventListener("pointerdown", (event) => { downOnOverlay = event.target === overlay; });
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay && downOnOverlay && !busy && Date.now() - openedAt > 350) finish(null);
      downOnOverlay = false;
    });
    cancelBtn.addEventListener("click", () => { if (!busy) finish(null); });
    if (okBtn) okBtn.addEventListener("click", submit);
    if (inputEl) inputEl.addEventListener("input", () => { syncOk(); showError(""); });
    for (const control of fieldEls.values()) control.addEventListener("input", () => showError(""));

    document.addEventListener("keydown", onKey, true);
    window.addEventListener("hashchange", onLeave);
    if (signal) signal.addEventListener("abort", onLeave);
    root.append(overlay);
    syncInert();
    syncOk();

    const initial = inputEl || fieldEls.values().next().value || optionEls.find((b) => !b.disabled)
      || (okBtn && okTone !== "danger" ? okBtn : cancelBtn);
    initial.focus({ preventScroll: true });
    if (inputEl) inputEl.select();
  });
}

/* Hỏi xác nhận xóa: true khi bấm nút chính, false khi Hủy/Esc/bấm nền (hoặc rời trang, xem dialog). */
function confirmDialog({ title, body, confirmLabel = "Xóa", tone = "danger", icon: iconName = "trash", signal } = {}) {
  return dialog({ tone, icon: iconName, title, body, confirmLabel, confirmTone: tone === "danger" ? "danger" : "accent", signal })
    .then((result) => result === true);
}

/* ── Dropdown ──────────────────────────────────────────────────── */

/* dropdown(anchor, items | (close) => Node, {align = "end", width, offset = 6, className}) → {close, el}
   items: [{label, icon, tone: "danger", onSelect, disabled, separator, hint}].
   Gọi lại trên cùng anchor khi đang mở = đóng (bật/tắt). Đóng khi bấm ngoài, Esc, chọn mục,
   hashchange, khi CHÍNH anchor bị cuộn đi (trang hoặc khung chứa anchor — khung khác tự cuộn như
   log OCR hay luồng chat thì không), hoặc khi focus rời hẳn menu. Đổi kích thước cửa sổ = đặt lại
   vị trí. Menu cao hơn màn hình → cuộn bên trong. Mũi tên lên/xuống/Home/End di chuyển giữa mục;
   Tab đóng menu và đi tiếp từ anchor. Nội dung tự dựng (panel) nhận focus khi mở.
   handle.close({restoreFocus}) — tùy chọn trả focus về anchor. */
function dropdown(anchor, content, { align = "end", width, offset = 6, className } = {}) {
  const current = dropdown.open;
  if (current && current.anchor === anchor) { current.close(); return { close() {}, el: null }; }
  if (current) current.close();

  const root = document.getElementById("menu-root") || document.body;
  const isList = Array.isArray(content);
  const menu = h("div", {
    class: ["menu", !isList && "menu-panel", className], role: isList ? "menu" : "dialog", tabindex: "-1",
    style: width ? { width: `${width}px` } : null,
  });
  let closed = false;

  const itemButtons = () => [...menu.querySelectorAll(".menu-item:not(:disabled)")];
  const close = ({ restoreFocus = false } = {}) => {
    if (closed) return;
    closed = true;
    menu.remove();
    anchor.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", onOutside, true);
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("scroll", onScroll, true);
    window.removeEventListener("resize", onResize);
    window.removeEventListener("hashchange", onRoute);
    window.removeEventListener("lac:route", onRouted);
    menu.removeEventListener("focusout", onFocusOut);
    if (dropdown.open && dropdown.open.menu === menu) dropdown.open = null;
    if (restoreFocus && anchor.isConnected) anchor.focus({ preventScroll: true });
  };

  if (isList) {
    for (const item of content) {
      if (!item) continue;
      if (item.separator) { menu.append(h("div", { class: "menu-sep", role: "separator" })); continue; }
      const btn = h("button", {
        type: "button", class: ["menu-item", item.tone === "danger" && "is-danger"], role: "menuitem",
        disabled: item.disabled, tabindex: "-1",
      }, item.icon ? icon(item.icon, { size: 15 }) : null, h("span", { class: "label" }, item.label), item.hint ? h("span", { class: "hint" }, item.hint) : null);
      btn.addEventListener("click", () => {
        close({ restoreFocus: true });
        if (typeof item.onSelect === "function") item.onSelect(item);
      });
      menu.append(btn);
    }
  } else if (typeof content === "function") {
    const node = content(() => close({ restoreFocus: true }));
    if (node) menu.append(node);
  } else if (content instanceof Node) {
    menu.append(content);
  }

  function onOutside(event) {
    if (menu.contains(event.target) || anchor.contains(event.target)) return;
    close();
  }
  function onKey(event) {
    if (event.key === "Escape") {
      // stopImmediatePropagation: dialog mở SAU menu (cùng nghe keydown ở document) không đóng theo.
      event.preventDefault();
      event.stopImmediatePropagation();
      close({ restoreFocus: true });
      return;
    }
    if (!menu.contains(document.activeElement) && document.activeElement !== anchor) return;
    if (event.key === "Tab") {
      // Menu nằm cuối <body>: Tab thoát ra thì đóng và trả focus về anchor TRƯỚC hành vi mặc định,
      // để trình duyệt đi tiếp từ anchor. Panel: chỉ khi Tab qua mục cuối / Shift+Tab qua mục đầu.
      if (isList || leavesPanel(event.shiftKey)) close({ restoreFocus: true });
      return;
    }
    if (!isList) return;
    const list = itemButtons();
    if (!list.length) return;
    const at = list.indexOf(document.activeElement);
    let next = null;
    if (event.key === "ArrowDown") next = list[(at + 1) % list.length];
    else if (event.key === "ArrowUp") next = list[(at - 1 + list.length) % list.length];
    else if (event.key === "Home") next = list[0];
    else if (event.key === "End") next = list[list.length - 1];
    if (next) { event.preventDefault(); next.focus(); }
  }
  function leavesPanel(backwards) {
    const list = [...menu.querySelectorAll("button, input, select, textarea, a[href], [tabindex]:not([tabindex='-1'])")]
      .filter((n) => n instanceof HTMLElement && !n.disabled && !n.hidden && n.getClientRects().length > 0);
    const at = document.activeElement;
    if (!list.length) return true;
    return backwards ? at === list[0] || at === menu || at === anchor : at === list[list.length - 1];
  }
  function onScroll(event) {
    const target = event.target;
    if (target instanceof Node && menu.contains(target)) return;
    if (target === document || target === window || (target instanceof Node && target.contains(anchor))) close();
  }
  function onResize() {
    if (!anchor.isConnected || !anchor.getClientRects().length) { close(); return; }
    place();
  }
  function onRoute() { close(); }
  // Router.replace (không có hashchange) mà view bị dựng lại: anchor đã rời trang → đóng menu mồ côi.
  // View chỉ tự ghi lại URL (update giữ nguyên view) thì anchor còn đó, menu vẫn mở.
  function onRouted() { setTimeout(() => { if (!anchor.isConnected) close(); }, 0); }
  function onFocusOut(event) {
    const to = event.relatedTarget;
    // relatedTarget null = cửa sổ mất focus (Alt+Tab) hoặc phần tử bị gỡ: không coi là rời menu.
    if (!to || menu.contains(to) || anchor.contains(to)) return;
    close();
  }

  /* Đặt dưới anchor; không đủ chỗ thì lật lên; không phía nào đủ thì giới hạn chiều cao ở phía
     rộng hơn và cuộn bên trong (menu position:fixed — phần tràn màn hình không cuộn tới được). */
  function place() {
    menu.style.maxHeight = "";
    menu.style.overflowY = "";
    const rect = anchor.getBoundingClientRect();
    const mw = menu.offsetWidth;
    let mh = menu.offsetHeight;
    const vw = document.documentElement.clientWidth;
    const vh = window.innerHeight;
    let left = align === "start" ? rect.left : rect.right - mw;
    left = Math.max(8, Math.min(left, vw - mw - 8));
    const below = vh - 8 - (rect.bottom + offset);
    const above = rect.top - offset - 8;
    let top = rect.bottom + offset;
    if (mh > below) {
      if (mh <= above) top = rect.top - offset - mh;
      else {
        const room = Math.max(below, above);
        if (room >= 120) {
          mh = room;
          top = below >= above ? rect.bottom + offset : rect.top - offset - mh;
        } else {
          mh = Math.min(mh, vh - 16);
          top = Math.max(8, vh - 8 - mh);
        }
        menu.style.maxHeight = `${mh}px`;
        menu.style.overflowY = "auto";
      }
    }
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

  menu.style.visibility = "hidden";
  root.append(menu);
  place();
  menu.style.visibility = "";

  if (!anchor.hasAttribute("aria-haspopup")) anchor.setAttribute("aria-haspopup", isList ? "menu" : "dialog");
  anchor.setAttribute("aria-expanded", "true");
  document.addEventListener("pointerdown", onOutside, true);
  document.addEventListener("keydown", onKey, true);
  document.addEventListener("scroll", onScroll, true);
  window.addEventListener("resize", onResize);
  window.addEventListener("hashchange", onRoute);
  window.addEventListener("lac:route", onRouted);
  menu.addEventListener("focusout", onFocusOut);

  const handle = { close: (opts) => close(opts), el: menu, anchor, menu };
  dropdown.open = handle;
  if (isList) {
    const first = itemButtons()[0];
    if (first) first.focus({ preventScroll: true });
  } else if (!menu.contains(document.activeElement)) {
    // Panel (chuông thông báo…): focus vào khung để Tab đi tiếp vào nội dung, không lạc về view.
    menu.focus({ preventScroll: true });
  }
  return handle;
}

/* ── Điều khiển nhỏ ────────────────────────────────────────────── */

/* segmented([{value, label, icon, count, badge}], value, onChange, {variant: "plain"|"bordered", size: "sm"|"md"|"lg", label})
   → phần tử; el.setValue(v) đổi mục đang chọn mà không gọi onChange; el.value đọc giá trị hiện tại. */
function segmented(options, value, onChange, { variant = "plain", size = "md", label } = {}) {
  let current = value;
  const group = h("div", {
    class: ["seg", variant === "bordered" && "seg-bordered", size === "sm" && "seg-sm", size === "lg" && "seg-lg"],
    role: "radiogroup", "aria-label": label,
  });
  const items = options.map((opt) => {
    const hasBadge = opt.badge !== undefined && opt.badge !== null && opt.badge !== false;
    const btn = h("button", { type: "button", class: "seg-item", role: "radio", disabled: opt.disabled },
      opt.icon ? icon(opt.icon, { size: 13 }) : null,
      h("span", { class: "seg-label" }, opt.label),
      opt.count !== undefined && opt.count !== null ? h("span", { class: "count" }, typeof opt.count === "number" ? fmtNumber(opt.count) : opt.count) : null,
      hasBadge ? h("span", { class: "badge-count" }, opt.badge) : null);
    btn.addEventListener("click", () => pick(opt.value, true));
    return { opt, btn };
  });
  const same = (a, b) => String(a) === String(b);
  function sync() {
    for (const { opt, btn } of items) {
      const on = same(opt.value, current);
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-checked", String(on));
      btn.tabIndex = on ? 0 : -1;
      const badge = btn.querySelector(".badge-count");
      if (badge) badge.classList.toggle("is-muted", !on);
    }
    if (!items.some(({ opt }) => same(opt.value, current)) && items[0]) items[0].btn.tabIndex = 0;
  }
  function pick(v, fromUser) {
    if (same(v, current)) return;
    current = v;
    sync();
    if (fromUser && typeof onChange === "function") onChange(v);
  }
  group.addEventListener("keydown", (event) => {
    const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (!(event.key in keys)) return;
    const enabled = items.filter(({ btn }) => !btn.disabled);
    if (!enabled.length) return;
    const at = enabled.findIndex(({ btn }) => btn === document.activeElement);
    const next = enabled[(at + keys[event.key] + enabled.length) % enabled.length];
    event.preventDefault();
    next.btn.focus();
    pick(next.opt.value, true);
  });
  group.append(...items.map(({ btn }) => btn));
  group.setValue = (v) => { current = v; sync(); };
  Object.defineProperty(group, "value", { get: () => current, configurable: true });
  sync();
  return group;
}

/* pill("Đã index", "ok") — 24px có chấm; size "sm" = 22px/11px; {bold} = 700 (thẻ vai trò/model). */
function pill(text, tone = "muted", { dot = true, size = "md", bold = false } = {}) {
  const key = ["ok", "warn", "danger", "accent", "muted"].includes(tone) ? tone : "muted";
  return h("span", { class: ["pill", `tone-${key}`, dot && "pill-dot", size === "sm" && "pill-22", bold && "pill-bold"] }, text);
}

/* chip("Công cụ: tắt", {icon: "zap", active, onClick, title}) → <button>; el.setActive(bool), el.setLabel(text). */
function chip(label, { icon: iconName, active = false, onClick, title } = {}) {
  const text = h("span", { class: "chip-label" }, label);
  const btn = h("button", {
    type: "button", class: ["chip", active && "is-active"], title,
    "aria-pressed": typeof onClick === "function" ? String(Boolean(active)) : null,
  }, iconName ? icon(iconName, { size: 12 }) : null, text);
  if (typeof onClick === "function") btn.addEventListener("click", onClick);
  btn.setActive = (on) => {
    btn.classList.toggle("is-active", Boolean(on));
    if (btn.hasAttribute("aria-pressed")) btn.setAttribute("aria-pressed", String(Boolean(on)));
  };
  btn.setLabel = (value) => { text.textContent = value; };
  return btn;
}

/* typeBadge("bao-cao.pdf") hoặc typeBadge("md", 34) — ô màu theo loại tệp (28 / 30 / 34 hoặc cỡ tùy ý). */
function typeBadge(filenameOrExt, size = 28) {
  const raw = String(filenameOrExt ?? "").trim().toLowerCase();
  const ext = raw.includes(".") ? raw.slice(raw.lastIndexOf(".") + 1) : raw;
  const kinds = {
    pdf: ["PDF", "type-pdf"], docx: ["DOCX", "type-docx"], doc: ["DOC", "type-docx"], md: ["MD", "type-md"],
    markdown: ["MD", "type-md"], txt: ["TXT", "type-txt"], png: ["PNG", "type-img"], jpg: ["JPG", "type-img"],
    jpeg: ["JPG", "type-img"], webp: ["IMG", "type-img"], tif: ["TIF", "type-img"], tiff: ["TIF", "type-img"],
  };
  const [text, cls] = kinds[ext] || [(ext || "?").toUpperCase().slice(0, 4), "type-txt"];
  const sizeCls = size === 28 ? "type-badge-28" : size === 34 ? "type-badge-34" : null;
  const style = size !== 28 && size !== 30 && size !== 34 ? { width: `${size}px`, height: `${size}px` } : null;
  return h("span", { class: ["type-badge", sizeCls, cls], style, title: text }, text);
}

/* switchEl({checked, onChange, size: "md"|"sm", disabled, label}) → <button role="switch">;
   el.checked đọc/gán (gán không gọi onChange). 38×22 hoặc 34×20. */
function switchEl({ checked = false, onChange, size = "md", disabled = false, label } = {}) {
  let state = Boolean(checked);
  const btn = h("button", {
    type: "button", class: ["switch", size === "sm" && "switch-sm"], role: "switch",
    "aria-checked": String(state), "aria-label": label, disabled,
  });
  btn.addEventListener("click", () => {
    state = !state;
    btn.setAttribute("aria-checked", String(state));
    if (typeof onChange === "function") onChange(state);
  });
  Object.defineProperty(btn, "checked", {
    get: () => state,
    set: (v) => { state = Boolean(v); btn.setAttribute("aria-checked", String(state)); },
    configurable: true,
  });
  return btn;
}

/* skeleton({w: "70%", h: 12, r: 6}) — số → px. */
function skeleton({ w, h: height = 12, r = 6 } = {}) {
  const px = (v) => (typeof v === "number" ? `${v}px` : v);
  return h("div", { class: "skeleton", "aria-hidden": "true", style: { width: px(w), height: px(height), borderRadius: px(r) } });
}

/* ── Trạng thái rỗng / lỗi / API chưa có ───────────────────────── */

/* emptyState({icon, title, text, action}) — action: Node hoặc {label, onClick, icon}. Nhận cả chuỗi = title. */
function emptyState(arg = {}) {
  const { icon: iconName = "info", title, text, action, tone = "muted" } = typeof arg === "string" ? { title: arg } : arg;
  let actionNode = null;
  if (action instanceof Node) actionNode = action;
  else if (action && action.label) {
    actionNode = h("button", { type: "button", class: "btn btn-32 btn-outline", onClick: action.onClick },
      action.icon ? icon(action.icon, { size: 14 }) : null, action.label);
  }
  return h("div", { class: "empty-state" },
    h("span", { class: ["icon-tile", "icon-tile-44", `tone-${tone}`] }, icon(iconName, { size: 20 })),
    title ? h("div", { class: "empty-state-title" }, title) : null,
    text ? h("div", { class: "empty-state-text" }, text) : null,
    actionNode ? h("div", { class: "empty-state-action" }, actionNode) : null);
}

/* errorState(error, onRetry) — thông báo lỗi (tiếng Việt từ sendJson) + nút "Thử lại" nếu có onRetry. */
function errorState(error, onRetry) {
  const message = (error && error.message) || (error ? String(error) : "Đã xảy ra lỗi không xác định.");
  const node = emptyState({
    icon: "alert", tone: "danger", title: "Không tải được dữ liệu", text: message,
    action: typeof onRetry === "function" ? { label: "Thử lại", icon: "retry", onClick: onRetry } : null,
  });
  node.classList.add("is-error");
  node.setAttribute("role", "alert");
  return node;
}

/* missingApiState({feature: "thông báo", endpoint: "GET /notifications"}) — nói thật là máy chủ chưa có. */
function missingApiState({ feature = "chức năng này", endpoint, text } = {}) {
  const node = emptyState({ icon: "lock", tone: "muted", title: `Máy chủ chưa hỗ trợ ${feature}.`, text });
  if (endpoint) node.append(h("code", { class: "code" }, endpoint));
  node.classList.add("is-missing");
  return node;
}

/* 404/405/501 mà KHÔNG có mã lỗi riêng (hoặc HTTP_ERROR) = route chưa tồn tại trên máy chủ. */
function isMissingApi(error) {
  return Boolean(error) && [404, 405, 501].includes(error.status) && (!error.code || error.code === "HTTP_ERROR");
}

/* 422 INVALID_INPUT: thường là PATCH mang khóa mà backend hiện tại chưa biết. */
function isUnsupportedField(error) {
  return Boolean(error) && error.status === 422 && error.code === "INVALID_INPUT";
}

/* ── Số đếm lên ────────────────────────────────────────────────── */

/* countUp(el, 1946, {duration: 1100, format: fmtNumber}) — ease-out cubic từ giá trị trước (hoặc 0).
   Tắt hiệu ứng / tab ẩn / giá trị không đổi → gán thẳng giá trị cuối. Trả về hàm hủy. */
function countUp(el, to, { duration = 1100, format = fmtNumber } = {}) {
  if (!el) return () => {};
  if (el._countUpStop) el._countUpStop();
  if (typeof to !== "number" || !Number.isFinite(to)) {
    el.textContent = to == null ? "—" : String(to);
    el._countValue = undefined;
    return () => {};
  }
  const from = typeof el._countValue === "number" ? el._countValue : 0;
  el._countValue = to;
  const motion = typeof Shell !== "undefined" && Shell && typeof Shell.motionOn === "function" ? Shell.motionOn() : true;
  if (!motion || document.hidden || from === to || duration <= 0) {
    el.textContent = format(to);
    return () => {};
  }
  const integral = Number.isInteger(from) && Number.isInteger(to);
  const start = performance.now();
  let frame = 0;
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    const v = from + (to - from) * eased;
    el.textContent = format(integral ? Math.round(v) : v);
    if (t < 1) frame = requestAnimationFrame(step);
    else el._countUpStop = null;
  };
  el.textContent = format(from);
  frame = requestAnimationFrame(step);
  const stop = () => { cancelAnimationFrame(frame); el._countUpStop = null; };
  el._countUpStop = stop;
  return stop;
}

/* ── Định dạng ─────────────────────────────────────────────────── */

/* 1946 → "1.946" (vi-VN). null/NaN → "—". */
function fmtNumber(n) {
  if (n === null || n === undefined || n === "" || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString("vi-VN");
}

/* 15360 → "15 KB"; 2516582 → "2.4 MB"; 155189248 → "148 MB" (bỏ ".0"). */
function fmtBytes(bytes) {
  const b = Number(bytes);
  if (bytes === null || bytes === undefined || !Number.isFinite(b) || b < 0) return "—";
  if (b < 1024) return `${Math.round(b)} B`;
  const kb = Math.round(b / 1024);
  if (kb < 1024) return `${kb} KB`;
  const units = ["MB", "GB", "TB"];
  let v = b / 1048576;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) { v /= 1024; u++; }
  const text = v.toFixed(1).replace(/\.0$/, "");
  return `${text} ${units[u]}`;
}

/* "vừa xong" (<60s) · "N phút trước" · "N giờ trước" (<24h) · "hôm qua" · "N ngày trước" (<7 ngày lịch) · dd/mm/yyyy.
   Nhận Date | chuỗi ISO | epoch giây (số < 1e12) | epoch ms. Không đọc được → "—". */
function fmtRelative(value, now = Date.now()) {
  if (value === null || value === undefined || value === "") return "—";
  const d = value instanceof Date ? value : new Date(typeof value === "number" && Math.abs(value) < 1e12 ? value * 1000 : value);
  const t = d.getTime();
  if (Number.isNaN(t)) return "—";
  const nowMs = now instanceof Date ? now.getTime() : now;
  const sec = Math.max(0, (nowMs - t) / 1000);
  if (sec < 60) return "vừa xong";
  if (sec < 3600) return `${Math.floor(sec / 60)} phút trước`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} giờ trước`;
  const dayStart = (ms) => { const x = new Date(ms); x.setHours(0, 0, 0, 0); return x.getTime(); };
  const days = Math.round((dayStart(nowMs) - dayStart(t)) / 86400000);
  if (days <= 1) return "hôm qua";
  if (days < 7) return `${days} ngày trước`;
  return fmtDate(d);
}

/* "16:12:05" (hoặc "16:12" với {seconds: false}); không truyền giá trị = bây giờ. */
function fmtClock(value = new Date(), { seconds = true } = {}) {
  const d = value instanceof Date ? value : new Date(typeof value === "number" && Math.abs(value) < 1e12 ? value * 1000 : value);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n) => String(n).padStart(2, "0");
  return seconds ? `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` : `${p(d.getHours())}:${p(d.getMinutes())}`;
}

/* "12/09/2026" (+ " 16:12" với {time: true}). */
function fmtDate(value, { time = false } = {}) {
  if (value === null || value === undefined || value === "") return "—";
  const d = value instanceof Date ? value : new Date(typeof value === "number" && Math.abs(value) < 1e12 ? value * 1000 : value);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n) => String(n).padStart(2, "0");
  const date = `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`;
  return time ? `${date} ${p(d.getHours())}:${p(d.getMinutes())}` : date;
}

/* Thời lượng tính bằng MILI GIÂY: 640 → "640ms"; 6200 → "6.2s"; 754000 → "12 phút";
   8040000 → "2 giờ 14 phút"; 273600000 → "3 ngày 4 giờ". */
function fmtDuration(ms) {
  const v = Number(ms);
  if (ms === null || ms === undefined || !Number.isFinite(v) || v < 0) return "—";
  if (v < 1000) return `${Math.round(v)}ms`;
  if (v < 60000) return `${(v / 1000).toFixed(1)}s`;
  const totalMin = Math.floor(v / 60000);
  if (totalMin < 60) return `${totalMin} phút`;
  const hours = Math.floor(totalMin / 60);
  const minutes = totalMin % 60;
  if (hours < 24) return minutes ? `${hours} giờ ${minutes} phút` : `${hours} giờ`;
  const days = Math.floor(hours / 24);
  const restH = hours % 24;
  return restH ? `${days} ngày ${restH} giờ` : `${days} ngày`;
}

/* ── Tiện ích ──────────────────────────────────────────────────── */

/* debounce(fn, 300) → hàm trễ; .cancel() hủy lần gọi đang chờ, .flush() chạy ngay. */
function debounce(fn, ms = 200) {
  let timer = null;
  let lastArgs = null;
  const debounced = (...args) => {
    lastArgs = args;
    clearTimeout(timer);
    timer = setTimeout(() => { timer = null; fn(...lastArgs); }, ms);
  };
  debounced.cancel = () => { clearTimeout(timer); timer = null; };
  debounced.flush = () => { if (timer) { clearTimeout(timer); timer = null; fn(...lastArgs); } };
  return debounced;
}

/* Sao chép + toast "Đã sao chép." / lỗi. Có đường dự phòng khi trang chạy HTTP thường trong LAN
   (navigator.clipboard chỉ có ở secure context). → Promise<bool>. */
async function copyText(text, { notify = true } = {}) {
  const value = String(text ?? "");
  let ok = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      ok = true;
    }
  } catch { ok = false; }
  if (!ok) {
    // select() dời focus vào ô tạm: trả lại cho nút đã bấm (người dùng bàn phím không bị rơi về <body>).
    const prev = document.activeElement;
    const area = h("textarea", { style: "position:fixed;top:-1000px;left:-1000px;opacity:0", "aria-hidden": "true", readonly: true });
    area.value = value;
    document.body.append(area);
    area.select();
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    area.remove();
    if (prev && prev !== document.body && prev.isConnected && typeof prev.focus === "function") {
      try { prev.focus({ preventScroll: true }); } catch { /* không nhận focus */ }
    }
  }
  if (notify) toast(ok ? "Đã sao chép." : "Không sao chép được (trình duyệt chặn clipboard).", ok ? "ok" : "danger");
  return ok;
}

/* "Bùi Tiến Dũng" → "BD" (chữ đầu của từ đầu + từ cuối); "dung.bt" → "DB"; "admin" → "AD". */
function initials(name) {
  const words = String(name ?? "").trim().split(/[\s._-]+/).filter(Boolean);
  if (!words.length) return "?";
  const first = [...words[0]];
  if (words.length === 1) return first.slice(0, 2).join("").toUpperCase();
  return `${first[0]}${[...words[words.length - 1]][0]}`.toUpperCase();
}

/* Màu avatar cố định theo chuỗi (bảng màu avatar của prototype) → {bg, color}. */
function avatarColor(seed) {
  const palette = [
    { bg: "#fde8e8", color: "#b91c1c" },
    { bg: "#e3f5ea", color: "#15803d" },
    { bg: "#fdf1e2", color: "#b45309" },
    { bg: "#e8efff", color: "#1d4ed8" },
  ];
  let hash = 0;
  for (const ch of String(seed ?? "")) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  return palette[hash % palette.length];
}
