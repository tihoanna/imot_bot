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

# Настройки за логване
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('imot_monitor.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Зареждане на .env файл
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
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3o1w&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=5&adv=1j173986902339001'  # Тестова обява
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

    def get_latest(self, count=5):
        with self._lock:
            return list(self._set)[-count:]

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
        response = requests.post(url, data=data, timeout=Config.REQUEST_TIMEOUT)
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
        if not date_str:
            return None
        date_match = re.search(r'(\d{1,2}:\d{2})\s+на\s+(\d{1,2}\s+[а-яА-Я]+,\s+\d{4})', date_str)
        if date_match:
            return dateparser.parse(f"{date_match.group(1)} {date_match.group(2)}", languages=['bg'])
        return dateparser.parse(date_str, languages=['bg'])
    except Exception as e:
        logging.error(f"Parse date error: {e}")
        return None

def extract_ad_info(soup):
    try:
        title = soup.find('h1').get_text(strip=True)
        price_tag = soup.find(class_='price')
        price = price_tag.get_text(strip=True) if price_tag else 'Няма цена'
        info_div = soup.find('div', class_='info')
        date_text = info_div.get_text(strip=True) if info_div else ''
        date = parse_date(date_text)
        return {'title': title, 'price': price, 'date': date}
    except Exception as e:
        logging.error(f"Extract error: {e}")
        return None

def fetch_with_retry(url, retry=0):
    try:
        headers = {
            'User-Agent': random.choice(Config.USER_AGENTS),
            'Accept-Language': 'bg-BG,bg;q=0.9'
        }
        response = requests.get(url, headers=headers, timeout=Config.REQUEST_TIMEOUT)
        response.raise_for_status()
        return response
    except Exception as e:
        if retry < Config.MAX_RETRIES:
            time.sleep(2 ** retry)
            return fetch_with_retry(url, retry+1)
        logging.error(f"Fetch error for {url}: {e}")
        return None

def process_url(url):
    new_ads = []
    response = fetch_with_retry(url)
    if not response:
        return new_ads

    soup = BeautifulSoup(response.text, 'html.parser')
    ad_info = extract_ad_info(soup)
    if ad_info and ad_info['date'] and (datetime.now() - ad_info['date']).days <= 5:
        if url not in seen_links:
            seen_links.add(url)
            new_ads.append({
                'title': ad_info['title'],
                'price': ad_info['price'],
                'link': url,
                'date': ad_info['date'].strftime('%H:%M %d.%m.%Y')
            })
    return new_ads

def background_tasks():
    while True:
        now = datetime.now()
        if now.hour == 10 and now.minute == 0:
            send_telegram(f"✅ Ботът е активен\n🕓 {now.strftime('%d.%m.%Y %H:%M')}\n📝 Обяви: {len(seen_links._set)}")
            seen_links.cleanup_old_entries()
        time.sleep(60)

@app.route('/')
def home():
    return 'IMOT.BG Monitor Active'

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != Config.WEBHOOK_SECRET:
        return 'Unauthorized', 401
    data = request.json
    msg = data.get('message', {}).get('text', '').strip().lower()
    if msg == '/status':
        send_telegram(f"🔄 Статус: Активен\n📝 Обяви: {len(seen_links._set)}")
    elif msg == '/latest':
        last = seen_links.get_latest()
        send_telegram("\n".join(last) if last else "❗ Няма запомнени обяви")
    elif msg == '/checknow':
        send_telegram("🔍 Ръчна проверка стартирана...")
        for url in Config.URLS:
            for ad in process_url(url):
                send_telegram(f"🏠 <b>{ad['title']}</b>\n💰 {ad['price']}\n📅 {ad['date']}\n🔗 {ad['link']}")
    return 'OK'

def main():
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, threaded=True), daemon=True).start()
    threading.Thread(target=background_tasks, daemon=True).start()
    send_telegram("🚀 Мониторингът започна успешно!")
    while True:
        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = executor.map(process_url, Config.URLS)
                for ads in results:
                    for ad in ads:
                        send_telegram(f"🏠 <b>{ad['title']}</b>\n💰 {ad['price']}\n📅 {ad['date']}\n🔗 {ad['link']}")
            time.sleep(Config.CHECK_INTERVAL)
        except Exception as e:
            logging.critical(f"Грешка: {e}\n{traceback.format_exc()}")
            send_telegram(f"❌ Грешка: {str(e)}")
            time.sleep(60)

if __name__ == '__main__':
    main()
