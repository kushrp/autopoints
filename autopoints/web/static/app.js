(function () {
  "use strict";

  const form = document.getElementById("search-form");
  const submitBtn = document.getElementById("submit-btn");
  const banners = document.getElementById("banners");
  const resultsSection = document.getElementById("results-section");
  const resultsTitle = document.getElementById("results-title");
  const resultsSubtitle = document.getElementById("results-subtitle");
  const resultsTable = document.getElementById("results-table");
  const resultsTbody = document.getElementById("results-tbody");
  const emptyState = document.getElementById("empty-state");
  const heatmapSection = document.getElementById("heatmap-section");
  const heatmapEl = document.getElementById("heatmap");
  const originInput = document.getElementById("origin");
  const destinationInput = document.getElementById("destination");
  const departInput = document.getElementById("depart_date");

  let programsData = readProgramsData();
  let lastResponse = null;
  let sortKey = "effective_cpp";
  let sortDir = "desc";

  function readProgramsData() {
    const el = document.getElementById("programs-data");
    if (!el) return { valuations: {}, transfer_ratios: {}, supported_charts: [], cpp_thresholds: { great: 2.0, good: 1.5 } };
    try {
      const parsed = JSON.parse(el.textContent || "{}");
      return Object.assign(
        { valuations: {}, transfer_ratios: {}, supported_charts: [], cpp_thresholds: { great: 2.0, good: 1.5 } },
        parsed || {}
      );
    } catch (e) {
      return { valuations: {}, transfer_ratios: {}, supported_charts: [], cpp_thresholds: { great: 2.0, good: 1.5 } };
    }
  }

  function todayPlus(days) {
    const d = new Date();
    d.setDate(d.getDate() + days);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function init() {
    if (!departInput.value) departInput.value = todayPlus(60);

    [originInput, destinationInput].forEach((el) => {
      el.addEventListener("input", () => {
        const start = el.selectionStart;
        const end = el.selectionEnd;
        el.value = el.value.toUpperCase().replace(/[^A-Z]/g, "");
        try { el.setSelectionRange(start, end); } catch (e) { /* some inputs don't support selection */ }
      });
    });

    form.addEventListener("submit", onSubmit);

    document.querySelectorAll("#results-table thead th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.getAttribute("data-sort");
        if (sortKey === key) {
          sortDir = sortDir === "asc" ? "desc" : "asc";
        } else {
          sortKey = key;
          sortDir = isNumericKey(key) ? "desc" : "asc";
        }
        if (lastResponse) renderResults(lastResponse);
      });
    });

    if (!Object.keys(programsData.valuations || {}).length) {
      fetch("/api/programs")
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data) programsData = Object.assign(programsData, data);
        })
        .catch(() => {});
    }
  }

  function isNumericKey(k) {
    return ["points_required", "effective_points_required", "taxes_cents", "cash_cents", "cpp", "effective_cpp"].includes(k);
  }

  async function onSubmit(e) {
    e.preventDefault();
    clearBanners();

    const body = {
      origin: originInput.value.trim().toUpperCase(),
      destination: destinationInput.value.trim().toUpperCase(),
      depart_date: departInput.value,
      window_days: Number(document.getElementById("window_days").value) || 0,
      cabin: document.getElementById("cabin").value,
      passengers: Number(document.getElementById("passengers").value) || 1,
      demo: document.getElementById("demo").checked,
      live_aeroplan: document.getElementById("live_aeroplan").checked,
    };

    setLoading(true);
    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        let detail = "";
        try {
          const j = await res.json();
          detail = j.detail || j.error || JSON.stringify(j);
        } catch (_) {
          detail = await res.text();
        }
        showError(`Request failed (${res.status}): ${detail || "unknown error"}`);
        return;
      }
      const data = await res.json();
      lastResponse = data;
      if (Array.isArray(data.warnings)) {
        data.warnings.forEach((w) => showWarning(w));
      }
      renderResults(data);
      renderHeatmap(data);
    } catch (err) {
      showError(`Network error: ${err && err.message ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  }

  function setLoading(loading) {
    submitBtn.disabled = loading;
    Array.from(form.elements).forEach((el) => {
      if (el !== submitBtn) el.disabled = loading;
    });
    if (loading) {
      submitBtn.innerHTML = '<span class="spinner"></span>Searching…';
    } else {
      submitBtn.textContent = "Search";
    }
  }

  function clearBanners() {
    banners.innerHTML = "";
  }

  function showError(msg) {
    const div = document.createElement("div");
    div.className = "banner error";
    div.textContent = msg;
    banners.appendChild(div);
  }

  function showWarning(msg) {
    const div = document.createElement("div");
    div.className = "banner warn";
    div.textContent = msg;
    banners.appendChild(div);
  }

  function fmtInt(n) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toLocaleString("en-US");
  }

  function fmtUSD(cents) {
    if (cents == null || isNaN(cents)) return "—";
    return "$" + (cents / 100).toFixed(2);
  }

  function fmtCPP(cpp) {
    if (cpp == null || isNaN(cpp)) return "—";
    return Number(cpp).toFixed(2) + "¢";
  }

  function escapeHTML(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function pillTransfer(name) {
    const safe = escapeHTML(name || "—");
    return `<span class="pill transfer-${escapeHTML(name)}">${safe}</span>`;
  }

  function pillProgram(name) {
    const safe = escapeHTML(name || "—");
    return `<span class="pill program-${escapeHTML(name)}">${safe}</span>`;
  }

  function verdictBadge(v) {
    const safe = escapeHTML(v || "—");
    return `<span class="verdict verdict-${escapeHTML(v)}">${safe}</span>`;
  }

  function getRowSortValue(row, key) {
    switch (key) {
      case "transfer_program":
        return row.transfer_program || "";
      case "points_program":
        return row.points_program || "";
      case "date":
        return (row.cash_offer && row.cash_offer.depart_date) || (row.award_offer && row.award_offer.depart_date) || "";
      case "carrier":
        return (row.cash_offer && row.cash_offer.carrier) || "";
      case "points_required":
        return row.points_required ?? -1;
      case "effective_points_required":
        return row.effective_points_required ?? -1;
      case "taxes_cents":
        return (row.award_offer && row.award_offer.taxes_cents) ?? -1;
      case "cash_cents":
        return (row.cash_offer && row.cash_offer.cash_cents) ?? -1;
      case "cpp":
        return row.cpp ?? -Infinity;
      case "effective_cpp":
        return row.effective_cpp ?? -Infinity;
      case "verdict": {
        const order = { great: 4, good: 3, ok: 2, bad: 1 };
        return order[row.verdict] || 0;
      }
      default:
        return "";
    }
  }

  function sortRedemptions(rows) {
    const dir = sortDir === "asc" ? 1 : -1;
    const sorted = rows.slice();
    sorted.sort((a, b) => {
      const av = getRowSortValue(a, sortKey);
      const bv = getRowSortValue(b, sortKey);
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
    return sorted;
  }

  function updateSortIndicators() {
    document.querySelectorAll("#results-table thead th[data-sort]").forEach((th) => {
      th.classList.remove("sort-asc", "sort-desc");
      if (th.getAttribute("data-sort") === sortKey) {
        th.classList.add(sortDir === "asc" ? "sort-asc" : "sort-desc");
      }
    });
  }

  function renderResults(data) {
    resultsSection.classList.remove("hidden");
    const req = data.request || {};
    const rows = Array.isArray(data.redemptions) ? data.redemptions : [];

    const cabin = (req.cabin || "").replace("_", " ");
    resultsTitle.textContent = `${req.origin || "?"} → ${req.destination || "?"}  ·  ${cabin}`;

    const dates = data.cheapest_cash_by_date ? Object.keys(data.cheapest_cash_by_date).sort() : [];
    let rangeText = req.depart_date || "";
    if (dates.length >= 2) {
      rangeText = `${dates[0]} to ${dates[dates.length - 1]}`;
    } else if (req.depart_date && req.window_days) {
      rangeText = `${req.depart_date} ± ${req.window_days} days`;
    }
    const passengers = req.passengers || 1;
    resultsSubtitle.textContent = `${rangeText}  ·  ${passengers} ${passengers === 1 ? "passenger" : "passengers"}`;

    resultsTbody.innerHTML = "";

    if (rows.length === 0) {
      emptyState.classList.remove("hidden");
      resultsTable.classList.add("hidden");
      updateSortIndicators();
      return;
    }
    emptyState.classList.add("hidden");
    resultsTable.classList.remove("hidden");

    const sorted = sortRedemptions(rows);
    sorted.forEach((row, idx) => {
      const tr = document.createElement("tr");
      tr.className = "result-row";
      tr.dataset.index = String(idx);

      const date = (row.cash_offer && row.cash_offer.depart_date) || (row.award_offer && row.award_offer.depart_date) || "—";
      const carrier = (row.cash_offer && row.cash_offer.carrier) || "—";
      const taxes = row.award_offer ? row.award_offer.taxes_cents : null;
      const cash = row.cash_offer ? row.cash_offer.cash_cents : null;

      const showEff = row.effective_points_required != null && row.effective_points_required !== row.points_required;
      const verdict = row.verdict || "ok";

      const notes = Array.isArray(row.notes) && row.notes.length ? row.notes.join(" · ") : "";

      tr.innerHTML = `
        <td>${pillTransfer(row.transfer_program)}</td>
        <td>${pillProgram(row.points_program)}</td>
        <td>${escapeHTML(date)}</td>
        <td>${escapeHTML(carrier)}</td>
        <td class="num">${fmtInt(row.points_required)}</td>
        <td class="num">${showEff ? fmtInt(row.effective_points_required) : ""}</td>
        <td class="num">${fmtUSD(taxes)}</td>
        <td class="num">${fmtUSD(cash)}</td>
        <td class="num">${fmtCPP(row.cpp)}</td>
        <td class="num"><span class="eff-cpp verdict-${escapeHTML(verdict)}">${fmtCPP(row.effective_cpp)}</span></td>
        <td>${verdictBadge(verdict)}</td>
        <td><div class="notes">${escapeHTML(notes)}</div></td>
      `;

      tr.addEventListener("click", () => toggleDetail(tr, row));
      resultsTbody.appendChild(tr);
    });

    updateSortIndicators();
  }

  function toggleDetail(tr, row) {
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("detail-row")) {
      next.remove();
      return;
    }
    const detail = document.createElement("tr");
    detail.className = "detail-row";
    const td = document.createElement("td");
    td.colSpan = 12;
    td.innerHTML = renderDetail(row);
    detail.appendChild(td);
    tr.parentNode.insertBefore(detail, tr.nextElementSibling);
  }

  function renderDetail(row) {
    const cash = row.cash_offer || {};
    const award = row.award_offer || {};
    const cashRows = [
      ["Carrier", cash.carrier],
      ["Date", cash.depart_date],
      ["Cash", cash.cash_cents != null ? fmtUSD(cash.cash_cents) : null],
      ["Stops", cash.stops != null ? String(cash.stops) : null],
      ["Duration", cash.duration_minutes != null ? `${Math.floor(cash.duration_minutes / 60)}h ${cash.duration_minutes % 60}m` : null],
    ];
    const awardRows = [
      ["Provider", award.provider],
      ["Operating", award.operating_carrier],
      ["Date", award.depart_date],
      ["Points", award.points != null ? fmtInt(award.points) : null],
      ["Taxes", award.taxes_cents != null ? fmtUSD(award.taxes_cents) : null],
      ["Cabin", award.cabin],
    ];
    const fmtBlock = (title, pairs) => {
      const items = pairs
        .filter((p) => p[1] != null && p[1] !== "")
        .map((p) => `<dt>${escapeHTML(p[0])}</dt><dd>${escapeHTML(p[1])}</dd>`)
        .join("");
      return `<div class="detail-block"><h4>${escapeHTML(title)}</h4><dl>${items || "<dt>—</dt><dd></dd>"}</dl></div>`;
    };
    const notesHTML =
      Array.isArray(row.notes) && row.notes.length
        ? `<div class="detail-block"><h4>Notes</h4><div class="notes" style="display:block;-webkit-line-clamp:unset;max-width:none;">${row.notes.map(escapeHTML).join("<br/>")}</div></div>`
        : "";
    return `<div class="detail-grid">${fmtBlock("Cash offer", cashRows)}${fmtBlock("Award offer", awardRows)}</div>${notesHTML}`;
  }

  function renderHeatmap(data) {
    const req = data.request || {};
    const windowDays = req.window_days || 0;
    if (!windowDays) {
      heatmapSection.classList.add("hidden");
      heatmapEl.innerHTML = "";
      return;
    }
    const all = Array.isArray(data.all_redemptions) && data.all_redemptions.length
      ? data.all_redemptions
      : Array.isArray(data.redemptions) ? data.redemptions : [];

    const dateSet = new Set();
    if (data.cheapest_cash_by_date) Object.keys(data.cheapest_cash_by_date).forEach((d) => dateSet.add(d));
    all.forEach((r) => {
      const d = (r.cash_offer && r.cash_offer.depart_date) || (r.award_offer && r.award_offer.depart_date);
      if (d) dateSet.add(d);
    });
    const dates = Array.from(dateSet).sort();

    const programs = Array.from(new Set(all.map((r) => r.points_program).filter(Boolean))).sort();

    if (!dates.length || !programs.length) {
      heatmapSection.classList.add("hidden");
      heatmapEl.innerHTML = "";
      return;
    }

    const best = {};
    programs.forEach((p) => {
      best[p] = {};
      dates.forEach((d) => {
        best[p][d] = null;
      });
    });
    all.forEach((r) => {
      const p = r.points_program;
      const d = (r.cash_offer && r.cash_offer.depart_date) || (r.award_offer && r.award_offer.depart_date);
      if (!p || !d || !(p in best) || !(d in best[p])) return;
      const cpp = r.effective_cpp;
      if (cpp == null) return;
      if (best[p][d] == null || cpp > best[p][d].cpp) {
        best[p][d] = { cpp, verdict: r.verdict };
      }
    });

    const thresholds = (programsData.cpp_thresholds) || { great: 2.0, good: 1.5 };

    let html = '<table class="heatmap-table"><thead><tr><th class="heatmap-program"></th>';
    dates.forEach((d) => {
      html += `<th class="heatmap-date">${escapeHTML(formatShortDate(d))}</th>`;
    });
    html += "</tr></thead><tbody>";

    programs.forEach((p) => {
      html += `<tr><td class="heatmap-program">${pillProgram(p)}</td>`;
      dates.forEach((d) => {
        const cell = best[p][d];
        if (!cell) {
          html += `<td><div class="heat-cell empty">—</div></td>`;
        } else {
          const color = heatColor(cell.cpp, thresholds);
          html += `<td><div class="heat-cell" style="background:${color};">${fmtCPP(cell.cpp)}</div></td>`;
        }
      });
      html += "</tr>";
    });
    html += "</tbody></table>";
    heatmapEl.innerHTML = html;
    heatmapSection.classList.remove("hidden");
  }

  function formatShortDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (!m) return iso;
    const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
    const dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getUTCDay()];
    return `${dow} ${m[2]}/${m[3]}`;
  }

  function heatColor(cpp, thresholds) {
    const great = thresholds.great || 2.0;
    const good = thresholds.good || 1.5;
    const worst = 0;
    if (cpp >= great) return "#15803d";
    if (cpp >= good) {
      const t = (cpp - good) / Math.max(0.0001, great - good);
      return mix("#65a30d", "#15803d", t);
    }
    if (cpp >= worst) {
      const t = (cpp - worst) / Math.max(0.0001, good - worst);
      return mix("#dc2626", "#ca8a04", t);
    }
    return "#b91c1c";
  }

  function mix(a, b, t) {
    const ca = hexToRgb(a);
    const cb = hexToRgb(b);
    const tt = Math.max(0, Math.min(1, t));
    const r = Math.round(ca.r + (cb.r - ca.r) * tt);
    const g = Math.round(ca.g + (cb.g - ca.g) * tt);
    const bl = Math.round(ca.b + (cb.b - ca.b) * tt);
    return `rgb(${r},${g},${bl})`;
  }

  function hexToRgb(hex) {
    const h = hex.replace("#", "");
    return {
      r: parseInt(h.slice(0, 2), 16),
      g: parseInt(h.slice(2, 4), 16),
      b: parseInt(h.slice(4, 6), 16),
    };
  }

  init();
})();
