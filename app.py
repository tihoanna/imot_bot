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
import random

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('imot_monitor.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

class Config:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
    CHECK_INTERVAL = 600
    URLS = [
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nqa&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nye&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nz2&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3o1w&f1=1'
    ]
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15'
    ]

app = Flask(__name__)
seen_links = set()


def send_telegram(message):
    try:
        url = f'https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage'
        data = {
            'chat_id': Config.TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }
        requests.post(url, data=data)
    except Exception as e:
        logging.error(f"Telegram error: {e}")


def fetch_ads(base_url):
    headers = {
        'User-Agent': random.choice(Config.USER_AGENTS),
        'Accept-Language': 'bg-BG,bg;q=0.9'
    }
    try:
        response = requests.get(base_url, headers=headers)
        response.encoding = 'windows-1251'
        soup = BeautifulSoup(response.text, 'html.parser')
        links = soup.select('a[href*="/pcgi/imot.cgi?act=5&adv="]')

        ads = []
        for link in links[:5]:
            full_url = f"https://www.imot.bg{link['href']}"
            if full_url not in seen_links:
                seen_links.add(full_url)
                ads.append(full_url)
        return ads
    except Exception as e:
        logging.error(f"Fetch error: {e}")
        return []


def background_checker():
    while True:
        all_ads = []
        for url in Config.URLS:
            all_ads.extend(fetch_ads(url))

        for ad in all_ads:
            send_telegram(f"Нова обява:
{ad}")

        time.sleep(Config.CHECK_INTERVAL)


@app.route('/')
def home():
    return "IMOT.BG бот е активен"


@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != Config.WEBHOOK_SECRET:
        return 'Unauthorized', 401

    data = request.json
    text = data.get('message', {}).get('text', '')

    if text.lower() == '/latest':
        all_ads = []
        for url in Config.URLS:
            all_ads.extend(fetch_ads(url))
        if all_ads:
            send_telegram("Най-нови обяви:\n" + "\n".join(all_ads))
        else:
            send_telegram("Няма намерени обяви.")

    return 'OK'


def main():
    threading.Thread(target=background_checker, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)


if __name__ == '__main__':
    main()
