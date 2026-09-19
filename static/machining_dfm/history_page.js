'use strict';
// 版本履历（业务数据重构 3a）：数据已落到服务端表 project_versions（kind='history'），
// 这里把旧页面上「改内存 VH[i].xxx + 整份保存」的写入点改成**按行行级保存**：
// 改一格 → PATCH 一行 → 服务端递增项目版本并留一个版本快照
//   → MachiningDFMHost.adopt(record) 接管内存 → 重绘。
//
// 页面对一行只有**下标**（VH[i]），没有行 id，所以每次写入都先读一次服务端清单，
// 用下标换 id；下标越界（列表被别处改过）就只刷新、不瞎写。
//
// 与保存版本（ProjectVersions kind='save'）的分工：
//   保存版本 = 每次保存一行全量快照，走 GET /versions + 「恢复此版本」；
//   版本履历 = 页面上这张表，就是本模块管的行。
// 两者同在一张表里，用 kind 分开（见 app/machining_history.py）。
//
// 约定与 process_page.js / issue_page.js / selection_page.js 相同：本模块只做「写」，
// 画面仍由 legacy_app.js 的版本履历卡片与 PPT 导出出。
(function(){
  const API='/api/machining-dfm';
  const TR=v=>(typeof window.TR==='function')?window.TR(v):v;
  const host=()=>window.MachiningDFMHost||null;
  //: 页面上那四个格子（顺序 = 旧 vh[] 行的键序）
  const FIELDS=['dt','ver','ds','by'];

  function current(){
    const h=host();
    return (h&&typeof h.current==='function')?h.current():null;
  }
  function enabled(){
    const project=current();
    return !!(project&&project.history_table);
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
  async function listing(pid){
    return call('/projects/'+encodeURIComponent(pid)+'/history');
  }
  // 行必须真的还在（列表可能刚被别处改过）：按下标换 id，越界就不猜，刷新后重来
  async function rowAt(pid,index){
    const data=await listing(pid);
    const rows=(data&&data.history)||[];
    const row=rows[index|0];
    if(!row){
      notice(TR('这一行已经不在了（列表变过），正在刷新'),true);
      repaint();
      return null;
    }
    return {data:data,row:row};
  }
  function done(record,what){
    adopt(record,what+' · v'+record.revision);
    notice(what+' · v'+record.revision);
    return record;
  }

  // ---------------- 写入 ----------------

  // 改一个格子（dt/ver/ds/by 任意一个）
  async function setField(index,key,value){
    const pid=projectId();
    if(!pid)return null;
    if(FIELDS.indexOf(key)<0){notice(TR('不认识的列：')+key,true);return null;}
    try{
      const found=await rowAt(pid,index);
      if(!found)return null;
      const body={};
      body[key]=value==null?'':String(value);
      const record=(await call('/projects/'+encodeURIComponent(pid)+'/history/'
        +encodeURIComponent(found.row.id),{method:'PATCH',json:body})).project;
      return done(record,TR('版本履历已保存'));
    }catch(error){
      notice(TR('版本履历保存失败：')+error.message,true);
      return null;
    }
  }
  // 新增一行（fields 可省：与页面 addVH() 的默认值一致——日期今天、其余空）
  async function add(fields){
    const pid=projectId();
    if(!pid)return null;
    try{
      const record=(await call('/projects/'+encodeURIComponent(pid)+'/history',
        {method:'POST',json:fields||{}})).project;
      return done(record,TR('已新增一行版本履历'));
    }catch(error){
      notice(TR('新增版本履历失败：')+error.message,true);
      return null;
    }
  }
  // 删除一行（逻辑删除：行还在表里，回收站能恢复——口径 2 永不物理删除）
  async function remove(index){
    const pid=projectId();
    if(!pid)return null;
    try{
      const found=await rowAt(pid,index);
      if(!found)return null;
      const record=(await call('/projects/'+encodeURIComponent(pid)+'/history/'
        +encodeURIComponent(found.row.id)+'?reason='+encodeURIComponent('页面删除'),
        {method:'DELETE'})).project;
      return done(record,TR('已删除该版本记录（回收站可恢复）'));
    }catch(error){
      notice(TR('删除版本履历失败：')+error.message,true);
      return null;
    }
  }
  // 读一次清单（页面要"服务端这行现在是什么"时调它，别自己猜）
  async function reload(){
    const pid=projectId();
    if(!pid)return null;
    try{
      return await listing(pid);
    }catch(error){
      notice(TR('读取版本履历失败：')+error.message,true);
      return null;
    }
  }

  window.HistoryPage={
    enabled:enabled, FIELDS:FIELDS,
    setField:setField, add:add, remove:remove, reload:reload,
    //: 内部函数导出一份，便于冒烟与单测直接断言（正式代码只调上面几个）
    _listing:listing, _rowAt:rowAt
  };
})();
