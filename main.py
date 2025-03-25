import os
import requests
from bs4 import BeautifulSoup
import time
import logging
from datetime import datetime, timedelta
import threading
from dotenv import load_dotenv

# Зареждане на environment variables
load_dotenv()

# Логиране
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('imot_bot.log'),
        logging.StreamHandler()
    ]
)

# URL-и за следене
URLS = [
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0u5&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0z9&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0zw&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus10u&f1=1',
]

# Променливи от средата
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Accept-Language': 'bg-BG,bg;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
}

# Сигурно множество с Lock
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

def send_telegram(message):
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
        data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        logging.info("Изпратено съобщение в Telegram.")
    except Exception as e:
        logging.error(f"Грешка при изпращане на съобщение: {e}")

def get_all_listings(base_url):
    listings = []
    page = 1
    now = datetime.now()
    threshold_time = now - timedelta(minutes=10)

    while True:
        paged_url = f"{base_url}&p={page}"
        try:
            response = requests.get(paged_url, headers=HEADERS, timeout=10)
            response.raise_for_status()
        except Exception as e:
            logging.error(f"Грешка при зареждане на страница {page}: {e}")
            break

        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.select('tr.odd, tr.even')

        if not rows:
            break

        for row in rows:
            title_tag = row.select_one('td:nth-child(3) .bold')
            link_tag = row.select_one('td:nth-child(3) .bold a')
            date_tag = row.select_one('td:nth-child(6)')

            if not (title_tag and link_tag and date_tag):
                continue

            try:
                post_time = datetime.strptime(date_tag.text.strip(), '%H:%M %d.%m.%Y')
            except ValueError:
                continue

            if post_time.date() == now.date() and post_time >= threshold_time:
                title = title_tag.text.strip()
                link = link_tag.get('href')
                if link:
                    listings.append((title, link.strip()))
        page += 1

    return listings

def check_new_listings():
    new_listings = []
    for url in URLS:
        try:
            for title, link in get_all_listings(url):
                if link not in seen_links:
                    seen_links.add(link)
                    new_listings.append((title, link))
        except Exception as e:
            logging.error(f"Грешка при проверка на URL: {url} — {e}")

    for title, link in new_listings:
        send_telegram(f"🏠 <b>Нова обява (до 10 минути):</b>\n<b>{title}</b>\nhttps:{link}")

def send_daily_status():
    while True:
        now = datetime.now()
        if now.hour == 10 and now.minute == 0:
            status = (
                f"✅ <b>Статус на бота:</b>\n"
                f"🕒 Час: {now.strftime('%H:%M:%S')}\n"
                f"📅 Дата: {now.strftime('%d.%m.%Y')}\n"
                f"🤖 Всичко работи нормално."
            )
            send_telegram(status)
            time.sleep(60)
        time.sleep(30)

def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.critical("Липсват TELEGRAM_TOKEN или TELEGRAM_CHAT_ID!")
        return

    threading.Thread(target=send_daily_status, daemon=True).start()

    send_telegram("🚀 Ботът стартира успешно и е в готовност.")
    logging.info("Ботът стартира. Проверява на всеки 10 минути...")

    while True:
        try:
            check_new_listings()
        except Exception as e:
            logging.error(f"Грешка в основния цикъл: {e}")
        time.sleep(600)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Ботът беше спрян.")
    except Exception as e:
        logging.critical(f"Критична грешка: {e}")
