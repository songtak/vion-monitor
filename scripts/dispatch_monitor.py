#!/usr/bin/env python3
"""Trigger the automated test monitor without storing a GitHub token in a file."""
import json
import subprocess
import urllib.request


credential = subprocess.run(
    ['/usr/bin/git', 'credential', 'fill'],
    input='protocol=https\nhost=github.com\n\n',
    text=True,
    capture_output=True,
    check=True,
)
fields = dict(line.split('=', 1) for line in credential.stdout.splitlines() if '=' in line)
token = fields.get('password')
if not token:
    raise RuntimeError('GitHub credential not found')

request = urllib.request.Request(
    'https://api.github.com/repos/songtak/vion-monitor/dispatches',
    data=json.dumps({'event_type': 'vion-monitor-test'}).encode(),
    method='POST',
    headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
    },
)
with urllib.request.urlopen(request, timeout=30) as response:
    if response.status != 204:
        raise RuntimeError(f'GitHub dispatch failed: HTTP {response.status}')
