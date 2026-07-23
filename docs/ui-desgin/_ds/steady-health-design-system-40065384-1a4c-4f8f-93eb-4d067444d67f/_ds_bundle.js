/* @ds-bundle: {"format":4,"namespace":"SteadyHealthDesignSystem_400653","components":[{"name":"DataTable","sourcePath":"components/data/DataTable.jsx"},{"name":"Banner","sourcePath":"components/feedback/Banner.jsx"},{"name":"Dialog","sourcePath":"components/feedback/Dialog.jsx"},{"name":"StatusPill","sourcePath":"components/feedback/StatusPill.jsx"},{"name":"Toast","sourcePath":"components/feedback/Toast.jsx"},{"name":"ChecklistItem","sourcePath":"components/flow/ChecklistItem.jsx"},{"name":"StepBar","sourcePath":"components/flow/StepBar.jsx"},{"name":"Button","sourcePath":"components/forms/Button.jsx"},{"name":"ChipGroup","sourcePath":"components/forms/ChipGroup.jsx"},{"name":"Field","sourcePath":"components/forms/Field.jsx"}],"sourceHashes":{"components/data/DataTable.jsx":"577874a719d5","components/feedback/Banner.jsx":"3c6e0a47d96d","components/feedback/Dialog.jsx":"e5f825fd4354","components/feedback/StatusPill.jsx":"2ca0014e9eb0","components/feedback/Toast.jsx":"970678c485dd","components/flow/ChecklistItem.jsx":"9e582f655b79","components/flow/StepBar.jsx":"942fd3910b08","components/forms/Button.jsx":"b0dca1fd1c73","components/forms/ChipGroup.jsx":"30ebaa9ee26c","components/forms/Field.jsx":"c497ed674751","ui_kits/feetforceplate/App.jsx":"9e0ffbf8ece3","ui_kits/feetforceplate/FocusScreen.jsx":"fe434404531a","ui_kits/feetforceplate/Heatmap.jsx":"e66651035359","ui_kits/feetforceplate/HubScreen.jsx":"8b4c99187b7e","ui_kits/feetforceplate/ResultScreen.jsx":"fae00cf74924","ui_kits/feetforceplate/TopBar.jsx":"bbe4cc39584c","ui_kits/feetforceplate/WizardScreen.jsx":"e16d5de914bd"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.SteadyHealthDesignSystem_400653 = window.SteadyHealthDesignSystem_400653 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/feedback/Banner.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const TONES = {
  warning: {
    fg: "var(--warning-fg)",
    bg: "var(--warning-bg)",
    border: "var(--warning-border)"
  },
  info: {
    fg: "var(--info-fg)",
    bg: "var(--info-bg)",
    border: "var(--info-border)"
  },
  success: {
    fg: "var(--success-fg)",
    bg: "var(--success-bg)",
    border: "var(--success-border)"
  },
  danger: {
    fg: "var(--danger-fg)",
    bg: "var(--danger-bg)",
    border: "var(--danger-border)"
  }
};
const ICONS = {
  warning: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
    d: "M12 9v4"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 17h.01"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M10.3 3.9 2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"
  })),
  info: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "9"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 11v5M12 8h.01"
  })),
  success: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "9"
  }), /*#__PURE__*/React.createElement("path", {
    d: "m9 12 2 2 4-4"
  })),
  danger: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "9"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 8v4M12 16h.01"
  }))
};

/**
 * Banner — full-width, top-of-page, non-blocking notice. Use for persistent
 * degraded states (e.g. grace-period network loss). Never interrupts a scan.
 */
function Banner({
  tone = "info",
  title,
  children,
  action,
  onClose,
  style,
  ...rest
}) {
  const t = TONES[tone] || TONES.info;
  return /*#__PURE__*/React.createElement("div", _extends({
    role: "status",
    style: {
      display: "flex",
      alignItems: "flex-start",
      gap: "var(--space-3)",
      width: "100%",
      padding: "var(--space-3) var(--space-4)",
      background: t.bg,
      borderTop: `1px solid ${t.border}`,
      borderBottom: `1px solid ${t.border}`,
      color: t.fg,
      boxSizing: "border-box",
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("svg", {
    width: "20",
    height: "20",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true",
    style: {
      flex: "none",
      marginTop: 2
    }
  }, ICONS[tone]), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      color: "var(--text-primary)"
    }
  }, title && /*#__PURE__*/React.createElement("div", {
    style: {
      font: "var(--text-body)",
      fontWeight: 600,
      color: t.fg
    }
  }, title), /*#__PURE__*/React.createElement("div", {
    style: {
      font: "var(--text-body)"
    }
  }, children)), action, onClose && /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onClose,
    "aria-label": "\u5173\u95ED",
    style: {
      flex: "none",
      background: "none",
      border: "none",
      cursor: "pointer",
      color: t.fg,
      padding: 4,
      borderRadius: 6,
      display: "inline-flex"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "18",
    height: "18",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M18 6 6 18M6 6l12 12"
  }))));
}
Object.assign(__ds_scope, { Banner });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Banner.jsx", error: String((e && e.message) || e) }); }

// components/feedback/StatusPill.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const TONES = {
  success: {
    fg: "var(--success-fg)",
    bg: "var(--success-bg)",
    border: "var(--success-border)"
  },
  warning: {
    fg: "var(--warning-fg)",
    bg: "var(--warning-bg)",
    border: "var(--warning-border)"
  },
  danger: {
    fg: "var(--danger-fg)",
    bg: "var(--danger-bg)",
    border: "var(--danger-border)"
  },
  info: {
    fg: "var(--info-fg)",
    bg: "var(--info-bg)",
    border: "var(--info-border)"
  },
  neutral: {
    fg: "var(--text-secondary)",
    bg: "var(--bg-sunken)",
    border: "var(--border-default)"
  }
};

/**
 * StatusPill — dot/icon + TEXT, pill shape, light bg. Text is NEVER omitted;
 * status = icon + text + color together. info can slowly spin its icon.
 */
function StatusPill({
  tone = "neutral",
  children,
  icon = "dot",
  spin = false,
  style,
  ...rest
}) {
  const t = TONES[tone] || TONES.neutral;
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "var(--space-2)",
      height: 28,
      padding: "0 var(--space-3)",
      borderRadius: "var(--radius-pill)",
      font: "var(--text-secondary-size)",
      fontWeight: 500,
      color: t.fg,
      background: t.bg,
      border: `1px solid ${t.border}`,
      whiteSpace: "nowrap",
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement(PillMark, {
    icon: icon,
    tone: tone,
    spin: spin
  }), children);
}
function PillMark({
  icon,
  spin
}) {
  if (icon === "dot") {
    return /*#__PURE__*/React.createElement("span", {
      style: {
        width: 8,
        height: 8,
        borderRadius: "999px",
        background: "currentColor",
        flex: "none"
      }
    });
  }
  const paths = {
    check: /*#__PURE__*/React.createElement("path", {
      d: "M20 6 9 17l-5-5"
    }),
    x: /*#__PURE__*/React.createElement("path", {
      d: "M18 6 6 18M6 6l12 12"
    }),
    warning: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M12 9v4"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M12 17h.01"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10.3 3.9 2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"
    })),
    spinner: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M21 12a9 9 0 1 1-6.2-8.6"
    }))
  };
  return /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.25",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true",
    style: spin ? {
      animation: "steady-spin 900ms linear infinite"
    } : undefined
  }, paths[icon] || paths.check);
}
if (typeof document !== "undefined" && !document.getElementById("steady-spin-kf")) {
  const s = document.createElement("style");
  s.id = "steady-spin-kf";
  s.textContent = "@keyframes steady-spin{to{transform:rotate(360deg)}}";
  document.head.appendChild(s);
}
Object.assign(__ds_scope, { StatusPill });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/StatusPill.jsx", error: String((e && e.message) || e) }); }

// components/data/DataTable.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * DataTable — screening records. 56px rows, 14/500 secondary header,
 * 16px body, zebra sunken rows, brand-alpha hover. Status column uses
 * StatusPill; IDs shown masked. Action column is a ghost text button.
 */
function DataTable({
  columns,
  rows,
  onRowAction,
  actionLabel = "查看",
  style,
  ...rest
}) {
  const [hover, setHover] = React.useState(-1);
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      overflow: "hidden",
      background: "var(--bg-surface)",
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("table", {
    style: {
      width: "100%",
      borderCollapse: "collapse",
      font: "var(--text-body)"
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, columns.map(c => /*#__PURE__*/React.createElement("th", {
    key: c.key,
    style: {
      textAlign: c.align || "left",
      font: "var(--text-secondary-size)",
      fontWeight: 500,
      color: "var(--text-secondary)",
      padding: "var(--space-3) var(--space-4)",
      background: "var(--bg-surface)",
      borderBottom: "1px solid var(--border-default)"
    }
  }, c.header)), onRowAction && /*#__PURE__*/React.createElement("th", {
    style: {
      borderBottom: "1px solid var(--border-default)",
      background: "var(--bg-surface)"
    }
  }))), /*#__PURE__*/React.createElement("tbody", null, rows.map((row, ri) => /*#__PURE__*/React.createElement("tr", {
    key: row.id ?? ri,
    onMouseEnter: () => setHover(ri),
    onMouseLeave: () => setHover(-1),
    style: {
      background: hover === ri ? "var(--brand-alpha-1)" : ri % 2 ? "var(--bg-sunken)" : "var(--bg-surface)",
      transition: "background var(--motion-fast)"
    }
  }, columns.map(c => /*#__PURE__*/React.createElement("td", {
    key: c.key,
    style: {
      height: "var(--size-table-row)",
      padding: "0 var(--space-4)",
      textAlign: c.align || "left",
      color: "var(--text-primary)",
      borderBottom: ri < rows.length - 1 ? "1px solid var(--border-default)" : "none",
      fontVariantNumeric: c.numeric ? "tabular-nums" : undefined,
      fontFamily: c.numeric ? "var(--font-num)" : undefined
    }
  }, c.render ? c.render(row[c.key], row) : row[c.key])), onRowAction && /*#__PURE__*/React.createElement("td", {
    style: {
      padding: "0 var(--space-4)",
      textAlign: "right",
      borderBottom: ri < rows.length - 1 ? "1px solid var(--border-default)" : "none"
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => onRowAction(row),
    style: {
      background: "none",
      border: "none",
      cursor: "pointer",
      color: "var(--brand-primary)",
      font: "var(--text-body)",
      padding: "var(--space-1) var(--space-2)"
    }
  }, actionLabel)))))));
}

/** Convenience: render a status cell as a StatusPill from a {tone,label,icon} value. */
DataTable.status = v => /*#__PURE__*/React.createElement(__ds_scope.StatusPill, {
  tone: v.tone,
  icon: v.icon || "dot",
  spin: v.spin
}, v.label);
Object.assign(__ds_scope, { DataTable });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/DataTable.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Toast.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Toast — bottom-right, transient success/info ONLY. Errors never use Toast.
 * 4s auto-dismiss, one at a time, aria-live polite, non-focus-stealing.
 */
function Toast({
  tone = "success",
  children,
  action,
  onClose,
  style,
  ...rest
}) {
  const fg = tone === "info" ? "var(--info-fg)" : "var(--success-fg)";
  const icon = tone === "info" ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "9"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 11v5M12 8h.01"
  })) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "9"
  }), /*#__PURE__*/React.createElement("path", {
    d: "m9 12 2 2 4-4"
  }));
  return /*#__PURE__*/React.createElement("div", _extends({
    role: "status",
    "aria-live": "polite",
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "var(--space-2)",
      maxWidth: 420,
      padding: "var(--space-3) var(--space-4)",
      background: "var(--bg-surface)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-control)",
      boxShadow: "var(--shadow-dialog)",
      font: "var(--text-body)",
      color: "var(--text-primary)",
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("svg", {
    width: "20",
    height: "20",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: fg,
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true",
    style: {
      flex: "none"
    }
  }, icon), /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1
    }
  }, children), action, onClose && /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onClose,
    "aria-label": "\u5173\u95ED",
    style: {
      background: "none",
      border: "none",
      cursor: "pointer",
      color: "var(--text-secondary)",
      padding: 2,
      display: "inline-flex"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "16",
    height: "16",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M18 6 6 18M6 6l12 12"
  }))));
}
Object.assign(__ds_scope, { Toast });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Toast.jsx", error: String((e && e.message) || e) }); }

// components/flow/ChecklistItem.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * ChecklistItem — one pre-check row: 24px status icon + item name + right-side
 * hint. Failure shows an ACTIONABLE fix ("请检查设备连接线"), never tech detail.
 */
function ChecklistItem({
  status = "pending",
  label,
  hint,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: "flex",
      alignItems: "center",
      gap: "var(--space-3)",
      minHeight: 56,
      padding: "var(--space-2) 0",
      borderBottom: "1px solid var(--border-default)",
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement(StatusIcon, {
    status: status
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      font: "var(--text-body)",
      color: "var(--text-primary)"
    }
  }, label), hint && /*#__PURE__*/React.createElement("span", {
    style: {
      font: "var(--text-secondary-size)",
      color: status === "fail" ? "var(--danger-fg)" : "var(--text-secondary)",
      textAlign: "right"
    }
  }, hint));
}
function StatusIcon({
  status
}) {
  const common = {
    width: 24,
    height: 24,
    flex: "none"
  };
  if (status === "running") {
    return /*#__PURE__*/React.createElement("svg", _extends({}, common, {
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "var(--brand-primary)",
      strokeWidth: "2",
      strokeLinecap: "round",
      "aria-label": "\u8FDB\u884C\u4E2D",
      style: {
        animation: "steady-spin 900ms linear infinite"
      }
    }), /*#__PURE__*/React.createElement("path", {
      d: "M21 12a9 9 0 1 1-6.2-8.6"
    }));
  }
  if (status === "pass") {
    return /*#__PURE__*/React.createElement("span", _extends({}, common, {
      style: {
        ...common,
        borderRadius: "999px",
        background: "var(--success-bg)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center"
      },
      "aria-label": "\u901A\u8FC7"
    }), /*#__PURE__*/React.createElement("svg", {
      width: "15",
      height: "15",
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "var(--success-fg)",
      strokeWidth: "2.5",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M20 6 9 17l-5-5"
    })));
  }
  if (status === "fail") {
    return /*#__PURE__*/React.createElement("span", _extends({}, common, {
      style: {
        ...common,
        borderRadius: "999px",
        background: "var(--danger-bg)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center"
      },
      "aria-label": "\u5931\u8D25"
    }), /*#__PURE__*/React.createElement("svg", {
      width: "14",
      height: "14",
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "var(--danger-fg)",
      strokeWidth: "2.5",
      strokeLinecap: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M18 6 6 18M6 6l12 12"
    })));
  }
  return /*#__PURE__*/React.createElement("span", _extends({}, common, {
    style: {
      ...common,
      borderRadius: "999px",
      border: "2px solid var(--border-strong)"
    },
    "aria-label": "\u5F85\u68C0"
  }));
}
if (typeof document !== "undefined" && !document.getElementById("steady-spin-kf")) {
  const s = document.createElement("style");
  s.id = "steady-spin-kf";
  s.textContent = "@keyframes steady-spin{to{transform:rotate(360deg)}}";
  document.head.appendChild(s);
}
Object.assign(__ds_scope, { ChecklistItem });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/flow/ChecklistItem.jsx", error: String((e && e.message) || e) }); }

// components/flow/StepBar.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * StepBar — thin linear wizard stepper. Current = brand; done = gray-green
 * check; not-reached = gray. Shown atop the wizard; no global nav during flow.
 */
function StepBar({
  steps,
  current = 0,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("ol", _extends({
    style: {
      display: "flex",
      alignItems: "center",
      gap: "var(--space-2)",
      listStyle: "none",
      margin: 0,
      padding: 0,
      ...style
    }
  }, rest), steps.map((label, i) => {
    const done = i < current;
    const active = i === current;
    return /*#__PURE__*/React.createElement(React.Fragment, {
      key: i
    }, /*#__PURE__*/React.createElement("li", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: "var(--space-2)"
      },
      "aria-current": active ? "step" : undefined
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 24,
        height: 24,
        borderRadius: "999px",
        flex: "none",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        font: "var(--text-secondary-size)",
        fontWeight: 600,
        background: done ? "var(--success-bg)" : active ? "var(--brand-primary)" : "var(--bg-sunken)",
        color: done ? "var(--success-fg)" : active ? "var(--text-on-brand)" : "var(--text-disabled)",
        border: done ? "1px solid var(--success-border)" : "none"
      }
    }, done ? /*#__PURE__*/React.createElement("svg", {
      width: "14",
      height: "14",
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2.5",
      strokeLinecap: "round",
      strokeLinejoin: "round",
      "aria-hidden": "true"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M20 6 9 17l-5-5"
    })) : i + 1), /*#__PURE__*/React.createElement("span", {
      style: {
        font: "var(--text-secondary-size)",
        fontWeight: active ? 600 : 400,
        color: active ? "var(--text-primary)" : done ? "var(--text-secondary)" : "var(--text-disabled)",
        whiteSpace: "nowrap"
      }
    }, label)), i < steps.length - 1 && /*#__PURE__*/React.createElement("span", {
      "aria-hidden": "true",
      style: {
        flex: 1,
        minWidth: 16,
        height: 1,
        background: i < current ? "var(--success-border)" : "var(--border-default)"
      }
    }));
  }));
}
Object.assign(__ds_scope, { StepBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/flow/StepBar.jsx", error: String((e && e.message) || e) }); }

// components/forms/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Steady Health primary control. One high-emphasis (primary) button per screen.
 * Copy is always a verb phrase. Solid & flat — no gradients.
 */
function Button({
  children,
  variant = "primary",
  // "primary" | "secondary" | "danger" | "ghost"
  size = "md",
  // "lg" (first-screen CTA, 64px) | "md" | "sm" (48px min)
  loading = false,
  loadingText,
  disabled = false,
  fullWidth = false,
  iconLeft = null,
  onClick,
  type = "button",
  style,
  ...rest
}) {
  const heights = {
    lg: 64,
    md: 56,
    sm: 48
  };
  const height = heights[size] ?? 56;
  const isDisabled = disabled || loading;
  const base = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "var(--space-2)",
    height,
    minHeight: "var(--size-touch-min)",
    padding: "0 var(--space-6)",
    borderRadius: "var(--radius-control)",
    font: "var(--text-body-lg)",
    fontWeight: 600,
    lineHeight: 1,
    cursor: isDisabled ? "not-allowed" : "pointer",
    width: fullWidth ? "100%" : undefined,
    border: "1px solid transparent",
    transition: "background var(--motion-fast), border-color var(--motion-fast), color var(--motion-fast)",
    outlineOffset: "var(--focus-offset)",
    whiteSpace: "nowrap",
    ...style
  };
  const variants = {
    primary: {
      background: isDisabled && !loading ? "var(--bg-sunken)" : "var(--brand-primary)",
      color: isDisabled && !loading ? "var(--text-disabled)" : "var(--text-on-brand)",
      borderColor: "transparent"
    },
    secondary: {
      background: "var(--bg-surface)",
      color: isDisabled ? "var(--text-disabled)" : "var(--text-primary)",
      borderColor: "var(--border-strong)"
    },
    danger: {
      background: "var(--bg-surface)",
      color: "var(--danger-fg)",
      borderColor: "var(--danger-border)"
    },
    ghost: {
      background: "transparent",
      color: "var(--brand-primary)",
      borderColor: "transparent",
      padding: "0 var(--space-2)"
    }
  };
  const hoverBg = {
    primary: "var(--brand-primary-hover)",
    secondary: "var(--bg-sunken)",
    danger: "var(--danger-bg)",
    ghost: "var(--brand-alpha-1)"
  };
  const [hover, setHover] = React.useState(false);
  const composed = {
    ...base,
    ...variants[variant]
  };
  if (hover && !isDisabled) {
    if (variant === "primary") composed.background = hoverBg.primary;else composed.background = hoverBg[variant];
  }
  if (loading) composed.opacity = 1; // stays branded; spinner conveys busy

  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    disabled: isDisabled,
    onClick: onClick,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: composed,
    "aria-busy": loading || undefined
  }, rest), loading ? /*#__PURE__*/React.createElement(Spinner, null) : iconLeft, /*#__PURE__*/React.createElement("span", null, loading && loadingText ? loadingText : children));
}
function Spinner() {
  return /*#__PURE__*/React.createElement("span", {
    style: {
      width: "var(--btn-spinner-size)",
      height: "var(--btn-spinner-size)",
      borderRadius: "999px",
      border: "2px solid currentColor",
      borderTopColor: "transparent",
      opacity: 0.9,
      display: "inline-block",
      animation: "steady-spin 700ms linear infinite"
    }
  });
}
if (typeof document !== "undefined" && !document.getElementById("steady-spin-kf")) {
  const s = document.createElement("style");
  s.id = "steady-spin-kf";
  s.textContent = "@keyframes steady-spin{to{transform:rotate(360deg)}}";
  document.head.appendChild(s);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Button.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Dialog.jsx
try { (() => {
/**
 * Dialog — the ONLY blocking surface, for must-decide moments (stop scan,
 * profile conflict, network gate). ≤2 buttons. Default focus on the SAFE
 * action (cancel). Danger confirm is the one place a filled-red button lives.
 */
function Dialog({
  open = true,
  title,
  children,
  confirmLabel = "确定",
  cancelLabel = "取消",
  onConfirm,
  onCancel,
  danger = false,
  style
}) {
  const cancelRef = React.useRef(null);
  React.useEffect(() => {
    if (!open) return;
    const onKey = e => {
      if (e.key === "Escape") onCancel && onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onCancel]);
  if (!open) return null;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "fixed",
      inset: 0,
      background: "var(--overlay)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      zIndex: 1000,
      padding: "var(--space-6)"
    },
    onMouseDown: e => {
      if (e.target === e.currentTarget) onCancel && onCancel();
    }
  }, /*#__PURE__*/React.createElement("div", {
    role: "alertdialog",
    "aria-modal": "true",
    "aria-label": title,
    style: {
      width: "100%",
      maxWidth: "var(--dialog-max-width)",
      background: "var(--bg-surface)",
      borderRadius: "var(--radius-card)",
      boxShadow: "var(--shadow-dialog)",
      padding: "var(--space-6)",
      ...style
    }
  }, title && /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      font: "var(--text-h3)",
      color: "var(--text-primary)"
    }
  }, title), /*#__PURE__*/React.createElement("div", {
    style: {
      margin: "var(--space-3) 0 var(--space-6)",
      font: "var(--text-body)",
      color: "var(--text-secondary)"
    }
  }, children), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "flex-end",
      gap: "var(--space-3)"
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Button, {
    variant: "secondary",
    size: "sm",
    autoFocus: true,
    onClick: onCancel
  }, cancelLabel), danger ? /*#__PURE__*/React.createElement(FilledDanger, {
    onClick: onConfirm
  }, confirmLabel) : /*#__PURE__*/React.createElement(__ds_scope.Button, {
    variant: "primary",
    size: "sm",
    onClick: onConfirm
  }, confirmLabel))));
}

/* The single place in the whole system where a filled-red button is allowed. */
function FilledDanger({
  children,
  onClick
}) {
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onClick,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      height: 48,
      minHeight: "var(--size-touch-min)",
      padding: "0 var(--space-6)",
      borderRadius: "var(--radius-control)",
      font: "var(--text-body-lg)",
      fontWeight: 600,
      lineHeight: 1,
      color: "var(--text-on-brand)",
      background: hover ? "#A82F2F" : "var(--danger-fg)",
      border: "1px solid transparent",
      cursor: "pointer",
      transition: "background var(--motion-fast)"
    }
  }, children);
}
Object.assign(__ds_scope, { Dialog });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Dialog.jsx", error: String((e && e.message) || e) }); }

// components/forms/ChipGroup.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Multi-select tag chips (e.g. medical history: 高血压 / 糖尿病 / 既往下肢损伤).
 * Selected = brand subtle fill + border + check. Solid & flat.
 */
function ChipGroup({
  options,
  value = [],
  onChange,
  style,
  ...rest
}) {
  const set = new Set(value);
  const toggle = v => {
    const next = new Set(set);
    next.has(v) ? next.delete(v) : next.add(v);
    onChange && onChange([...next]);
  };
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: "var(--space-2)",
      ...style
    },
    role: "group"
  }, rest), options.map(opt => {
    const val = typeof opt === "string" ? opt : opt.value;
    const label = typeof opt === "string" ? opt : opt.label;
    const selected = set.has(val);
    return /*#__PURE__*/React.createElement(Chip, {
      key: val,
      label: label,
      selected: selected,
      onClick: () => toggle(val)
    });
  }));
}
function Chip({
  label,
  selected,
  onClick
}) {
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    "aria-pressed": selected,
    onClick: onClick,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "var(--space-2)",
      minHeight: "var(--size-touch-min)",
      padding: "0 var(--space-4)",
      borderRadius: "var(--radius-pill)",
      font: "var(--text-body)",
      cursor: "pointer",
      transition: "background var(--motion-fast), border-color var(--motion-fast)",
      background: selected ? "var(--brand-primary-subtle)" : hover ? "var(--bg-sunken)" : "var(--bg-surface)",
      color: selected ? "var(--brand-primary)" : "var(--text-primary)",
      border: `1px solid ${selected ? "var(--brand-primary-border)" : "var(--border-strong)"}`,
      outlineOffset: "var(--focus-offset)"
    }
  }, selected && /*#__PURE__*/React.createElement("svg", {
    width: "16",
    height: "16",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.25",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M20 6 9 17l-5-5"
  })), label);
}
Object.assign(__ds_scope, { ChipGroup });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/ChipGroup.jsx", error: String((e && e.message) || e) }); }

// components/forms/Field.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Steady Health text field. Label is ALWAYS visible above the input
 * (never placeholder-as-label). Optional fields tagged "(选填)".
 * Unit (cm/kg) sits inside on the right. Validate on blur/submit.
 */
function Field({
  label,
  value,
  onChange,
  optional = false,
  unit,
  placeholder,
  error,
  hint,
  type = "text",
  disabled = false,
  id,
  style,
  ...rest
}) {
  const inputId = id || React.useId();
  const describedBy = error ? `${inputId}-err` : hint ? `${inputId}-hint` : undefined;
  const [focus, setFocus] = React.useState(false);
  const borderColor = error ? "var(--danger-fg)" : focus ? "var(--brand-primary)" : "var(--border-strong)";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "var(--space-2)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("label", {
    htmlFor: inputId,
    style: {
      font: "var(--text-secondary-size)",
      fontWeight: 500,
      color: "var(--text-primary)"
    }
  }, label, optional && /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-disabled)",
      fontWeight: 400
    }
  }, "(\u9009\u586B)")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      display: "flex",
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("input", _extends({
    id: inputId,
    type: type,
    value: value,
    onChange: onChange,
    placeholder: placeholder,
    disabled: disabled,
    onFocus: () => setFocus(true),
    onBlur: () => setFocus(false),
    "aria-invalid": !!error,
    "aria-describedby": describedBy,
    style: {
      width: "100%",
      height: "var(--size-input)",
      padding: unit ? "0 44px 0 var(--space-3)" : "0 var(--space-3)",
      font: "var(--text-body)",
      color: disabled ? "var(--text-disabled)" : "var(--text-primary)",
      background: disabled ? "var(--bg-sunken)" : "var(--bg-surface)",
      border: `1px solid ${borderColor}`,
      borderRadius: "var(--radius-control)",
      outline: focus ? "var(--focus-ring)" : "none",
      outlineOffset: "var(--focus-offset)",
      transition: "border-color var(--motion-fast)",
      boxSizing: "border-box"
    }
  }, rest)), unit && /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      right: "var(--space-3)",
      font: "var(--text-body)",
      color: "var(--text-secondary)",
      pointerEvents: "none"
    }
  }, unit)), error ? /*#__PURE__*/React.createElement("span", {
    id: `${inputId}-err`,
    role: "alert",
    style: {
      font: "var(--text-secondary-size)",
      color: "var(--danger-fg)"
    }
  }, error) : hint ? /*#__PURE__*/React.createElement("span", {
    id: `${inputId}-hint`,
    style: {
      font: "var(--text-secondary-size)",
      color: "var(--text-secondary)"
    }
  }, hint) : null);
}
Object.assign(__ds_scope, { Field });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Field.jsx", error: String((e && e.message) || e) }); }

// ui_kits/feetforceplate/App.jsx
try { (() => {
// FeetForcePlate — App state machine: hub → wizard → focus → result.
// Includes a bottom-right Toast queue (never during a scan).
const APP = window.SteadyHealthDesignSystem_400653;
function App() {
  const {
    Toast,
    Banner
  } = APP;
  const [screen, setScreen] = React.useState("hub");
  const [toast, setToast] = React.useState(null);
  const [online, setOnline] = React.useState(true);
  const showToast = (msg, tone = "success") => {
    setToast({
      msg,
      tone
    });
    setTimeout(() => setToast(null), 4000);
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      display: "flex",
      flexDirection: "column",
      fontFamily: "var(--font-ui)",
      color: "var(--text-primary)"
    }
  }, screen !== "focus" && /*#__PURE__*/React.createElement(TopBar, {
    deviceReady: true,
    online: online
  }), !online && screen !== "focus" && /*#__PURE__*/React.createElement(Banner, {
    tone: "warning",
    title: "\u7F51\u7EDC\u4E2D\u65AD",
    onClose: () => setOnline(true)
  }, "\u5F53\u524D\u68C0\u6D4B\u4E0D\u53D7\u5F71\u54CD,\u7CFB\u7EDF\u4F1A\u81EA\u52A8\u91CD\u8FDE\u3002"), screen === "hub" && /*#__PURE__*/React.createElement(HubScreen, {
    onStart: () => setScreen("wizard"),
    onOpen: () => showToast("正在打开报告…", "info")
  }), screen === "wizard" && /*#__PURE__*/React.createElement(WizardScreen, {
    onDone: () => setScreen("focus"),
    onExit: () => setScreen("hub")
  }), screen === "focus" && /*#__PURE__*/React.createElement(FocusScreen, {
    onComplete: () => setScreen("result"),
    onStop: () => {
      setScreen("hub");
    }
  }), screen === "result" && /*#__PURE__*/React.createElement(ResultScreen, {
    onViewReport: () => showToast("PDF 已导出"),
    onNext: () => setScreen("wizard")
  }), toast && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "fixed",
      right: "var(--toast-offset)",
      bottom: "var(--toast-offset)",
      zIndex: 2000
    }
  }, /*#__PURE__*/React.createElement(Toast, {
    tone: toast.tone,
    onClose: () => setToast(null)
  }, toast.msg)));
}
window.App = App;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/feetforceplate/App.jsx", error: String((e && e.message) || e) }); }

// ui_kits/feetforceplate/FocusScreen.jsx
try { (() => {
// FeetForcePlate — P-07 Focus: full-screen scan. Left heatmap canvas (~60%),
// right subject instruction + countdown. Only control is a danger secondary
// "stop" button (bottom-right) → confirm Dialog. No navigation.
const FC = window.SteadyHealthDesignSystem_400653;
function FocusScreen({
  onComplete,
  onStop
}) {
  const {
    Dialog
  } = FC;
  const [remaining, setRemaining] = React.useState(12);
  const [confirm, setConfirm] = React.useState(false);
  React.useEffect(() => {
    if (confirm) return; // pause countdown while confirming
    if (remaining <= 0) {
      onComplete();
      return;
    }
    const id = setTimeout(() => setRemaining(r => r - 1), 1000);
    return () => clearTimeout(id);
  }, [remaining, confirm]);
  const pct = Math.round((12 - remaining) / 12 * 100);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: "flex",
      background: "var(--bg-page)",
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flexBasis: "60%",
      padding: "var(--space-8)",
      display: "flex",
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement(Heatmap, {
    live: true,
    side: "both"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      borderLeft: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
      padding: "var(--space-12) var(--space-8)",
      display: "flex",
      flexDirection: "column",
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: "flex",
      flexDirection: "column",
      justifyContent: "center",
      gap: "var(--space-8)"
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      font: "var(--text-secondary-size)",
      color: "var(--brand-primary)",
      fontWeight: 600,
      letterSpacing: 2
    }
  }, "\u6B63\u5728\u68C0\u6D4B"), /*#__PURE__*/React.createElement("p", {
    style: {
      font: "var(--text-body-lg)",
      fontSize: 24,
      lineHeight: 1.5,
      color: "var(--text-primary)",
      margin: "var(--space-2) 0 0",
      maxWidth: 360
    }
  }, "\u8BF7\u53CC\u811A\u81EA\u7136\u7AD9\u7ACB\u4E8E\u538B\u529B\u57AB\u4E2D\u592E,", /*#__PURE__*/React.createElement("br", null), "\u4FDD\u6301\u8EAB\u4F53\u653E\u677E,\u76EE\u89C6\u524D\u65B9\u3002")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      font: "var(--text-countdown)",
      fontSize: 96,
      color: "var(--brand-primary)",
      fontVariantNumeric: "tabular-nums",
      lineHeight: 1
    }
  }, String(remaining).padStart(2, "0")), /*#__PURE__*/React.createElement("div", {
    style: {
      font: "var(--text-body)",
      color: "var(--text-secondary)",
      marginTop: "var(--space-2)"
    }
  }, "\u5269\u4F59\u91C7\u96C6\u65F6\u95F4(\u79D2)")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 8,
      borderRadius: 999,
      background: "var(--bg-sunken)",
      overflow: "hidden",
      maxWidth: 360
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: "100%",
      width: pct + "%",
      background: "var(--brand-bright)",
      borderRadius: 999,
      transition: "width 1s linear"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      font: "var(--text-secondary-size)",
      color: "var(--text-secondary)",
      marginTop: "var(--space-2)"
    }
  }, "\u91C7\u96C6\u8FDB\u884C\u4E2D,\u8BF7\u52FF\u79BB\u5F00\u538B\u529B\u57AB"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "flex-end"
    }
  }, /*#__PURE__*/React.createElement(FC_Stop, {
    onClick: () => setConfirm(true)
  }))), /*#__PURE__*/React.createElement(Dialog, {
    open: confirm,
    danger: true,
    title: "\u505C\u6B62\u672C\u6B21\u68C0\u6D4B?",
    confirmLabel: "\u505C\u6B62\u68C0\u6D4B",
    cancelLabel: "\u7EE7\u7EED\u68C0\u6D4B",
    onConfirm: onStop,
    onCancel: () => setConfirm(false)
  }, "\u5DF2\u91C7\u96C6\u7684\u6570\u636E\u5C06\u4E0D\u751F\u6210\u62A5\u544A,\u53EF\u7ACB\u5373\u91CD\u65B0\u5F00\u59CB\u3002"));
}
function FC_Stop({
  onClick
}) {
  const {
    Button
  } = FC;
  return /*#__PURE__*/React.createElement(Button, {
    variant: "danger",
    size: "sm",
    onClick: onClick
  }, "\u505C\u6B62\u68C0\u6D4B");
}
window.FocusScreen = FocusScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/feetforceplate/FocusScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/feetforceplate/Heatmap.jsx
try { (() => {
// FeetForcePlate — plantar pressure heatmap on the light data canvas.
// The core data visualization: light canvas + blue grid + isolated heat scale.
// Pressure blobs are soft "energy" radial gradients (not hard color tiles);
// low pressure fades into the canvas, high pressure gets a soft outer glow.

function Heatmap({
  live = false,
  side = "both"
}) {
  const canvasRef = React.useRef(null);
  React.useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const draw = t => {
      const w = cv.clientWidth,
        h = cv.clientHeight;
      cv.width = w * dpr;
      cv.height = h * dpr;
      const ctx = cv.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const feet = side === "both" ? [0.34, 0.66] : side === "left" ? [0.4] : [0.6];
      const pulse = live ? 1 + 0.06 * Math.sin(t / 380) : 1;
      feet.forEach((cx0, fi) => {
        const cx = cx0 * w;
        // pressure regions: heel, arch(low), forefoot, big toe
        const regions = [{
          y: 0.72,
          r: 0.14,
          load: 0.95
        },
        // heel — high
        {
          y: 0.52,
          r: 0.10,
          load: 0.30
        },
        // arch — low
        {
          y: 0.34,
          r: 0.15,
          load: 0.90
        },
        // forefoot — high
        {
          y: 0.20,
          r: 0.07,
          load: 0.55
        },
        // toes
        {
          y: 0.16,
          r: 0.05,
          load: 0.72,
          dx: fi === 0 ? -0.03 : 0.03
        } // big toe
        ];
        regions.forEach(rg => {
          const gy = rg.y * h;
          const gx = cx + (rg.dx || 0) * w;
          const rad = rg.r * h * (0.9 + rg.load * 0.4) * pulse;
          const g = ctx.createRadialGradient(gx, gy, rad * 0.1, gx, gy, rad);
          const col = heatColor(rg.load);
          g.addColorStop(0, rgba(col, 0.85 * rg.load + 0.1));
          g.addColorStop(0.5, rgba(col, (0.85 * rg.load + 0.1) * 0.5));
          g.addColorStop(1, rgba(col, 0));
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(gx, gy, rad, 0, Math.PI * 2);
          ctx.fill();
        });
      });
    };
    let raf;
    const loop = t => {
      draw(t);
      if (live) raf = requestAnimationFrame(loop);
    };
    if (live) raf = requestAnimationFrame(loop);else draw(0);
    return () => raf && cancelAnimationFrame(raf);
  }, [live, side]);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      width: "100%",
      height: "100%",
      borderRadius: "var(--radius-card)",
      background: "var(--viz-canvas)",
      border: "1px solid var(--viz-canvas-border)",
      backgroundImage: "linear-gradient(var(--viz-grid) 1px,transparent 1px),linear-gradient(90deg,var(--viz-grid) 1px,transparent 1px)",
      backgroundSize: "28px 28px",
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("canvas", {
    ref: canvasRef,
    style: {
      position: "absolute",
      inset: 0,
      width: "100%",
      height: "100%"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      top: 12,
      left: 12,
      font: "var(--text-secondary-size)",
      color: "var(--viz-axis-label)",
      background: "rgba(255,255,255,.7)",
      padding: "2px 8px",
      borderRadius: 6
    }
  }, "\u8DB3\u5E95\u538B\u529B\u5206\u5E03"), /*#__PURE__*/React.createElement(Legend, null));
}
function Legend() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      bottom: 12,
      right: 12,
      display: "flex",
      flexDirection: "column",
      gap: 4,
      background: "rgba(255,255,255,.75)",
      padding: "8px 10px",
      borderRadius: 8,
      border: "1px solid var(--viz-canvas-border)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      font: "var(--text-secondary-size)",
      color: "var(--viz-axis-label)"
    }
  }, "\u538B\u529B"), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 120,
      height: 10,
      borderRadius: 5,
      background: "linear-gradient(90deg,var(--viz-heat-1),var(--viz-heat-2),var(--viz-heat-3),var(--viz-heat-4),var(--viz-heat-5))"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      fontFamily: "var(--font-num)",
      fontSize: 10,
      color: "var(--viz-axis-label)"
    }
  }, /*#__PURE__*/React.createElement("span", null, "\u4F4E"), /*#__PURE__*/React.createElement("span", null, "\u9AD8")));
}
const HEAT = [[45, 79, 168], [31, 159, 206], [99, 198, 133], [240, 194, 74], [226, 85, 57]];
function heatColor(load) {
  const p = Math.max(0, Math.min(1, load)) * (HEAT.length - 1);
  const i = Math.floor(p),
    f = p - i;
  const a = HEAT[i],
    b = HEAT[Math.min(i + 1, HEAT.length - 1)];
  return [Math.round(a[0] + (b[0] - a[0]) * f), Math.round(a[1] + (b[1] - a[1]) * f), Math.round(a[2] + (b[2] - a[2]) * f)];
}
function rgba(c, a) {
  return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
}
window.Heatmap = Heatmap;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/feetforceplate/Heatmap.jsx", error: String((e && e.message) || e) }); }

// ui_kits/feetforceplate/HubScreen.jsx
try { (() => {
// FeetForcePlate — P-01 Hub: top bar + centered hero + recent-records table.
const HB = window.SteadyHealthDesignSystem_400653;
function HubScreen({
  onStart,
  onOpen
}) {
  const {
    Button,
    DataTable
  } = HB;
  const cols = [{
    key: "id",
    header: "编号"
  }, {
    key: "name",
    header: "受试者"
  }, {
    key: "time",
    header: "时间",
    numeric: true
  }, {
    key: "status",
    header: "状态",
    render: DataTable.status
  }];
  const rows = [{
    id: "**2781",
    name: "受试者 A",
    time: "14:32",
    status: {
      tone: "success",
      label: "已完成"
    }
  }, {
    id: "**2775",
    name: "受试者 B",
    time: "14:08",
    status: {
      tone: "info",
      icon: "spinner",
      spin: true,
      label: "分析生成中"
    }
  }, {
    id: "临时034",
    name: "临时受试者",
    time: "13:52",
    status: {
      tone: "success",
      label: "已完成"
    }
  }, {
    id: "**2760",
    name: "受试者 C",
    time: "13:31",
    status: {
      tone: "danger",
      icon: "x",
      label: "未完成"
    }
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: "auto",
      background: "var(--bg-page)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "var(--content-max-reading)",
      margin: "0 auto",
      padding: "var(--space-16) var(--space-8) var(--space-8)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: "center",
      padding: "var(--space-12) 0 var(--space-16)"
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: 0,
      font: "var(--text-display)",
      color: "var(--text-primary)"
    }
  }, "\u8DB3\u5E95\u538B\u529B\u5065\u5EB7\u7B5B\u67E5"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "var(--space-4) 0 var(--space-12)",
      font: "var(--text-body-lg)",
      color: "var(--text-secondary)"
    }
  }, "\u8BF7\u5F15\u5BFC\u53D7\u8BD5\u8005\u5230\u8FBE\u538B\u529B\u57AB\u524D,\u51C6\u5907\u5C31\u7EEA\u540E\u5F00\u59CB\u65B0\u7684\u68C0\u6D4B\u3002"), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "lg",
    onClick: onStart
  }, "\u5F00\u59CB\u65B0\u7684\u68C0\u6D4B")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      justifyContent: "space-between",
      marginBottom: "var(--space-4)"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      font: "var(--text-h3)",
      color: "var(--text-primary)"
    }
  }, "\u6700\u8FD1\u68C0\u6D4B"), /*#__PURE__*/React.createElement("span", {
    style: {
      font: "var(--text-secondary-size)",
      color: "var(--text-secondary)"
    }
  }, "\u4ECA\u65E5 4 \u6761")), /*#__PURE__*/React.createElement(DataTable, {
    columns: cols,
    rows: rows,
    onRowAction: onOpen,
    actionLabel: "\u67E5\u770B"
  })));
}
window.HubScreen = HubScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/feetforceplate/HubScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/feetforceplate/ResultScreen.jsx
try { (() => {
// FeetForcePlate — P-08 Result: centered status card. Big green check +
// "基础报告已生成" + blue "完整分析正在后台生成"; two buttons.
const RS = window.SteadyHealthDesignSystem_400653;
function ResultScreen({
  onViewReport,
  onNext
}) {
  const {
    Button,
    StatusPill
  } = RS;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: "auto",
      background: "var(--bg-page)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "var(--space-8)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "100%",
      maxWidth: 560,
      background: "var(--bg-surface)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      boxShadow: "var(--shadow-card)",
      padding: "var(--space-12)",
      textAlign: "center"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 72,
      height: 72,
      borderRadius: 999,
      background: "var(--success-bg)",
      border: "1px solid var(--success-border)",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      marginBottom: "var(--space-6)"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "40",
    height: "40",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "var(--success-fg)",
    strokeWidth: "2.5",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M20 6 9 17l-5-5"
  }))), /*#__PURE__*/React.createElement("h1", {
    style: {
      font: "var(--text-h1)",
      margin: "0 0 var(--space-3)",
      color: "var(--text-primary)"
    }
  }, "\u57FA\u7840\u62A5\u544A\u5DF2\u751F\u6210"), /*#__PURE__*/React.createElement("p", {
    style: {
      font: "var(--text-body)",
      color: "var(--text-secondary)",
      margin: "0 0 var(--space-6)"
    }
  }, "\u672C\u6B21\u8DB3\u5E95\u538B\u529B\u7B5B\u67E5\u5DF2\u5B8C\u6210\u8D28\u91CF\u6821\u6838,\u57FA\u7840\u62A5\u544A\u53EF\u7ACB\u5373\u67E5\u770B\u3002"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "inline-flex",
      marginBottom: "var(--space-8)"
    }
  }, /*#__PURE__*/React.createElement(StatusPill, {
    tone: "info",
    icon: "spinner",
    spin: true
  }, "\u5B8C\u6574\u5206\u6790\u62A5\u544A\u6B63\u5728\u540E\u53F0\u751F\u6210")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "var(--space-3)",
      justifyContent: "center"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    onClick: onNext
  }, "\u5F00\u59CB\u4E0B\u4E00\u4F4D\u68C0\u6D4B"), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    onClick: onViewReport
  }, "\u67E5\u770B\u57FA\u7840\u62A5\u544A"))));
}
window.ResultScreen = ResultScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/feetforceplate/ResultScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/feetforceplate/TopBar.jsx
try { (() => {
// FeetForcePlate — top bar: institution name + two status pills (Hub/List only).
const {
  StatusPill: TB_Pill
} = window.SteadyHealthDesignSystem_400653;
function TopBar({
  deviceReady = true,
  online = true,
  title = "康健社区健康服务中心"
}) {
  return /*#__PURE__*/React.createElement("header", {
    style: {
      height: 64,
      flex: "none",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "0 var(--space-8)",
      background: "var(--bg-surface)",
      borderBottom: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "var(--space-4)"
    }
  }, /*#__PURE__*/React.createElement("img", {
    src: "../../assets/logo-horizontal.png",
    alt: "\u5929\u5BCC\u667A\u67D4 TechFlex",
    style: {
      height: 34,
      width: "auto",
      display: "block"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      width: 1,
      height: 20,
      background: "var(--border-default)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      font: "var(--text-body)",
      color: "var(--text-secondary)"
    }
  }, title)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "var(--space-3)"
    }
  }, deviceReady ? /*#__PURE__*/React.createElement(TB_Pill, {
    tone: "success",
    icon: "dot"
  }, "\u8BBE\u5907\u5DF2\u5C31\u7EEA") : /*#__PURE__*/React.createElement(TB_Pill, {
    tone: "danger",
    icon: "x"
  }, "\u8BBE\u5907\u672A\u8FDE\u63A5"), online ? /*#__PURE__*/React.createElement(TB_Pill, {
    tone: "success",
    icon: "dot"
  }, "\u7F51\u7EDC\u6B63\u5E38") : /*#__PURE__*/React.createElement(TB_Pill, {
    tone: "warning",
    icon: "warning"
  }, "\u7F51\u7EDC\u5F85\u6062\u590D")));
}
window.TopBar = TopBar;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/feetforceplate/TopBar.jsx", error: String((e && e.message) || e) }); }

// ui_kits/feetforceplate/WizardScreen.jsx
try { (() => {
// FeetForcePlate — P-02~06 Wizard: consent → profile → health → pre-check.
const WZ = window.SteadyHealthDesignSystem_400653;
function WizardScreen({
  onDone,
  onExit
}) {
  const {
    Button,
    Field,
    ChipGroup,
    ChecklistItem,
    StepBar
  } = WZ;
  const steps = ["知情同意", "受试者档案", "健康问询", "设备预检"];
  const [step, setStep] = React.useState(0);
  const [profile, setProfile] = React.useState({
    id: "",
    height: "",
    weight: "",
    note: ""
  });
  const [history, setHistory] = React.useState([]);
  const set = k => e => setProfile(p => ({
    ...p,
    [k]: e.target.value
  }));
  const next = () => step < steps.length - 1 ? setStep(step + 1) : onDone();
  const back = () => step > 0 ? setStep(step - 1) : onExit();
  const primaryLabel = ["同意并继续", "保存并继续", "继续", "开始检测"][step];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: "flex",
      flexDirection: "column",
      background: "var(--bg-page)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--bg-surface)",
      borderBottom: "1px solid var(--border-default)",
      padding: "var(--space-4) var(--space-8)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "var(--content-max-wizard)",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement(StepBar, {
    steps: steps,
    current: step
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: "auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "var(--content-max-wizard)",
      margin: "0 auto",
      padding: "var(--space-12) var(--space-8)"
    }
  }, step === 0 && /*#__PURE__*/React.createElement(Consent, null), step === 1 && /*#__PURE__*/React.createElement(Profile, {
    profile: profile,
    set: set
  }), step === 2 && /*#__PURE__*/React.createElement(Health, {
    history: history,
    setHistory: setHistory
  }), step === 3 && /*#__PURE__*/React.createElement(PreCheck, null))), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--bg-surface)",
      borderTop: "1px solid var(--border-default)",
      padding: "var(--space-4) var(--space-8)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "var(--content-max-wizard)",
      margin: "0 auto",
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    onClick: back
  }, "\u2190 ", step === 0 ? "返回工作台" : "返回"), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    onClick: next
  }, primaryLabel))));
}
function Consent() {
  const {
    Button
  } = WZ;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    style: {
      font: "var(--text-h2)",
      margin: "0 0 var(--space-4)",
      color: "var(--text-primary)"
    }
  }, "\u4FE1\u606F\u5904\u7406\u4E0E\u77E5\u60C5\u540C\u610F"), /*#__PURE__*/React.createElement("p", {
    style: {
      font: "var(--text-body)",
      color: "var(--text-secondary)",
      lineHeight: 1.6,
      marginTop: 0
    }
  }, "\u672C\u6B21\u68C0\u6D4B\u5C06\u91C7\u96C6\u8DB3\u5E95\u538B\u529B\u6570\u636E\u7528\u4E8E\u5065\u5EB7\u7B5B\u67E5\u4E0E\u62A5\u544A\u751F\u6210\u3002\u6570\u636E\u4EC5\u5728\u672C\u673A\u6784\u8303\u56F4\u5185\u5904\u7406,\u4E0D\u7528\u4E8E\u8BCA\u65AD\u3002 \u53D7\u8BD5\u8005\u53EF\u968F\u65F6\u8981\u6C42\u505C\u6B62\u68C0\u6D4B\u5E76\u5220\u9664\u672C\u6B21\u6570\u636E\u3002"), /*#__PURE__*/React.createElement("ul", {
    style: {
      font: "var(--text-body)",
      color: "var(--text-secondary)",
      lineHeight: 1.8
    }
  }, /*#__PURE__*/React.createElement("li", null, "\u91C7\u96C6\u5185\u5BB9:\u8DB3\u5E95\u538B\u529B\u5206\u5E03\u3001\u7AD9\u7ACB\u5E73\u8861\u3001\u6B65\u6001\u8F7D\u8377\u66F2\u7EBF"), /*#__PURE__*/React.createElement("li", null, "\u7528\u9014:\u751F\u6210\u57FA\u7840\u62A5\u544A\u4E0E\u5B8C\u6574\u5206\u6790\u62A5\u544A"), /*#__PURE__*/React.createElement("li", null, "\u4FDD\u5B58:\u672C\u673A\u6784\u672C\u5730\u5B58\u50A8,\u53EF\u6309\u9700\u5BFC\u51FA PDF")), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost"
  }, "\u67E5\u770B\u5B8C\u6574\u4FE1\u606F\u5904\u7406\u89C4\u5219"));
}
function Profile({
  profile,
  set
}) {
  const {
    Field
  } = WZ;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    style: {
      font: "var(--text-h2)",
      margin: "0 0 var(--space-6)",
      color: "var(--text-primary)"
    }
  }, "\u53D7\u8BD5\u8005\u6863\u6848"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "var(--space-6)"
    }
  }, /*#__PURE__*/React.createElement(Field, {
    label: "\u673A\u6784\u6863\u6848\u53F7",
    value: profile.id,
    onChange: set("id"),
    placeholder: "\u4F8B\u5982 2024-0731",
    hint: "\u8131\u654F\u663E\u793A,\u62A5\u544A\u4E2D\u4E0D\u51FA\u73B0\u5B8C\u6574\u4FE1\u606F"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "var(--space-4)"
    }
  }, /*#__PURE__*/React.createElement(Field, {
    label: "\u8EAB\u9AD8",
    unit: "cm",
    value: profile.height,
    onChange: set("height"),
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(Field, {
    label: "\u4F53\u91CD",
    unit: "kg",
    value: profile.weight,
    onChange: set("weight"),
    style: {
      flex: 1
    }
  })), /*#__PURE__*/React.createElement(Field, {
    label: "\u5907\u6CE8",
    optional: true,
    value: profile.note,
    onChange: set("note"),
    placeholder: "\u5982\u6709\u7279\u6B8A\u60C5\u51B5\u53EF\u5907\u6CE8"
  })));
}
function Health({
  history,
  setHistory
}) {
  const {
    ChipGroup
  } = WZ;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    style: {
      font: "var(--text-h2)",
      margin: "0 0 var(--space-4)",
      color: "var(--text-primary)"
    }
  }, "\u5065\u5EB7\u95EE\u8BE2"), /*#__PURE__*/React.createElement("p", {
    style: {
      font: "var(--text-body)",
      color: "var(--text-secondary)",
      marginTop: 0
    }
  }, "\u8BF7\u9009\u62E9\u53D7\u8BD5\u8005\u65E2\u5F80\u75C5\u53F2(\u53EF\u591A\u9009,\u65E0\u5219\u8DF3\u8FC7)\u3002"), /*#__PURE__*/React.createElement(ChipGroup, {
    options: ["高血压", "糖尿病", "既往下肢损伤", "关节炎", "周围神经病变", "足部手术史"],
    value: history,
    onChange: setHistory,
    style: {
      marginTop: "var(--space-4)"
    }
  }));
}
function PreCheck() {
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    style: {
      font: "var(--text-h2)",
      margin: "0 0 var(--space-2)",
      color: "var(--text-primary)"
    }
  }, "\u8BBE\u5907\u9884\u68C0"), /*#__PURE__*/React.createElement("p", {
    style: {
      font: "var(--text-body)",
      color: "var(--text-secondary)",
      marginTop: 0
    }
  }, "\u8BF7\u786E\u8BA4\u4EE5\u4E0B\u5404\u9879\u901A\u8FC7\u540E\u5F00\u59CB\u68C0\u6D4B\u3002"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "var(--space-4)",
      background: "var(--bg-surface)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      padding: "var(--space-2) var(--space-6)"
    }
  }, [["pass", "压力垫连接", "已连接"], ["pass", "传感器校准", "通过"], ["pass", "信号自检", "通过"], ["pass", "存储空间", "充足"]].map(([s, l, h]) => /*#__PURE__*/React.createElement(WZ_Check, {
    key: l,
    status: s,
    label: l,
    hint: h
  }))));
}
function WZ_Check(props) {
  const {
    ChecklistItem
  } = WZ;
  return /*#__PURE__*/React.createElement(ChecklistItem, props);
}
window.WizardScreen = WizardScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/feetforceplate/WizardScreen.jsx", error: String((e && e.message) || e) }); }

__ds_ns.DataTable = __ds_scope.DataTable;

__ds_ns.Banner = __ds_scope.Banner;

__ds_ns.Dialog = __ds_scope.Dialog;

__ds_ns.StatusPill = __ds_scope.StatusPill;

__ds_ns.Toast = __ds_scope.Toast;

__ds_ns.ChecklistItem = __ds_scope.ChecklistItem;

__ds_ns.StepBar = __ds_scope.StepBar;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.ChipGroup = __ds_scope.ChipGroup;

__ds_ns.Field = __ds_scope.Field;

})();
