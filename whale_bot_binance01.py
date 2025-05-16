import os, re, time, math, logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any

import pandas as pd
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By

from binance.um_futures import UMFutures
from binance.error       import ClientError

API_KEY    = "YOUR_BINANCE_API_KEY"
API_SECRET = "YOUR_BINANCE_SECRET"

MIN_NOTIONAL_USD = 50_000_000      
ACCOUNT_RISK     = 0.050           # risk ≤50% equity per trade
CHECK_INTERVAL   = 10             
WH_ALERT_URL     = "https://nitter.net/whale_alert"

PAIR_CFG : Dict[str, Dict[str,Any]] = {
    # symbol  :  tp%   sl%   lev   max_usd
    "XRPUSDT":   {"tp":0.35,"sl":0.15,"lev":5,"usd":15_000},
    "DOGEUSDT":  {"tp":0.60,"sl":0.25,"lev":3,"usd":10_000},
    "TRUMPUSDT": {"tp":0.60,"sl":0.25,"lev":3,"usd": 5_000},
    "SOLUSDT":   {"tp":0.35,"sl":0.15,"lev":5,"usd":15_000},
    "LTCUSDT":   {"tp":0.35,"sl":0.15,"lev":5,"usd":12_000},
}

VALID_EXCHANGES = r"#(Binance|Coinbase|Bybit|Kraken|OKX|HTX)"

logging.basicConfig(level=logging.INFO,
        format="%(asctime)s - %(levelname)s: %(message)s",
        handlers=[logging.FileHandler("whale_flow_bot.log"),
                  logging.StreamHandler()])
log = logging.getLogger("WhaleFlowBot")

client = UMFutures(key=API_KEY, secret=API_SECRET)

def get_precision(symbol:str):
    info = client.exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            qty_prec   = int(s['quantityPrecision'])
            price_prec = int(s['pricePrecision'])
            step       = float([f for f in s['filters'] if f['filterType']=="LOT_SIZE"][0]['stepSize'])
            tick       = float([f for f in s['filters'] if f['filterType']=="PRICE_FILTER"][0]['tickSize'])
            return qty_prec, price_prec, step, tick
    raise ValueError(f"Symbol {symbol} not found in exchangeInfo")

def round_step(val, step):
    return math.floor(val / step) * step

def place_with_retry(params, max_retries=3):
    for attempt in range(max_retries):
        try:
            return client.new_order(**params)
        except Exception as e:
            backoff = 2 ** attempt
            log.warning(f"Order attempt {attempt+1} failed: {e}. Retry in {backoff}s")
            time.sleep(backoff)
    log.error(f"All retries failed for order: {params}")
    return None

def position_open(symbol):
    try:
        for p in client.account()['positions']:
            if p['symbol']==symbol and float(p['positionAmt'])!=0:
                return True
    except ClientError as e:
        log.error(f"account() error: {e}")
    return False

def cancel_open_orders(symbol):
    try: client.cancel_open_orders(symbol=symbol)
    except ClientError as e: log.warning(f"Cancel orders error: {e}")

OPEN_POS = {}   # symbol → {qty, entry, tp_id, sl_id}

def short_perp(symbol, cfg):
    if position_open(symbol):
        log.info(f"Position already open on {symbol}")
        return
    cancel_open_orders(symbol)

    # leverage
    try: client.change_leverage(symbol=symbol, leverage=cfg['lev'])
    except ClientError as e: log.warning(f"Leverage set error: {e}")

    qty_prec, price_prec, step, tick = get_precision(symbol)
    mark_price = float(client.mark_price(symbol=symbol)['markPrice'])
    bal        = float(client.balance(asset="USDT")[0]['balance'])

    notional_cap = min(cfg['usd'], bal*ACCOUNT_RISK*cfg['lev'])
    qty = round_step(notional_cap / mark_price, step)
    if qty==0:
        log.warning(f"Qty rounds to 0 for {symbol}. Skip.")
        return

    res = place_with_retry({
        "symbol": symbol,
        "side":   "SELL",
        "type":   "MARKET",
        "quantity": qty
    })
    if not res: return
    entry = float(res.get('avgPrice') or mark_price)

    tp_price = round(entry*(1-cfg['tp']/100), price_prec)
    sl_price = round(entry*(1+cfg['sl']/100), price_prec)

    place_with_retry({
        "symbol": symbol,
        "side":   "BUY",
        "type":   "TAKE_PROFIT_MARKET",
        "stopPrice": tp_price,
        "closePosition": True,
        "workingType": "CONTRACT_PRICE"   # to avoid dual trigger rules
    })

    place_with_retry({
        "symbol": symbol,
        "side":   "BUY",
        "type":   "STOP_MARKET",
        "stopPrice": sl_price,
        "closePosition": True,
        "workingType": "CONTRACT_PRICE"
    })

    OPEN_POS[symbol] = {'qty':qty,'time':time.time()}
    log.info(f"Opened SHORT {symbol} qty={qty} entry={entry}, TP={tp_price}, SL={sl_price}")

#  SELENIUM TWEET SCRAPER
opt = Options(); opt.add_argument("--headless")
driver = webdriver.Firefox(options=opt)
driver.set_page_load_timeout(30)

last_id = None
amount_re = re.compile(r'([\d,]+(?:\.\d+)?)\s+#([A-Z0-9]+)')
usd_re    = re.compile(r'\$([\d,]+(?:\.\d+)?)\s+USD', re.I)
wallet_to_cex = re.compile(r'unknown wallet.*?to\s+' + VALID_EXCHANGES, re.I)

def fetch_latest_tweet():
    global last_id
    driver.get(WH_ALERT_URL)
    first = driver.find_elements(By.CSS_SELECTOR, ".timeline-item")[0]
    tid   = first.get_attribute("data-id")
    if tid==last_id: return None
    last_id = tid
    return first.text

def parse_tweet(txt):
    if not wallet_to_cex.search(txt): return None
    amt_m = amount_re.search(txt); usd_m = usd_re.search(txt)
    if not amt_m: return None
    amount, coin = amt_m.groups()
    usd_val = float(usd_m.group(1).replace(',','')) if usd_m else 0
    return dict(coin=coin.upper(), usd=usd_val)

log.info("Whale flow bot started.")
try:
    while True:
        try:
            t = fetch_latest_tweet()
            if t:
                info = parse_tweet(t)
                if info and info['usd']>=MIN_NOTIONAL_USD:
                    sym = info['coin'] + "USDT"
                    if sym in PAIR_CFG:
                        log.info(f"Signal: {info['coin']} → CEX  (${info['usd']:,})")
                        short_perp(sym, PAIR_CFG[sym])
                    else:
                        log.info(f"{sym} not in config list.")
        except Exception as e:
            log.error(f"Loop err: {e}")
        time.sleep(CHECK_INTERVAL)
except KeyboardInterrupt:
    pass
finally:
    driver.quit()
    log.info("Bot stopped.")