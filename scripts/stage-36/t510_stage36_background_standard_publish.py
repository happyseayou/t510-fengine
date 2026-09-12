#!/usr/bin/env python3
"""Publish only completed, sealed acceptance evidence and browser-verify it."""
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
q=Path(sys.argv[1]);repo=Path(__file__).resolve().parents[2]
s=json.loads((q/'queue_state.json').read_text());assert s['status']=='completed' and s['verification_status']=='PASS'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
m=q/'queue_manifest.json';assert sha(m)==(q/'queue_manifest.sha256').read_text().split()[0];files={r['path']:r for r in json.loads(m.read_text())['files']}
web=q/'evidence/web'
for p in web.rglob('*'):
 if p.is_file():assert sha(p)==files[str(p.relative_to(q))]['sha256']
static=Path('/opt/t510-stage36-explorer/current/static');dest=static/'background-standard-data'
if dest.exists():raise RuntimeError('refuse overwriting prior acceptance dataset')
subprocess.run(['sudo','-n','cp','-a',str(web),str(dest)],check=True)
for name in ('background-standard.html','background-standard.js'):
 subprocess.run(['sudo','-n','install','-m644',str(repo/'scripts/stage-36/web/explorer'/name),str(static/name)],check=True)
subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('t510_stage36_background_standard_web_verify.py'))],check=True)
text=(static/'index.html').read_text();needle='        <div class="boundary"><a href="/static/ocb2.html">'
assert needle in text
text=text.replace(needle,'        <div class="boundary"><a href="/static/background-standard.html">标准背景处理：新八路50 Ω模板与独立检验 →</a></div>\n'+needle,1)
with tempfile.NamedTemporaryFile(mode='w',suffix='.html') as f:
 f.write(text);f.flush();subprocess.run(['sudo','-n','install','-m644',f.name,str(static/'index.html')],check=True)
print('PASS: sealed products published, browser verified, main page linked')
