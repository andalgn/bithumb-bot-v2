# Trading Dashboard Quick Start Guide

**For:** Building a professional monitoring dashboard for bithumb-bot-v2
**Time Estimate:** 4-6 weeks for web dashboard + 2-3 weeks for terminal UI
**Difficulty:** Medium (Python + async, no frontend framework needed)

---

## TL;DR - Executive Summary

**Build two complementary dashboards:**

### Primary: Web Dashboard (Weeks 1-6)
```bash
Framework: Dash (Python)
Backend: FastAPI
Real-Time: WebSocket for orders, SSE for prices
Charting: Plotly (candlestick OHLCV)
Access: http://localhost:8080 (browser)
```

### Secondary: Terminal UI (Weeks 4-7, parallel)
```bash
Framework: Textual (Python TUI)
Access: SSH terminal or local tmux
Purpose: 24/7 monitoring complement to web
Updates: 200-500ms refresh rate
```

---

## Step 1: Choose Your Framework (5 minutes)

### Decision Checklist
- [ ] Do you want maximum customization? → Use FastAPI + Custom React
- [ ] Do you want fastest development? → Use **Dash (Python)** ✅ RECOMMENDED
- [ ] Do you want terminal access? → Also add Textual ✅ RECOMMENDED
- [ ] Do you need a desktop app? → Wait for Tauri Python support

**→ Decision: Dash + Plotly + WebSocket + Textual TUI**

---

## Step 2: Install Dependencies (10 minutes)

```bash
# Install Python packages
pip install dash plotly dash-bootstrap-components
pip install fastapi websockets uvicorn python-multipart
pip install textual rich

# Verify installations
python -c "import dash; print(dash.__version__)"
python -c "import plotly; print(plotly.__version__)"
python -c "from textual import __version__; print(__version__)"
```

---

## Step 3: Create Project Structure (5 minutes)

```bash
# From project root
mkdir -p app/dashboard
mkdir -p app/dashboard/layouts
mkdir -p app/dashboard/components
mkdir -p app/tui_monitor

# Create files
touch app/dashboard/__init__.py
touch app/dashboard/server.py
touch app/dashboard/callbacks.py
touch app/dashboard/websocket.py
touch app/dashboard/layouts/__init__.py
touch app/dashboard/layouts/trading_page.py
touch app/dashboard/components/__init__.py
touch app/dashboard/components/charts.py
touch app/tui_monitor/__init__.py
touch app/tui_monitor/app.py
```

---

## Step 4: Implement Dash Server (30 minutes)

**File: `app/dashboard/server.py`**

```python
from dash import Dash, dcc, html, callback, Input, Output
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime
import asyncio

# Create Dash app
app = Dash(__name__)

# Define app layout
app.layout = html.Div([
    # Header
    html.Header([
        html.H1("Bithumb Bot Dashboard", className="title"),
        html.Div([
            html.Span(id='bot-status', children="Status: LIVE", className="status-badge"),
            html.Span(id='equity-display', children="Equity: $10,000", className="metric"),
            html.Span(id='pnl-display', children="P&L: +$234 (+2.3%)", className="metric"),
        ], className="header-metrics"),
    ], className="header"),

    html.Div([
        # Sidebar
        html.Aside([
            html.Nav([
                html.A("📊 Trading", href="#", id="nav-trading", className="nav-active"),
                html.A("📈 Analysis", href="#", id="nav-analysis", className="nav-item"),
                html.A("⚙️ System", href="#", id="nav-system", className="nav-item"),
            ]),
        ], className="sidebar"),

        # Main content
        html.Main([
            # Charts section
            dcc.Graph(id='price-chart', style={'height': '400px'}),

            # Positions table
            html.Section([
                html.H2("Active Positions"),
                html.Table(id='positions-table', className='positions-table'),
            ], className="section"),

            # Recent trades
            html.Section([
                html.H2("Recent Trades"),
                html.Div(id='recent-trades', className='trades-log'),
            ], className="section"),
        ], className="main-content"),
    ], className="container"),

    # Auto-update interval (1 second)
    dcc.Interval(id='interval-component', interval=1000, n_intervals=0),
])

# Callback: Update price chart
@app.callback(
    Output('price-chart', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_chart(n):
    """Update OHLCV candlestick chart every second"""
    try:
        # Fetch latest candles from your bot
        df = fetch_latest_candles()  # Your function

        if df is None or len(df) == 0:
            raise PreventUpdate

        fig = go.Figure(data=[go.Candlestick(
            x=df['timestamp'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name='BTC/KRW'
        )])

        fig.update_layout(
            title='Price Action (1H)',
            yaxis_title='Price (KRW)',
            xaxis_rangeslider_visible=False,
            hovermode='x unified',
            height=400,
        )

        return fig
    except Exception as e:
        print(f"Error updating chart: {e}")
        raise PreventUpdate

# Callback: Update positions table
@app.callback(
    Output('positions-table', 'children'),
    Input('interval-component', 'n_intervals')
)
def update_positions(n):
    """Update position table every second"""
    try:
        positions = get_active_positions()  # Your function

        if not positions:
            return [html.Tr([html.Td("No active positions", colSpan=6)])]

        rows = [
            html.Tr([
                html.Th("Symbol"),
                html.Th("Entry"),
                html.Th("Current"),
                html.Th("P&L"),
                html.Th("Pct"),
                html.Th("Size"),
            ])
        ]

        for pos in positions:
            pnl_class = 'positive' if pos['pnl'] > 0 else 'negative'
            rows.append(html.Tr([
                html.Td(pos['symbol']),
                html.Td(f"${pos['entry_price']:.2f}"),
                html.Td(f"${pos['current_price']:.2f}"),
                html.Td(f"${pos['pnl']:.2f}", className=pnl_class),
                html.Td(f"{pos['pnl_pct']:.2f}%", className=pnl_class),
                html.Td(f"{pos['size']:.4f} BTC"),
            ]))

        return rows
    except Exception as e:
        print(f"Error updating positions: {e}")
        raise PreventUpdate

# Callback: Update metrics
@app.callback(
    [Output('bot-status', 'children'),
     Output('equity-display', 'children'),
     Output('pnl-display', 'children')],
    Input('interval-component', 'n_intervals')
)
def update_metrics(n):
    """Update header metrics every second"""
    try:
        metrics = get_bot_metrics()  # Your function

        status = "✓ LIVE" if metrics['is_live'] else "◯ PAPER"
        equity = f"Equity: ${metrics['equity']:,.2f}"
        pnl = f"P&L: {metrics['pnl_str']}"

        return status, equity, pnl
    except Exception as e:
        print(f"Error updating metrics: {e}")
        raise PreventUpdate

# CSS styling (inline)
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }

            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto;
                background: #f8f9fa;
                color: #333;
            }

            .header {
                background: white;
                border-bottom: 1px solid #e0e0e0;
                padding: 1rem;
                display: flex;
                justify-content: space-between;
                align-items: center;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }

            .header .title {
                font-size: 1.5rem;
                font-weight: 600;
            }

            .header-metrics {
                display: flex;
                gap: 2rem;
                align-items: center;
            }

            .status-badge {
                background: #10b981;
                color: white;
                padding: 0.5rem 1rem;
                border-radius: 4px;
                font-weight: 600;
                font-size: 0.9rem;
            }

            .metric {
                font-size: 0.95rem;
                font-weight: 500;
            }

            .container {
                display: flex;
                gap: 1rem;
                padding: 1rem;
                max-width: 1400px;
                margin: 0 auto;
            }

            .sidebar {
                width: 200px;
                background: white;
                border-radius: 4px;
                padding: 1rem;
                height: fit-content;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }

            nav {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }

            nav a {
                padding: 0.75rem;
                border-radius: 4px;
                text-decoration: none;
                color: #666;
                transition: all 0.2s;
                font-size: 0.9rem;
            }

            nav a:hover {
                background: #f0f0f0;
                color: #333;
            }

            nav a.nav-active {
                background: #3b82f6;
                color: white;
            }

            .main-content {
                flex: 1;
                display: flex;
                flex-direction: column;
                gap: 1rem;
            }

            .section {
                background: white;
                border-radius: 4px;
                padding: 1rem;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }

            .section h2 {
                font-size: 1.1rem;
                margin-bottom: 1rem;
                color: #333;
            }

            .positions-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 0.9rem;
            }

            .positions-table th,
            .positions-table td {
                padding: 0.75rem;
                text-align: left;
                border-bottom: 1px solid #e0e0e0;
            }

            .positions-table th {
                background: #f5f5f5;
                font-weight: 600;
                color: #666;
            }

            .positive { color: #10b981; font-weight: 500; }
            .negative { color: #ef4444; font-weight: 500; }

            .trades-log {
                max-height: 300px;
                overflow-y: auto;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer></footer>
        {%config%}
        {%scripts%}
        {%renderer%}
    </body>
</html>
'''

if __name__ == '__main__':
    app.run_server(debug=False, host='0.0.0.0', port=8080)
```

**Helper Functions (add to your bot's state module):**

```python
# Add these to fetch data from your bot
def fetch_latest_candles(symbol='BTC', timeframe='1h', limit=100):
    """Fetch latest candles from bot state"""
    # Connect to your market_store or bot state
    # Return DataFrame with columns: timestamp, open, high, low, close
    pass

def get_active_positions():
    """Get list of active positions"""
    # Return list of dicts with: symbol, entry_price, current_price, pnl, pnl_pct, size
    pass

def get_bot_metrics():
    """Get bot health metrics"""
    # Return dict with: is_live, equity, pnl_str, status, etc.
    pass
```

---

## Step 5: Add WebSocket for Orders (20 minutes)

**File: `app/dashboard/websocket.py`**

```python
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter
import json
import asyncio

router = APIRouter()

class OrderWebSocketManager:
    def __init__(self):
        self.active_connections = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Send order update to all connected clients"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"Error sending WebSocket message: {e}")

manager = OrderWebSocketManager()

@router.websocket("/ws/orders")
async def websocket_orders(websocket: WebSocket):
    """WebSocket endpoint for real-time order updates"""
    await manager.connect(websocket)

    try:
        while True:
            # Wait for order event from bot
            order_event = await get_order_event()  # Your queue

            if order_event:
                message = {
                    'type': 'order_update',
                    'symbol': order_event.symbol,
                    'status': order_event.status,
                    'entry_price': order_event.entry_price,
                    'timestamp': order_event.timestamp.isoformat(),
                }

                await manager.broadcast(message)

    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def get_order_event():
    """Get next order event from queue (your implementation)"""
    # This should connect to your bot's order queue
    pass
```

**Add to FastAPI app:**

```python
# In app/main.py or your FastAPI setup
from fastapi import FastAPI
from app.dashboard.server import app as dash_app
from app.dashboard.websocket import router as ws_router

api = FastAPI()

# Mount Dash app
api.mount('/dashboard', dash_app.server)

# Include WebSocket router
api.include_router(ws_router)

@api.get("/api/health")
async def health():
    """Health check endpoint"""
    return {
        'status': 'ok',
        'bot_status': 'live',
        'equity': 10000.0,
    }
```

---

## Step 6: Deploy as Systemd Service (20 minutes)

**File: `scripts/bithumb-dashboard.service`**

```ini
[Unit]
Description=Bithumb Bot Dashboard
After=network.target bithumb-bot.service
Wants=bithumb-bot.service

[Service]
Type=simple
User=bythejune
WorkingDirectory=/home/bythejune/projects/bithumb-bot-v2
ExecStart=/usr/bin/python3 -m app.dashboard.server
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Install:**

```bash
# Copy service file
sudo cp scripts/bithumb-dashboard.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable bithumb-dashboard
sudo systemctl start bithumb-dashboard

# Check status
sudo systemctl status bithumb-dashboard

# View logs
sudo journalctl -u bithumb-dashboard -f
```

---

## Step 7: Build Terminal UI (1 hour)

**File: `app/tui_monitor/app.py`**

```python
from textual.app import ComposeResult, RenderableType
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static, Header, Footer
from textual.reactive import reactive
from textual import work
import asyncio

class PositionPanel(Static):
    """Display active positions"""

    positions = reactive([])

    def render(self) -> RenderableType:
        from rich.table import Table

        table = Table(title="📊 Active Positions")
        table.add_column("Symbol", style="cyan")
        table.add_column("Entry", style="white")
        table.add_column("Current", style="white")
        table.add_column("P&L", style="green")
        table.add_column("Size", style="white")

        for pos in self.positions:
            pnl_color = "green" if pos['pnl'] > 0 else "red"
            table.add_row(
                pos['symbol'],
                f"${pos['entry']:.2f}",
                f"${pos['current']:.2f}",
                f"[{pnl_color}]${pos['pnl']:.2f}[/]",
                f"{pos['size']:.4f}",
            )

        return table

    @work(exclusive=True)
    async def update_positions(self):
        """Periodically update positions"""
        while True:
            self.positions = get_active_positions()  # Your function
            await asyncio.sleep(0.5)

class MetricsPanel(Static):
    """Display key metrics"""

    equity = reactive(10000.0)
    pnl = reactive(0.0)

    def render(self) -> RenderableType:
        from rich.panel import Panel
        from rich.table import Table

        table = Table.grid(padding=(0, 2))
        table.add_row(f"[bold]Equity:[/] ${self.equity:,.2f}")
        table.add_row(f"[bold]P&L:[/] [green]${self.pnl:.2f}[/]" if self.pnl > 0 else f"[bold]P&L:[/] [red]${self.pnl:.2f}[/]")

        return Panel(table, title="📈 Metrics", border_style="blue")

class DashboardApp(ComposeResult):
    """Terminal-based trading dashboard"""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

        with Vertical():
            yield MetricsPanel(id="metrics")
            yield PositionPanel(id="positions")

    @work(exclusive=True)
    async def on_mount(self) -> None:
        """App startup"""
        self.query_one(PositionPanel).update_positions()

if __name__ == '__main__':
    app = DashboardApp()
    app.run()
```

**Run TUI:**

```bash
python -m app.tui_monitor.app
```

Or in tmux alongside bot:

```bash
tmux new-session -d -s bithumb
tmux send-keys -t bithumb "python run_bot.py" Enter
tmux new-window -t bithumb
tmux send-keys -t bithumb "python -m app.tui_monitor.app" Enter
tmux attach -t bithumb
```

---

## Step 8: Test & Access (15 minutes)

### Test Locally
```bash
# Terminal 1: Start dashboard
python -m app.dashboard.server

# Terminal 2: Check endpoints
curl http://localhost:8080/           # Dashboard UI
curl http://localhost:8080/api/health # Health check

# Browser
open http://localhost:8080
```

### Access from Network
```bash
# On same network
http://192.168.10.3:8080

# From remote (with VPN)
ssh -L 8080:localhost:8080 bythejune@192.168.10.3
# Then open http://localhost:8080
```

---

## Step 9: Performance Tuning (Optional, 30 minutes)

### Add Caching
```python
# Reduce database queries
from functools import lru_cache

@lru_cache(maxsize=128)
def get_active_positions():
    # Return cached positions for 500ms
    pass
```

### Add Database Query Optimization
```python
# Use SQLite WAL mode for faster reads
conn.execute('PRAGMA journal_mode=WAL')
```

### Profile Performance
```bash
# Check dashboard response time
curl -w "@curl-format.txt" http://localhost:8080/api/health
```

---

## Checklist: Features by Week

### Week 1-2: Foundation
- [ ] Dash server running
- [ ] OHLCV chart displaying
- [ ] Positions table updating
- [ ] Basic styling

### Week 2-3: Real-Time
- [ ] WebSocket for orders integrated
- [ ] SSE for prices implemented
- [ ] Update interval optimized (1 second)
- [ ] No UI lag under load

### Week 3-4: Features
- [ ] Regime display added
- [ ] Strategy stats panel
- [ ] Risk metrics displayed
- [ ] Recent trades log

### Week 4-5: Polish
- [ ] Responsive design
- [ ] Dark mode option
- [ ] Mobile-friendly layout
- [ ] Documentation

### Week 5-6: Deployment
- [ ] Systemd service working
- [ ] Auto-restart on crash
- [ ] Discord alerts on dashboard error
- [ ] Production ready

### Week 4-7 (Parallel): Terminal UI
- [ ] Textual framework setup
- [ ] Position panel working
- [ ] Metrics panel displaying
- [ ] Auto-update loop running
- [ ] SSH access tested

---

## Troubleshooting

### Dashboard not updating?
```python
# Check if data functions exist
print(get_active_positions())
print(fetch_latest_candles())

# Enable debug mode
app.run_server(debug=True)
```

### WebSocket connection failing?
```javascript
// Check browser console (F12)
// Verify WebSocket URL: ws://localhost:8080/ws/orders
// Check for CORS issues
```

### Textual TUI not rendering?
```bash
# Check terminal is large enough (min 80x24)
# Ensure textual library installed
pip install textual --upgrade

# Run with debug
TEXTUAL=devtools python -m app.tui_monitor.app
```

---

## Next Steps After Basic Dashboard

1. **Add parameter adjustment UI** (2 weeks)
   - Sliders to tweak strategy parameters
   - Live restart without stopping bot

2. **Add backtesting comparison** (2 weeks)
   - Side-by-side P&L comparison
   - Shadow bot vs LIVE bot charts

3. **Add trade annotation** (1 week)
   - Click on trades to add notes
   - Self-reflection display

4. **Custom React frontend** (4+ weeks)
   - If Dash becomes limiting
   - Use [ashwinder-bot/stock-market-dashboard](https://github.com/ashwinder-bot/stock-market-dashboard) as template

---

## References

- **Dash Docs:** https://dash.plotly.com/
- **FastAPI WebSocket:** https://fastapi.tiangolo.com/advanced/websockets/
- **Textual Docs:** https://textual.textualize.io/
- **Example Project:** https://github.com/ashwinder-bot/stock-market-dashboard
- **Plotly Financial:** https://plotly.com/examples/finance/

---

## Timeline Summary

```
Week 1-2:  Foundation (Dash + basic charts)
Week 2-3:  Real-time (WebSocket + SSE)
Week 3-4:  Features (regime, stats, metrics)
Week 4-5:  Polish (responsive, dark mode)
Week 5-6:  Deploy (systemd service, production)
Week 4-7:  Terminal UI (parallel with phases 1-5)

Total: 6-7 weeks, 1 person
Result: Professional-grade trading dashboard + TUI monitor
```

**You're ready to start. Good luck!**
