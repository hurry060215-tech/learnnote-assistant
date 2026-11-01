"""Exercise the exact packaged PDF worker without opening a GUI or user data."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.media_process import owned_media_process
from app.pdf_limits import wait_for_pdf_worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', required=True)
    args = parser.parse_args()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>']
    data = bytearray(b'%PDF-1.4\n')
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += b'%d 0 obj\n' % index + obj + b'\nendobj\n'
    xref = len(data)
    data += b'xref\n0 4\n0000000000 65535 f \n'
    for offset in offsets:
        data += b'%010d 00000 n \n' % offset
    data += b'trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % xref
    with tempfile.TemporaryDirectory(prefix='learnnote-installed-pdf-') as directory:
        source, result = Path(directory) / 'input.pdf', Path(directory) / 'result.json'
        for content, valid in [(bytes(data), True), (b'%PDF-1.4\n startxref\n 28\n%%EOF\n xref\n 1 0\n aaa', False)]:
            source.write_bytes(content)
            result.unlink(missing_ok=True)
            with owned_media_process([args.executable, '--pdf-worker', str(source), str(result), '500', '5000000'],
                                     memory_limit_bytes=1024**3, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
                wait_for_pdf_worker(child, timeout=30, memory_bytes=1024**3)
                if child.returncode:
                    raise RuntimeError('Installed PDF worker failed')
            response = json.loads(result.read_bytes())
            if valid:
                assert response['parser_version'] == '6.21.4', response
                assert response['result'][2]['page_count'] == 1, response
            else:
                assert response == {'error': 'pdf_file_invalid'}, response
    print('PASS installed PDF worker: pypdf 6.21.4, valid page, truncated xref, bounded process')


if __name__ == '__main__':
    main()
