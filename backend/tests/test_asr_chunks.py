from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import wave

from app.asr_chunks import transcribe_windows


class ChunkedTranscriptionTests(unittest.TestCase):
    def test_completed_windows_survive_failure_and_resume_with_absolute_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / 'audio.wav'
            with wave.open(str(audio), 'wb') as stream:
                stream.setparams((1,2,2,0,'NONE','not compressed'))
                stream.writeframes(b'\0\0' * 1240)  # 620 seconds, three windows.
            calls = []
            fail = [True]
            class Model:
                def transcribe(self, path, vad_filter=True):
                    index = int(Path(path).stem)
                    calls.append(index)
                    if index == 600 and fail[0]:
                        raise MemoryError('fixture allocation failure')
                    return iter([SimpleNamespace(start=0,end=10,text='speech')]), SimpleNamespace(language='en')
            with self.assertRaises(MemoryError):
                transcribe_windows(audio, Model, 'fixture-model')
            self.assertEqual(calls, [0,600])
            fail[0] = False
            result = transcribe_windows(audio, Model, 'fixture-model')
            self.assertEqual(calls, [0,600,600,1200])
            self.assertEqual([s.start for s in result.segments], [0,300,600])
            self.assertEqual([s.end for s in result.segments], [10,310,610])
            transcribe_windows(audio, Model, 'fixture-model')
            self.assertEqual(len(calls), 4, 'all completed windows must be reused')
            transcribe_windows(audio, Model, 'different-model')
            self.assertEqual(len(calls), 7, 'model identity changes invalidate checkpoints')

    def test_malformed_checkpoint_is_recomputed(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / 'audio.wav'
            with wave.open(str(audio), 'wb') as stream:
                stream.setparams((1,2,2,0,'NONE','not compressed'))
                stream.writeframes(b'\0\0' * 20)
            calls = []
            class Model:
                def transcribe(self,path,vad_filter=True):
                    calls.append(path)
                    return iter([]), SimpleNamespace(language='en')
            transcribe_windows(audio,Model,'one')
            next((audio.parent/'asr-checkpoints').glob('*.json')).write_text('42')
            transcribe_windows(audio,Model,'one')
            self.assertEqual(len(calls), 2)
