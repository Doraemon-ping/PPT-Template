'use strict';
// 选型（业务数据重构 2b → 拆表）：数据落在服务端**两张项目级表**上——
// 夹具选型 project_fixtures、检具选型 project_gauges；这里把旧页面上
// 「改内存 G.fixQ[k] / G.insp[k] + 整份保存」的写入点改成**按格子行级保存**：
// 选一格 → PUT 一个格子 → 服务端递增项目版本并留一个版本快照
// → MachiningDFMHost.adopt(record) 接管内存 → 重绘。
//
// 坐标只有两个：**哪一类（路径 /fixtures 或 /gauges）+ 格子下标（slot）**。
//   夹具：格子顺序 = 模具中心字典顺序（页面 fixClasses()）
//   检具：格子顺序 = 检具类别字典顺序（页面 inspClasses()）
// 页面天然只有下标，所以接口也只认这个坐标，不需要（也不该）缓存行 id。
// 两类各打各的接口（不再有 /selections/{kind}/{slot} 这种带 kind 的多态路径）。
//
// 与设计口径对应的一处行为变化（有意为之）：
//   旧结构里存的是拼出来的字符串（"中心|名称"），库里改名之后它就指向了不存在的夹具；
//   现在页面选的**库里那一行**（外键 fixture_id/gauge_id），读模型按当前库值现算字符串，
//   库行被删则回退到选型当时的快照（口径 4）。
//
// 约定与 process_page.js / issue_page.js 相同：本模块只做「写」，
// 画面仍由 legacy_app.js 的 fixQuoteTable()/inspQuoteTable() 出。
(function(){
  const API='/api/machining-dfm';
  const TR=v=>(typeof window.TR==='function')?window.TR(v):v;
  const host=()=>window.MachiningDFMHost||null;

  //: 旧数组键 → 选型类别（写入口用）
  const KIND_OF={fixQ:'fixture',insp:'gauge'};
  //: 类别 → 服务端路径段（两张表各一套接口）
  const KIND_PATH={fixture:'fixtures',gauge:'gauges'};
  //: 类别 → 页面上的类别顺序从哪来（只用于"下标越界"的人话提示）
  const KIND_LABEL={fixture:'夹具',gauge:'检具'};
  //: 类别 → 页面更新价格/工期用的旧函数（渲染仍归 legacy_app.js）
  const REFRESH={fixQ:'setFixSel',insp:'setInspSel'};

  function current(){
    const h=host();
    return (h&&typeof h.current==='function')?h.current():null;
  }
  function enabled(){
    const project=current();
    return !!(project&&project.selection_table);
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
  async function listing(pid,kind){
    return call('/projects/'+encodeURIComponent(pid)+'/'+(KIND_PATH[kind]||KIND_PATH.fixture));
  }
  // 格子必须真的还在（字典可能刚被改过）：不在就不猜，刷新后重来
  async function slotAt(pid,kind,slot){
    const data=await listing(pid,kind);
    const rows=(data&&data.slots)||[];
    const row=rows[slot|0];
    if(!row){
      notice(TR('这一格已经不在了（类别字典变过），正在刷新'),true);
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

  // 选一格：value = 旧格式字符串（"中心|名称" / "类别|名称|图号"），空串 = 清空这一格。
  // 字符串原样提交，服务端按"唯一才绑"的规矩找库行（不猜），页面不用关心库行 id。
  async function setSelection(kind,slot,value){
    const pid=projectId();
    if(!pid)return null;
    const label=KIND_LABEL[kind]||kind;
    try{
      const found=await slotAt(pid,kind,slot);
      if(!found)return null;
      const text=String(value==null?'':value);
      const path='/projects/'+encodeURIComponent(pid)+'/'
        +(KIND_PATH[kind]||KIND_PATH.fixture)+'/'+encodeURIComponent(slot);
      let record;
      if(text){
        record=(await call(path,{method:'PUT',json:{legacy_key:text}})).project;
      }else{
        record=(await call(path,{method:'DELETE'})).project;
      }
      return done(record,TR(label+'选型已保存'));
    }catch(error){
      notice(TR(label+'选型保存失败：')+error.message,true);
      return null;
    }
  }
  // 只改「是否报价」这一个勾选（不动选型）
  async function setQuoted(kind,slot,on){
    const pid=projectId();
    if(!pid)return null;
    const label=KIND_LABEL[kind]||kind;
    try{
      const found=await slotAt(pid,kind,slot);
      if(!found)return null;
      const record=(await call('/projects/'+encodeURIComponent(pid)+'/'
        +(KIND_PATH[kind]||KIND_PATH.fixture)+'/'+encodeURIComponent(slot),
        {method:'PATCH',json:{quoted:on?1:0}})).project;
      return done(record,TR(label+'报价设置已保存'));
    }catch(error){
      notice(TR(label+'报价设置保存失败：')+error.message,true);
      return null;
    }
  }
  // 读一次列表（页面要用"服务端这一格现在是什么"时调它，别自己猜）
  async function reload(kind){
    const pid=projectId();
    if(!pid)return null;
    try{
      return await listing(pid,kind);
    }catch(error){
      notice(TR('读取选型失败：')+error.message,true);
      return null;
    }
  }

  window.SelectionPage={
    enabled:enabled, KIND_OF:KIND_OF, KIND_LABEL:KIND_LABEL, KIND_PATH:KIND_PATH,
    REFRESH:REFRESH,
    setSelection:setSelection, setQuoted:setQuoted, reload:reload,
    //: 内部函数导出一份，便于冒烟与单测直接断言（正式代码只调上面几个）
    _listing:listing, _slotAt:slotAt
  };
})();
