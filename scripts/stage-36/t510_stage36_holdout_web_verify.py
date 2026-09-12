#!/usr/bin/env python3
"""Browser checks for the fixed-background experiment page, on GB10."""
import base64,json,subprocess,time,os,math,urllib.request
from pathlib import Path
from urllib.error import HTTPError
from t510_stage36_formula_layout_verify import request,execute,wait_until
out=Path('/home/astrolab/.cache/t510/background-holdout-20260911/web');out.mkdir(exist_ok=True)
d='http://127.0.0.1:19527';p=subprocess.Popen(['/snap/chromium/current/usr/lib/chromium-browser/chromedriver','--port=19527'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);s=None
try:
 wait_until(lambda:request('GET',d+'/status'))
 profile=Path.home()/'snap/chromium/common/t510-holdout-verify'/str(os.getpid());profile.mkdir(parents=True)
 s=request('POST',d+'/session',{'capabilities':{'alwaysMatch':{'browserName':'chrome','goog:chromeOptions':{'binary':'/snap/chromium/current/usr/lib/chromium-browser/chrome','args':['--headless=new','--no-sandbox','--disable-dev-shm-usage','--window-size=1600,1100',f'--user-data-dir={profile}']}}}})['sessionId']
 run=lambda js:execute(d,s,js)
 request('POST',f'{d}/session/{s}/url',{'url':'http://127.0.0.1:8036/static/background-holdout.html'})
 wait_until(lambda:run('return window.holdoutReady===true'))
 assert run("return document.querySelectorAll('#pair option').length") ==28
 assert run("return document.getElementById('summary').textContent.includes('0.395')")
 assert run("return document.getElementById('trend').data.length===6 && document.getElementById('trend').data.every(t=>t.x.length===600 && t.x[599]===59.95)")
 # Independently compare browser RMS to the earlier numerical analysis.
 plotted=run("return Math.sqrt(document.getElementById('trend').data[1].y.reduce((s,v)=>s+v*v,0)/600)")
 assert abs(plotted-1.846843835631445)<1e-6,plotted
 run("document.getElementById('trend-view').value='residual';document.getElementById('trend-view').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return document.getElementById('trend').data.length===3"))
 run("document.getElementById('trend-section').scrollIntoView()")
 (out/'trend-residual.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 run("document.getElementById('trend-view').value='both';document.getElementById('trend-view').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return document.getElementById('trend').data.length===6"))
 (out/'trend-both.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 with urllib.request.urlopen('http://127.0.0.1:8036/static/background-holdout-trends/4-5-3073.json') as response:native=json.load(response)
 phases=run("return document.getElementById('phase-trend').data.map(t=>t.y)")
 assert len(phases)==6 and all(len(v)==600 for v in phases)
 for j,row in enumerate(native['series']):
  for corrected in (0,1):
   expected=[math.degrees(math.atan2(im-corrected*native['background_imag'],re-corrected*native['background_real'])) for re,im in zip(row['real'],row['imag'])]
   assert max(abs(a-b) for a,b in zip(expected,phases[2*j+corrected]))<1e-10
 run("document.getElementById('phase-trend').scrollIntoView()")
 (out/'phase-trend.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 # Real WebDriver click on the first legend entry, then verify all plots.
 e=request('POST',f'{d}/session/{s}/element',{'using':'css selector','value':'#amplitude .legendtoggle'})
 request('POST',f'{d}/session/{s}/element/{e["element-6066-11e4-a52e-4f735466cecf"]}/click',{})
 wait_until(lambda:run("return ['trend','phase-trend','amplitude','complex','integration'].every(id=>document.getElementById(id).data.find(t=>t.legendgroup==='A2').visible==='legendonly')"))
 run("document.getElementById('reset').click()")
 wait_until(lambda:run("return document.getElementById('amplitude').data[0].visible===true"))
 (out/'desktop.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 run("document.getElementById('integration').scrollIntoView()")
 (out/'integration.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 run("document.getElementById('pair').value='0-1';document.getElementById('pair').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return document.getElementById('status').textContent.includes('ADC0–ADC1')"))
 run("document.getElementById('bin').value='3182';document.getElementById('bin').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return document.getElementById('status').textContent.includes('bin 3182')"))
 request('POST',f'{d}/session/{s}/window/rect',{'width':430,'height':950})
 time.sleep(1)
 run('window.scrollTo(0,0)')
 assert run('return document.documentElement.scrollWidth <= innerWidth+1')
 (out/'mobile.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 (out/'verification.json').write_text(json.dumps({'status':'PASS','checks':['phase atan2 values for all 3600 points','phase legend synchronization','default numbers','native 600 points per group','browser residual RMS matches reference','trend view toggle','28 pairs','real legend click synchronizes all three plots','reset','pair and bin selectors','mobile no horizontal overflow']}))
 print('PASS')
except HTTPError as error:
 print(error.read().decode());raise
finally:
 if s:request('DELETE',f'{d}/session/{s}')
 p.terminate()
