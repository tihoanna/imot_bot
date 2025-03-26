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

# Зареждане на environment variables
load_dotenv()

# Конфигурационни параметри
class Config:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
    CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', 600))
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', 15))
    URLS = os.getenv('URLS', '').split(',')
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15',
        'Mozilla/5.0 (Linux; Android 10; SM-A505FN) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36'
    ]

# Thread-safe колекции
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

    def cleanup_old_entries(self, days=30):
        with self._lock:
            cutoff = datetime.now() - timedelta(days=days)
            to_remove = [k for k, v in self._timestamps.items() if v < cutoff]
            for key in to_remove:
                self._set.discard(key)
                del self._timestamps[key]

seen_links = ThreadSafeSet()
app = Flask(__name__)

# Telegram помощни функции
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

# Дата парсване
def parse_date(date_str):
    try:
        return dateparser.parse(
            date_str,
            languages=['bg'],
            settings={'PREFER_DATES_FROM': 'past'}
        )
    except Exception as e:
        logging.error(f"Грешка при парсване на дата: {e}")
        return None

# Извличане на информация от обява
def extract_ad_info(ad_soup):
    try:
        title = ad_soup.find('h1').get_text(strip=True)
        price = ad_soup.find(class_='price').get_text(strip=True)
        date_str = ad_soup.find(string=re.compile(r'Публикувана|Коригирана'))
        
        return {
            'title': title or "Без заглавие",
            'price': price or "Не е посочена",
            'date': parse_date(date_str) if date_str else None
        }
    except Exception as e:
        logging.error(f"Грешка при извличане на информация: {e}")
        return None

# Мрежови заявки с ротация на User-Agent
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
            time.sleep(2 ** retry)
            return fetch_with_retry(url, retry+1)
        logging.error(f"Грешка при заявка към {url}: {e}")
        return None

# Основна логика за проверка на обяви
def process_url(base_url):
    new_ads = []
    page = 1
    
    while True:
        url = f"{base_url}&p={page}"
        response = fetch_with_retry(url)
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

                ad_soup = BeautifulSoup(ad_response.text, 'html.parser')
                ad_info = extract_ad_info(ad_soup)
                
                if ad_info and ad_info['date'] and ad_info['date'] > datetime.now() - timedelta(days=2):
                    seen_links.add(full_link)
                    new_ads.append({
                        'title': ad_info['title'],
                        'price': ad_info['price'],
                        'link': full_link,
                        'date': ad_info['date'].strftime('%H:%M %d.%m.%Y')
                    })
            except Exception as e:
                logging.error(f"Грешка при обработка на обява: {e}")

        page += 1
        time.sleep(1)
    
    return new_ads

# Фонови задачи
def background_tasks():
    while True:
        try:
            # Ежедневен статус
            if datetime.now().hour == 10 and datetime.now().minute == 0:
                msg = f"✅ Ботът е активен\n{datetime.now().strftime('%d.%m.%Y %H:%M')}\nСледи {len(Config.URLS)} линка."
                send_telegram(msg)
            
            # Почистване на стари линкове
            seen_links.cleanup_old_entries(days=7)
            
            time.sleep(60)
        except Exception as e:
            logging.error(f"Грешка във фонов процес: {e}")

# Flask endpoints
@app.route('/')
def home():
    return "Ботът е активен."

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != Config.WEBHOOK_SECRET:
        return 'Unauthorized', 401

    data = request.json
    if data.get('message', {}).get('text') == '/status':
        status_msg = f"🔄 Активен\nПоследна проверка: {datetime.now().strftime('%H:%M %d.%m.%Y')}"
        send_telegram(status_msg)
    
    return 'OK'

# Главна функция
def main():
    # Стартиране на Flask в отделна нишка
    threading.Thread(target=lambda: app.run(
        host='0.0.0.0',
        port=5000,
        threaded=True
    )).start()

    # Стартиране на фонов процес
    threading.Thread(target=background_tasks, daemon=True).start()

    send_telegram("🚀 Ботът стартира успешно!")
    logging.info("Ботът стартира")

    # Основен цикъл за проверка
    while True:
        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = executor.map(process_url, Config.URLS)
                for ads in results:
                    for ad in ads:
                        msg = f"🏠 <b>{ad['title']}</b>\n💰 {ad['price']}\n📅 {ad['date']}\n🔗 <a href='{ad['link']}'>Виж обявата</a>"
                        send_telegram(msg)
            
            time.sleep(Config.CHECK_INTERVAL)
        except Exception as e:
            logging.critical(f"Критична грешка: {e}\n{traceback.format_exc()}")
            send_telegram(f"❌ Критична грешка: {str(e)}")
            time.sleep(60)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        send_telegram("🛑 Ботът е спрян ръчно")
        sys.exit(0)
    except Exception as e:
        logging.critical(f"Грешка при стартиране: {e}")
        send_telegram(f"🔴 Критична грешка при стартиране: {str(e)}")
        sys.exit(1)
