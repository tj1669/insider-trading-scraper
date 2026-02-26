#!/usr/bin/env python3
"""
INSIDER TRADING SCRAPER - GITHUB ACTIONS VERSION WITH EMAIL REPORTS
Uses yfinance insider_transactions + SEC fallback
Looks back 10 days and computes price impact since trade
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
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# EMAIL CONFIGURATION (Use environment variables)
EMAIL_CONFIG = {
    'sender_email': os.getenv('SENDER_EMAIL', 'YOUR_EMAIL@gmail.com'),
    'sender_password': os.getenv('SENDER_PASSWORD', 'YOUR_APP_PASSWORD'),
    'recipient_email': os.getenv('RECIPIENT_EMAIL', 'YOUR_EMAIL@gmail.com'),
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587
}

# Realistic headers (still used for SEC fallback)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


class InsiderTradingScraperCloud:
    def __init__(self):
        self.data_dir = Path('data')
        self.data_dir.mkdir(exist_ok=True)
        self.trades = []
        self.timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S CET')

    def fetch_insider_trades_last_10d(self):
        """Use yfinance insider_transactions + price history for last 10 days."""
        print("  Fetching insider trades (last 10 days) via yfinance...")

        tickers = [
            'NVDA', 'TSLA', 'MSFT', 'AAPL', 'GOOGL', 'META', 'AMZN',
            'JPM', 'BAC', 'GS', 'IBM', 'INTC', 'AMD', 'NFLX', 'UBER'
        ]

        all_trades = []
        today = datetime.utcnow().date()
        start_date = today - timedelta(days=10)

        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                df = t.insider_transactions  # DataFrame with insider activity
                if df is None or df.empty:
                    continue

                df = df.copy()
                if not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index, errors='coerce')

                df = df.dropna(subset=[df.index.name])

                # Filter to last 10 days
                df = df[(df.index.date >= start_date) & (df.index.date <= today)]
                if df.empty:
                    continue

                # Price history for impact
                price_hist = t.history(
                    start=start_date,
                    end=today + timedelta(days=1),
                    auto_adjust=False
                )
                if price_hist is None or price_hist.empty:
                    continue

                latest_close = float(price_hist['Close'].iloc[-1])

                for trade_time, row in df.iterrows():
                    trade_date = trade_time.date()

                    # Price at/after trade date
                    trade_price = None
                    try:
                        ph = price_hist[price_hist.index.date >= trade_date]
                        if not ph.empty:
                            trade_price = float(ph['Close'].iloc[0])
                    except Exception:
                        pass

                    pct_change = None
                    if trade_price and trade_price > 0:
                        pct_change = round(
                            (latest_close - trade_price) / trade_price * 100,
                            2
                        )

                    insider_name = str(row.get('Insider', '') or row.get('insider', '')).strip()
                    relationship = str(row.get('Relationship', '') or row.get('relationship', '')).strip()

                    # Classify actor
                    actor_type = 'insider'
                    actor_role = relationship or 'Insider'

                    lower_rel = relationship.lower()
                    if any(x in lower_rel for x in ['senator', 'rep.', 'representative', 'congress', 'mp', 'parliament']):
                        actor_type = 'politician'
                    elif any(x in lower_rel for x in ['ceo', 'cfo', 'cio', 'coo', 'president', 'chairman', 'director', 'vp']):
                        actor_type = 'insider'

                    trade_type = 'buy'
                    tx = str(row.get('Transaction', '') or row.get('Type', '')).lower()
                    if 'sell' in tx or 'sale' in tx:
                        trade_type = 'sell'

                    shares = row.get('Shares', None)
                    if shares is None:
                        shares = row.get('Share', None)

                    all_trades.append({
                        'source': 'yfinance_insider',
                        'ticker': ticker,
                        'company_name': ticker,
                        'trader': insider_name[:50] if insider_name else 'Unknown',
                        'title': actor_role[:60],
                        'trade_type': trade_type,
                        'shares': str(shares) if shares is not None else 'N/A',
                        'value': str(row.get('Value', 'N/A')),
                        'filed_date': trade_date.strftime('%Y-%m-%d'),
                        'actor_type': actor_type,               # insider vs politician
                        'actor_role': actor_role,               # CEO, Director, Senator, etc.
                        'price_at_trade': trade_price,
                        'current_price': latest_close,
                        'pct_change_since_trade': pct_change,
                    })
            except Exception as e:
                print(f"  ⚠️ yfinance error for {ticker}: {e}")
                continue

        print(f"✅ Collected {len(all_trades)} trades from last 10 days via yfinance")
        return all_trades

    def fetch_sec_filings_alternative(self):
        """Fetch from SEC using alternative method (simple recent Form 4 fallback)."""
        try:
            print("  Fetching recent Form 4 filings from SEC EDGAR (fallback)...")

            url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4&owner=exclude&count=40&myJSON=1"
            response = requests.get(url, headers=HEADERS, timeout=15)

            if response.status_code != 200:
                print(f"❌ SEC EDGAR returned {response.status_code}")
                return []

            data = response.json()
            trades = []

            filings = data.get('filings', [])
            for filing in filings[:20]:
                trade = {
                    'source': 'SEC EDGAR',
                    'ticker': (filing.get('ticker') or 'N/A').upper(),
                    'company_name': filing.get('company_name', 'N/A'),
                    'cik': filing.get('cik_str', ''),
                    'filed_date': filing.get('filing_date', 'N/A'),
                    'form_type': filing.get('form_type', 'Form 4'),
                    'actor_type': 'insider',
                    'actor_role': 'Insider (Form 4)',
                    'trade_type': 'N/A',
                    'shares': 'N/A',
                    'value': 'N/A',
                    'price_at_trade': None,
                    'current_price': None,
                    'pct_change_since_trade': None,
                    'trader': 'Unknown',
                    'title': 'Insider',
                }
                if trade['ticker'] and trade['ticker'] != 'N/A':
                    trades.append(trade)

            if trades:
                print(f"✅ Fetched {len(trades)} Form 4 filings from SEC EDGAR")
            else:
                print("⚠️ SEC EDGAR: No filings found")

            return trades

        except Exception as e:
            print(f"❌ SEC EDGAR error: {str(e)}")
            return []

    def save_trades(self, trades):
        """Save trades to JSON file."""
        try:
            file_path = self.data_dir / 'insider_trades_data.json'

            seen = set()
            unique_trades = []
            for trade in trades:
                ticker = trade.get('ticker', '')
                filed_date = trade.get('filed_date', '')
                trader = trade.get('trader', '')
                key = f"{ticker}_{filed_date}_{trader}"

                if key not in seen and ticker:
                    seen.add(key)
                    unique_trades.append(trade)

            with open(file_path, 'w') as f:
                json.dump(unique_trades, f, indent=2)

            print(f"💾 Saved {len(unique_trades)} trades to {file_path}")
            return unique_trades

        except Exception as e:
            print(f"❌ Save error: {str(e)}")
            return []

    def generate_email_report(self, trades):
        """Generate HTML email report with actor + impact columns."""

        buy_trades = [t for t in trades if t.get('trade_type') == 'buy']
        sell_trades = [t for t in trades if t.get('trade_type') == 'sell']

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
                <h1>📊 Insider Trading Report (Last 10 Days)</h1>
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
                        <strong>Sources:</strong> yfinance insider + SEC EDGAR
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
                    <h3>⚠️ NO REAL DATA AVAILABLE FOR LAST 10 DAYS</h3>
                    <p>Public APIs (yfinance / SEC EDGAR) did not return insider trading data for your ticker universe in the last 10 days.</p>
                    <p>This can be due to API limits, processing delays, or simply no qualifying insider trades.</p>
                    <p><strong>No action taken. Please check again tomorrow.</strong></p>
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
                    "<th>Shares</th><th>Value</th>"
                    "<th>Price @ Trade</th><th>Current</th><th>% Since Trade</th>"
                    "<th>Date</th></tr>"
                )
                for trade in buy_trades[:50]:
                    ticker = trade.get('ticker', 'N/A')
                    company = trade.get('company_name', 'N/A')[:30]
                    trader = trade.get('trader', 'N/A')[:25]
                    shares = trade.get('shares', 'N/A')
                    value = trade.get('value', 'N/A')
                    date = trade.get('filed_date', 'N/A')
                    source = trade.get('source', '')
                    actor_role = trade.get('actor_role', trade.get('title', 'N/A'))
                    actor_type = trade.get('actor_type', 'insider')
                    trade_type = trade.get('trade_type', 'N/A').upper()

                    pat = trade.get('price_at_trade', None)
                    cur = trade.get('current_price', None)
                    pct = trade.get('pct_change_since_trade', None)

                    pat_str = f"{pat:.2f}" if isinstance(pat, (int, float)) else 'N/A'
                    cur_str = f"{cur:.2f}" if isinstance(cur, (int, float)) else 'N/A'
                    pct_str = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else 'N/A'

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
                    "<th>Shares</th><th>Value</th>"
                    "<th>Price @ Trade</th><th>Current</th><th>% Since Trade</th>"
                    "<th>Date</th></tr>"
                )
                for trade in sell_trades[:50]:
                    ticker = trade.get('ticker', 'N/A')
                    company = trade.get('company_name', 'N/A')[:30]
                    trader = trade.get('trader', 'N/A')[:25]
                    shares = trade.get('shares', 'N/A')
                    value = trade.get('value', 'N/A')
                    date = trade.get('filed_date', 'N/A')
                    source = trade.get('source', '')
                    actor_role = trade.get('actor_role', trade.get('title', 'N/A'))
                    actor_type = trade.get('actor_type', 'insider')
                    trade_type = trade.get('trade_type', 'N/A').upper()

                    pat = trade.get('price_at_trade', None)
                    cur = trade.get('current_price', None)
                    pct = trade.get('pct_change_since_trade', None)

                    pat_str = f"{pat:.2f}" if isinstance(pat, (int, float)) else 'N/A'
                    cur_str = f"{cur:.2f}" if isinstance(cur, (int, float)) else 'N/A'
                    pct_str = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else 'N/A'

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
                    <p>Data sources: yfinance insider transactions, SEC EDGAR Form 4.</p>
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
            if EMAIL_CONFIG['sender_email'] == 'YOUR_EMAIL@gmail.com':
                print("⚠️ Email not configured. Skipping send.")
                return False

            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"📊 Insider Trading Report - {datetime.now().strftime('%Y-%m-%d')}"
            msg['From'] = EMAIL_CONFIG['sender_email']
            msg['To'] = EMAIL_CONFIG['recipient_email']

            part = MIMEText(html_content, 'html')
            msg.attach(part)

            with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
                server.starttls()
                server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
                server.send_message(msg)

            print(f"✅ Email sent to {EMAIL_CONFIG['recipient_email']}")
            return True

        except Exception as e:
            print(f"❌ Email error: {str(e)}")
            return False

    def run_scrape(self):
        """Execute full scrape - ONLY REAL DATA."""
        print("\n" + "=" * 80)
        print(f"🌐 INSIDER TRADING SCRAPE - {self.timestamp}")
        print("=" * 80)

        print("\n📥 Fetching insider trading data (last 10 days)...")

        trades = self.fetch_insider_trades_last_10d()

        if len(trades) < 5:
            print("\n📥 Adding SEC EDGAR filings (fallback)...")
            sec_trades = self.fetch_sec_filings_alternative()
            trades.extend(sec_trades)

        if len(trades) == 0:
            print("\n⚠️ No real data available from APIs for last 10 days")

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
