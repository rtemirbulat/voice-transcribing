import os
from pydub import AudioSegment

input_folder = os.path.expanduser("~/Desktop/opus_files")
output_folder = os.path.expanduser("~/Desktop/wav_files")

def speech_to_text(filename, chunk_duration=30):
    file, format_ = filename.split(".")
    if format_ == "opus":
        audio = AudioSegment.from_file(filename)
        newfilename = file + ".wav"
        audio.export(newfilename, format="wav")



for filename in os.listdir(input_folder):
    old = os.path.join(input_folder, filename)
    new = speech_to_text(old)
    print(f"Converted: {old} -> {new}")
print("All files have been converted.")
