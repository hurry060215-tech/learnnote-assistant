"""Independent read-only verification of the completed synthetic two-hour run."""
from collections import Counter
from datetime import datetime
import argparse,hashlib,json
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--evidence-dir', type=Path, required=True, help='Completed run directory containing report, journal and data/tasks')
parser.add_argument('--driver', type=Path, required=True, help='Exact durable driver used by the run')
args=parser.parse_args()
root=args.evidence_dir
report=json.loads((root/'report.json').read_text())
assert report['status']=='pass', report['status']
assert report['server_stopped'] and report['writer_stopped']
assert report['terminal_observed'] and not report['terminal_deadline_expired']
assert report['elapsed_seconds']>=7200
assert report['verified_commit_sha']=='c31a507efdf9f38da9ba08e0bc1147d6c8d24731'
assert hashlib.sha256(args.driver.read_bytes()).hexdigest()==report['driver_sha256']
raw=(root/'received.jsonl').read_bytes();journal=[json.loads(x) for x in raw.splitlines()]
assert hashlib.sha256(raw).hexdigest()==report['received_journal_sha256']
terminal=[x for x in journal if x['event']=='task_terminal']
wire=[x for x in journal if x['event']!='task_terminal']
paths=list((root/'data/tasks').glob('*/events.jsonl'));assert len(paths)==1
rawdisk=paths[0].read_bytes();disk=[json.loads(x) for x in rawdisk.splitlines()]
expected=[dict(row,event_id=i) for i,row in enumerate(disk,1)]
assert [x['id'] for x in wire]==list(range(1,len(disk)+1))
assert [x['data'] for x in wire]==expected
assert json.loads((root/'received.json').read_text())==expected
assert len(terminal)==1 and terminal[0]['id']==len(disk) and terminal[0]['data']['status']=='success'
assert journal[-1]==terminal[0]
comparison=json.loads((root/'comparison.json').read_text())
assert comparison['exact_id_order'] and comparison['exact_payloads']
assert not any(comparison[k] for k in ('missing_ids','unexpected_ids','duplicate_ids'))
assert comparison['first_payload_mismatch'] is None
sequences=[x['details']['sequence'] for x in disk if 'sequence' in (x.get('details') or {})]
assert sequences==list(range(1,len(sequences)+1))
result={'passed':True,'source_sha':report['verified_commit_sha'],'received_events':len(wire),'disk_events':len(disk),'journal_records':len(journal),'terminal_events':len(terminal),'producer_events':len(sequences),'exact_id_order':True,'exact_payloads':True,'received_journal_sha256':hashlib.sha256(raw).hexdigest(),'disk_events_sha256':hashlib.sha256(rawdisk).hexdigest(),'independent_read_only':True,'reported_clean_shutdown':True,'finished_at':report['finished_at'],'scope':report['scope']}
(root/'independent-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
