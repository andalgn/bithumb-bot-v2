# Trading Dashboard Technology Decision Matrix

**Last Updated:** March 28, 2026
**Purpose:** Quick reference guide for choosing dashboard implementation approach

---

## 1. Framework Selection Quick Guide

### Quick Decision Tree

```
Do you need a desktop app (offline, native UI)?
  ├─ YES → Tauri + React + Python (lightweight)
  │         OR Electron + React + Python (proven but heavy)
  │
  └─ NO (server-side bot, always online)
      ├─ Need maximum customization?
      │   ├─ YES → FastAPI + Custom React + TypeScript
      │   └─ NO → Dash (Plotly + Python)
      │
      ├─ Need quick prototype?
      │   ├─ YES → Streamlit (but limited for real-time)
      │   └─ NO → Dash (production-grade)
      │
      └─ Need terminal monitoring?
          └─ YES → Textual TUI (async Python)
```

### Framework Scorecard

| Framework | Real-Time | Charting | Learning Curve | Complexity | Recommended |
|-----------|-----------|----------|----------------|-----------|-------------|
| **Dash (Plotly)** | 🟢 Excellent | 🟢 Excellent | 🟢 Low | 🟢 Low | ⭐⭐⭐ **USE THIS** |
| **FastAPI + React** | 🟢 Excellent | 🟢 Excellent | 🟡 Medium | 🟡 Medium | ⭐⭐⭐ Advanced only |
| **Streamlit** | 🔴 Poor | 🟢 Good | 🟢 Very Low | 🟢 Very Low | ❌ Not suitable |
| **Panel (HoloViz)** | 🟢 Excellent | 🟡 Good | 🟡 Medium | 🟡 Medium | ⭐⭐ Alternative |
| **NiceGUI** | 🟢 Excellent | 🟡 Medium | 🟡 Medium | 🟡 Medium | ⭐⭐ Consider |
| **Textual (TUI)** | 🟢 Excellent | 🔴 None | 🟡 Medium | 🟢 Low | ⭐⭐ Companion |
| **PyQt/PySide** | 🟡 Good | 🔴 Limited | 🔴 High | 🔴 High | ❌ Overkill |
| **Tauri + React** | 🟢 Excellent | 🟢 Excellent | 🔴 High | 🔴 High | ⏰ Wait for Python backend |
| **Electron + React** | 🟢 Excellent | 🟢 Excellent | 🔴 High | 🔴 Very High | ⏰ Only if desktop required |

---

## 2. Real-Time Data Pattern Selection

### When to Use What

```
Update Frequency     Pattern          Latency     Protocol    Use Case
─────────────────────────────────────────────────────────────────────
<0.5/sec             Polling          1-5s        HTTP        Health checks, metadata
0.5-2/sec            SSE              50-200ms    HTTP        Prices, metrics, public data
2-10/sec             WebSocket        10-50ms     WS          Orders, fills, position updates
10+/sec              WebSocket        <10ms       WS          High-frequency signals
Bidirectional        WebSocket        10-50ms     WS          Commands + responses
```

### Hybrid Pattern for bithumb-bot

```python
# Recommended: Mix SSE + WebSocket + Polling

# SSE: Price updates (stateless, proxy-friendly)
GET /stream/prices → EventStream
  └─ Updates every 500ms (2/sec)
  └─ Works through proxies

# WebSocket: Order updates (bidirectional, stateful)
WebSocket /ws/orders
  └─ Instant fill notifications
  └─ Position changes

# Polling: System health (fallback, fault-tolerant)
GET /api/health → JSON
  └─ Every 10 seconds
  └─ Lightweight check
```

---

## 3. Charting Library Selection Matrix

### When to Use Which Library

```
Use Case                    Library              Bundle Size    Performance    Notes
────────────────────────────────────────────────────────────────────────────────
Candlestick OHLCV          Plotly               2.5MB          Good (WebGL)   Financial presets
Lightweight charts          Lightweight-Charts   45KB            Excellent      TradingView-grade
Interactive dashboards      Recharts             100KB           Good           React-friendly
Heavy data (10k+ points)    ECharts              500KB           Excellent      Maps + 3D
Scientific/Research         Bokeh                2MB             Good           Jupyter-friendly
Simple metrics              Recharts             100KB           Good           Clean React API
Heatmaps (multi-coin)       ECharts              500KB           Excellent      Correlation matrices
Real-time updates           Lightweight-Charts   45KB            Excellent      Lowest overhead
```

### Recommended Combo for bithumb-bot

```
Primary Chart (Price Action):     Plotly Candlestick
Secondary Metrics (P&L, Equity):  Recharts Line Charts
Heatmaps (Momentum):              ECharts Heatmap
```

---

## 4. Deployment Architecture Comparison

### Option A: Web Dashboard (Recommended)

```
Your Ubuntu Server (Running 24/7)
  ├─ Bot Process (Python async)
  ├─ Dashboard Server (Dash on port 8080)
  └─ Database (SQLite)

Access:
  ├─ Local: http://localhost:8080
  ├─ Network: http://192.168.10.3:8080
  └─ Remote: http://your-ip:8080 (with VPN)

Systemd Service:
  ├─ bithumb-bot (main bot)
  └─ bithumb-dashboard (dashboard service)
```

**Pros:**
- Single machine, single codebase
- Browser accessible from any device
- No packaging overhead (no Electron)
- Works on all OS (web standard)

**Cons:**
- Requires network access (localhost only with default setup)
- Browser-dependent (no offline capability)

---

### Option B: Desktop App (Future, if needed)

```
Windows/Mac/Linux Desktop
  ├─ Tauri App (React frontend)
  └─ Sidecar Process (FastAPI Python backend)

Deployment:
  ├─ Executable installer (20-100MB)
  ├─ Auto-update support
  └─ Native window/menu integration

Real-Time:
  └─ HTTP localhost communication
```

**Pros:**
- Native desktop experience
- Offline capable
- Auto-updates

**Cons:**
- Requires installer per OS
- More complex deployment
- Larger bundle

---

### Option C: Terminal UI (Complementary)

```
Your Ubuntu Server (Running 24/7)
  └─ Bot Process + Dashboard (Textual TUI)

Access:
  ├─ Local tmux tab: Alt+Z, then `tmux attach -t bithumb`
  └─ SSH remote: `ssh -t user@ip 'tmux attach'`

Layout:
  Pane 1: Bot logs
  Pane 2: Textual dashboard (positions, P&L, alerts)
```

**Pros:**
- Lightweight (no browser needed)
- Remote SSH access
- Perfect 24/7 monitoring
- Can run in background

**Cons:**
- Limited charting (text-based only)
- Less pretty than web dashboard
- Terminal-only

---

## 5. Your Recommended Implementation Path

### Timeline & Complexity

```
Phase 1: Web Dashboard (Weeks 1-6)
├─ Set up Dash server (2 days)
├─ Build WebSocket order endpoint (3 days)
├─ Create OHLCV chart component (4 days)
├─ Build position table + metrics (4 days)
├─ Add regime/strategy displays (3 days)
├─ Integrate with bot state (3 days)
├─ Testing + deployment (3 days)
└─ Effort: ~4-6 weeks, 1 person

Phase 2: Terminal UI (Weeks 4-7, parallel)
├─ Create Textual framework (3 days)
├─ Build position panel (2 days)
├─ Add P&L/alerts panel (2 days)
├─ Connect to bot async queue (2 days)
├─ Testing in tmux (1 day)
└─ Effort: ~2-3 weeks, 1 person

Phase 3: Advanced Web Features (Months 2-3)
├─ Parameter adjustment UI (1 week)
├─ Backtest comparison view (1 week)
├─ Trade annotation + notes (3 days)
└─ Effort: ~2-3 weeks, 1 person
```

### Technology Stack Decision

```
✅ PRIMARY: Dash (Python)
   Reason: Same codebase, Plotly charting, WebSocket support,
           minimal learning curve, production-proven

✅ SECONDARY: Textual (Python)
   Reason: 24/7 monitoring, SSH access, lightweight,
           async-native, perfect complement to Dash

⏰ FUTURE: FastAPI + Custom React
   Reason: Only if Dash becomes limiting (unlikely),
           or need maximum UI customization

❌ AVOID: Electron, PyQt, Streamlit
   Reason: Desktop apps unnecessary, PyQt overkill,
           Streamlit inadequate for real-time trading
```

---

## 6. Specific File Structure for Dashboard

```
app/
├── main.py                    ← Current bot orchestrator
├── dashboard/
│   ├── __init__.py
│   ├── server.py             ← Dash app factory
│   ├── layouts/
│   │   ├── __init__.py
│   │   ├── trading_page.py   ← Primary trading view
│   │   ├── analysis_page.py  ← Stats + regime
│   │   └── system_page.py    ← Health + logs
│   ├── components/
│   │   ├── __init__.py
│   │   ├── charts.py         ← OHLCV + indicators
│   │   ├── tables.py         ← Positions, trades
│   │   └── metrics.py        ← KPI cards
│   ├── callbacks.py          ← Dash interactivity
│   └── websocket.py          ← WebSocket handlers
├── tui_monitor/              ← Terminal UI (NEW)
│   ├── __init__.py
│   ├── app.py                ← Textual main app
│   └── widgets/
│       ├── position_panel.py
│       ├── pnl_panel.py
│       └── alerts_panel.py
└── main.py                   ← Launch both dashboard + TUI
```

---

## 7. Quick Start: Dash Skeleton

```python
# app/dashboard/server.py
from dash import Dash, dcc, html, callback
import plotly.graph_objects as go
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Create Dash app attached to FastAPI
api = FastAPI()
app = Dash(__name__, server=api, url_base_pathname='/dashboard/')

# App layout
app.layout = html.Div([
    html.Header([
        html.Span("Bot Status: LIVE", id='status'),
        html.Span("Equity: $10,000", id='equity'),
        html.Span("P&L: +$234 (+2.3%)", id='pnl'),
    ]),

    html.Div([
        # Left sidebar (filters, navigation)
        html.Aside([
            html.Nav([
                html.A("Trading", href="/dashboard/", className="nav-link active"),
                html.A("Analysis", href="/dashboard/?tab=analysis", className="nav-link"),
                html.A("System", href="/dashboard/?tab=system", className="nav-link"),
            ]),
        ], className="sidebar"),

        # Main content
        html.Main([
            # Chart
            dcc.Graph(id='price-chart', style={'height': '400px'}),

            # Positions table
            html.Table(id='positions-table'),

            # Recent trades
            html.Div(id='recent-trades'),
        ], className="main-canvas"),
    ], className="container"),

    # Auto-update interval
    dcc.Interval(id='interval-component', interval=1000),  # 1 second
])

# Callback for price chart
@app.callback(
    Output('price-chart', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_chart(n):
    # Fetch latest OHLCV from bot
    df = fetch_latest_candlestick()  # Your function

    fig = go.Figure(data=[go.Candlestick(
        x=df['time'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close']
    )])
    return fig

# Callback for positions table
@app.callback(
    Output('positions-table', 'children'),
    Input('interval-component', 'n_intervals')
)
def update_positions(n):
    positions = get_active_positions()  # Your function
    rows = [html.Tr([
        html.Td(pos['symbol']),
        html.Td(f"${pos['entry_price']:.2f}"),
        html.Td(f"${pos['current_price']:.2f}"),
        html.Td(f"+${pos['pnl']:.2f}", className='positive' if pos['pnl'] > 0 else 'negative'),
    ]) for pos in positions]
    return rows

if __name__ == '__main__':
    api.run(host='0.0.0.0', port=8080)
```

---

## 8. WebSocket Integration Pattern

```python
# app/dashboard/websocket.py (FastAPI backend)
from fastapi import WebSocket, WebSocketDisconnect
import json
import asyncio

@api.websocket("/ws/orders")
async def websocket_orders(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            # Get order update from bot queue
            order_event = await bot.order_queue.get()  # Your queue

            # Send to frontend
            await websocket.send_json({
                'type': 'order_update',
                'symbol': order_event.symbol,
                'status': order_event.status,
                'timestamp': order_event.timestamp.isoformat(),
            })
    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
```

```javascript
// Frontend (Dash + JavaScript callback)
const ws = new WebSocket('ws://localhost:8080/ws/orders');

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('Order update:', data);
    // Trigger Dash callback to update UI
    fetch(`/api/update-positions?timestamp=${Date.now()}`);
};
```

---

## 9. Deployment Checklist

- [ ] Install Dash: `pip install dash plotly dash-bootstrap-components`
- [ ] Create `app/dashboard/` directory structure
- [ ] Write `app/dashboard/server.py` with Dash app
- [ ] Add WebSocket endpoint to FastAPI
- [ ] Create systemd service: `bithumb-dashboard.service`
- [ ] Test locally: `python -m app.dashboard.server`
- [ ] Test with browser: `http://localhost:8080`
- [ ] Test production: `sudo systemctl restart bithumb-dashboard`
- [ ] Add to bot startup script
- [ ] Set up SSL/TLS (optional, self-signed cert)
- [ ] Configure Nginx reverse proxy (optional)

---

## 10. Cost Comparison

| Component | Estimated Cost |
|-----------|----------------|
| Dash + Plotly | Free (open-source) |
| FastAPI | Free (open-source) |
| React (if custom) | Free (open-source) |
| Textual | Free (open-source) |
| Lightweight-Charts | Free (open-source) |
| Electron (if desktop) | Free (open-source) |
| Tauri (if desktop) | Free (open-source) |
| Hosting (you already have) | Already covered |
| **Total Additional Cost** | **$0** |

**Commercial Alternatives:**
- HighCharts (if need commercial license): ~$3,000/yr
- Dash Enterprise (if need enterprise features): ~$25k/yr
- Tradingview Widgets: Free (with branding)

**Recommendation:** Stick with open-source stack (Dash + Plotly).

---

## Final Decision: What to Build

### Your Situation:
- 24/7 server-side bot ✓
- Single small team ✓
- Ubuntu mini-PC (no desktop GUI needed) ✓
- Want real-time monitoring ✓
- Want professional appearance ✓

### Therefore: **Dash + Plotly Web Dashboard + Textual TUI**

```
Phase 1 (4-6 weeks):
  └─ Web Dashboard with Dash on port 8080
     ├─ OHLCV candlestick charts
     ├─ Position table with real-time updates
     ├─ P&L metrics + equity curve
     ├─ Risk gate status + regime display
     └─ Trade log + strategy performance

Phase 2 (2-3 weeks):
  └─ Terminal UI Monitor in tmux
     ├─ Real-time positions panel
     ├─ P&L + alerts panel
     ├─ Regime + system health panel
     └─ SSH-accessible monitoring

Result:
  ✓ Professional trading dashboard
  ✓ 24/7 monitoring capability
  ✓ No unnecessary desktop app overhead
  ✓ Pure Python (low maintenance)
  ✓ Web + terminal both covered
  ✓ Proven by dozens of trading platforms
```

---

**This is your path forward for bithumb-bot-v2 dashboard implementation.**

