'use strict';
// 工序与工序刀具行（业务数据重构 1b）：数据已落到服务端两张项目级表
// （project_processes / project_process_tools），这里把旧页面上"改内存 + 整份保存"
// 的写入点改成**行级保存**：改一个格 → PATCH 一行 → 服务端递增项目版本并留一个版本快照
// → 用 MachiningDFMHost.adopt(record) 接管内存与指纹 → 重绘。
//
// 约定（与四个基础库、项目信息一致）：
// * 本模块只做"写"，画面仍由 legacy_app.js 的 render()/bProcess() 出（DOM 不变）；
// * 每次写之前先读一次行列表拿行 id（不缓存行 id，避免 DOM 与缓存不同步写错行）；
// * 数字与布尔按页面口径归一：数字 parseFloat、勾选框 1/0；
// * 刀具行的刀号在旧 JSON 里叫 id，表里叫 code——只有这一处需要换名。
(function(){
  const API='/api/machining-dfm';
  const TR=v=>(typeof window.TR==='function')?window.TR(v):v;
  const host=()=>window.MachiningDFMHost||null;

  // 旧键 → 表里的字段键（其余同名；id 是刀号，不是行主键）
  const TOOL_KEY_ALIAS={id:'code'};
  // 刀柄/配件选型：选了就把库里的编号与价格一起存进快照（口径 4）
  const SNAP_KEYS={hld:{id:'hld_id',price:'hld_price',grp:'hld'},
                   acc:{id:'acc_id',price:'acc_price',grp:'acc'}};

  function current(){
    const h=host();
    return (h&&typeof h.current==='function')?h.current():null;
  }
  function enabled(){
    const project=current();
    return !!(project&&project.process_table);
  }
  function projectId(){
    const project=current();
    if(!project){notice(TR('没有打开的项目'),true);return null;}
    return project.id;
  }
  function notice(text,error){
    const h=host();
    if(h&&typeof h.status==='function'){h.status(text,!!error);return;}
    const el=document.getElementById('serverSaveStatus');
    if(el){el.textContent=text;el.classList.toggle('error',!!error);}
  }
  function repaint(){
    if(typeof window.render==='function'&&document.getElementById('mainPanels')){window.render();return true;}
    return false;
  }
  // 行级保存成功：服务端记录接管内存（含版本号与指纹），再换画面
  function adopt(record,note){
    const h=host();
    if(h&&typeof h.adopt==='function')h.adopt(record,note);
    else repaint();
    return record;
  }
  async function call(path,options){
    const h=host();
    if(!h||typeof h.api!=='function')throw new Error(TR('页面未连接服务端'));
    return h.api(path,options||{});
  }
  async function write(path,payload,method){
    const result=await call(path,{method:method||'PATCH',json:payload});
    return result.project||result;
  }
  // 读行列表（含行 id）。行 id 不缓存：DOM 里的下标只有对着最新列表才可靠。
  async function listing(pid){
    return call('/projects/'+encodeURIComponent(pid)+'/processes');
  }
  function rowName(row){return String((row&&row.nm)||'');}
  // 用下标定位行：先核对列表长度与页面一致，不一致说明画面已经过期，不猜、直接刷新
  function pickProcess(data,pi){
    const rows=(data&&data.processes)||[];
    if(rows.length!==Number(PR.length)){
      notice(TR('工序列表已变化，正在刷新，请再操作一次'),true);
      repaint();
      return null;
    }
    const row=rows[pi|0];
    if(!row){notice(TR('找不到这道工序，请刷新后重试'),true);repaint();return null;}
    return row;
  }
  function pickTool(data,pi,i){
    const process=pickProcess(data,pi);
    if(!process)return null;
    const tools=process.tools||[];
    const want=(PR[pi]&&PR[pi].tl)?PR[pi].tl.length:0;
    if(tools.length!==want){
      notice(TR('刀具行已变化，正在刷新，请再操作一次'),true);
      repaint();
      return null;
    }
    const row=tools[i|0];
    if(!row){notice(TR('找不到这把刀，请刷新后重试'),true);repaint();return null;}
    return row;
  }
  const number=value=>{const n=parseFloat(value);return isNaN(n)?0:n;};

  // ---------------- 工序 ----------------

  async function addProcess(){
    const pid=projectId();
    if(!pid)return null;
    const mid=(typeof MachinesPage!=='undefined'&&MachinesPage.defaultId)?(MachinesPage.defaultId()||''):'';
    const name='机加工序-OP'+((Number(PR.length)||0)+1)*10;
    notice(TR('正在新增工序…'));
    try{
      const record=await write('/projects/'+encodeURIComponent(pid)+'/processes',
        {nm:name,mid:mid,mc:1,nc:{cc:2,co:2,mc_:2,sc:2,ac:1,it:5}},
        'POST');
      // 工序在总表里，不再有"每道工序一个页签"：新增后停在总表（procView 由宿主维护）
      procView=-1;
      adaptTab();
      adopt(record,TR('已新增工序')+' · v'+record.revision);
      notice(TR('已新增工序')+' '+name+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('新增工序失败：')+error.message,true);
      return null;
    }
  }

  async function removeProcess(pi){
    const pid=projectId();
    if(!pid)return null;
    if(Number(PR.length)<=1){notice(TR('至少保留一道工序'),true);return null;}
    const name=rowName(PR[pi]);
    if(!confirm(TR('删除工序「')+name+TR('」？刀具行会一起进回收站，之后可以恢复（不会真正删除数据）。')))return null;
    notice(TR('正在删除工序…'));
    try{
      const data=await listing(pid);
      const row=pickProcess(data,pi);
      if(!row)return null;
      const record=await write('/projects/'+encodeURIComponent(pid)+'/processes/'+encodeURIComponent(row.id),
        {by:(current()||{}).operator||'',reason:TR('页面删除')},'DELETE');
      // 删掉的可能正是"正在看的那道工序"：退回总表；后面的工序整体前移一位
      if(procView===pi)procView=-1;else if(procView>pi)procView=procView-1;
      adaptTab();
      adopt(record,TR('工序已移入回收站')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('删除工序失败：')+error.message,true);
      return null;
    }
  }

  // 工艺设置页里的工序名与台数（旧页面是直接改内存，这里走行级保存）
  async function setProcessField(pi,key,value){
    const pid=projectId();
    if(!pid)return null;
    const payload={};
    if(key==='mc')payload.mc=Math.max(1,Math.round(number(value))||1);
    else if(key==='eqP'||key==='fixP')payload[key]=number(value);
    else payload[key]=value;
    notice(TR('正在保存…'));
    try{
      const data=await listing(pid);
      const row=pickProcess(data,pi);
      if(!row)return null;
      const record=await write('/projects/'+encodeURIComponent(pid)+'/processes/'+encodeURIComponent(row.id),payload);
      adopt(record,TR('工序已保存')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('保存失败：')+error.message,true);
      return null;
    }
  }

  async function setNC(pi,field,value){
    const pid=projectId();
    if(!pid)return null;
    const base=(PR[pi]&&PR[pi].nc)||{cc:2,co:2,mc_:2,sc:2,ac:1,it:5};
    const nc={cc:base.cc,co:base.co,mc_:base.mc_,sc:base.sc,ac:base.ac,it:base.it};
    nc[field]=number(value);
    notice(TR('正在保存…'));
    try{
      const data=await listing(pid);
      const row=pickProcess(data,pi);
      if(!row)return null;
      const record=await write('/projects/'+encodeURIComponent(pid)+'/processes/'+encodeURIComponent(row.id),{nc:nc});
      adopt(record,TR('非加工时间已保存')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('保存失败：')+error.message,true);
      return null;
    }
  }

  // 工序设备选择：走专门的 `PUT /projects/{id}/processes/{pid}/machine`（写 id + 快照；
  // 设备库有价时服务端同步这道工序的设备费，前端不用再补一次 PATCH）。
  async function setMachine(pi,mid){
    const pid=projectId();
    if(!pid)return null;
    notice(TR('正在保存…'));
    try{
      const data=await listing(pid);
      const row=pickProcess(data,pi);
      if(!row)return null;
      const value=String(mid||'').trim();
      const record=await write('/projects/'+encodeURIComponent(pid)+'/processes/'+encodeURIComponent(row.id)+'/machine',
        value?{machine_id:value}:null,value?'PUT':'DELETE');
      adopt(record,value?(TR('设备已保存')+' · v'+record.revision):(TR('已清空设备选择（改回兜底机型）')+' · v'+record.revision));
      return record;
    }catch(error){
      notice(TR('保存失败：')+error.message,true);
      return null;
    }
  }

  async function refreshEquipmentPrice(){
    const pid=projectId();
    if(!pid)return null;
    let data;
    try{data=await listing(pid);}catch(error){notice(TR('读取工序失败：')+error.message,true);return null;}
    const rows=data.processes||[];
    if(rows.length!==Number(PR.length)){notice(TR('工序列表已变化，正在刷新'),true);repaint();return null;}
    let changed=0,record=null;
    try{
      for(let pi=0;pi<rows.length;pi++){
        const mid=rows[pi].mid||'';
        const idx=(typeof midIndex==='function')?midIndex(mid):-1;
        const machine=idx<0?null:MDB[idx];
        const price=machine?parseFloat(machine.price):NaN;
        if(isNaN(price)||price<=0)continue;
        if(number(rows[pi].eqP)===price)continue;
        record=await write('/projects/'+encodeURIComponent(pid)+'/processes/'+encodeURIComponent(rows[pi].id),{eqP:price});
        changed++;
      }
    }catch(error){
      notice(TR('刷新设备成本失败：')+error.message,true);
      return null;
    }
    if(record)adopt(record,TR('设备成本已刷新')+' · '+changed+TR(' 道工序'));
    notice(changed?TR('已按设备库价格刷新 ')+changed+TR(' 道工序的设备成本'):TR('设备库里还没有填价格（设备成本保持不变）'),!changed);
    return record;
  }

  function adaptTab(){
    if(typeof PR==='undefined'||!PR)return;
    // 页签序号是固定的（SI 之后的都是后台页签），只有"看的是哪道工序"需要夹一下
    if(typeof procView==='number'&&(procView<-1||procView>=PR.length))procView=-1;
    if(curTab<0)curTab=0;
  }

  // ---------------- 工序刀具行 ----------------

  // 从刀具库选：把库里的参数与"编号 + 价格 + 寿命 + 组"一起存进行内快照（口径 4）
  function libraryTool(tp){
    const rows=(typeof TDB!=='undefined'&&TDB)?TDB:[];
    const group=(typeof G!=='undefined'&&G)?(G.prj||'hp'):'hp';
    for(let i=0;i<rows.length;i++){
      const row=rows[i],grp=row.grp||'hp';
      if(row.tp===tp&&(grp===group||grp==='hld'||grp==='acc'))return row;
    }
    return null;
  }
  function snapshotPayload(hit){
    const payload={};
    if(!hit)return payload;
    ['d','n','vf','ln','cat'].forEach(key=>{if(hit[key]!==undefined&&hit[key]!==null)payload[key]=hit[key];});
    payload.tool_id=hit.id||'';
    payload.tool_grp=hit.grp||'hp';
    payload.tool_price=number(hit.price);
    payload.tool_life=number(hit.life);
    return payload;
  }
  function snapshotHint(row){
    const hit=libraryTool(row.tp);
    if(!hit)return '';
    const price=number(hit.price),snap=number(row.tool_price);
    if(price>0&&snap>0&&Math.abs(price-snap)>1e-9){
      return TR('（提示：刀具库现价 ')+price+TR(' 元，行内仍是选型时的快照 ')+snap+TR(' 元；重选该刀具才会更新）');
    }
    if(!price&&!snap)return TR('（刀具库未录价格，这把刀的成本按 0 计）');
    return '';
  }

  async function saveTool(pid,row,payload,noteLabel){
    const record=await write('/projects/'+encodeURIComponent(pid)+'/tools/'+encodeURIComponent(row.id),payload);
    adopt(record,noteLabel+' · v'+record.revision);
    return record;
  }

  async function setToolFromLibrary(pi,i,tp){
    const pid=projectId();
    if(!pid)return null;
    const payload={tp:String(tp||'')};
    const hit=libraryTool(tp);
    Object.assign(payload,snapshotPayload(hit));
    notice(TR('正在保存…'));
    try{
      const data=await listing(pid);
      const row=pickTool(data,pi,i);
      if(!row)return null;
      const record=await saveTool(pid,row,payload,TR('刀具已保存'));
      const hint=snapshotHint({...row,...payload});
      notice(hit?TR('已从刀具库带入参数')+' '+TR('并记下价格/寿命快照')+hint:TR('刀具库没有「')+tp+TR('」，只保存了刀名'),!hit);
      return record;
    }catch(error){
      notice(TR('保存失败：')+error.message,true);
      return null;
    }
  }

  async function setToolText(pi,i,key,value){
    const pid=projectId();
    if(!pid)return null;
    const payload={};
    payload[TOOL_KEY_ALIAS[key]||key]=value;
    // 选了刀柄/配件：连库里的编号与价格一起快照
    if(SNAP_KEYS[key]){
      const spec=SNAP_KEYS[key];
      let hit=null;
      const rows=(typeof TDB!=='undefined'&&TDB)?TDB:[];
      for(let j=0;j<rows.length;j++){if((rows[j].grp||'hp')===spec.grp&&rows[j].tp===value){hit=rows[j];break;}}
      payload[spec.id]=hit?(hit.id||''):'';
      payload[spec.price]=hit?number(hit.price):0;
    }
    notice(TR('正在保存…'));
    try{
      const data=await listing(pid);
      const row=pickTool(data,pi,i);
      if(!row)return null;
      const record=await saveTool(pid,row,payload,TR('刀具已保存'));
      if(SNAP_KEYS[key]&&value){
        notice(TR('选型已保存')+(payload[SNAP_KEYS[key].price]>0?TR('，已记下库价快照 ')+payload[SNAP_KEYS[key].price]+TR(' 元'):TR('，库里还没填这个选型的价格')));
      }
      return record;
    }catch(error){
      notice(TR('保存失败：')+error.message,true);
      return null;
    }
  }

  async function setToolNumber(pi,i,key,value){
    const pid=projectId();
    if(!pid)return null;
    const payload={};
    payload[TOOL_KEY_ALIAS[key]||key]=number(value);
    notice(TR('正在保存…'));
    try{
      const data=await listing(pid);
      const row=pickTool(data,pi,i);
      if(!row)return null;
      const record=await saveTool(pid,row,payload,TR('刀具已保存'));
      notice(TR('刀具已保存')+' · v'+record.revision+snapshotHint({...row,...payload}));
      return record;
    }catch(error){
      notice(TR('保存失败：')+error.message,true);
      return null;
    }
  }

  async function setBigTool(pi,i,checked){
    const pid=projectId();
    if(!pid)return null;
    notice(TR('正在保存…'));
    try{
      const data=await listing(pid);
      const row=pickTool(data,pi,i);
      if(!row)return null;
      const record=await saveTool(pid,row,{bg:checked?1:0},TR('大刀标记已保存'));
      notice(TR('大刀标记已保存')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('保存失败：')+error.message,true);
      return null;
    }
  }

  async function addTool(pi){
    const pid=projectId();
    if(!pid)return null;
    notice(TR('正在新增刀具行…'));
    try{
      const data=await listing(pid);
      const process=pickProcess(data,pi);
      if(!process)return null;
      const count=(process.tools||[]).length;
      const record=await write('/projects/'+encodeURIComponent(pid)+'/processes/'+encodeURIComponent(process.id)+'/tools',
        {code:'T'+(count+1),tp:'',ds:'新特征',d:10,n:3000,vf:1200,ln:50,ps:1,cn:1,bg:0,td:500,tt:2,sd:1,cat:'other',hld:'',acc:''},
        'POST');
      adopt(record,TR('已新增刀具行')+' · v'+record.revision);
      notice(TR('已新增刀具行')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('新增刀具行失败：')+error.message,true);
      return null;
    }
  }

  async function removeTool(pi,i){
    const pid=projectId();
    if(!pid)return null;
    if(Number((PR[pi]&&PR[pi].tl?PR[pi].tl.length:0))<=1){notice(TR('每道工序至少保留一把刀'),true);return null;}
    const name=(PR[pi].tl[i]||{}).tp||(PR[pi].tl[i]||{}).id||'';
    if(!confirm(TR('删除刀具行「')+name+TR('」？会移入回收站，之后可以恢复。')))return null;
    notice(TR('正在删除刀具行…'));
    try{
      const data=await listing(pid);
      const row=pickTool(data,pi,i);
      if(!row)return null;
      const record=await write('/projects/'+encodeURIComponent(pid)+'/tools/'+encodeURIComponent(row.id),
        {by:(current()||{}).operator||'',reason:TR('页面删除')},'DELETE');
      adopt(record,TR('刀具行已移入回收站')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('删除刀具行失败：')+error.message,true);
      return null;
    }
  }

  // ---------------- 图片（夹具示意图 cI / 刀具图 fi） ----------------

  function rest(path,blob){
    const h=host(),project=current();
    if(!h||!project)return Promise.reject(new Error(TR('没有打开的项目')));
    const headers={};
    if(blob.type)headers['Content-Type']=blob.type;
    return fetch(API+path,{method:'PUT',cache:'no-store',headers,body:blob}).then(async response=>{
      if(!response.ok){
        let detail=TR('上传失败');
        try{detail=(await response.json()).detail||detail;}catch(e){}
        throw new Error(detail);
      }
      return response.json();
    });
  }
  // 旧页面把 data URL 直接塞进内存；现在先落附件库，行里只存附件地址
  function toBlob(value){
    if(value&&typeof value==='string'&&value.indexOf('data:')===0){
      return fetch(value).then(response=>response.blob());
    }
    return Promise.resolve(value);
  }
  async function setProcessPhoto(pi,value){
    const pid=projectId();
    if(!pid)return null;
    notice(TR('正在保存夹具示意图…'));
    try{
      const data=await listing(pid);
      const row=pickProcess(data,pi);
      if(!row)return null;
      let record;
      if(!value){
        record=await write('/projects/'+encodeURIComponent(pid)+'/processes/'+encodeURIComponent(row.id)+'/photo',{},'DELETE');
      }else{
        const blob=await toBlob(value);
        const result=await rest('/projects/'+encodeURIComponent(pid)+'/processes/'+encodeURIComponent(row.id)+'/photo',blob);
        record=result.project;
      }
      adopt(record,TR('夹具示意图已更新')+' · v'+record.revision);
      notice(TR('夹具示意图已更新')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('夹具示意图保存失败：')+error.message,true);
      return null;
    }
  }
  async function setToolPhoto(pi,i,value){
    const pid=projectId();
    if(!pid)return null;
    notice(TR('正在保存刀具图片…'));
    try{
      const data=await listing(pid);
      const row=pickTool(data,pi,i);
      if(!row)return null;
      let record;
      if(!value){
        record=await write('/projects/'+encodeURIComponent(pid)+'/tools/'+encodeURIComponent(row.id)+'/photo',{},'DELETE');
      }else{
        const blob=await toBlob(value);
        const result=await rest('/projects/'+encodeURIComponent(pid)+'/tools/'+encodeURIComponent(row.id)+'/photo',blob);
        record=result.project;
      }
      adopt(record,TR('刀具图片已更新')+' · v'+record.revision);
      notice(TR('刀具图片已更新')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('刀具图片保存失败：')+error.message,true);
      return null;
    }
  }

  // 重新从服务端拉一次（表是唯一权威，页面上任何"看着不对"都先来一下这个）
  async function reload(){
    const h=host(),project=current();
    if(!h||!project)return null;
    notice(TR('正在重新载入工序…'));
    try{
      const record=await h.api('/projects/'+encodeURIComponent(project.id));
      adopt(record,TR('工序已从服务端重新载入')+' · v'+record.revision);
      notice(TR('工序已从服务端重新载入')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('重新载入失败：')+error.message,true);
      return null;
    }
  }

  // 只读：回收站里现在有多少（回收站界面在逻辑删除阶段做）
  async function recycleBin(){
    const pid=projectId();
    if(!pid)return null;
    try{
      const data=await listing(pid);
      return {processes:data.deleted_processes||[],tools:data.deleted_tools||[]};
    }catch(error){
      notice(TR('读取回收站失败：')+error.message,true);
      return null;
    }
  }

  window.ProcessPage={enabled,repaint,reload,recycleBin,
    addProcess,removeProcess,setProcessField,setNC,setMachine,refreshEquipmentPrice,
    addTool,removeTool,setToolFromLibrary,setToolText,setToolNumber,setBigTool,
    setProcessPhoto,setToolPhoto,
    toolKeyAlias:()=>({...TOOL_KEY_ALIAS}),snapshotKeys:()=>({...SNAP_KEYS})};
})();
