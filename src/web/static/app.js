/* ================================================================
   TradeSignal Lens — Dashboard JavaScript
   ================================================================ */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentTab = 'summary';
let chartInstance = null;
let candleSeries = null;
let volumeSeries = null;
let sma20Series = null;
let sma50Series = null;
let slLine = null;
let entryLine = null;

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  loadMarketStatus();
  loadSummary();
  loadCacheStatus();
  setupSearch();
  // Refresh market status + cache status every 60s
  setInterval(loadMarketStatus, 60000);
  setInterval(loadCacheStatus, 60000);
  // Auto-refresh active tab every 60s
  setInterval(refreshCurrentTab, 60000);
});

// ---------------------------------------------------------------------------
// TAB NAVIGATION
// ---------------------------------------------------------------------------
function switchTab(tab) {
  currentTab = tab;

  // Update nav buttons
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });

  // Show/hide panels
  document.querySelectorAll('.tab-panel').forEach(panel => {
    panel.classList.toggle('hidden', panel.id !== `panel-${tab}`);
    if (panel.id === `panel-${tab}`) {
      panel.classList.add('active');
    } else {
      panel.classList.remove('active');
    }
  });

  // Load data for tab
  switch (tab) {
    case 'summary': loadSummary(); break;
    case 'portfolio': loadPortfolio(); break;
    case 'watchlist': loadWatchlist(); break;
    case 'tracking': loadTracking(); break;
    case 'momentum': loadMomentum(); break;
  }
}

function refreshCurrentTab() {
  switchTab(currentTab);
}

// ---------------------------------------------------------------------------
// MARKET STATUS
// ---------------------------------------------------------------------------
async function loadMarketStatus() {
  try {
    const res = await fetch('/api/market-status');
    const data = await res.json();
    const badge = document.getElementById('market-badge');
    const isOpen = data.is_open || data.status === 'open';
    badge.className = 'market-badge ' + (isOpen ? 'open' : 'closed');
    badge.querySelector('.badge-text').textContent = isOpen ? 'Market Open' : 'Market Closed';
  } catch (e) {
    console.error('Market status error:', e);
  }
}

async function loadCacheStatus() {
  try {
    const res = await fetch('/api/cache-status');
    const data = await res.json();
    const el = document.getElementById('last-updated');
    if (data.last_refresh) {
      const dt = new Date(data.last_refresh);
      el.textContent = `Data: ${dt.toLocaleTimeString()} · ${data.symbols_cached} symbols · Every ${data.refresh_interval_minutes}m`;
    } else {
      el.textContent = 'Data: warming cache...';
    }
  } catch (e) {
    console.error('Cache status error:', e);
  }
}

// ---------------------------------------------------------------------------
// SUMMARY
// ---------------------------------------------------------------------------
async function loadSummary() {
  const container = document.getElementById('summary-content');
  container.innerHTML = '<div class="loader-inline"><div class="spinner"></div> Loading summary...</div>';

  try {
    const res = await fetch('/api/summary');
    const data = await res.json();
    const p = data.portfolio;
    const t = data.tracking;
    const m = data.market;

    const pnlClass = p.total_pnl >= 0 ? 'positive' : 'negative';
    const pnlSign = p.total_pnl >= 0 ? '+' : '';

    // Market investability
    const investClass = m.investable ? 'positive' : (m.regime === 'RANGE_BOUND' ? 'neutral' : 'negative');
    const investIcon = m.investable ? '✅' : (m.regime === 'RANGE_BOUND' ? '⚠️' : '🛑');
    const investLabel = m.investable ? 'Market looks investable' : 'Caution advised';
    const reasonsList = m.reasons.map(r => `<li>${r}</li>`).join('');

    // Top gainers/losers
    const gainersList = p.top_gainers.map(g =>
      `<li><span class="sym">${g.symbol.replace('.NS', '')}</span> <span class="${g.pnl_pct >= 0 ? 'text-green' : 'text-red'}">${g.pnl_pct >= 0 ? '+' : ''}${g.pnl_pct}%</span></li>`
    ).join('');
    const losersList = p.top_losers.map(l =>
      `<li><span class="sym">${l.symbol.replace('.NS', '')}</span> <span class="${l.pnl_pct >= 0 ? 'text-green' : 'text-red'}">${l.pnl_pct >= 0 ? '+' : ''}${l.pnl_pct}%</span></li>`
    ).join('');

    // Sector breakdown
    const sectors = Object.entries(p.sectors || {}).sort((a, b) => b[1] - a[1]);
    const sectorBars = sectors.slice(0, 6).map(([sec, val]) => {
      const pct = p.total_current > 0 ? ((val / p.total_current) * 100).toFixed(1) : 0;
      return `<div style="margin-bottom:6px;">
        <div class="flex justify-between" style="font-size:12px;margin-bottom:2px;">
          <span>${sec}</span><span class="text-muted">${pct}%</span>
        </div>
        <div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden;">
          <div style="width:${pct}%;height:100%;background:var(--gradient);border-radius:2px;"></div>
        </div>
      </div>`;
    }).join('');

    container.innerHTML = `
      <!-- Row 1: Key Metrics -->
      <div class="card">
        <div class="card-title">Portfolio Value</div>
        <div class="card-value">₹${formatNum(p.total_current)}</div>
        <div class="card-sub">${p.count} holdings</div>
      </div>

      <div class="card">
        <div class="card-title">Total P&L</div>
        <div class="card-value ${pnlClass}">${pnlSign}₹${formatNum(Math.abs(p.total_pnl))}</div>
        <div class="card-sub ${pnlClass}">${pnlSign}${p.total_pnl_pct.toFixed(2)}%</div>
      </div>

      <div class="card">
        <div class="card-title">Total Invested</div>
        <div class="card-value">₹${formatNum(p.total_invested)}</div>
        <div class="card-sub">Account: ₹${formatNum(p.account_value)}</div>
      </div>

      <div class="card">
        <div class="card-title">Tracking</div>
        <div class="card-value">${t.count}</div>
        <div class="card-sub">Paper positions</div>
      </div>

      <!-- Row 2: Market Verdict -->
      <div class="summary-full">
        <div class="invest-verdict ${investClass}">
          <span class="verdict-icon">${investIcon}</span>
          <div class="verdict-text">
            <strong>${investLabel} — Regime: ${m.regime}</strong>
            <ul>${reasonsList}</ul>
          </div>
        </div>
      </div>

      <!-- Row 3: Details -->
      <div class="card">
        <div class="card-title">Top Gainers</div>
        <ul class="mini-list">${gainersList || '<li class="text-muted">No data</li>'}</ul>
      </div>

      <div class="card">
        <div class="card-title">Top Losers</div>
        <ul class="mini-list">${losersList || '<li class="text-muted">No data</li>'}</ul>
      </div>

      <div class="card">
        <div class="card-title">Sector Allocation</div>
        <div style="margin-top:8px;">${sectorBars || '<span class="text-muted">No holdings</span>'}</div>
      </div>

      ${t.items && t.items.length > 0 ? `
      <div class="card summary-full">
        <div class="card-title">Tracked Stocks</div>
        <table class="data-table" style="margin-top:8px;">
          <thead><tr><th>Symbol</th><th>Qty</th><th>Sim. Price</th><th>Current</th><th>P&L</th></tr></thead>
          <tbody>
            ${t.items.map(item => `<tr onclick="openStockDrawer('${item.symbol}')">
              <td class="sym-cell">${item.symbol.replace('.NS', '')}</td>
              <td>${item.qty}</td>
              <td>₹${item.simulated_price.toFixed(2)}</td>
              <td>₹${item.current_price.toFixed(2)}</td>
              <td class="${item.pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative'}">${item.pnl_pct >= 0 ? '+' : ''}${item.pnl_pct}%</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>` : ''}
    `;

    // last-updated is handled by loadCacheStatus()
  } catch (e) {
    container.innerHTML = `<div class="text-red">Error loading summary: ${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------------
// PORTFOLIO
// ---------------------------------------------------------------------------
async function loadPortfolio() {
  const container = document.getElementById('portfolio-content');
  container.innerHTML = '<div class="loader-inline"><div class="spinner"></div> Loading portfolio...</div>';

  try {
    const res = await fetch('/api/portfolio');
    const data = await res.json();
    const items = data.holdings || [];

    if (items.length === 0) {
      container.innerHTML = '<div class="text-muted" style="padding:40px 0;">No holdings yet. Add stocks to your portfolio.</div>';
      return;
    }

    const totalInvested = items.reduce((a, h) => a + h.invested, 0);
    const totalCurrent = items.reduce((a, h) => a + h.current_value, 0);
    const totalPnl = totalCurrent - totalInvested;
    const totalPnlPct = totalInvested > 0 ? (totalPnl / totalInvested * 100) : 0;
    const pnlClass = totalPnl >= 0 ? 'pnl-positive' : 'pnl-negative';

    const rows = items.map(h => `
      <tr onclick="openStockDrawer('${h.symbol}')">
        <td class="sym-cell">${h.symbol.replace('.NS', '')}</td>
        <td><span class="sector-badge">${h.sector}</span></td>
        <td>${h.qty}</td>
        <td>₹${h.avg_price.toFixed(2)}</td>
        <td>₹${h.current_price.toFixed(2)}</td>
        <td>₹${formatNum(h.invested)}</td>
        <td>₹${formatNum(h.current_value)}</td>
        <td class="${h.pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative'}">${h.pnl_pct >= 0 ? '+' : ''}${h.pnl_pct}%</td>
        <td class="${h.pnl_abs >= 0 ? 'pnl-positive' : 'pnl-negative'}">${h.pnl_abs >= 0 ? '+' : ''}₹${formatNum(Math.abs(h.pnl_abs))}</td>
        <td>
          <button class="btn-danger" onclick="event.stopPropagation(); removeFromPortfolio('${h.symbol}')" title="Remove">✕</button>
        </td>
      </tr>
    `).join('');

    container.innerHTML = `
      <div class="flex gap-8 mb-8" style="flex-wrap:wrap;gap:12px;">
        <div class="card" style="min-width:180px;">
          <div class="card-title">Total Invested</div>
          <div class="card-value" style="font-size:20px;">₹${formatNum(totalInvested)}</div>
        </div>
        <div class="card" style="min-width:180px;">
          <div class="card-title">Current Value</div>
          <div class="card-value" style="font-size:20px;">₹${formatNum(totalCurrent)}</div>
        </div>
        <div class="card" style="min-width:180px;">
          <div class="card-title">Total P&L</div>
          <div class="card-value ${pnlClass}" style="font-size:20px;">${totalPnl >= 0 ? '+' : ''}₹${formatNum(Math.abs(totalPnl))}</div>
          <div class="card-sub ${pnlClass}">${totalPnlPct >= 0 ? '+' : ''}${totalPnlPct.toFixed(2)}%</div>
        </div>
      </div>

      <div class="card" style="overflow-x:auto;">
        <table class="data-table">
          <thead>
            <tr>
              <th>Symbol</th><th>Sector</th><th>Qty</th><th>Avg Price</th>
              <th>Current</th><th>Invested</th><th>Value</th><th>P&L %</th><th>P&L ₹</th><th></th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  } catch (e) {
    container.innerHTML = `<div class="text-red">Error: ${e.message}</div>`;
  }
}

async function removeFromPortfolio(symbol) {
  if (!confirm(`Remove ${symbol} from portfolio?`)) return;
  await fetch('/api/portfolio/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol }),
  });
  loadPortfolio();
}

function showAddToPortfolioModal() {
  showModal('Add to Portfolio', `
    <div class="form-group">
      <label>Symbol</label>
      <input id="modal-symbol" type="text" placeholder="e.g. RELIANCE.NS" autofocus>
    </div>
    <div class="form-group">
      <label>Quantity</label>
      <input id="modal-qty" type="number" min="1" value="1">
    </div>
    <div class="form-group">
      <label>Buy Price (₹)</label>
      <input id="modal-price" type="number" step="0.01" min="0" placeholder="0 = auto-fetch">
    </div>
    <div class="modal-actions">
      <button class="btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn-primary" onclick="addToPortfolio()">Add to Portfolio</button>
    </div>
  `);
}

async function addToPortfolio() {
  const symbol = document.getElementById('modal-symbol').value.trim().toUpperCase();
  const qty = parseInt(document.getElementById('modal-qty').value) || 1;
  const price = parseFloat(document.getElementById('modal-price').value) || 0;

  if (!symbol) return alert('Please enter a symbol');

  const res = await fetch('/api/portfolio/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, qty, price: price || 0 }),
  });

  if (res.ok) {
    closeModal();
    loadPortfolio();
  } else {
    const err = await res.json();
    alert(err.error || 'Error adding to portfolio');
  }
}

// ---------------------------------------------------------------------------
// WATCHLIST
// ---------------------------------------------------------------------------
async function loadWatchlist() {
  const container = document.getElementById('watchlist-content');
  container.innerHTML = '<div class="loader-inline"><div class="spinner"></div> Scanning stocks (this may take 30-60s on first load)...</div>';

  try {
    const res = await fetch('/api/watchlist');
    const data = await res.json();
    const items = data.items || [];

    if (items.length === 0) {
      container.innerHTML = '<div class="text-muted" style="padding:40px 0;">No watchlist data. Run a scan first.</div>';
      return;
    }

    const highCount = items.filter(i => i.tier === 'HIGH').length;
    const medCount = items.filter(i => i.tier === 'MEDIUM').length;
    const lowCount = items.filter(i => i.tier === 'LOW').length;

    const rows = items.map(item => `
      <tr onclick="openStockDrawer('${item.symbol}')">
        <td class="sym-cell">${item.symbol.replace('.NS', '')}</td>
        <td><span class="tier-badge ${item.tier}">${item.tier}</span></td>
        <td>₹${item.price.toFixed(2)}</td>
        <td class="${item.day_change_pct >= 0 ? 'pnl-positive' : 'pnl-negative'}">${item.day_change_pct >= 0 ? '+' : ''}${item.day_change_pct}%</td>
        <td>${item.mtf_score.toFixed(3)}</td>
        <td>${item.entry_quality}/100</td>
        <td>${item.rsi}</td>
        <td>${item.rvol.toFixed(1)}x</td>
        <td><span class="sector-badge">${item.sector}</span></td>
        <td>₹${item.stop_loss.toFixed(2)}</td>
        <td>
          <button class="btn-success" onclick="event.stopPropagation(); quickTrack('${item.symbol}', ${item.price})" title="Track">🎯</button>
        </td>
      </tr>
    `).join('');

    container.innerHTML = `
      <div class="flex gap-8 mb-8" style="gap:12px;flex-wrap:wrap;">
        <div class="card" style="min-width:140px;text-align:center;">
          <div class="card-title">Regime</div>
          <div style="font-size:16px;font-weight:700;color:var(--cyan);">${data.regime}</div>
        </div>
        <div class="card" style="min-width:140px;text-align:center;">
          <div class="card-title">🟢 High</div>
          <div style="font-size:20px;font-weight:700;color:var(--green);">${highCount}</div>
        </div>
        <div class="card" style="min-width:140px;text-align:center;">
          <div class="card-title">🟡 Medium</div>
          <div style="font-size:20px;font-weight:700;color:var(--amber);">${medCount}</div>
        </div>
        <div class="card" style="min-width:140px;text-align:center;">
          <div class="card-title">🔴 Low</div>
          <div style="font-size:20px;font-weight:700;color:var(--text-muted);">${lowCount}</div>
        </div>
      </div>

      <div class="card" style="overflow-x:auto;">
        <table class="data-table">
          <thead>
            <tr>
              <th>Symbol</th><th>Tier</th><th>Price</th><th>Change</th>
              <th>MTF Score</th><th>Quality</th><th>RSI</th><th>RVOL</th>
              <th>Sector</th><th>SL</th><th>Track</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  } catch (e) {
    container.innerHTML = `<div class="text-red">Error: ${e.message}</div>`;
  }
}

async function quickTrack(symbol, price) {
  const res = await fetch('/api/tracking/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, qty: 1, price }),
  });
  if (res.ok) {
    alert(`${symbol} added to tracking at ₹${price}`);
  } else {
    const err = await res.json();
    alert(err.error || 'Error');
  }
}

// ---------------------------------------------------------------------------
// TRACKING
// ---------------------------------------------------------------------------
async function loadTracking() {
  const container = document.getElementById('tracking-content');
  container.innerHTML = '<div class="loader-inline"><div class="spinner"></div> Loading tracking...</div>';

  try {
    const res = await fetch('/api/tracking');
    const data = await res.json();
    const items = data.items || [];

    if (items.length === 0) {
      container.innerHTML = '<div class="text-muted" style="padding:40px 0;">No tracked stocks. Add stocks from the Watchlist or use the button above.</div>';
      return;
    }

    const rows = items.map(item => `
      <tr>
        <td class="sym-cell" style="cursor:pointer;" onclick="openStockDrawer('${item.symbol}')">${item.symbol.replace('.NS', '')}</td>
        <td>
          <input class="editable-cell" type="number" min="1" value="${item.qty}"
                 onchange="updateTracking('${item.symbol}', 'qty', this.value)" title="Edit quantity">
        </td>
        <td>
          <input class="editable-cell" type="number" step="0.01" value="${item.simulated_price.toFixed(2)}"
                 onchange="updateTracking('${item.symbol}', 'price', this.value)" title="Edit price">
        </td>
        <td>₹${item.current_price.toFixed(2)}</td>
        <td class="${item.pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative'}">${item.pnl_pct >= 0 ? '+' : ''}${item.pnl_pct}%</td>
        <td class="${item.pnl_abs >= 0 ? 'pnl-positive' : 'pnl-negative'}">${item.pnl_abs >= 0 ? '+' : ''}₹${formatNum(Math.abs(item.pnl_abs))}</td>
        <td>
          <button class="btn-success" onclick="showBuyModal('${item.symbol}', ${item.qty}, ${item.simulated_price})" title="Mark as Bought">💰 Buy</button>
          <button class="btn-danger" style="margin-left:6px;" onclick="removeTracking('${item.symbol}')" title="Remove">✕</button>
        </td>
      </tr>
    `).join('');

    container.innerHTML = `
      <div class="card" style="overflow-x:auto;">
        <table class="data-table">
          <thead>
            <tr>
              <th>Symbol</th><th>Qty</th><th>Sim. Price</th><th>Current</th>
              <th>P&L %</th><th>P&L ₹</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  } catch (e) {
    container.innerHTML = `<div class="text-red">Error: ${e.message}</div>`;
  }
}

async function updateTracking(symbol, field, value) {
  const body = { symbol };
  if (field === 'qty') body.qty = parseInt(value);
  if (field === 'price') body.price = parseFloat(value);

  await fetch('/api/tracking/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

async function removeTracking(symbol) {
  if (!confirm(`Remove ${symbol} from tracking?`)) return;
  await fetch('/api/tracking/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol }),
  });
  loadTracking();
}

function showBuyModal(symbol, qty, price) {
  showModal('Mark as Bought', `
    <p style="color:var(--text-secondary);margin-bottom:14px;">Move <strong>${symbol}</strong> from tracking to your real portfolio.</p>
    <div class="form-group">
      <label>Quantity</label>
      <input id="buy-qty" type="number" min="1" value="${qty}">
    </div>
    <div class="form-group">
      <label>Buy Price (₹)</label>
      <input id="buy-price" type="number" step="0.01" value="${price.toFixed(2)}">
    </div>
    <div class="modal-actions">
      <button class="btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn-primary" onclick="confirmBuy('${symbol}')">✅ Confirm Buy</button>
    </div>
  `);
}

async function confirmBuy(symbol) {
  const qty = parseInt(document.getElementById('buy-qty').value);
  const price = parseFloat(document.getElementById('buy-price').value);

  const res = await fetch('/api/tracking/buy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, qty, price }),
  });

  if (res.ok) {
    closeModal();
    loadTracking();
    alert(`${symbol} moved to portfolio! Qty: ${qty}, Price: ₹${price}`);
  } else {
    const err = await res.json();
    alert(err.error || 'Error');
  }
}

function showAddTrackingModal() {
  showModal('Add to Tracking', `
    <div class="form-group">
      <label>Symbol</label>
      <input id="track-symbol" type="text" placeholder="e.g. RELIANCE.NS" autofocus>
    </div>
    <div class="form-group">
      <label>Quantity</label>
      <input id="track-qty" type="number" min="1" value="1">
    </div>
    <div class="form-group">
      <label>Simulated Buy Price (₹) — leave 0 for current price</label>
      <input id="track-price" type="number" step="0.01" min="0" value="0">
    </div>
    <div class="modal-actions">
      <button class="btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn-primary" onclick="addTracking()">🎯 Add to Track</button>
    </div>
  `);
}

async function addTracking() {
  const symbol = document.getElementById('track-symbol').value.trim().toUpperCase();
  const qty = parseInt(document.getElementById('track-qty').value) || 1;
  const price = parseFloat(document.getElementById('track-price').value) || 0;

  if (!symbol) return alert('Please enter a symbol');

  const res = await fetch('/api/tracking/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, qty, price }),
  });

  if (res.ok) {
    const data = await res.json();
    closeModal();
    loadTracking();
    alert(`${symbol} added to tracking at ₹${data.price}`);
  } else {
    const err = await res.json();
    alert(err.error || 'Error');
  }
}

// ---------------------------------------------------------------------------
// MOMENTUM (reuses watchlist data, sorted differently)
// ---------------------------------------------------------------------------
async function loadMomentum() {
  const container = document.getElementById('momentum-content');
  container.innerHTML = '<div class="loader-inline"><div class="spinner"></div> Scanning momentum stocks...</div>';

  try {
    const res = await fetch('/api/watchlist');
    const data = await res.json();
    let items = data.items || [];

    // Filter positive scores and sort by momentum (score × rvol × entry_quality)
    items = items
      .filter(i => i.mtf_score > 0)
      .map(i => ({ ...i, momentum: i.mtf_score * i.rvol * (i.entry_quality / 100) }))
      .sort((a, b) => b.momentum - a.momentum)
      .slice(0, 15);

    if (items.length === 0) {
      container.innerHTML = '<div class="text-muted" style="padding:40px 0;">No momentum stocks found.</div>';
      return;
    }

    const rows = items.map((item, idx) => `
      <tr onclick="openStockDrawer('${item.symbol}')">
        <td style="color:var(--text-muted);font-weight:600;">#${idx + 1}</td>
        <td class="sym-cell">${item.symbol.replace('.NS', '')}</td>
        <td>₹${item.price.toFixed(2)}</td>
        <td class="${item.day_change_pct >= 0 ? 'pnl-positive' : 'pnl-negative'}">${item.day_change_pct >= 0 ? '+' : ''}${item.day_change_pct}%</td>
        <td style="font-weight:600;color:var(--cyan);">${item.momentum.toFixed(3)}</td>
        <td>${item.mtf_score.toFixed(3)}</td>
        <td>${item.rvol.toFixed(1)}x</td>
        <td>${item.entry_quality}/100</td>
        <td>${item.squeeze_fire ? '🔥' : '—'}</td>
        <td><span class="tier-badge ${item.tier}">${item.tier}</span></td>
        <td>
          <button class="btn-success" onclick="event.stopPropagation(); quickTrack('${item.symbol}', ${item.price})" title="Track">🎯</button>
        </td>
      </tr>
    `).join('');

    container.innerHTML = `
      <div class="card" style="overflow-x:auto;">
        <table class="data-table">
          <thead>
            <tr>
              <th>#</th><th>Symbol</th><th>Price</th><th>Change</th>
              <th>Momentum</th><th>MTF</th><th>RVOL</th><th>Quality</th>
              <th>Squeeze</th><th>Tier</th><th>Track</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  } catch (e) {
    container.innerHTML = `<div class="text-red">Error: ${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------------
// STOCK DETAIL DRAWER
// ---------------------------------------------------------------------------
async function openStockDrawer(symbol) {
  const drawer = document.getElementById('stock-drawer');
  const title = document.getElementById('drawer-title');
  const chartDiv = document.getElementById('drawer-chart');
  const analysisDiv = document.getElementById('drawer-analysis');

  title.textContent = symbol.replace('.NS', '') + ' — Loading...';
  analysisDiv.innerHTML = '<div class="loader-inline"><div class="spinner"></div></div>';
  drawer.classList.remove('hidden');

  // Load chart
  try {
    const chartRes = await fetch(`/api/stock/${encodeURIComponent(symbol)}/chart`);
    const chartData = await chartRes.json();

    if (chartData.error) {
      chartDiv.innerHTML = `<div class="text-muted" style="padding:20px;">No chart data for ${symbol}</div>`;
    } else {
      renderChart(chartDiv, chartData);
    }
  } catch (e) {
    chartDiv.innerHTML = `<div class="text-red">Chart error: ${e.message}</div>`;
  }

  // Load analysis
  try {
    const aRes = await fetch(`/api/stock/${encodeURIComponent(symbol)}/analysis`);
    const analysis = await aRes.json();

    if (analysis.error) {
      title.textContent = symbol.replace('.NS', '');
      analysisDiv.innerHTML = `<div class="text-muted">${analysis.error}</div>`;
      return;
    }

    title.textContent = `${symbol.replace('.NS', '')} — ₹${analysis.price}`;

    const recClass = analysis.recommendation.includes('BUY') ? 'buy' :
      analysis.recommendation.includes('SELL') ? 'sell' : 'hold';

    analysisDiv.innerHTML = `
      <div class="rec-badge ${recClass}">${analysis.recommendation} (${analysis.confidence})</div>
      <span class="tier-badge ${analysis.tier}" style="margin-left:8px;">${analysis.tier} RECO</span>

      <div class="analysis-grid mt-16">
        <div class="analysis-item">
          <span class="analysis-label">Price</span>
          <span class="analysis-value">₹${analysis.price}</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">Day Change</span>
          <span class="analysis-value ${analysis.day_change_pct >= 0 ? 'text-green' : 'text-red'}">${analysis.day_change_pct >= 0 ? '+' : ''}${analysis.day_change_pct}%</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">MTF Score</span>
          <span class="analysis-value" style="color:var(--cyan);">${analysis.mtf_score}</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">Entry Quality</span>
          <span class="analysis-value">${analysis.entry_quality}/100</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">RSI</span>
          <span class="analysis-value">${analysis.rsi}</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">ADX</span>
          <span class="analysis-value">${analysis.adx}</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">RVOL</span>
          <span class="analysis-value">${analysis.rvol}x</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">CMF</span>
          <span class="analysis-value">${analysis.cmf}</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">Supertrend</span>
          <span class="analysis-value ${analysis.supertrend === 'Bullish' ? 'text-green' : 'text-red'}">${analysis.supertrend}</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">Divergence</span>
          <span class="analysis-value">${analysis.divergence || 'None'}</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">Stop Loss</span>
          <span class="analysis-value text-red">₹${analysis.stop_loss}</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">Regime</span>
          <span class="analysis-value">${analysis.regime}</span>
        </div>
        <div class="analysis-item" style="grid-column: 1 / -1; background: rgba(63, 185, 80, 0.1); padding: 8px;">
          <span class="analysis-label" style="display: inline-block; width: 120px;">Breakout Status</span>
          <span class="analysis-value ${analysis.breakout ? 'text-green' : 'text-muted'}">
            ${analysis.breakout 
              ? `🚀 ACTIVE (Level: ₹${analysis.breakout_level.toFixed(2)}, +${analysis.pct_above_breakout.toFixed(1)}%) — SL tightened to ₹${analysis.stop_loss.toFixed(2)}` 
              : `No (20-day high: ₹${analysis.breakout_level.toFixed(2)})`}
          </span>
        </div>
      </div>

      <div style="margin-top:16px;display:flex;gap:8px;">
        <button class="btn-success" onclick="quickTrack('${symbol}', ${analysis.price})">🎯 Track</button>
        <button class="btn-primary" onclick="showAddToPortfolioModalPrefilled('${symbol}', ${analysis.price})">💼 Add to Portfolio</button>
      </div>
    `;
  } catch (e) {
    analysisDiv.innerHTML = `<div class="text-red">Analysis error: ${e.message}</div>`;
  }
}

function closeDrawer() {
  document.getElementById('stock-drawer').classList.add('hidden');
  // Clean up chart
  if (chartInstance) {
    chartInstance.remove();
    chartInstance = null;
  }
}

function showAddToPortfolioModalPrefilled(symbol, price) {
  showModal('Add to Portfolio', `
    <div class="form-group">
      <label>Symbol</label>
      <input id="modal-symbol" type="text" value="${symbol}" readonly style="opacity:0.7;">
    </div>
    <div class="form-group">
      <label>Quantity</label>
      <input id="modal-qty" type="number" min="1" value="1" autofocus>
    </div>
    <div class="form-group">
      <label>Buy Price (₹)</label>
      <input id="modal-price" type="number" step="0.01" value="${price.toFixed(2)}">
    </div>
    <div class="modal-actions">
      <button class="btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn-primary" onclick="addToPortfolio()">Add to Portfolio</button>
    </div>
  `);
}

// ---------------------------------------------------------------------------
// CHART RENDERING (Lightweight Charts)
// ---------------------------------------------------------------------------
function renderChart(container, data) {
  container.innerHTML = '';

  if (chartInstance) {
    chartInstance.remove();
    chartInstance = null;
  }

  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth - 24,
    height: container.clientHeight - 24,
    layout: {
      background: { color: '#161b22' },
      textColor: '#8b949e',
      fontSize: 11,
    },
    grid: {
      vertLines: { color: 'rgba(48, 54, 61, 0.4)' },
      horzLines: { color: 'rgba(48, 54, 61, 0.4)' },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#30363d' },
    timeScale: {
      borderColor: '#30363d',
      timeVisible: false,
    },
  });

  chartInstance = chart;

  // Candlestick
  candleSeries = chart.addCandlestickSeries({
    upColor: '#3fb950',
    downColor: '#f85149',
    borderDownColor: '#f85149',
    borderUpColor: '#3fb950',
    wickDownColor: '#f85149',
    wickUpColor: '#3fb950',
  });
  candleSeries.setData(data.candles);

  // Volume
  volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  });
  chart.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.85, bottom: 0 },
  });
  volumeSeries.setData(data.volumes);

  // SMA 20 baseline
  if (data.sma20 && data.sma20.length > 0) {
    sma20Series = chart.addLineSeries({
      color: '#26c6da',
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Solid,
      title: 'SMA 20',
    });
    sma20Series.setData(data.sma20);
  }

  // SMA 50 baseline
  if (data.sma50 && data.sma50.length > 0) {
    sma50Series = chart.addLineSeries({
      color: '#a78bfa',
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      title: 'SMA 50',
    });
    sma50Series.setData(data.sma50);
  }

  // Stop Loss line
  if (data.stop_loss) {
    candleSeries.createPriceLine({
      price: data.stop_loss,
      color: '#f85149',
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dotted,
      axisLabelVisible: true,
      title: 'SL',
    });
  }

  // Entry price line
  if (data.entry_price) {
    candleSeries.createPriceLine({
      price: data.entry_price,
      color: '#d29922',
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'Entry',
    });
  }

  chart.timeScale().fitContent();

  // Resize observer
  const resizeObserver = new ResizeObserver(() => {
    chart.applyOptions({
      width: container.clientWidth - 24,
      height: container.clientHeight - 24,
    });
  });
  resizeObserver.observe(container);
}

// ---------------------------------------------------------------------------
// SEARCH
// ---------------------------------------------------------------------------
function setupSearch() {
  const input = document.getElementById('symbol-search');
  const dropdown = document.getElementById('search-results');
  let debounceTimer;

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (q.length < 2) {
      dropdown.classList.add('hidden');
      return;
    }
    debounceTimer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        if (data.results.length === 0) {
          dropdown.classList.add('hidden');
          return;
        }
        dropdown.innerHTML = data.results.map(sym =>
          `<div class="search-item" onclick="selectSearchResult('${sym}')">${sym}</div>`
        ).join('');
        dropdown.classList.remove('hidden');
      } catch (e) {
        dropdown.classList.add('hidden');
      }
    }, 300);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const q = input.value.trim().toUpperCase();
      if (q) {
        openStockDrawer(q);
        dropdown.classList.add('hidden');
        input.value = '';
      }
    }
    if (e.key === 'Escape') {
      dropdown.classList.add('hidden');
    }
  });

  // Close dropdown on outside click
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-container')) {
      dropdown.classList.add('hidden');
    }
  });
}

function selectSearchResult(symbol) {
  document.getElementById('search-results').classList.add('hidden');
  document.getElementById('symbol-search').value = '';
  openStockDrawer(symbol);
}

// ---------------------------------------------------------------------------
// MODAL
// ---------------------------------------------------------------------------
function showModal(title, bodyHtml) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHtml;
  document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
}

// ---------------------------------------------------------------------------
// UTILS
// ---------------------------------------------------------------------------
function formatNum(n) {
  if (n === undefined || n === null) return '0';
  if (Math.abs(n) >= 10000000) return (n / 10000000).toFixed(2) + ' Cr';
  if (Math.abs(n) >= 100000) return (n / 100000).toFixed(2) + ' L';
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}
