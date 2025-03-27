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

def parse_date(date_str):
    try:
        if not date_str:
            return None
        match = re.search(r'(\d{2}:\d{2})\s+на\s+(\d{1,2}\s+[а-я]+\s+\d{4})', date_str)
        if match:
            time_part, date_part = match.groups()
            return dateparser.parse(f"{time_part} {date_part}", languages=['bg'])
        return dateparser.parse(date_str, languages=['bg'])
    except Exception as e:
        logging.error(f"Грешка при парсване на дата: {e}")
        return None

def extract_ad_info(ad_soup):
    try:
        title_elem = ad_soup.find('h1')
        price_elem = ad_soup.find(class_=re.compile(r'price|amount', re.I))
        date_elem = ad_soup.find(string=re.compile(r'Публикувана|Коригирана|Обновена', re.I))

        return {
            'title': title_elem.get_text(strip=True) if title_elem else "Без заглавие",
            'price': price_elem.get_text(strip=True) if price_elem else "Не е посочена",
            'date': parse_date(date_elem) if date_elem else None
        }
    except Exception as e:
        logging.error(f"Грешка при извличане на информация: {e}")
        return None

def fetch_with_retry(url, retry=0):
    try:
        headers = {
            'User-Agent': random.choice(Config.USER_AGENTS),
            'Accept-Language': 'bg-BG,bg;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://www.imot.bg/'
        }
        response = requests.get(url, headers=headers, timeout=Config.REQUEST_TIMEOUT)
        response.raise_for_status()
        return response
    except Exception as e:
        if retry < Config.MAX_RETRIES:
            delay = 5 * (retry + 1)
            logging.warning(f"Повторен опит {retry+1} за {url} след {delay} сек...")
            time.sleep(delay)
            return fetch_with_retry(url, retry+1)
        logging.error(f"Грешка при заявка към {url}: {e}")
        return None

def process_url(base_url):
    new_ads = []
    page = 1
    max_pages = 5

    while page <= max_pages:
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

                if full_link in seen_links:
                    continue

                ad_response = fetch_with_retry(full_link)
                if not ad_response:
                    continue

                ad_soup = BeautifulSoup(ad_response.text, 'html.parser')
                ad_info = extract_ad_info(ad_soup)

                if ad_info:
                    seen_links.add(full_link)
                    new_ads.append({
                        'title': ad_info['title'],
                        'price': ad_info['price'],
                        'link': full_link,
                        'date': ad_info['date'].strftime('%H:%M %d.%m.%Y') if ad_info['date'] else 'Няма дата'
                    })
            except Exception as e:
                logging.error(f"Грешка при обработка на обява: {e}")

        page += 1
        time.sleep(random.uniform(1, 3))

    return new_ads

def background_tasks():
    while True:
        try:
            now = datetime.now()
            if now.hour == 10 and now.minute == 0:
                status_msg = (
                    f"✅ Ботът е активен\n"
                    f"⌛ Последна проверка: {now.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🔍 Следи {len(Config.URLS)} линка\n"
                    f"📝 Запомнени обяви: {len(seen_links._set)}"
                )
                send_telegram(status_msg)
                seen_links.cleanup_old_entries()
            time.sleep(60)
        except Exception as e:
            logging.error(f"Грешка във фонов процес: {e}")
            time.sleep(300)

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
        latest = seen_links.get_latest(5)
        if latest:
            response = "Последни 5 запомнени обяви:\n" + "\n".join(f"{i+1}. {link}" for i, link in enumerate(latest))
        else:
            response = "Все още няма запомнени обяви."
        send_telegram(response)
    elif message == '/checknow':
        send_telegram("⏳ Започвам ръчна проверка...")
        new_ads = []
        for url in Config.URLS:
            new_ads.extend(process_url(url))
        if new_ads:
            for ad in new_ads:
                msg = (
                    f"🏠 <b>{ad['title']}</b>\n"
                    f"💰 {ad['price']}\n"
                    f"📅 {ad['date']}\n"
                    f"🔗 <a href='{ad['link']}'>Виж обявата</a>"
                )
                send_telegram(msg)
        else:
            send_telegram("ℹ️ Няма намерени нови обяви.")

    return 'OK'

def main():
    flask_thread = threading.Thread(
        target=lambda: app.run(
            host='0.0.0.0',
            port=5000,
            threaded=True,
            use_reloader=False
        ),
        daemon=True
    )
    flask_thread.start()

    threading.Thread(target=background_tasks, daemon=True).start()
    send_telegram("🚀 Мониторингът започна успешно!")
    logging.info("Ботът стартира")

    while True:
        try:
            with ThreadPoolExecutor(max_workers=min(4, len(Config.URLS))) as executor:
                results = executor.map(process_url, Config.URLS)
                for ads in results:
                    for ad in ads:
                        msg = (
                            f"🏠 <b>{ad['title']}</b>\n"
                            f"💰 {ad['price']}\n"
                            f"📅 {ad['date']}\n"
                            f"🔗 <a href='{ad['link']}'>Виж обявата</a>"
                        )
                        send_telegram(msg)
            time.sleep(Config.CHECK_INTERVAL)
        except KeyboardInterrupt:
            send_telegram("🛑 Ботът е спрян ръчно")
            sys.exit(0)
        except Exception as e:
            logging.critical(f"Критична грешка: {e}\n{traceback.format_exc()}")
            send_telegram(f"❌ Критична грешка: {str(e)}")
            time.sleep(60)

if __name__ == '__main__':
    main()