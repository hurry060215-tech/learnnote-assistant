"""Explicitly test the user's selected endpoint without printing/storing its key."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--connection-data', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['LEARNNOTE_DATA_DIR'] = str(output / 'data')
    sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
    from app import model_connections
    from app.models import TaskOptions
    # Only credential lookup is bound to the configured directory. All test
    # artifacts and cache configuration remain isolated in output/data.
    with patch.object(model_connections, 'DATA_DIR', args.connection_data.resolve()):
        status = model_connections.selected_connection_status()
        options = model_connections.resolve_model_options(TaskOptions())
        key = model_connections.connected_api_key(options)
    report = {'model':status.get('model'), 'key_available':bool(key), 'status':'blocked_missing_key', 'network_attempted':False}
    if key:
        from openai import OpenAI
        started = time.monotonic()
        try:
            client = OpenAI(api_key=key, base_url=options.llm_base_url, timeout=30, max_retries=0)
            report['network_attempted'] = True
            response = client.chat.completions.create(model=options.llm_model,
                messages=[{'role':'user','content':'Reply exactly LEARNNOTE_PROVIDER_OK.'}], max_tokens=24,
                extra_body={'thinking':{'type':'disabled'}} if status['model']['provider'] == 'deepseek' else {})
            answer = str(response.choices[0].message.content or '')
            report['status'] = 'pass' if 'LEARNNOTE_PROVIDER_OK' in answer else 'unexpected_response'
            report['usage'] = response.usage.model_dump() if response.usage else None
        except Exception as exc:
            report.update(status='fail', error_type=type(exc).__name__, http_status=getattr(exc,'status_code',None))
        report['elapsed_seconds'] = round(time.monotonic()-started,3)
    key = ''
    (output / 'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
