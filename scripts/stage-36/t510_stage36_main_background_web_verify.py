#!/usr/bin/env python3
"""Browser acceptance of main-report historical background overlays."""
import base64
import json
import subprocess
from pathlib import Path
from t510_stage36_formula_layout_verify import request, execute, wait_until


def main():
    driver='http://127.0.0.1:19531'
    process=subprocess.Popen(['/snap/chromium/current/usr/lib/chromium-browser/chromedriver','--port=19531'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    session=None
    out=Path('/tmp/stage36-main-background-web');out.mkdir(exist_ok=True)
    try:
        wait_until(lambda: request('GET',driver+'/status'),10)
        session=request('POST',driver+'/session',{'capabilities':{'alwaysMatch':{'browserName':'chrome','goog:chromeOptions':{'binary':'/snap/chromium/current/usr/lib/chromium-browser/chrome','args':['--headless=new','--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader','--window-size=1800,1300']}}}})['sessionId']
        results=[]
        for pair in ('0-1','5-7'):
            request('POST',f'{driver}/session/{session}/url',{'url':f'http://127.0.0.1:8036/?mode=pair&pairs={pair}&bins=3073&allan_scale=absolute'})
            wait_until(lambda: '权威数据就绪' in execute(driver,session,"return document.getElementById('health').textContent"),60)
            js="""
              const p=document.querySelector('[id^="pair-long-page-"]');
              const a=document.querySelector('[id^="pair-allan-page-"]');
              const ps=gpuPlots.get(p), as=gpuPlots.get(a);
              return {traces:ps.traces.length, lengths:ps.traces.filter(t=>t.yaxis==='y').map(t=>t.x.length),
                starts:ps.traces.filter(t=>t.yaxis==='y').map(t=>t.x[0]), shades:ps.layout.shapes.length,
                legends:ps.layout.legend.groupclick, allan:as.traces.filter(t=>t.mode==='lines+markers').length,
                errors:document.querySelectorAll('.katex-error').length,
                formulas:p.closest('.figure').querySelectorAll('.katex').length,
                width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth};
            """
            try:
                r=execute(driver,session,js)
            except Exception as exc:
                print(exc.read().decode() if hasattr(exc, 'read') else str(exc))
                print(execute(driver,session,"return [...document.querySelectorAll('.plot')].map(p=>({id:p.id,data:!!ps.traces,layout:!!ps.layout}))"))
                raise
            assert r['traces']==18 and r['lengths']==[9000,8400]*3 and r['allan']==6,r
            assert r['starts']==[.05,60.05]*3 and r['shades']==2 and r['legends']=='togglegroup',r
            assert r['errors']==0 and r['formulas']>0,r
            wait_until(lambda: execute(driver,session,'return document.documentElement.scrollWidth<=document.documentElement.clientWidth+1'),10)
            execute(driver,session,"document.querySelector('[id^=\"pair-long-page-\"]').closest('.figure').scrollIntoView()")
            wait_until(lambda: execute(driver,session,"return gpuOwner===document.querySelector('[id^=\"pair-long-page-\"]') && gpuPlots.get(gpuOwner).state==='rendered'"),15)
            # Exercise the rendered Plotly legend with a real browser click.
            # Plotly uses mousedown/up rather than native click in some bundles.
            el=request('POST',f'{driver}/session/{session}/element',{'using':'css selector','value':'[id^="pair-long-page-"] .legendtoggle'})
            eid=el['element-6066-11e4-a52e-4f735466cecf']
            request('POST',f'{driver}/session/{session}/element/{eid}/click',{})
            wait_until(lambda: execute(driver,session,"return gpuSurface.data.slice(0,3).filter(t=>t.x.length).every(t=>t.visible==='legendonly')"),10)
            request('POST',f'{driver}/session/{session}/element/{eid}/click',{})
            wait_until(lambda: execute(driver,session,"return gpuSurface.data.slice(0,3).filter(t=>t.x.length).every(t=>t.visible===true)"),10)
            r['legend_linked']=True
            shot=request('GET',f'{driver}/session/{session}/screenshot')
            (out/f'pair-{pair}.png').write_bytes(base64.b64decode(shot))
            execute(driver,session,"document.querySelector('[id^=\"pair-allan-page-\"]').closest('.figure').scrollIntoView()")
            wait_until(lambda: execute(driver,session,"return gpuOwner===document.querySelector('[id^=\"pair-allan-page-\"]') && gpuPlots.get(gpuOwner).state==='rendered'"),15)
            (out/f'allan-{pair}.png').write_bytes(base64.b64decode(request('GET',f'{driver}/session/{session}/screenshot')))
            assert execute(driver,session,'return GPU_TRACE_SLOTS>=4*4*3*2*3')
            results.append({'pair':pair,**r})
        (out/'result.json').write_text(json.dumps({'status':'PASS','results':results},indent=2))
        print(json.dumps({'status':'PASS','results':results}))
    finally:
        if session:request('DELETE',f'{driver}/session/{session}')
        process.terminate();process.wait(timeout=10)


if __name__=='__main__':main()
