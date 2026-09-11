'use strict';
window.NamedProjects=(function(){
  let current=null, saving=false;const qs=new URLSearchParams(location.search);
  /* 局域网 http 访问属非安全上下文，crypto.randomUUID 不存在；统一走带回退的生成器 */
  const dfmUuid=window.dfmUuid||(()=>'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=Math.random()*16|0;return (c==='x'?r:(r&3|8)).toString(16);}));
  function updateLinks(){document.querySelectorAll('a[href^="/template-editor"]').forEach(a=>a.href='/template-editor?app_id=dfm'+(current?'&project_id='+encodeURIComponent(current.id):''));}
  const dialog=document.createElement('dialog');dialog.style.cssText='border:1px solid #dde2e8;border-radius:12px;width:min(540px,94vw);padding:24px';
  dialog.innerHTML='<h2>保存数据项目</h2><p>每个项目独立保存，更新会保留历史版本。</p><label>项目名称<input id="namedProjectName" style="width:100%;margin:8px 0 18px" maxlength="160"></label><p id="namedProjectStatus" role="status"></p><div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn pri" id="namedSave">保存</button><button class="btn" id="namedCopy">另存为新项目</button><button class="btn" id="namedClose">取消</button></div>';
  document.body.appendChild(dialog);
  const versionsButton=document.createElement('button');versionsButton.className='btn';versionsButton.textContent='项目历史版本';
  document.querySelector('a[href="/forms"]').after(versionsButton);
  const versionsDialog=document.createElement('dialog');versionsDialog.style.cssText=dialog.style.cssText;
  versionsDialog.innerHTML='<h2>项目历史版本</h2><p>恢复会创建新版本，不删除已有记录；当前未保存修改将被替换。</p><div></div><button class="btn">关闭</button>';
  document.body.appendChild(versionsDialog);versionsDialog.querySelector('button').onclick=()=>versionsDialog.close();
  versionsButton.onclick=async()=>{if(!current){toast('请先保存为命名项目');return;}try{const list=await request('/api/form-apps/dfm/projects/'+current.id+'/versions');const container=versionsDialog.querySelector('div');container.replaceChildren();for(const version of list.versions){const button=document.createElement('button');button.className='btn';button.textContent='恢复版本 '+version.revision+' · '+new Date(version.created).toLocaleString();button.onclick=async()=>{if(!confirm('恢复将替换当前未保存修改，并创建新版本。继续？'))return;button.disabled=true;try{const old=await request('/api/form-apps/dfm/projects/'+current.id+'?revision='+version.revision);current=await request('/api/form-apps/dfm/projects/'+current.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:old.name,data:old.data,revision:current.revision})});S.f={};S.t={};S.i={};mergeState(current.data);renderMain();refreshAll(true);save();versionsDialog.close();toast('已恢复为版本 '+current.revision);}catch(e){toast(e.message);}finally{button.disabled=false;}};container.appendChild(button);}versionsDialog.showModal();}catch(e){toast(e.message);}};
  async function request(path,options){const r=await fetch(path,options);if(!r.ok){const e=await r.json();throw new Error(typeof e.detail==='string'?e.detail:JSON.stringify(e.detail));}return r.json();}
  async function persist(copy){const name=document.querySelector('#namedProjectName').value.trim();if(!name){document.querySelector('#namedProjectStatus').textContent='请填写项目名称';return;}const id=copy?null:current?.id;
    if(saving)return;saving=true;
    try{current=await request('/api/form-apps/dfm/projects'+(id?'/'+id:''),{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,revision:id?current.revision:null,data:{f:S.f,t:S.t,i:S.i}})});
      LS_KEY='hpdc_dfm_project_a12:'+current.id;localStorage.setItem(LS_KEY,JSON.stringify(S));history.replaceState(null,'','/?project_id='+current.id);dialog.close();toast('已保存「'+current.name+'」· 版本 '+current.revision);
      updateLinks();
    }catch(e){document.querySelector('#namedProjectStatus').textContent=e.message;}finally{saving=false;}
  }
  document.querySelector('#namedSave').onclick=()=>persist(false);document.querySelector('#namedCopy').onclick=()=>persist(true);document.querySelector('#namedClose').onclick=()=>dialog.close();
  async function init(){try{if(qs.get('project_id')){current=await request('/api/form-apps/dfm/projects/'+qs.get('project_id'));mergeState(current.data);renderMain();refreshAll(true);save();toast('已载入「'+current.name+'」· 版本 '+current.revision);}else if(qs.has('new_project')){S.f={};S.t={};S.i={};initState();LS_KEY='hpdc_dfm_new_'+dfmUuid();renderMain();refreshAll(true);} }catch(e){toast('项目载入失败：'+e.message);}}
  init().then(updateLinks);
  return {showSave(){document.querySelector('#namedProjectName').value=current?.name||S.f.projName||S.f.partNo||'DFM 项目';document.querySelector('#namedProjectStatus').textContent=current?'将更新当前项目并创建新版本':'将创建新项目';document.querySelector('#namedCopy').hidden=!current;dialog.showModal();}};
})();
