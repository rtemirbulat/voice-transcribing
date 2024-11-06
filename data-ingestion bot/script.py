# transcription_script.py

import os
import requests
import logging
import pandas as pd
from datetime import datetime
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

def is_audio_file(filename):
    """Check if the file is an audio file based on its extension."""
    _, ext = os.path.splitext(filename)
    return ext.lower() in AUDIO_EXTENSIONS

def find_audio_files(directory):
    """Recursively find all audio files in the given directory."""
    audio_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if is_audio_file(file):
                full_path = os.path.join(root, file)
                audio_files.append(full_path)
    return audio_files

def send_audio_to_api(audio_path):
    """Send the audio file to the transcription API and return the transcribed text."""
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

def append_to_csv(filename, transcribed_text):
    """Append the transcription result to the CSV file."""
    try:
        # Check if CSV already exists
        if not os.path.isfile(RESULTS_CSV):
            # Create CSV with headers
            df = pd.DataFrame(columns=['filename', 'transcribed_text'])
            df.to_csv(RESULTS_CSV, index=False)
            logger.debug(f"Created new CSV file: {RESULTS_CSV}")

        # Append the new row
        df = pd.DataFrame([[filename, transcribed_text]], columns=['filename', 'transcribed_text'])
        df.to_csv(RESULTS_CSV, mode='a', header=False, index=False)
        logger.info(f"Appended transcription to CSV for file: {filename}")
    except Exception as e:
        logger.error(f"Failed to write to CSV for file {filename}: {e}")

# -------------------------------
# Main Processing Function
# -------------------------------

def process_audio_files():
    """Main function to process audio files and transcribe them."""
    logger.info("Starting audio transcription process.")

    # Step 1: Find all audio files
    audio_files = find_audio_files(MEDIA_DIR)
    logger.info(f"Found {len(audio_files)} audio files in '{MEDIA_DIR}' directory.")

    if not audio_files:
        logger.info("No audio files to process. Exiting.")
        return

    # Step 2: Process each audio file
    for audio_path in audio_files:
        filename = os.path.basename(audio_path)
        logger.info(f"Processing file: {filename}")

        # Step 2a: Send audio to transcription API
        transcribed_text = send_audio_to_api(audio_path)

        # Step 2b: Append result to CSV
        append_to_csv(filename, transcribed_text)

    logger.info("Completed audio transcription process.")

# -------------------------------
# Entry Point
# -------------------------------

if __name__ == "__main__":
    start_time = datetime.now()
    logger.info("Script started.")
    try:
        process_audio_files()
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}")
    finally:
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Script finished in {duration}.")
