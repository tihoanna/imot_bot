import os
import sys
import re
import requests
from bs4 import BeautifulSoup
import time
import logging
from datetime import datetime, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from flask import Flask, request
import traceback
import dateparser
import random

# Конфигурация на logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('imot_monitor.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

load_dotenv()

class Config:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    CHECK_INTERVAL = 600
    MAX_RETRIES = 3
    REQUEST_TIMEOUT = 15
    URLS = [
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nqa&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nye&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nz2&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3o1w&f1=1'
    ]
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15',
        'Mozilla/5.0 (Linux; Android 10; SM-A505FN) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36'
    ]

class ThreadSafeSet:
    def __init__(self):
        self._set = set()
        self._lock = threading.Lock()
        self._timestamps = {}

    def add(self, item):
        with self._lock:
            self._set.add(item)
            self._timestamps[item] = datetime.now()

    def __contains__(self, item):
        with self._lock:
            return item in self._set

    def cleanup_old_entries(self, days=7):
        with self._lock:
            cutoff = datetime.now() - timedelta(days=days)
            to_remove = [k for k, v in self._timestamps.items() if v < cutoff]
            for key in to_remove:
                self._set.discard(key)
                del self._timestamps[key]

seen_links = ThreadSafeSet()
app = Flask(__name__)

def send_telegram(message, retry=0):
    if not Config.TELEGRAM_TOKEN or not Config.TELEGRAM_CHAT_ID:
        return False

    try:
        url = f'https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage'
        data = {
            'chat_id': Config.TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }
        response = requests.post(url, data=data, timeout=15)
        response.raise_for_status()
        return True
    except Exception as e:
        if retry < Config.MAX_RETRIES:
            time.sleep(2 ** retry)
            return send_telegram(message, retry+1)
        logging.error(f"Telegram error: {e}")
        return False

def parse_date(date_str):
    try:
        return dateparser.parse(
            date_str,
            languages=['bg'],
            settings={'PREFER_DATES_FROM': 'past'}
        )
    except Exception:
        return None

def extract_ad_info(ad_soup):
    try:
        return {
            'title': ad_soup.find('h1').get_text(strip=True),
            'price': ad_soup.find(class_='price').get_text(strip=True),
            'date': parse_date(ad_soup.find(string=re.compile(r'Публикувана|Коригирана')))
        }
    except Exception as e:
        logging.error(f"Extract error: {e}")
        return None

def fetch_with_retry(url):
    for retry in range(Config.MAX_RETRIES):
        try:
            headers = {'User-Agent': random.choice(Config.USER_AGENTS)}
            response = requests.get(url, headers=headers, timeout=Config.REQUEST_TIMEOUT)
            response.raise_for_status()
            return response
        except Exception:
            if retry < Config.MAX_RETRIES - 1:
                time.sleep(2 ** retry)
    return None

def process_url(base_url):
    new_ads = []
    page = 1
    
    while True:
        response = fetch_with_retry(f"{base_url}&p={page}")
        if not response:
            break

        soup = BeautifulSoup(response.text, 'html.parser')
        ads = soup.select('div.content > table > tr:has(.photo)')
        if not ads:
            break

        for ad in ads:
            try:
                link = ad.select_one('a.ver15hl')['href']
                full_link = f"https://www.imot.bg{link}"
                
                if full_link in seen_links:
                    continue

                ad_response = fetch_with_retry(full_link)
                if not ad_response:
                    continue

                ad_info = extract_ad_info(BeautifulSoup(ad_response.text, 'html.parser'))
                if ad_info and ad_info['date'] and (datetime.now() - ad_info['date']).days <= 2:
                    seen_links.add(full_link)
                    new_ads.append({
                        'title': ad_info['title'],
                        'price': ad_info['price'],
                        'link': full_link,
                        'date': ad_info['date'].strftime('%H:%M %d.%m.%Y')
                    })
            except Exception as e:
                logging.error(f"Ad process error: {e}")

        page += 1
        time.sleep(1)
    
    return new_ads

def background_tasks():
    while True:
        try:
            if datetime.now().hour == 10 and datetime.now().minute == 0:
                send_telegram(f"✅ Ботът работи нормално\n{datetime.now().strftime('%d.%m.%Y %H:%M')}")
            seen_links.cleanup_old_entries()
            time.sleep(60)
        except Exception as e:
            logging.error(f"Background task error: {e}")

@app.route('/')
def home():
    return "IMOT.BG Monitor Active"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != Config.WEBHOOK_SECRET:
        return 'Unauthorized', 401
    
    data = request.json
    if data.get('message', {}).get('text') == '/status':
        send_telegram(f"🔄 Статус: Активен\nПоследна проверка: {datetime.now().strftime('%H:%M %d.%m.%Y')}")
    
    return 'OK'

def main():
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000)).start()
    threading.Thread(target=background_tasks, daemon=True).start()
    
    send_telegram("🚀 Мониторингът започна успешно!")
    
    while True:
        try:
            with ThreadPoolExecutor() as executor:
                results = executor.map(process_url, Config.URLS)
                for ads in results:
                    for ad in ads:
                        message = f"🏠 <b>{ad['title']}</b>\n💰 {ad['price']}\n📅 {ad['date']}\n🔗 <a href='{ad['link']}'>Линк</a>"
                        send_telegram(message)
            time.sleep(Config.CHECK_INTERVAL)
        except Exception as e:
            logging.critical(f"Critical error: {str(e)}")
            send_telegram(f"❌ Грешка: {str(e)}")
            time.sleep(60)

if __name__ == '__main__':
    main()
