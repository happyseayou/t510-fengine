(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.Stage29Math=api;
})(typeof self!=='undefined'?self:this,function(){
  function signedBin(index,bins){return index<bins/2?index:index-bins}
  function sampleRateHz(headerRate,bandwidthMhz){
    const header=Number(headerRate);
    if(Number.isFinite(header)&&header>0)return header;
    return Number(bandwidthMhz)===200?245760000:122880000;
  }
  function rfForBin(centerMhz,sampleRate,bins,index){
    return Number(centerMhz)-signedBin(index,bins)*Number(sampleRate)/Number(bins)/1e6;
  }
  function binForRf(centerMhz,sampleRate,bins,rfMhz){
    const width=Number(sampleRate)/Number(bins);
    const signed=Math.round((Number(centerMhz)-Number(rfMhz))*1e6/width);
    return((signed%bins)+bins)%bins;
  }
  function orderedBins(bins){
    const out=[];
    for(let display=0;display<bins;display++){
      const signed=Math.floor(bins/2)-1-display;
      out.push(signed>=0?signed:bins+signed);
    }
    return out;
  }
  function phasor(amplitude,phase,maxAmplitude,ignoreAmplitude,referencePhase){
    const angle=referencePhase===undefined?phase:wrapPhase(phase-referencePhase);
    const radius=ignoreAmplitude?1:Number(amplitude)/Math.max(1,Number(maxAmplitude));
    return{angle,radius,x:radius*Math.cos(angle),y:radius*Math.sin(angle)};
  }
  function wrapPhase(value){while(value>Math.PI)value-=2*Math.PI;while(value<-Math.PI)value+=2*Math.PI;return value}
  return{signedBin,sampleRateHz,rfForBin,binForRf,orderedBins,phasor,wrapPhase};
});
