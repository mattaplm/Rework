// Apply before the stylesheet loads so navigation never flashes the wrong theme.
(function () {
  "use strict";
  var storageKey = "rework-theme";
  var system = window.matchMedia("(prefers-color-scheme: dark)");
  var preference = "system";

  function valid(value) {
    return value === "light" || value === "dark" || value === "system";
  }

  try {
    var saved = localStorage.getItem(storageKey);
    if (valid(saved)) preference = saved;
  } catch (error) {
    // Storage can be unavailable in private or restricted browser sessions.
  }

  function apply() {
    document.documentElement.dataset.theme = preference === "system"
      ? (system.matches ? "dark" : "light") : preference;
    document.querySelectorAll("[data-theme-choice]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.themeChoice === preference));
    });
  }

  apply();
  system.addEventListener("change", function () {
    if (preference === "system") apply();
  });
  window.addEventListener("storage", function (event) {
    if (event.key === storageKey || event.key === null) {
      preference = valid(event.newValue) ? event.newValue : "system";
      apply();
    }
  });
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-theme-choice]").forEach(function (button) {
      button.addEventListener("click", function () {
        preference = button.dataset.themeChoice;
        try { localStorage.setItem(storageKey, preference); } catch (error) {}
        apply();
      });
    });
    apply();
    document.querySelectorAll(".theme-picker").forEach(function (picker) {
      picker.hidden = false;
    });
  });
})();
