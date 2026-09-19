'use strict';
(function(){
  const API='/api/machining-dfm';
  let current=null,projects=[],archived=false,ready=false,timer=null,saving=null;
  let config={site_title:'机加 DFM 项目工作台',autosave_ms:1200};
  let sharedLibraries=null,libraryFingerprint='',projectFingerprint='',pendingRole='admin';
  const tokens={process:sessionStorage.getItem('machiningDfmProcessToken')||'',admin:sessionStorage.getItem('machiningDfmAdminToken')||''};
  const $=s=>document.querySelector(s);
  const clone=value=>JSON.parse(JSON.stringify(value));
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function state(){if(typeof sve==='function')sve();return {mdb:MDB,tdb:TDB,pr:PR,is:IS,fdb:FDB,idb:IDB,vh:VH,G:G};}
  // 四个基础库都已是独立表、按行直存（设备/刀具/夹具/检具），类别走字典接口：
  // 这里不再有"整库保存"的内容，旧的 PUT /libraries 只留给缓存了旧 JS 的页面。
  function libraryState(){return {};}
  // 类别列表来自字典表，页面只在 G.icnX / G.fcnX 上做只读缓存（报价选型按类别下标对齐）。
  function categoryState(){return {icnX:(G&&G.icnX)||[],fcnX:(G&&G.fcnX)||[]};}
  function projectState(value){const g=clone(value.G||{});delete g.icnX;delete g.fcnX;return {pr:value.pr,is:value.is,vh:value.vh,G:g};}
  const signature=value=>JSON.stringify(value);
  async function request(path,options={}){const token=options.token||'';const init={...options};delete init.token;const headers=new Headers(init.headers||{});if(token)headers.set('Authorization','Bearer '+token);if(init.json!==undefined){headers.set('Content-Type','application/json');init.body=JSON.stringify(init.json);delete init.json;}init.headers=headers;const response=await fetch(API+path,{cache:'no-store',...init});if(!response.ok){let detail='请求失败';try{detail=(await response.json()).detail||detail;}catch(e){}throw new Error(detail);}return response.json();}
  function write(path,body,method='POST',token=''){return request(path,{method,token,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
  function status(text,error=false){const el=$('#serverSaveStatus');if(!el)return;el.textContent=text;el.classList.toggle('error',error);}
  function projectLabel(p){return (p.archived?'[已删除] ':'')+p.name+' · v'+p.revision;}
  function drawProjects(){const select=$('#serverProjectSelect');if(!select)return;select.innerHTML=projects.map(p=>`<option value="${p.id}" ${current&&p.id===current.id?'selected':''}>${esc(projectLabel(p))}</option>`).join('');$('#serverArchive').textContent=archived?'恢复项目':'删除项目';$('#serverArchive').classList.toggle('danger',!archived);}
  function installBar(){const bar=document.createElement('div');bar.id='serverProjectBar';bar.innerHTML='<strong id="serverTitle">机加 DFM 项目</strong><select id="serverProjectSelect" aria-label="当前项目"></select><button id="serverNew" class="primary">新建</button><button id="serverSave">立即保存</button><button id="serverPpt">PPT模板工作台</button><button id="serverArchive" class="danger">删除项目</button><button id="serverVersions">历史版本</button><button id="serverBackend">后台配置</button><label><input id="serverShowArchived" type="checkbox"> 已删除项目</label><a id="serverFormCenter" href="/forms">表单中心</a><span id="serverSaveStatus" class="server-status">正在连接服务端…</span>';document.body.insertBefore(bar,document.body.firstChild);
    const version=document.createElement('div');version.id='serverVersionDialog';version.className='server-dialog';version.hidden=true;version.innerHTML='<div class="server-dialog-box"><div class="server-dialog-head"><h2>历史版本</h2><button id="serverVersionClose">关闭</button></div><div id="serverVersionList"></div></div>';document.body.appendChild(version);
    const backend=document.createElement('div');backend.id='serverBackendDialog';backend.className='server-dialog';backend.hidden=true;backend.innerHTML='<div class="server-dialog-box"><div class="server-dialog-head"><h2>后台配置</h2><button id="serverBackendClose">关闭</button></div><section id="serverLogin"><label>登录角色<select id="serverLoginRole"><option value="admin">管理员</option><option value="process">工艺设置</option></select></label><label>密码<input id="serverLoginPassword" type="password" autocomplete="current-password"></label><button id="serverLoginSubmit" class="primary">登录</button><p id="serverLoginStatus" class="muted"></p></section><section id="serverAdminConfig" hidden><div class="server-counts" id="serverLibraryCounts"></div><label>工作台名称<input id="serverSiteTitle" maxlength="100"></label><label>自动保存延迟（毫秒）<input id="serverAutosaveMs" type="number" min="500" max="10000"></label><button id="serverConfigSave">保存后台配置</button><hr><label>修改密码<select id="serverPasswordRole"><option value="process">工艺设置密码</option><option value="admin">管理员密码</option></select></label><label>新密码<input id="serverNewPassword" type="password" minlength="6" autocomplete="new-password"></label><button id="serverPasswordSave">更新密码</button><hr><div class="btn-row"><button id="serverOpenProcess">打开工艺设置</button><button id="serverOpenLibraries" class="primary">管理设备/刀具/夹具/检具</button><button id="serverLogout">退出后台登录</button></div><p id="serverAdminStatus" class="muted"></p></section></div>';document.body.appendChild(backend);
    $('#serverProjectSelect').onchange=()=>open($('#serverProjectSelect').value);$('#serverNew').onclick=create;$('#serverSave').onclick=()=>persist(true);$('#serverPpt').onclick=openPptWorkbench;$('#serverArchive').onclick=archiveCurrent;$('#serverVersions').onclick=showVersions;$('#serverBackend').onclick=()=>openBackend('admin');
    $('#serverShowArchived').onchange=async e=>{await flush();archived=e.target.checked;projects=(await request('/projects?archived='+archived)).projects;current=null;drawProjects();if(projects.length)await open(projects[0].id);else status(archived?'没有已删除项目':'没有可用项目');};
    $('#serverVersionClose').onclick=()=>version.hidden=true;version.onclick=e=>{if(e.target===version)version.hidden=true;};
    $('#serverBackendClose').onclick=()=>backend.hidden=true;backend.onclick=e=>{if(e.target===backend)backend.hidden=true;};
    $('#serverLoginSubmit').onclick=login;$('#serverLoginPassword').onkeydown=e=>{if(e.key==='Enter')login();};$('#serverConfigSave').onclick=saveConfig;$('#serverPasswordSave').onclick=changePassword;$('#serverOpenProcess').onclick=openProcessSettings;$('#serverOpenLibraries').onclick=openLibrarySettings;$('#serverLogout').onclick=logout;
  }
  async function refresh(activeId){projects=(await request('/projects?archived='+archived)).projects;if(activeId){const found=projects.find(p=>p.id===activeId);if(found&&current)current={...current,...found};}drawProjects();}
  // 行级保存（项目信息等模块）之后由服务端记录统一"接管"当前状态：
  // 换掉当前项目、合并服务端回来的数据、刷新指纹（否则下一次整份保存会拿旧内存覆盖新值）。
  function adopt(record,note){ready=false;current=record;applyData(record.state);sharedLibraries=clone(libraryState(record.state));libraryFingerprint=signature(sharedLibraries);projectFingerprint=signature(projectState(record.state));render();ready=true;status(note||('已更新 · 版本 '+record.revision));drawProjects();return current;}
  function apply(record){adopt(record,'已载入 · 版本 '+record.revision);setTimeout(shrinkImgs,1200);document.body.classList.remove('server-loading');}
  async function open(id){if(!id)return;await flush();status('正在载入…');apply(await request('/projects/'+encodeURIComponent(id)+(archived?'?allow_archived=true':'')));}
  async function persist(explicit=false){if(!ready||!current||current.archived)return current;if(saving)return saving;clearTimeout(timer);timer=null;saving=(async()=>{status('正在保存…');const snapshot=state();const nextLibraries=libraryState(snapshot);const nextLibrarySignature=signature(nextLibraries);let librarySaved=false;if(nextLibrarySignature!==libraryFingerprint){if(tokens.admin){await write('/libraries',nextLibraries,'PUT',tokens.admin);sharedLibraries=clone(nextLibraries);libraryFingerprint=nextLibrarySignature;librarySaved=true;}else{FDB=clone(sharedLibraries.fdb);IDB=clone(sharedLibraries.idb);G.icnX=clone(sharedLibraries.icnX);G.fcnX=clone(sharedLibraries.fcnX);}}
      const nextProjectSignature=signature(projectState(snapshot));if(nextProjectSignature!==projectFingerprint){current=await write('/projects/'+encodeURIComponent(current.id),{name:current.name,state:snapshot,revision:current.revision},'PUT');projectFingerprint=signature(projectState(current.state));sharedLibraries=clone(libraryState(current.state));libraryFingerprint=signature(sharedLibraries);await refresh(current.id);status('项目已保存 · 版本 '+current.revision);}else status(librarySaved?'公共基础库已保存':'没有需要保存的项目修改');if(explicit)alert(librarySaved?'项目/公共基础库已保存':'项目已保存到服务端');return current;})().catch(error=>{status(error.message,true);if(explicit)alert('保存失败：'+error.message);throw error;}).finally(()=>saving=null);return saving;}
  function scheduleSave(){if(!ready||!current||current.archived)return;clearTimeout(timer);status('有修改，等待自动保存…');timer=setTimeout(()=>persist(false).catch(()=>{}),Number(config.autosave_ms)||1200);}
  async function flush(){if(timer){clearTimeout(timer);timer=null;await persist(false);}else if(saving)await saving;}
  // 新建项目：先取名，再跳到"项目信息"页把客户/零件/产能参数填好（新项目从项目信息开始维护）
  async function create(){await flush();const name=prompt('请输入新项目名称：','DFM_'+((G&&G.part)||'新项目').replace(/\s/g,'_'));if(!name||!name.trim())return;const defaults=await request('/defaults');applyData(defaults);const record=await write('/projects',{name:name.trim(),state:state()});archived=false;$('#serverShowArchived').checked=false;await refresh(record.id);apply(record);curTab=0;render();status('项目已创建，请先填写项目信息 · 版本 '+record.revision);}
  async function saveAs(){await flush();const name=prompt('请输入新项目名称：',(current?current.name:'DFM项目')+'_副本');if(!name||!name.trim())return;const record=await write('/projects',{name:name.trim(),state:state()});archived=false;$('#serverShowArchived').checked=false;await refresh(record.id);apply(record);alert('已另存为新项目');}
  async function openPptWorkbench(){if(!current||current.archived){alert('请先选择可用项目');return;}try{await flush();await persist(false);const response=await fetch('/api/integration/workbench-link?app_id=machining-dfm&project_id='+encodeURIComponent(current.id));if(!response.ok)throw new Error('工作台地址读取失败');location.href=(await response.json()).url;}catch(error){status(error.message,true);}}
  // 项目"删除/恢复"走阶段 4 的接口（口径 2：没有彻底删除，恢复只给管理员，两头都留流水）。
  // 老路径 POST /projects/{id}/archive 仍在，只是页面不再用它。
  async function archiveCurrent(){
    if(!current)return;
    if(archived){                                   // 在"已删除项目"里：按钮就是"恢复项目"
      if(!validToken('admin')){alert('恢复项目需要管理员身份，请先到「后台配置」用管理员密码登录。');openBackend('admin');return;}
      let result;
      try{result=await write('/projects/'+encodeURIComponent(current.id)+'/restore',{},'POST',tokens.admin);}
      catch(error){status(error.message,true);alert('恢复失败：'+error.message);return;}
      archived=false;$('#serverShowArchived').checked=false;await refresh(result.project.id);apply(result.project);
      notifyTrash('probe');status('项目已恢复 · 版本 '+result.project.revision);
      return;
    }
    if(!validToken('admin')){alert('删除项目需要管理员身份（删除会记一条变更流水，随时可在回收站恢复）。请先到「后台配置」用管理员密码登录。');openBackend('admin');return;}
    if(!confirm('删除后项目进「已删除项目」（逻辑删除，随时可恢复），数据库与历史版本全部保留。继续？'))return;
    const reason=(prompt('删除原因（会记到变更流水和回收站里，可留空）：','')||'').trim();
    try{await write('/projects/'+encodeURIComponent(current.id)+'?reason='+encodeURIComponent(reason),{},'DELETE',tokens.admin);}
    catch(error){status(error.message,true);alert('删除失败：'+error.message);return;}
    projects=(await request('/projects')).projects;
    if(projects.length)apply(await request('/projects/'+projects[0].id));
    else{current=null;drawProjects();status('项目已删除，可在「回收站」里恢复');document.body.classList.add('server-loading');}
    notifyTrash('probe');
  }
  async function showVersions(){if(!current)return;const result=await request('/projects/'+encodeURIComponent(current.id)+'/versions');$('#serverVersionList').innerHTML=result.versions.map(v=>`<div class="server-version"><div><b>版本 ${v.revision}</b><small>${esc(new Date(v.created).toLocaleString())} · ${esc(v.name)}</small></div><button data-version="${v.revision}">恢复此版本</button></div>`).join('');$('#serverVersionList').onclick=async e=>{const version=e.target.dataset.version;if(!version)return;if(!confirm('恢复后会保存为一个新版本，当前历史不会删除。继续？'))return;const old=await request('/projects/'+encodeURIComponent(current.id)+'?revision='+version);current=await write('/projects/'+encodeURIComponent(current.id),{name:old.name,state:old.state,revision:current.revision},'PUT');apply(current);$('#serverVersionDialog').hidden=true;};$('#serverVersionDialog').hidden=false;}
  async function reset(){if(!confirm('确认用原文件初始项目数据重置当前项目？公共基础库不会被重置，且项目仍可从历史版本恢复。'))return;const defaults=await request('/defaults');applyData({...defaults,G:{...defaults.G,...categoryState()}});render();scheduleSave();}
  // 回收站（阶段 4）：登录成功后入口才可能出现（读回收站要登录），退出登录后整块收回去。
  // TrashPage 没加载（老缓存页面）时这里什么都不做，页面照常工作。
  function notifyTrash(method){try{const page=(typeof window!=='undefined')?window.TrashPage:null;if(page&&typeof page[method]==='function')page[method]();}catch(error){}}
  function validToken(role){return role==='admin'?!!tokens.admin:!!(tokens.process||tokens.admin);}
  function requireRole(role){if(validToken(role)){if(role==='admin')adUnl=true;else dbUnl=true;return true;}openBackend(role);return false;}
  async function openBackend(role='admin'){pendingRole=role;$('#serverBackendDialog').hidden=false;$('#serverLoginRole').value=role;$('#serverLoginPassword').value='';$('#serverLoginStatus').textContent='';if(role==='admin'&&tokens.admin)await showAdminConfig();else{$('#serverLogin').hidden=false;$('#serverAdminConfig').hidden=true;setTimeout(()=>$('#serverLoginPassword').focus(),0);}}
  async function login(){const role=$('#serverLoginRole').value,password=$('#serverLoginPassword').value;$('#serverLoginStatus').textContent='正在验证…';try{const result=await write('/auth/login',{role,password});tokens[role]=result.token;sessionStorage.setItem(role==='admin'?'machiningDfmAdminToken':'machiningDfmProcessToken',result.token);$('#serverLoginStatus').textContent='登录成功';notifyTrash('probe');if(role==='admin'){adUnl=true;await showAdminConfig();}else{dbUnl=true;openProcessSettings();}}catch(error){$('#serverLoginStatus').textContent=error.message;}}
  async function showAdminConfig(){const [settings,libraries]=await Promise.all([request('/config'),request('/libraries')]);config={...config,...settings};$('#serverLogin').hidden=true;$('#serverAdminConfig').hidden=false;$('#serverSiteTitle').value=config.site_title||'';$('#serverAutosaveMs').value=config.autosave_ms||1200;const labels={mdb:'设备',tdb:'刀具',fdb:'夹具',idb:'检具'};$('#serverLibraryCounts').innerHTML=Object.entries(libraries.counts).map(([key,value])=>`<span>${labels[key]} <b>${value}</b> 条</span>`).join('');}
  async function saveConfig(){try{config=await write('/config',{site_title:$('#serverSiteTitle').value.trim(),autosave_ms:Number($('#serverAutosaveMs').value)},'PUT',tokens.admin);$('#serverTitle').textContent=config.site_title;$('#serverAdminStatus').textContent='后台配置已保存';}catch(error){$('#serverAdminStatus').textContent=error.message;}}
  async function changePassword(){const role=$('#serverPasswordRole').value,password=$('#serverNewPassword').value;if(password.length<6){$('#serverAdminStatus').textContent='新密码至少 6 位';return;}try{await write('/auth/password',{role,password},'PUT',tokens.admin);$('#serverNewPassword').value='';if(role==='process'){tokens.process='';sessionStorage.removeItem('machiningDfmProcessToken');}$('#serverAdminStatus').textContent=(role==='admin'?'管理员':'工艺设置')+'密码已更新';}catch(error){$('#serverAdminStatus').textContent=error.message;}}
  function openProcessSettings(){dbUnl=true;$('#serverBackendDialog').hidden=true;curTab=SI+2;render();}
  function openLibrarySettings(){adUnl=true;$('#serverBackendDialog').hidden=true;curTab=SI+3;render();}
  function logout(){tokens.admin='';tokens.process='';sessionStorage.removeItem('machiningDfmAdminToken');sessionStorage.removeItem('machiningDfmProcessToken');adUnl=false;dbUnl=false;$('#serverBackendDialog').hidden=true;curTab=0;notifyTrash('reset');render();status('已退出后台登录');}
  async function start(){installBar();fetch('/api/integration/services').then(r=>r.json()).then(links=>{$('#serverFormCenter').href=links.hpdc;}).catch(()=>{});const params=new URLSearchParams(location.search);try{const boot=await request('/bootstrap'+(params.get('project_id')?'?project_id='+encodeURIComponent(params.get('project_id')):''));projects=boot.projects;config={...config,...boot.config};$('#serverTitle').textContent=config.site_title;apply(boot.project);window.saveAll=()=>persist(true);window.saveAs=saveAs;window.resetData=reset;window.addEventListener('beforeunload',()=>{if(timer)persist(false).catch(()=>{});});}catch(error){document.body.classList.remove('server-loading');status('加载失败：'+error.message,true);alert('机加 DFM 加载失败：'+error.message);}}
  window.MachiningDFMHost={start,scheduleSave,save:persist,saveAs,requireRole,openBackend,logout,token:role=>tokens[role]||'',api:request,adopt,current:()=>current,status,libraryState,categoryState};
})();
