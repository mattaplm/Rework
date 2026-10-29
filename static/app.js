// Shared front-end helpers for the Doors Rework tracker.

/** Generic searchable combobox: input + filtered <ul>. `items` is a flat
 * array; `getLabel`/`getSub` pull the main/secondary text for each row. */
function makeCombo(inputEl, listEl, items, getLabel, getSub, onSelect) {
  var active = -1, filtered = items;

  function render(q) {
    filtered = items.filter(function (it) {
      return getLabel(it).toLowerCase().indexOf((q || "").toLowerCase()) !== -1;
    });
    listEl.innerHTML = "";
    active = -1;
    if (!filtered.length) {
      var empty = document.createElement("li");
      empty.className = "combo-empty";
      empty.textContent = "No matches";
      listEl.appendChild(empty);
      return;
    }
    filtered.forEach(function (it) {
      var li = document.createElement("li");
      li.className = "combo-opt";
      li.setAttribute("role", "option");
      var sub = getSub ? getSub(it) : "";
      li.innerHTML = "<span></span>" + (sub ? "<small></small>" : "");
      li.children[0].textContent = getLabel(it);
      if (sub) li.children[1].textContent = sub;
      li.addEventListener("mousedown", function (e) {
        e.preventDefault();
        onSelect(it);
        listEl.hidden = true;
      });
      listEl.appendChild(li);
    });
  }

  function setActive(i) {
    var opts = listEl.querySelectorAll(".combo-opt");
    opts.forEach(function (o) { o.classList.remove("active"); });
    if (opts[i]) { opts[i].classList.add("active"); opts[i].scrollIntoView({ block: "nearest" }); }
    active = i;
  }

  inputEl.addEventListener("input", function () { render(inputEl.value); listEl.hidden = false; });
  inputEl.addEventListener("focus", function () { render(inputEl.value); listEl.hidden = false; });
  inputEl.addEventListener("blur", function () { setTimeout(function () { listEl.hidden = true; }, 120); });
  inputEl.addEventListener("keydown", function (e) {
    if (listEl.hidden) return;
    var opts = listEl.querySelectorAll(".combo-opt");
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(active + 1, opts.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(active - 1, 0)); }
    else if (e.key === "Enter") { if (active >= 0 && filtered[active]) { e.preventDefault(); onSelect(filtered[active]); listEl.hidden = true; } }
    else if (e.key === "Escape") { listEl.hidden = true; }
  });

  return { refresh: function (newItems) { items = newItems; } };
}

function nzd(value) {
  return new Intl.NumberFormat("en-NZ", { style: "currency", currency: "NZD" }).format(value);
}

(function initNavToggle() {
  var navToggle = document.getElementById("nav-toggle");
  var backdrop = document.getElementById("sidebar-backdrop");
  if (!navToggle) return;
  var closeNav = function () { document.body.classList.remove("nav-open"); };
  navToggle.addEventListener("click", function () { document.body.classList.toggle("nav-open"); });
  if (backdrop) backdrop.addEventListener("click", closeNav);
  document.querySelectorAll(".sidebar .nav-link").forEach(function (a) { a.addEventListener("click", closeNav); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeNav(); });
})();

function debounce(fn, ms) {
  var t;
  return function () {
    var args = arguments, ctx = this;
    clearTimeout(t);
    t = setTimeout(function () { fn.apply(ctx, args); }, ms);
  };
}

// "Update available -- click to refresh": polls /api/version and, once the
// server's build differs from the one this tab first saw (i.e. a deploy
// happened), shows a button that reloads the page. Same approach as the Paid
// hours app. The first response is the baseline, so a tab opened after a
// deploy never shows it.
(function () {
  var CHECK_MS = 5 * 60 * 1000;
  var baseline = null, shown = false;

  function showBadge() {
    if (shown) return;
    shown = true;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "update-badge";
    btn.textContent = "\uD83D\uDD04 Update available \u2014 click to refresh";
    btn.addEventListener("click", function () { window.location.reload(); });
    document.body.appendChild(btn);
  }

  function check() {
    fetch("/api/version", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (baseline === null) baseline = d.version;
        else if (d.version !== baseline) showBadge();
      })
      .catch(function () { /* offline / transient -- try again next interval */ });
  }

  check();
  setInterval(check, CHECK_MS);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") check();
  });
})();
