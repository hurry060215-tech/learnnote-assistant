"""Restore one same-repository release candidate for non-publishing diagnostics.

The retained binary source and current test-harness source are separate identities.
A successful rerun is never current-source release acceptance. Downloads use only
GitHub's artifact-ID API; no caller-supplied URL or archive path is accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = '.github/workflows/desktop-release.yml'
INSTALLER = 'LearnNote-Setup-x64.exe'
MANIFEST = 'build/release/installer-candidate.json'
FRESHNESS = 'build/release/freshness.json'
AUDIT = 'build/release-tree-audit.json'
MEMBERS = {INSTALLER, MANIFEST, FRESHNESS, AUDIT}
MAX_INSTALLER_BYTES = 4 * 1024**3


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def gh_api(endpoint, output=None):
    command = ['gh', 'api', '--hostname', 'github.com', '-H', 'Accept: application/vnd.github+json',
               '-H', 'X-GitHub-Api-Version: 2022-11-28', endpoint]
    result = subprocess.run(command, stdout=output or subprocess.PIPE, stderr=subprocess.PIPE,
                            check=True, timeout=600)
    return None if output else json.loads(result.stdout)


def verify_origin(artifact, run, workflow, repository, artifact_id, source_commit):
    require(artifact.get('id') == int(artifact_id) and artifact.get('expired') is False,
            'Artifact identity or expiry mismatch')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', '')), 'Artifact SHA256 is required')
    require(type(artifact.get('size_in_bytes')) is int and 0 < artifact['size_in_bytes'] <= MAX_INSTALLER_BYTES,
            'Artifact size is invalid')
    origin = artifact.get('workflow_run') or {}
    require(run.get('id') == origin.get('id') and run.get('status') == 'completed'
            and run.get('conclusion') in ('success', 'failure'), 'Candidate run must be completed')
    repo, head_repo = run.get('repository') or {}, run.get('head_repository') or {}
    require(repo.get('full_name') == repository and head_repo.get('full_name') == repository
            and repo.get('id') == head_repo.get('id') == origin.get('repository_id') == origin.get('head_repository_id')
            and type(repo.get('id')) is int, 'Candidate repository mismatch')
    require(run.get('path') == WORKFLOW and workflow.get('path') == WORKFLOW
            and run.get('workflow_id') == workflow.get('id') and type(workflow.get('id')) is int,
            'Candidate workflow mismatch')
    require(run.get('event') == 'workflow_dispatch' and run.get('head_branch') == 'main'
            and origin.get('head_branch') == 'main', 'Candidate must originate from a manual main-branch release run')
    require(run.get('head_sha') == origin.get('head_sha') == source_commit,
            'Candidate source does not match original release workflow source')
    require(type(run.get('run_attempt')) is int and run['run_attempt'] > 0
            and artifact.get('name') == f"installer-candidate-{run['id']}-{run['run_attempt']}",
            'Candidate run attempt/name mismatch')


def verify_archive(archive, artifact, run, source_commit, release_tag, destination):
    require(sha256(archive) == artifact['digest'][7:], 'Artifact ZIP digest mismatch')
    require(archive.stat().st_size == artifact['size_in_bytes'], 'Artifact ZIP size mismatch')
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        require(len(members) == len(MEMBERS) and {x.filename for x in members} == MEMBERS,
                'Candidate archive must contain exactly the declared four files')
        for item in members:
            mode = stat.S_IFMT(item.external_attr >> 16)
            limit = MAX_INSTALLER_BYTES if item.filename == INSTALLER else 1024**2
            require(not item.is_dir() and mode in (0, stat.S_IFREG) and not item.flag_bits & 1
                    and 0 < item.file_size <= limit, 'Unsafe candidate archive member')
        manifest, freshness, audit = [json.loads(bundle.read(name).decode('utf-8-sig'))
                                      for name in (MANIFEST, FRESHNESS, AUDIT)]
        require(manifest.get('schema_version') == 1 and manifest.get('source_commit') == source_commit
                and manifest.get('release_tag') == release_tag and manifest.get('acceptance_status') == 'pending'
                and str(manifest.get('run_id')) == str(run['id'])
                and str(manifest.get('run_attempt')) == str(run['run_attempt'])
                and manifest.get('installer_name') == INSTALLER, 'Candidate manifest identity mismatch')
        require(type(manifest.get('installer_bytes')) is int
                and manifest['installer_bytes'] == bundle.getinfo(INSTALLER).file_size
                and re.fullmatch(r'[0-9a-f]{64}', manifest.get('installer_sha256', '')),
                'Candidate installer identity is invalid')
        require(freshness.get('schema_version') == 1 and freshness.get('status') == 'pass'
                and freshness.get('commit') == freshness.get('expected_commit') == source_commit
                and all(freshness.get(key) is True for key in
                        ('clean_checkout', 'matches_expected_commit', 'require_current_ref')),
                'Candidate source freshness did not pass')
        require(audit.get('passed') is True, 'Candidate bundle audit did not pass')
        for name in MEMBERS:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(name) as source, target.open('xb') as sink:
                shutil.copyfileobj(source, sink)
        require(sha256(destination / INSTALLER) == manifest['installer_sha256'], 'Candidate installer digest mismatch')
    return manifest


def restore(args):
    env = os.environ
    require(env.get('ACCEPTANCE_ONLY') == 'true' and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch',
            'Retained installers require acceptance-only manual diagnostics')
    require(re.fullmatch(r'[1-9][0-9]*', args.artifact_id) and re.fullmatch(r'[0-9a-f]{40}', args.source_commit)
            and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', args.release_tag), 'Invalid candidate identity arguments')
    repository = env.get('GITHUB_REPOSITORY', '')
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository), 'Invalid repository identity')
    harness = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout.strip()
    require(re.fullmatch(r'[0-9a-f]{40}', harness) and harness == env.get('GITHUB_SHA') == env.get('BUILD_COMMIT'),
            'Harness must match the dispatched workflow SHA')
    endpoint = f'repos/{repository}/actions/artifacts/{args.artifact_id}'
    artifact = gh_api(endpoint)
    name = re.fullmatch(r'installer-candidate-([1-9][0-9]*)-([1-9][0-9]*)', artifact.get('name', ''))
    require(name is not None, 'Invalid candidate artifact name')
    run = gh_api(f'repos/{repository}/actions/runs/{name[1]}/attempts/{name[2]}')
    workflow = gh_api(f'repos/{repository}/actions/workflows/desktop-release.yml')
    verify_origin(artifact, run, workflow, repository, args.artifact_id, args.source_commit)
    output = ROOT / 'build/release/retained-candidate'
    output.mkdir(parents=True, exist_ok=True)
    require(not (ROOT / INSTALLER).exists(), 'Refusing to replace an existing installer')
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        archive = stage / 'candidate.zip'
        with archive.open('xb') as sink:
            gh_api(endpoint + '/zip', sink)
        manifest = verify_archive(archive, artifact, run, args.source_commit, args.release_tag, stage / 'verified')
        for member in (MANIFEST, FRESHNESS, AUDIT):
            shutil.copyfile(stage / 'verified' / member, output / Path(member).name)
        shutil.copyfile(stage / 'verified' / INSTALLER, ROOT / INSTALLER)
    report = {'schema_version': 1, 'mode': 'retained-installer-diagnostic', 'current_source_acceptance': False,
              'scope': 'Existing binary diagnostics only; newer product-source changes require a fresh build and all release gates.',
              'repository': repository, 'workflow': WORKFLOW, 'artifact_id': int(args.artifact_id),
              'artifact_sha256': artifact['digest'][7:], 'candidate_source_commit': args.source_commit,
              'candidate_run_id': run['id'], 'candidate_run_attempt': run['run_attempt'],
              'harness_source_commit': harness, 'harness_run_id': env.get('GITHUB_RUN_ID'),
              'release_tag': args.release_tag, 'installer_sha256': manifest['installer_sha256']}
    (output / 'diagnostic-identity.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-id', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--release-tag', required=True)
    restore(parser.parse_args())
