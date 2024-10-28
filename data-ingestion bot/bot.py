import os
import requests
from flask import Flask, request, jsonify

# Initialize Flask app
app = Flask(__name__)

ACCESS_TOKEN = ""
PHONE_NUMBER_ID = ""


@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        return verify_webhook()
    elif request.method == 'POST':
        return receive_message()

def verify_webhook():
    verify_token = "my_verify_token"
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == verify_token:
        print("Webhook verified successfully!")
        return challenge, 200
    else:
        print("Webhook verification failed.")
        return "Forbidden", 403

def receive_message():
    data = request.get_json()
    print(f"Received Data: {data}")

    if 'messages' in data['entry'][0]['changes'][0]['value']:
        message = data['entry'][0]['changes'][0]['value']['messages'][0]
        from_number = message['from']
        msg_body = message.get('text', {}).get('body', '')

        print(f"Message from {from_number}: {msg_body}")

        if message['type'] in ['image', 'document']:
            media_id = message[message['type']]['id']
            media_url = get_media_url(media_id)
            print(f"Media URL: {media_url}")
            download_media(media_url)

        send_message(from_number, "Message received!")

    return jsonify({"status": "success"}), 200

def get_media_url(media_id):
    url = f"https://graph.facebook.com/v21.0/{media_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers).json()
    return response.get("url")

#def download_media(media_url):

def send_message(to, message):
    url = f"https://graph.facebook.com/v16.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }

    response = requests.post(url, headers=headers, json=payload)
    print(f"Message sent to {to}: {response.status_code}, {response.text}")

if __name__ == "__main__":
    app.run(port=3000, debug=True)
