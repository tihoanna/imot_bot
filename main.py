import os
import sys
import re
import requests
from bs4 import BeautifulSoup
import time
import logging
from datetime import datetime, timedelta
import threading
from dotenv import load_dotenv
from flask import Flask, request
import traceback

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
    CHECK_INTERVAL = 600  # 10 минути
    MAX_RETRIES = 3
    REQUEST_TIMEOUT = 15
    URLS = [
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nqa&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nye&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nz2&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3o1w&f1=1',
    ]
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'bg-BG,bg;q=0.9,en-US;q=0.8,en;q=0.7'
    }

# Thread-safe колекции
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

seen_links = ThreadSafeSet()
app = Flask(__name__)

# Telegram изпращане

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
            time.sleep(2)
            return send_telegram(message, retry+1)
        logging.error(f"Грешка при изпращане към Telegram: {e}")
        return False

# Дата парсване и извличане

def parse_date(date_str):
    try:
        match = re.search(r'(\d{2}):(\d{2})\s+на\s+(\d{2})\s+([а-яА-Я]+),\s+(\d{4})', date_str)
        if match:
            hour, minute, day, month_bg, year = match.groups()
            bg_months = {
                'януари': '01', 'февруари': '02', 'март': '03', 'април': '04',
                'май': '05', 'юни': '06', 'юли': '07', 'август': '08',
                'септември': '09', 'октомври': '10', 'ноември': '11', 'декември': '12'
            }
            month = bg_months.get(month_bg.lower(), '01')
            return datetime.strptime(f"{day}.{month}.{year} {hour}:{minute}", "%d.%m.%Y %H:%M")
    except Exception:
        return None
    return None

def extract_ad_info(ad_soup):
    try:
        title_tag = ad_soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Без заглавие"
        price_tag = ad_soup.find(class_='price')
        price = price_tag.get_text(strip=True) if price_tag else "Не е посочена"

        time_tag = ad_soup.find(string=lambda text: text and ("Публикувана" in text or "Коригирана" in text))
        date = parse_date(time_tag) if time_tag else None

        return {'title': title, 'price': price, 'date': date}
    except Exception as e:
        logging.error(f"Грешка при извличане на информация: {e}")
        return None

# Основна логика

def fetch_with_retry(url, retry=0):
    try:
        response = requests.get(url, headers=Config.HEADERS, timeout=Config.REQUEST_TIMEOUT)
        response.raise_for_status()
        return response
    except Exception as e:
        if retry < Config.MAX_RETRIES:
            time.sleep(2)
            return fetch_with_retry(url, retry+1)
        logging.error(f"Грешка при заявка към {url}: {e}")
        return None

def check_listings():
    new_ads = []
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    for base_url in Config.URLS:
        page = 1
        while True:
            url = f"{base_url}&p={page}"
            response = fetch_with_retry(url)
            if not response:
                break

            soup = BeautifulSoup(response.text, 'html.parser')
            ads = soup.select('tr.odd, tr.even')
            if not ads:
                break

            stop_processing = False
            for ad in ads:
                link_tag = ad.select_one('td:nth-child(3) .bold a')
                if not link_tag or 'href' not in link_tag.attrs:
                    continue

                relative_link = link_tag['href']
                full_link = f"https:{relative_link}"

                if full_link in seen_links:
                    continue

                ad_response = fetch_with_retry(full_link)
                if not ad_response:
                    continue

                ad_soup = BeautifulSoup(ad_response.text, 'html.parser')
                ad_info = extract_ad_info(ad_soup)
                if not ad_info or not ad_info['date']:
                    continue

                if ad_info['date'].date() >= yesterday:
                    seen_links.add(full_link)
                    new_ads.append({
                        'title': ad_info['title'],
                        'price': ad_info['price'],
                        'link': full_link,
                        'date': ad_info['date'].strftime('%H:%M %d.%m.%Y')
                    })
                else:
                    stop_processing = True
                    break

            if stop_processing:
                break
            page += 1
            time.sleep(1)
    return new_ads

def send_daily_status():
    while True:
        now = datetime.now()
        if now.hour == 10 and now.minute == 0:
            msg = f"✅ Ботът е активен\n{now.strftime('%d.%m.%Y %H:%M')}\nСледи {len(Config.URLS)} линка."
            send_telegram(msg)
            time.sleep(60)
        time.sleep(30)

@app.route('/')
def home():
    return "Ботът е активен."

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if data:
        chat_id = data.get('message', {}).get('chat', {}).get('id')
        text = data.get('message', {}).get('text', '').lower()

        if str(chat_id) == Config.TELEGRAM_CHAT_ID:
            if text == '/покажи':
                new_ads = check_listings()
                if not new_ads:
                    send_telegram("Няма нови или редактирани обяви от днес и вчера.")
                else:
                    for ad in new_ads:
                        msg = f"🏠 <b>{ad['title']}</b>\n💰 {ad['price']}\n📅 {ad['date']}\n🔗 <a href='{ad['link']}'>Виж обявата</a>"
                        send_telegram(msg)
    return 'OK'

def run_flask():
    app.run(host='0.0.0.0', port=5000)

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=send_daily_status, daemon=True).start()

    send_telegram("🚀 Ботът стартира успешно и е в готовност.")
    logging.info("Ботът стартира.")

    while True:
        try:
            new_ads = check_listings()
            for ad in new_ads:
                msg = f"🏠 <b>{ad['title']}</b>\n💰 {ad['price']}\n📅 {ad['date']}\n🔗 <a href='{ad['link']}'>Виж обявата</a>"
                send_telegram(msg)
            time.sleep(Config.CHECK_INTERVAL)
        except Exception as e:
            logging.critical(f"Критична грешка: {e}\n{traceback.format_exc()}")
            send_telegram(f"❌ Критична грешка: {e}")
            time.sleep(60)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        send_telegram("🛑 Ботът е спрян.")
        sys.exit(0)
    except Exception as e:
        logging.critical(f"Грешка при стартиране: {e}\n{traceback.format_exc()}")
        send_telegram(f"🔴 Критична грешка при стартиране: {e}")
        sys.exit(1)

        sys.exit(0)
    except Exception as e:
        send_telegram(f"🔴 Критична грешка при стартиране: {e}")
        logging.critical(f"Грешка при стартиране: {e}\n{traceback.format_exc()}")
        sys.exit(1)
