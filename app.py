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
import random
from urllib.parse import urljoin, urlparse, parse_qs

# Логване
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
    REQUEST_TIMEOUT = 30
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

    def add(self, item):
        with self._lock:
            self._set.add(item)

    def __contains__(self, item):
        with self._lock:
            return item in self._set

    def get_latest(self, count=5):
        with self._lock:
            return list(self._set)[-count:]

seen_ids = ThreadSafeSet()
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
        response = requests.post(url, data=data, timeout=Config.REQUEST_TIMEOUT)
        response.raise_for_status()
        return True
    except Exception as e:
        if retry < Config.MAX_RETRIES:
            time.sleep(2 ** retry)
            return send_telegram(message, retry+1)
        logging.error(f"Telegram error: {e}")
        return False

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

def extract_id(link):
    match = re.search(r'adv=([\w\d]+)', link)
    return match.group(1) if match else None

def process_url(base_url):
    new_ads = []
    page = 1

    while True:
        url = f"{base_url}&p={page}" if page > 1 else base_url
        response = fetch_with_retry(url)
        if not response:
            break

        soup = BeautifulSoup(response.text, 'html.parser')
        ads = soup.select('table.tblOffers tr:has(a[href*="/p/"])')
        if not ads:
            break

        for ad in ads:
            try:
                link_tag = ad.select_one('a[href*="/p/"]')
                if not link_tag:
                    continue
                relative_link = link_tag['href']
                full_link = urljoin('https://www.imot.bg', relative_link)
                adv_id = extract_id(full_link)
                if not adv_id or adv_id in seen_ids:
                    continue
                seen_ids.add(adv_id)

                title = link_tag.get_text(strip=True)
                price_tag = ad.find(string=re.compile(r'EUR'))
                price = price_tag.strip() if price_tag else 'Цена неизвестна'

                new_ads.append({
                    'title': title,
                    'price': price,
                    'link': full_link
                })
            except Exception as e:
                logging.error(f"Ad error: {e}")

        page += 1
        time.sleep(1)
    return new_ads

@app.route('/')
def home():
    return "IMOT.BG Monitor Active"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != Config.WEBHOOK_SECRET:
        return 'Unauthorized', 401

    data = request.json
    message = data.get('message', {}).get('text', '').strip().lower()

    if message == '/status':
        send_telegram("Ботът е активен и работи!")
    elif message == '/checknow':
        new_ads = []
        for url in Config.URLS:
            new_ads.extend(process_url(url))
        if new_ads:
            for ad in new_ads:
                send_telegram(f"🏠 <b>{ad['title']}</b>\n💰 {ad['price']}\n🔗 <a href='{ad['link']}'>Линк</a>")
        else:
            send_telegram("Няма намерени нови обяви.")
    elif message == '/latest':
        latest = seen_ids.get_latest(5)
        if latest:
            send_telegram("Последни ID-та: " + ', '.join(latest))
        else:
            send_telegram("Все още няма събрани обяви.")

    return 'OK'

def main():
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000)).start()
    send_telegram("Мониторингът стартира успешно!")

    while True:
        try:
            with ThreadPoolExecutor() as executor:
                results = executor.map(process_url, Config.URLS)
                for ads in results:
                    for ad in ads:
                        msg = f"🏠 <b>{ad['title']}</b>\n💰 {ad['price']}\n🔗 <a href='{ad['link']}'>Линк</a>"
                        send_telegram(msg)
            time.sleep(Config.CHECK_INTERVAL)
        except Exception as e:
            logging.error(f"Main loop error: {e}\n{traceback.format_exc()}")
            time.sleep(60)

if __name__ == '__main__':
    main()
