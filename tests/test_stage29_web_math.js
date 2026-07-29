'use strict';
const assert=require('node:assert/strict');
const math=require('../rust/t510_time_rx/static/stage29_math.js');
for(const [center,rate,rf] of [
  [100,122880000,60],
  [100,245760000,140],
  [170,320000000,60],
  [170,320000000,280],
  [170,160000000,120],
  [170,160000000,220],
]){
  const bin=math.binForRf(center,rate,4096,rf);
  const roundTrip=math.rfForBin(center,rate,4096,bin);
  const halfBinMhz=rate/4096/2/1e6;
  assert.ok(Math.abs(roundTrip-rf)<=halfBinMhz+1e-12);
}

assert.equal(math.rfForBin(170,320000000,4096,1408),280);
assert.equal(math.rfForBin(170,320000000,4096,2688),60);
assert.equal(math.binForRf(170,320000000,4096,280),1408);
assert.equal(math.binForRf(170,320000000,4096,60),2688);
assert.equal(math.rfForBin(170,160000000,4096,1280),220);
assert.equal(math.rfForBin(170,160000000,4096,2816),120);

const ordered=math.orderedBins(4096).map(bin=>math.rfForBin(100,122880000,4096,bin));
for(let i=1;i<ordered.length;i++)assert.ok(ordered[i]>=ordered[i-1]);
assert.equal(ordered[0],100-122880000/2/1e6);
assert.ok(ordered.at(-1)<100+122880000/2/1e6);
const raw=math.phasor(2,Math.PI/2,4,false);
assert.ok(Math.abs(raw.radius-.5)<1e-12&&Math.abs(raw.x)<1e-12&&Math.abs(raw.y-.5)<1e-12);
const equal=math.phasor(2,Math.PI/2,4,true,Math.PI/2);
assert.ok(Math.abs(equal.radius-1)<1e-12&&Math.abs(equal.x-1)<1e-12&&Math.abs(equal.y)<1e-12);
console.log('Stage 29 Web math tests passed');
