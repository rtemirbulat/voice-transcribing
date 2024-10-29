import os
import json
import requests
import aiohttp
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask import abort

app = Flask(__name__)

# Load environment variables
load_dotenv()
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERSION = os.getenv("VERSION")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

# Ensure necessary directories exist
os.makedirs("media", exist_ok=True)
os.makedirs("messages", exist_ok=True)

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
        print("Webhook verified successfully!")
        return challenge, 200
    else:
        print("Webhook verification failed.")
        return "Forbidden", 403

def handle_message():
    """Handle incoming messages and download media if present."""
    data = request.get_json()
    print(f"Received data: {json.dumps(data, indent=2)}")

    messages = []
    from_number = None

    # Extract messages from the incoming data
    try:
        entry = data['entry'][0]
        changes = entry['changes'][0]
        value = changes['value']
        messages = value.get('messages', [])
    except (KeyError, IndexError) as e:
        print("No messages found in the webhook data.")
        return jsonify({"status": "no_messages"}), 200

    # Initialize counts
    counts = {
        'text': 0,
        'image': 0,
        'video': 0,
        'audio': 0,
        'document': 0,
        'voice': 0,
        'others': 0
    }

    for message in messages:
        from_number = message.get('from')
        timestamp = datetime.fromtimestamp(int(message.get('timestamp')))
        formatted_time = timestamp.strftime('%Y-%m-%d_%H-%M-%S')
        message_type = message.get('type')

        if message_type == 'text':
            counts['text'] += 1
            text = message['text']['body']
            print(f"Received text from {from_number}: {text}")
            save_message(from_number, text, formatted_time)

        elif message_type in ['image', 'video', 'audio', 'document', 'voice']:
            counts[message_type] += 1
            media_id = message[message_type]['id']
            media_url = get_media_url(media_id)
            download_media(media_url, message_type, from_number, formatted_time)

        else:
            counts['others'] += 1
            print(f"Received {message_type} message from {from_number}")

    # After processing, send a reply
    if from_number:
        asyncio.run(send_reply(from_number, counts))

    return jsonify({"status": "received"}), 200

def get_media_url(media_id):
    """Retrieve media download URL from WhatsApp Cloud API."""
    url = f"https://graph.facebook.com/{VERSION}/{media_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers).json()
    return response.get('url')

def download_media(url, media_type, from_number, timestamp):
    """Download media files and save them with proper extensions."""
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

    filename = f"{from_number}_{media_type}_{timestamp}{extension}"
    filepath = os.path.join("media", filename)

    # Save the file
    with open(filepath, "wb") as f:
        for chunk in response.iter_content(1024):
            f.write(chunk)

    print(f"Media saved at: {filepath}")



def save_message(from_number, text, timestamp):
    """Save text messages to a file."""
    filename = f"{from_number}_{timestamp}.txt"
    filepath = os.path.join("messages", filename)

    with open(filepath, "w") as f:
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"From: {from_number}\n")
        f.write(f"Message: {text}\n")

    print(f"Message saved at: {filepath}")

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
                print("Async message sent successfully!")
                print(response_text)
            else:
                print(f"Async send failed: {response.status}")
                print(response_text)


def get_text_message_input(recipient, text):
    # Remove '+' sign
    formatted_recipient = recipient.lstrip('+')

    # Remove the first '7' (country code)
    if formatted_recipient.startswith('7'):
        formatted_recipient = formatted_recipient[1:]

    # Prepend '78' to the number
    formatted_recipient = '78' + formatted_recipient

    print(f"Formatted recipient number: {formatted_recipient}")
    return {
        "messaging_product": "whatsapp",
        "to": formatted_recipient,
        "type": "text",
        "text": {"body": text}
    }


async def send_reply(recipient_id, counts):
    """Send a reply message with the counts of received messages."""
    message_lines = []
    for msg_type, count in counts.items():
        if count > 0:
            message_lines.append(f"{count} {msg_type} message(s)")

    if message_lines:
        message_body = "Received:\n" + "\n".join(message_lines)
    else:
        message_body = "No messages received."

    data = get_text_message_input(recipient_id, message_body)

    await send_async_message(data)


if __name__ == "__main__":
    app.run(port=3000, debug=True)

