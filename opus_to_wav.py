import os
import subprocess

input_folder = os.path.expanduser("~/Desktop/opus_files")
output_folder = os.path.expanduser("~/Desktop/wav_files")

for filename in os.listdir(input_folder):
    if filename.endswith(".opus"):
        input_path = os.path.join(input_folder, filename)
        output_path = os.path.join(output_folder, filename.replace(".opus", ".wav"))
        command = ['ffmpeg', '-i', f'{input_path}', f'{output_path}']
        subprocess.run(command, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
        print(f"Converted: {filename} -> {output_path}")

print("All files have been converted.")



