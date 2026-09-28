'use strict';
/* FastAPI integration for the canonical A13 form.  A13 remains usable by
 * itself; this file adds server projects, PPT schemes and stable workbench
 * projections when it is served by the application. */
window.A13Platform=(function(){
  function clone(value){return JSON.parse(JSON.stringify(value));}
  function number(value,def){var n=parseFloat(value);return Number.isFinite(n)?n:(def||0);}
  function snapshot(){
    if(typeof qEnsureDB==='function')qEnsureDB();
    var data=clone(S),f=data.f||(data.f={}),t=data.t||(data.t={});data.i=data.i||{};
    var q=data.quote||{},meta=q.meta||{},map={customer:'quoteCustomer',moldName:'quoteMoldName',partNo:'quotePartNo',date:'quoteDate',alloy:'quoteAlloy',blankW:'quoteBlankWeight',finW:'quoteFinishedWeight',moldType:'quoteMoldType',mat:'quoteMoldMaterial',ton:'quoteMachineTonnage',cond:'quoteStructureCondition',qty:'quoteMoldQuantity',slider:'quoteHasSlider'};
    Object.keys(map).forEach(function(k){if(Object.prototype.hasOwnProperty.call(meta,k))f[map[k]]=meta[k];});
    var net=0;t.quoteSheet=(q.sheet||[]).map(function(row){var unit=number(row.unit),qty=number(row.qty,1),total=unit*qty;net+=total;return {key:row.key||'',cat:row.cat||'',desc:row.desc||'',unit:unit,qty:qty,total:total};});
    f.quoteItemCount=t.quoteSheet.length;f.quoteNetTotal=+net.toFixed(2);f.quoteTax=+(net*.13).toFixed(2);f.quoteGrossTotal=+(net*1.13).toFixed(2);
    t.machineLibrary=clone((data.mach&&data.mach.list)||[]);
    t.visionDefects=[];Object.keys(data.v||{}).forEach(function(k){((data.v[k]&&data.v[k].defects)||[]).forEach(function(d){t.visionDefects.push({module:k.replace(/Def$/,''),image:d.img||0,type:d.type||'',severity:d.severity||'',advice:d.advice||'',source:d.source||'',verdict:d.verdict||'',confidence:d.confidence||0,x:d.x||0,y:d.y||0,w:d.w||0,h:d.h||0});});});
    f.visionDefectCount=t.visionDefects.length;f.visionReviewedCount=t.visionDefects.filter(function(x){return !!x.verdict;}).length;
    return data;
  }
  function refresh(){
    if(typeof renderNav==='function')renderNav();
    if(typeof renderMain==='function')renderMain();
    if(typeof fillMachine==='function')fillMachine();
    if(typeof recalcDerived==='function')recalcDerived();
    if(typeof renderResults==='function')renderResults();
    if(typeof initVisionAll==='function')initVisionAll();
  }
  async function request(path,opts){var r=await fetch(path,Object.assign({cache:'no-store'},opts||{}));if(!r.ok){var tx=await r.text().catch(function(){return '';});throw new Error(typeof dfmReadError==='function'?dfmReadError(r.status,tx,r.headers.get('X-Request-Id')||''):('请求失败 '+r.status));}return r;}
  var maskEl=document.createElement('div');maskEl.id='schemeMask';maskEl.style.cssText='display:none;position:fixed;inset:0;z-index:160;background:rgba(15,23,42,.45);align-items:center;justify-content:center;padding:20px';
  maskEl.innerHTML='<div style="width:min(720px,96vw);max-height:86vh;overflow:auto;background:#fff;border-radius:14px;padding:20px;box-shadow:0 24px 70px rgba(15,23,42,.25)"><div style="display:flex;align-items:center;gap:10px"><h2 style="margin:0">按 PPT 方案生成</h2><span style="flex:1"></span><button class="btn" data-close>关闭</button></div><p class="hint">使用 PPT 工作台保存的模板与绑定关系，读取当前 A13 完整项目数据。</p><div data-list></div><p data-status class="hint"></p></div>';
  document.body.appendChild(maskEl);maskEl.querySelector('[data-close]').onclick=function(){maskEl.style.display='none';};maskEl.onclick=function(e){if(e.target===maskEl)maskEl.style.display='none';};
  async function showSchemes(){
    maskEl.style.display='flex';var box=maskEl.querySelector('[data-list]'),status=maskEl.querySelector('[data-status]');box.innerHTML='<div class="hint">正在读取方案…</div>';status.textContent='';
    try{var list=(await (await request('/api/schemes')).json()).schemes||[];if(!list.length){box.innerHTML='<div class="note">还没有方案。请先进入 PPT 工作台导入模板并完成绑定。</div>';return;}
      box.innerHTML='';list.forEach(function(s){var row=document.createElement('div');row.style.cssText='display:flex;gap:12px;align-items:center;border:1px solid #e2e8f0;border-radius:9px;padding:12px;margin:8px 0';row.innerHTML='<div style="flex:1"><b>'+esc(s.name)+'</b><div class="hint">模板 '+esc(s.template)+' · '+s.slide_count+' 页 · '+s.binding_count+' 个绑定</div></div><button class="btn pri">生成</button>';row.querySelector('button').onclick=function(){generateScheme(s.name,this,status);};box.appendChild(row);});
    }catch(e){box.innerHTML='<div class="verdict v-bad">'+esc(e.message)+'</div>';}
  }
  async function generateScheme(name,button,status){button.disabled=true;status.textContent='正在生成，请稍候…';try{var r=await request('/api/schemes/'+encodeURIComponent(name)+'/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data:snapshot()})});var blob=await r.blob(),cd=r.headers.get('Content-Disposition')||'',m=cd.match(/filename\*=UTF-8''([^;]+)/),fn=m?decodeURIComponent(m[1]):'DFM_A13.pptx',url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=fn;a.click();setTimeout(function(){URL.revokeObjectURL(url);},3000);status.textContent='已生成 '+fn+' · '+(r.headers.get('x-dfm-slide-count')||'?')+' 页';toast('已按方案生成：'+fn);}catch(e){status.textContent=e.message;toast('生成失败：'+e.message);}finally{button.disabled=false;}}
  var schemeButton=document.querySelector('#btnSchemeGen');if(schemeButton)schemeButton.onclick=showSchemes;
  var saveButton=document.querySelector('#btnServerSave');if(saveButton)saveButton.onclick=function(){if(window.NamedProjects)window.NamedProjects.showSave();else toast('项目服务尚未加载');};
  return {snapshot:snapshot,refresh:refresh,showSchemes:showSchemes};
})();
