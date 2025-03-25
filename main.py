import os
import sys
import requests
from bs4 import BeautifulSoup
import time
import logging
from datetime import datetime, timedelta
import threading
from flask import Flask, request
from dotenv import load_dotenv

# Зареждане на .env променливи
load_dotenv()

# Конфигурация
URLS = [
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0u5&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0z9&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0zw&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus10u&f1=1',
]

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Accept-Language': 'bg-BG,bg;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
}

seen_links = set()
lock = threading.Lock()

# Telegram изпращане
def send_telegram(msg):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg}
    try:
        requests.post(url, data=data, timeout=10)
    except:
        pass

# Извличане на всички обяви
def get_all_listings(url):
    listings = []
    page = 1
    now = datetime.now()
    yesterday = now - timedelta(days=1)

    while True:
        paged_url = f"{url}&p={page}"
        try:
            resp = requests.get(paged_url, headers=HEADERS, timeout=10)
        except:
            break

        soup = BeautifulSoup(resp.text, 'html.parser')
        rows = soup.select('tr.odd, tr.even')
        if not rows:
            break

        for row in rows:
            link_tag = row.select_one('td:nth-child(3) .bold a')
            date_tag = row.select_one('td:nth-child(6)')
            if not link_tag or not date_tag:
                continue

            link = link_tag.get('href')
            date_str = date_tag.text.strip()

            try:
                date = datetime.strptime(date_str, '%H:%M %d.%m.%Y')
            except:
                continue

            if date.date() in [now.date(), yesterday.date()]:
                listings.append(f"https:{link.strip()}")

        page += 1

    return listings

# Проверка за нови обяви
def check_new():
    new_links = []
    for url in URLS:
        for link in get_all_listings(url):
            with lock:
                if link not in seen_links:
                    seen_links.add(link)
                    new_links.append(link)
    for link in new_links:
        send_telegram(f"Нова обява:\n{link}")

# Дневен статус
def daily_status():
    while True:
        now = datetime.now()
        if now.hour == 10 and now.minute == 0:
            send_telegram("Ботът е активен и няма проблеми.")
            time.sleep(60)
        time.sleep(30)

# Обработка на Telegram команда /покажи
def handle_show_command():
    all_today = set()
    for url in URLS:
        all_today.update(get_all_listings(url))

    if not all_today:
        send_telegram("Няма нови или редактирани обяви от днес и вчера.")
    else:
        for link in all_today:
            send_telegram(link)

# Flask за Telegram webhook
app = Flask(__name__)

@app.route('/', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if not data or 'message' not in data:
        return '', 200

    message = data['message']
    chat_id = str(message.get('chat', {}).get('id'))

    if chat_id != TELEGRAM_CHAT_ID:
        return '', 200

    text = message.get('text', '').strip().lower()
    if text == '/покажи':
        threading.Thread(target=handle_show_command).start()

    return '', 200

def start_flask():
    app.run(host='0.0.0.0', port=8080)

# Старт на всичко
def main():
    threading.Thread(target=start_flask, daemon=True).start()
    threading.Thread(target=daily_status, daemon=True).start()

    send_telegram("Ботът стартира успешно и е в готовност.")

    while True:
        try:
            check_new()
        except Exception as e:
            print("Грешка при проверка:", e)
        time.sleep(600)

if __name__ == '__main__':
    main()
