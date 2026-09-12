"use strict";
const el=id=>document.getElementById(id), groups=['A2','A4','A6'], colors=['#1769aa','#d76b24','#008c95'];
const trendCache=new Map();
let result, hidden=new Set(), busy=false;
const fmt=n=>Number(n).toLocaleString('zh-CN',{maximumFractionDigits:4});
const base={margin:{l:75,r:25,t:65,b:70},legend:{orientation:'h',y:1.18},font:{family:'system-ui',size:13},paper_bgcolor:'white'};
function trace(g,extra){return {type:'scatter',mode:'markers',name:g,legendgroup:g,visible:hidden.has(g)?'legendonly':true,marker:{color:colors[groups.indexOf(g)],size:11},...extra};}
async function render(){
 const pair=el('pair').value.split('-').map(Number),bin=Number(el('bin').value),pct=el('scale').value==='percent';
 const rows=groups.map(g=>result.means.find(r=>r.test===g&&r.bin===bin&&r.pair.join('-')===pair.join('-')));
 const curves=groups.map(g=>result.curves.find(r=>r.test===g&&r.bin===bin&&r.pair.join('-')===pair.join('-')).points);
 el('summary').innerHTML=rows.map(r=>`<tr><td>${r.test}${hidden.has(r.test)?'（图中隐藏）':''}</td><td>${fmt(r.minutes_since_training)}</td><td>${fmt(pct?r.residual_normalized_pct/r.residual_over_raw:r.raw_amplitude_count2)} ${pct?'%':'count²'}</td><td>${fmt(pct?r.residual_normalized_pct:r.residual_amplitude_count2)} ${pct?'%':'count²'}</td><td>${fmt(100*r.residual_over_raw)}%</td></tr>`).join('');
 const amplitude=rows.map(r=>trace(r.test,{mode:'lines+markers',x:['原始复均值','扣除 A0 后'],y:pct?[r.residual_normalized_pct/r.residual_over_raw,r.residual_normalized_pct]:[r.raw_amplitude_count2,r.residual_amplitude_count2],marker:{color:colors[groups.indexOf(r.test)],size:12,symbol:['circle','diamond']},hovertemplate:'%{x}<br>%{y:.5f}<extra>%{fullData.name}</extra>'}));
 const complex=[{type:'scatter',mode:'markers',name:'A0 固定背景',x:[rows[0].training_real_count2],y:[rows[0].training_imag_count2],marker:{color:'#202830',symbol:'star',size:16}},...rows.map(r=>trace(r.test,{x:[r.test_real_count2],y:[r.test_imag_count2]}))];
 const integration=groups.map((g,i)=>trace(g,{mode:'lines+markers',x:curves[i].map(r=>r.tau_seconds),y:curves[i].map(r=>r.residual_complex_rms_count2)}));
 integration.push({type:'scatter',mode:'lines',name:'白噪声参考＋训练误差',x:curves[0].map(r=>r.tau_seconds),y:curves[0].map(r=>r.white_reference_with_training_uncertainty_count2),line:{color:'#333',dash:'dash'}});
 const key=`${pair.join('-')}-${bin}`;
 if(!trendCache.has(key)){
  const response=await fetch(`/static/background-holdout-trends/${key}.json`);
  if(!response.ok)throw Error('100ms趋势数据读取失败');
  trendCache.set(key,await response.json());
 }
 const native=trendCache.get(key),trend=[],phaseTrend=[],view=el('trend-view').value;
 for(const row of native.series){
  const color=colors[groups.indexOf(row.test)];
  if(view!=='residual')trend.push(trace(row.test,{name:row.test+' · 原始',x:native.time_s,y:row.real.map((r,i)=>Math.hypot(r,row.imag[i])),marker:{color,size:4,opacity:0.65,symbol:'circle'},hovertemplate:'%{x:.2f} 秒<br>%{y:.5f} count²<extra>%{fullData.name}</extra>'}));
  if(view!=='raw')trend.push(trace(row.test,{name:row.test+' · 扣除后',showlegend:view==='residual',x:native.time_s,y:row.real.map((r,i)=>Math.hypot(r-native.background_real,row.imag[i]-native.background_imag)),marker:{color,size:5,opacity:0.75,symbol:'x'},hovertemplate:'%{x:.2f} 秒<br>%{y:.5f} count²<extra>%{fullData.name}</extra>'}));
 }
 for(const row of native.series){
  for(const corrected of [false,true]){
   if((corrected&&view==='raw')||(!corrected&&view==='residual'))continue;
   const angles=row.real.map((r,i)=>{
    const re=r-(corrected?native.background_real:0),im=row.imag[i]-(corrected?native.background_imag:0);
    return re===0&&im===0?null:Math.atan2(im,re)*180/Math.PI;
   });
   phaseTrend.push(trace(row.test,{name:row.test+(corrected?' · 扣除后':' · 原始'),showlegend:!corrected||view==='residual',x:native.time_s,y:angles,
    marker:{color:colors[groups.indexOf(row.test)],size:corrected?5:4,opacity:0.65,symbol:corrected?'x':'circle'},
    hovertemplate:'%{x:.2f} 秒<br>%{y:.3f}°<extra>%{fullData.name}</extra>'}));
  }
 }
 const config={responsive:true,displaylogo:false};
 await Promise.all([Plotly.react('phase-trend',phaseTrend,{...base,xaxis:{title:{text:'相对各组采集起点（秒）'},range:[0,60]},yaxis:{title:{text:'相位（度）'},range:[-180,180],tickvals:[-180,-90,0,90,180]}},config),Plotly.react('trend',trend,{...base,xaxis:{title:{text:'相对各组采集起点（秒）'},range:[0,60]},yaxis:{title:{text:'复可见度幅度（count²）'},rangemode:'tozero'}},config),Plotly.react('amplitude',amplitude,{...base,yaxis:{title:{text:pct?'归一化幅度（%）':'复可见度幅度（count²）'},rangemode:'tozero'}},config),Plotly.react('complex',complex,{...base,xaxis:{title:{text:'实部（count²）'}},yaxis:{title:{text:'虚部（count²）'},scaleanchor:'x',scaleratio:1}},config),Plotly.react('integration',integration,{...base,xaxis:{type:'log',tickmode:'array',tickvals:[0.1,0.5,1,5,10,30,60],ticktext:['0.1','0.5','1','5','10','30','60'],title:{text:'积分时间 τ（秒）'}},yaxis:{type:'log',tickformat:'.3~g',title:{text:'复残差 RMS（count²）'}}},config)]);
 el('status').textContent=`已加载：ADC${pair[0]}–ADC${pair[1]} · bin ${bin} · A0 训练，A2/A4/A6 独立留出；仅使用已有数据。`;
 window.holdoutReady=true;
}
async function refresh(){if(busy)return;busy=true;try{await render();}catch(e){el('status').textContent='加载失败：'+e.message;throw e;}finally{busy=false;}}
fetch('/static/background-holdout-data.json').then(r=>{if(!r.ok)throw Error(r.status);return r.json();}).then(async data=>{
 result=data;const pairs=data.means.filter(r=>r.test==='A2'&&r.bin===3073).map(r=>r.pair);
 el('pair').innerHTML=pairs.map(p=>`<option value="${p.join('-')}">ADC${p[0]}–ADC${p[1]}</option>`).join('');el('pair').value='4-5';
 el('sources').textContent=JSON.stringify(data.sources,null,2);await refresh();
 for(const id of ['pair','bin','scale','trend-view'])el(id).addEventListener('change',refresh);
 el('reset').onclick=()=>{hidden.clear();refresh();};
 for(const id of ['trend','phase-trend','amplitude','complex','integration']){
  el(id).on('plotly_legendclick',e=>{const g=e.data[e.curveNumber].legendgroup;if(groups.includes(g)){hidden.has(g)?hidden.delete(g):hidden.add(g);refresh();}return false;});
  el(id).on('plotly_legenddoubleclick',e=>{const g=e.data[e.curveNumber].legendgroup;if(groups.includes(g)){hidden=new Set(groups.filter(x=>x!==g));refresh();}return false;});
 }
}).catch(e=>{el('status').textContent='加载失败：'+e.message;});
