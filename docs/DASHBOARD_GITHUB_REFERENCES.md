# Trading Dashboard GitHub Reference Directory

**Purpose:** Curated list of open-source projects, templates, and examples for building trading dashboards
**Last Updated:** March 28, 2026
**Research Scope:** 40+ projects analyzed from GitHub searches

---

## 1. Full-Stack Trading Dashboard Examples (Complete Projects)

### Tier 1: Recommended Starting Points

#### [ashwinder-bot/stock-market-dashboard](https://github.com/ashwinder-bot/stock-market-dashboard) ⭐⭐⭐
**Tech Stack:** FastAPI (Python) + React + SQLite + Docker
**Key Features:**
- Real-time stock data from yFinance
- Candlestick charts with Plotly
- Fully containerized (Docker)
- Simple, clean architecture
- Perfect template for bithumb-bot

**Why Use It:**
- Closest match to your use case
- Modern Python async backend
- Production-ready structure
- Good learning reference

**Complexity:** Medium
**Customization:** Easy (clear separation of concerns)

---

#### [nMaroulis/sibyl](https://github.com/nMaroulis/sibyl) ⭐⭐⭐
**Tech Stack:** Python + React + AI Agents + Trading Engine
**Key Features:**
- AI-powered crypto insights
- Exchange API connections
- Custom trading engine (BUY/SELL orders)
- Backtesting integrated
- Real-time UI dashboard
- LLM agents for analysis

**Why Use It:**
- Shows how to integrate trading engine with dashboard
- Real-world crypto exchange integration
- Good pattern for order/position tracking
- Advanced AI integration example

**Complexity:** High
**Customization:** Medium (complex but well-structured)

---

#### [marketcalls/openalgo](https://github.com/marketcalls/openalgo) ⭐⭐⭐
**Tech Stack:** Flask + React + 30+ Broker APIs
**Key Features:**
- Enterprise-grade platform
- 30+ Indian broker integrations
- Self-hosted algo trading
- AI agentic coding tools
- Unified API layer

**Why Use It:**
- Production enterprise example
- Shows how to handle multiple exchanges
- Good architecture patterns
- Advanced features reference

**Complexity:** Very High
**Customization:** Difficult (meant as complete platform)

---

### Tier 2: Good Learning Examples

#### [reshinto/online_trading_platform](https://github.com/reshinto/online_trading_platform)
**Tech Stack:** Django (Python) + React (Redux) + Material-UI
**Key Features:**
- Stock trading simulator
- Company fundamentals display
- News feed integration
- Material-UI for styling
- Redux state management

**Purpose:** Good for understanding full-stack architecture with state management

---

#### [danielxxhogan/rando-trader](https://github.com/danielxxhogan/rando-trader)
**Tech Stack:** Python scripts + React/Express + PostgreSQL + EC2
**Key Features:**
- Data collection pipeline (web scraping + APIs)
- Automated trading algorithms
- Cloud deployment on AWS
- Production-style infrastructure

**Purpose:** Shows real-world deployment with data pipeline

---

#### [davesearle/stockreturns-dashboard](https://github.com/davesearle/stockreturns-dashboard)
**Tech Stack:** Flask (Python) + React + IEX API
**Key Features:**
- Simple prototype quality
- Clean code for learning
- Minimal dependencies
- Good starting point

**Purpose:** Simplest complete example for beginners

---

#### [GitHub-Valie/trading-app](https://github.com/GitHub-Valie/trading-app)
**Tech Stack:** Flask (Python) + React
**Key Features:**
- Broker API integration
- Account information display
- Price data visualization
- Flask backend structure

**Purpose:** Simple Flask + React pattern for trading

---

### Tier 3: Cryptocurrency-Specific Examples

#### [sivakirlampalli/ai-trading-dashboard](https://github.com/sivakirlampalli/ai-trading-dashboard)
**Tech Stack:** FastAPI + React + SQLite + TailwindCSS
**Key Features:**
- AI trade signals
- Portfolio analytics
- Real-time market data
- Modern UI with TailwindCSS

**Purpose:** AI-powered signals example

---

#### [nMaroulis/sibyl](https://github.com/nMaroulis/sibyl) (Already listed above)

---

#### [dylewskii/cryptodashe](https://github.com/dylewskii/cryptodashe)
**Tech Stack:** MERN Stack (MongoDB, Express, React, Node.js) + TypeScript
**Key Features:**
- 10,000+ token support
- Portfolio tracking
- Portfolio management
- Type-safe implementation

**Purpose:** MERN alternative to Python stack, shows TypeScript patterns

---

#### [coinybubble/main-dashboard](https://github.com/coinybubble/main-dashboard)
**Tech Stack:** Vue.js + WebSocket
**Key Features:**
- Real-time cryptocurrency trading dashboard
- Live volume tracking
- Multi-exchange monitoring
- WebSocket architecture

**Purpose:** Vue.js alternative, excellent WebSocket patterns

---

#### [roblen001/Crypto-Bot](https://github.com/roblen001/Crypto-Bot)
**Tech Stack:** Flask + Gatsby + RL trading
**Key Features:**
- Reinforcement learning trading agent
- Continuous news scraping
- Flask API backend
- Gatsby frontend

**Purpose:** Advanced ML integration example

---

#### [mxvsh/modern-crypto-dashboard-ui](https://github.com/mxvsh/modern-crypto-dashboard-ui)
**Tech Stack:** React.js (Frontend only)
**Key Features:**
- Modern UI design
- Responsive layout
- Crypto dashboard inspiration
- Beautiful design patterns

**Purpose:** UI/UX inspiration, frontend-only

---

#### [pavandeveloperr/cryptocurrency-dashboard](https://github.com/pavandeveloperr/cryptocurrency-dashboard)
**Tech Stack:** React.js
**Key Features:**
- Multiple chart types
- Coin sorting and searching
- CoinGecko API integration
- Simple frontend

**Purpose:** Simple React dashboard example

---

#### [BobsProgrammingAcademy/cryptocurrency-dashboard](https://github.com/BobsProgrammingAcademy/cryptocurrency-dashboard)
**Tech Stack:** React 18 + Material UI 5 + Chart.js 4
**Key Features:**
- Material UI styling
- CoinGecko API integration
- Chart.js for visualization
- Educational quality code

**Purpose:** Good learning example with popular libraries

---

#### [akshada2712/Real-time-Crypto-Analysis](https://github.com/akshada2712/Real-time-Crypto-Analysis)
**Tech Stack:** Streamlit (Python) + LSTM
**Key Features:**
- Real-time data updates
- Candlestick charts
- Technical indicators (SMA, EMA)
- Price predictions with LSTM
- Market sentiment analysis

**Purpose:** Streamlit example with ML, but NOT recommended for real-time trading

---

#### [karkranikhil/react-dashboard](https://github.com/karkranikhil/react-dashboard)
**Tech Stack:** React.js
**Key Features:**
- Crypto currency dashboard
- React patterns
- Frontend-only example

**Purpose:** React learning reference

---

---

## 2. WebSocket + Real-Time Communication Examples

### Recommended WebSocket Patterns

#### [ustropo/websocket-example](https://github.com/ustropo/websocket-example)
**Tech Stack:** FastAPI (Python) + React + Recharts
**Key Features:**
- FastAPI WebSocket implementation
- React client with Recharts charts
- Real-time data streaming
- Simple, clear example

**Use For:** WebSocket pattern reference with Recharts charting

---

#### FastAPI WebSocket Documentation
**Resource:** [fastapi.tiangolo.com/advanced/websockets/](https://fastapi.tiangolo.com/advanced/websockets/)
**Key Content:**
- Official WebSocket implementation guide
- Code examples for Python
- Best practices from FastAPI team

---

#### [zhiyuan8/FastAPI-websocket-tutorial](https://github.com/zhiyuan8/FastAPI-websocket-tutorial)
**Tech Stack:** FastAPI + WebSocket + Database
**Key Features:**
- Real-time WebSocket communication
- Database integration (SQLAlchemy)
- Pydantic validation
- Middleware examples

**Use For:** Production WebSocket patterns

---

#### [Buuntu/fastapi-react](https://github.com/Buuntu/fastapi-react)
**Tech Stack:** FastAPI (Python) + React + PostgreSQL + Docker
**Key Features:**
- Cookiecutter template for FastAPI + React
- SQLAlchemy ORM
- Docker setup included
- PostgreSQL database

**Use For:** Quick project scaffold template

---

### Real-Time Dashboard Examples

#### [Build Real-Time Stock Price Dashboard in ReactJS](https://www.sevensquaretech.com/reactjs-live-stock-price-dashboard-websocket-github-code/)
**Resource:** Blog post with code examples
**Key Features:**
- Real-time stock prices
- WebSocket implementation
- React patterns
- GitHub code included

---

#### TestDriven.io: Real-Time Dashboard with FastAPI
**Resource:** [testdriven.io/blog/fastapi-postgres-websockets/](https://testdriven.io/blog/fastapi-postgres-websockets/)
**Key Content:**
- Complete tutorial
- FastAPI + PostgreSQL + WebSocket
- Production-ready patterns
- Testing examples

---

---

## 3. Charting Libraries & Visualization

### Financial Charting Libraries

#### [tradingview/lightweight-charts](https://github.com/tradingview/lightweight-charts) ⭐
**Tech Stack:** JavaScript/TypeScript (44 KB bundle)
**Key Features:**
- Ultra-fast financial charts
- TradingView-grade performance
- HTML5 canvas-based rendering
- Real-time streaming support
- OHLC, Line, Area, Histogram chart types

**Use For:** Maximum performance, professional trading terminal feel
**Integration:** Use with React wrapper or custom implementation

**Official Docs:** [tradingview.github.io/lightweight-charts/](https://tradingview.github.io/lightweight-charts/)

---

#### Plotly Financial Examples
**Resource:** [plotly.com/examples/finance/](https://plotly.com/examples/finance/)
**Key Features:**
- Pre-built financial chart templates
- Candlestick examples
- Range slider integration
- OHLCV visualization

**Use For:** Dash dashboard charting

---

#### [apache/echarts](https://github.com/apache/echarts)
**Tech Stack:** JavaScript/TypeScript (500 KB)
**Key Features:**
- 60+ chart types
- Heatmaps and correlation matrices
- 3D visualization
- High performance with large datasets

**Use For:** Multi-coin heatmaps, momentum rankings

---

### Python Charting Wrappers

#### [pyecharts](https://github.com/pyecharts/pyecharts)
**Purpose:** Python wrapper for ECharts
**Use For:** ECharts visualization in Python dashboards

---

#### [bokeh](https://github.com/bokeh/bokeh)
**Tech Stack:** Python + JavaScript
**Key Features:**
- Interactive visualizations
- Jupyter notebook integration
- Candlestick charts support
- WebSocket support via Bokeh Server

**Use For:** Scientific/research dashboards, Jupyter integration

---

#### [plotly/plotly.py](https://github.com/plotly/plotly.py)
**Tech Stack:** Python (official Plotly library)
**Key Features:**
- Financial chart templates
- Dash integration built-in
- Interactive charts
- WebGL for large datasets

**Use For:** Dash dashboard primary charting

---

---

## 4. Dashboard Frameworks & Libraries

### Python Dashboard Frameworks

#### Dash by Plotly
**Official Repo:** [plotly/dash](https://github.com/plotly/dash)
**Resource:** [dash.plotly.com/](https://dash.plotly.com/)
**Key Features:**
- Python-only framework
- Built on Flask
- Excellent Plotly integration
- Callback-based reactivity
- Financial dashboard templates

**Recommendation:** ⭐⭐⭐ PRIMARY CHOICE for bithumb-bot

---

#### Panel by HoloViz
**Official Repo:** [holoviz/panel](https://github.com/holoviz/panel)
**Resource:** [panel.holoviz.org/](https://panel.holoviz.org/)
**Key Features:**
- Flexible UI framework
- Jupyter notebook support
- WebSocket integration
- Multiple charting backends

**Recommendation:** ⭐⭐ ALTERNATIVE to Dash

---

#### NiceGUI
**Official Repo:** [zauberzeug/nicegui](https://github.com/zauberzeug/nicegui)
**Resource:** [nicegui.io/](https://nicegui.io/)
**Key Features:**
- Vue.js frontend from Python
- Modern Python-first approach
- WebSocket support
- Clean syntax

**Recommendation:** ⭐⭐ CONSIDER as alternative

---

#### Streamlit
**Official Repo:** [streamlit/streamlit](https://github.com/streamlit/streamlit)
**Resource:** [streamlit.io/](https://streamlit.io/)
**Key Features:**
- Fastest time-to-demo
- Data science focused
- Limited real-time capabilities

**Recommendation:** ❌ NOT SUITABLE for real-time trading

---

#### Gradio
**Official Repo:** [gradio-app/gradio](https://github.com/gradio-app/gradio)
**Resource:** [gradio.app/](https://gradio.app/)
**Key Features:**
- ML model demos
- Auto-generated UI
- Limited for trading

**Recommendation:** ❌ NOT SUITABLE for trading dashboards

---

### Terminal UI Framework

#### [Textualize/textual](https://github.com/Textualize/textual) ⭐
**Resource:** [textual.textualize.io/](https://textual.textualize.io/)
**Key Features:**
- Modern TUI framework for Python
- Async/await native
- CSS-like styling
- Mouse and keyboard support
- Real-time updates

**Use For:** Terminal dashboard complementary to web dashboard
**Recommendation:** ⭐⭐ SECONDARY, for 24/7 monitoring

---

#### [rothgar/awesome-tuis](https://github.com/rothgar/awesome-tuis)
**Purpose:** Curated list of terminal UI projects
**Use For:** Exploring other TUI examples and patterns

---

### Example Textual Projects

#### [stocksTUI](https://pypi.org/project/stocksTUI/)
**Tech Stack:** Textual + yfinance
**Key Features:**
- Live crypto price tracking
- Command-line interface
- Real-time updates
- Terminal-friendly

**Use For:** Reference for Textual trading dashboard

---

---

## 5. Desktop App Frameworks

### Tauri (Lightweight Desktop)

#### [tauri-apps/tauri](https://github.com/tauri-apps/tauri)
**Resource:** [tauri.app/](https://tauri.app/)
**Key Features:**
- Rust-based frontend framework
- 80MB vs Electron's 300MB
- Native OS windowing
- Python backend experimental

**Status:** Python support coming soon (v3+)
**Recommendation:** ⏰ WAIT for stable Python backend

---

#### [tauri-apps/awesome-tauri](https://github.com/tauri-apps/awesome-tauri)
**Purpose:** Collection of Tauri apps and resources
**Use For:** Learning Tauri patterns and best practices

---

### Electron (Heavy Desktop)

#### [electron/electron](https://github.com/electron/electron)
**Resource:** [electronjs.org/](https://electronjs.org/)
**Key Features:**
- Proven, mature framework
- Large ecosystem
- Large bundle (300MB+)
- High memory usage

**Recommendation:** ⏰ ONLY if desktop app essential

---

### PyQt/PySide (Native Desktop)

#### [pyqt/examples](https://github.com/pyqt/examples)
**Purpose:** PyQt learning examples
**Key Features:**
- Native desktop apps
- High performance
- Complex to learn

**Recommendation:** ❌ NOT recommended (overkill complexity)

---

---

## 6. Data Collection & Backtesting

### Algo Trading Platforms

#### [marketcalls/openalgo](https://github.com/marketcalls/openalgo)
**Already listed in Tier 1 section above**

---

#### [quantconnect/Lean](https://github.com/quantconnect/Lean)
**Tech Stack:** C# + Python
**Key Features:**
- Backtesting engine
- Multi-asset support
- Historical data included

**Use For:** Backtesting reference

---

#### [edtechre/pybroker](https://github.com/edtechre/pybroker)
**Tech Stack:** Python
**Key Features:**
- Algorithmic trading framework
- Machine learning focus
- Backtesting engine
- Fast NumPy-based calculations

**Use For:** Trading strategy and backtesting reference

---

#### [ranaroussi/qtpylib](https://github.com/ranaroussi/qtpylib)
**Tech Stack:** Python
**Key Features:**
- Pythonic algo trading library
- Paper/live trading support
- Interactive Brokers integration
- Web Reports component

**Use For:** Trading library reference with web reporting

---

### Data & Research

#### [merovinh/best-of-algorithmic-trading](https://github.com/merovinh/best-of-algorithmic-trading)
**Purpose:** Ranked list of algo trading libraries
**Use For:** Discovery of related tools and libraries

---

#### [wangzhe3224/awesome-systematic-trading](https://github.com/wangzhe3224/awesome-systematic-trading)
**Purpose:** Curated list of systematic trading resources
**Use For:** Systematic trading reference

---

---

## 7. Styling & UI Components

### Dash Bootstrap Components
**Repo:** [facultyai/dash-bootstrap-components](https://github.com/facultyai/dash-bootstrap-components)
**Purpose:** Bootstrap components for Dash
**Use For:** Quick professional styling in Dash dashboards

---

### TailwindCSS
**Repo:** [tailwindlabs/tailwindcss](https://github.com/tailwindlabs/tailwindcss)
**Purpose:** Utility-first CSS framework
**Use For:** Custom React dashboard styling

---

### shadcn/ui
**Repo:** [shadcn-ui/ui](https://github.com/shadcn-ui/ui)
**Purpose:** High-quality React components
**Use For:** Custom React dashboard UI components

---

---

## 8. API Integration Examples

### Bithumb API Integration

#### Exchange API Integration Pattern
**Resources for Learning:**
- [ashwinder-bot/stock-market-dashboard](https://github.com/ashwinder-bot/stock-market-dashboard) — yFinance integration
- [nMaroulis/sibyl](https://github.com/nMaroulis/sibyl) — Exchange API connections

---

---

## 9. Recommended Study Order

### For Web Dashboard (Dash)
1. Start: [ashwinder-bot/stock-market-dashboard](https://github.com/ashwinder-bot/stock-market-dashboard)
   - Clone and run locally
   - Understand FastAPI + React structure
   - Adapt for Bithumb API

2. Reference: [ustropo/websocket-example](https://github.com/ustropo/websocket-example)
   - Learn WebSocket pattern
   - Integrate into Dash app

3. Styling: Check out Plotly financial templates
   - Use candlestick examples
   - Apply to your data

### For Terminal UI (Textual)
1. Install: `pip install textual`
2. Tutorial: Official Textual docs
3. Reference: [stocksTUI](https://pypi.org/project/stocksTUI/)
   - Study code structure
   - Adapt for bithumb-bot

### For Advanced (Custom React)
1. Foundation: [Buuntu/fastapi-react](https://github.com/Buuntu/fastapi-react)
   - Understand scaffold structure
   - Learn template patterns

2. Real-time: [ustropo/websocket-example](https://github.com/ustropo/websocket-example)
   - WebSocket client patterns
   - Chart integration

3. Charting: [tradingview/lightweight-charts](https://github.com/tradingview/lightweight-charts)
   - Ultra-fast charting
   - Professional appearance

---

## 10. Quick Links Summary

### Essential Resources
- **Official Docs:**
  - [Dash Documentation](https://dash.plotly.com/)
  - [FastAPI Documentation](https://fastapi.tiangolo.com/)
  - [Plotly Charts](https://plotly.com/python/)
  - [Textual Framework](https://textual.textualize.io/)

- **Best Starter Template:**
  - [ashwinder-bot/stock-market-dashboard](https://github.com/ashwinder-bot/stock-market-dashboard)

- **WebSocket Reference:**
  - [FastAPI WebSocket Guide](https://fastapi.tiangolo.com/advanced/websockets/)
  - [ustropo/websocket-example](https://github.com/ustropo/websocket-example)

- **Charting Options:**
  - [Plotly Financial Templates](https://plotly.com/examples/finance/)
  - [lightweight-charts](https://github.com/tradingview/lightweight-charts)
  - [ECharts](https://github.com/apache/echarts)

- **Terminal UI:**
  - [Textual Framework](https://github.com/Textualize/textual)
  - [stocksTUI Example](https://pypi.org/project/stocksTUI/)

---

## Appendix: How to Use This Reference

### Finding a Specific Pattern
1. **WebSocket implementation?** → Section 2 (WebSocket Examples)
2. **Charting library choice?** → Section 3 (Charting Libraries)
3. **Complete dashboard template?** → Section 1 Tier 1 (Full-Stack Examples)
4. **Terminal UI?** → Section 4 (Terminal UI Framework)
5. **Styling?** → Section 7 (Styling & UI Components)

### Building Your Dashboard
1. **Foundation:** Clone [ashwinder-bot/stock-market-dashboard](https://github.com/ashwinder-bot/stock-market-dashboard)
2. **Real-Time:** Reference [ustropo/websocket-example](https://github.com/ustropo/websocket-example)
3. **Charting:** Use Plotly examples from [plotly.com/examples/finance/](https://plotly.com/examples/finance/)
4. **Terminal UI:** Study [Textual docs](https://textual.textualize.io/) with [stocksTUI](https://pypi.org/project/stocksTUI/) example
5. **Advanced:** Customize with [lightweight-charts](https://github.com/tradingview/lightweight-charts) if needed

---

**Last Updated:** March 28, 2026
**Total Projects Catalogued:** 40+
**Recommendation:** Start with [ashwinder-bot/stock-market-dashboard](https://github.com/ashwinder-bot/stock-market-dashboard) + [Textual](https://textual.textualize.io/) combination.
