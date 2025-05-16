import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

def analyze_whale_transfers(csv_file="whale_alert_data.csv"):
    
    print(f"Loading data from {csv_file}...")
    
    df = pd.read_csv(csv_file)
    print(f"Loaded {len(df)} transactions")
    
    if 'timestamp' in df.columns and isinstance(df['timestamp'].iloc[0], str):
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    exchanges = [
        'Binance', 'Coinbase', 'Kraken', 'Bitfinex', 'HTX', 'Aave', 'OKX',
        'Bybit', 'KuCoin', 'Coinbase Institutional', 'Bitstamp', 'Crypto.com'
    ]
    
    unknown_sources = df['from_entity'].str.contains('unknown', case=False, na=False)
    
    exchange_destinations = df['to_entity'].apply(
        lambda x: any(exchange.lower() in str(x).lower() for exchange in exchanges)
    )
    
    unknown_to_exchange = unknown_sources & exchange_destinations
    
    filtered_df = df[unknown_to_exchange].copy()
    print(f"Found {len(filtered_df)} transactions from unknown wallets to exchanges")
    
    if len(filtered_df) == 0:
        print("No transactions match the criteria")
        return pd.DataFrame()
    
    symbol_map = {
        'BTC': 'BTCUSDT',
        'ETH': 'ETHUSDT',
        'XRP': 'XRPUSDT',
        'SOL': 'SOLUSDT',
        'USDT': 'BTCUSDT',  # For stablecoins, check BTC as a proxy
        'USDC': 'BTCUSDT'
    }
    
    def get_binance_symbol(currency):
        if currency in symbol_map:
            return symbol_map[currency]
        else:
            return f"{currency}USDT"
    
    def fetch_price_data(symbol, start_time, end_time, interval="1m"):
        try:
            endpoint = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'startTime': int(start_time),
                'endTime': int(end_time),
                'limit': 1000
            }
            
            response = requests.get(endpoint, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                if not data:
                    print(f"No data returned for {symbol}")
                    return None
                
                df = pd.DataFrame(data, columns=[
                    'open_time', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_asset_volume', 'number_of_trades',
                    'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
                ])
                
                df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
                df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
                
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                
                return df
            
            else:
                print(f"Error fetching price data: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"Exception while fetching price data: {e}")
            return None
    
    # Analyze price impact
    results = []
    
    print("Analyzing price impact after whale transfers...")
    for i, row in filtered_df.iterrows():
        try:
            # Get transaction details
            currency = row['currency']
            timestamp = row['timestamp']
            amount = row['amount']
            usd_value = row['usd_value']
            to_entity = row['to_entity']
            
            symbol = get_binance_symbol(currency)
            
            print(f"Analyzing {amount} {currency} transferred to {to_entity} at {timestamp}")
            
            # Calculate time range for price data
            start_time = int((timestamp - timedelta(minutes=0)).timestamp() * 1000)
            end_time = int((timestamp + timedelta(minutes=15)).timestamp() * 1000)
            
            price_data = fetch_price_data(symbol, start_time, end_time)
            
            if price_data is None or len(price_data) == 0:
                print(f"No price data available for {symbol} at {timestamp}")
                continue
            
            price_data['time_diff'] = abs(price_data['open_time'] - timestamp)
            closest_index = price_data['time_diff'].idxmin()
            closest_row = price_data.loc[closest_index]
            price_at_tx = closest_row['open']
            
            after_tx = price_data[price_data['open_time'] >= pd.Timestamp(timestamp)]
            
            if len(after_tx) == 0:
                print(f"No price data available after the transaction time for {symbol}")
                continue
            
            # Find the lowest price in the window after the transaction
            lowest_price = after_tx['low'].min()
            lowest_price_time = after_tx.loc[after_tx['low'].idxmin(), 'open_time']
            
            # Calculate price drop percentage
            price_drop_pct = ((lowest_price - price_at_tx) / price_at_tx) * 100
            minutes_until_lowest = (lowest_price_time - timestamp).total_seconds() / 60
            
            result = {
                'transaction_id': i,
                'currency': currency,
                'amount': amount,
                'usd_value': usd_value,
                'timestamp': timestamp,
                'to_exchange': to_entity,
                'price_at_tx': price_at_tx,
                'lowest_price': lowest_price,
                'minutes_until_lowest': minutes_until_lowest,
                'price_drop_pct': price_drop_pct,
                'price_drop_usd': price_at_tx - lowest_price
            }
            
            results.append(result)
            print(f"Price impact: {price_drop_pct:.2f}% drop within {minutes_until_lowest:.1f} minutes")
            
            time.sleep(0.2)
            
        except Exception as e:
            print(f"Error analyzing transaction {i}: {e}")
            continue
    
    if results:
        results_df = pd.DataFrame(results)
        
        currency_stats = results_df.groupby('currency').agg({
            'price_drop_pct': ['mean', 'min', 'count'],
            'minutes_until_lowest': 'mean'
        })
        
        print("\nPrice Impact Summary by Currency:")
        print(currency_stats)
        
        results_df.to_csv("whale_price_impact.csv", index=False)
        print(f"Saved detailed price impact data to whale_price_impact.csv")
        
        plt.figure(figsize=(10, 6))
        avg_drops = currency_stats['price_drop_pct']['mean'].sort_values()
        avg_drops.plot(kind='barh', color='darkred')
        plt.axvline(x=0, color='black', linestyle='-', alpha=0.3)
        plt.title('Average Price Drop Within 10 Minutes After Whale Transfer', fontsize=14)
        plt.xlabel('Price Drop (%)', fontsize=12)
        plt.ylabel('Currency', fontsize=12)
        plt.grid(axis='x', linestyle='--', alpha=0.7)
        plt.tight_layout()
        plt.savefig('price_drop_by_currency.png')
        
        return results_df
    else:
        print("No valid price impact data was produced")
        return pd.DataFrame()

if __name__ == "__main__":
    result = analyze_whale_transfers()
    
    if len(result) > 0:
        print("\nTop 5 Largest Price Drops:")
        top_drops = result.sort_values('price_drop_pct').head(5)
        for i, row in top_drops.iterrows():
            print(f"{row['currency']}: {row['price_drop_pct']:.2f}% drop after {row['amount']} units transferred to {row['to_exchange']}")
        
        print("\nOverall Statistics:")
        print(f"Average Price Drop: {result['price_drop_pct'].mean():.2f}%")
        print(f"Median Price Drop: {result['price_drop_pct'].median():.2f}%")
        print(f"Average Time to Lowest Price: {result['minutes_until_lowest'].mean():.2f} minutes")