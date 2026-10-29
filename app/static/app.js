"use strict";
// GymTrack AI front end. Plain JS, no build step. All text is inserted with textContent
// (never innerHTML) so user data cannot inject markup. Authorization is enforced by the API;
// hiding a menu item here is only a convenience.

const state = { token: null, user: null, exercises: null };
try { state.token = sessionStorage.getItem("gt_token"); } catch (_) { /* storage blocked */ }

// ------------------------------------------------------------------ helpers

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

class ApiError extends Error {
  constructor(status, body) {
    const err = (body && body.error) || {};
    super(err.message || `Request failed (${status})`);
    this.status = status;
    this.code = err.code;
    this.details = err.details;
  }
}

async function api(path, { method = "GET", body, raw = false } = {}) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (_) {
    throw new ApiError(0, { error: { message: "Cannot reach the server. Check your connection." } });
  }
  if (res.status === 401 && path !== "/api/auth/login") {
    setToken(null);
    location.hash = "#/login";
    throw new ApiError(401, { error: { message: "Your session has ended. Please sign in again." } });
  }
  if (!res.ok) {
    let data = null;
    try { data = await res.json(); } catch (_) { /* non-JSON error */ }
    throw new ApiError(res.status, data);
  }
  if (raw) return res;
  return res.status === 204 ? null : res.json();
}

function setToken(token) {
  state.token = token;
  state.user = null;
  try {
    if (token) sessionStorage.setItem("gt_token", token);
    else sessionStorage.removeItem("gt_token");
  } catch (_) { /* storage blocked */ }
}

function errorBox(err) {
  const box = h("div", { class: "msg error", role: "alert" }, err.message || String(err));
  if (Array.isArray(err.details)) {
    box.append(h("ul", {}, err.details.map((d) => h("li", {}, `${d.field || "input"}: ${d.message}`))));
  }
  return box;
}

let toastTimer;
function toast(message) {
  const t = document.getElementById("toast");
  t.textContent = message;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3500);
}

const badge = (s) => h("span", { class: `badge ${s}` }, String(s).replaceAll("_", " "));
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
const money = (cents) => (cents / 100).toFixed(2);
// Local calendar date (YYYY-MM-DD), not UTC.
const today = () => new Date().toLocaleDateString("en-CA");

function field(label, input) {
  const id = input.id || `f-${Math.random().toString(36).slice(2, 9)}`;
  input.id = id;
  return h("div", { class: "field" }, h("label", { for: id }, label), input);
}

function formData(form) {
  const out = {};
  for (const [k, v] of new FormData(form).entries()) out[k] = typeof v === "string" ? v.trim() : v;
  return out;
}

// Wraps a submit handler with disabled button, error display and success toast.
function onSubmit(handler) {
  return async (ev) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    const btn = form.querySelector("button[type=submit]");
    form.querySelectorAll(".msg").forEach((m) => m.remove());
    if (btn) btn.disabled = true;
    try {
      await handler(form);
    } catch (err) {
      form.append(errorBox(err));
    } finally {
      if (btn) btn.disabled = false;
    }
  };
}

// Renders `loader()`'s result into a container with loading / error states.
async function section(container, loader) {
  container.replaceChildren(h("p", { class: "loading" }, "Loading…"));
  try {
    const content = await loader();
    // Views return nested arrays with optional (null/false) parts; flatten fully and drop those.
    container.replaceChildren(...[content].flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
  } catch (err) {
    container.replaceChildren(errorBox(err));
  }
}

function table(headers, rows, emptyText) {
  if (!rows.length) return h("p", { class: "empty" }, emptyText);
  return h("div", { class: "table-wrap" },
    h("table", {}, h("thead", {}, h("tr", {}, headers.map((x) => h("th", { scope: "col" }, x)))),
      h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c)))))));
}

function pager(page, onChange) {
  const { total, limit, offset } = page;
  if (total <= limit) return null;
  return h("div", { class: "row" },
    h("button", { class: "secondary", disabled: offset === 0, onclick: () => onChange(Math.max(0, offset - limit)) }, "Previous"),
    h("span", { class: "muted" }, `${offset + 1}–${Math.min(offset + limit, total)} of ${total}`),
    h("button", { class: "secondary", disabled: offset + limit >= total, onclick: () => onChange(offset + limit) }, "Next"));
}

async function exercises() {
  if (!state.exercises) state.exercises = await api("/api/exercises");
  return state.exercises;
}

// ------------------------------------------------------------------ routing

const isStaff = () => state.user && ["admin", "trainer"].includes(state.user.role);
const isAdmin = () => state.user && state.user.role === "admin";

const NAV = {
  admin: [["#/dashboard", "Dashboard"], ["#/desk", "Check-in desk"], ["#/members", "Members"],
    ["#/plans", "Plans"], ["#/staff", "Staff"]],
  trainer: [["#/dashboard", "Dashboard"], ["#/desk", "Check-in desk"], ["#/members", "My members"]],
  member: [["#/me", "My membership"], ["#/me/workouts", "My workouts"], ["#/me/visits", "My visits"]],
};

function renderChrome() {
  const nav = document.getElementById("nav");
  const box = document.getElementById("userbox");
  if (!state.user) { nav.replaceChildren(); box.replaceChildren(); return; }
  const current = location.hash.split("?")[0];
  nav.replaceChildren(...NAV[state.user.role].map(([href, text]) =>
    h("a", { href, "aria-current": current === href ? "page" : null }, text)));
  box.replaceChildren(
    h("a", { href: "#/account" }, state.user.full_name),
    h("button", { class: "secondary", onclick: logout }, "Sign out"));
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch (_) { /* already gone */ }
  setToken(null);
  location.hash = "#/login";
}

async function router() {
  const main = document.getElementById("main");
  const path = location.hash.replace(/^#/, "") || "/";
  if (!state.token) {
    state.user = null;
    renderChrome();
    return main.replaceChildren(loginView());
  }
  if (!state.user) {
    try { state.user = await api("/api/auth/me"); } catch (err) { return; }
  }
  renderChrome();
  const home = isStaff() ? "/dashboard" : "/me";
  const routes = [
    [/^\/dashboard$/, dashboardView, isStaff],
    [/^\/desk$/, deskView, isStaff],
    [/^\/members$/, membersView, isStaff],
    [/^\/members\/(\d+)$/, memberDetailView, isStaff],
    [/^\/plans$/, plansView, isAdmin],
    [/^\/staff$/, staffView, isAdmin],
    [/^\/me$/, myMembershipView, () => !isStaff()],
    [/^\/me\/workouts$/, myWorkoutsView, () => !isStaff()],
    [/^\/me\/visits$/, myVisitsView, () => !isStaff()],
    [/^\/account$/, accountView, () => true],
  ];
  for (const [re, view, allowed] of routes) {
    const m = path.match(re);
    if (m && allowed()) {
      main.replaceChildren(view(...m.slice(1)));
      main.focus();
      return;
    }
  }
  location.hash = `#${home}`;
}

window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", router);

// ------------------------------------------------------------------ views: auth

function loginView() {
  const form = h("form", { class: "card", style: null, novalidate: true },
    h("h1", {}, "Sign in"),
    field("Email", h("input", { name: "email", type: "email", autocomplete: "username", required: true })),
    field("Password", h("input", { name: "password", type: "password", autocomplete: "current-password", required: true })),
    h("button", { type: "submit" }, "Sign in"));
  form.addEventListener("submit", onSubmit(async (f) => {
    const { email, password } = formData(f);
    if (!email || !password) throw new Error("Enter your email and password.");
    const res = await api("/api/auth/login", { method: "POST", body: { email, password } });
    setToken(res.token);
    state.user = res.user;
    location.hash = res.user.role === "member" ? "#/me" : "#/dashboard";
    router();
  }));
  return h("div", { style: null }, form);
}

function accountView() {
  const form = h("form", { class: "card" },
    h("h1", {}, "Change password"),
    field("Current password", h("input", { name: "current_password", type: "password", autocomplete: "current-password", required: true })),
    field("New password (min 8 characters)", h("input", { name: "new_password", type: "password", autocomplete: "new-password", minlength: 8, required: true })),
    h("button", { type: "submit" }, "Update password"));
  form.addEventListener("submit", onSubmit(async (f) => {
    await api("/api/auth/change-password", { method: "POST", body: formData(f) });
    f.reset();
    toast("Password updated. Other devices were signed out.");
  }));
  return h("div", {}, h("p", { class: "muted" }, `${state.user.email} · ${state.user.role}`), form);
}

// ------------------------------------------------------------------ views: staff

function occupancyCard() {
  const card = h("div", { class: "card" });
  section(card, async () => {
    const o = await api("/api/attendance/occupancy");
    return [
      h("h2", {}, "Estimated people in the gym"),
      h("div", { class: "stat" }, o.estimated_count),
      h("p", { class: "muted" }, o.explanation),
      o.stale_open_sessions ? h("p", { class: "muted" },
        `${o.stale_open_sessions} older check-in(s) without check-out are not counted.`) : null,
      h("p", { class: "muted" }, `As of ${fmtTime(o.as_of)}`),
    ];
  });
  return card;
}

function dashboardView() {
  const wrap = h("div", {}, h("h1", {}, `Welcome, ${state.user.full_name}`));
  const grid = h("div", { class: "grid" }, occupancyCard(), checkCard());
  wrap.append(grid);
  if (isAdmin()) {
    const stale = h("div", { class: "card" }, h("h2", {}, "Housekeeping"),
      h("p", { class: "muted" }, "Close check-ins that were never checked out (older than the stale limit)."),
      h("button", {
        class: "secondary",
        onclick: async (ev) => {
          ev.target.disabled = true;
          try {
            const r = await api("/api/attendance/close-stale", { method: "POST" });
            toast(`Closed ${r.closed} stale check-in(s).`);
          } catch (err) { toast(err.message); } finally { ev.target.disabled = false; }
        },
      }, "Close stale check-ins"));
    grid.append(stale);
  }
  return wrap;
}

function checkCard() {
  const result = h("div", { "aria-live": "polite" });
  const input = h("input", { name: "code", autocomplete: "off", placeholder: "Scan QR or type member ID", required: true });
  const send = (action) => async (ev) => {
    ev.preventDefault();
    const code = input.value.trim();
    if (!code) { result.replaceChildren(errorBox(new Error("Scan a QR code or enter a member ID."))); return; }
    const body = /^\d+$/.test(code) ? { member_id: Number(code) } : { qr_token: code };
    result.replaceChildren(h("p", { class: "loading" }, "Working…"));
    try {
      const r = await api(`/api/attendance/${action}`, { method: "POST", body });
      result.replaceChildren(h("div", { class: "msg ok" }, badge(r.result), " ", r.member.full_name,
        ` · ${action === "check-in" ? "in" : "out"} at ${fmtTime(action === "check-in" ? r.session.check_in_at : r.session.check_out_at)}`,
        r.closed_stale_session_id ? h("div", { class: "muted" }, "A previous visit without check-out was closed as stale.") : null));
      input.value = "";
    } catch (err) {
      result.replaceChildren(errorBox(err));
    }
    input.focus();
  };
  const form = h("form", { onsubmit: send("check-in") },
    field("Member QR code or ID", input),
    h("div", { class: "row" },
      h("button", { type: "submit" }, "Check in"),
      h("button", { type: "button", class: "secondary", onclick: send("check-out") }, "Check out")));
  return h("div", { class: "card" }, h("h2", {}, "Check-in desk"),
    h("p", { class: "muted" }, "USB/Bluetooth QR scanners type the code into the box and press Enter."),
    form, result);
}

function deskView() {
  const card = checkCard();
  setTimeout(() => card.querySelector("input").focus(), 0);
  return h("div", {}, h("h1", {}, "Check-in desk"), card, occupancyCard());
}

function membersView() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const list = h("div", {});
  let offset = 0;
  const q = h("input", { name: "q", type: "search", value: params.get("q") || "", placeholder: "Name, email or phone" });
  const status = h("select", { name: "status" }, h("option", { value: "" }, "Any"),
    h("option", { value: "active" }, "Active"), h("option", { value: "inactive" }, "Inactive"));
  const load = () => section(list, async () => {
    const qs = new URLSearchParams({ limit: 25, offset });
    if (q.value.trim()) qs.set("q", q.value.trim());
    if (status.value) qs.set("status", status.value);
    const page = await api(`/api/members?${qs}`);
    return [
      table(["Name", "Contact", "Status", "Membership", ""], page.items.map((m) => [
        m.full_name,
        [m.email, m.phone].filter(Boolean).join(" · ") || "—",
        badge(m.status),
        m.current_membership ? h("span", {}, badge(m.current_membership.status), ` ${m.current_membership.plan_name} → ${m.current_membership.end_date}`) : "None",
        h("a", { href: `#/members/${m.id}` }, "Open"),
      ]), q.value ? "No members match your search." : "No members yet."),
      pager(page, (o) => { offset = o; load(); }),
    ];
  });
  const search = h("form", { class: "row", onsubmit: (e) => { e.preventDefault(); offset = 0; load(); } },
    field("Search", q), field("Status", status), h("div", { class: "field" }, h("button", { type: "submit" }, "Search")));
  load();
  return h("div", {}, h("h1", {}, isAdmin() ? "Members" : "My members"),
    isAdmin() ? newMemberForm() : null,
    h("div", { class: "card" }, search, list));
}

function trainerSelect(name, selected) {
  const sel = h("select", { name }, h("option", { value: "" }, "None"));
  api("/api/users?role=trainer&limit=200").then((p) => {
    for (const t of p.items.filter((t) => t.is_active)) {
      sel.append(h("option", { value: t.id, selected: t.id === selected }, t.full_name));
    }
  }).catch(() => {});
  return sel;
}

function newMemberForm() {
  const form = h("form", { novalidate: true },
    h("div", { class: "row" },
      field("Full name *", h("input", { name: "full_name", required: true, maxlength: 120 })),
      field("Email", h("input", { name: "email", type: "email" })),
      field("Phone", h("input", { name: "phone", type: "tel" })),
      field("Trainer", trainerSelect("assigned_trainer_id")),
      field("Login password (optional)", h("input", { name: "password", type: "password", autocomplete: "new-password", minlength: 8 }))),
    h("button", { type: "submit" }, "Add member"));
  form.addEventListener("submit", onSubmit(async (f) => {
    const d = formData(f);
    if (!d.full_name) throw new Error("Full name is required.");
    const m = await api("/api/members", {
      method: "POST",
      body: {
        full_name: d.full_name, email: d.email || null, phone: d.phone || null,
        assigned_trainer_id: d.assigned_trainer_id ? Number(d.assigned_trainer_id) : null,
        password: d.password || null,
      },
    });
    toast(`${m.full_name} added.`);
    location.hash = `#/members/${m.id}`;
  }));
  return h("details", { class: "card" }, h("summary", {}, "Add a member"), form);
}

function memberDetailView(id) {
  const wrap = h("div", {});
  section(wrap, async () => {
    const m = await api(`/api/members/${id}`);
    const info = h("div", { class: "card" },
      h("h1", {}, m.full_name, " ", badge(m.status)),
      h("p", { class: "muted" }, `Member #${m.id} · ${m.email || "no email"} · ${m.phone || "no phone"} · ${m.has_login ? "has login" : "no login"}`));
    if (isAdmin()) info.append(adminMemberActions(m));
    return [
      info,
      h("div", { class: "grid" }, membershipsCard(m), isAdmin() ? qrCard(m.id) : null),
      attendanceCard(`/api/attendance?member_id=${m.id}`),
      workoutsCard(m.id, m.status === "active"),
      progressCard(m.id),
    ];
  });
  return wrap;
}

function adminMemberActions(m) {
  const edit = h("form", { novalidate: true },
    h("div", { class: "row" },
      field("Full name", h("input", { name: "full_name", value: m.full_name, required: true })),
      field("Email", h("input", { name: "email", type: "email", value: m.email || "" })),
      field("Phone", h("input", { name: "phone", type: "tel", value: m.phone || "" })),
      field("Trainer", trainerSelect("assigned_trainer_id", m.assigned_trainer_id))),
    h("button", { type: "submit" }, "Save changes"));
  edit.addEventListener("submit", onSubmit(async (f) => {
    const d = formData(f);
    await api(`/api/members/${m.id}`, {
      method: "PATCH",
      body: { full_name: d.full_name, email: d.email || null, phone: d.phone || null,
        assigned_trainer_id: d.assigned_trainer_id ? Number(d.assigned_trainer_id) : null },
    });
    toast("Member updated.");
    router();
  }));
  const actions = h("div", { class: "row" });
  const act = (label, path, confirmText, cls = "secondary") => h("button", {
    class: cls,
    onclick: async () => {
      if (confirmText && !confirm(confirmText)) return;
      try { await api(path, { method: "POST" }); toast("Done."); router(); } catch (err) { toast(err.message); }
    },
  }, label);
  if (m.status === "active") {
    actions.append(act("Deactivate", `/api/members/${m.id}/deactivate`,
      "Deactivate this member? They will not be able to check in or sign in. History is kept.", "danger"));
  } else {
    actions.append(act("Reactivate", `/api/members/${m.id}/reactivate`));
  }
  if (!m.has_login) {
    const pw = h("form", { class: "row", novalidate: true },
      field("New login password", h("input", { name: "password", type: "password", minlength: 8, autocomplete: "new-password" })),
      h("div", { class: "field" }, h("button", { type: "submit", class: "secondary" }, "Create login")));
    pw.addEventListener("submit", onSubmit(async (f) => {
      await api(`/api/members/${m.id}/account`, { method: "POST", body: formData(f) });
      toast("Login created."); router();
    }));
    actions.append(pw);
  }
  return h("details", {}, h("summary", {}, "Edit / manage"), edit, actions);
}

function membershipsCard(m) {
  const card = h("div", { class: "card" });
  const load = () => section(card, async () => {
    const list = await api(`/api/members/${m.id}/memberships`);
    const rows = list.map((ms) => [
      ms.plan_name, `${ms.start_date} → ${ms.end_date}`, badge(ms.status),
      isAdmin() ? h("div", { class: "row" }, ...transitionButtons(ms, load)) : "",
    ]);
    const out = [h("h2", {}, "Memberships"), table(["Plan", "Dates (inclusive)", "Status", ""], rows, "No memberships yet.")];
    if (isAdmin() && m.status === "active") out.push(await addMembershipForm(m.id, load));
    return out;
  });
  load();
  return card;
}

function transitionButtons(ms, reload) {
  const btn = (label, action, cls = "secondary") => h("button", {
    class: cls,
    onclick: async () => {
      if (action === "cancel" && !confirm("Cancel this membership? This cannot be undone.")) return;
      try { await api(`/api/memberships/${ms.id}/${action}`, { method: "POST" }); reload(); } catch (err) { toast(err.message); }
    },
  }, label);
  const s = ms.stored_status;
  return [
    s === "active" ? btn("Suspend", "suspend") : null,
    s === "suspended" ? btn("Resume", "resume") : null,
    s !== "cancelled" ? btn("Cancel", "cancel", "danger") : null,
  ];
}

async function addMembershipForm(memberId, reload) {
  const plans = await api("/api/plans");
  if (!plans.length) return h("p", { class: "muted" }, "Create a plan first (Plans page).");
  const form = h("form", { class: "row" },
    field("Plan", h("select", { name: "plan_id" }, plans.map((p) => h("option", { value: p.id }, `${p.name} (${p.duration_days} days)`)))),
    field("Start date", h("input", { name: "start_date", type: "date", value: today() })),
    h("div", { class: "field" }, h("button", { type: "submit" }, "Add membership")));
  form.addEventListener("submit", onSubmit(async (f) => {
    const d = formData(f);
    await api(`/api/members/${memberId}/memberships`, {
      method: "POST", body: { plan_id: Number(d.plan_id), start_date: d.start_date || null },
    });
    toast("Membership added."); reload();
  }));
  return form;
}

function qrCard(memberId) {
  const card = h("div", { class: "card qr" });
  const load = () => section(card, async () => {
    const res = await api(`/api/members/${memberId}/qr.svg`, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    return [
      h("h2", {}, "Check-in QR code"),
      h("img", { src: url, alt: "Member check-in QR code" }),
      h("p", { class: "muted" }, "Contains a random code only — no personal details."),
      h("button", {
        class: "secondary",
        onclick: async () => {
          if (!confirm("Replace this QR code? The old one will stop working immediately.")) return;
          try { await api(`/api/members/${memberId}/qr/rotate`, { method: "POST" }); load(); } catch (err) { toast(err.message); }
        },
      }, "Replace QR code"),
    ];
  });
  load();
  return card;
}

function attendanceCard(baseUrl) {
  const card = h("div", { class: "card" });
  let offset = 0;
  const load = () => section(card, async () => {
    const sep = baseUrl.includes("?") ? "&" : "?";
    const page = await api(`${baseUrl}${sep}limit=10&offset=${offset}`);
    return [
      h("h2", {}, "Visits"),
      table(["Checked in", "Checked out", "Status", "Method"], page.items.map((s) => [
        fmtTime(s.check_in_at), fmtTime(s.check_out_at),
        s.closed_reason ? badge(s.closed_reason) : badge("checked_in"), s.method,
      ]), "No visits recorded."),
      pager(page, (o) => { offset = o; load(); }),
    ];
  });
  load();
  return card;
}

// ------------------------------------------------------------------ workouts (shared)

function workoutsCard(memberId, canLog) {
  const card = h("div", { class: "card" });
  let offset = 0;
  const load = () => section(card, async () => {
    const page = await api(`/api/members/${memberId}/workouts?limit=10&offset=${offset}`);
    const items = page.items.map((w) => h("div", { class: "card" },
      h("div", { class: "row" },
        h("strong", {}, w.performed_on),
        w.duration_minutes ? h("span", { class: "muted" }, `${w.duration_minutes} min`) : null,
        h("button", {
          class: "danger",
          onclick: async () => {
            if (!confirm("Delete this workout?")) return;
            try { await api(`/api/workouts/${w.id}`, { method: "DELETE" }); load(); } catch (err) { toast(err.message); }
          },
        }, "Delete")),
      w.notes ? h("p", {}, w.notes) : null,
      table(["Exercise", "Set", "Reps", "Weight", "Time"], w.sets.map((s) => [
        s.exercise_name, s.set_number, s.reps ?? "—",
        s.weight != null ? `${s.weight} ${s.weight_unit}` : "—",
        s.duration_seconds != null ? `${s.duration_seconds}s` : "—",
      ]), "")));
    return [
      h("h2", {}, "Workouts"),
      canLog ? await workoutForm(memberId, load) : h("p", { class: "muted" }, "Member is inactive; new workouts cannot be logged."),
      items.length ? items : h("p", { class: "empty" }, "No workouts logged yet."),
      pager(page, (o) => { offset = o; load(); }),
    ];
  });
  load();
  return card;
}

async function workoutForm(memberId, onSaved) {
  const exs = await exercises();
  const sets = h("div", {});
  const addSet = (prev) => {
    const row = h("div", { class: "set-row" },
      field("Exercise", h("select", { name: "exercise_id" }, exs.map((e) => h("option", { value: e.id, selected: prev && Number(prev.exercise_id) === e.id }, e.name)))),
      field("Reps", h("input", { name: "reps", type: "number", min: 0, max: 1000, inputmode: "numeric", value: prev ? prev.reps : "" })),
      field("Weight", h("input", { name: "weight", type: "number", min: 0, max: 1000, step: "0.5", inputmode: "decimal", value: prev ? prev.weight : "" })),
      field("Unit", h("select", { name: "weight_unit" }, ["kg", "lb"].map((u) => h("option", { value: u, selected: prev && prev.weight_unit === u }, u)))),
      field("Seconds", h("input", { name: "duration_seconds", type: "number", min: 0, inputmode: "numeric" })),
      h("div", { class: "field" }, h("label", {}, " "),
        h("button", { type: "button", class: "secondary", "aria-label": "Remove set", onclick: () => row.remove() }, "✕")));
    sets.append(row);
  };
  const readRow = (row) => {
    const get = (n) => row.querySelector(`[name=${n}]`).value.trim();
    return { exercise_id: get("exercise_id"), reps: get("reps"), weight: get("weight"), weight_unit: get("weight_unit"), duration_seconds: get("duration_seconds") };
  };
  addSet();
  const form = h("form", { novalidate: true },
    h("div", { class: "row" },
      field("Date", h("input", { name: "performed_on", type: "date", value: today(), max: today(), required: true })),
      field("Duration (min)", h("input", { name: "duration_minutes", type: "number", min: 1, max: 1440 })),
      field("Notes", h("input", { name: "notes", maxlength: 2000 }))),
    sets,
    h("div", { class: "row" },
      h("button", { type: "button", class: "secondary", onclick: () => { const rows = sets.children; addSet(rows.length ? readRow(rows[rows.length - 1]) : null); } }, "Add set"),
      h("button", { type: "submit" }, "Save workout")));
  form.addEventListener("submit", onSubmit(async (f) => {
    const num = (v) => (v === "" ? null : Number(v));
    const payloadSets = [...sets.children].map(readRow).map((s) => ({
      exercise_id: Number(s.exercise_id), reps: num(s.reps), weight: num(s.weight),
      weight_unit: s.weight_unit, duration_seconds: num(s.duration_seconds),
    }));
    if (!payloadSets.length) throw new Error("Add at least one set.");
    if (payloadSets.some((s) => s.reps === null && s.duration_seconds === null)) {
      throw new Error("Each set needs reps or seconds.");
    }
    const d = formData(f);
    await api(`/api/members/${memberId}/workouts`, {
      method: "POST",
      body: { performed_on: d.performed_on, duration_minutes: num(d.duration_minutes), notes: d.notes || null, sets: payloadSets },
    });
    toast("Workout saved.");
    onSaved();
  }));
  return h("details", {}, h("summary", {}, "Log a workout"), form);
}

function progressCard(memberId) {
  const out = h("div", {});
  const sel = h("select", { name: "exercise_id" });
  const card = h("div", { class: "card" }, h("h2", {}, "Progress"),
    h("form", { class: "row", onsubmit: (e) => { e.preventDefault(); show(); } },
      field("Exercise", sel), h("div", { class: "field" }, h("button", { type: "submit" }, "Show"))), out);
  exercises().then((exs) => exs.forEach((e) => sel.append(h("option", { value: e.id }, e.name))))
    .catch((err) => out.replaceChildren(errorBox(err)));
  const show = () => section(out, async () => {
    const p = await api(`/api/members/${memberId}/progress?exercise_id=${sel.value}`);
    const maxVol = Math.max(1, ...p.points.map((x) => x.volume_kg));
    return [
      p.best_weight_kg != null ? h("p", {}, `Best weight: ${p.best_weight_kg} kg`) : null,
      table(["Date", "Sets", "Reps", "Top weight (kg)", "Volume (kg)", ""], p.points.map((x) => [
        x.performed_on, x.sets, x.total_reps, x.max_weight_kg ?? "—", x.volume_kg,
        h("div", { class: "bar", style: null, "aria-hidden": "true", "data-w": x.volume_kg / maxVol }),
      ]), "No sets logged for this exercise yet."),
      h("p", { class: "disclaimer" }, p.disclaimer),
    ];
  }).then(() => out.querySelectorAll(".bar").forEach((b) => { b.style.width = `${Math.round(Number(b.dataset.w) * 100)}%`; }));
  return card;
}

// ------------------------------------------------------------------ views: admin

function plansView() {
  const list = h("div", {});
  const load = () => section(list, async () => {
    const plans = await api("/api/plans?include_inactive=true");
    return table(["Name", "Days", "Price", "Status", ""], plans.map((p) => [
      p.name, p.duration_days, money(p.price_cents), badge(p.is_active ? "active" : "inactive"),
      h("button", {
        class: "secondary",
        onclick: async () => {
          try { await api(`/api/plans/${p.id}`, { method: "PATCH", body: { is_active: !p.is_active } }); load(); } catch (err) { toast(err.message); }
        },
      }, p.is_active ? "Retire" : "Re-enable"),
    ]), "No plans yet. Add one above.");
  });
  const form = h("form", { class: "row", novalidate: true },
    field("Name", h("input", { name: "name", required: true, maxlength: 80 })),
    field("Duration (days)", h("input", { name: "duration_days", type: "number", min: 1, max: 3660, required: true })),
    field("Price", h("input", { name: "price", type: "number", min: 0, step: "0.01", value: "0" })),
    h("div", { class: "field" }, h("button", { type: "submit" }, "Add plan")));
  form.addEventListener("submit", onSubmit(async (f) => {
    const d = formData(f);
    await api("/api/plans", { method: "POST", body: { name: d.name, duration_days: Number(d.duration_days), price_cents: Math.round(Number(d.price || 0) * 100) } });
    f.reset(); toast("Plan added."); load();
  }));
  load();
  return h("div", {}, h("h1", {}, "Membership plans"),
    h("p", { class: "muted" }, "Prices are for reference only. GymTrack does not take payments."),
    h("div", { class: "card" }, form), h("div", { class: "card" }, list));
}

function staffView() {
  const list = h("div", {});
  const load = () => section(list, async () => {
    const page = await api("/api/users?limit=200");
    const staff = page.items.filter((u) => u.role !== "member");
    return table(["Name", "Email", "Role", "Status", ""], staff.map((u) => [
      u.full_name, u.email, u.role, badge(u.is_active ? "active" : "inactive"),
      u.id === state.user.id ? "(you)" : h("button", {
        class: u.is_active ? "danger" : "secondary",
        onclick: async () => {
          try { await api(`/api/users/${u.id}`, { method: "PATCH", body: { is_active: !u.is_active } }); load(); } catch (err) { toast(err.message); }
        },
      }, u.is_active ? "Deactivate" : "Reactivate"),
    ]), "No staff accounts.");
  });
  const form = h("form", { class: "row", novalidate: true },
    field("Full name", h("input", { name: "full_name", required: true })),
    field("Email", h("input", { name: "email", type: "email", required: true })),
    field("Role", h("select", { name: "role" }, h("option", { value: "trainer" }, "Trainer"), h("option", { value: "admin" }, "Admin"))),
    field("Password", h("input", { name: "password", type: "password", minlength: 8, autocomplete: "new-password", required: true })),
    h("div", { class: "field" }, h("button", { type: "submit" }, "Add staff")));
  form.addEventListener("submit", onSubmit(async (f) => {
    await api("/api/users", { method: "POST", body: formData(f) });
    f.reset(); toast("Staff account created."); load();
  }));
  load();
  return h("div", {}, h("h1", {}, "Staff"), h("div", { class: "card" }, form), h("div", { class: "card" }, list));
}

// ------------------------------------------------------------------ views: member

function myMembershipView() {
  const wrap = h("div", {});
  section(wrap, async () => {
    const m = await api("/api/members/me");
    const cm = m.current_membership;
    return [
      h("h1", {}, `Hi, ${m.full_name}`),
      h("div", { class: "grid" },
        h("div", { class: "card" }, h("h2", {}, "My membership"),
          cm ? [h("p", {}, badge(cm.status), " ", cm.plan_name),
            h("p", { class: "muted" }, `${cm.start_date} to ${cm.end_date} (inclusive)`)]
            : h("p", { class: "empty" }, "You have no membership yet. Please ask the front desk.")),
        qrCard(m.id)),
    ];
  });
  return wrap;
}

function myWorkoutsView() {
  const wrap = h("div", {});
  section(wrap, async () => {
    const m = await api("/api/members/me");
    return [h("h1", {}, "My workouts"), workoutsCard(m.id, m.status === "active"), progressCard(m.id)];
  });
  return wrap;
}

function myVisitsView() {
  return h("div", {}, h("h1", {}, "My visits"), attendanceCard("/api/attendance/me"));
}
