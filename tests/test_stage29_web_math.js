'use strict';
const assert=require('node:assert/strict');
const math=require('../rust/t510_time_rx/static/stage29_math.js');
for(const [rate,width] of [[122880000,30000],[245760000,60000]]){
  const bin=math.binForRf(100,rate,4096,60);
  const rf=math.rfForBin(100,rate,4096,bin);
  assert.ok(Math.abs(rf-60)<=width/2/1e6);
  assert.ok(Math.abs(rf-140)>1);
}
const ordered=math.orderedBins(4096).map(bin=>math.rfForBin(100,122880000,4096,bin));
for(let i=1;i<ordered.length;i++)assert.ok(ordered[i]>=ordered[i-1]);
const raw=math.phasor(2,Math.PI/2,4,false);
assert.ok(Math.abs(raw.radius-.5)<1e-12&&Math.abs(raw.x)<1e-12&&Math.abs(raw.y-.5)<1e-12);
const equal=math.phasor(2,Math.PI/2,4,true,Math.PI/2);
assert.ok(Math.abs(equal.radius-1)<1e-12&&Math.abs(equal.x-1)<1e-12&&Math.abs(equal.y)<1e-12);
console.log('Stage 29 Web math tests passed');
