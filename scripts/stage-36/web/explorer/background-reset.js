'use strict';
const el=id=>document.getElementById(id),names={none:'不扣除',old:'扣旧背景',new:'扣新背景'},policies=['none','old','new'];
const colors=['#1769aa','#d76b24','#008c95','#7651a6','#b74842','#397b58','#8a6d1d','#a34f8b','#287c71'];
const cache=new Map(),hidden=new Set();let meta,generation=0;
const fmt=x=>Number(x).toLocaleString('zh-CN',{maximumFractionDigits:4});
const layout={margin:{l:75,r:20,t:70,b:65},legend:{orientation:'h',y:1.03,yanchor:'bottom'},font:{family:'system-ui',size:13}};
const visibility=key=>hidden.has(key)?'legendonly':true;
async function render(){
 const gen=++generation;window.resetReady=false;
 const pair=el('pair').value,bin=+el('bin').value,policy=el('policy').value;
 const rounds=[...document.querySelectorAll('#rounds input:checked')].map(x=>+x.value);
 el('status').textContent='正在载入并绘制…';
 try{
  const datasets=await Promise.all(rounds.map(async r=>{const key=`${r}-${pair}-${bin}`;if(!cache.has(key)){const response=await fetch(`/static/background-reset-data/trends/${key}.json`);if(!response.ok)throw Error('数据读取失败 '+key);cache.set(key,await response.json());}return cache.get(key);}));
  if(gen!==generation)return;
  const amp=[],phase=[],minute=[];
  for(const d of datasets)for(const p of policies){
   if(policy!=='all'&&policy!==p)continue;
   const key=`${d.round}-${p}`,bg=p==='none'?[0,0]:d[p],color=colors[(d.round-1)*3+policies.indexOf(p)];
   const re=d.real.map(v=>v-bg[0]),im=d.imag.map(v=>v-bg[1]),x=d.real.map((_,i)=>(i+.5)/10);
   const common={name:`第${d.round}轮 · ${names[p]}`,legendgroup:key,visible:visibility(key),mode:'markers',marker:{color,size:3,opacity:.65},type:'scattergl'};
   amp.push({...common,x,y:re.map((v,i)=>Math.hypot(v,im[i])),hovertemplate:'%{x:.2f}s<br>%{y:.5f} count²<extra>%{fullData.name}</extra>'});
   phase.push({...common,x,y:re.map((v,i)=>v===0&&im[i]===0?null:Math.atan2(im[i],v)*180/Math.PI),hovertemplate:'%{x:.2f}s<br>%{y:.3f}°<extra>%{fullData.name}</extra>'});
   minute.push({...common,type:'scatter',mode:'lines+markers',marker:{color,size:7},x:d.minutes.map((_,i)=>i+.5),y:d.minutes.map(v=>100*Math.hypot(v.real-bg[0],v.imag-bg[1])/Math.sqrt(v.power_a*v.power_b)),hovertemplate:'检验第 %{x} 分钟中心<br>%{y:.5f}%<extra>%{fullData.name}</extra>'});
  }
  const config={responsive:true,displaylogo:false,displayModeBar:false};
  await Promise.all([Plotly.react('amp',amp,{...layout,xaxis:{title:{text:'相对检验起点（秒）'},range:[0,540]},yaxis:{title:{text:'幅度（count²）'},rangemode:'tozero'}},config),Plotly.react('phase',phase,{...layout,xaxis:{title:{text:'相对检验起点（秒）'},range:[0,540]},yaxis:{title:{text:'相位（度）'},range:[-180,180],tickvals:[-180,-90,0,90,180]}},config),Plotly.react('minute',minute,{...layout,xaxis:{title:{text:'相对检验起点（分钟）'},range:[0,9]},yaxis:{title:{text:'归一化复残差（%）'},rangemode:'tozero'}},config)]);
  if(gen!==generation)return;
  const rows=meta.summary.filter(r=>r.pair.join('-')===pair);
  el('pairTable').innerHTML=rows.map(r=>`<tr><td>${r.round}</td><td>${fmt(r.median_pct.none)}</td><td>${fmt(r.median_pct.old)}</td><td>${fmt(r.median_pct.new)}</td><td>${r.new_better_none?'降低':'升高或持平'}</td></tr>`).join('');
  el('status').textContent=`ADC${pair.replace('-','–ADC')} · bin${bin} · ${rounds.length?'第'+rounds.join('/')+'轮，每轮5400点':'未选择轮次'} · 频带表格始终保留三轮。`;
  window.resetReady=true;
 }catch(e){el('status').textContent='加载失败：'+e.message;console.error(e);}
}
async function start(){
 const r=await fetch('/static/background-reset-data/summary.json');if(!r.ok)throw Error('汇总读取失败');meta=await r.json();
 el('pair').innerHTML=meta.pairs.map(p=>`<option value="${p.join('-')}">ADC${p[0]}–ADC${p[1]}</option>`).join('');el('pair').value='0-2';
 el('allTable').innerHTML=meta.pairs.map(p=>`<tr><td><button data-pair="${p.join('-')}">${p.join('–')}</button></td>${[1,2,3].map(n=>{const r=meta.summary.find(r=>r.round===n&&r.pair.join('-')===p.join('-'));return `<td>${fmt(r.median_pct.none)} → ${fmt(r.median_pct.new)}（${r.new_better_none?'↓':'↑'}）</td>`;}).join('')}</tr>`).join('');
 el('allTable').onclick=e=>{if(e.target.dataset.pair){el('pair').value=e.target.dataset.pair;render();el('native').scrollIntoView();}};
 el('identity').textContent=JSON.stringify({queue_manifest_sha256:meta.queue_manifest_sha256,limitations:meta.limitations},null,2);
 await render();
 for(const id of ['pair','bin','policy'])el(id).onchange=render;
 document.querySelectorAll('#rounds input').forEach(x=>x.onchange=render);el('showAll').onclick=()=>{hidden.clear();render();};
 for(const id of ['amp','phase','minute']){
  el(id).on('plotly_legendclick',e=>{const key=e.data[e.curveNumber].legendgroup;hidden.has(key)?hidden.delete(key):hidden.add(key);render();return false;});
  el(id).on('plotly_legenddoubleclick',e=>{const key=e.data[e.curveNumber].legendgroup;hidden.clear();e.data.forEach(t=>{if(t.legendgroup!==key)hidden.add(t.legendgroup);});render();return false;});
 }
}
start().catch(e=>{el('status').textContent='加载失败：'+e.message;});
