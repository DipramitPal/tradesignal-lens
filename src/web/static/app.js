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
    case 'advisor': loadAdvisor(); break;
    case 'backtest': loadBacktest(); break;
    case 'signals': loadSwingSignals(); break;
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
        <td class="sym-cell">${item.symbol.replace('.NS', '')}${item.breakout ? ' <span title="Breakout Active" style="font-size:14px">🚀</span>' : ''}</td>
        <td><span class="tier-badge ${item.tier}">${item.tier}</span></td>
        <td>₹${item.price.toFixed(2)}</td>
        <td class="${item.day_change_pct >= 0 ? 'pnl-positive' : 'pnl-negative'}">${item.day_change_pct >= 0 ? '+' : ''}${item.day_change_pct}%</td>
        <td style="font-weight:600;color:var(--cyan);">${(item.swing_rank || 0).toFixed(1)} <span class="text-muted">${item.swing_rank_bucket || ''}</span></td>
        <td>${item.swing_setup || 'NO_SETUP'}</td>
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
              <th>Swing Rank</th><th>Setup</th><th>MTF Score</th><th>Quality</th><th>RSI</th><th>RVOL</th>
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

    // Filter positive swing candidates and sort by swing rank.
    items = items
      .filter(i => (i.swing_rank || 0) > 0)
      .map(i => ({ ...i, momentum: i.swing_rank || 0 }))
      .sort((a, b) => b.momentum - a.momentum)
      .slice(0, 15);

    if (items.length === 0) {
      container.innerHTML = '<div class="text-muted" style="padding:40px 0;">No momentum stocks found.</div>';
      return;
    }

    const rows = items.map((item, idx) => `
      <tr onclick="openStockDrawer('${item.symbol}')">
        <td style="color:var(--text-muted);font-weight:600;">#${idx + 1}</td>
        <td class="sym-cell">${item.symbol.replace('.NS', '')}${item.breakout ? ' <span title="Breakout Active" style="font-size:14px">🚀</span>' : ''}</td>
        <td>₹${item.price.toFixed(2)}</td>
        <td class="${item.day_change_pct >= 0 ? 'pnl-positive' : 'pnl-negative'}">${item.day_change_pct >= 0 ? '+' : ''}${item.day_change_pct}%</td>
        <td style="font-weight:600;color:var(--cyan);">${item.momentum.toFixed(1)} <span class="text-muted">${item.swing_rank_bucket || ''}</span></td>
        <td>${item.swing_setup || 'NO_SETUP'}</td>
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
              <th>Swing Rank</th><th>Setup</th><th>MTF</th><th>RVOL</th><th>Quality</th>
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
// ADVISOR
// ---------------------------------------------------------------------------
let _advisorData = null;
let _weeklyData = null;
let _advisorSection = 'all';

async function loadAdvisor() {
  const container = document.getElementById('advisor-content');
  container.innerHTML = '<div class="loader-inline"><div class="spinner"></div> Loading advisor (fetching live data)...</div>';

  try {
    const [advRes, weeklyRes] = await Promise.all([
      fetch('/api/portfolio/advisor'),
      fetch('/api/portfolio/weekly-report'),
    ]);
    _advisorData = await advRes.json();
    _weeklyData = await weeklyRes.json();
    renderAdvisor(_advisorSection);
  } catch (e) {
    container.innerHTML = `<div class="text-red">Error loading advisor: ${e.message}</div>`;
  }
}

function filterAdvisor(section) {
  _advisorSection = section;
  document.querySelectorAll('.advisor-filter').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.section === section);
  });
  renderAdvisor(section);
}

function renderAdvisor(section) {
  const container = document.getElementById('advisor-content');
  if (!_advisorData && !_weeklyData) {
    container.innerHTML = '<div class="text-muted" style="padding:40px 0;">No advisor data available.</div>';
    return;
  }

  let html = '';

  if (section === 'all' || section === 'weekly') {
    html += renderWeeklySection();
  }
  if (section === 'all' || section === 'tsl') {
    html += renderTSLSection();
  }
  if (section === 'all' || section === 'average') {
    html += renderAveragingSection();
  }
  if (section === 'all' || section === 'harvest') {
    html += renderHarvestSection();
  }

  container.innerHTML = html;
}

function renderWeeklySection() {
  if (!_weeklyData || _weeklyData.error) return '';
  const p = _weeklyData.portfolio;
  const pnlClass = p.week_change_pct >= 0 ? 'pnl-positive' : 'pnl-negative';
  const totalPnlClass = p.total_pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative';

  const gainersHtml = (_weeklyData.top_gainers || []).map(s =>
    `<tr><td class="sym-cell">${s.name}</td><td class="pnl-positive">+${s.week_change_pct}%</td><td>Rs.${s.current_price}</td></tr>`
  ).join('');

  const losersHtml = (_weeklyData.top_losers || []).map(s =>
    `<tr><td class="sym-cell">${s.name}</td><td class="pnl-negative">${s.week_change_pct}%</td><td>Rs.${s.current_price}</td></tr>`
  ).join('');

  const sectorHtml = (_weeklyData.sector_performance || []).map(s => {
    const cls = s.week_change_pct >= 0 ? 'pnl-positive' : 'pnl-negative';
    const sign = s.week_change_pct >= 0 ? '+' : '';
    return `<tr><td>${s.sector}</td><td class="${cls}">${sign}${s.week_change_pct}%</td><td>Rs.${formatNum(s.current_value)}</td></tr>`;
  }).join('');

  const decisionsHtml = (_weeklyData.key_decisions || []).map(d => {
    const colors = { WARNING: 'var(--red)', HARVEST: 'var(--amber)', PROFIT: 'var(--green)', TARGET: 'var(--cyan)', CONCENTRATION: 'var(--purple)' };
    return `<div style="border-left:3px solid ${colors[d.type] || 'var(--border)'}; padding:8px 12px; margin-bottom:8px; background:var(--bg-card); border-radius:0 var(--radius-xs) var(--radius-xs) 0;">
      <span style="font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:${colors[d.type] || 'var(--text-muted)'}">${d.type}</span>
      <div style="font-size:13px; color:var(--text-secondary); margin-top:2px;">${d.advice}</div>
    </div>`;
  }).join('');

  return `
    <div style="margin-bottom:24px;">
      <h3 style="font-size:16px; font-weight:700; margin-bottom:12px; color:var(--cyan);">Weekly Portfolio Report</h3>
      <div class="summary-grid" style="margin-bottom:16px;">
        <div class="card">
          <div class="card-title">Week Change</div>
          <div class="card-value ${pnlClass}" style="font-size:22px;">${p.week_change_pct >= 0 ? '+' : ''}${p.week_change_pct.toFixed(2)}%</div>
          <div class="card-sub ${pnlClass}">Rs.${p.week_change_pct >= 0 ? '+' : ''}${formatNum(Math.abs(p.week_pnl_abs))}</div>
        </div>
        <div class="card">
          <div class="card-title">Total P&L</div>
          <div class="card-value ${totalPnlClass}" style="font-size:22px;">${p.total_pnl_pct >= 0 ? '+' : ''}${p.total_pnl_pct.toFixed(2)}%</div>
          <div class="card-sub ${totalPnlClass}">Rs.${p.total_pnl >= 0 ? '+' : ''}${formatNum(Math.abs(p.total_pnl))}</div>
        </div>
        <div class="card">
          <div class="card-title">Current Value</div>
          <div class="card-value" style="font-size:22px;">Rs.${formatNum(p.total_current)}</div>
          <div class="card-sub">${p.holdings_count} holdings</div>
        </div>
      </div>

      <div class="summary-grid">
        <div class="card">
          <div class="card-title">Top Weekly Gainers</div>
          <table class="data-table" style="margin-top:8px;"><tbody>${gainersHtml}</tbody></table>
        </div>
        <div class="card">
          <div class="card-title">Top Weekly Losers</div>
          <table class="data-table" style="margin-top:8px;"><tbody>${losersHtml}</tbody></table>
        </div>
        <div class="card">
          <div class="card-title">Sector Performance</div>
          <table class="data-table" style="margin-top:8px;"><tbody>${sectorHtml}</tbody></table>
        </div>
      </div>

      ${decisionsHtml ? `<div style="margin-top:16px;"><div class="card-title" style="margin-bottom:8px;">Key Decisions</div>${decisionsHtml}</div>` : ''}
    </div>
  `;
}

function renderTSLSection() {
  if (!_advisorData || !_advisorData.tsl_advice) return '';
  const items = _advisorData.tsl_advice;
  if (items.length === 0) return '<div class="card" style="margin-top:16px;"><div class="card-title">TSL Assistant</div><div class="text-muted">No holdings to analyze.</div></div>';

  const actionColors = { 'EXIT NOW': 'var(--red)', 'MOVE SL': 'var(--amber)', 'TRAIL SL': 'var(--green)', 'HOLD SL': 'var(--text-muted)', 'REVIEW': 'var(--purple)' };

  const rows = items.map(r => {
    const color = actionColors[r.action] || 'var(--text-muted)';
    const pnlCls = r.pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative';
    return `<tr>
      <td class="sym-cell" onclick="openStockDrawer('${r.symbol}')" style="cursor:pointer;">${r.symbol.replace('.NS', '')}</td>
      <td>Rs.${r.current_price}</td>
      <td>Rs.${r.avg_price}</td>
      <td class="${pnlCls}">${r.pnl_pct >= 0 ? '+' : ''}${r.pnl_pct}%</td>
      <td>Rs.${r.recommended_sl}</td>
      <td><span style="font-size:11px; font-weight:700; color:${color}">${r.sl_phase}</span></td>
      <td><span style="padding:3px 8px; border-radius:999px; font-size:11px; font-weight:700; background:${color}20; color:${color}; border:1px solid ${color}40;">${r.action}</span></td>
    </tr>`;
  }).join('');

  return `
    <div style="margin-bottom:24px;">
      <h3 style="font-size:16px; font-weight:700; margin-bottom:12px; color:var(--cyan);">Trailing Stop-Loss Assistant</h3>
      <div class="card" style="overflow-x:auto;">
        <table class="data-table">
          <thead><tr><th>Symbol</th><th>Price</th><th>Entry</th><th>P&L</th><th>Rec. SL</th><th>Phase</th><th>Action</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  `;
}

function renderAveragingSection() {
  if (!_advisorData || !_advisorData.averaging_recommendations) return '';
  const items = _advisorData.averaging_recommendations;
  if (items.length === 0) return '<div class="card" style="margin-top:16px;"><div class="card-title">Smart Averaging</div><div class="text-muted" style="padding:8px 0;">All holdings are above average cost.</div></div>';

  const cards = items.map(r => {
    const borderColor = r.safe_to_average ? 'var(--green)' : r.blocked ? 'var(--red)' : 'var(--amber)';
    let actionHtml = '';
    if (r.blocked) {
      actionHtml = (r.block_reasons || []).map(br => `<div style="color:var(--red); font-size:12px; margin-top:4px;">[X] ${br}</div>`).join('');
    } else if (r.action && r.action.includes('BUY')) {
      actionHtml = `<div style="color:var(--green); font-size:13px; font-weight:600; margin-top:6px;">${r.action}</div>
        <div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">Investment: Rs.${formatNum(r.recommended_investment)} | New Avg: Rs.${r.new_avg_price}</div>`;
      if (r.reasons) actionHtml += r.reasons.map(x => `<div style="font-size:11px; color:var(--text-muted); margin-top:2px;">* ${x}</div>`).join('');
    } else {
      actionHtml = `<div style="font-size:13px; color:var(--amber); margin-top:4px;">${r.action}</div>`;
      if (r.reasons) actionHtml += r.reasons.map(x => `<div style="font-size:11px; color:var(--text-muted); margin-top:2px;">* ${x}</div>`).join('');
    }
    if (r.warnings && r.warnings.length > 0) {
      actionHtml = r.warnings.map(w => `<div style="color:var(--red); font-size:12px; margin-top:4px; font-weight:600;">${w}</div>`).join('') + actionHtml;
    }

    return `<div class="card" style="border-left:3px solid ${borderColor}; margin-bottom:10px;">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
          <span class="sym-cell" style="cursor:pointer;" onclick="openStockDrawer('${r.symbol}')">${r.symbol.replace('.NS', '')}</span>
          <span class="sector-badge" style="margin-left:8px;">${r.sector}</span>
        </div>
        <span class="pnl-negative" style="font-size:14px;">${r.loss_pct}%</span>
      </div>
      <div style="font-size:12px; color:var(--text-secondary); margin-top:4px;">Price: Rs.${r.current_price} | Avg: Rs.${r.avg_price}</div>
      ${actionHtml}
    </div>`;
  }).join('');

  return `
    <div style="margin-bottom:24px;">
      <h3 style="font-size:16px; font-weight:700; margin-bottom:12px; color:var(--cyan);">Smart Averaging Down</h3>
      ${cards}
    </div>
  `;
}

function renderHarvestSection() {
  if (!_advisorData || !_advisorData.tax_harvest) return '';
  const data = _advisorData.tax_harvest;
  const candidates = data.candidates || [];

  if (candidates.length === 0) {
    return '<div class="card" style="margin-top:16px;"><div class="card-title">Tax-Loss Harvesting</div><div class="text-muted" style="padding:8px 0;">No significant unrealized losses to harvest.</div></div>';
  }

  const priorityColors = { HIGH: 'var(--red)', MEDIUM: 'var(--amber)', LOW: 'var(--text-muted)' };

  const rows = candidates.map(r => {
    const pColor = priorityColors[r.priority] || 'var(--text-muted)';
    return `<tr>
      <td class="sym-cell" onclick="openStockDrawer('${r.symbol}')" style="cursor:pointer;">${r.symbol.replace('.NS', '')}</td>
      <td><span class="sector-badge">${r.sector}</span></td>
      <td class="pnl-negative">${r.loss_pct}%</td>
      <td class="pnl-negative">Rs.${formatNum(r.unrealized_loss)}</td>
      <td><span style="color:${pColor}; font-weight:700; font-size:11px;">${r.priority}</span></td>
      <td style="font-size:12px; color:var(--text-secondary); max-width:300px; white-space:normal;">${r.advice}</td>
    </tr>`;
  }).join('');

  return `
    <div style="margin-bottom:24px;">
      <h3 style="font-size:16px; font-weight:700; margin-bottom:12px; color:var(--cyan);">Tax-Loss Harvesting</h3>
      <div class="summary-grid" style="margin-bottom:12px;">
        <div class="card">
          <div class="card-title">Total Harvestable Loss</div>
          <div class="card-value pnl-negative" style="font-size:22px;">Rs.${formatNum(data.total_harvestable_loss)}</div>
          <div class="card-sub">${data.candidate_count} candidates</div>
        </div>
        <div class="card">
          <div class="card-title">FY-End Status</div>
          <div class="card-value" style="font-size:22px; color:${data.near_fy_end ? 'var(--red)' : 'var(--green)'}">${data.near_fy_end ? 'NEAR' : 'Not near'}</div>
          <div class="card-sub">${data.days_to_fy_end} days to FY end</div>
        </div>
      </div>
      <div class="card" style="overflow-x:auto;">
        <table class="data-table">
          <thead><tr><th>Symbol</th><th>Sector</th><th>Loss %</th><th>Loss Rs.</th><th>Priority</th><th>Advice</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// BACKTEST
// ---------------------------------------------------------------------------
let _backtestChart = null;

function loadBacktest() {
  // Just show config form — no auto-run
}

async function runBacktest() {
  const resultsDiv = document.getElementById('backtest-results');
  const btn = document.getElementById('btn-run-backtest');
  btn.disabled = true;
  btn.textContent = '⏳ Running backtest...';
  resultsDiv.innerHTML = '<div class="loader-inline"><div class="spinner"></div> Running swing backtest (this may take 1-3 minutes)...</div>';

  try {
    const body = {
      start_date: document.getElementById('bt-start').value,
      end_date: document.getElementById('bt-end').value,
      initial_capital: parseFloat(document.getElementById('bt-capital').value),
      max_positions: parseInt(document.getElementById('bt-positions').value),
      rebalance_freq: document.getElementById('bt-rebalance').value,
      min_swing_rank: parseFloat(document.getElementById('bt-min-rank').value),
    };

    const res = await fetch('/api/backtest/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();

    if (data.error) {
      resultsDiv.innerHTML = `<div class="text-red" style="padding:20px;">Error: ${data.error}</div>`;
      return;
    }

    renderBacktestResults(data, resultsDiv);
  } catch (e) {
    resultsDiv.innerHTML = `<div class="text-red">Error: ${e.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '🚀 Run Backtest';
  }
}

function renderBacktestResults(data, container) {
  const r = data.report || {};
  const s = r.summary || {};
  const ra = r.risk_adjusted || {};
  const tq = r.trade_quality || {};
  const ex = r.exposure || {};
  const dd = r.drawdown || {};
  const mr = r.monthly_returns || {};
  const cfg = data.config || {};

  const retClass = s.total_return_pct >= 0 ? 'pnl-positive' : 'pnl-negative';
  const retSign = s.total_return_pct >= 0 ? '+' : '';

  // Monthly heatmap
  const monthTable = (mr.table || []);
  const years = [...new Set(monthTable.map(m => m.year))].sort();
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  let heatmapHtml = '';
  if (years.length > 0) {
    heatmapHtml = '<table class="data-table" style="margin-top:8px;font-size:12px;"><thead><tr><th>Year</th>';
    months.forEach(m => heatmapHtml += `<th>${m}</th>`);
    heatmapHtml += '</tr></thead><tbody>';
    years.forEach(yr => {
      heatmapHtml += `<tr><td style="font-weight:600;">${yr}</td>`;
      for (let mi = 1; mi <= 12; mi++) {
        const entry = monthTable.find(m => m.year === yr && m.month === mi);
        if (entry) {
          const cls = entry.return_pct >= 0 ? 'pnl-positive' : 'pnl-negative';
          heatmapHtml += `<td class="${cls}">${entry.return_pct >= 0 ? '+' : ''}${entry.return_pct.toFixed(1)}%</td>`;
        } else {
          heatmapHtml += '<td class="text-muted">—</td>';
        }
      }
      heatmapHtml += '</tr>';
    });
    heatmapHtml += '</tbody></table>';
  }

  // By setup breakdown
  const bySetup = r.by_setup || {};
  let setupRows = '';
  Object.entries(bySetup).sort((a, b) => b[1].total_pnl - a[1].total_pnl).forEach(([setup, st]) => {
    setupRows += `<tr>
      <td style="font-weight:600;">${setup}</td>
      <td>${st.count}</td>
      <td>${st.win_rate_pct.toFixed(1)}%</td>
      <td class="${st.avg_pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}">₹${formatNum(st.avg_pnl)}</td>
      <td class="${st.total_pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}">₹${formatNum(st.total_pnl)}</td>
      <td>${st.avg_r.toFixed(2)}R</td>
    </tr>`;
  });

  // By exit reason
  const byExit = r.by_exit_reason || {};
  let exitRows = '';
  Object.entries(byExit).sort((a, b) => b[1].count - a[1].count).forEach(([reason, st]) => {
    exitRows += `<tr>
      <td style="font-weight:600;">${reason}</td>
      <td>${st.count}</td>
      <td>${st.win_rate_pct.toFixed(1)}%</td>
      <td class="${st.avg_pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}">₹${formatNum(st.avg_pnl)}</td>
      <td>${st.avg_hold.toFixed(0)}d</td>
    </tr>`;
  });

  // Recent trades
  const trades = data.recent_trades || [];
  let tradeRows = trades.map(t => {
    const cls = t.action === 'SELL' ? (t.pnl >= 0 ? 'pnl-positive' : 'pnl-negative') : '';
    return `<tr>
      <td>${t.date}</td>
      <td style="font-weight:600;">${t.symbol}</td>
      <td><span class="tier-badge ${t.action === 'BUY' ? 'HIGH' : 'LOW'}">${t.action}</span></td>
      <td>₹${t.price.toFixed(2)}</td>
      <td>${t.reason}</td>
      <td class="${cls}">${t.action === 'SELL' ? (t.pnl >= 0 ? '+' : '') + '₹' + formatNum(Math.abs(t.pnl)) : '—'}</td>
    </tr>`;
  }).join('');

  container.innerHTML = `
    <!-- Key Metrics -->
    <div class="summary-grid" style="margin-bottom:16px;">
      <div class="card">
        <div class="card-title">Total Return</div>
        <div class="card-value ${retClass}" style="font-size:22px;">${retSign}${s.total_return_pct}%</div>
        <div class="card-sub">CAGR: ${s.cagr_pct}%</div>
      </div>
      <div class="card">
        <div class="card-title">Final Value</div>
        <div class="card-value" style="font-size:22px;">₹${formatNum(s.final_value)}</div>
        <div class="card-sub">Start: ₹${formatNum(s.initial_capital)}</div>
      </div>
      <div class="card">
        <div class="card-title">Max Drawdown</div>
        <div class="card-value pnl-negative" style="font-size:22px;">${s.max_drawdown_pct}%</div>
        <div class="card-sub">${dd.max_dd_duration_days || 0} days</div>
      </div>
      <div class="card">
        <div class="card-title">Sharpe / Sortino</div>
        <div class="card-value" style="font-size:22px;color:var(--cyan);">${ra.sharpe} / ${ra.sortino}</div>
        <div class="card-sub">Calmar: ${ra.calmar}</div>
      </div>
    </div>

    <!-- Trade Quality -->
    <div class="summary-grid" style="margin-bottom:16px;">
      <div class="card">
        <div class="card-title">Trades</div>
        <div class="card-value" style="font-size:20px;">${tq.total_trades}</div>
        <div class="card-sub">Win Rate: ${tq.win_rate_pct}%</div>
      </div>
      <div class="card">
        <div class="card-title">Profit Factor</div>
        <div class="card-value" style="font-size:20px;color:var(--cyan);">${tq.profit_factor}</div>
        <div class="card-sub">Expectancy: ₹${formatNum(tq.expectancy)}</div>
      </div>
      <div class="card">
        <div class="card-title">Avg R-Multiple</div>
        <div class="card-value" style="font-size:20px;">${tq.avg_r_multiple}R</div>
        <div class="card-sub">Median: ${tq.median_r_multiple}R</div>
      </div>
      <div class="card">
        <div class="card-title">Exposure</div>
        <div class="card-value" style="font-size:20px;">${ex.time_in_market_pct}%</div>
        <div class="card-sub">Avg ${ex.avg_positions_held} positions</div>
      </div>
    </div>

    <!-- Equity Curve -->
    <div class="card" style="margin-bottom:16px;">
      <div class="card-title">Equity Curve</div>
      <div id="bt-equity-chart" style="height:300px;margin-top:8px;"></div>
    </div>

    <!-- Monthly Heatmap -->
    ${heatmapHtml ? `<div class="card" style="margin-bottom:16px;overflow-x:auto;">
      <div class="card-title">Monthly Returns</div>
      <div style="display:flex;gap:16px;margin-top:4px;font-size:12px;">
        <span>Best: <span class="pnl-positive">${mr.best_month >= 0 ? '+' : ''}${mr.best_month}%</span></span>
        <span>Worst: <span class="pnl-negative">${mr.worst_month}%</span></span>
        <span>+ve: ${mr.positive_months} | -ve: ${mr.negative_months}</span>
      </div>
      ${heatmapHtml}
    </div>` : ''}

    <!-- By Setup -->
    ${setupRows ? `<div class="card" style="margin-bottom:16px;overflow-x:auto;">
      <div class="card-title">Performance by Setup Type</div>
      <table class="data-table" style="margin-top:8px;">
        <thead><tr><th>Setup</th><th>Trades</th><th>Win%</th><th>Avg PnL</th><th>Total PnL</th><th>Avg R</th></tr></thead>
        <tbody>${setupRows}</tbody>
      </table>
    </div>` : ''}

    <!-- By Exit Reason -->
    ${exitRows ? `<div class="card" style="margin-bottom:16px;overflow-x:auto;">
      <div class="card-title">Performance by Exit Reason</div>
      <table class="data-table" style="margin-top:8px;">
        <thead><tr><th>Reason</th><th>Trades</th><th>Win%</th><th>Avg PnL</th><th>Avg Hold</th></tr></thead>
        <tbody>${exitRows}</tbody>
      </table>
    </div>` : ''}

    <!-- Recent Trades -->
    ${tradeRows ? `<div class="card" style="overflow-x:auto;">
      <div class="card-title">Recent Trades (last 30)</div>
      <table class="data-table" style="margin-top:8px;">
        <thead><tr><th>Date</th><th>Symbol</th><th>Action</th><th>Price</th><th>Reason</th><th>PnL</th></tr></thead>
        <tbody>${tradeRows}</tbody>
      </table>
    </div>` : ''}
  `;

  // Render equity curve with lightweight-charts
  const eq = data.equity_curve || [];
  if (eq.length > 0 && typeof LightweightCharts !== 'undefined') {
    const chartEl = document.getElementById('bt-equity-chart');
    if (_backtestChart) { _backtestChart.remove(); _backtestChart = null; }
    _backtestChart = LightweightCharts.createChart(chartEl, {
      layout: { background: { color: '#0d1117' }, textColor: '#8b949e' },
      grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
      width: chartEl.clientWidth,
      height: 300,
      rightPriceScale: { borderColor: '#30363d' },
      timeScale: { borderColor: '#30363d' },
    });
    const series = _backtestChart.addAreaSeries({
      topColor: 'rgba(38,198,218,0.4)',
      bottomColor: 'rgba(38,198,218,0.04)',
      lineColor: '#26c6da',
      lineWidth: 2,
    });
    series.setData(eq);
    _backtestChart.timeScale().fitContent();
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
          <span class="analysis-label">Swing Rank</span>
          <span class="analysis-value" style="color:var(--cyan);">${analysis.swing_rank || 0}/100 ${analysis.swing_rank_bucket || ''}</span>
        </div>
        <div class="analysis-item">
          <span class="analysis-label">Swing Setup</span>
          <span class="analysis-value">${analysis.swing_setup || 'NO_SETUP'} (${analysis.swing_setup_quality || 0}/100)</span>
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

      <div style="margin-top:24px; padding: 12px; background: rgba(13, 17, 23, 0.5); border-radius: 6px; border: 1px solid var(--border-color);">
        <h4 style="color:var(--text-primary); margin-top: 0; margin-bottom: 8px;">Latest News & Sentiment</h4>
        <div style="margin-bottom: 12px; font-size: 13px;"><strong>Overall Sentiment:</strong> 
          <span class="tier-badge ${analysis.news_sentiment === 'Positive' ? 'HIGH' : analysis.news_sentiment === 'Negative' ? 'LOW' : 'MEDIUM'}" style="padding: 2px 6px;">${analysis.news_sentiment || 'Neutral'}</span>
        </div>
        ${analysis.recent_news && analysis.recent_news.length > 0
        ? analysis.recent_news.map(n => `
            <div style="margin-bottom: 10px; font-size: 13px; line-height: 1.4; border-left: 2px solid var(--border-color); padding-left: 8px;">
              <a href="${n.url}" target="_blank" style="color:var(--cyan); text-decoration:none; display: block; margin-bottom: 2px;">${n.title}</a>
              <span class="text-muted" style="font-size: 11px;">${n.source}</span> • 
              <span style="font-size: 11px; color: ${n.sentiment === 'Positive' ? 'var(--green)' : n.sentiment === 'Negative' ? 'var(--red)' : 'var(--text-muted)'}">${n.sentiment}</span>
            </div>
          `).join('')
        : '<div class="text-muted" style="font-size: 12px;">No recent news found.</div>'
      }
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

// ---------------------------------------------------------------------------
// SWING SIGNALS TAB
// ---------------------------------------------------------------------------
let _swingSignalData = null;

async function loadSwingSignals() {
  const container = document.getElementById('signals-content');
  container.innerHTML = '<div class="loader-inline"><div class="spinner"></div> Loading swing signals report...</div>';

  try {
    const res = await fetch('/api/swing-signals');
    const data = await res.json();

    if (data.empty || data.error) {
      container.innerHTML = `
        <div class="card" style="text-align:center; padding:40px 20px;">
          <div style="font-size:40px; margin-bottom:12px;">⚡</div>
          <div style="font-size:16px; color:var(--text-secondary); margin-bottom:16px;">No swing signal report found yet.</div>
          <div style="font-size:13px; color:var(--text-muted); margin-bottom:20px;">Click the button below to run the EOD scanner on your universe.</div>
          <button class="btn-primary" onclick="runSwingScan()">⚡ Run EOD Scan Now</button>
        </div>`;
      return;
    }

    _swingSignalData = data;
    renderSwingSignals(data);
  } catch (e) {
    container.innerHTML = `<div class="text-red">Error loading swing signals: ${e.message}</div>`;
  }
}

async function runSwingScan() {
  const container = document.getElementById('signals-content');
  const btn = document.getElementById('btn-run-scan');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Scanning...'; }
  container.innerHTML = '<div class="loader-inline"><div class="spinner"></div> Running EOD swing scan (this may take 30-60s)...</div>';

  try {
    const res = await fetch('/api/swing-signals/run', { method: 'POST' });
    const data = await res.json();

    if (data.error) {
      container.innerHTML = `<div class="text-red">Error: ${data.error}</div>`;
      return;
    }

    _swingSignalData = data;
    renderSwingSignals(data);
  } catch (e) {
    container.innerHTML = `<div class="text-red">Scan error: ${e.message}</div>`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '⚡ Run EOD Scan'; }
  }
}

function renderSwingSignals(data) {
  const container = document.getElementById('signals-content');
  const buySignals = data.buy_signals || [];
  const holdUpdates = data.hold_updates || [];
  const sellAlerts = data.sell_alerts || [];
  const regime = data.market_regime || 'UNKNOWN';
  const scanned = data.universe_scanned || 0;
  const passed = data.candidates_passed_filter || 0;
  const generatedAt = data.generated_at || '';
  const reportFile = data.report_file || '';

  // Summary cards
  let html = `
    <div class="flex gap-8 mb-8" style="gap:12px;flex-wrap:wrap;">
      <div class="card" style="min-width:140px;text-align:center;">
        <div class="card-title">Regime</div>
        <div style="font-size:16px;font-weight:700;color:var(--cyan);">${regime}</div>
      </div>
      <div class="card" style="min-width:140px;text-align:center;">
        <div class="card-title">🟢 BUY</div>
        <div style="font-size:20px;font-weight:700;color:var(--green);">${buySignals.length}</div>
      </div>
      <div class="card" style="min-width:140px;text-align:center;">
        <div class="card-title">🟡 HOLD</div>
        <div style="font-size:20px;font-weight:700;color:var(--amber);">${holdUpdates.length}</div>
      </div>
      <div class="card" style="min-width:140px;text-align:center;">
        <div class="card-title">🔴 SELL</div>
        <div style="font-size:20px;font-weight:700;color:var(--red);">${sellAlerts.length}</div>
      </div>
      <div class="card" style="min-width:140px;text-align:center;">
        <div class="card-title">Scanned</div>
        <div style="font-size:16px;font-weight:600;">${scanned} → ${passed} passed</div>
      </div>
    </div>`;

  // Meta info
  if (generatedAt) {
    html += `<div style="font-size:11px; color:var(--text-muted); margin-bottom:16px;">Report: ${generatedAt}${reportFile ? ' · ' + reportFile : ''}</div>`;
  }

  // ── SELL ALERTS ──────────────────────────
  if (sellAlerts.length > 0) {
    const sellRows = sellAlerts.map(s => {
      const pnlCls = s.pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative';
      const urgencyColor = s.urgency === 'IMMEDIATE' ? 'var(--red)' : 'var(--amber)';
      const reasonsHtml = (s.exit_reasons || []).slice(0, 3).map(r => `<div style="font-size:11px; color:var(--text-muted); padding-left:16px;">└─ ${r}</div>`).join('');
      return `<tr onclick="openStockDrawer('${s.symbol}')">
        <td class="sym-cell">${s.symbol.replace('.NS', '')}</td>
        <td>₹${s.price.toFixed(2)}</td>
        <td>₹${s.entry_price.toFixed(2)}</td>
        <td class="${pnlCls}">${s.pnl_pct >= 0 ? '+' : ''}${s.pnl_pct}%</td>
        <td><span style="padding:3px 8px;border-radius:999px;font-size:11px;font-weight:700;background:${urgencyColor}20;color:${urgencyColor};border:1px solid ${urgencyColor}40;">${s.urgency}</span></td>
        <td>${s.reason}</td>
        <td>${s.exit_score.toFixed(2)}</td>
      </tr><tr><td colspan="7" style="padding:0 0 8px 0;">${reasonsHtml}</td></tr>`;
    }).join('');

    html += `
      <div style="margin-bottom:24px;">
        <h3 style="font-size:16px; font-weight:700; margin-bottom:12px; color:var(--red);">🔴 SELL Alerts</h3>
        <div class="card" style="overflow-x:auto;">
          <table class="data-table">
            <thead><tr>
              <th>Symbol</th><th>Price</th><th>Entry</th><th>P&L</th><th>Urgency</th><th>Reason</th><th>Score</th>
            </tr></thead>
            <tbody>${sellRows}</tbody>
          </table>
        </div>
      </div>`;
  }

  // ── HOLD UPDATES ────────────────────────
  if (holdUpdates.length > 0) {
    const holdRows = holdUpdates.map(h => {
      const pnlCls = h.pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative';
      const phaseColors = { 'INITIAL': 'var(--text-muted)', 'BREAKEVEN': 'var(--amber)', 'TRAILING': 'var(--cyan)', 'LOCK': 'var(--green)' };
      const phaseColor = phaseColors[h.sl_phase] || 'var(--text-muted)';
      let alertHtml = '';
      if (h.alert === 'BOOK_T2') alertHtml = '<span style="color:var(--green);font-weight:700;font-size:11px;">⚡ BOOK T2</span>';
      else if (h.alert === 'BOOK_T1') alertHtml = '<span style="color:var(--cyan);font-weight:700;font-size:11px;">⚡ BOOK T1</span>';
      else if (h.alert === 'TIGHTEN_SL') alertHtml = '<span style="color:var(--amber);font-weight:700;font-size:11px;">⚡ SL MOVED</span>';

      return `<tr onclick="openStockDrawer('${h.symbol}')">
        <td class="sym-cell">${h.symbol.replace('.NS', '')}</td>
        <td>₹${h.price.toFixed(2)}</td>
        <td class="${pnlCls}">${h.pnl_pct >= 0 ? '+' : ''}${h.pnl_pct}%</td>
        <td class="${pnlCls}">${h.r_multiple >= 0 ? '+' : ''}${h.r_multiple.toFixed(1)}R</td>
        <td>₹${h.new_sl.toFixed(2)}</td>
        <td><span style="font-size:11px;font-weight:700;color:${phaseColor}">${h.sl_phase}</span></td>
        <td style="font-size:11px;">T1:₹${h.t1.toFixed(0)} ${h.t1_hit ? '✅' : ''} · T2:₹${h.t2.toFixed(0)} ${h.t2_hit ? '✅' : ''}</td>
        <td>${alertHtml}</td>
      </tr>`;
    }).join('');

    html += `
      <div style="margin-bottom:24px;">
        <h3 style="font-size:16px; font-weight:700; margin-bottom:12px; color:var(--amber);">🟡 HOLD Updates — Dynamic SL & Targets</h3>
        <div class="card" style="overflow-x:auto;">
          <table class="data-table">
            <thead><tr>
              <th>Symbol</th><th>Price</th><th>P&L</th><th>R-Multiple</th><th>Current SL</th><th>Phase</th><th>Targets</th><th>Alert</th>
            </tr></thead>
            <tbody>${holdRows}</tbody>
          </table>
        </div>
      </div>`;
  }

  // ── BUY SIGNALS ─────────────────────────
  if (buySignals.length > 0) {
    const buyRows = buySignals.map((b, idx) => {
      const reasonsHtml = (b.reasons || []).slice(0, 2).map(r => `<div style="font-size:11px; color:var(--text-muted); padding-left:16px;">· ${r}</div>`).join('');
      return `<tr onclick="openStockDrawer('${b.symbol}')">
        <td style="color:var(--text-muted);font-weight:600;">#${idx + 1}</td>
        <td class="sym-cell">${b.symbol.replace('.NS', '')}</td>
        <td style="font-weight:600;color:var(--cyan);">${b.rank_score.toFixed(1)} <span class="text-muted">${b.rank_bucket}</span></td>
        <td>${b.setup_type}</td>
        <td>₹${b.price.toFixed(2)}</td>
        <td>₹${b.entry_sl.toFixed(2)}</td>
        <td>₹${b.t1.toFixed(0)}</td>
        <td>₹${b.t2.toFixed(0)}</td>
        <td>${b.rr_ratio.toFixed(1)}x</td>
        <td>${b.suggested_shares}</td>
        <td><span class="sector-badge">${b.sector}</span></td>
        <td>
          <button class="btn-success" onclick="event.stopPropagation(); quickTrack('${b.symbol}', ${b.price})" title="Track">🎯</button>
        </td>
      </tr><tr><td colspan="12" style="padding:0 0 6px 0;">${reasonsHtml}</td></tr>`;
    }).join('');

    html += `
      <div style="margin-bottom:24px;">
        <h3 style="font-size:16px; font-weight:700; margin-bottom:12px; color:var(--green);">🟢 BUY Signals — Ranked by Swing Score</h3>
        <div class="card" style="overflow-x:auto;">
          <table class="data-table">
            <thead><tr>
              <th>#</th><th>Symbol</th><th>Rank</th><th>Setup</th><th>Price</th><th>SL</th><th>T1</th><th>T2</th><th>R:R</th><th>Shares</th><th>Sector</th><th>Track</th>
            </tr></thead>
            <tbody>${buyRows}</tbody>
          </table>
        </div>
      </div>`;
  } else if (sellAlerts.length === 0 && holdUpdates.length === 0) {
    html += `
      <div class="card" style="text-align:center; padding:30px 20px;">
        <div style="font-size:14px; color:var(--text-muted);">No signals generated — market conditions or rank filters not met.</div>
      </div>`;
  }

  // Sector summary
  const sectors = data.sector_summary || {};
  const sectorEntries = Object.entries(sectors);
  if (sectorEntries.length > 0) {
    const phaseColors = { 'LEADING': 'var(--green)', 'IMPROVING': 'var(--cyan)', 'WEAKENING': 'var(--amber)', 'LAGGING': 'var(--red)' };
    const sectorBadges = sectorEntries.map(([sec, phase]) => {
      const c = phaseColors[phase] || 'var(--text-muted)';
      return `<span style="display:inline-block;padding:4px 10px;margin:3px;border-radius:6px;font-size:11px;font-weight:600;background:${c}15;color:${c};border:1px solid ${c}30;">${sec}: ${phase}</span>`;
    }).join('');
    html += `
      <div class="card" style="margin-top:8px;">
        <div class="card-title" style="margin-bottom:8px;">Sector Phases</div>
        <div>${sectorBadges}</div>
      </div>`;
  }

  container.innerHTML = html;
}
