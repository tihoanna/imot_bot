import os
import sys
import requests
from bs4 import BeautifulSoup
import time
import logging
from datetime import datetime, timedelta
import threading
from dotenv import load_dotenv
import traceback

# Зареждане на environment variables
load_dotenv()

# Конфигуриране на logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('imot_bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Константи
URLS = [
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0u5&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0z9&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0zw&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus10u&f1=1',
]

# Четене на environment variables с default стойности
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
PING_URL = os.getenv('PING_URL', '')  # Допълнителен URL за keep-alive

# Защитени headers
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'bg-BG,bg;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
}

# Threadcsafe множество за проследяване на линкове
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

def ping_service():
    """Периодично изпращане на ping към външен сървис за keep-alive"""
    while True:
        try:
            if PING_URL:
                requests.get(PING_URL, timeout=10)
                logging.info("Успешен ping към keep-alive услуга")
        except Exception as e:
            logging.error(f"Грешка при ping: {e}")
        time.sleep(600)  # На всеки 10 минути

def send_telegram(message):
    """Изпращане на съобщение в Telegram с разширена грешка обработка"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Липсват Telegram credentials")
        return

    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
        data = {
            'chat_id': TELEGRAM_CHAT_ID, 
            'text': message,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        logging.info(f"Успешно изпратено съобщение: {message[:50]}...")
    except requests.RequestException as e:
        logging.error(f"Грешка при изпращане на телеграм съобщение: {e}")
        # Допълнителен механизъм за логване на грешки
        with open('telegram_errors.log', 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now()} - Грешка: {e}\n")

def get_all_listings(base_url):
    """Извличане на листинги с разширена грешка обработка"""
    listings = []
    page = 1
    now = datetime.now()
    threshold_time = now - timedelta(minutes=10)
    
    try:
        while True:
            paged_url = f"{base_url}&p={page}"
            
            try:
                response = requests.get(paged_url, headers=HEADERS, timeout=15)
                response.raise_for_status()
            except requests.RequestException as e:
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

                date_text = date_tag.get_text(strip=True)

                try:
                    post_time = datetime.strptime(date_text, '%H:%M %d.%m.%Y')
                except ValueError:
                    continue

                if post_time.date() == now.date() and post_time >= threshold_time:
                    title = title_tag.get_text(strip=True)
                    link = link_tag.get('href')
                    if link:
                        listings.append((title, link.strip()))

            page += 1
    except Exception as e:
        logging.error(f"Неочаквана грешка при извличане на листинги: {e}")
        logging.error(traceback.format_exc())
    
    return listings

def check_new_listings():
    """Проверка за нови листинги с подобрена обработка"""
    new_listings = []
    for url in URLS:
        try:
            for title, link in get_all_listings(url):
                if link not in seen_links:
                    seen_links.add(link)
                    new_listings.append((title, link))
        except Exception as e:
            logging.error(f"Грешка при проверка на URL {url}: {e}")
            logging.error(traceback.format_exc())

    for title, link in new_listings:
        try:
            send_telegram(f"🏠 Нова обява (до 10 минути):\n<b>{title}</b>\nhttps:{link}")
        except Exception as e:
            logging.error(f"Грешка при изпращане на съобщение: {e}")

def send_daily_status():
    """Изпращане на разширен дневен статус"""
    while True:
        try:
            now = datetime.now()
            if now.hour == 10 and now.minute == 0:
                # Четене на log файла за последни грешки
                try:
                    with open('imot_bot.log', 'r', encoding='utf-8') as f:
                        log_tail = f.readlines()[-10:]  # Последни 10 реда
                except Exception:
                    log_tail = ["Не може да се прочете log файла"]

                status_message = (
                    "✅ Статус на бота:\n"
                    f"🕒 Час: {now.strftime('%H:%M:%S')}\n"
                    f"📅 Дата: {now.strftime('%d.%m.%Y')}\n"
                    "🤖 Последни log съобщения:\n" +
                    "".join(log_tail[-5:])  # Последни 5 реда от log
                )
                send_telegram(status_message)
                time.sleep(60)  # Забавяне, за да не изпраща повторно
        except Exception as e:
            logging.error(f"Грешка при изпращане на дневен статус: {e}")
        
        time.sleep(30)

def main():
    """Главна функция за стартиране на бота"""
    # Проверка за задължителни environment variables
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.critical("Липсват задължителни environment variables!")
        sys.exit(1)

    # Стартиране на threading
    threads = [
        threading.Thread(target=send_daily_status, daemon=True),
        threading.Thread(target=ping_service, daemon=True)
    ]
    
    for thread in threads:
        thread.start()

    # Първоначално съобщение
    send_telegram("🚀 Ботът стартира успешно и е в готовност.")
    logging.info("Ботът стартира. Проверява на всеки 10 минути...")

    # Основен работен цикъл
    while True:
        try:
            check_new_listings()
        except Exception as e:
            logging.error(f"Неочаквана грешка в основния цикъл: {e}")
            logging.error(traceback.format_exc())
        
        time.sleep(600)  # Пауза от 10 минути

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Ботът е спрян.")
    except Exception as e:
        logging.critical(f"Критична грешка: {e}")
        logging.critical(traceback.format_exc())
        send_telegram(f"❌ Критична грешка: {e}")
        sys.exit(1)
