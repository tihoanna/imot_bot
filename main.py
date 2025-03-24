import requests
from bs4 import BeautifulSoup
import time
from keep_alive import keep_alive
from datetime import datetime, timedelta
import threading

keep_alive()

URLS = [
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0u5&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0z9&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus0zw&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bus10u&f1=1',
]

TELEGRAM_TOKEN = '7957617876:AAGo4nxyn2FlVRZPiFIrIw6EaqNlzF8G7Jo'
TELEGRAM_CHAT_ID = '6290875129'
HEADERS = {'User-Agent': 'Mozilla/5.0'}

seen_links = set()

def send_telegram(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
    requests.post(url, data=data)

def get_all_listings(base_url):
    listings = []
    page = 1
    now = datetime.now()
    threshold_time = now - timedelta(minutes=10)
    today_str = now.strftime('%d.%m.%Y')

    while True:
        paged_url = f"{base_url}&p={page}"
        response = requests.get(paged_url, headers=HEADERS)
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
                continue  # ако форматът не съвпада

            if post_time.date() == now.date() and post_time >= threshold_time:
                title = title_tag.get_text(strip=True)
                link = link_tag.get('href')
                if link:
                    listings.append((title, link.strip()))

        page += 1

    return listings

def check_new_listings():
    new_listings = []
    for url in URLS:
        for title, link in get_all_listings(url):
            if link not in seen_links:
                seen_links.add(link)
                new_listings.append((title, link))

    for title, link in new_listings:
        send_telegram(f"🏠 Нова обява (до 10 минути):\n{title}\nhttps:{link}")

def send_daily_status():
    while True:
        now = datetime.now()
        if now.hour == 10 and now.minute == 0:
            send_telegram("✅ Ботът е активен и няма проблеми.")
            time.sleep(60)
        time.sleep(30)

threading.Thread(target=send_daily_status, daemon=True).start()

send_telegram("🚀 Ботът стартира успешно и е в готовност.")
print("✅ Ботът стартира. Проверява на всеки 10 минути...")

while True:
    try:
        check_new_listings()
    except Exception as e:
        print("⚠️ Грешка:", e)
    time.sleep(600)
