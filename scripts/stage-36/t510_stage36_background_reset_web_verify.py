#!/usr/bin/env python3
"""Browser checks for the fixed-background experiment page, on GB10."""
import base64,json,subprocess,time,os,math,urllib.request
from pathlib import Path
from urllib.error import HTTPError
from t510_stage36_formula_layout_verify import request,execute,wait_until
out=Path('/home/astrolab/.cache/t510/background-reset-web-check-20260911');out.mkdir(exist_ok=True)
d='http://127.0.0.1:19531';p=subprocess.Popen(['/snap/chromium/current/usr/lib/chromium-browser/chromedriver','--port=19531'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);s=None
try:
 wait_until(lambda:request('GET',d+'/status'))
 profile=Path.home()/'snap/chromium/common/t510-holdout-verify'/str(os.getpid());profile.mkdir(parents=True)
 s=request('POST',d+'/session',{'capabilities':{'alwaysMatch':{'browserName':'chrome','goog:chromeOptions':{'binary':'/snap/chromium/current/usr/lib/chromium-browser/chrome','args':['--headless=new','--no-sandbox','--disable-dev-shm-usage','--window-size=1600,1100','--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader',f'--user-data-dir={profile}']}}}})['sessionId']
 run=lambda js:execute(d,s,js)
 request('POST',f'{d}/session/{s}/url',{'url':'http://127.0.0.1:8036/static/background-reset.html'})
 wait_until(lambda:run('return window.resetReady===true'))
 assert run("return document.querySelectorAll('#pair option').length===28 && document.querySelectorAll('#allTable tr').length===28")
 assert run("return document.getElementById('amp').data.length===3 && document.getElementById('amp').data.every(t=>t.x.length===5400&&t.x[5399]===539.95)")
 with urllib.request.urlopen('http://127.0.0.1:8036/static/background-reset-data/trends/1-0-2-3073.json') as f:native=json.load(f)
 plotted=run("return [document.getElementById('amp').data.map(t=>t.y),document.getElementById('phase').data.map(t=>t.y),document.getElementById('minute').data.map(t=>t.y)]")
 for j,key in enumerate(('none','old','new')):
  b=[0,0] if key=='none' else native[key]
  for i,(re,im) in enumerate(zip(native['real'],native['imag'])):
   re-=b[0];im-=b[1]
   assert abs(plotted[0][j][i]-math.hypot(re,im))<1e-10
   assert abs(plotted[1][j][i]-math.degrees(math.atan2(im,re)))<1e-10
  for i,m in enumerate(native['minutes']):assert abs(plotted[2][j][i]-100*math.hypot(m['real']-b[0],m['imag']-b[1])/math.sqrt(m['power_a']*m['power_b']))<1e-10
 run("document.getElementById('native').scrollIntoView()")
 time.sleep(1)
 (out/'amplitude.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 run("document.getElementById('phase').scrollIntoView()")
 time.sleep(1)
 (out/'phase.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 e=request('POST',f'{d}/session/{s}/element',{'using':'css selector','value':'#phase .legendtoggle'})
 request('POST',f'{d}/session/{s}/element/{e["element-6066-11e4-a52e-4f735466cecf"]}/click',{})
 wait_until(lambda:run("return window.resetReady&&['amp','phase','minute'].every(id=>document.getElementById(id).data[0].visible==='legendonly')"))
 run("document.getElementById('showAll').click()")
 wait_until(lambda:run("return window.resetReady&&document.getElementById('amp').data[0].visible===true"))
 run("document.querySelectorAll('#rounds input').forEach(x=>x.checked=true);document.querySelector('#rounds input').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return window.resetReady&&document.getElementById('amp').data.length===9"))
 run("document.getElementById('policy').value='new';document.getElementById('policy').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return window.resetReady&&document.getElementById('phase').data.length===3"))
 run("document.getElementById('pair').value='5-7';document.getElementById('pair').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return window.resetReady&&document.getElementById('status').textContent.includes('ADC5–ADC7')"))
 run("document.getElementById('bin').value='3182';document.getElementById('bin').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return window.resetReady&&document.getElementById('status').textContent.includes('bin3182')"))
 request('POST',f'{d}/session/{s}/window/rect',{'width':430,'height':950});time.sleep(1)
 run("document.getElementById('phase').scrollIntoView()")
 assert run('return document.documentElement.scrollWidth<=innerWidth+1')
 (out/'mobile.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 (out/'verification.json').write_text(json.dumps({'status':'PASS','checks':['28pairs','native5400 points','16200 amplitude/phase values and27minute points match independent formulas','real legend click sync','three rounds overlay','policy,pair,bin switch','mobile no horizontal overflow']}))
 print('PASS')
finally:
 if s:request('DELETE',f'{d}/session/{s}')
 p.terminate()
