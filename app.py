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
from urllib.parse import urljoin

# Логване
logging.basicConfig(
    level=logging.DEBUG,
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
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
        'Mozilla/5.0 (Linux; Android 10; SM-A505FN)'
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

    def get_latest(self, count=5):
        with self._lock:
            return list(self._set)[-count:]

seen_links = ThreadSafeSet()
app = Flask(__name__)

def send_telegram(message, retry=0):
    if not Config.TELEGRAM_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logging.warning("Липсват Telegram credentials")
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
        logging.error(f"Грешка при изпращане към Telegram: {e}")
        return False

def fetch_with_retry(url, retry=0):
    try:
        headers = {
            'User-Agent': random.choice(Config.USER_AGENTS),
            'Accept-Language': 'bg-BG,bg;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        response = requests.get(url, headers=headers, timeout=Config.REQUEST_TIMEOUT)
        response.raise_for_status()
        return response
    except Exception as e:
        if retry < Config.MAX_RETRIES:
            time.sleep(5)
            return fetch_with_retry(url, retry+1)
        logging.error(f"Грешка при заявка към {url}: {e}")
        return None

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
        status_msg = (
            f"🔄 Статус: Активен\n"
            f"⌛ Последна проверка: {datetime.now().strftime('%H:%M %d.%m.%Y')}\n"
            f"🔍 Следи {len(Config.URLS)} линка\n"
            f"📝 Запомнени обяви: {len(seen_links._set)}"
        )
        send_telegram(status_msg)

    elif message == '/latest':
        send_telegram("⏳ Зареждам последните обяви от всички линкове...")
        latest_ads = []
        for url in Config.URLS:
            response = fetch_with_retry(url)
            if not response:
                continue
            soup = BeautifulSoup(response.text, 'html.parser')
            ads = soup.select('table.tblOffers tr:has(a[href*="/p/"])')[:5]
            for ad in ads:
                try:
                    link_tag = ad.select_one('a[href*="/p/"]')
                    if not link_tag:
                        continue
                    relative_link = link_tag['href']
                    full_link = urljoin('https://www.imot.bg', relative_link)
                    latest_ads.append(full_link)
                except Exception as e:
                    logging.error(f"Грешка при latest: {e}")

        if latest_ads:
            send_telegram("📌 Последни 5 обяви от всеки линк:\n" + "\n".join(latest_ads))
        else:
            send_telegram("ℹ️ Няма открити обяви.")

    return 'OK'

def main():
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, use_reloader=False), daemon=True).start()
    send_telegram("🚀 Мониторингът започна успешно!")
    while True:
        time.sleep(Config.CHECK_INTERVAL)

if __name__ == '__main__':
    main()
