/* Executed only inside the opaque-origin original-form frame. */
(function(channel){
  'use strict';
  const memory=Object.create(null);
  const storage={getItem:k=>Object.hasOwn(memory,k)?memory[k]:null,setItem:(k,v)=>{memory[k]=String(v);},removeItem:k=>{delete memory[k];},clear:()=>{Object.keys(memory).forEach(k=>delete memory[k]);},key:n=>Object.keys(memory)[n]??null,get length(){return Object.keys(memory).length;}};
  Object.defineProperty(window,'localStorage',{value:storage});
  Object.defineProperty(window,'sessionStorage',{value:storage});
  let ready=false, loading=false;
  const edited=new Set();
  const send=(type,extra={})=>parent.postMessage({channel,type,...extra},'*');
  function changed(){if(ready&&!loading)send('dirty');}
  const clone=v=>JSON.parse(JSON.stringify(v));
  function snapshot(){
    // Moving focus out of an iframe does not consistently commit onchange-backed
    // controls. Explicitly commit edited controls before reading the source model.
    const controls=Array.from(edited);edited.clear();
    controls.forEach(el=>{if(el.isConnected)el.dispatchEvent(new Event('change',{bubbles:true}));});
    // Recalculate the original per-tool values, using only the source's functions.
    if(typeof window.st==='function')window.PR.forEach(p=>window.st(p.tl||[]));
    const computed={};
    if(typeof window.nct==='function'&&typeof window.cap==='function'){
      computed.processes=window.PR.map((p,n)=>{const cut=window.st(p.tl||[]),noncut=window.nct(n);return {name:p.nm,cut_seconds:cut,noncut_seconds:noncut,cycle_seconds:cut+noncut,monthly_capacity:window.cap(cut+noncut,p.mc)};});
      computed.total_seconds=computed.processes.reduce((sum,p)=>sum+p.cycle_seconds,0);
      computed.monthly_capacity=computed.processes.length?Math.min(...computed.processes.map(p=>p.monthly_capacity)):0;
    }
    return {adapter:'dfm_quote_v1',state:clone({mdb:window.MDB,tdb:window.TDB,pr:window.PR,is:window.IS,fdb:window.FDB,idb:window.IDB,vh:window.VH,G:window.G}),labels:clone(window.GLBL||{}),computed};
  }
  function restore(runtime){
    if(!runtime)return;
    if(runtime.adapter!=='dfm_quote_v1')throw new Error('数据适配器不一致');
    const s=clone(runtime.state);
    // Assign full snapshots, including empty arrays. Source applyData() falls back
    // to defaults for empty arrays and therefore cannot restore deleted rows exactly.
    for(const [key,globalName] of Object.entries({mdb:'MDB',tdb:'TDB',pr:'PR',is:'IS',fdb:'FDB',idb:'IDB',vh:'VH',G:'G'})){
      if(s[key]===undefined)throw new Error('快照缺少 '+key);
      window[globalName]=s[key];
    }
    memory.cncCalcV7=JSON.stringify(s);
    window.curTab=0;window.render();
  }
  window.addEventListener('message',event=>{
    if(event.source!==parent||event.data?.channel!==channel||!ready)return;
    const msg=event.data;
    try{
      loading=true;
      if(msg.type==='restore')restore(msg.runtime);
      else if(msg.type!=='snapshot')return;
      send('snapshot',{id:msg.id,runtime:snapshot()});
    }catch(e){send('failure',{id:msg.id,error:e.message});}
    finally{loading=false;}
  });
  document.addEventListener('input',event=>{edited.add(event.target);changed();},true);
  document.addEventListener('change',changed,true);
  // Buttons may alter arrays/images without dispatching input events.
  document.addEventListener('click',event=>{
    const a=event.target.closest('a[href]');
    if(a&&!/^(blob:|data:|#)/.test(a.getAttribute('href')||''))event.preventDefault();
    changed();
  },true);
  window.addEventListener('load',()=>setTimeout(()=>{
    if(typeof window.applyData!=='function'||typeof window.render!=='function'||!window.G||!Array.isArray(window.PR)){
      send('failure',{error:'原 HTML 未正常初始化，无法保存。请检查源文件或适配器。'});return;
    }
    const originalRender=window.render;
    window.render=function(){const result=originalRender.apply(this,arguments);document.querySelectorAll('.note,.fbox').forEach(n=>{if(n.textContent.includes('数据自动保存在本机浏览器'))n.textContent='平台模式：页面内缓存仅供当前窗口使用。请使用上方「保存项目」保存完整数据和历史版本；导出共享文件、JSON 备份仍可使用。';});return result;};
    window.exportHTML=function(){send('export-html');};
    window.render();ready=true;send('ready');
  },0));
})(__CHANNEL__);
