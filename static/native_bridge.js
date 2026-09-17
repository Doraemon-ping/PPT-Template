/* Executed only inside the opaque-origin original-form frame. */
(function(channel,adapter){
  'use strict';
  const memory=Object.create(null);
  const storage={getItem:k=>Object.hasOwn(memory,k)?memory[k]:null,setItem:(k,v)=>{memory[k]=String(v);},removeItem:k=>{delete memory[k];},clear:()=>{Object.keys(memory).forEach(k=>delete memory[k]);},key:n=>Object.keys(memory)[n]??null,get length(){return Object.keys(memory).length;}};
  Object.defineProperty(window,'localStorage',{value:storage});
  Object.defineProperty(window,'sessionStorage',{value:storage});
  let ready=false,loading=false;
  const edited=new Set();
  const send=(type,extra={})=>parent.postMessage({channel,type,...extra},'*');
  function changed(){if(ready&&!loading)send('dirty');}
  const clone=v=>JSON.parse(JSON.stringify(v));

  function commitEdits(){
    const controls=Array.from(edited);edited.clear();
    controls.forEach(el=>{if(el.isConnected)el.dispatchEvent(new Event('change',{bubbles:true}));});
  }

  function genericContract(){
    const explicit=window.__DFM_BRIDGE__;
    if(explicit&&typeof explicit==='object')return explicit;
    return {
      exportData:typeof window.exportData==='function'?window.exportData.bind(window):null,
      importData:typeof window.importData==='function'?window.importData.bind(window):typeof window.applyData==='function'?window.applyData.bind(window):typeof window.loadData==='function'?window.loadData.bind(window):null,
      render:typeof window.render==='function'?window.render.bind(window):null
    };
  }

  async function jsonValue(value){
    value=await value;
    if(typeof Blob!=='undefined'&&value instanceof Blob)value=await value.text();
    if(typeof value==='string'){
      try{return JSON.parse(value);}catch(_){throw new Error('exportData() 返回了字符串，但不是有效 JSON');}
    }
    if(!value||typeof value!=='object')throw new Error('exportData() 必须 return JSON 对象；如果原函数只下载文件，请在 __DFM_BRIDGE__.exportData 中返回同一份对象');
    return clone(value);
  }

  async function metadataValue(value,fallback,context=window){
    if(typeof value==='function')value=await value.call(context);
    if(value===undefined||value===null)return fallback;
    return clone(value);
  }

  async function snapshot(){
    commitEdits();
    if(adapter==='dfm_quote_v1'){
      if(typeof window.st==='function')window.PR.forEach(p=>window.st(p.tl||[]));
      const computed={};
      if(typeof window.nct==='function'&&typeof window.cap==='function'){
        computed.processes=window.PR.map((p,n)=>{const cut=window.st(p.tl||[]),noncut=window.nct(n);return {name:p.nm,cut_seconds:cut,noncut_seconds:noncut,cycle_seconds:cut+noncut,monthly_capacity:window.cap(cut+noncut,p.mc)};});
        computed.total_seconds=computed.processes.reduce((sum,p)=>sum+p.cycle_seconds,0);
        computed.monthly_capacity=computed.processes.length?Math.min(...computed.processes.map(p=>p.monthly_capacity)):0;
      }
      return {adapter,state:clone({mdb:window.MDB,tdb:window.TDB,pr:window.PR,is:window.IS,fdb:window.FDB,idb:window.IDB,vh:window.VH,G:window.G}),labels:clone(window.GLBL||{}),computed};
    }
    if(adapter==='json_export_v1'){
      const api=genericContract();
      if(typeof api.exportData!=='function')throw new Error('通用 JSON 工具未提供 exportData()');
      return {
        adapter,
        source_version:await metadataValue(api.version||api.sourceVersion,1,api),
        raw:await jsonValue(api.exportData.call(api)),
        labels:await metadataValue(api.labels,{},api),
        rules:await metadataValue(api.rules,{},api)
      };
    }
    throw new Error('不支持的数据适配器：'+adapter);
  }

  async function restore(runtime){
    if(!runtime)return;
    if(runtime.adapter!==adapter)throw new Error('数据适配器不一致');
    if(adapter==='dfm_quote_v1'){
      const s=clone(runtime.state);
      for(const [key,globalName] of Object.entries({mdb:'MDB',tdb:'TDB',pr:'PR',is:'IS',fdb:'FDB',idb:'IDB',vh:'VH',G:'G'})){
        if(s[key]===undefined)throw new Error('快照缺少 '+key);
        window[globalName]=s[key];
      }
      memory.cncCalcV7=JSON.stringify(s);
      window.curTab=0;window.render();
      return;
    }
    const api=genericContract();
    if(typeof api.importData!=='function')throw new Error('通用 JSON 工具未提供 importData()/applyData()，无法恢复项目');
    await api.importData.call(api,clone(runtime.raw));
    if(typeof api.render==='function')await api.render.call(api);
  }

  window.addEventListener('message',event=>{
    if(event.source!==parent||event.data?.channel!==channel||!ready)return;
    const msg=event.data;
    (async()=>{
      loading=true;
      if(msg.type==='restore')await restore(msg.runtime);
      else if(msg.type!=='snapshot')return;
      send('snapshot',{id:msg.id,runtime:await snapshot()});
    })().catch(e=>send('failure',{id:msg.id,error:e?.message||String(e)})).finally(()=>{loading=false;});
  });
  document.addEventListener('input',event=>{edited.add(event.target);changed();},true);
  document.addEventListener('change',changed,true);
  document.addEventListener('click',event=>{
    const a=event.target.closest?.('a[href]');
    if(a&&!/^(blob:|data:|#)/.test(a.getAttribute('href')||''))event.preventDefault();
    changed();
  },true);
  window.addEventListener('load',()=>setTimeout(()=>{
    let error='';
    if(adapter==='dfm_quote_v1'&&(typeof window.applyData!=='function'||typeof window.render!=='function'||!window.G||!Array.isArray(window.PR)))error='原 HTML 未正常初始化，无法保存。请检查源文件或适配器。';
    if(adapter==='json_export_v1'){
      const api=genericContract();
      if(typeof api.exportData!=='function'||typeof api.importData!=='function')error='通用 JSON 对接需要 exportData() 和 importData()/applyData()。';
    }
    if(error){send('failure',{error});return;}
    if(adapter==='dfm_quote_v1'){
      const originalRender=window.render;
      window.render=function(){const result=originalRender.apply(this,arguments);document.querySelectorAll('.note,.fbox').forEach(n=>{if(n.textContent.includes('数据自动保存在本机浏览器'))n.textContent='平台模式：页面内缓存仅供当前窗口使用。请使用上方「保存项目」保存完整数据和历史版本；导出共享文件、JSON 备份仍可使用。';});return result;};
      window.exportHTML=function(){send('export-html');};
      window.render();
    }
    ready=true;send('ready');
  },0));
})(__CHANNEL__,__ADAPTER__);
