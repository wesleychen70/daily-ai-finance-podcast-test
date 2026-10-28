"""Deploy the authorized public test project using GitHub CLI login, never print credentials."""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

from nacl.public import PublicKey, SealedBox

from podcast.common import GateError, load_env, save
from podcast.publish import github

load_env()
gh = Path('.tools/gh/bin/gh.exe').resolve()
if not gh.exists():
    gh = 'gh'
os.environ['GH_CONFIG_DIR'] = str(Path('.tools/gh-config').resolve())
result = subprocess.run([str(gh), 'auth', 'token'], capture_output=True, text=True)
if result.returncode:
    raise GateError('GitHub CLI login required')
token = result.stdout.strip()
os.environ['GH_TOKEN'] = token
user = github('GET', '/user').json()['login']
name = 'daily-ai-finance-podcast-test'
repo = user + '/' + name
# Reuse only the exact repository explicitly named for this project, never modify an unrelated repo.
from podcast.common import request
import requests
r = requests.get('https://api.github.com/repos/' + repo,
                 headers={'Authorization': 'Bearer ' + token}, timeout=30)
if r.status_code == 404:
    github('POST', '/user/repos', json={'name': name, 'private': False,
           'description': '每日 AI 財經 Podcast 自動化系統｜技術測試，未提交正式節目', 'auto_init': False})
elif r.status_code != 200:
    raise GateError('Cannot inspect test repository')
elif r.json().get('description') != '每日 AI 財經 Podcast 自動化系統｜技術測試，未提交正式節目':
    raise GateError('Existing repo is not recognized as this test project')

files = ['.gitignore', '.env.example', 'requirements.txt', 'README.md']
if Path('DEPLOYMENT_REPORT.md').exists():
    files.append('DEPLOYMENT_REPORT.md')
if Path('public/cover.jpg').exists():
    files.append('public/cover.jpg')
files += [str(p).replace('\\', '/') for root in ['podcast', 'scripts', 'tests', '.github']
          for p in Path(root).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
env = os.environ.copy()
# Pass credential through process environment, never a command argument or persistent git setting.
env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
           GIT_CONFIG_VALUE_0='AUTHORIZATION: basic ' + base64.b64encode(('x-access-token:' + token).encode()).decode(),
           GIT_TERMINAL_PROMPT='0')

def git(*args, check=True):
    r = subprocess.run(['git', *args], capture_output=True, text=True, env=env,
                       encoding='utf-8', errors='replace')
    if check and r.returncode:
        raise GateError('Git operation failed: ' + r.stderr.replace(token, '[REDACTED]')[-1000:])
    return r

remote_before = git('remote', 'get-url', 'origin', check=False)
expected_before = f'https://github.com/{repo}.git'
if remote_before.returncode == 0:
    if remote_before.stdout.strip() != expected_before:
        raise GateError('Existing origin points to a different repository')
    git('pull', '--ff-only', 'origin', 'codex/daily-finance-podcast')
if '--withdraw-current-test' in sys.argv:
    from podcast.feed import build_feed
    build_feed([], Path('public'), f'https://{user}.github.io/{name}')
    save('public/episodes.json', [])
    files += [str(p).replace('\\', '/') for p in Path('public').iterdir() if p.is_file()]
git('add', '--', *files)
diff = git('diff', '--cached', '--quiet', check=False)
if diff.returncode:
    git('-c', 'user.name=AI Finance Podcast Setup', '-c', 'user.email=setup@users.noreply.github.com',
        'commit', '-m', 'Build evidence-gated daily finance podcast test system')
git('branch', '-M', 'codex/daily-finance-podcast')
remote = git('remote', 'get-url', 'origin', check=False)
expected = f'https://github.com/{repo}.git'
if remote.returncode:
    git('remote', 'add', 'origin', expected)
elif remote.stdout.strip() != expected:
    raise GateError('Existing origin points to a different repository')
git('push', '-u', 'origin', 'codex/daily-finance-podcast')
key = github('GET', f'/repos/{repo}/actions/secrets/public-key').json()
encrypted = SealedBox(PublicKey(base64.b64decode(key['key']))).encrypt(os.environ['GEMINI_API_KEY'].encode())
github('PUT', f'/repos/{repo}/actions/secrets/GEMINI_API_KEY', json={
    'encrypted_value': base64.b64encode(encrypted).decode(), 'key_id': key['key_id']})
base = f'https://{user}.github.io/{name}'
variables = {'PIPELINE_ENABLED': 'true', 'PUBLIC_TEST_ENABLED': 'true', 'PAGES_BASE_URL': base}
if os.environ.get('PODCAST_OWNER_EMAIL'):
    import re
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', os.environ['PODCAST_OWNER_EMAIL']):
        raise GateError('Invalid public RSS contact email')
    variables['PODCAST_OWNER_EMAIL'] = os.environ['PODCAST_OWNER_EMAIL']
current = {v['name']: v for v in github('GET', f'/repos/{repo}/actions/variables').json()['variables']}
for key, value in variables.items():
    if key in current:
        github('PATCH', f'/repos/{repo}/actions/variables/{key}', json={'name': key, 'value': value})
    else:
        github('POST', f'/repos/{repo}/actions/variables', json={'name': key, 'value': value})
pages = requests.get('https://api.github.com/repos/' + repo + '/pages',
                     headers={'Authorization': 'Bearer ' + token}, timeout=30)
if pages.status_code == 404:
    github('POST', f'/repos/{repo}/pages', json={'build_type': 'workflow'})
elif pages.status_code != 200:
    raise GateError('Cannot inspect Pages configuration')
github('PUT', f'/repos/{repo}/actions/permissions/workflow', json={'default_workflow_permissions': 'write',
                                                               'can_approve_pull_request_reviews': False})
save('artifacts/deployment.json', {'repository': 'https://github.com/' + repo,
      'pages_base': base, 'rss': base + '/rss-test.xml', 'configured': True,
      'live_rss_verified': False, 'spotify_ingestion': 'NOT_RUN', 'formal_publication': False})
if '--dispatch' in sys.argv:
    github('POST', f'/repos/{repo}/actions/workflows/daily.yml/dispatches', json={'ref': 'codex/daily-finance-podcast'})
print('Configured TEST pipeline: https://github.com/' + repo)
