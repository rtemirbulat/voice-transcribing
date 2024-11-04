import os
import json
import requests
import aiohttp
import asyncio
import re
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify


app = Flask(__name__)

# Load environment variables
load_dotenv()
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERSION = os.getenv("VERSION")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD")

# Ensure necessary directories exist
os.makedirs("logs", exist_ok=True)
os.makedirs("media", exist_ok=True)
os.makedirs("messages", exist_ok=True)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

handler = TimedRotatingFileHandler(
    filename='logs/bot.log',
    when='H',
    interval=1,
    backupCount=24
)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Global dictionary to store user authentication status
user_sessions = {}
# Media sequence
media_sequence = {}

# To verify webhooks
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """Webhook endpoint for verification and message handling."""
    if request.method == 'GET':
        return verify_webhook()
    elif request.method == 'POST':
        return handle_message()

def verify_webhook():
    """Verify the webhook using the token."""
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully!")
        return challenge, 200
    else:
        logger.warning("Webhook verification failed.")
        return "Forbidden", 403

# Main functionality
def handle_message():
    """Handle incoming messages and download media if authenticated."""
    data = request.get_json()
    logger.debug(f"Received data: {json.dumps(data)}")

    messages = []
    from_number = None

    try:
        entry = data['entry'][0]
        changes = entry['changes'][0]
        value = changes['value']
        messages = value.get('messages', [])
    except (KeyError, IndexError) as e:
        logger.info("No messages found in the webhook data.")
        return jsonify({"status": "no_messages"}), 200

    for message in messages:
        from_number = message.get('from')
        timestamp = datetime.fromtimestamp(int(message.get('timestamp')))
        formatted_time = timestamp.strftime('%Y-%m-%d_%H-%M')
        message_type = message.get('type')
        message_body = message.get('text', {}).get('body', '').lower()

        if from_number not in user_sessions:
            user_sessions[from_number] = {'authenticated': False, 'awaiting_password': False}

        is_authenticated = user_sessions[from_number]['authenticated']
        awaiting_password = user_sessions[from_number]['awaiting_password']

        if message_type == 'text' and (message_body == 'start' or message_body == 'старт'):
            asyncio.run(send_text_message(from_number, "Введите 4-х значный код для входа"))
            user_sessions[from_number]['awaiting_password'] = True
            return jsonify({"status": "password_requested"}), 200

        elif message_type == 'text' and awaiting_password:
            entered_password = message.get('text', {}).get('body', '')
            if entered_password == AUTH_PASSWORD:
                user_sessions[from_number]['authenticated'] = True
                user_sessions[from_number]['awaiting_password'] = False
                asyncio.run(send_text_message(from_number, "Авторизация успешна!"))
            else:
                user_sessions[from_number]['authenticated'] = False
                user_sessions[from_number]['awaiting_password'] = False
                asyncio.run(send_text_message(from_number, "Неверный код. Введите слово 'cтарт' и попробуйте еще раз"))
            return jsonify({"status": "authentication_attempted"}), 200

        if not is_authenticated and not awaiting_password:
            logger.info(f"User {from_number} is not authenticated. Prompting to register.")
            asyncio.run(send_text_message(from_number, "Для работы с ботом требуется код. Введите 'старт' и пройдите проверку"))
            return jsonify({"status": "not_authenticated"}), 200

        # The user is authenticated; proceed to process and save the message
        counts = {
            'text': 0,
            'image': 0,
            'video': 0,
            'audio': 0,
            'document': 0,
            'voice': 0,
            'others': 0
        }

        if message_type == 'text':
            counts['text'] += 1
            text = message['text']['body']
            logger.info(f"Received text from {from_number}: {text}")
            save_message(from_number, text, formatted_time)

        elif message_type in ['image', 'video', 'audio', 'document', 'voice']:
            counts[message_type] += 1
            media_id = message[message_type]['id']
            media_url = get_media_url(media_id)
            download_media(media_url, message_type, from_number, formatted_time)

        else:
            counts['others'] += 1
            logger.info(f"Received {message_type} message from {from_number}")

        if from_number:
            asyncio.run(send_reply(from_number, counts))

    return jsonify({"status": "received"}), 200

def get_media_url(media_id):
    """Retrieve media download URL from WhatsApp Cloud API."""
    url = f"https://graph.facebook.com/{VERSION}/{media_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers).json()
    return response.get('url')

def get_next_sequence_number(phone_dir, media_type):
    sequence_numbers = []
    pattern = re.compile(rf"{media_type}_(\d+)_")

    for filename in os.listdir(phone_dir):
        match = pattern.match(filename)
        if match:
            sequence_numbers.append(int(match.group(1)))

    if sequence_numbers:
        return max(sequence_numbers) + 1
    else:
        return 1

def download_media(url, media_type, from_number, timestamp):
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers, stream=True)
    extension_mapping = {
        'audio': '.wav',
        'voice': '.wav',
        'image': '.jpg',
        'video': '.mp4',
        'document': '.pdf',
    }
    extension = extension_mapping.get(media_type, '.media')
    date_str = timestamp.strftime('%Y-%m-%d')
    time_str = timestamp.strftime('%H-%M-%S-%f') #thinking about adding microseconds
    phone_dir = os.path.join("media", from_number, date_str)
    os.makedirs(phone_dir, exist_ok=True)
    sequence_number = get_next_sequence_number(phone_dir, media_type)

    filename = f"{media_type}_{sequence_number}_{time_str}{extension}"
    filepath = os.path.join(phone_dir, filename)

    try:
        with open(filepath, "wb") as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        logger.info(f"Media saved at: {filepath}")
        success = True
    except Exception as e:
        logger.error(f"Failed to save media: {e}")
        success = False
        filepath = None

    return filepath, filename, success

def save_message(from_number, text, timestamp):
    filename = f"{from_number}.txt"
    filepath = os.path.join("messages", filename)

    message_content = f"Timestamp: {timestamp}\nFrom: {from_number}\nMessage: {text}\n\n"

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(message_content)

    logger.info(f"Message appended to: {filepath}")

async def send_async_message(data):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ACCESS_TOKEN}",
    }
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as response:
            response_text = await response.text()
            if response.status in [200, 201]:
                logger.info("Async message sent successfully!")
                logger.debug(f"Response: {response_text}")
            else:
                logger.error(f"Async send failed: {response.status}")
                logger.error(f"Response: {response_text}")

def get_text_message_input(recipient, text):
    """Generate JSON payload for text message."""
    formatted_recipient = recipient.lstrip('+')
    # Works only for KZ numbers
    if formatted_recipient.startswith('7'):
        formatted_recipient = '78' + formatted_recipient[1:]
    else:
        formatted_recipient = '78' + formatted_recipient

    logger.debug(f"Formatted recipient number: {formatted_recipient}")

    return {
        "messaging_product": "whatsapp",
        "to": formatted_recipient,
        "type": "text",
        "text": {"body": text}
    }

async def send_reply(recipient_id, counts):
    """Send a reply message with the counts of received messages."""
    message_lines = []

    msg_type_forms = {
        'text': 'текстовое сообщение',
        'image': 'изображения',
        'video': 'видео',
        'audio': 'аудио',
        'document': 'документ',
        'voice': 'голосовое сообщение',
        'others': 'других сообщений',
    }

    for msg_type, count in counts.items():
        if count > 0:
            message_lines.append(f"{count} {msg_type_forms.get(msg_type)} сообщени(й)")

    if message_lines:
        message_body = "Получено:\n" + "\n".join(message_lines)
    else:
        message_body = "Сообщения не получены."

    data = get_text_message_input(recipient_id, message_body)

    await send_async_message(data)

async def send_text_message(recipient_id, message_body):
    data = get_text_message_input(recipient_id, message_body)
    await send_async_message(data)

