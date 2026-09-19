'use strict';
// 问题清单（业务数据重构 2a）：数据已落到服务端表 project_issues，这里把旧页面上
// 「改内存 IS[i] + 整份保存」的写入点改成**行级保存**：改一个格 → PATCH 一行
// → 服务端递增项目版本并留一个版本快照 → MachiningDFMHost.adopt(record) 接管内存 → 重绘。
//
// 与外键口径对应的一处行为变化（有意为之）：
//   旧结构里 `pr` 存的是**工序名字**，工序一改名这条问题就"指向不存在"。
//   现在 `pr` 由外键 process_id 现算：下拉里选的是**工序行**（存 id），
//   名字变化自动跟随；工序被删进回收站时，读模型回退到 `prName` 名字快照。
//
// 约定与 process_page.js 相同：本模块只做「写」，画面仍由 legacy_app.js 的
// render()/bIssues() 出；每次写之前先读一次行列表拿行 id（不缓存行 id）。
(function(){
  const API='/api/machining-dfm';
  const TR=v=>(typeof window.TR==='function')?window.TR(v):v;
  const host=()=>window.MachiningDFMHost||null;

  //: 图片槽：旧键 bI/aI ↔ 行里的附件槽名
  const PHOTO_SLOTS={bI:'before',aI:'after'};
  //: 旧键 → 表里的字段键（pr 不是字段：它是外键 process_id，见 setProcess）
  const KEY_ALIAS={};

  function current(){
    const h=host();
    return (h&&typeof h.current==='function')?h.current():null;
  }
  function enabled(){
    const project=current();
    return !!(project&&project.issue_table);
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
  async function write(path,payload,method){
    const result=await call(path,{method:method||'PATCH',json:payload});
    return result.project||result;
  }
  // 读行列表（含行 id 与外键）；行 id 不缓存：DOM 下标只有对着最新列表才可靠
  async function listing(pid){
    return call('/projects/'+encodeURIComponent(pid)+'/issues');
  }
  // 用下标定位行：长度对不上说明画面已经过期，不猜、直接刷新
  function pick(data,i){
    const rows=(data&&data.issues)||[];
    if(rows.length!==Number(IS.length)){
      notice(TR('问题清单已变化，正在刷新，请再操作一次'),true);
      repaint();
      return null;
    }
    const row=rows[i|0];
    if(!row){notice(TR('找不到这条问题，请刷新后重试'),true);repaint();return null;}
    return row;
  }
  // 工序下拉框给的是**页面上的序号**（PR 的下标），这里换成工序行的 id：
  // 序号与列表都对得上才写，对不上就是不猜、刷新重来。
  function processIdAt(data,index){
    const rows=(data&&data.processes)||[];
    if(rows.length!==Number(PR.length)){
      notice(TR('工序列表已变化，正在刷新，请再操作一次'),true);
      repaint();
      return null;
    }
    const row=rows[index|0];
    if(!row){notice(TR('找不到这道工序，请刷新后重试'),true);repaint();return null;}
    return String(row.id);
  }

  // ---------------- 写入 ----------------

  // 改一个格：只提交这一个字段（行级保存）
  async function setField(i,key,value){
    const pid=projectId();
    if(!pid)return null;
    const column=KEY_ALIAS[key]||key;
    try{
      const data=await listing(pid);
      const row=pick(data,i);
      if(!row)return null;
      const payload={};
      payload[column]=value;
      const record=await write('/projects/'+encodeURIComponent(pid)+'/issues/'
        +encodeURIComponent(row.id),payload);
      adopt(record,TR('问题清单已保存')+' · v'+record.revision);
      notice(TR('问题清单已保存')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('问题清单保存失败：')+error.message,true);
      return null;
    }
  }
  // 选工序：下拉框给的是页面序号（PR 下标），这里换成工序行 id 再写外键。
  // 空串 = 不挂具体工序（项目级问题）。
  async function setProcess(i,index){
    const pid=projectId();
    if(!pid)return null;
    try{
      const data=await listing(pid);
      const row=pick(data,i);
      if(!row)return null;
      let processId=null;
      if(index!==''&&index!==null&&index!==undefined){
        processId=processIdAt(data,index);
        if(processId===null)return null;
      }
      const record=await write('/projects/'+encodeURIComponent(pid)+'/issues/'
        +encodeURIComponent(row.id),{process_id:processId});
      adopt(record,TR('问题清单已保存')+' · v'+record.revision);
      notice(TR('问题清单已保存')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('问题清单保存失败：')+error.message,true);
      return null;
    }
  }
  // 新增一条：返回新行的下标（与旧 addIssue 一样 push 到末尾）
  async function addIssue(template){
    const pid=projectId();
    if(!pid)return null;
    notice(TR('正在新增问题…'));
    try{
      const body=Object.assign({tp:TR('尺寸'),ds:'',fx:'',cr:'',st:TR('进行中')},template||{});
      const records=await call('/projects/'+encodeURIComponent(pid)+'/issues',
        {method:'POST',json:body});
      const record=records.project||records;
      adopt(record,TR('已新增一条问题')+' · v'+record.revision);
      notice(TR('已新增一条问题')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('新增问题失败：')+error.message,true);
      return null;
    }
  }
  async function removeIssue(i){
    const pid=projectId();
    if(!pid)return null;
    try{
      const data=await listing(pid);
      const row=pick(data,i);
      if(!row)return null;
      const record=await write('/projects/'+encodeURIComponent(pid)+'/issues/'
        +encodeURIComponent(row.id),{},'DELETE');
      adopt(record,TR('已删除（可在回收站恢复）')+' · v'+record.revision);
      notice(TR('已删除（可在回收站恢复）')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('删除失败：')+error.message,true);
      return null;
    }
  }
  async function restoreIssue(issueId){
    const pid=projectId();
    if(!pid||!issueId)return null;
    try{
      const record=await write('/projects/'+encodeURIComponent(pid)+'/issues/'
        +encodeURIComponent(issueId)+'/restore',{},'POST');
      adopt(record,TR('已从回收站恢复')+' · v'+record.revision);
      notice(TR('已从回收站恢复')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('恢复失败：')+error.message,true);
      return null;
    }
  }

  // ---------------- 图片（优化前 bI / 优化后 aI） ----------------

  function rest(path,blob){
    const h=host();
    if(!h)return Promise.reject(new Error(TR('页面未连接服务端')));
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
  function toBlob(value){
    if(value&&typeof value==='string'&&value.indexOf('data:')===0){
      return fetch(value).then(response=>response.blob());
    }
    return Promise.resolve(value);
  }
  async function setPhoto(i,key,value){
    const pid=projectId();
    if(!pid)return null;
    const slot=PHOTO_SLOTS[key];
    if(!slot)return null;
    notice(TR('正在保存图片…'));
    try{
      const data=await listing(pid);
      const row=pick(data,i);
      if(!row)return null;
      const base='/projects/'+encodeURIComponent(pid)+'/issues/'+encodeURIComponent(row.id)
        +'/photo/'+slot;
      let record;
      if(!value){
        record=await write(base,{},'DELETE');
      }else{
        const blob=await toBlob(value);
        const result=await rest(base,blob);
        record=result.project;
      }
      adopt(record,TR('图片已更新')+' · v'+record.revision);
      notice(TR('图片已更新')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('图片保存失败：')+error.message,true);
      return null;
    }
  }

  // 重新从服务端拉一次（表是唯一权威）
  async function reload(){
    const h=host(),project=current();
    if(!h||!project)return null;
    notice(TR('正在重新载入问题清单…'));
    try{
      const record=await h.api('/projects/'+encodeURIComponent(project.id));
      adopt(record,TR('问题清单已从服务端重新载入')+' · v'+record.revision);
      notice(TR('问题清单已从服务端重新载入')+' · v'+record.revision);
      return record;
    }catch(error){
      notice(TR('重新载入失败：')+error.message,true);
      return null;
    }
  }
  async function recycleBin(){
    const pid=projectId();
    if(!pid)return null;
    try{
      const data=await listing(pid);
      return data.deleted_issues||[];
    }catch(error){
      notice(TR('读取回收站失败：')+error.message,true);
      return null;
    }
  }

  window.IssuePage={enabled,repaint,reload,recycleBin,
    setField,setProcess,addIssue,removeIssue,restoreIssue,setPhoto,
    photoSlots:()=>({...PHOTO_SLOTS})};
})();
