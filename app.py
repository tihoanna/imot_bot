import os
import requests
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, request

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
CHECK_INTERVAL = 600
URLS = [
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nqa&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nye&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nz2&f1=1',
    'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3o1w&f1=1'
]

seen_links = set()
app = Flask(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def send_telegram(msg):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}
    try:
        requests.post(url, data=data, timeout=10)
    except:
        pass

def parse_date(text):
    try:
        return datetime.strptime(text.strip(), '%H:%M %d.%m.%Y')
    except:
        return None

def get_ads_from(url):
    new_ads = []
    page = 1
    while True:
        r = requests.get(f"{url}&p={page}", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        ads = soup.select('div.content > table > tr:has(.photo)')
        if not ads:
            break

        for ad in ads:
            link_tag = ad.select_one('a.ver15hl')
            if not link_tag:
                continue
            link = 'https://www.imot.bg' + link_tag['href']
            if link in seen_links:
                continue
            seen_links.add(link)

            ad_page = requests.get(link, headers=HEADERS, timeout=10)
            ad_soup = BeautifulSoup(ad_page.text, 'html.parser')
            title = ad_soup.find('h1').get_text(strip=True)
            price = ad_soup.find(class_='price').get_text(strip=True)
            date_str = ad_soup.find(string=lambda t: 'Публикувана' in t or 'Коригирана' in t)
            date = parse_date(date_str.split('на')[-1]) if date_str else None

            if date and date.date() >= (datetime.now() - timedelta(days=1)).date():
                msg = f"<b>{title}</b>\n{price}\n<a href='{link}'>Линк към обявата</a>"
                new_ads.append(msg)
        page += 1
    return new_ads

@app.route('/')
def home():
    return 'Ботът е активен.'

@app.route('/webhook', methods=['POST'])
def webhook():
    msg = request.json.get('message', {}).get('text')
    if msg == '/status':
        send_telegram('Ботът е активен и работи нормално.')
    return 'OK'

def check_all():
    for url in URLS:
        for msg in get_ads_from(url):
            send_telegram(msg)

if __name__ == '__main__':
    from threading import Thread
    Thread(target=lambda: app.run(host='0.0.0.0', port=5000), daemon=True).start()
    send_telegram('🚀 Ботът стартира успешно.')
    while True:
        check_all()
        time.sleep(CHECK_INTERVAL)
