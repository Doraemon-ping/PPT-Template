'use strict';
/* 变更流水时间线（阶段 4 前端一半）——版本履历页签的下半部分，**只读**。
 *
 * 数据源：GET /projects/{pid}/changes?limit=200&entity=    （阶段 3b 就有了，页面只读不写）
 * 一条流水 = 一次行级写入里动到的一个实体：label 是人话主行，extra 是结构化明细（折行小字）。
 * 顶部一排按钮按 entity 过滤（全部/项目/项目信息/工序/工序刀具行/问题清单/选型报价/版本履历）。
 *
 * 什么时候拉：
 *   - sw() 切到「版本履历」页签时（ChangesPage.enter()）；
 *   - 点过滤按钮时；
 *   - 页签上换了一个项目时。
 * 纯 render()（自动保存/重绘）只把**已有**的行重新吐出来，不重复打接口。
 */
(function(){
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const TR=v=>(typeof window.TR==='function')?window.TR(v):v;
  const host=()=>window.MachiningDFMHost||null;

  //: 过滤按钮（值 = 后端 entity，与 machining_changes.ENTITY_LABELS 对齐）
  const FILTERS=[['','全部'],['project','项目'],['settings','项目信息'],['process','工序'],
    ['tool','工序刀具行'],['issue','问题清单'],['selection','选型报价'],['history','版本履历']];
  //: extra_json 里常见的键给一句人话
  const EXTRA_LABELS={fields:'字段',by:'操作人',reason:'原因',ids:'涉及行',slot:'格子',column:'列',
    cascade:'连带',process_id:'工序',photos:'图片',name:'项目名',revision:'版本',unchanged:'没变的'};

  let state={entity:'',rows:[],labels:{},actions:{},error:'',loading:false,
    projectId:'',loadedKey:'',pendingKey:''};

  function current(){
    const h=host();
    return (h&&typeof h.current==='function')?h.current():null;
  }
  async function request(path,options){
    const h=host();
    if(!h||typeof h.api!=='function')throw new Error(TR('页面未连接服务端'));
    return h.api(path,options||{});
  }
  function pad(value){return (value<10?'0':'')+value;}
  function stampValue(text){
    const raw=String(text||'').trim();
    if(!raw)return 0;
    const fixed=raw.replace(/\.(\d{3})\d+/,'.$1').replace(' ','T');
    let time=Date.parse(fixed);
    if(isNaN(time))time=Date.parse(raw);
    return isNaN(time)?0:time;
  }
  // created → 人话（刚刚 / N 分钟前 / 今天 HH:MM / YYYY-MM-DD HH:MM）
  function whenText(value){
    const raw=String(value||'').trim();
    if(!raw)return TR('时间未记录');
    const time=stampValue(raw);
    if(!time)return raw;
    const diff=Date.now()-time;
    if(diff>=0&&diff<60000)return TR('刚刚');
    if(diff>=60000&&diff<3600000)return Math.round(diff/60000)+TR(' 分钟前');
    if(diff>=3600000&&diff<86400000)return Math.round(diff/3600000)+TR(' 小时前');
    const date=new Date(time);
    const ymd=date.getFullYear()+'-'+pad(date.getMonth()+1)+'-'+pad(date.getDate());
    const hm=pad(date.getHours())+':'+pad(date.getMinutes());
    const today=new Date();
    if(ymd===today.getFullYear()+'-'+pad(today.getMonth()+1)+'-'+pad(today.getDate()))return TR('今天 ')+hm;
    return ymd+' '+hm;
  }
  // extra_json 的对象 → 折行小字（"字段：进给；操作人：admin"）
  function extraText(extra){
    if(!extra||typeof extra!=='object')return '';
    const parts=[];
    for(const key of Object.keys(extra)){
      const value=extra[key];
      if(value===null||value===undefined||value==='')continue;
      if(Array.isArray(value)&&!value.length)continue;
      let shown;
      if(Array.isArray(value)){
        const bits=[];
        for(let i=0;i<value.length;i++)bits.push(textOf(value[i]));
        shown=bits.join('、');
      }else shown=textOf(value);
      if(!shown)continue;
      if(shown.length>160)shown=shown.slice(0,160)+'…';
      parts.push((EXTRA_LABELS[key]||key)+'：'+shown);
    }
    return parts.join('；');
  }
  function textOf(value){
    if(value===null||value===undefined)return '';
    if(typeof value==='object'){try{return JSON.stringify(value);}catch(error){return '';}}
    return String(value);
  }
  function entityLabel(entity){
    const key=String(entity||'');
    if(!key)return TR('全部');
    return String(state.labels[key]||lookup(key)||key);
  }
  function actionLabel(action){
    const key=String(action||'');
    return String(state.actions[key]||key);
  }
  function lookup(entity){
    for(let i=0;i<FILTERS.length;i++)if(FILTERS[i][0]===entity)return FILTERS[i][1];
    return '';
  }
  // 时间倒序（新的在前）：先按 created，再按 sort_order（同一批写入里的行保持服务端顺序）
  function sorted(){
    const rows=state.rows.slice();
    rows.sort(function(a,b){
      const left=stampValue(a&&a.created),right=stampValue(b&&b.created);
      if(left!==right)return right-left;
      const ls=Number((a&&a.sort_order)||0),rs=Number((b&&b.sort_order)||0);
      if(ls!==rs)return rs-ls;
      return String((b&&b.id)||'').localeCompare(String((a&&a.id)||''));
    });
    return rows;
  }
  function itemHtml(row){
    const label=String((row&&row.label)||'').trim()||TR('（这次改动没有描述）');
    const entity=String((row&&row.entity)||'');
    const action=String((row&&row.action)||'');
    const revision=(row&&row.version_revision!==null&&row.version_revision!==undefined&&row.version_revision!=='')
      ?' · v'+row.version_revision:'';
    const extra=extraText(row&&row.extra);
    return '<div class="chg">'+
      '<div class="chg-hd"><b class="chg-label">'+esc(label)+'</b>'+
      '<span class="chg-tag">'+esc(entityLabel(entity))+(action?' · '+esc(actionLabel(action)):'')+'</span>'+
      '<span class="chg-when">'+esc(whenText(row&&row.created))+revision+'</span></div>'+
      (extra?'<div class="chg-extra">'+esc(extra)+'</div>':'')+
      '</div>';
  }
  function listHtml(){
    let h='';
    if(state.error)h+='<div class="fbox" style="background:#fff5f5;border-color:#feb2b2;color:#c53030">'+
      esc(TR('变更流水读取失败：')+state.error)+'</div>';
    if(state.loading)h+='<div class="note">'+TR('正在读取变更流水…')+'</div>';
    const rows=sorted();
    if(!rows.length){
      h+='<div class="note">'+TR('变更流水从打开开关那一刻开始记，之前的改动没有流水')+'</div>';
      if(state.entity)h+='<div class="note" style="font-size:11px">'+TR('当前筛选：')+esc(entityLabel(state.entity))+'</div>';
      return h;
    }
    h+='<div class="chg-list">';
    for(let i=0;i<rows.length;i++)h+=itemHtml(rows[i]);
    return h+'</div>';
  }
  function filterHtml(){
    let h='';
    for(let i=0;i<FILTERS.length;i++){
      const value=FILTERS[i][0];
      const on=state.entity===value;
      h+='<button class="btn '+(on?'btn-p':'btn-s')+'" data-entity="'+esc(value)+'"'+
        ' onclick="ChangesPage.filter(\''+value+'\')">'+esc(entityLabel(value))+'</button>';
    }
    return h;
  }
  // 段落外壳（bVersion() 的下半部分）：外壳里的内容来自上一次拉到的结果，不在这里打接口
  function section(){
    const project=current();
    if(!project)return '';
    if(state.projectId!==project.id){
      const previous=state.projectId;
      state.projectId=project.id;
      state.rows=[];state.error='';state.loadedKey='';state.pendingKey='';
      if(previous)schedule(project.id,keyOf(project),true);   // 换项目：自动拉一次
    }
    return '<div class="panel on"><div class="card"><div class="card-hd"><h2>'+TR('变更流水 / Change Log')+
      ' <span class="note" style="font-size:10px">'+TR('只读')+'</span></h2></div><div class="card-bd">'+
      '<div class="note">'+TR('服务端在每个行级写入点自动记一条流水（页面只读，不改也不删）；新的在前，可按实体筛选。')+'</div>'+
      '<div id="changesFilters" class="btn-row" style="margin:8px 0">'+filterHtml()+'</div>'+
      '<div id="changesTimeline">'+listHtml()+'</div>'+
      '</div></div></div>';
  }
  // 把结果就地贴回容器（只动时间线这一段，不整页重绘，避免和 render() 打架）
  function paintDom(){
    if(typeof document==='undefined'||!document.getElementById)return false;
    const filters=document.getElementById('changesFilters');
    const timeline=document.getElementById('changesTimeline');
    if(filters)filters.innerHTML=filterHtml();
    if(timeline)timeline.innerHTML=listHtml();
    return !!(filters||timeline);
  }
  function keyOf(project){
    return String((project&&project.id)||'')+'|'+String((project&&project.revision)||'')+'|'+state.entity;
  }
  function schedule(projectId,key,force){
    if(!force&&(state.pendingKey===key||state.loadedKey===key))return false;
    state.pendingKey=key;
    state.loading=true;
    setTimeout(function(){load(projectId,key).catch(function(){});},0);
    return true;
  }
  // 进入页签（sw）：无条件拉一次（项目级删除/恢复不递增版本，光看版本号会漏）
  function enter(){
    const project=current();
    if(!project)return false;
    state.projectId=project.id;
    schedule(project.id,keyOf(project),true);
    return true;
  }
  async function load(projectId,key){
    const pid=String(projectId||(current()||{}).id||'');
    if(!pid){state.loading=false;return state.rows;}
    const target=key||keyOf(current());
    const query='?limit=200'+(state.entity?'&entity='+encodeURIComponent(state.entity):'');
    try{
      const data=await request('/projects/'+encodeURIComponent(pid)+'/changes'+query);
      state.rows=(data&&data.changes)||[];
      state.labels=(data&&data.entity_labels)||{};
      state.actions=(data&&data.action_labels)||{};
      state.error='';
    }catch(error){
      state.rows=[];
      state.error=(error&&error.message)?error.message:String(error);
    }
    state.loadedKey=target;
    state.pendingKey='';
    state.loading=false;
    paintDom();
    return state.rows;
  }
  // 顶部过滤按钮
  function filter(entity){
    state.entity=String(entity||'');
    state.loadedKey='';state.pendingKey='';
    const project=current();
    if(project){
      state.projectId=project.id;
      schedule(project.id,keyOf(project),true);
    }
    paintDom();
    return state.entity;
  }
  function rows(){return sorted();}

  window.ChangesPage={
    section:section,enter:enter,filter:filter,rows:rows,reload:function(){
      state.loadedKey='';state.pendingKey='';
      const project=current();
      if(!project)return Promise.resolve([]);
      return load(project.id,keyOf(project));
    },
    //: 内部件导出，便于无头自检直接断言（正式代码只用上面几个）
    _state:function(){return state;},
    _listHtml:listHtml,_filterHtml:filterHtml,_itemHtml:itemHtml,
    _extraText:extraText,_when:whenText,_sorted:sorted,_filters:FILTERS,
  };
})();
