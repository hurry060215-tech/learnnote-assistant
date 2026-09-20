"""Exercise migration/restore only on a new snapshot, never on source data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-data', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--legacy-layout', action='store_true', help='Construct a pre-space layout by omitting copied learning spaces; never delete source data.')
    args = parser.parse_args()
    source, output = args.source_data.resolve(), args.output_dir.resolve()
    if output.exists() or output == source or output.is_relative_to(source) or source.is_relative_to(output):
        parser.error('Use a new independent output directory; overwrites are not allowed.')
    if not (source / 'study.sqlite3').is_file():
        parser.error('Source study database missing')
    target = output / 'data'
    target.mkdir(parents=True)
    fingerprints = {}
    for folder in ('courses','learning-spaces','personal-notes','materials','user-editions'):
        if args.legacy_layout and folder == 'learning-spaces':
            continue
        if (source / folder).is_dir():
            shutil.copytree(source / folder, target / folder)
            for path in (source / folder).rglob('*'):
                if path.is_file():
                    fingerprints[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    for task_path in (source / 'tasks').glob('*/task.json'):
        destination = target / 'tasks' / task_path.parent.name
        destination.mkdir(parents=True)
        for name in ('task.json','note.md','transcript.json','claim_evidence_map.json'):
            path = task_path.parent / name
            if path.is_file():
                shutil.copy2(path, destination / name)
                fingerprints[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('study.sqlite3','library.sqlite3'):
        path = source / name
        if not path.is_file():
            continue
        fingerprints[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        original = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        copy = sqlite3.connect(target / name)
        try:
            original.backup(copy)
        finally:
            copy.close()
            original.close()
    os.environ['LEARNNOTE_DATA_DIR'] = str(target)
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.study import export_study_data
    from app.learning_spaces import migrate_courses_to_learning_spaces, export_learning_space_data, restore_learning_space_data
    before = export_study_data()
    first = migrate_courses_to_learning_spaces()
    second = migrate_courses_to_learning_spaces()
    backup = export_learning_space_data()
    restored_first = restore_learning_space_data(backup)
    restored_second = restore_learning_space_data(backup)
    after_spaces = export_learning_space_data()
    after = export_study_data()
    keys = ('card_id','due_at','stability','difficulty','fsrs_state','fsrs_step','last_reviewed_at')
    def schedule(cards):
        return sorted(({k:card.get(k) for k in keys} for card in cards), key=lambda row:row['card_id'])
    checks = {
        'second_migration_creates_nothing':second['migrated'] == 0,
        'space_count_stable_on_repeated_restore':len(backup['spaces']) == len(after_spaces['spaces']),
        'source_count_stable':sum(len(s.get('sources',[])) for s in backup['spaces']) == sum(len(s.get('sources',[])) for s in after_spaces['spaces']),
        'card_count_preserved':len(before['cards']) == len(after['cards']),
        'review_history_preserved':digest(before['reviews']) == digest(after['reviews']),
        'fsrs_schedule_preserved':digest(schedule(before['cards'])) == digest(schedule(after['cards'])),
        'source_files_unchanged':all(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == h for p,h in fingerprints.items()),
    }
    report = {'status':'pass' if all(checks.values()) else 'fail','checks':checks,
              'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'cards':len(after['cards']), 'reviews':len(after['reviews']), 'spaces':len(after_spaces['spaces']),
              'first_migration':first,'second_migration':second,'first_restore':restored_first,'second_restore':restored_second,
              'constructed_legacy_layout':args.legacy_layout,
              'scope':'local real-data snapshot; model settings, browser profile and media excluded; copied source contents stay local'}
    (output / 'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
