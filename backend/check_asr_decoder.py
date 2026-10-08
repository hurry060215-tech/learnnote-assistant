"""Exercise installed audio-decoder compatibility without network or model files."""
import os
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
from pathlib import Path
import tempfile
import wave


def main() -> None:
    import av
    from faster_whisper.audio import decode_audio

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sample.wav"
        with wave.open(str(path), "wb") as stream:
            stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            stream.writeframes(b"\0\0" * 8000)
        samples = decode_audio(str(path))
        if len(samples) != 8000:
            raise RuntimeError("Installed ASR decoder did not preserve the sample duration")
    print(f"ASR decoder compatible: PyAV {av.__version__}; no model downloaded")


if __name__ == "__main__":
    main()
