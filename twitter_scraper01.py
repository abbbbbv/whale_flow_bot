import time
import re
import logging
import pandas as pd
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("whale_alert_scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

class WhaleAlertScraper:
    def __init__(self, headless=True, wait_time=10):
        self.options = Options()
        if headless:
            self.options.add_argument("--headless")
        
        # Initialize the driver
        self.driver = None
        self.base_url = "https://nitter.net/whale_alert"
        self.wait_time = wait_time  # Default wait time in seconds
        
    def start_driver(self):
        """Start the Firefox driver with geckodriver."""
        self.driver = webdriver.Firefox(options=self.options)
        self.driver.set_page_load_timeout(30)
        
    def close_driver(self):
        """Close the driver."""
        if self.driver:
            self.driver.quit()
            
    def parse_tweet_text(self, text):
        """Parse the tweet text to extract transaction details."""
        # Regular expression patterns to extract information
        amount_pattern = r'([\d,]+(?:\.\d+)?)\s+#([A-Za-z0-9]+)'
        usd_pattern = r'$$([\d,]+(?:\.\d+)?)\s+USD$$'
        from_to_pattern = r'from\s+#([A-Za-z0-9]+)\s+to\s+#([A-Za-z0-9]+)'
        unknown_wallet_pattern = r'(from|to)\s+(unknown wallet)'
        from_pattern = r'from\s+([A-Za-z0-9 ]+)\s+to'
        to_pattern = r'to\s+([A-Za-z0-9 ]+)'
        
        # Extract the cryptocurrency amount and symbol
        amount_matches = re.findall(amount_pattern, text)
        if not amount_matches:
            logger.warning(f"Could not extract amount from tweet: {text[:100]}...")
            return None
            
        amount, currency = amount_matches[0]
        amount = float(amount.replace(',', ''))
        
        # Extract USD value
        usd_match = re.search(usd_pattern, text)
        usd_value = float(usd_match.group(1).replace(',', '')) if usd_match else None
        
        # Extract from/to information
        from_entity = "unknown"
        to_entity = "unknown"
        
        # Check for exchange to exchange transfers
        from_to_match = re.search(from_to_pattern, text)
        if from_to_match:
            from_entity = from_to_match.group(1)
            to_entity = from_to_match.group(2)
        else:
            # Check for unknown wallet transfers
            unknown_match = re.search(unknown_wallet_pattern, text)
            if unknown_match:
                direction = unknown_match.group(1)
                if direction == "from":
                    from_entity = "unknown wallet"
                    # Try to find the destination
                    to_match = re.search(r'to\s+#([A-Za-z0-9]+)', text)
                    if to_match:
                        to_entity = to_match.group(1)
                else:  # direction == "to"
                    to_entity = "unknown wallet"
                    # Try to find the source
                    from_match = re.search(r'from\s+#([A-Za-z0-9]+)', text)
                    if from_match:
                        from_entity = from_match.group(1)
            else:
                from_match = re.search(from_pattern, text)
                if from_match:
                    from_entity = from_match.group(1).strip()
                    if from_entity.endswith('#'):
                        from_entity = from_entity[:-1].strip()
                
                to_match = re.search(to_pattern, text)
                if to_match:
                    to_entity = to_match.group(1).strip()
                    if to_entity.endswith('#'):
                        to_entity = to_entity[:-1].strip()
        
        return {
            "amount": amount,
            "currency": currency,
            "usd_value": usd_value,
            "from_entity": from_entity,
            "to_entity": to_entity,
            "raw_text": text
        }
    
    def format_timestamp(self, timestamp_text):
        try:
            return datetime.strptime(timestamp_text, "%d %b %Y, %H:%M:%S")
        except ValueError:
            try:
                if "·" in timestamp_text:
                    parts = timestamp_text.split("·")
                    date_part = parts[0].strip()
                    time_part = parts[1].strip().replace(" UTC", "")
                    
                    combined = f"{date_part} {time_part}"
                    return pd.to_datetime(combined)
                
                # Try to parse relative timestamps like "2 hours ago"
                elif "ago" in timestamp_text or "m" in timestamp_text or "h" in timestamp_text:
                    # Rough estimate based on the text
                    now = datetime.now()
                    if "minute" in timestamp_text or "m" in timestamp_text:
                        minutes = int(re.search(r'(\d+)', timestamp_text).group(1))
                        return now - pd.Timedelta(minutes=minutes)
                    elif "hour" in timestamp_text or "h" in timestamp_text:
                        hours = int(re.search(r'(\d+)', timestamp_text).group(1))
                        return now - pd.Timedelta(hours=hours)
                    elif "day" in timestamp_text:
                        days = int(re.search(r'(\d+)', timestamp_text).group(1))
                        return now - pd.Timedelta(days=days)
                    else:
                        return now
                else:
                    return pd.to_datetime(timestamp_text)
            except Exception as e:
                logger.warning(f"Could not parse timestamp: {timestamp_text}. Error: {e}")
                return None
    
    def get_tweet_timestamp(self, tweet_element):
        try:
            timestamp_element = tweet_element.find_element(By.CSS_SELECTOR, ".tweet-date a")
            
            timestamp_text = timestamp_element.get_attribute("title")
            
            if not timestamp_text:
                timestamp_text = timestamp_element.text
                
            formatted_timestamp = self.format_timestamp(timestamp_text)
            return timestamp_text, formatted_timestamp
            
        except Exception as e:
            logger.warning(f"Error getting timestamp from tweet: {e}")
            return None, None
            
    def is_valid_tweet(self, tweet):
        try:
            class_attr = tweet.get_attribute("class")
            return class_attr == "timeline-item " and len(class_attr.strip()) > 0
        except (NoSuchElementException, StaleElementReferenceException):
            return False
    
    def process_tweet(self, tweet):
        try:
            if not self.is_valid_tweet(tweet):
                return None
                
            try:
                tweet_text_element = tweet.find_element(By.CSS_SELECTOR, ".tweet-content")
                tweet_text = tweet_text_element.text
            except NoSuchElementException:
                logger.warning("Tweet content not found, skipping")
                return None
            
            timestamp_text, formatted_timestamp = self.get_tweet_timestamp(tweet)
            
            try:
                tweet_link_element = tweet.find_element(By.CSS_SELECTOR, ".tweet-link")
                tweet_link = tweet_link_element.get_attribute("href")
            except NoSuchElementException:
                tweet_link = None
                logger.warning("Tweet link not found")
            
            transaction_indicators = ["🚨", "🔓", "🔒", "🔥", "#BTC", "#ETH", "#USDT", "#USDC", "#XRP"]
            is_transaction = any(indicator in tweet_text for indicator in transaction_indicators)
            
            if not is_transaction:
                logger.info(f"Skipping non-transaction tweet: {tweet_text[:50]}...")
                return None
            
            parsed_data = self.parse_tweet_text(tweet_text)
            
            if parsed_data:
                # Add the timestamp and URL
                parsed_data["timestamp_text"] = timestamp_text
                parsed_data["timestamp"] = formatted_timestamp
                parsed_data["tweet_link"] = tweet_link
                
                return parsed_data
            
            return None
            
        except Exception as e:
            logger.error(f"Error processing tweet: {e}")
            return None
    
    def scrape_tweets(self, count=100, max_pages=10):
       
        if not self.driver:
            self.start_driver()
            
        tweets_data = []
        current_page = 1
        current_url = self.base_url
        
        try:
            logger.info(f"Starting to scrape up to {count} tweets...")
            
            # Initial page load
            self.driver.get(current_url)
            logger.info(f"Loaded initial page: {current_url}")
            
            wait = WebDriverWait(self.driver, self.wait_time)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".timeline-item")))
            
            while len(tweets_data) < count and current_page <= max_pages:
                logger.info(f"Processing page {current_page}...")
                
                tweets = self.driver.find_elements(By.CSS_SELECTOR, ".timeline-item")
                
                valid_tweets = []
                for t in tweets:
                    try:
                        class_attr = t.get_attribute("class")
                        if class_attr == "timeline-item ":
                            valid_tweets.append(t)
                    except:
                        continue
                
                logger.info(f"Found {len(valid_tweets)} tweets on page {current_page}")
                
                # Process tweets on this page
                for i, tweet in enumerate(valid_tweets):
                    if len(tweets_data) >= count:
                        break
                        
                    try:
                        # Process the tweet
                        parsed_data = self.process_tweet(tweet)
                        
                        if parsed_data:
                            tweets_data.append(parsed_data)
                            logger.info(f"Processed tweet {len(tweets_data)}/{count}: {parsed_data['raw_text'][:50]}...")
                    except Exception as e:
                        logger.error(f"Error processing tweet on page {current_page}: {e}")
                
                # Check if we have enough tweets
                if len(tweets_data) >= count:
                    logger.info(f"Reached the requested count of {count} tweets")
                    break
                
                # Look for the "Load more" button
                try:
                    load_more_elements = self.driver.find_elements(By.CSS_SELECTOR, ".show-more a")
                    
                    load_more_link = None
                    for element in load_more_elements:
                        if element.text == "Load more":
                            load_more_link = element
                            break
                    
                    if not load_more_link:
                        logger.warning("No 'Load more' button found, ending pagination")
                        break
                    
                    next_url = load_more_link.get_attribute("href")
                    logger.info(f"Found 'Load more' button linking to: {next_url}")
                    
                    # Navigate to the next page
                    self.driver.get(next_url)
                    current_url = next_url
                    current_page += 1
                    
                    # Wait for the new page to load
                    time.sleep(3)
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".timeline-item")))
                    
                except NoSuchElementException:
                    logger.warning("No 'Load more' button found, ending pagination")
                    break
                except Exception as e:
                    logger.error(f"Error while navigating to next page: {e}")
                    break
        
        except Exception as e:
            logger.error(f"Error during scraping: {e}")
        
        return tweets_data
        
    def save_to_csv(self, tweets_data, filename="whale_alert_data.csv"):
        """Save the scraped data to a CSV file."""
        if not tweets_data:
            logger.warning("No data to save")
            return None
            
        df = pd.DataFrame(tweets_data)
        df.to_csv(filename, index=False)
        logger.info(f"Data saved to {filename}")
        
        return df

    def save_to_excel(self, tweets_data, filename="whale_alert_data.xlsx"):
        """Save the scraped data to an Excel file."""
        if not tweets_data:
            logger.warning("No data to save")
            return None
        
        try:
            import openpyxl
            df = pd.DataFrame(tweets_data)
            df.to_excel(filename, index=False)
            logger.info(f"Data saved to {filename}")
            return df
        except ImportError:
            logger.warning("openpyxl not installed. Install with: pip install openpyxl")
            logger.info("Saving as CSV instead.")
            return self.save_to_csv(tweets_data, filename.replace('.xlsx', '.csv'))


def main():
    # Create the scraper
    scraper = WhaleAlertScraper(headless=False, wait_time=15)  # Set to True for headless mode
    
    try:
        # Scrape 100 tweets
        tweets_data = scraper.scrape_tweets(count=2000, max_pages=100)
        
        # Save the data
        if tweets_data:
            df = scraper.save_to_csv(tweets_data)
            
            try:
                scraper.save_to_excel(tweets_data)
            except Exception as e:
                logger.error(f"Error saving to Excel: {e}")
            
            logger.info(f"Successfully scraped {len(tweets_data)} tweets")
            
            # Display some basic analysis
            print("\nCurrencies mentioned:")
            print(df['currency'].value_counts())
            
            print("\nMost common from/to entities:")
            print(pd.concat([df['from_entity'], df['to_entity']]).value_counts().head(10))
            
            if 'usd_value' in df.columns and not df['usd_value'].isna().all():
                print("\nTotal USD value by currency:")
                print(df.groupby('currency')['usd_value'].sum().sort_values(ascending=False))
        else:
            logger.warning("No data was scraped")
    
    except Exception as e:
        logger.error(f"An error occurred in the main function: {e}")
    
    finally:
        # Clean up
        scraper.close_driver()


if __name__ == "__main__":
    main()