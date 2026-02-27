import sounddevice as sd
import numpy as np
import scipy.io.wavfile

MIC_SAMPLE_RATE = 48000
MIC_DEVICE_INDEX = 1

def record_audio():
    print("Recording 3s test...")
    filename = "test_audio.wav"
    frames = []

    def callback(indata, frames_count, time, status):
        vol = np.linalg.norm(indata) * 10 
        print(f"Vol: {vol}")
        frames.append(indata.copy())
        
    try:
        with sd.InputStream(samplerate=MIC_SAMPLE_RATE, device=MIC_DEVICE_INDEX, channels=1, dtype='int16', callback=callback):
            sd.sleep(3000)
    except Exception as e:
        print(f"Recording Error: {e}")
        return None
    
    data = np.concatenate(frames, axis=0)
    scipy.io.wavfile.write(filename, MIC_SAMPLE_RATE, data)
    print(f"Saved {filename}")

if __name__ == "__main__":
    record_audio()
