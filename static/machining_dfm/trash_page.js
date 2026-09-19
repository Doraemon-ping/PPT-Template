'use strict';
/* 回收站（阶段 4 前端一半）——入口 + 面板。
 *
 * 数据源（都是只读 GET，写只有"恢复"一个 POST）：
 *   GET /trash                          全局：已删除项目 + 8 张基础库/字典表的已删行
 *   GET /projects/{pid}/trash           本项目：工序/刀具行/问题/选型/履历的已删行
 * 每条带四样：deleted_at / deleted_by / deleted_reason / references（被几个项目引用）。
 *
 * 恢复（只有管理员；后端对写接口另外强制 role=admin）：
 *   基础库/字典行 → POST /trash/{table}/{id}/restore      （后端有表名白名单）
 *   项目业务行    → POST /projects/{pid}/{seg}/{id}/restore（工序/刀具行/问题/履历各自的模块接口，
 *                   这几个表不在 /trash 的白名单里，按 /trash 走会被 422 挡掉）
 *   已删除项目    → POST /projects/{id}/restore
 *   选型报价的格子没有独立恢复（清空格子不是逻辑删除），界面上不给按钮，用「历史版本」恢复。
 *
 * 优雅降级：/trash 404/403/401/网络错或 enabled=false → 入口整块隐藏，页面不报错。
 */
(function(){
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const TR=v=>(typeof window.TR==='function')?window.TR(v):v;
  const host=()=>window.MachiningDFMHost||null;

  //: 走 /trash/{table}/{id}/restore 的表（与后端 TRASH_TABLES 白名单一致）
  const LIBRARY_TABLES=['machines','tools','fixtures','gauges',
    'tool_groups','tool_categories','fixture_centers','gauge_categories'];
  //: 项目业务行：entity → 模块恢复接口里的那一段
  const ROW_SEGMENTS={process:'processes',tool:'tools',issue:'issues',history:'history'};
  //: 入口作用域（页签行用 all；四个库页面各一个，含本库自己的字典表）
  const SCOPES={
    all:{title:'回收站',tables:[]},
    machines:{title:'设备库回收站',tables:['machines']},
    tools:{title:'刀具库回收站',tables:['tools','tool_groups','tool_categories']},
    fixtures:{title:'夹具库回收站',tables:['fixtures','fixture_centers']},
    gauges:{title:'检具库回收站',tables:['gauges','gauge_categories']},
  };

  let available=false,probing=null,lastProbeAt=0,repainting=false;
  let state=fresh('all');

  function fresh(key){
    const scope=SCOPES[key]||SCOPES.all;
    return {key:key in SCOPES?key:'all',open:false,items:[],loading:false,error:'',notice:'',busy:-1,
      pid:'',tables:(scope.tables||[]).slice(),title:scope.title};
  }

  // ---------------- 基础 ----------------
  function current(){
    const h=host();
    return (h&&typeof h.current==='function')?h.current():null;
  }
  function adminToken(){
    const h=host();
    return (h&&typeof h.token==='function')?(h.token('admin')||''):'';
  }
  // 读回收站：管理员或工艺设置都能看（后端 authorize(...,'process')）
  function viewToken(){
    const h=host();
    if(!h||typeof h.token!=='function')return '';
    return h.token('admin')||h.token('process')||'';
  }
  function isAdmin(){return !!adminToken();}
  async function request(path,options){
    const h=host();
    if(!h||typeof h.api!=='function')throw new Error(TR('页面未连接服务端'));
    return h.api(path,options||{});
  }
  function repaint(){
    if(repainting)return false;
    if(typeof window.render!=='function'||!document.getElementById('mainPanels'))return false;
    repainting=true;
    try{window.render();}finally{repainting=false;}
    return true;
  }
  function pad(value){return (value<10?'0':'')+value;}
  // 服务端时间戳是 ISO（可能带 6 位小数），Date.parse 在部分浏览器上只认 3 位
  function stampValue(text){
    const raw=String(text||'').trim();
    if(!raw)return 0;
    const fixed=raw.replace(/\.(\d{3})\d+/,'.$1').replace(' ','T');
    let time=Date.parse(fixed);
    if(isNaN(time))time=Date.parse(raw);
    return isNaN(time)?0:time;
  }
  // deleted_at → 人话（刚刚 / N 分钟前 / N 小时前 / 今天 HH:MM / YYYY-MM-DD HH:MM）
  function whenText(value){
    const raw=String(value||'').trim();
    if(!raw)return TR('未记录');
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

  // ---------------- 入口可用性（优雅降级） ----------------
  // 探测失败（404/403/401/网络错/enabled=false）一律当作"这台服务没有回收站"：
  // 入口整块隐藏，且不抛异常、不留未捕获的 Promise。
  async function probe(){
    if(!viewToken()){available=false;return false;}
    if(probing)return probing;
    lastProbeAt=Date.now();
    const was=available;
    probing=(async function(){
      try{
        const data=await request('/trash',{token:viewToken()});
        available=!!(data&&data.enabled!==false);
      }catch(error){
        available=false;
      }finally{
        probing=null;
      }
      if(available&&!was)repaint();
      return available;
    })();
    return probing;
  }
  // 每次重绘都会问一次"能不能用"：没登录就不探（不做无谓请求），探过失败就 3 秒内不重复探
  function ensureProbe(){
    if(available||!viewToken())return;
    if(Date.now()-(lastProbeAt||0)<3000)return;
    probe().catch(function(){});
  }
  function availableNow(){return !!available;}
  // 退出登录：入口跟着消失（下次登录后 probe() 再放出来）
  function reset(){
    available=false;probing=null;lastProbeAt=0;
    state=fresh('all');
    const dialog=dialogNode();
    if(dialog)dialog.hidden=true;
    repaint();
  }
  // 页签行入口（项目页）：全局回收站 + 当前项目的业务行
  function tabEntry(){
    ensureProbe();
    if(!available)return '';
    return '<button class="tab db-tab trash-tab" onclick="TrashPage.open(\'all\')">'+TR('回收站')+
      '<br><span style="font-size:8px;opacity:0.6">Trash</span></button>';
  }
  // 库页面入口（四个库页面各一个）
  function button(key){
    ensureProbe();
    if(!available)return '';
    return '<button class="btn btn-s" onclick="TrashPage.open(\''+esc(key)+'\')">'+TR('回收站')+'</button>';
  }

  // ---------------- 面板 ----------------
  function dialogNode(){
    if(typeof document==='undefined'||!document.getElementById)return null;
    return document.getElementById('trashDialog');
  }
  function ensureDialog(){
    let dialog=dialogNode();
    if(dialog)return dialog;
    if(typeof document==='undefined'||!document.body||typeof document.createElement!=='function')return null;
    dialog=document.createElement('div');
    dialog.id='trashDialog';
    dialog.className='server-dialog';
    dialog.hidden=true;
    dialog.innerHTML='<div class="server-dialog-box trash-box" id="trashBox"></div>';
    dialog.onclick=function(event){if(event.target===dialog)close();};
    document.body.appendChild(dialog);
    return dialog;
  }
  function paint(){
    const dialog=ensureDialog();
    if(!dialog)return '';
    const box=document.getElementById('trashBox');
    const html=panelHtml();
    if(box)box.innerHTML=html;
    return html;
  }
  function close(){
    state.open=false;
    const dialog=dialogNode();
    if(dialog)dialog.hidden=true;
    return true;
  }
  async function open(key){
    const name=(key&&SCOPES[key])?key:'all';
    const scope=SCOPES[name];
    const project=current();
    state=fresh(name);
    state.open=true;
    state.loading=true;
    state.pid=(project&&project.id)||'';
    const dialog=ensureDialog();
    if(dialog)dialog.hidden=false;
    paint();
    await refresh();
    return state.items.length;
  }
  // 按当前作用域收行：库页面只看本库（含本库字典），页签行看全局 + 本项目
  function collect(items){
    const seen={},out=[];
    for(let i=0;i<(items||[]).length;i++){
      const item=items[i];
      if(!item)continue;
      const table=String(item.table||'');
      if(state.tables.length&&state.tables.indexOf(table)<0)continue;
      const key=table+'|'+String(item.record_id||'');
      if(seen[key])continue;
      seen[key]=1;out.push(item);
    }
    out.sort(function(a,b){
      const left=stampValue(a.deleted_at),right=stampValue(b.deleted_at);
      if(left!==right)return right-left;
      return String(b.deleted_at||'').localeCompare(String(a.deleted_at||''));
    });
    return out;
  }
  async function refresh(){
    state.loading=true;state.error='';state.notice='';
    paint();
    const items=[],problems=[];
    const token=viewToken();
    try{
      const data=await request('/trash',{token:token});
      if(data&&data.enabled===false)problems.push(TR('服务端没有打开回收站（enabled=false）'));
      else for(const item of ((data&&data.items)||[]))items.push(item);
    }catch(error){problems.push(TR('回收站读取失败：')+error.message);}
    if(state.key==='all'&&state.pid){
      try{
        const data=await request('/projects/'+encodeURIComponent(state.pid)+'/trash',{token:token});
        if(data&&data.enabled===false)problems.push(TR('本项目回收站没有打开（enabled=false）'));
        else for(const item of ((data&&data.items)||[]))items.push(item);
      }catch(error){problems.push(TR('本项目回收站读取失败：')+error.message);}
    }
    state.items=collect(items);
    state.loading=false;
    state.error=problems.join('；');
    paint();
    return state.items;
  }
  function groups(){
    const order=[],map={};
    for(let i=0;i<state.items.length;i++){
      const name=String(state.items[i].group||TR('未分组'));
      if(!map[name]){map[name]=[];order.push(name);}
      map[name].push(state.items[i]);
    }
    const out=[];
    for(let i=0;i<order.length;i++)out.push({name:order[i],items:map[order[i]]});
    return out;
  }
  // 恢复走哪条接口（''=这项没有独立恢复）
  function restorePath(item,projectId){
    if(!item)return '';
    const table=String(item.table||''),id=String(item.record_id||'');
    if(!id)return '';
    if(table==='projects')return '/projects/'+encodeURIComponent(id)+'/restore';
    if(LIBRARY_TABLES.indexOf(table)>=0)return '/trash/'+encodeURIComponent(table)+'/'+encodeURIComponent(id)+'/restore';
    const segment=ROW_SEGMENTS[String(item.entity||'')];
    const pid=String(projectId||state.pid||((current()||{}).id)||'');
    if(segment&&pid)return '/projects/'+encodeURIComponent(pid)+'/'+segment+'/'+encodeURIComponent(id)+'/restore';
    return '';
  }
  function nameOf(item){return String((item&&(item.title||item.record_id))||TR('（没有名字的行）'));}
  function rowHtml(item,index){
    const title=nameOf(item);
    const raw=String(item.deleted_at||'');
    const by=String(item.deleted_by||'').trim()||TR('未记录');
    const reason=String(item.deleted_reason||'').trim()||TR('未记录');
    const references=Number(item.references||0)||0;
    const target=restorePath(item);
    let actions;
    if(!target)actions='<span class="note" style="font-size:10px">'+TR('这项没有独立恢复（选型报价的格子请用「历史版本」恢复）')+'</span>';
    else if(isAdmin())actions='<button class="btn btn-s" style="width:auto;background:#2c5282;border-color:#2c5282;color:#fff" onclick="TrashPage.restore('+index+')">'+TR('恢复')+'</button>';
    else actions='<span class="note" style="font-size:10px">'+TR('只有管理员能恢复')+'</span>';
    if(state.busy===index)actions='<span class="note" style="font-size:10px">'+TR('正在恢复…')+'</span>';
    return '<tr>'+
      '<td><b>'+esc(title)+'</b><br><span class="note" style="font-size:10px">'+esc(TR(item.group||''))+
        ' · '+esc(String(item.entity_label||item.entity||''))+'</span></td>'+
      '<td>'+esc(by)+'</td>'+
      '<td>'+esc(reason)+'</td>'+
      '<td title="'+esc(raw)+'">'+esc(whenText(raw))+'</td>'+
      '<td>'+TR('被 ')+references+TR(' 个项目引用')+'</td>'+
      '<td style="white-space:nowrap">'+actions+'</td></tr>';
  }
  function panelHtml(){
    let h='<div class="server-dialog-head"><h2>'+esc(TR(state.title||'回收站'))+'</h2>'+
      '<div class="btn-row"><button onclick="TrashPage.reload()">'+TR('重新载入')+'</button>'+
      '<button onclick="TrashPage.close()">'+TR('关闭')+'</button></div></div>';
    h+='<div class="note">'+TR('回收站里的行只是被标记删除（永不物理删除）：基础库/字典行、已删除项目、以及本项目被删的工序/刀具行/问题/履历。恢复后原样接回原来的引用；恢复只有管理员能做。')+'</div>';
    if(state.loading)h+='<div class="note">'+TR('正在读取回收站…')+'</div>';
    if(state.error)h+='<div class="fbox" style="background:#fff5f5;border-color:#feb2b2;color:#c53030">'+esc(state.error)+'</div>';
    if(state.notice)h+='<div class="note" style="color:#2f855a">'+esc(state.notice)+'</div>';
    const list=groups();
    if(!list.length&&!state.loading&&!state.error){
      h+='<div class="note">'+TR('回收站是空的：这里只显示被逻辑删除的行。')+'</div>';
    }
    for(let g=0;g<list.length;g++){
      const group=list[g];
      h+='<div class="card" style="margin-top:8px"><div class="card-hd"><h3>'+esc(TR(group.name))+
        ' <span style="font-size:10px;color:var(--s)">'+group.items.length+' '+TR('条')+'</span></h3></div>'+
        '<div class="card-bd"><div class="tbw"><table><thead><tr>'+
        '<th>'+TR('记录')+'</th><th>'+TR('谁删的')+'</th><th>'+TR('为什么')+'</th><th>'+TR('删除时间')+'</th>'+
        '<th>'+TR('引用')+'</th><th>'+TR('操作')+'</th></tr></thead><tbody>';
      for(let i=0;i<group.items.length;i++)h+=rowHtml(group.items[i],state.items.indexOf(group.items[i]));
      h+='</tbody></table></div></div></div>';
    }
    h+='<div class="note">'+TR('共 ')+state.items.length+TR(' 条记录；「被 N 个项目引用」= 现在还有几个项目在用这一行。')+'</div>';
    return h;
  }
  async function reload(){
    await refresh();
    return state.items;
  }

  // ---------------- 恢复 ----------------
  function dropRow(item){
    state.items=state.items.filter(function(row){
      if(row===item)return false;
      return !(String(row.table||'')===String(item.table||'')
        && String(row.record_id||'')===String(item.record_id||''));
    });
  }
  // 项目业务行恢复后会回一份新的项目记录：交给 host.adopt() 接管读模型并重绘（别的项目不动）
  function adoptRecord(record,item){
    const h=host();
    if(item.table==='projects'){
      const active=current();
      if(!active||String(active.id)!==String(item.record_id||''))return false;
    }
    if(h&&typeof h.adopt==='function'){h.adopt(record,TR('已恢复')+'「'+nameOf(item)+'」');return true;}
    repaint();
    return false;
  }
  // 基础库/字典行恢复后，所属的库页面要重新载入，否则界面上还是旧的（行还"没回来"）
  function ownerOf(table){
    if(table==='machines')return 'MachinesPage';
    if(table==='tools'||table==='tool_groups'||table==='tool_categories')return 'ToolsPage';
    if(table==='fixtures'||table==='fixture_centers')return 'FixturesPage';
    if(table==='gauges'||table==='gauge_categories')return 'GaugesPage';
    return '';
  }
  async function reloadOwner(item){
    const name=ownerOf(String((item&&item.table)||''));
    const page=name?window[name]:null;
    if(page&&typeof page.reload==='function'){
      try{await page.reload();}catch(error){/* 库页面自己会把错误写在它的状态栏里 */}
    }
  }
  async function restore(index){
    const item=state.items[index|0];
    if(!item)return null;
    if(!isAdmin()){
      state.error=TR('只有管理员能恢复回收站里的行（请先用管理员身份登录）');
      state.notice='';
      paint();
      return null;
    }
    const path=restorePath(item);
    if(!path){
      state.error=TR('这一行没有独立恢复入口（选型报价的格子请用「历史版本」恢复）');
      state.notice='';
      paint();
      return null;
    }
    state.busy=index|0;state.error='';state.notice=TR('正在恢复')+'「'+nameOf(item)+'」…';
    paint();
    try{
      const result=await request(path,{method:'POST',token:adminToken()});
      if(result&&result.project)adoptRecord(result.project,item);
      dropRow(item);
      state.busy=-1;
      state.notice=TR('已恢复')+'「'+nameOf(item)+'」'+(item.table==='projects'?TR('；可在顶部项目下拉里选它'):TR('；数据按原引用接回'));
      paint();
      await reloadOwner(item);
      return item;
    }catch(error){
      state.busy=-1;
      state.error=TR('恢复失败：')+(error&&error.message?error.message:String(error));
      state.notice='';
      paint();
      return null;
    }
  }

  window.TrashPage={
    probe:probe,reset:reset,available:availableNow,ensureProbe:ensureProbe,
    tabEntry:tabEntry,button:button,
    open:open,close:close,reload:reload,refresh:refresh,restore:restore,
    isAdmin:isAdmin,
    //: 内部件导出，便于无头自检直接断言（正式代码只用上面几个）
    _state:function(){return state;},
    _items:function(){return state.items.slice();},
    _panelHtml:panelHtml,_rowHtml:rowHtml,_when:whenText,_groups:groups,
    _restorePath:restorePath,_scopes:SCOPES,
  };
})();
