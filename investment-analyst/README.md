# 📊 Google ADK Investment Analyst Agent

A lightweight, super-simple stock research agent built with **Google ADK** (Agent Development Kit) and powered by **Gemini 2.5 Flash**.

The agent retrieves real-time financial market data, fundamental metrics, and recent company news, synthesizing them into structured, objective investment research summaries.

---

## 📁 Project Structure

```
investment-analyst/
├── agent.py            # ADK root_agent definition with tools & instructions
├── tools.py            # Financial research tools (quotes, metrics, news via yfinance)
├── main.py             # User-friendly CLI runner (interactive REPL & single-shot queries)
├── __init__.py         # Package entry point exposing root_agent
├── requirements.txt    # Dependencies (google-adk, yfinance, python-dotenv)
├── .env.example        # Environment variable template
├── .env                # Local environment file for GOOGLE_API_KEY
├── .gitignore          # Git exclusion rules
└── README.md           # Documentation
```

---

## 🚀 Quick Start

### 1. Configure Your API Key

Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).

Set it in `.env`:
```bash
echo "GOOGLE_API_KEY=your_gemini_api_key_here" > .env
```

Or export it in your terminal:
```bash
export GOOGLE_API_KEY="your_gemini_api_key_here"
```

### 2. Run the Agent

#### Option A: Direct Python Runner (`main.py`)

Interactive conversation mode:
```bash
python main.py
```

Single-query mode:
```bash
python main.py "Give me an investment analysis of NVDA"
```

#### Option B: Google ADK CLI (`adk run`)

> **Note on Agent Invocation**: Run the agent directly using `python main.py` or through Google ADK.

From the parent folder:
```bash
adk run investment_analyst "Analyze Apple (AAPL) stock and provide bull/bear cases"
```

Or start the ADK interactive Web UI:
```bash
adk web /home/admin_
```

---

## 🛠️ Tools Included

| Tool | Description |
|------|-------------|
| `get_stock_quote(ticker)` | Fetches current price, currency, market cap, P/E ratios, 52-week high/low, and trading volume. |
| `get_financial_metrics(ticker)` | Fetches revenue, YoY revenue growth, profit margins, EPS, debt-to-equity, ROE, free cash flow, and Wall Street price targets. |
| `get_company_news(ticker, limit)` | Fetches latest headlines, publishers, and publication timestamps. |

---

## 📋 Research Output Format

When analyzing a stock, the agent provides:
1. **Executive Snapshot**: Ticker, Company Name, Current Price, Market Cap, 52-Week Range, P/E.
2. **Financial Health & Valuation**: Revenue growth, profit margins, balance sheet health (debt-to-equity), and cash flow.
3. **Bull Case**: Key growth drivers, competitive advantages, and upside catalysts.
4. **Bear Case**: Risks, valuation headwinds, debt load, and competitive threats.
5. **Analyst Consensus & Conclusion**: Price targets, buy/hold/sell consensus, and a balanced bottom line.

---

## ⚠️ Disclaimer

*This agent and its outputs are for educational and informational purposes only. Nothing generated constitutes financial, legal, or investment advice.*
