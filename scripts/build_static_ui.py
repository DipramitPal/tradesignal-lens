#!/usr/bin/env python3
"""
Static Site Generator for TradeSignal Lens Dashboard.
Runs the Flask application internally, captures the data as JSON,
and builds a fully static `public/` directory for GitHub Pages.
"""

import sys
import os
import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from web.app import create_app
from settings import SCAN_UNIVERSE, MONITOR_SYMBOLS

def build_static_site():
    app = create_app()
    client = app.test_client()
    
    public_dir = PROJECT_ROOT / "public"
    api_dir = public_dir / "api"
    static_dir = public_dir / "static"
    
    # Clean previous build
    if public_dir.exists():
        shutil.rmtree(public_dir)
        
    os.makedirs(api_dir, exist_ok=True)
    os.makedirs(static_dir, exist_ok=True)
    
    # 1. Generate Static API JSONs
    print("Generating standard API endpoints...")
    endpoints = [
        "/api/summary",
        "/api/portfolio",
        "/api/watchlist",
        "/api/tracking",
        "/api/market-status",
        "/api/cache-status"
    ]
    for ep in endpoints:
        resp = client.get(ep)
        filename = ep.split("/")[-1] + ".json"
        with open(api_dir / filename, "w", encoding="utf-8") as f:
            json.dump(resp.get_json(), f)
            
    # 2. Gather all active symbols to generate individual charts/analysis
    symbols = set()
    try:
        with open(api_dir / "watchlist.json", "r") as f:
            wlist = json.load(f)
            for item in wlist.get("items", []):
                symbols.add(item["symbol"])
    except Exception as e:
        print(f"Error loading watchlist: {e}")
    
    try:
        with open(api_dir / "portfolio.json", "r") as f:
            port = json.load(f)
            for item in port.get("holdings", []):
                symbols.add(item["symbol"])
    except Exception as e:
        print(f"Error loading portfolio: {e}")
    
    try:
        with open(api_dir / "tracking.json", "r") as f:
            track = json.load(f)
            for item in track.get("items", []):
                symbols.add(item["symbol"])
    except Exception as e:
        print(f"Error loading tracking: {e}")
        
    # Generate search dump
    all_sym = list(set(SCAN_UNIVERSE + MONITOR_SYMBOLS + list(symbols)))
    with open(api_dir / "search.json", "w", encoding="utf-8") as f:
        json.dump({"results": all_sym}, f)

    stock_dir = api_dir / "stock"
    os.makedirs(stock_dir, exist_ok=True)
    
    print(f"Generating charts & analysis for {len(symbols)} symbols...")
    for sym in symbols:
        # Chart
        resp = client.get(f"/api/stock/{sym}/chart")
        with open(stock_dir / f"{sym}_chart.json", "w", encoding="utf-8") as f:
            json.dump(resp.get_json(), f)
            
        # Analysis
        resp = client.get(f"/api/stock/{sym}/analysis")
        with open(stock_dir / f"{sym}_analysis.json", "w", encoding="utf-8") as f:
            json.dump(resp.get_json(), f)
            
    # 3. Copy & Patch Frontend Assets
    print("Copying static frontend assets...")
    
    # HTML
    html_src = PROJECT_ROOT / "src" / "web" / "templates" / "dashboard.html"
    with open(html_src, "r", encoding="utf-8") as f:
        html = f.read()
    
    # Convert Flask Template to strictly static references
    html = html.replace("{{ url_for('static', filename='style.css') }}", "static/style.css")
    html = html.replace("{{ url_for('static', filename='app.js') }}", "static/app.js")
    
    # Inject POST blocker + cache-busting for static JSON files
    blocker = '''
<script>
const originalFetch = window.fetch;
window.fetch = async function(url, opts) {
    if (opts && opts.method === 'POST') {
        alert("Editing is disabled in the static Cloud Hosted dashboard. Use the local CLI or run Flask locally to add to your portfolio/tracking.");
        return new Response(JSON.stringify({error: "read-only"}), {status: 403});
    }
    // Cache-bust all .json requests so the browser always gets fresh data
    if (typeof url === 'string' && url.endsWith('.json')) {
        url += (url.includes('?') ? '&' : '?') + '_t=' + Date.now();
    }
    return originalFetch.call(this, url, opts);
};
</script>
</head>
'''
    html = html.replace("</head>", blocker)
    
    with open(public_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    shutil.copy(PROJECT_ROOT / "src" / "web" / "static" / "style.css", static_dir / "style.css")
    
    # JS
    js_src = PROJECT_ROOT / "src" / "web" / "static" / "app.js"
    with open(js_src, "r", encoding="utf-8") as f:
        js = f.read()
        
    # Patch main API routes
    js = js.replace("fetch('/api/market-status')", "fetch('api/market-status.json')")
    js = js.replace("fetch('/api/cache-status')", "fetch('api/cache-status.json')")
    js = js.replace("fetch('/api/summary')", "fetch('api/summary.json')")
    js = js.replace("fetch('/api/portfolio')", "fetch('api/portfolio.json')")
    js = js.replace("fetch('/api/watchlist')", "fetch('api/watchlist.json')")
    js = js.replace("fetch('/api/tracking')", "fetch('api/tracking.json')")
    
    # Patch dynamic symbol routes
    js = js.replace("fetch(`/api/stock/${encodeURIComponent(symbol)}/chart`)", "fetch(`api/stock/${encodeURIComponent(symbol)}_chart.json`)")
    js = js.replace("fetch(`/api/stock/${encodeURIComponent(symbol)}/analysis`)", "fetch(`api/stock/${encodeURIComponent(symbol)}_analysis.json`)")
    
    # Patch search mechanism
    # Look for fetch(`/api/search?q=${encodeURIComponent(q)}`);
    search_patch_source = "const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);\\n        const data = await res.json();"
    # Wait, the exact code has single backticks: fetch(`/api/search?q=${encodeURIComponent(q)}`)
    # Let's perform a smart string replacement:
    search_old = "const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);"
    search_new = "const res = await fetch('api/search.json');"
    js = js.replace(search_old, search_new)
    
    filter_old = "const data = await res.json();"
    filter_new = "const data = await res.json(); data.results = data.results.filter(s => s.toLowerCase().includes(q.toLowerCase()));"
    # We only want to replace this in the context of the search function. But doing it globally is risky.
    # Instead, let's just let it be a tiny bit messy and replace it explicitly:
    js = js.replace(search_old + "\\n        " + filter_old, search_new + "\\n        " + filter_new)
    
    with open(static_dir / "app.js", "w", encoding="utf-8") as f:
        f.write(js)
        
    print("Static build complete! Output is in the 'public/' directory.")

if __name__ == '__main__':
    build_static_site()
