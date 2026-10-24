"""Records every input device at once for 6 seconds and ranks them by speech loudness."""
import time
import numpy as np
import sounddevice as sd

RATE = 16000
SECONDS = 6

devices = [(i, d) for i, d in enumerate(sd.query_devices())
           if d["max_input_channels"] > 0 and "Mapper" not in d["name"] and "Primary" not in d["name"]]

buffers: dict[int, list] = {}
streams = []
for i, d in devices:
    buffers[i] = []
    try:
        s = sd.InputStream(device=i, channels=1, samplerate=RATE, dtype="float32",
                           callback=lambda indata, f, t, st, i=i: buffers[i].append(indata.copy()))
        s.start()
        streams.append(s)
    except Exception as exc:
        print(f"  skip [{i}] {d['name'][:40]}: {str(exc)[:50]}")

print(f"\n>>> SPEAK NOW for {SECONDS} seconds — say a full sentence at normal volume <<<\n")
time.sleep(SECONDS)
for s in streams:
    s.stop(); s.close()

rows = []
for i, d in devices:
    if not buffers[i]:
        continue
    a = np.concatenate(buffers[i]).flatten()
    frames = a[: len(a) // 1600 * 1600].reshape(-1, 1600)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    noise, speech = float(np.percentile(rms, 10)), float(np.percentile(rms, 90))
    rows.append((speech / max(noise, 1e-6), i, d["name"][:45], noise, speech))

print("Index | Device                                         | noise  | speech | ratio")
for ratio, i, name, noise, speech in sorted(rows, reverse=True):
    print(f"{i:>5} | {name:<46} | {noise:.4f} | {speech:.4f} | {ratio:5.1f}x")
print("\nBest device = highest ratio. Put its index in .env as MIC_DEVICE=<index>")
