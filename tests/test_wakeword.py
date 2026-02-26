import sys
import os

print("--- OpenWakeWord Logic Test ---")
try:
    from openwakeword.model import Model
    print("[1] Library Imported")
except ImportError:
    print("[FAIL] openwakeword not installed")
    sys.exit(1)

model_path = "./wakeword.onnx"
if not os.path.exists(model_path):
    print(f"[FAIL] Model file not found at {model_path}")
    sys.exit(1)

print(f"[2] Model found at {model_path}")

try:
    print("[3] Attempting Init with 'wakeword_model_paths'...")
    oww = Model(wakeword_model_paths=[model_path])
    print("[SUCCESS] Model Loaded with 'wakeword_model_paths'")
    sys.exit(0)
except TypeError as e:
    print(f"[WARN] Failed with 'wakeword_model_paths': {e}")

try:
    print("[3] Attempting Init with 'wakeword_models'...")
    oww = Model(wakeword_models=[model_path])
    print("[SUCCESS] Model Loaded with 'wakeword_models'")
    sys.exit(0)
except TypeError as e:
    print(f"[FAIL] All init attempts failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"[FAIL] Unexpected error: {e}")
    sys.exit(1)
