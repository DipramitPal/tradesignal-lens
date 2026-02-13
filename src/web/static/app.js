/* TradeSignal Lens — Budget Advisor frontend */

// ── Helpers ──────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const show = (el) => el.classList.remove("hidden");
const hide = (el) => el.classList.add("hidden");
const fmt = (n) => Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });

function recBadgeClass(rec) {
  const r = (rec || "").toUpperCase();
  if (r === "STRONG BUY")  return "badge strong-buy";
  if (r === "BUY")         return "badge buy";
  if (r === "STRONG SELL") return "badge strong-sell";
  if (r === "SELL")        return "badge sell";
  return "badge hold";
}

function riskTagClass(level) {
  const l = (level || "").toLowerCase();
  if (l === "low")  return "risk-tag low";
  if (l === "high") return "risk-tag high";
  return "risk-tag medium";
}

// ── Market Status ────────────────────────────────────────────
async function fetchMarketStatus() {
  try {
    const res = await fetch("/api/market-status");
    const data = await res.json();
    const el = $("#market-status");
    if (data.is_open) {
      el.textContent = "Market Open";
      el.className = "market-badge open";
    } else {
      el.textContent = "Market Closed";
      el.className = "market-badge closed";
    }
  } catch { /* silent */ }
}
fetchMarketStatus();

// ── Tab Switching ────────────────────────────────────────────
function switchTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tab-panel").forEach((p) => {
    if (p.id === "panel-" + name) { show(p); p.classList.add("active"); }
    else { hide(p); p.classList.remove("active"); }
  });
}

// ── Main Request ─────────────────────────────────────────────
async function getSuggestions() {
  const budget = parseFloat($("#budget").value);
  const risk   = $("#risk").value;

  if (!budget || budget < 500) {
    showError("Please enter a budget of at least \u20b9500.");
    return;
  }

  hide($("#results"));
  hide($("#disclaimer"));
  hide($("#error-box"));
  show($("#loader"));
  $("#btn-suggest").disabled = true;

  try {
    const res = await fetch("/api/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ budget, risk_profile: risk }),
    });

    const data = await res.json();

    if (!res.ok) {
      showError(data.error || "Something went wrong.");
      return;
    }

    renderResults(data);
  } catch (err) {
    showError("Network error — is the server running?");
  } finally {
    hide($("#loader"));
    $("#btn-suggest").disabled = false;
  }
}

function showError(msg) {
  const el = $("#error-box");
  el.textContent = msg;
  show(el);
  hide($("#loader"));
  $("#btn-suggest").disabled = false;
}

// ── Render Results ───────────────────────────────────────────
function renderResults(data) {
  const s = data.suggestions;

  renderSingleStocks(s.single_stocks || []);
  renderIndexFunds(s.index_funds || []);
  renderBatches(s.batches || []);
  renderMixes(s.mixes || []);

  switchTab("single");
  show($("#results"));
  show($("#disclaimer"));
}

// ── Single Stocks ────────────────────────────────────────────
function renderSingleStocks(stocks) {
  const panel = $("#panel-single");
  if (!stocks.length) { panel.innerHTML = emptyState("No single-stock picks for this budget/risk combination."); return; }

  panel.innerHTML = stocks.map((s) => `
    <div class="suggestion-card">
      <div class="info">
        <div class="symbol">${esc(s.symbol)}</div>
        <div class="name">${esc(s.name)}</div>
        <div class="sector">${esc(s.sector)}</div>
      </div>
      <div class="metrics">
        <div class="metric"><div class="label">Price</div><div class="value">\u20b9${fmt(s.price)}</div></div>
        <div class="metric"><div class="label">Qty</div><div class="value">${s.quantity}</div></div>
        <div class="metric"><div class="label">Total</div><div class="value">\u20b9${fmt(s.total_cost)}</div></div>
        <div class="metric"><div class="label">RSI</div><div class="value">${fmt(s.rsi)}</div></div>
        <div class="metric"><div class="label">Score</div><div class="value">${s.score > 0 ? "+" : ""}${s.score.toFixed(3)}</div></div>
        <div class="metric"><span class="${recBadgeClass(s.recommendation)}">${esc(s.recommendation)}</span></div>
      </div>
    </div>
  `).join("");
}

// ── Index Funds ──────────────────────────────────────────────
function renderIndexFunds(funds) {
  const panel = $("#panel-index");
  if (!funds.length) { panel.innerHTML = emptyState("No index funds found for this budget."); return; }

  panel.innerHTML = funds.map((f) => `
    <div class="suggestion-card">
      <div class="info">
        <div class="symbol">${esc(f.symbol)}</div>
        <div class="name">${esc(f.name)}</div>
        <div class="sector">${esc(f.type)}</div>
      </div>
      <div class="metrics">
        <div class="metric"><div class="label">Price</div><div class="value">\u20b9${fmt(f.price)}</div></div>
        <div class="metric"><div class="label">Units</div><div class="value">${f.quantity}</div></div>
        <div class="metric"><div class="label">Total</div><div class="value">\u20b9${fmt(f.total_cost)}</div></div>
        <div class="metric"><div class="label">Remaining</div><div class="value">\u20b9${fmt(f.remaining)}</div></div>
      </div>
    </div>
    <p class="muted" style="margin:-0.4rem 0 1rem 0.2rem;font-size:0.8rem">${esc(f.description)}</p>
  `).join("");
}

// ── Batches ──────────────────────────────────────────────────
function renderBatches(batches) {
  const panel = $("#panel-batches");
  if (!batches.length) { panel.innerHTML = emptyState("Could not build diversified batches for this budget."); return; }

  panel.innerHTML = batches.map((b) => `
    <div class="batch-card">
      <div class="batch-header">
        <span class="batch-name">${esc(b.name)}</span>
        <span class="${riskTagClass(b.risk_level)}">Risk: ${esc(b.risk_level)}</span>
      </div>
      <div class="batch-desc">${esc(b.description)}</div>

      <table class="batch-stocks">
        <thead>
          <tr><th>Stock</th><th>Sector</th><th>Price</th><th>Qty</th><th>Allocation</th><th>Signal</th></tr>
        </thead>
        <tbody>
          ${b.stocks.map((s) => `
            <tr>
              <td><strong>${esc(s.symbol)}</strong><br><span class="muted" style="font-size:0.75rem">${esc(s.name)}</span></td>
              <td>${esc(s.sector)}</td>
              <td>\u20b9${fmt(s.price)}</td>
              <td>${s.quantity}</td>
              <td>\u20b9${fmt(s.allocation)}</td>
              <td><span class="${recBadgeClass(s.recommendation)}">${esc(s.recommendation)}</span></td>
            </tr>
          `).join("")}
        </tbody>
      </table>

      <div class="batch-footer">
        <span>Total: <strong>\u20b9${fmt(b.total_cost)}</strong></span>
        <span>Remaining: <strong>\u20b9${fmt(b.remaining)}</strong></span>
        <span>Sectors: <strong>${b.num_sectors}</strong></span>
      </div>
    </div>
  `).join("");
}

// ── Mixes ────────────────────────────────────────────────────
function renderMixes(mixes) {
  const panel = $("#panel-mixes");
  if (!mixes.length) { panel.innerHTML = emptyState("Could not build stock+ETF mixes for this budget."); return; }

  panel.innerHTML = mixes.map((m) => `
    <div class="mix-card">
      <div class="mix-name">${esc(m.name)}</div>
      <div class="mix-desc">${esc(m.description)}</div>

      ${m.stocks && m.stocks.length ? `
        <div class="mix-section-title">Stocks (${Math.round(m.stock_allocation_pct * 100)}%)</div>
        <table class="batch-stocks">
          <thead><tr><th>Stock</th><th>Price</th><th>Qty</th><th>Allocation</th><th>Signal</th></tr></thead>
          <tbody>${m.stocks.map((s) => `
            <tr>
              <td><strong>${esc(s.symbol)}</strong></td>
              <td>\u20b9${fmt(s.price)}</td>
              <td>${s.quantity}</td>
              <td>\u20b9${fmt(s.allocation)}</td>
              <td><span class="${recBadgeClass(s.recommendation)}">${esc(s.recommendation)}</span></td>
            </tr>
          `).join("")}</tbody>
        </table>
      ` : ""}

      ${m.index_funds && m.index_funds.length ? `
        <div class="mix-section-title">Index Funds (${Math.round(m.etf_allocation_pct * 100)}%)</div>
        <table class="batch-stocks">
          <thead><tr><th>ETF</th><th>Price</th><th>Units</th><th>Allocation</th></tr></thead>
          <tbody>${m.index_funds.map((f) => `
            <tr>
              <td><strong>${esc(f.symbol)}</strong><br><span class="muted" style="font-size:0.75rem">${esc(f.name)}</span></td>
              <td>\u20b9${fmt(f.price)}</td>
              <td>${f.quantity}</td>
              <td>\u20b9${fmt(f.allocation)}</td>
            </tr>
          `).join("")}</tbody>
        </table>
      ` : ""}

      <div class="batch-footer">
        <span>Total: <strong>\u20b9${fmt(m.total_cost)}</strong></span>
        <span>Remaining: <strong>\u20b9${fmt(m.remaining)}</strong></span>
      </div>
    </div>
  `).join("");
}

// ── Utilities ────────────────────────────────────────────────
function emptyState(msg) {
  return `<div class="empty-state">${esc(msg)}</div>`;
}

function esc(str) {
  const el = document.createElement("span");
  el.textContent = str;
  return el.innerHTML;
}
