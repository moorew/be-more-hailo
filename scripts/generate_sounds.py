import os
import subprocess

PIPER_CMD = "./piper/piper"
PIPER_MODEL = "./piper/en_GB-semaine-medium.onnx"

greetings = [
    "Hello! BMO is here!",
    "Who wants to play video games?",
    "BMO is ready for action!",
    "Yay! A new friend!",
    "BMO is online and feeling fine!",
    "Greetings, human!",
    "BMO is powered up!",
    "Let's go on an adventure!",
    "BMO is happy to see you!",
    "System check complete. BMO is perfect!",
    "Hello! What game are we playing today?",
    "BMO is awake!",
    "I am a little living robot!",
    "BMO is ready to help!",
    "Hello! Do you have any batteries?",
    "BMO is here to save the day!",
    "Yay! You're back!",
    "BMO is fully charged!",
    "Hello! Let's do something fun!",
    "BMO is ready to compute!"
]

thinking = [
    "Hmm... BMO is processing...",
    "Let me check my memory banks...",
    "BMO is thinking very hard...",
    "Calculating...",
    "One moment, please...",
    "BMO is searching for the answer...",
    "Let me see...",
    "Processing data...",
    "BMO is computing...",
    "Hold on, BMO is thinking...",
    "Let me look that up...",
    "BMO is accessing the mainframe...",
    "Thinking...",
    "Let me ponder that...",
    "BMO is analyzing the situation...",
    "Just a second...",
    "BMO is running a diagnostic...",
    "Let me figure this out...",
    "BMO is working on it...",
    "Processing..."
]

def generate_audio(text, filename):
    print(f"Generating {filename}...")
    # Replace BMO with Beemo for correct pronunciation
    text = text.replace("BMO", "Beemo")
    safe_text = text.replace("'", "'\\''")
    cmd = f"echo '{safe_text}' | {PIPER_CMD} --model {PIPER_MODEL} --output_file {filename}"
    subprocess.run(cmd, shell=True, check=True)

os.makedirs("sounds/greeting_sounds", exist_ok=True)
os.makedirs("sounds/thinking_sounds", exist_ok=True)

for i, text in enumerate(greetings):
    generate_audio(text, f"sounds/greeting_sounds/greeting_{i+1:02d}.wav")

for i, text in enumerate(thinking):
    generate_audio(text, f"sounds/thinking_sounds/thinking_{i+1:02d}.wav")

print("Done!")
