import asyncio
import json
import logging
import os
import re
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

import aiohttp
import pytz
import requests
import json
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from pydub import AudioSegment
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, ForeignKey, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from script import send_audio_to_api

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

# Load json bot responses
with open('bot_responses.json', 'r', encoding='utf-8') as f:
    MESSAGES = json.load(f)

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

# SQLAlchemy setup
engine = create_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# DB models
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
    result = relationship("Result", uselist=False, back_populates="message")
    phone_number_ref = relationship("PhoneNumber", back_populates="messages")


class Result(Base):
    __tablename__ = 'results'

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey('messages.id'))
    audio_file_path = Column(String, nullable=False)
    audio_file_name = Column(String, nullable=False)
    models_output = Column(Text, nullable=True)
    corrected = Column(Boolean, default=False)
    human_output = Column(Text, nullable=True)

    message = relationship("Message", back_populates="result")


# To verify webhooks
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        return verify_webhook()
    elif request.method == 'POST':
        return handle_message()


# Use token in WA API to verify webhook
def verify_webhook():
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully!")
        return challenge, 200
    else:
        logger.warning("Webhook verification failed.")
        return "Forbidden", 403


# Test connection to DB
def test_connection():
    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            fetched = result.fetchone()
            print("Database connection successful:", fetched)
    except SQLAlchemyError as e:
        print("Database connection failed:", e)


# Create tables if needed
def create_tables():
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully")


# Main functionality
def handle_message():
    messages = []
    from_number = None
    has_attachments = False
    attachment_links = []

    data = request.get_json()
    logger.debug(f"Received data: {json.dumps(data)}")

    try:
        entry = data['entry'][0]
        changes = entry['changes'][0]
        value = changes['value']
        messages = value.get('messages', [])
    except (KeyError, IndexError) as e:
        logger.info("No messages found in the webhook data.")
        return jsonify({"status": "no_messages"}), 200
    # Main driver loop
    session = SessionLocal()
    try:
        for message in messages:
            # Timezone
            from_number = message.get('from')
            timestamp = datetime.fromtimestamp(int(message.get('timestamp')), pytz.utc)
            # Convert to UTC+5
            utc_plus_5 = pytz.timezone('Asia/Yekaterinburg')  # Replace with the appropriate time zone
            timestamp = timestamp.astimezone(utc_plus_5)
            # Make the datetime naive by removing the tzinfo
            timestamp_naive = timestamp.replace(tzinfo=None)
            formatted_time = timestamp_naive.strftime('%Y-%m-%d %H:%M:%S')
            message_type = message.get('type')
            message_body = message.get('text', {}).get('body', '').lower()

            if from_number not in user_sessions:
                user_sessions[from_number] = {
                    'authenticated': False,
                    'awaiting_password': False,
                    'awaiting_confirmation': False,
                    'awaiting_correction': False,
                    'detection': '',
                    'result_id': None,
                    'language': None,
                    'awaiting_language_selection': False
                }

            is_authenticated = user_sessions[from_number]['authenticated']
            awaiting_password = user_sessions[from_number]['awaiting_password']

            # Language selection
            if user_sessions[from_number]['language'] is None:
                if not user_sessions[from_number]['awaiting_language_selection']:
                    asyncio.run(prompt_language_selection(from_number))
                else:
                    # Handle user's language selection
                    user_response = message_body
                    if user_response == '1':
                        user_sessions[from_number]['language'] = 'kk'
                        user_sessions[from_number]['awaiting_language_selection'] = False
                        # Proceed with authentication prompt
                        asyncio.run(send_authentication_prompt(from_number))
                    elif user_response == '2':
                        user_sessions[from_number]['language'] = 'ru'
                        user_sessions[from_number]['awaiting_language_selection'] = False
                        # Proceed with authentication prompt
                        asyncio.run(send_authentication_prompt(from_number))
                    else:
                        # Invalid input, ask the user to select again
                        asyncio.run(prompt_language_selection(from_number, invalid=True))
                return jsonify({"status": "language_selection_handled"}), 200

            language = user_sessions[from_number]['language']

            # Auth handling
            if message_type == 'text' and message_body.lower() in ['start', 'старт']:
                asyncio.run(send_authentication_prompt(from_number))
                user_sessions[from_number]['awaiting_password'] = True
                return jsonify({"status": "password_requested"}), 200

            if message_type == 'text' and awaiting_password:
                entered_password = message.get('text', {}).get('body', '')
                if entered_password == AUTH_PASSWORD:
                    user_sessions[from_number]['authenticated'] = True
                    user_sessions[from_number]['awaiting_password'] = False
                    success_message = get_message_text('authentication_success', language)
                    asyncio.run(send_text_message(from_number, success_message))
                else:
                    user_sessions[from_number]['authenticated'] = False
                    user_sessions[from_number]['awaiting_password'] = False
                    failure_message = get_message_text('incorrect_code', language)
                    asyncio.run(send_text_message(from_number, failure_message))
                return jsonify({"status": "authentication_attempted"}), 200

            if not is_authenticated and not awaiting_password:
                logger.info(f"User {from_number} is not authenticated. Prompting to register.")
                auth_required_msg = get_message_text('authentication_required', language)
                asyncio.run(send_text_message(from_number, auth_required_msg))
                return jsonify({"status": "not_authenticated"}), 200

            # Confirmation for our model to re-train it back again
            if message_type == 'text' and user_sessions[from_number].get('awaiting_confirmation'):
                user_response = message_body.strip().lower()
                result_id = user_sessions[from_number]['result_id']

                affirmative = ['иә'] if language == 'kk' else ['да']
                negative = ['жоқ'] if language == 'kk' else ['нет']

                if user_response in affirmative:
                    confirmation_message = get_message_text('confirmation_thanks', language)
                    asyncio.run(send_text_message(from_number, confirmation_message))
                    # Update the Result record
                    update_result(session, result_id, corrected=False)
                    # Reset the session state
                    user_sessions[from_number]['awaiting_confirmation'] = False
                    user_sessions[from_number]['detection'] = ''
                    user_sessions[from_number]['result_id'] = None
                elif user_response in negative:
                    correction_prompt = get_message_text('correction_prompt', language)
                    asyncio.run(send_text_message(from_number, correction_prompt))
                    # Update session to expect corrected text
                    user_sessions[from_number]['awaiting_correction'] = True
                    user_sessions[from_number]['awaiting_confirmation'] = False
                else:
                    retry_message = get_message_text('confirmation_retry', language)
                    asyncio.run(send_text_message(from_number, retry_message))
                return jsonify({"status": "confirmation_received"}), 200

            if message_type == 'text' and user_sessions[from_number].get('awaiting_correction'):
                corrected_text = message_body
                result_id = user_sessions[from_number]['result_id']
                # Update the Result record
                update_result(session, result_id, corrected=True, human_output=corrected_text)
                correction_thanks = get_message_text('correction_thanks', language)
                asyncio.run(send_text_message(from_number, correction_thanks))
                user_sessions[from_number]['awaiting_correction'] = False
                user_sessions[from_number]['detection'] = ''
                user_sessions[from_number]['result_id'] = None
                return jsonify({"status": "correction_received"}), 200

            #  For text messages:
            if message_type == 'text':
                text = message['text']['body']
                logger.info(f"Received text from {from_number}: {text}")
                save_message_to_db(
                    session=session,
                    phone_num=from_number,
                    message_text=text,
                    has_attachments=False,
                    attachment_links='',
                    date_time=timestamp
                )
                await_response = get_message_text('text_received', language).format(text=text)
                asyncio.run(save_message(from_number, text, formatted_time))
                asyncio.run(send_text_message(from_number, await_response))
            # For audio files:
            elif message_type in ['audio', 'voice']:
                media_id = message[message_type]['id']
                media_url = get_media_url(media_id)
                filepath, filename, success = download_media(media_url, message_type, from_number, timestamp)
                if success:
                    has_attachments = True
                    attachment_links = filepath
                    detection = send_audio_to_api(filepath)

                    message_entry = save_message_to_db(
                        session=session,
                        phone_num=from_number,
                        message_text='',
                        has_attachments=True,
                        attachment_links=filepath,
                        date_time=timestamp,
                        detected_audio=detection
                    )

                    if message_entry:
                        result_entry = Result(
                            message_id=message_entry.id,
                            audio_file_path=filepath,
                            audio_file_name=filename,
                            models_output=detection,
                            corrected=False,
                            human_output=None
                        )
                        session.add(result_entry)
                        session.commit()

                        asyncio.run(ask_user_for_confirmation(from_number, detection, result_entry.id))
                    else:
                        logger.error("Failed to save message to database.")
                else:
                    error_message = get_message_text('media_save_error', language)
                    asyncio.run(send_async_message_status(from_number, filepath, success, message_type))


            elif message_type in ['image', 'video', 'document']:
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
                    media_saved_message = get_message_text('media_saved', language).format(filepath=filepath)
                    asyncio.run(send_text_message(from_number, media_saved_message))
                else:
                    error_message = get_message_text('media_save_error', language)
                    asyncio.run(send_text_message(from_number, error_message))

            else:
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
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        logger.debug("Exception info:", exc_info=True)
        # Return 200 OK to prevent message retries
        return jsonify({"status": "error", "message": str(e)}), 200
    finally:
        session.close()  # TO-DO: discover why we need close user sessions


def get_media_url(media_id):
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

    content_type = response.headers.get('Content-Type', '')
    logger.info(f"Content-Type: {content_type}")

    content_type_mapping = {
        # Audio MIME types
        'audio/mpeg': ('.mp3', 'mp3'),
        'audio/mp3': ('.mp3', 'mp3'),
        'audio/ogg': ('.ogg', 'ogg'),
        'audio/opus': ('.opus', 'opus'),
        'audio/x-m4a': ('.m4a', 'm4a'),
        'audio/aac': ('.aac', 'aac'),
        'audio/wav': ('.wav', 'wav'),
        'audio/x-wav': ('.wav', 'wav'),
        'audio/webm': ('.webm', 'webm'),
        # Image MIME types
        'image/jpeg': ('.jpg', None),
        'image/png': ('.png', None),
        'image/gif': ('.gif', None),
        'image/bmp': ('.bmp', None),
        'image/webp': ('.webp', None),

        # Video MIME types
        'video/mp4': ('.mp4', None),
        'video/quicktime': ('.mov', None),
        'video/x-msvideo': ('.avi', None),
        'video/x-matroska': ('.mkv', None),

        # Document MIME types
        'application/pdf': ('.pdf', None),
        'application/msword': ('.doc', None),
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ('.docx', None),
        'application/vnd.ms-excel': ('.xls', None),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ('.xlsx', None),

    }
    if content_type in content_type_mapping:
        extension, audio_format = content_type_mapping[content_type]
    else:
        extension = '.media'
        audio_format = None

    date_str = timestamp.strftime('%Y-%m-%d')
    time_str = timestamp.strftime('%H-%M-%S')
    phone_dir = os.path.join("media", from_number, date_str)
    os.makedirs(phone_dir, exist_ok=True)
    sequence_number = get_next_sequence_number(phone_dir, media_type)

    original_filename = f"{media_type}_{sequence_number}_{time_str}{extension}"
    original_filepath = os.path.join(phone_dir, original_filename)

    try:
        with open(original_filepath, "wb") as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        logger.info(f"Media saved at: {original_filepath}")
        success = True
        # Convert every audio or voice to wav
        if media_type in ['audio', 'voice'] and audio_format is not None:
            try:
                audio = AudioSegment.from_file(original_filepath, format=audio_format)

                wav_filename = f"{media_type}_{sequence_number}_{time_str}.wav"
                wav_filepath = os.path.join(phone_dir, wav_filename)

                audio.export(wav_filepath, format="wav", bitrate="192k")

                logger.info(f"Converted audio saved at: {wav_filepath}")

                os.remove(original_filepath)
                logger.info(f"Deleted original file: {original_filepath}")

                return wav_filepath, wav_filename, True

            except Exception as e:
                logger.error(f"Failed to convert audio to WAV: {e}")
                return original_filepath, original_filename, False

        else:
            return original_filepath, original_filename, True

    except Exception as e:
        logger.error(f"Failed to save media: {e}")
        success = False
        original_filepath = None
        return original_filepath, original_filename, success


def get_text_message_input(recipient, text):
    formatted_recipient = recipient.lstrip('+')

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


def save_message_to_db(session, phone_num, message_text, has_attachments, attachment_links, date_time,
                       detected_audio=None):
    phone_entry = get_or_create_phone_number(session, phone_num)
    if not phone_entry:
        logger.error(f"Failed to retrieve or create phone number entry for {phone_num}. Skipping message save.")
        return None
    message_entry = Message(
        phone_num=phone_num,
        message_text=message_text,
        hasAttachments=has_attachments,
        attachment_links=attachment_links,
        date_time=date_time,
        detected_audio=detected_audio
    )
    session.add(message_entry)
    try:
        session.commit()
        logger.info(f"Saved message from {phone_num} to database.")
        return message_entry
    except SQLAlchemyError as e:
        logger.error(f"Error saving message from {phone_num}: {e}")
        session.rollback()
        return None


def get_message_text(message_key, language):
    return MESSAGES.get(message_key, {}).get(language, '')


def update_result(session, result_id, corrected, human_output=None):
    """Update the Result record based on user's confirmation or correction.

    Args:
        session: Database session.
        result_id: ID of the Result record.
        corrected: Boolean indicating if the result was corrected.
        human_output: The corrected text provided by the user (if any).
    """
    try:
        result_entry = session.query(Result).filter_by(id=result_id).first()
        if result_entry:
            result_entry.corrected = corrected
            result_entry.human_output = human_output
            session.commit()
            logger.info(f"Updated result with id {result_id}. Corrected: {corrected}")
        else:
            logger.warning(f"No result entry found with id: {result_id}")
    except SQLAlchemyError as e:
        logger.error(f"Error updating result with id {result_id}: {e}")
        session.rollback()

def get_or_create_phone_number(session, phone_num):

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


# Response message
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


async def prompt_language_selection(from_number, invalid=False):
    if invalid:
        message_body = get_message_text('language_invalid', 'kk')
    else:
        message_body = get_message_text('language_prompt', 'kk')
    await send_text_message(from_number, message_body)

    user_sessions[from_number]['awaiting_language_selection'] = True


async def send_authentication_prompt(from_number):
    language = user_sessions[from_number]['language']
    message_body = get_message_text('authentication_prompt', language)
    await send_text_message(from_number, message_body)
    user_sessions[from_number]['awaiting_password'] = True


async def ask_user_for_confirmation(from_number, detection, result_id):
    language = user_sessions[from_number]['language']
    if language == 'kk':
        message_body = f"Біз танылдық: \"{detection}\". Бұл дұрыс па? 'Иә' немесе 'жоқ' деп жауап беріңіз."
    elif language == 'ru':
        message_body = f"Мы распознали: \"{detection}\". Это правильно? Пожалуйста, ответьте 'да' или 'нет'."
    else:
        message_body = f"Мы распознали: \"{detection}\". Это правильно? Пожалуйста, ответьте 'да' или 'нет'."
    await send_text_message(from_number, message_body)
    # Update user session to expect confirmation
    user_sessions[from_number]['awaiting_confirmation'] = True
    user_sessions[from_number]['detection'] = detection
    user_sessions[from_number]['result_id'] = result_id


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

async def save_message(from_number, text, timestamp):
    filename = f"{from_number}.txt"
    filepath = os.path.join("messages", filename)

    message_content = f"Timestamp: {timestamp}\nFrom: {from_number}\nMessage: {text}\n\n"

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(message_content)


async def send_text_message(from_number, message_body):
    data = get_text_message_input(from_number, message_body)
    await send_async_message(data)


if __name__ == "__main__":
    test_connection()
    create_tables()
    app.run(host='0.0.0.0', port=3000)
