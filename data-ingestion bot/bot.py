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
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, ForeignKey, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.exc import SQLAlchemyError
import pytz

app = Flask(__name__)

# Load environment variables
load_dotenv()
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERSION = os.getenv("VERSION")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD")
DATABASE_URL = os.getenv("DATABASE_URL")

# Ensure necessary directories exist
os.makedirs("logs", exist_ok=True)
os.makedirs("media", exist_ok=True)
os.makedirs("messages", exist_ok=True)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

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

#SQLAlchemy setup
engine = create_engine(DATABASE_URL,echo=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


#DB models
class PhoneNumber(Base):
    __tablename__ = 'phone_num'

    phone_num = Column(String, primary_key=True, unique=True, nullable=True)
    name = Column(String, nullable=True)
    whatsapp_name = Column(String, nullable=True)

    messages = relationship("Message", back_populates="phone_number_ref")


class Message(Base):
    __tablename__ = 'messages'

    id = Column(Integer, primary_key=True, index=True)
    phone_num = Column(String, ForeignKey('phone_num.phone_num'), nullable=True)
    name = Column(String, nullable=True)
    message_text = Column(Text, nullable=True)
    hasAttachments = Column(Boolean, default=False)
    attachment_links = Column(Text, nullable=True)  # Comma-separated links
    date_time = Column(DateTime, nullable=True)
    detected_audio = Column(String, nullable=True)
    rut_type = Column(String, nullable=True)
    router = Column(String, nullable=True)
    oiler_number = Column(String, nullable=True)
    cdng = Column(String, nullable=True)
    ngdu = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)

    phone_number_ref = relationship("PhoneNumber", back_populates="messages")


# To verify webhooks
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        return verify_webhook()
    elif request.method == 'POST':
        return handle_message()


def verify_webhook():
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

    session = SessionLocal()

    for message in messages:
        from_number = message.get('from')
        timestamp = datetime.fromtimestamp(int(message.get('timestamp')), pytz.utc)
        # Convert to UTC+5
        utc_plus_5 = pytz.timezone('Etc/GMT-5')  # Etc/GMT-5 is UTC+5
        timestamp = timestamp.astimezone(utc_plus_5)
        formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
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
                asyncio.run(send_text_message(from_number, "Неверный код. Введите слово 'старт' и попробуйте еще раз"))
            return jsonify({"status": "authentication_attempted"}), 200

        if not is_authenticated and not awaiting_password:
            logger.info(f"User {from_number} is not authenticated. Prompting to register.")
            asyncio.run(
                send_text_message(from_number, "Для работы с ботом требуется код. Введите 'старт' и пройдите проверку"))
            return jsonify({"status": "not_authenticated"}), 200




        counts = {
            'text': 0,
            'image': 0,
            'video': 0,
            'audio': 0,
            'document': 0,
            'voice': 0,
            'others': 0
        }

        has_attachments = False
        attachment_links = []

        if message_type == 'text':
            # Process text message
            text = message['text']['body']
            logger.info(f"Received text from {from_number}: {text}")

            # Save to database
            save_message_to_db(
                session=session,
                phone_num=from_number,
                message_text=text,
                has_attachments=False,
                attachment_links='',
                date_time=timestamp
            )
            asyncio.run(save_message(from_number, text, formatted_time))

        elif message_type in ['image', 'video', 'audio', 'document', 'voice']:
            counts[message_type] += 1
            media_id = message[message_type]['id']
            media_url = get_media_url(media_id)
            filepath, filename, success = download_media(media_url, message_type, from_number, timestamp)
            if success:
                has_attachments = True
                attachment_links = filepath  # Modify if handling multiple attachments
                # Save to database
                save_message_to_db(
                    session=session,
                    phone_num=from_number,
                    message_text='',
                    has_attachments=True,
                    attachment_links=filepath,
                    date_time=timestamp
                )
                # Notify user
                asyncio.run(send_async_message_status(from_number, filepath, success, message_type))
            else:
                # Notify user about failure
                asyncio.run(send_async_message_status(from_number, filepath, success, message_type))
        else:
            counts['others'] += 1
            logger.info(f"Received {message_type} message from {from_number}")
            save_message_to_db(
                session=session,
                phone_num=from_number,
                message_text='',
                has_attachments=False,
                attachment_links='',
                date_time=timestamp
            )

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
    time_str = timestamp.strftime('%H-%M-%S')
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


# save message text
async def save_message(from_number, text, timestamp):
    filename = f"{from_number}.txt"
    filepath = os.path.join("messages", filename)

    message_content = f"Timestamp: {timestamp}\nFrom: {from_number}\nMessage: {text}\n\n"

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(message_content)

    message_body = (f"Вы написали {text}, сообщение сохранено в {filepath}")
    await send_text_message(from_number, message_body)


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


async def send_text_message(from_number, message_body):
    data = get_text_message_input(from_number, message_body)
    await send_async_message(data)


def get_or_create_phone_number(session, phone_num):
    """Fetch a PhoneNumber entry or create it if it doesn't exist."""
    phone_entry = session.query(PhoneNumber).filter_by(phone_num=phone_num).first()
    if phone_entry:
        return phone_entry
    else:
        # Fetch whatsapp_name from WhatsApp Cloud API
        whatsapp_name = fetch_whatsapp_name(phone_num)
        # Create a new PhoneNumber entry with 'Unknown' name if not found
        new_entry = PhoneNumber(
            phone_num=phone_num,
            name='name',  # You can modify this to prompt user or fetch from another source
            whatsapp_name=whatsapp_name
        )
        session.add(new_entry)
        try:
            session.commit()
            logger.info(f"Inserted new phone number {phone_num} with WhatsApp name '{whatsapp_name}'.")
        except SQLAlchemyError as e:
            logger.error(f"Error inserting phone number {phone_num}: {e}")
            session.rollback()
        return new_entry


def fetch_whatsapp_name(phone_num):
    # Ensure phone_num is in E.164 format
    if not phone_num.startswith('+'):
        phone_num_formatted = '+' + phone_num
    else:
        phone_num_formatted = phone_num

    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/contacts/{phone_num_formatted}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        whatsapp_name = data.get('profile', {}).get('name', 'Unknown')
        logger.info(f"Fetched WhatsApp name for {phone_num}: {whatsapp_name}")
        return whatsapp_name
    else:
        logger.warning(f"Failed to fetch WhatsApp name for {phone_num}: {response.text}")
        return 'Unknown'



def save_message_to_db(session, phone_num, message_text, has_attachments, attachment_links, date_time):
    """Save a message to the database."""
    phone_entry = get_or_create_phone_number(session, phone_num)
    if not phone_entry:
        logger.error(f"Failed to retrieve or create phone number entry for {phone_num}. Skipping message save.")
        return
    message_entry = Message(
        phone_num=phone_num,
        name=phone_entry.name,
        message_text=message_text,
        hasAttachments=has_attachments,
        attachment_links=attachment_links,
        date_time=date_time
    )
    session.add(message_entry)
    try:
        session.commit()
        logger.info(f"Saved message from {phone_num} to database.")
    except SQLAlchemyError as e:
        logger.error(f"Error saving message from {phone_num}: {e}")
        session.rollback()


async def send_async_message_status(from_number, filepath, success, message_type):
    msg_type_forms = {
        'text': 'текстовое сообщение',
        'image': 'изображение',
        'video': 'видео',
        'audio': 'аудио',
        'document': 'документ',
        'voice': 'голосовое сообщение',
        'others': 'другое сообщение',
    }

    if success:
        message_body = f"Вы отправили :{msg_type_forms.get(message_type)}, успешно сохранено в {filepath}"
    else:
        message_body = f"Не удалось сохранить {msg_type_forms.get(message_type)}, попробуйте еще раз"
    await send_text_message(from_number, message_body)


def insert_phone_number(phone_num: str, name: str, whatsapp_name: str):
    session = SessionLocal()
    try:
        existing = session.query(PhoneNumber).filter_by(phone_num=phone_num).first()
        if existing:
            logger.info(f"Phone number {phone_num} already exists with name {existing.name}.")
            return
        new_entry = PhoneNumber(
            phone_num=phone_num,
            name=name,
            whatsapp_name=whatsapp_name
        )
        session.add(new_entry)
        session.commit()
        logger.info(f"Inserted phone number {phone_num} with name {name} and WhatsApp name '{whatsapp_name}'.")
    except SQLAlchemyError as e:
        logger.error(f"Error inserting phone number {phone_num}: {e}")
        session.rollback()
    finally:
        session.close()


def test_connection():
    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            fetched = result.fetchone()
            print("Database connection successful:", fetched)
    except SQLAlchemyError as e:
        print("Database connection failed:", e)


def create_tables():
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully")

if __name__ == "__main__":
    test_connection()
    create_tables()
    app.run(host='0.0.0.0', port=3000)
