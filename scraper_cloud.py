#!/usr/bin/env python3
"""
INSIDER TRADING SCRAPER - GITHUB ACTIONS VERSION WITH EMAIL REPORTS
Uses sec-api.io Insider Trading API + yfinance for prices
Looks back 90 days and computes price impact since trade
ONLY REAL DATA - NO SAMPLE DATA
"""

import os
import json
import smtplib
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from email.mime_text import MIMEText
from email.mime.multipart import MIMEMultipart

# EMAIL CONFIGURATION (Use environment variables)
EMAIL_CONFIG = {
    'sender_email': os.getenv('SENDER_EMAIL', 'YOUR_EMAIL@gmail.com'),
    'sender_password': os.getenv('SENDER_PASSWORD', 'YOUR_APP_PASSWORD'),
    'recipient_email': os.getenv('RECIPIENT_EMAIL', 'YOUR_EMAIL@gmail.com'),
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587
}

# SEC API CONFIG
SECAPI_KEY = os.getenv('SECAPI_KEY', '')
SECAPI_ENDPOINT = "https://api.sec-api.io/insider-trading"


class InsiderTradingScraperCloud:
    def __init__(self):
        self.data_dir = Path('data')
        self.data_dir.mkdir(exist_ok=True)
        self.trades = []
        self.timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S CET')

    def fetch_insider_trades_last_90d_secapi(self):
        """
        Fetch insider trades for last 90 days via sec-api.io Insider Trading API
        using a broad string-based query (Form 3/4/5 + date range, NO ticker filter yet).
        """
        if not SECAPI_KEY:
            print("❌ SECAPI_KEY not set. Skipping sec-api.io fetch.")
            return []

        print("  Fetching insider trades (last 90 days) via sec-api.io...")

        today = datetime.utcnow().date()
        start_date = today - timedelta(days=90)

        # Broad query: all Forms 3/4/5 over last 90 days (no ticker filter yet)
        query_string = (
            f"formType:(3 4 5) "
            f"AND filedAt:[{start_date.strftime('%Y-%m-%d')} TO {today.strftime('%Y-%m-%d')}]"
        )

        payload = {
            "query": query_string,
            "from": 0,
            "size": 50,  # sec-api.io size limit
            "sort": [{"filedAt": {"order": "desc"}}]
        }

        headers = {
            "Authorization": SECAPI_KEY,
            "Content-Type": "application/json"
        }

        try:
            resp = requests.post(SECAPI_ENDPOINT, headers=headers, data=json.dumps(payload), timeout=25)
            if resp.status_code != 200:
                print(f"❌ sec-api.io returned {resp.status_code}: {resp.text[:200]}")
                return []

            data = resp.json()
            filings = data.get("filings", [])
            if not filings:
                print("⚠️ sec-api.io: no filings returned for query")
        except Exception as e:
            print(f"❌ sec-api.io error: {e}")
            return []

        all_trades = []
        price_cache = {}

        for filing in filings:
            try:
                issuer = filing.get("issuer", {}) or {}
                reporting_owners = filing.get("reportingOwners", []) or []
                non_deriv = filing.get("nonDerivativeTable", []) or []
                deriv = filing.get("derivativeTable", []) or []

                ticker = issuer.get("tradingSymbol") or issuer.get("ticker") or ""
                if not ticker:
                    continue
                ticker = ticker.upper()

                company_name = issuer.get("name") or issuer.get("issuerName") or ticker
                filed_at = filing.get("filedAt") or filing.get("filingDate")
                if filed_at:
                    filed_date = filed_at[:10]
                else:
                    filed_date = ""

                # Prepare price history once per ticker
                if ticker not in price_cache:
                    try:
                        t = yf.Ticker(ticker)
                        price_hist = t.history(
                            start=start_date,
                            end=today + timedelta(days=1),
                            auto_adjust=False
                        )
                        price_cache[ticker] = price_hist
                    except Exception as e:
                        print(f"  ⚠️ yfinance price error for {ticker}: {e}")
                        price_cache[ticker] = pd.DataFrame()

                price_hist = price_cache.get(ticker, pd.DataFrame())
                latest_close = None
                if not price_hist.empty:
                    try:
                        latest_close = float(price_hist["Close"].iloc[-1])
                    except Exception:
                        latest_close = None

                for owner in reporting_owners:
                    owner_name = (owner.get("name") or owner.get("reportingOwnerName") or "").strip()
                    rel = owner.get("relationship", {}) or {}

                    roles = []
                    if rel.get("isDirector"):
                        roles.append("Director")
                    if rel.get("isOfficer"):
                        roles.append("Officer")
                    if rel.get("isTenPercentOwner"):
                        roles.append("10% Owner")
                    if rel.get("isOther"):
                        roles.append("Other")

                    actor_role = ", ".join(roles) if roles else "Insider"
                    actor_type = "insider"

                    other_text = str(rel.get("otherText") or "").lower()
                    if any(x in other_text for x in ["senator", "rep.", "representative", "congress", "mp", "parliament"]):
                        actor_type = "politician"

                    all_tx_tables = []
                    for entry in non_deriv:
                        txs = entry.get("transactions", []) or []
                        all_tx_tables.extend(txs)
                    for entry in deriv:
                        txs = entry.get("transactions", []) or []
                        all_tx_tables.extend(txs)

                    if not all_tx_tables:
                        continue

                    for tx in all_tx_tables:
                        try:
                            tx_date_raw = tx.get("transactionDate", {}) or {}
                            tx_date_str = tx_date_raw.get("value") or filed_date
                            tx_date = None
                            if tx_date_str:
                                tx_date = datetime.strptime(tx_date_str[:10], "%Y-%m-%d").date()

                            code_raw = tx.get("transactionCoding", {}) or {}
                            code = (code_raw.get("transactionCode") or "").upper()
                            trade_type = "buy"
                            if code in ["S", "SD", "SE", "SS", "S*"]:
                                trade_type = "sell"
                            elif code in ["P", "M", "C", "A"]:
                                trade_type = "buy"

                            amounts = tx.get("transactionAmounts", {}) or {}
                            shares_val = (amounts.get("transactionShares") or {}).get("value")
                            price_val = (amounts.get("transactionPricePerShare") or {}).get("value")

                            total_val = None
                            try:
                                if shares_val and price_val:
                                    total_val = float(shares_val) * float(price_val)
                            except Exception:
                                total_val = None

                            price_at_trade = None
                            pct_change = None
                            if price_hist is not None and not price_hist.empty and tx_date:
                                try:
                                    ph = price_hist[price_hist.index.date >= tx_date]
                                    if not ph.empty:
                                        price_at_trade = float(ph["Close"].iloc[0])
                                except Exception:
                                    price_at_trade = None

                            if latest_close and price_at_trade and price_at_trade > 0:
                                try:
                                    pct_change = round(
                                        (latest_close - price_at_trade) / price_at_trade * 100,
                                        2
                                    )
                                except Exception:
                                    pct_change = None

                            all_trades.append({
                                "source": "sec-api.io",
                                "ticker": ticker,
                                "company_name": company_name,
                                "trader": owner_name[:50] if owner_name else "Unknown",
                                "title": actor_role[:60],
                                "trade_type": trade_type,
                                "shares": str(shares_val) if shares_val is not None else "N/A",
                                "value": f"{total_val:.2f}" if isinstance(total_val, (int, float)) else "N/A",
                                "filed_date": tx_date_str[:10] if tx_date_str else filed_date,
                                "actor_type": actor_type,
                                "actor_role": actor_role,
                                "price_at_trade": price_at_trade,
                                "current_price": latest_close,
                                "pct_change_since_trade": pct_change,
                            })
                        except Exception as e:
                            print(f"  ⚠️ error parsing transaction for {ticker}: {e}")
                            continue

            except Exception as e:
                print(f"  ⚠️ error parsing filing: {e}")
                continue

        print(f"✅ Collected {len(all_trades)} trades from last 90 days via sec-api.io")
        return all_trades

    def save_trades(self, trades):
        """Save trades to JSON file."""
        try:
            file_path = self.data_dir / "insider_trades_data.json"

            seen = set()
            unique_trades = []
            for trade in trades:
                ticker = trade.get("ticker", "")
                filed_date = trade.get("filed_date", "")
                trader = trade.get("trader", "")
                key = f"{ticker}_{filed_date}_{trader}"

                if key not in seen and ticker:
                    seen.add(key)
                    unique_trades.append(trade)

            with open(file_path, "w") as f:
                json.dump(unique_trades, f, indent=2)

            print(f"💾 Saved {len(unique_trades)} trades to {file_path}")
            return unique_trades

        except Exception as e:
            print(f"❌ Save error: {e}")
            return []

    def generate_email_report(self, trades):
        """Generate HTML email report with actor + impact columns."""

        buy_trades = [t for t in trades if t.get("trade_type") == "buy"]
        sell_trades = [t for t in trades if t.get("trade_type") == "sell"]

        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; background: #f5f5f5; }}
                .container {{ max-width: 1100px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }}
                h1 {{ color: #1e40af; border-bottom: 3px solid #1e40af; padding-bottom: 10px; }}
                h2 {{ color: #22c55e; margin-top: 20px; }}
                h2.sell {{ color: #ef4444; }}
                .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 20px 0; }}
                .stat-box {{ background: #f0f9ff; padding: 15px; border-radius: 6px; border-left: 4px solid #1e40af; }}
                .stat-box.buy {{ border-left-color: #22c55e; }}
                .stat-box.sell {{ border-left-color: #ef4444; }}
                table {{ width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 12px; }}
                th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background: #f3f4f6; font-weight: bold; }}
                tr:hover {{ background: #f9fafb; }}
                .ticker {{ font-weight: bold; color: #1e40af; font-size: 13px; }}
                .source {{ color: #666; font-size: 10px; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px; }}
                .warning {{ background: #fef3c7; padding: 12px; border-radius: 6px; margin: 20px 0; border-left: 4px solid #f59e0b; }}
                .header-row {{ background: #f0f0f0; font-weight: bold; }}
                .no-data {{ background: #fee2e2; padding: 20px; border-radius: 6px; margin: 20px 0; border-left: 4px solid #ef4444; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📊 Insider Trading Report (Last 90 Days)</h1>
                <p><strong>Report Date:</strong> {self.timestamp}</p>
                
                <div class="stats">
                    <div class="stat-box buy">
                        <strong>Buy Orders:</strong> {len(buy_trades)}
                    </div>
                    <div class="stat-box sell">
                        <strong>Sell Orders:</strong> {len(sell_trades)}
                    </div>
                    <div class="stat-box">
                        <strong>Total Trades:</strong> {len(trades)}
                    </div>
                    <div class="stat-box">
                        <strong>Sources:</strong> sec-api.io (SEC Forms 3/4/5) + yfinance prices
                    </div>
                </div>
                
                <div class="warning">
                    <strong>⚠️ Disclaimer:</strong> This is educational information only. Not investment advice. 
                    All data is from public SEC filings and public market data. Always do your own research and consult a financial advisor.
                </div>
        """

        if not trades or len(trades) == 0:
            html_content += """
                <div class="no-data">
                    <h3>⚠️ NO REAL DATA AVAILABLE FOR LAST 90 DAYS</h3>
                    <p>sec-api.io did not return insider trading data in the last 90 days.</p>
                    <p>This can be due to API limits, processing delays, or other restrictions.</p>
                    <p><strong>No action taken. Please check again later.</strong></p>
                </div>
            """
        else:
            # BUY TRADES
            if buy_trades:
                html_content += (
                    "<h2>💰 BUY TRADES</h2>"
                    "<table><tr class='header-row'>"
                    "<th>Ticker</th><th>Company</th><th>Trader</th>"
                    "<th>Role</th><th>Actor Type</th><th>Type</th>"
                    "<th>Shares</th><th>Value (USD)</th>"
                    "<th>Price @ Trade</th><th>Current</th><th>% Since Trade</th>"
                    "<th>Date</th></tr>"
                )
                for trade in buy_trades[:150]:
                    ticker = trade.get("ticker", "N/A")
                    company = trade.get("company_name", "N/A")[:30]
                    trader = trade.get("trader", "N/A")[:25]
                    shares = trade.get("shares", "N/A")
                    value = trade.get("value", "N/A")
                    date = trade.get("filed_date", "N/A")
                    source = trade.get("source", "")
                    actor_role = trade.get("actor_role", trade.get("title", "N/A"))
                    actor_type = trade.get("actor_type", "insider")
                    trade_type = trade.get("trade_type", "N/A").upper()

                    pat = trade.get("price_at_trade", None)
                    cur = trade.get("current_price", None)
                    pct = trade.get("pct_change_since_trade", None)

                    pat_str = f"{pat:.2f}" if isinstance(pat, (int, float)) else "N/A"
                    cur_str = f"{cur:.2f}" if isinstance(cur, (int, float)) else "N/A"
                    pct_str = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else "N/A"

                    html_content += f"""
                    <tr>
                        <td><span class="ticker">{ticker}</span><br><span class="source">{source}</span></td>
                        <td>{company}</td>
                        <td>{trader}</td>
                        <td>{actor_role}</td>
                        <td>{actor_type}</td>
                        <td>{trade_type}</td>
                        <td>{shares}</td>
                        <td>{value}</td>
                        <td>{pat_str}</td>
                        <td>{cur_str}</td>
                        <td>{pct_str}</td>
                        <td>{date}</td>
                    </tr>
                    """
                html_content += "</table>"

            # SELL TRADES
            if sell_trades:
                html_content += (
                    "<h2 class='sell'>📉 SELL TRADES</h2>"
                    "<table><tr class='header-row'>"
                    "<th>Ticker</th><th>Company</th><th>Trader</th>"
                    "<th>Role</th><th>Actor Type</th><th>Type</th>"
                    "<th>Shares</th><th>Value (USD)</th>"
                    "<th>Price @ Trade</th><th>Current</th><th>% Since Trade</th>"
                    "<th>Date</th></tr>"
                )
                for trade in sell_trades[:150]:
                    ticker = trade.get("ticker", "N/A")
                    company = trade.get("company_name", "N/A")[:30]
                    trader = trade.get("trader", "N/A")[:25]
                    shares = trade.get("shares", "N/A")
                    value = trade.get("value", "N/A")
                    date = trade.get("filed_date", "N/A")
                    source = trade.get("source", "")
                    actor_role = trade.get("actor_role", trade.get("title", "N/A"))
                    actor_type = trade.get("actor_type", "insider")
                    trade_type = trade.get("trade_type", "N/A").upper()

                    pat = trade.get("price_at_trade", None)
                    cur = trade.get("current_price", None)
                    pct = trade.get("pct_change_since_trade", None)

                    pat_str = f"{pat:.2f}" if isinstance(pat, (int, float)) else "N/A"
                    cur_str = f"{cur:.2f}" if isinstance(cur, (int, float)) else "N/A"
                    pct_str = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else "N/A"

                    html_content += f"""
                    <tr>
                        <td><span class="ticker">{ticker}</span><br><span class="source">{source}</span></td>
                        <td>{company}</td>
                        <td>{trader}</td>
                        <td>{actor_role}</td>
                        <td>{actor_type}</td>
                        <td>{trade_type}</td>
                        <td>{shares}</td>
                        <td>{value}</td>
                        <td>{pat_str}</td>
                        <td>{cur_str}</td>
                        <td>{pct_str}</td>
                        <td>{date}</td>
                    </tr>
                    """
                html_content += "</table>"

        html_content += """
                <div class="footer">
                    <p>Report generated automatically by Insider Trading Scraper (GitHub Actions).</p>
                    <p>Data sources: sec-api.io (SEC Forms 3/4/5), yfinance price history.</p>
                    <p>Raw data available in: data/insider_trades_data.json (in your GitHub repo).</p>
                </div>
            </div>
        </body>
        </html>
        """

        return html_content

    def send_email_report(self, trades, html_content):
        """Send email report."""
        try:
            if EMAIL_CONFIG["sender_email"] == "YOUR_EMAIL@gmail.com":
                print("⚠️ Email not configured. Skipping send.")
                return False

            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"📊 Insider Trading Report - {datetime.now().strftime('%Y-%m-%d')}"
            msg["From"] = EMAIL_CONFIG["sender_email"]
            msg["To"] = EMAIL_CONFIG["recipient_email"]

            part = MIMEText(html_content, "html")
            msg.attach(part)

            with smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"]) as server:
                server.starttls()
                server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
                server.send_message(msg)

            print(f"✅ Email sent to {EMAIL_CONFIG['recipient_email']}")
            return True

        except Exception as e:
            print(f"❌ Email error: {e}")
            return False

    def run_scrape(self):
        """Execute full scrape - ONLY REAL DATA."""
        print("\n" + "=" * 80)
        print(f"🌐 INSIDER TRADING SCRAPE - {self.timestamp}")
        print("=" * 80)

        print("\n📥 Fetching insider trading data (last 90 days) from sec-api.io...")

        trades = self.fetch_insider_trades_last_90d_secapi()

        if len(trades) == 0:
            print("\n⚠️ No real data returned from sec-api.io for last 90 days")

        saved_trades = self.save_trades(trades)

        print("\n📧 Generating email report...")
        html_report = self.generate_email_report(saved_trades)

        print("📧 Sending email...")
        self.send_email_report(saved_trades, html_report)

        print("\n✅ SCRAPE COMPLETE")
        print(f"Total trades collected: {len(saved_trades)}")
        print("=" * 80 + "\n")

        return saved_trades


def main():
    scraper = InsiderTradingScraperCloud()
    scraper.run_scrape()


if __name__ == "__main__":
    main()
