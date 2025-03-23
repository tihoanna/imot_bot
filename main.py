import requests
from bs4 import BeautifulSoup
import time

# Конфигурация
IMOT_URL = 'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=burrxh&f1=1'
TELEGRAM_TOKEN = '7957617876:AAGo4nxyn2FlVRZPiFIrIw6EaqNlzF8G7Jo'
TELEGRAM_CHAT_ID = '6290875129'
HEADERS = {'User-Agent': 'Mozilla/5.0'}
seen_links = set()

def send_telegram(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
    requests.post(url, data=data)

def get_listings():
    response = requests.get(IMOT_URL, headers=HEADERS)
    soup = BeautifulSoup(response.text, 'html.parser')
    listings = []

    for row in soup.select('tr.oddRow, tr.evenRow'):
        link_tag = row.select_one('a[href*="imot.cgi?act=5"]')
        if link_tag:
            title = link_tag.text.strip()
            href = link_tag['href']
            full_link = 'https://www.imot.bg' + href
            listings.append((title, full_link))
    return listings

def check_new_listings():
    global seen_links
    new_listings = []
    listings = get_listings()

    for title, link in listings:
        if link not in seen_links:
            seen_links.add(link)
            new_listings.append((title, link))

    for title, link in new_listings:
        send_telegram(f'🆕 Нова обява: {title}\n{link}')

print("✅ Ботът стартира. Проверява на всеки 10 минути...")
while True:
    try:
        check_new_listings()
    except Exception as e:
        print("⚠️ Грешка:", e)
    time.sleep(600)  # Проверка на всеки 10 минути
