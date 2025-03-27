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
from urllib.parse import urljoin

# Логване
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('imot_monitor.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

load_dotenv()

class Config:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    CHECK_INTERVAL = 600
    MAX_RETRIES = 3
    REQUEST_TIMEOUT = 30
    URLS = [
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nqa&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nye&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3nz2&f1=1',
        'https://www.imot.bg/pcgi/imot.cgi?act=3&slink=bv3o1w&f1=1'
    ]
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15',
        'Mozilla/5.0 (Linux; Android 10; SM-A505FN) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36'
    ]

app = Flask(__name__)

# Telegram изпращане

def send_telegram(message):
    try:
        url = f'https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage'
        data = {
            'chat_id': Config.TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logging.error(f"Telegram error: {e}")

# Последните обяви от всеки линк

def fetch_latest_from_each_url():
    messages = []
    for url in Config.URLS:
        try:
            response = requests.get(url, headers={'User-Agent': random.choice(Config.USER_AGENTS)})
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            ads = soup.select('table.tblOffers tr:has(a[href*="/p/"])')[:5]
            for ad in ads:
                link_tag = ad.select_one('a[href*="/p/"]')
                if link_tag:
                    full_link = urljoin('https://www.imot.bg', link_tag['href'])
                    messages.append(full_link)
        except Exception as e:
            logging.error(f"Fetch latest error: {e}")
    return messages

# Webhook

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != Config.WEBHOOK_SECRET:
        return 'Unauthorized', 401

    data = request.json
    message = data.get('message', {}).get('text', '').strip().lower()

    if message == '/latest':
        links = fetch_latest_from_each_url()
        if links:
            for i, link in enumerate(links, 1):
                send_telegram(f"{i}. {link}")
        else:
            send_telegram("Няма налични обяви в момента.")

    elif message == '/status':
        send_telegram("🟢 Ботът е активен и работи коректно.")

    return 'OK'

@app.route('/')
def home():
    return 'OK'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
