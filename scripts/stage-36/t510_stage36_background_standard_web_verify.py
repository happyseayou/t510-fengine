#!/usr/bin/env python3
"""Browser checks for the fixed-background experiment page, on GB10."""
import base64,json,subprocess,time,os,math,urllib.request
from pathlib import Path
from urllib.error import HTTPError
from t510_stage36_formula_layout_verify import request,execute,wait_until
out=Path('/home/astrolab/.cache/t510/background-standard-web-check-20260912');out.mkdir(exist_ok=True)
d='http://127.0.0.1:19531';p=subprocess.Popen(['/snap/chromium/current/usr/lib/chromium-browser/chromedriver','--port=19531'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);s=None
try:
 wait_until(lambda:request('GET',d+'/status'))
 profile=Path.home()/'snap/chromium/common/t510-holdout-verify'/str(os.getpid());profile.mkdir(parents=True)
 s=request('POST',d+'/session',{'capabilities':{'alwaysMatch':{'browserName':'chrome','goog:chromeOptions':{'binary':'/snap/chromium/current/usr/lib/chromium-browser/chrome','args':['--headless=new','--no-sandbox','--disable-dev-shm-usage','--window-size=1600,1100','--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader',f'--user-data-dir={profile}']}}}})['sessionId']
 run=lambda js:execute(d,s,js)
 request('POST',f'{d}/session/{s}/url',{'url':'http://127.0.0.1:8036/static/background-standard.html'})
 wait_until(lambda:run('return window.backgroundReady===true'))
 assert run("return document.querySelectorAll('#pair option').length===28 && document.getElementById('amp').data.length===2")
 native=json.load(urllib.request.urlopen('http://127.0.0.1:8036/static/background-standard-data/trends/validation-0-1-3201.json'))
 plotted=run("return [document.getElementById('amp').data[1].y,document.getElementById('phase').data[1].y]")
 for i,(re,im) in enumerate(zip(native['real'],native['imag'])):
  re-=native['background'][0];im-=native['background'][1]
  assert abs(plotted[0][i]-math.hypot(re,im))<1e-9
  assert abs(plotted[1][i]-math.degrees(math.atan2(im,re)))<1e-9
 run("document.getElementById('onlyOff').click()")
 wait_until(lambda:run("return window.backgroundReady && document.getElementById('amp').data.length===2"))
 run("document.getElementById('amp').scrollIntoView()")
 time.sleep(1)
 (out/'off.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 e=request('POST',f'{d}/session/{s}/element',{'using':'css selector','value':'#amp .legendtoggle'})
 request('POST',f'{d}/session/{s}/element/{e["element-6066-11e4-a52e-4f735466cecf"]}/click',{})
 wait_until(lambda:run("return window.backgroundReady&&['amp','phase'].every(id=>document.getElementById(id).data[0].visible==='legendonly')"))
 run("document.getElementById('pair').value='5-7';document.getElementById('pair').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return window.backgroundReady&&document.getElementById('status').textContent.includes('ADC5–ADC7')"))
 request('POST',f'{d}/session/{s}/window/rect',{'width':430,'height':950});time.sleep(1)
 wait_until(lambda:run('return document.documentElement.scrollWidth<=innerWidth+1'))
 (out/'mobile.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 (out/'verification.json').write_text(json.dumps({'status':'PASS','checks':['28pairs','native600 corrected amplitude/phase values','OFF selection','real legend click sync','pair switch','mobile no overflow']}))
 print('PASS')
finally:
 if s:request('DELETE',f'{d}/session/{s}')
 p.terminate()
