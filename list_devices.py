import sounddevice as sd
devices = sd.query_devices()
for i, d in enumerate(devices):
    print(f"{i}: {d['name']}  IN:{d['max_input_channels']} OUT:{d['max_output_channels']}")
print(f"\nDefault input:  {sd.default.device[0]}")
print(f"Default output: {sd.default.device[1]}")
