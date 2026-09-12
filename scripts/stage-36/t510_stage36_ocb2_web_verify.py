#!/usr/bin/env python3
"""Browser checks for the fixed-background experiment page, on GB10."""
import base64,json,subprocess,time,os,math,urllib.request
from pathlib import Path
from urllib.error import HTTPError
from t510_stage36_formula_layout_verify import request,execute,wait_until
out=Path('/home/astrolab/.cache/t510/ocb2-web-check-20260912');out.mkdir(exist_ok=True)
d='http://127.0.0.1:19531';p=subprocess.Popen(['/snap/chromium/current/usr/lib/chromium-browser/chromedriver','--port=19531'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);s=None
try:
 wait_until(lambda:request('GET',d+'/status'))
 profile=Path.home()/'snap/chromium/common/t510-holdout-verify'/str(os.getpid());profile.mkdir(parents=True)
 s=request('POST',d+'/session',{'capabilities':{'alwaysMatch':{'browserName':'chrome','goog:chromeOptions':{'binary':'/snap/chromium/current/usr/lib/chromium-browser/chrome','args':['--headless=new','--no-sandbox','--disable-dev-shm-usage','--window-size=1600,1100','--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader',f'--user-data-dir={profile}']}}}})['sessionId']
 run=lambda js:execute(d,s,js)
 request('POST',f'{d}/session/{s}/url',{'url':'http://127.0.0.1:8036/static/ocb2.html'})
 wait_until(lambda:run('return window.ocbReady===true'))
 assert run("return document.querySelectorAll('#pair option').length===28 && document.querySelectorAll('#allTable tr').length===28")
 native=json.load(urllib.request.urlopen('http://127.0.0.1:8036/static/ocb2-data/pairs/6-7.json'))
 for policy in ('raw','fixed','local'):
  run(f"document.getElementById('policy').value='{policy}';document.getElementById('policy').dispatchEvent(new Event('change'))")
  wait_until(lambda:run('return window.ocbReady'))
  plotted=run("return [document.getElementById('amp').data.map(t=>t.y),document.getElementById('phase').data.map(t=>t.y)]")
  for j,state in enumerate(('A1','B','A2')):
   a=native['native']['3073'][state];b=[0,0] if policy=='raw' else a[policy]
   for i in range(600,1200):
    re=a['real'][i]-b[0];im=a['imag'][i]-b[1]
    assert abs(plotted[0][j][i-600]-math.hypot(re,im))<1e-9
    assert abs(plotted[1][j][i-600]-math.degrees(math.atan2(im,re)))<1e-9
 assert run("return document.getElementById('spectrum').data.every(t=>t.y.length===4096) && document.getElementById('contrast').data.every(t=>t.y.length===4096)")
 def avg(state,key):
  a=native['native']['3073'][state];w=a['n_valid'][600:];return sum(v*n for v,n in zip(a[key][600:],w))/sum(w)
 meta=json.load(urllib.request.urlopen('http://127.0.0.1:8036/static/ocb2-data/summary.json'));alpha=meta['alpha']
 a,b,c=[complex(avg(state,'real'),avg(state,'imag')) for state in ('A1','B','A2')]
 norm=math.sqrt((avg('A1','power_a')+avg('A2','power_a'))/2*(avg('A1','power_b')+avg('A2','power_b'))/2)
 assert abs(native['spectra']['B_vs_interpolated_A'][3073]-100*abs(b-((1-alpha)*a+alpha*c))/norm)<1e-9
 run("document.getElementById('amp').scrollIntoView()")
 time.sleep(1)
 (out/'native.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 e=request('POST',f'{d}/session/{s}/element',{'using':'css selector','value':'#amp .legendtoggle'})
 request('POST',f'{d}/session/{s}/element/{e["element-6066-11e4-a52e-4f735466cecf"]}/click',{})
 wait_until(lambda:run("return window.ocbReady&&['amp','phase','iq','complex','power','spectrum'].every(id=>document.getElementById(id).data[0].visible==='legendonly')"))
 run("document.getElementById('showAll').click();")
 wait_until(lambda:run('return window.ocbReady'))
 run("document.getElementById('policy').value='raw';document.getElementById('policy').dispatchEvent(new Event('change'))")
 wait_until(lambda:run('return window.ocbReady'))
 run("document.getElementById('complex').scrollIntoView()")
 time.sleep(1)
 (out/'complex.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 run("document.getElementById('pair').value='4-5';document.getElementById('pair').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return window.ocbReady&&document.getElementById('status').textContent.includes('ADC4–ADC5')"))
 run("document.getElementById('bin').value='3182';document.getElementById('bin').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return window.ocbReady&&document.getElementById('status').textContent.includes('3182')"))
 run("document.getElementById('window').value='all';document.getElementById('window').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return window.ocbReady&&document.getElementById('amp').data.every(t=>t.x.length===1200)"))
 run("document.querySelectorAll('#states input').forEach(x=>x.checked=true);document.querySelector('#states input').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return window.ocbReady&&document.getElementById('amp').data.length===5"))
 run("document.getElementById('band').value='all';document.getElementById('band').dispatchEvent(new Event('change'))")
 wait_until(lambda:run("return window.ocbReady&&document.getElementById('contrast').layout.xaxis.range[1]===4095"))
 request('POST',f'{d}/session/{s}/window/rect',{'width':430,'height':950});time.sleep(1)
 run("document.getElementById('amp').scrollIntoView()")
 wait_until(lambda:run('return document.documentElement.scrollWidth<=innerWidth+1'))
 assert run('return document.documentElement.scrollWidth<=innerWidth+1')
 (out/'mobile.png').write_bytes(base64.b64decode(request('GET',f'{d}/session/{s}/screenshot')))
 (out/'verification.json').write_text(json.dumps({'status':'PASS','checks':['28pairs table','5400 native amplitude and phase formula checks','independent complex B contrast','4096bin spectra','real legend sync six plots','pair/bin/policy/window/state/band changes','mobile no overflow']}))
 print('PASS')
finally:
 if s:request('DELETE',f'{d}/session/{s}')
 p.terminate()
