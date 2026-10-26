/* Dashboard charts drawn as plain SVG/HTML. No libraries, so they work offline.
   Data comes from the admin-only JSON endpoint named in [data-stats-url]. */
(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var COLORS = {
    created: '#1b4470',
    resolved: '#2a9160',
    status: {
      'Pending': '#e0a100',
      'In Progress': '#2f74b8',
      'Resolved': '#2a9160',
      'Rejected': '#c8473d',
      'Cancelled': '#8b97ab'
    }
  };

  /* ---- tiny DOM helpers -------------------------------------------------- */
  function svgEl(name, attrs, parent) {
    var node = document.createElementNS(SVG_NS, name);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (parent) { parent.appendChild(node); }
    return node;
  }

  function htmlEl(name, className, text, parent) {
    var node = document.createElement(name);
    if (className) { node.className = className; }
    if (text !== null && text !== undefined) { node.textContent = text; }
    if (parent) { parent.appendChild(node); }
    return node;
  }

  function clear(node) {
    while (node.firstChild) { node.removeChild(node.firstChild); }
  }

  function message(target, text) {
    clear(target);
    htmlEl('p', 'faint', text, target);
  }

  function sum(values) {
    return values.reduce(function (total, value) { return total + value; }, 0);
  }

  /* Smallest multiple of 4 that is >= value (at least 4), so the four
     grid intervals always land on whole numbers. */
  function niceMax(value) {
    return Math.max(4, Math.ceil(value / 4) * 4);
  }

  /* ---- line chart: submitted vs resolved per day ------------------------- */
  function renderTrend(target, trend) {
    var W = 760, H = 250;
    var M = { top: 14, right: 14, bottom: 30, left: 34 };
    var innerW = W - M.left - M.right;
    var innerH = H - M.top - M.bottom;
    var count = trend.labels.length;
    var top = niceMax(Math.max.apply(null, trend.created.concat(trend.resolved)));

    function x(i) { return M.left + (count === 1 ? innerW / 2 : (i * innerW) / (count - 1)); }
    function y(v) { return M.top + innerH - (v / top) * innerH; }

    clear(target);
    target.setAttribute('aria-label',
      'Line chart. ' + sum(trend.created) + ' requests submitted and ' +
      sum(trend.resolved) + ' resolved over the last ' + count + ' days.');

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + W + ' ' + H,
      preserveAspectRatio: 'xMidYMid meet',
      focusable: 'false'
    }, target);

    for (var tick = 0; tick <= 4; tick++) {
      var value = (top / 4) * tick;
      svgEl('line', { x1: M.left, x2: W - M.right, y1: y(value), y2: y(value), 'class': 'grid-line' }, svg);
      var yLabel = svgEl('text', { x: M.left - 8, y: y(value) + 4, 'text-anchor': 'end', 'class': 'axis-label' }, svg);
      yLabel.textContent = value;
    }

    trend.labels.forEach(function (text, i) {
      if (i % 2 === (count - 1) % 2) {
        var xLabel = svgEl('text', { x: x(i), y: H - 8, 'text-anchor': 'middle', 'class': 'axis-label' }, svg);
        xLabel.textContent = text;
      }
    });

    var areaPoints = trend.created.map(function (v, i) { return x(i) + ',' + y(v); });
    areaPoints.push(x(count - 1) + ',' + y(0), x(0) + ',' + y(0));
    svgEl('polygon', { points: areaPoints.join(' '), fill: COLORS.created, 'fill-opacity': '0.08' }, svg);

    function drawSeries(values, color, noun) {
      var points = values.map(function (v, i) { return x(i) + ',' + y(v); }).join(' ');
      svgEl('polyline', {
        points: points, fill: 'none', stroke: color, 'stroke-width': '2.5',
        'stroke-linejoin': 'round', 'stroke-linecap': 'round'
      }, svg);
      values.forEach(function (v, i) {
        var dot = svgEl('circle', {
          cx: x(i), cy: y(v), r: '3.6', fill: '#fff', stroke: color, 'stroke-width': '2'
        }, svg);
        var title = svgEl('title', {}, dot);
        title.textContent = trend.labels[i] + ': ' + v + ' ' + noun;
      });
    }

    drawSeries(trend.created, COLORS.created, 'submitted');
    drawSeries(trend.resolved, COLORS.resolved, 'resolved');
  }

  /* ---- donut chart: requests by status ----------------------------------- */
  function renderStatus(target, items) {
    var total = sum(items.map(function (item) { return item.value; }));
    if (!total) { message(target, 'No requests yet.'); return; }

    clear(target);
    target.setAttribute('role', 'img');
    target.setAttribute('aria-label', 'Donut chart of requests by status. ' +
      items.map(function (item) { return item.label + ' ' + item.value; }).join(', ') + '.');

    var wrap = htmlEl('div', 'donut-wrap', null, target);
    var svg = svgEl('svg', { viewBox: '0 0 42 42', 'class': 'donut', focusable: 'false' }, wrap);
    var radius = 15.9155; // circumference = 100, so dash lengths are percentages

    svgEl('circle', { cx: 21, cy: 21, r: radius, fill: 'none', stroke: '#e6e9ef', 'stroke-width': 6 }, svg);

    var offset = 25; // start at 12 o'clock
    items.forEach(function (item) {
      if (!item.value) { return; }
      var percent = (item.value / total) * 100;
      var arc = svgEl('circle', {
        cx: 21, cy: 21, r: radius, fill: 'none',
        stroke: COLORS.status[item.label] || '#8b97ab', 'stroke-width': 6,
        'stroke-dasharray': percent + ' ' + (100 - percent),
        'stroke-dashoffset': offset
      }, svg);
      var title = svgEl('title', {}, arc);
      title.textContent = item.label + ': ' + item.value;
      offset -= percent;
    });

    var big = svgEl('text', { x: 21, y: 22.5, 'text-anchor': 'middle', 'class': 'donut-total' }, svg);
    big.textContent = total;
    var caption = svgEl('text', { x: 21, y: 27, 'text-anchor': 'middle', 'class': 'donut-caption' }, svg);
    caption.textContent = 'requests';

    var list = htmlEl('ul', 'legend-list', null, wrap);
    items.forEach(function (item) {
      var row = htmlEl('li', null, null, list);
      var swatch = htmlEl('i', 'sw', null, row);
      swatch.style.background = COLORS.status[item.label] || '#8b97ab';
      htmlEl('span', null, item.label, row);
      htmlEl('b', null, String(item.value), row);
    });
  }

  /* ---- horizontal bars: requests by category ----------------------------- */
  function renderCategories(target, items) {
    if (!items.length) { message(target, 'No requests yet.'); return; }
    clear(target);
    var max = Math.max.apply(null, items.map(function (item) { return item.value; }));
    items.forEach(function (item) {
      var row = htmlEl('div', 'bar-row', null, target);
      htmlEl('span', null, item.label, row);
      var track = htmlEl('div', 'bar-track', null, row);
      var fill = htmlEl('div', 'bar-fill', null, track);
      fill.style.width = ((item.value / max) * 100) + '%';
      htmlEl('b', null, String(item.value), row);
    });
  }

  /* ---- boot --------------------------------------------------------------- */
  function init() {
    var root = document.querySelector('[data-stats-url]');
    if (!root) { return; }

    var targets = {
      trend: document.getElementById('chart-trend'),
      status: document.getElementById('chart-status'),
      category: document.getElementById('chart-category')
    };

    fetch(root.getAttribute('data-stats-url'), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (response) {
        if (!response.ok) { throw new Error('HTTP ' + response.status); }
        return response.json();
      })
      .then(function (stats) {
        renderTrend(targets.trend, stats.trend);
        renderStatus(targets.status, stats.statuses);
        renderCategories(targets.category, stats.categories);
      })
      .catch(function () {
        Object.keys(targets).forEach(function (key) {
          if (targets[key]) { message(targets[key], 'The chart could not be loaded. Refresh the page to try again.'); }
        });
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
