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
