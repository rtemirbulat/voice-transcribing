# transcription_script.py

import os
import requests
import logging
from dotenv import load_dotenv

# -------------------------------
# Configuration Section
# -------------------------------
load_dotenv()
# Path to the media directory
MEDIA_DIR = os.getenv('MEDIA_DIR')

# Transcription API Endpoint
TRANSCRIPTION_API_URL = os.getenv("TRANSCRIPTION_API_URL")

# CSV File to Store Results
RESULTS_CSV = "results.csv"

# Log File Configuration
LOG_FILE = "script.log"

# Supported Audio File Extensions
AUDIO_EXTENSIONS = {'.wav'}

# -------------------------------
# Logging Configuration
# -------------------------------

# Create a logger
logger = logging.getLogger('TranscriptionLogger')
logger.setLevel(logging.DEBUG)  # Set to DEBUG to capture all types of log messages

# Create handlers
c_handler = logging.StreamHandler()  # Console handler
f_handler = logging.FileHandler(LOG_FILE)  # File handler

c_handler.setLevel(logging.INFO)  # Set console handler to INFO
f_handler.setLevel(logging.DEBUG)  # Set file handler to DEBUG

# Create formatters and add to handlers
c_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                             datefmt='%Y-%m-%d %H:%M:%S')
f_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                             datefmt='%Y-%m-%d %H:%M:%S')
c_handler.setFormatter(c_format)
f_handler.setFormatter(f_format)

# Add handlers to the logger
logger.addHandler(c_handler)
logger.addHandler(f_handler)

# -------------------------------
# Helper Functions
# -------------------------------

def is_wav(filename):
    """Check if the file is an audio file based on its extension."""
    _, ext = os.path.splitext(filename)
    return ext.lower() in AUDIO_EXTENSIONS

def send_audio_to_api(audio_path):
    """Send the audio file to the transcription API and return the transcribed text."""
    if is_wav(audio_path):
        try:
            with open(audio_path, 'rb') as audio_file:
                files = {
                    'file': (os.path.basename(audio_path), audio_file, 'audio/wav')  # Adjust MIME type if necessary
                }
                logger.debug(f"Sending audio file {audio_path} to transcription API.")
                response = requests.post(TRANSCRIPTION_API_URL, files=files, timeout=60)  # Timeout after 60 seconds

                if response.status_code == 200:
                    response_data = response.json()
                    transcribed_text = response_data.get('detection')  # Adjust based on API's response structure
                    if transcribed_text:
                        logger.debug(f"Received transcription for {audio_path}: {transcribed_text}")
                        return transcribed_text
                    else:
                        logger.warning(f"No 'transcript' field in API response for {audio_path}.")
                        return "Transcription unavailable."
                else:
                    logger.error(f"Transcription API returned status code {response.status_code} for {audio_path}: {response.text}")
                    return "Transcription failed."
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP request failed for {audio_path}: {e}")
            return "Transcription request error."
        except Exception as e:
            logger.error(f"Unexpected error while transcribing {audio_path}: {e}")
            return "Transcription error."
    else:
        return None