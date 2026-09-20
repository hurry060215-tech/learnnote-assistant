"""Run commit-bound offline gates before packaging; retain every failure."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()
    if dirty:
        parser.error('Commit the source before recording reliability evidence.')
    env = dict(os.environ, LEARNNOTE_DATA_DIR=str(output / 'data'), LEARNNOTE_LLM_API_KEY='', PYTHONIOENCODING='utf-8')
    jobs = [('scheduler', 'scheduler-reliability.py', []), ('cancel', 'cancel-reliability.py', [])]
    for duration in (300, 1800, 3600, 10800):
        jobs.append((f'media-{duration}', 'long-video-reliability.py', [
            '--duration-seconds', str(duration), '--frame-interval', str(max(30, duration // 40)),
            '--max-frames', '40', '--memory-budget-mb', '512', '--min-free-disk-mb', '512', '--keep-artifacts']))
        jobs.append((f'full-{duration}', 'full-local-task-reliability.py', ['--duration-seconds', str(duration)]))
    report = {'commit': head, 'python': sys.version, 'mode': 'synthetic-media-fixture-summary',
              'dependencies': sorted(f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions()),
              'status': 'running', 'results': []}
    for label, script, extra in jobs:
        target = output / label
        command = [sys.executable, str(ROOT / 'scripts' / script), '--output-dir', str(target), *extra]
        started = time.monotonic()
        try:
            process = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=900)
            (output / f'{label}.log').write_bytes(process.stdout + process.stderr)
            detail_path = target / 'report.json'
            detail = json.loads(detail_path.read_text(encoding='utf-8')) if detail_path.is_file() else {}
            passed = process.returncode == 0 and detail.get('status') == 'pass'
            item = {'name': label, 'command': command, 'exit_code': process.returncode, 'status': 'pass' if passed else 'fail',
                    'report_sha256': hashlib.sha256(detail_path.read_bytes()).hexdigest() if detail else None}
        except (subprocess.TimeoutExpired, ValueError) as exc:
            item = {'name': label, 'command': command, 'status': 'fail', 'error': type(exc).__name__}
        item['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['results'].append(item)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(item), flush=True)
    unchanged = head == subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    clean = not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()
    report['source_unchanged'] = unchanged and clean
    report['status'] = 'pass' if unchanged and clean and all(r['status'] == 'pass' for r in report['results']) else 'fail'
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
