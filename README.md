# Insider Trading Scraper

Automated insider trading scraper that runs daily and sends email reports with insider trading data from Yahoo Finance and SEC EDGAR.

## Features

- ✅ Automated daily execution at 6 PM CET
- ✅ Scrapes insider trading data from multiple sources
- ✅ Sends formatted HTML email reports
- ✅ Stores data as JSON for analysis
- ✅ Runs on GitHub Actions (free, no computer needed)

## Setup

1. **Fork this repository**
2. **Add GitHub Secrets:**
   - `SENDER_EMAIL` - Your Gmail address
   - `SENDER_PASSWORD` - Your Gmail app password
   - `RECIPIENT_EMAIL` - Email to receive reports

3. **GitHub Actions runs automatically at 6 PM CET daily**

## Data Sources

- Yahoo Finance insider transactions
- SEC EDGAR Form 4 filings
- Fallback sample data when APIs limited

## Files

- `scraper_cloud.py` - Main scraper script
- `.github/workflows/scraper.yml` - GitHub Actions workflow
- `data/insider_trades_data.json` - Collected trade data

## Disclaimer

This tool is for educational purposes only. Not investment advice. All data from public SEC filings. Always do your own research and consult a financial advisor before making investment decisions.

## License

MIT
