/* Attendance System web client.
 *
 * Plain ES modules-free JavaScript. Talks to the same-origin REST API.
 * The admin token is kept in localStorage and sent as a Bearer token on
 * every admin request. The terminal view uses a per-device API key instead.
 */
(function () {
  "use strict";

  var TOKEN_KEY = "attendance_admin_token";
  var TERM_KEY = "attendance_terminal_key";

  // ---- tiny DOM helpers ---------------------------------------------------
  function $(sel) { return document.querySelector(sel); }
  function $all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      if (k === "class") node.className = attrs[k];
      else if (k === "text") node.textContent = attrs[k];
      else if (k === "html") node.innerHTML = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) {
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function getToken() { return localStorage.getItem(TOKEN_KEY) || ""; }

  // ---- API client ---------------------------------------------------------
  function api(method, path, body, opts) {
    opts = opts || {};
    var headers = { "Content-Type": "application/json" };
    if (opts.apiKey) headers["X-API-Key"] = opts.apiKey;
    else headers["Authorization"] = "Bearer " + getToken();

    return fetch(path, {
      method: method,
      headers: headers,
      body: body ? JSON.stringify(body) : undefined
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          var err = new Error((data && data.error) || ("HTTP " + res.status));
          err.status = res.status;
          throw err;
        }
        return data;
      });
    });
  }

  function toast(msg, isError) {
    var t = $("#toast");
    t.textContent = msg;
    t.className = "toast " + (isError ? "err" : "ok");
    setTimeout(function () { t.className = "toast hidden"; }, 3000);
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleString();
  }

  function typeBadge(t) {
    var cls = t === "check_in" ? "badge-in" : "badge-out";
    var label = t === "check_in" ? "Check in" : "Check out";
    return '<span class="badge ' + cls + '">' + label + "</span>";
  }

  // ---- auth / shell -------------------------------------------------------
  function showLogin() {
    $("#app-view").classList.add("hidden");
    $("#login-view").classList.remove("hidden");
  }
  function showApp() {
    $("#login-view").classList.add("hidden");
    $("#app-view").classList.remove("hidden");
    route();
  }

  function login(token) {
    // Validate by hitting an admin endpoint.
    localStorage.setItem(TOKEN_KEY, token);
    return api("GET", "/api/users").then(function () {
      showApp();
    }).catch(function (e) {
      localStorage.removeItem(TOKEN_KEY);
      throw e;
    });
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    location.hash = "";
    showLogin();
  }

  // ---- router -------------------------------------------------------------
  var VIEWS = ["dashboard", "users", "devices", "attendance", "terminal"];
  var TITLES = {
    dashboard: "Dashboard", users: "Users", devices: "Devices",
    attendance: "Attendance", terminal: "Terminal"
  };

  function route() {
    var view = (location.hash || "#dashboard").slice(1);
    if (VIEWS.indexOf(view) === -1) view = "dashboard";

    $all(".view").forEach(function (v) { v.classList.add("hidden"); });
    $("#" + view).classList.remove("hidden");
    $("#view-title").textContent = TITLES[view];
    $all(".nav-link").forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("data-view") === view);
    });

    if (view === "dashboard") loadDashboard();
    else if (view === "users") loadUsers();
    else if (view === "devices") loadDevices();
    else if (view === "attendance") loadAttendanceView();
  }

  // ---- dashboard ----------------------------------------------------------
  function loadDashboard() {
    Promise.all([
      api("GET", "/api/users"),
      api("GET", "/api/devices"),
      api("GET", "/api/attendance?limit=500")
    ]).then(function (r) {
      var users = r[0].users, devices = r[1].devices, records = r[2].records;
      $("#stat-users").textContent = users.filter(function (u) { return u.active; }).length;
      $("#stat-devices").textContent = devices.length;
      $("#stat-total").textContent = records.length;

      var today = new Date().toISOString().slice(0, 10);
      $("#stat-today").textContent = records.filter(function (rec) {
        return (rec.punch_time || "").slice(0, 10) === today;
      }).length;

      var userById = {}, devById = {};
      users.forEach(function (u) { userById[u.id] = u.name; });
      devices.forEach(function (d) { devById[d.id] = d.name; });

      var body = $("#recent-body");
      body.innerHTML = "";
      var recent = records.slice(0, 10);
      if (!recent.length) {
        body.appendChild(el("tr", {}, [el("td", { colspan: "5", class: "muted", text: "No activity yet." })]));
        return;
      }
      recent.forEach(function (rec) {
        body.appendChild(el("tr", { html:
          "<td>" + fmtTime(rec.punch_time) + "</td>" +
          "<td>" + (userById[rec.user_id] || ("#" + rec.user_id)) + "</td>" +
          "<td>" + typeBadge(rec.punch_type) + "</td>" +
          "<td>" + (devById[rec.device_id] || "—") + "</td>" +
          "<td>" + (rec.source || "") + "</td>"
        }));
      });
    }).catch(handleErr);
  }

  // ---- users --------------------------------------------------------------
  function loadUsers() {
    var includeDeleted = $("#show-deleted").checked;
    api("GET", "/api/users" + (includeDeleted ? "?include_deleted=1" : "")).then(function (r) {
      var body = $("#users-body");
      body.innerHTML = "";
      if (!r.users.length) {
        body.appendChild(el("tr", {}, [el("td", { colspan: "7", class: "muted", text: "No users yet." })]));
        return;
      }
      r.users.forEach(function (u) {
        var status = u.deleted
          ? '<span class="badge badge-inactive">deleted</span>'
          : (u.active ? '<span class="badge badge-active">active</span>'
                      : '<span class="badge badge-inactive">inactive</span>');
        var tr = el("tr", { html:
          "<td>" + esc(u.employee_code) + "</td>" +
          "<td>" + esc(u.name) + "</td>" +
          "<td>" + esc(u.email || "—") + "</td>" +
          "<td>" + esc(u.card_id || "—") + "</td>" +
          "<td>" + esc(u.pin || "—") + "</td>" +
          "<td>" + status + "</td>"
        });
        var actions = el("td");
        if (!u.deleted) {
          var edit = el("button", { class: "btn btn-sm", text: "Edit" });
          edit.onclick = function () { openUserModal(u); };
          var del = el("button", { class: "btn btn-sm btn-danger", text: "Delete" });
          del.onclick = function () { deleteUser(u); };
          actions.appendChild(edit);
          actions.appendChild(document.createTextNode(" "));
          actions.appendChild(del);
        }
        tr.appendChild(actions);
        body.appendChild(tr);
      });
    }).catch(handleErr);
  }

  function openUserModal(user) {
    var editing = !!user;
    openModal(editing ? "Edit user" : "Add user", [
      field("name", "Name", "text", user && user.name, true),
      field("employee_code", "Employee code", "text", user && user.employee_code, true),
      field("email", "Email", "email", user && user.email),
      field("card_id", "Card ID", "text", user && user.card_id),
      field("pin", "PIN", "text", user && user.pin),
      checkField("active", "Active", !user || user.active)
    ], function (data) {
      data.active = !!data.active;
      var req = editing
        ? api("PUT", "/api/users/" + user.id, data)
        : api("POST", "/api/users", data);
      return req.then(function () {
        toast(editing ? "User updated" : "User created");
        loadUsers();
      });
    });
  }

  function deleteUser(u) {
    if (!confirm("Delete user " + u.name + "? Existing records are kept.")) return;
    api("DELETE", "/api/users/" + u.id).then(function () {
      toast("User deleted");
      loadUsers();
    }).catch(handleErr);
  }

  // ---- devices ------------------------------------------------------------
  function loadDevices() {
    api("GET", "/api/devices").then(function (r) {
      var body = $("#devices-body");
      body.innerHTML = "";
      if (!r.devices.length) {
        body.appendChild(el("tr", {}, [el("td", { colspan: "6", class: "muted", text: "No devices registered." })]));
        return;
      }
      r.devices.forEach(function (d) {
        var statusBadge = d.status === "active"
          ? '<span class="badge badge-active">active</span>'
          : '<span class="badge badge-inactive">' + esc(d.status) + "</span>";
        var tr = el("tr", { html:
          "<td>" + esc(d.name) + "</td>" +
          "<td>" + esc(d.location || "—") + "</td>" +
          "<td>" + statusBadge + "</td>" +
          "<td>" + fmtTime(d.last_sync_at) + "</td>" +
          '<td><code class="api-key">' + esc(d.api_key) + "</code></td>"
        });
        var actions = el("td");
        var copy = el("button", { class: "btn btn-sm", text: "Copy key" });
        copy.onclick = function () { copyText(d.api_key); };
        var rotate = el("button", { class: "btn btn-sm", text: "Rotate" });
        rotate.onclick = function () { rotateKey(d); };
        var del = el("button", { class: "btn btn-sm btn-danger", text: "Delete" });
        del.onclick = function () { deleteDevice(d); };
        [copy, rotate, del].forEach(function (b, i) {
          if (i) actions.appendChild(document.createTextNode(" "));
          actions.appendChild(b);
        });
        tr.appendChild(actions);
        body.appendChild(tr);
      });
    }).catch(handleErr);
  }

  function openDeviceModal() {
    openModal("Register device", [
      field("name", "Name", "text", "", true),
      field("location", "Location", "text", "")
    ], function (data) {
      return api("POST", "/api/devices", data).then(function (d) {
        toast("Device registered");
        loadDevices();
      });
    });
  }

  function rotateKey(d) {
    if (!confirm("Rotate API key for " + d.name + "? The old key stops working immediately.")) return;
    api("PUT", "/api/devices/" + d.id, { rotate_api_key: true }).then(function () {
      toast("API key rotated");
      loadDevices();
    }).catch(handleErr);
  }

  function deleteDevice(d) {
    if (!confirm("Delete device " + d.name + "?")) return;
    api("DELETE", "/api/devices/" + d.id).then(function () {
      toast("Device deleted");
      loadDevices();
    }).catch(handleErr);
  }

  // ---- attendance ---------------------------------------------------------
  function loadAttendanceView() {
    Promise.all([api("GET", "/api/users?include_deleted=1"), api("GET", "/api/devices")])
      .then(function (r) {
        fillSelect($("#filter-user"), r[0].users, "All users", function (u) { return [u.id, u.name]; });
        fillSelect($("#filter-device"), r[1].devices, "All devices", function (d) { return [d.id, d.name]; });
        applyAttendanceFilter();
      }).catch(handleErr);
  }

  function applyAttendanceFilter() {
    var q = [];
    var u = $("#filter-user").value, d = $("#filter-device").value;
    var from = $("#filter-from").value, to = $("#filter-to").value;
    if (u) q.push("user_id=" + u);
    if (d) q.push("device_id=" + d);
    if (from) q.push("from=" + from + "T00:00:00");
    if (to) q.push("to=" + to + "T23:59:59");
    q.push("limit=500");

    Promise.all([
      api("GET", "/api/attendance?" + q.join("&")),
      api("GET", "/api/users?include_deleted=1"),
      api("GET", "/api/devices")
    ]).then(function (r) {
      var userById = {}, devById = {};
      r[1].users.forEach(function (x) { userById[x.id] = x.name; });
      r[2].devices.forEach(function (x) { devById[x.id] = x.name; });
      var body = $("#attendance-body");
      body.innerHTML = "";
      if (!r[0].records.length) {
        body.appendChild(el("tr", {}, [el("td", { colspan: "5", class: "muted", text: "No records match." })]));
        return;
      }
      r[0].records.forEach(function (rec) {
        body.appendChild(el("tr", { html:
          "<td>" + fmtTime(rec.punch_time) + "</td>" +
          "<td>" + (userById[rec.user_id] || ("#" + rec.user_id)) + "</td>" +
          "<td>" + typeBadge(rec.punch_type) + "</td>" +
          "<td>" + (devById[rec.device_id] || "—") + "</td>" +
          "<td>" + (rec.source || "") + "</td>"
        }));
      });
    }).catch(handleErr);
  }

  // ---- terminal -----------------------------------------------------------
  function initTerminal() {
    $("#term-key").value = localStorage.getItem(TERM_KEY) || "";
    $all("[data-punch]").forEach(function (btn) {
      btn.onclick = function () { punch(btn.getAttribute("data-punch")); };
    });
  }

  function punch(type) {
    var key = $("#term-key").value.trim();
    var idType = $("#term-id-type").value;
    var idValue = $("#term-id-value").value.trim();
    var result = $("#term-result");
    if (!key) { return showTermResult("Enter a device API key.", true); }
    if (!idValue) { return showTermResult("Enter an identifier.", true); }
    localStorage.setItem(TERM_KEY, key);

    var body = { punch_type: type };
    body[idType] = idValue;
    api("POST", "/api/punch", body, { apiKey: key }).then(function (r) {
      var label = type === "check_in" ? "checked in" : "checked out";
      showTermResult("✓ " + r.user.name + " " + label + " at " + fmtTime(r.record.punch_time), false);
      $("#term-id-value").value = "";
    }).catch(function (e) {
      showTermResult("✗ " + e.message, true);
    });
  }

  function showTermResult(msg, isError) {
    var r = $("#term-result");
    r.textContent = msg;
    r.className = "term-result " + (isError ? "err" : "ok");
  }

  // ---- modal --------------------------------------------------------------
  function field(name, label, type, value, required) {
    var wrap = el("div");
    wrap.appendChild(el("label", { text: label + (required ? " *" : "") }));
    var input = el("input", { type: type || "text", name: name });
    if (value != null && value !== "") input.value = value;
    if (required) input.required = true;
    wrap.appendChild(input);
    return wrap;
  }
  function checkField(name, label, checked) {
    var wrap = el("label", { class: "checkbox" });
    var input = el("input", { type: "checkbox", name: name });
    input.checked = !!checked;
    wrap.appendChild(input);
    wrap.appendChild(document.createTextNode(" " + label));
    return wrap;
  }

  function openModal(title, fields, onSubmit) {
    $("#modal-title").textContent = title;
    var form = $("#modal-form");
    form.innerHTML = "";
    fields.forEach(function (f) { form.appendChild(f); });
    var actions = el("div", { class: "modal-actions" });
    var cancel = el("button", { type: "button", class: "btn btn-ghost", text: "Cancel" });
    cancel.onclick = closeModal;
    var save = el("button", { type: "submit", class: "btn btn-primary", text: "Save" });
    actions.appendChild(cancel);
    actions.appendChild(save);
    form.appendChild(actions);

    form.onsubmit = function (e) {
      e.preventDefault();
      var data = {};
      Array.prototype.forEach.call(form.elements, function (input) {
        if (!input.name) return;
        data[input.name] = input.type === "checkbox" ? input.checked : input.value.trim();
      });
      save.disabled = true;
      Promise.resolve(onSubmit(data)).then(closeModal).catch(function (err) {
        handleErr(err);
        save.disabled = false;
      });
    };
    $("#modal-overlay").classList.remove("hidden");
  }
  function closeModal() { $("#modal-overlay").classList.add("hidden"); }

  // ---- utilities ----------------------------------------------------------
  function fillSelect(select, items, allLabel, map) {
    select.innerHTML = "";
    select.appendChild(el("option", { value: "", text: allLabel }));
    items.forEach(function (it) {
      var pair = map(it);
      select.appendChild(el("option", { value: pair[0], text: pair[1] }));
    });
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function copyText(text) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(function () { toast("Copied to clipboard"); });
    } else {
      toast("Copy not supported", true);
    }
  }
  function handleErr(e) {
    if (e && e.status === 401) { toast("Session expired — sign in again", true); logout(); return; }
    toast((e && e.message) || "Request failed", true);
  }

  // ---- wire up ------------------------------------------------------------
  function init() {
    $("#login-form").onsubmit = function (e) {
      e.preventDefault();
      var err = $("#login-error");
      err.classList.add("hidden");
      login($("#login-token").value.trim()).catch(function (ex) {
        err.textContent = ex.status === 401 ? "Invalid admin token." : ex.message;
        err.classList.remove("hidden");
      });
    };
    $("#goto-terminal").onclick = function (e) {
      e.preventDefault();
      // Terminal is reachable without admin login.
      $("#login-view").classList.add("hidden");
      $("#app-view").classList.remove("hidden");
      location.hash = "#terminal";
    };
    $("#logout-btn").onclick = logout;
    $("#add-user-btn").onclick = function () { openUserModal(null); };
    $("#add-device-btn").onclick = openDeviceModal;
    $("#show-deleted").onchange = loadUsers;
    $("#apply-filter").onclick = applyAttendanceFilter;
    $("#clear-filter").onclick = function () {
      $("#filter-user").value = ""; $("#filter-device").value = "";
      $("#filter-from").value = ""; $("#filter-to").value = "";
      applyAttendanceFilter();
    };
    $("#modal-close").onclick = closeModal;
    $("#modal-overlay").onclick = function (e) { if (e.target === this) closeModal(); };

    window.addEventListener("hashchange", function () {
      if (!$("#app-view").classList.contains("hidden")) route();
    });

    initTerminal();

    if (getToken()) {
      // Verify the stored token still works.
      api("GET", "/api/users").then(showApp).catch(showLogin);
    } else {
      showLogin();
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
