// Minimal SVG bar/line chart helpers for the Dashboard.
// Follows the dataviz skill's non-negotiables: one axis per chart (never
// dual-axis -- two measures become two charts), thin marks with rounded
// data-ends, muted gridlines/axis ink, a shared hover tooltip, legends only
// when >=2 series, direct labels kept selective (<=10 marks here).

(function (global) {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";

  function el(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function ensureTooltip() {
    var tip = document.getElementById("chartTooltip");
    if (!tip) {
      tip = document.createElement("div");
      tip.id = "chartTooltip";
      tip.className = "chart-tooltip";
      tip.hidden = true;
      document.body.appendChild(tip);
    }
    return tip;
  }

  function showTooltip(evt, html) {
    var tip = ensureTooltip();
    tip.innerHTML = html;
    tip.hidden = false;
    var x = evt.clientX + 14, y = evt.clientY + 14;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }

  function hideTooltip() {
    var tip = document.getElementById("chartTooltip");
    if (tip) tip.hidden = true;
  }

  // ── Horizontal bar chart: one series, ranked categories ──
  // data: [{label, value}], opts: {color, width, barHeight, formatValue}
  function barChart(container, data, opts) {
    opts = opts || {};
    var color = opts.color || "var(--accent)";
    var width = opts.width || container.clientWidth || 480;
    var barH = opts.barHeight || 22;
    var gap = 10;
    var labelW = opts.labelWidth || 120;
    var plotW = width - labelW - 56; // room for value label on the right
    var height = data.length * (barH + gap) + gap;
    var maxVal = Math.max.apply(null, data.map(function (d) { return d.value; })) || 1;
    var fmt = opts.formatValue || function (v) { return v; };

    var svg = el("svg", { viewBox: "0 0 " + width + " " + height, width: "100%", height: height });
    data.forEach(function (d, i) {
      var y = gap + i * (barH + gap);
      var w = Math.max(2, (d.value / maxVal) * plotW);

      svg.appendChild(el("text", {
        x: labelW - 8, y: y + barH / 2 + 4, "text-anchor": "end", class: "chart-label",
      })).textContent = d.label;

      var rect = el("rect", {
        x: labelW, y: y, width: w, height: barH, rx: 4, fill: d.color || color, class: "chart-bar",
      });
      rect.addEventListener("mousemove", function (e) { showTooltip(e, "<strong>" + d.label + "</strong><br>" + fmt(d.value)); });
      rect.addEventListener("mouseleave", hideTooltip);
      svg.appendChild(rect);

      svg.appendChild(el("text", {
        x: labelW + w + 8, y: y + barH / 2 + 4, class: "chart-value",
      })).textContent = fmt(d.value);
    });

    container.innerHTML = "";
    container.appendChild(svg);
  }

  // ── Line chart: one series over time ──
  // data: [{label, value}], opts: {color, formatValue}
  function lineChart(container, data, opts) {
    opts = opts || {};
    var color = opts.color || "var(--accent)";
    var width = opts.width || container.clientWidth || 480;
    var height = opts.height || 180;
    var padL = 36, padR = 12, padT = 16, padB = 28;
    var plotW = width - padL - padR, plotH = height - padT - padB;
    var maxVal = Math.max.apply(null, data.map(function (d) { return d.value; })) || 1;
    var fmt = opts.formatValue || function (v) { return v; };
    var n = data.length;

    function x(i) { return padL + (n <= 1 ? 0 : (i / (n - 1)) * plotW); }
    function y(v) { return padT + plotH - (v / maxVal) * plotH; }

    var svg = el("svg", { viewBox: "0 0 " + width + " " + height, width: "100%", height: height });

    // gridlines (3 bands)
    [0, 0.5, 1].forEach(function (t) {
      var gy = padT + plotH - t * plotH;
      svg.appendChild(el("line", { x1: padL, x2: width - padR, y1: gy, y2: gy, class: "chart-grid" }));
      svg.appendChild(el("text", { x: padL - 8, y: gy + 4, "text-anchor": "end", class: "chart-axis" })).textContent = fmt(Math.round(maxVal * t));
    });

    var points = data.map(function (d, i) { return x(i) + "," + y(d.value); }).join(" ");
    svg.appendChild(el("polyline", { points: points, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));

    data.forEach(function (d, i) {
      var cx = x(i), cy = y(d.value);
      var dot = el("circle", { cx: cx, cy: cy, r: 4, fill: color, class: "chart-dot" });
      dot.addEventListener("mousemove", function (e) { showTooltip(e, "<strong>" + d.label + "</strong><br>" + fmt(d.value)); });
      dot.addEventListener("mouseleave", hideTooltip);
      svg.appendChild(dot);
      if (i === 0 || i === n - 1 || i % Math.ceil(n / 6) === 0) {
        svg.appendChild(el("text", { x: cx, y: height - 6, "text-anchor": "middle", class: "chart-axis" })).textContent = d.label;
      }
    });

    container.innerHTML = "";
    container.appendChild(svg);
  }

  global.RWCharts = { barChart: barChart, lineChart: lineChart };
})(window);
