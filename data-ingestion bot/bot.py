import os
import json
import requests
import aiohttp
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify

app = Flask(__name__)

# Load environment variables
load_dotenv()
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
RECIPIENT_WAID = os.getenv("RECIPIENT_WAID")
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

    entry = data.get('entry', [])[0]
    changes = entry.get('changes', [])[0].get('value', {})
    messages = changes.get('messages', [])

    for message in messages:
        from_number = message.get('from')
        timestamp = datetime.fromtimestamp(int(message.get('timestamp')))
        formatted_time = timestamp.strftime('%Y-%m-%d_%H-%M-%S')

        if message['type'] == 'text':
            text = message['text']['body']
            print(f"Received text from {from_number}: {text}")
            save_message(from_number, text, formatted_time)

        elif message['type'] in ['image', 'video', 'audio', 'document']:
            media_id = message[message['type']]['id']
            media_url = get_media_url(media_id)
            media_type = message['type']
            download_media(media_url, media_type, from_number, formatted_time)

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

    # Determine the correct file extension
    if media_type == 'audio':
        extension = '.wav'
    elif media_type == 'image':
        extension = '.jpg'
    elif media_type == 'video':
        extension = '.mp4'
    elif media_type == 'document':
        extension = '.pdf'
    else:
        extension = '.media'

    # Construct the filename and path
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

# Asynchronous function to send a WhatsApp message
async def send_async_message(data):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ACCESS_TOKEN}",
    }
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as response:
            if response.status == 200:
                print("Async message sent successfully!")
                print(await response.text())
            else:
                print(f"Async send failed: {response.status}")
                print(await response.text())

def get_text_message_input(recipient, text):
    """Generate JSON payload for text message."""
    return {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    }

if __name__ == "__main__":
    # Test sending a message asynchronously
    text_data = get_text_message_input(RECIPIENT_WAID, "Hello from WhatsApp!")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(send_async_message(text_data))

    # Run Flask app
    app.run(port=3000, debug=True)

