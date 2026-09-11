/* Original HTML is never inserted into the host DOM as executable markup. */
window.NativeFormHost=(function(){
  let frame=null, channel=null, pending=new Map(), mounted=false, originalSource='';
  /* 局域网 http 访问属非安全上下文，crypto.randomUUID 不存在；统一走带回退的生成器 */
  const dfmUuid=window.dfmUuid||(()=>'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=Math.random()*16|0;return (c==='x'?r:(r&3|8)).toString(16);}));
  function dispose(){mounted=false;for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('表单已切换'));}pending.clear();frame?.remove();frame=null;channel=null;}
  function request(type,runtime){
    if(!frame||!mounted)return Promise.reject(new Error('原样表单尚未就绪，请等待页面加载'));
    return new Promise((resolve,reject)=>{
      const id=dfmUuid(),timer=setTimeout(()=>{pending.delete(id);reject(new Error('读取原表单超时，未保存数据，请重试'));},15000);
      pending.set(id,{resolve,reject,timer});frame.contentWindow.postMessage({channel,id,type,runtime},'*');
    });
  }
  async function mount(container,appId,runtime,onDirty){
    dispose();
    const [response,scriptResponse]=await Promise.all([fetch('/api/form-apps/'+encodeURIComponent(appId)+'/runtime-source'),fetch('/static/native_bridge.js')]);
    if(!response.ok||!scriptResponse.ok)throw new Error('无法读取原 HTML 或数据桥接脚本');
    const source=await response.json(),bridge=await scriptResponse.text();originalSource=source.html;
    channel=dfmUuid();
    const doc=new DOMParser().parseFromString(source.html,'text/html');
    doc.querySelectorAll('base,meta[http-equiv],iframe,object,embed,script[src],link').forEach(n=>n.remove());
    const policy=doc.createElement('meta');policy.httpEquiv='Content-Security-Policy';
    policy.content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'; object-src 'none'";
    const shim=doc.createElement('script');shim.textContent=bridge.replace('__CHANNEL__',JSON.stringify(channel));
    doc.head.prepend(policy,shim);
    frame=document.createElement('iframe');frame.title='原样 HTML 表单';
    frame.setAttribute('sandbox','allow-scripts allow-modals allow-downloads');
    frame.referrerPolicy='no-referrer';frame.style.cssText='width:100%;height:calc(100vh - 210px);min-height:650px;border:1px solid #dde2e8;border-radius:10px;background:white';
    const activeFrame=frame,activeChannel=channel;
    const ready=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{window.removeEventListener('message',listener);reject(new Error('原 HTML 初始化超时；不能保存未加载的数据'));},20000);
      const listener=event=>{
        if(event.source!==activeFrame.contentWindow||event.data?.channel!==activeChannel)return;
        if(event.data.type==='ready'){clearTimeout(timer);window.removeEventListener('message',listener);mounted=true;resolve();}
        if(event.data.type==='failure'){clearTimeout(timer);window.removeEventListener('message',listener);reject(new Error(event.data.error));}
      };
      window.addEventListener('message',listener);
    });
    NativeFormHost.onDirty=onDirty;
    container.replaceChildren(frame);frame.srcdoc='<!doctype html>'+doc.documentElement.outerHTML;
    await ready;return request('restore',runtime);
  }
  window.addEventListener('message',event=>{
    if(!frame||event.source!==frame.contentWindow||event.data?.channel!==channel)return;
    const msg=event.data;
    if(msg.type==='export-html'){
      request('snapshot').then(runtime=>{
        const state=JSON.stringify(runtime.state).replace(/</g,'\\u003c');
        const script='<script>window.addEventListener("load",function(){var s='+state+';Object.entries({mdb:"MDB",tdb:"TDB",pr:"PR",is:"IS",fdb:"FDB",idb:"IDB",vh:"VH",G:"G"}).forEach(function(e){window[e[1]]=s[e[0]];});render();});<'+ '/script>';
        const html=originalSource.replace(/<\/body\s*>/i,script+'</body>');
        const url=URL.createObjectURL(new Blob([html===originalSource?originalSource+script:html],{type:'text/html;charset=utf-8'}));
        const a=document.createElement('a');a.href=url;a.download='DFM-shared.html';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }).catch(e=>alert('导出失败：'+e.message));return;
    }
    if(msg.type==='dirty'){NativeFormHost.onDirty?.();return;}
    const p=pending.get(msg.id);if(!p)return;
    pending.delete(msg.id);clearTimeout(p.timer);
    if(msg.type==='snapshot'&&msg.runtime?.adapter==='dfm_quote_v1')p.resolve(msg.runtime);
    else p.reject(new Error(msg.error||'数据桥接响应无效'));
  });
  return {mount,dispose,snapshot:()=>request('snapshot'),onDirty:null};
})();
