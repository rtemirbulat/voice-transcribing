import os
import re
from pydub import AudioSegment

# Directories with source files
input_folder = os.path.expanduser("~/Desktop/opus_files")
output_folder = os.path.expanduser("~/Desktop/wav_files")


# function to display files in directory with specific format or just all files in sorted manner
def display_files_in_directory(folder, file_format: None):
    files = [f for f in os.listdir(folder) if f.endswith(f".{file_format}" if file_format else "")]

    files_with_index = [
        (int(re.search(r"audio_(\d+)_", f).group(1)), f)
        for f in files if re.search(r"audio_(\d+)_", f)
    ]


    for index, filename in sorted(files_with_index):
        print(f"{filename}")


# function to change the audio file format from opus to wav using pydub
def convert_opus_to_wav(input_folder, output_folder, chunk_duration=30):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    for filename in os.listdir(input_folder):
        if filename.endswith(".opus"):
            old_path = os.path.join(input_folder, filename)
            new_filename = filename.replace(".opus", ".wav")
            new_path = os.path.join(output_folder, new_filename)

            audio = AudioSegment.from_file(old_path)
            audio.export(new_path, format="wav")

            print(f"Converted: {old_path} -> {new_path}")
    print("All files have been converted.")


# function to change filename from WhatsApp to specific format (audio_index_date_time)
# Пример вводных данных - Аудио 24  WhatsApp 2024-10-16 в 17.16.01_aa41c95e.waptt.opus
# Пример выходных данных - audio_24_2024-10-16_17-16
def rename_files_to_pattern(folder, start_index=1):
    pattern = r"Аудио\s+(\d+)\s+WhatsApp\s+(\d{4}-\d{2}-\d{2})\s+в\s+(\d{2})\.(\d{2})\.(\d{2})_(\w+)\.waptt\.opus"

    for filename in os.listdir(folder):
        match = re.match(pattern, filename)
        if match:
            new_filename = f"audio_{match.group(1)}_{match.group(2)}_{match.group(3)}-{match.group(4)}.opus"
            old_path = os.path.join(folder, filename)
            new_path = os.path.join(folder, new_filename)

            os.rename(old_path, new_path)
            print(f'Renamed: "{filename}" to "{new_filename}"')
        else:
            print(f'Skipped: "{filename}" (does not match the pattern)')


# print("Displaying files:")
# display_files_in_directory(input_folder, "opus")
#
# rename_files_to_pattern(input_folder, 6)
#
# print("\nConverting files to WAV:")
# convert_opus_to_wav(input_folder, output_folder)

print("Displaying files:")
display_files_in_directory(output_folder, "wav")

