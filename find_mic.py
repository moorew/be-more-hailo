import sounddevice as sd

print("\n=== AUDIO DEVICES ===\n")
print(sd.query_devices())
print("\n=====================\n")

default_input = sd.default.device[0]
print(f"Default Input Device Index: {default_input}")
