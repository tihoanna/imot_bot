import requests
from bs4 import BeautifulSoup
import time
from keep_alive import keep_alive
from datetime import datetime

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
    while True:
        paged_url = f"{base_url}&p={page}"
        response = requests.get(paged_url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')
        titles = soup.select('td:nth-child(3) .bold')
        links = soup.select('td:nth-child(3) .bold a')

        if not titles or not links:
            break

        for title, link in zip(titles, links):
            href = link.get('href')
            if href:
                listings.append((title.text.strip(), href.strip()))

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
        send_telegram(f"🏠 Нова обява:\n{title}\nhttps:{link}")


def send_daily_ping():
    now = datetime.now()
    if now.hour == 10 and now.minute == 0:
        send_telegram("✅ Ботът беше рестартиран и е активен :)")
        time.sleep(60)


send_telegram("🚀 Ботът стартира успешно и е в готовност.")

print("✅ Ботът стартира. Проверява на всеки 10 минути...")

while True:
    try:
        check_new_listings()
        send_daily_ping()
    except Exception as e:
        print("⚠️ Грешка:", e)
    time.sleep(600)
