# crypto_whale_flow_bot

It's a Python project that combines **whale alert scraping**, **transaction analysis**, and an **automated trading bot** to act on large crypto transfers.

---

## Overview

This repo consists of three main components:

1. **Whale Alert Scraper**  
   Uses Selenium with a headless Firefox browser to scrape large crypto transaction alerts (whale alerts) from [Nitter's Whale Alert feed](https://nitter.net/whale_alert). It filters and extracts relevant data like transfer amounts, coins, and destination exchanges.

2. **Whale Transfer Analyzer**  
   Processes the scraped whale transfer data from CSV files, filters transfers from unknown wallets to exchanges, and analyzes short-term price impact using Binance's public API. This helps understand how whale movements affect price action in the minutes following a transfer.

3. **Automated Trading Bot**  
   Uses Binance Futures API to open short positions on selected symbols when a qualifying whale transfer is detected. The bot places market orders with preset take-profit (TP) and stop-loss (SL) percentages and manages open positions. It is designed to be simple and effective, without optimizing TP/SL parameters yet.

---

## Features

- Scrapes large whale transfer alerts in real-time.
- Analyzes price impact of whale transfers within a 15-minute window.
- Automatically places leveraged short trades on Binance Futures based on whale flows.
- Logs activity and errors for monitoring.

---

## Requirements

- Python 3.8+
- `pandas`, `numpy`, `requests`, `matplotlib`
- `selenium` and Firefox GeckoDriver for scraping
- Binance Futures API key and secret
- Internet connection for API calls and scraping

---

## Usage

1. Run the scraper to collect whale alert data.
2. Use the analyzer script to evaluate price impact from saved CSV data.
3. Run the trading bot to automate trades based on live whale alert signals.

---

## Notes

- This is a project which combine data scraping, analysis, and automated trading.
- TP and SL values are fixed in the config and not yet optimized.

---

## License

MIT License

---

## Author

Abhinav V

