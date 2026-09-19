'use strict';
/* 刀具类型参数库（Tool Type Library）——独立于 legacy_app.js。
 *
 * 数据源：GET /api/machining-dfm/tools（类型化 tools 表 + assets 图片元数据）；
 * 字段定义（含库分类/类型的取值与中文名）来自 GET /tools/fields 的登记表，
 * 页面表头与下拉都由它生成，前端不再各写一份分类字典。
 * 每次编辑只 PATCH 这一行的一个字段；图片二进制 PUT 上传，库里只留外键与 URL。
 * 渲染后把旧读模型 TDB 同步成同样内容，成本表/工序下拉/导出继续可用。
 */
(function(){
  const API='/api/machining-dfm';
  let rows=[],fields=[],derived=[],groups=[],categories=[],loaded=false,pending=false,notice='';
  let filterGroup='all',filterCat='';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const TR=v=>(typeof window.TR==='function')?window.TR(v):v;
  const fnum=(v,n)=>(typeof window.f==='function')?window.f(v,n):Number(v||0).toFixed(n);
  const fint=v=>(typeof window.fi==='function')?window.fi(v):String(v);

  function hostToken(){return (window.MachiningDFMHost&&window.MachiningDFMHost.token)?window.MachiningDFMHost.token('admin'):'';}
  function syncLegacy(){ // 旧页面靠全局 TDB 读刀具（成本表按名称查价）；就地同步，保持数组身份不变。
    if(!Array.isArray(window.TDB))return;
    window.TDB.length=0;
    for(let i=0;i<rows.length;i++)window.TDB.push(rows[i]);
    window.toolGrp=filterGroup;
    window.toolCat=filterCat;
  }
  function rowById(id){for(let i=0;i<rows.length;i++)if(rows[i].id===id)return rows[i];return null;}
  function fieldByKey(key){for(let i=0;i<fields.length;i++)if(fields[i].key===key)return fields[i];return null;}
  function labelOf(key){const f=fieldByKey(key);return f?(f.label+(f.unit?' '+f.unit:'')):key;}
  function groupOf(row){return row.grp||'hp';}
  function isNonCutting(group){return group==='hld'||group==='acc';}

  // 类型下拉：刀柄/配件只有国内|进口，切削刀具用刀具分类。
  function categoryOptions(nonCutting){return nonCutting?categories.filter(item=>item.group==='nc'):categories.filter(item=>item.group==='cut');}
  function categoryLabel(code,nonCutting){
    const list=categoryOptions(nonCutting);
    for(let i=0;i<list.length;i++)if(list[i].value===code)return list[i].label;
    return nonCutting?TR('国内'):TR('其他');
  }

  async function api(path,options={}){
    const init={cache:'no-store',...options};
    const headers=new Headers(init.headers||{});
    const token=hostToken();
    if(token)headers.set('Authorization','Bearer '+token);
    if(init.json!==undefined){headers.set('Content-Type','application/json');init.body=JSON.stringify(init.json);delete init.json;}
    init.headers=headers;
    const response=await fetch(API+path,init);
    if(!response.ok){
      let detail='请求失败';
      try{const body=await response.json();detail=body.detail||detail;}catch(e){}
      const error=new Error(typeof detail==='string'?detail:JSON.stringify(detail));
      error.status=response.status;error.detail=detail;
      throw error;
    }
    return response.status===204?null:response.json();
  }

  function readMeta(data){
    const spec=(data&&data.fields)||{};
    if(Array.isArray(spec.fields))fields=spec.fields;
    if(Array.isArray(spec.derived))derived=spec.derived;
    const groupField=fieldByKey('grp'),catField=fieldByKey('cat');
    if(groupField&&groupField.choices)groups=groupField.choices.slice();
    if(catField&&catField.choices){
      const cut=[],nc=[];
      for(let i=0;i<catField.choices.length;i++){
        const item=catField.choices[i];
        // 归属（cut 切削刀具 / nc 刀柄配件）由字典表给出；老响应没有 scope 时按码回退
        const nonCutting=item.scope?item.scope==='nc':(item.value==='cn'||item.value==='im');
        (nonCutting?nc:cut).push({value:item.value,label:item.label,group:nonCutting?'nc':'cut'});
      }
      // 保持 legacy 顺序：切削刀具在前，国内/进口在后
      categories=cut.concat(nc);
    }
  }
  async function load(){
    const data=await api('/tools');
    rows=data.tools||[];
    if(data.fields)readMeta({fields:data.fields});
    loaded=true;
    syncLegacy();
    return rows;
  }
  function setNotice(text,error){
    notice=text;
    const el=document.getElementById('toolsStatus');
    if(el){el.textContent=text;el.classList.toggle('error',!!error);}
  }
  // 本模块的 render() 只生成 HTML，真正换画面要交给旧的整页 render()。
  // 旧页面的增删按钮就是直接调它；漏掉这一步会让"新增/删除/换图"在界面上没反应。
  function repaint(){
    if(typeof window.render==='function'&&document.getElementById('mainPanels')){window.render();return true;}
    return false;
  }

  // ---------------- 渲染 ----------------

  function visibleIndexes(){
    const view=[];
    for(let i=0;i<rows.length;i++){
      if(filterGroup!=='all'&&groupOf(rows[i])!==filterGroup)continue;
      if(filterCat&&(rows[i].cat||'other')!==filterCat)continue;
      view.push(i);
    }
    return view;
  }
  function filterBar(view){
    let h='<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">';
    h+='<span style="font-size:11px;color:var(--s)">'+TR('库分类：')+'</span>'+
      '<select onchange="ToolsPage.setFilter(this.value,\'\')">'+
      '<option value="all"'+('all'===filterGroup?' selected':'')+'>'+TR('全部')+'</option>';
    for(let i=0;i<groups.length;i++)h+='<option value="'+esc(groups[i].value)+'"'+(groups[i].value===filterGroup?' selected':'')+'>'+esc(TR(groups[i].label))+'</option>';
    h+='</select>';
    h+='<span style="font-size:11px;color:var(--s)">'+TR('刀具类型：')+'</span>'+
      '<select onchange="ToolsPage.setFilter(\''+esc(filterGroup)+'\',this.value)">'+
      '<option value=""'+(''===filterCat?' selected':'')+'>'+TR('全部类型')+'</option>';
    const opts=categoryOptions(isNonCutting(filterGroup));
    for(let i=0;i<opts.length;i++)h+='<option value="'+esc(opts[i].value)+'"'+(opts[i].value===filterCat?' selected':'')+'>'+esc(TR(opts[i].label))+'</option>';
    h+='</select>';
    h+='<span style="font-size:11px;color:var(--s)">'+TR('共')+' '+view.length+' '+TR('项')+TR('（按录入顺序显示）')+'</span>';
    return h+'</div>';
  }
  function groupCell(row){
    let h='<td><select style="width:100px" onchange="ToolsPage.saveField(\''+row.id+'\',\'grp\',this.value)">';
    const current=groupOf(row);
    const label=groups.filter(item=>item.value===current);
    h+='<option value="'+esc(current)+'">'+esc(TR(label.length?label[0].label:current))+'</option>';
    for(let i=0;i<groups.length;i++)if(groups[i].value!==current)h+='<option value="'+esc(groups[i].value)+'">'+esc(TR(groups[i].label))+'</option>';
    return h+'</select></td>';
  }
  function categoryCell(row){
    const nc=isNonCutting(groupOf(row));
    const current=nc?((row.cat==='cn'||row.cat==='im')?row.cat:'cn'):(row.cat||'other');
    let h='<td><select style="width:82px" onchange="ToolsPage.saveField(\''+row.id+'\',\'cat\',this.value)">';
    h+='<option value="'+esc(current)+'">'+esc(categoryLabel(current,nc))+'</option>';
    const opts=categoryOptions(nc);
    for(let i=0;i<opts.length;i++)if(opts[i].value!==current)h+='<option value="'+esc(opts[i].value)+'">'+esc(TR(opts[i].label))+'</option>';
    return h+'</select></td>';
  }
  function photoCell(row){
    const photo=row.photo_url;
    return '<td style="text-align:center;min-width:70px;white-space:nowrap">'+
      (photo
        ? '<img src="'+esc(photo)+'" style="height:34px;border-radius:4px;cursor:pointer;vertical-align:middle" title="'+TR('点击后按 Ctrl+V 粘贴新图')+'" onclick="ToolsPage.view(\''+row.id+'\')">'+
          ' <a style="cursor:pointer;font-size:10px;color:var(--p)" title="'+TR('按 Ctrl+V 粘贴新图')+'" onclick="ToolsPage.paste(\''+row.id+'\')">'+TR('换图')+'</a>'+
          ' <a style="cursor:pointer;color:#e53e3e;font-size:10px" title="'+TR('删除图片')+'" onclick="ToolsPage.clearAttachment(\''+row.id+'\')">✕</a>'
        : '<a style="cursor:pointer;color:#2c5282;font-size:10px" title="'+TR('点击后按 Ctrl+V 粘贴')+'" onclick="ToolsPage.paste(\''+row.id+'\')">'+TR('粘贴')+'</a>'+
          ' <a style="cursor:pointer;color:#2c5282;font-size:10px" title="'+TR('上传图片')+'" onclick="ToolsPage.pickPhoto(\''+row.id+'\')">📁</a>')+
      '</td>';
  }
  function inputCell(row,key,width,step){
    const value=row[key];
    const shown=(key in row)&&value!==null&&value!==undefined?value:0;
    return '<td><input type="number" step="'+(step||'1')+'" min="0" value="'+esc(shown)+'" style="width:'+(width||'55px')+'"'+
      ' onchange="ToolsPage.saveField(\''+row.id+'\',\''+key+'\',this.value)"></td>';
  }
  function blankCell(){return '<td class="ro2">—</td>';}
  function fzCell(row){return '<td class="ro2">'+(Number(row.n)>0?fnum(Number(row.vf||0)/Number(row.n),3):'—')+'</td>';}
  function vcCell(row){
    return '<td class="ro2">'+((Number(row.n)>0&&Number(row.d)>0)?fint(Math.round((Math.PI*Number(row.d)*Number(row.n))/1000)):'—')+'</td>';
  }
  function actionsCell(row,index){
    const first=index===0,last=index===rows.length-1;
    return '<td style="white-space:nowrap">'+
      '<a style="cursor:pointer;font-size:11px;color:'+(first?'#cbd5e0':'#2c5282')+'" onclick="ToolsPage.move(\''+row.id+'\',-1)">▲</a>'+
      '<a style="cursor:pointer;font-size:11px;color:'+(last?'#cbd5e0':'#2c5282')+'" onclick="ToolsPage.move(\''+row.id+'\',1)">▼</a> '+
      '<button class="act" onclick="ToolsPage.remove(\''+row.id+'\')">X</button></td>';
  }

  function render(){
    if(!loaded&&Array.isArray(window.TDB)&&window.TDB.length){
      rows=window.TDB.slice();
      load().then(function(){if(document.getElementById('tabBar')&&typeof window.render==='function')window.render();})
            .catch(function(error){setNotice(TR('离线/未登录：刀具库为只读（')+error.message+'）',true);});
    }
    const hideCut=isNonCutting(filterGroup);
    const view=visibleIndexes();
    let h='<div class="panel on"><div class="card"><div class="card-hd"><h2>'+TR('刀具类型参数库 / Tool Type Library')+'</h2></div><div class="card-bd">';
    h+=filterBar(view);
    h+='<div class="tbw"><table><thead><tr><th>'+TR('库分类')+'</th><th>'+TR('型号')+'</th><th>'+TR('图片')+'</th><th>'+TR('类型')+'</th><th>'+TR('D(mm)')+'</th><th>'+TR('长度L(mm)')+'</th>';
    if(!hideCut)h+='<th>'+TR('转速n(rpm)')+'</th><th>'+TR('进给vf(mm/min)')+'</th><th>'+TR('每齿进给fz<br>(自动)')+'</th><th>'+TR('线速度Vc<br>(自动)')+'</th>';
    h+='<th>'+TR('寿命(min)')+'</th><th>'+TR('价格(¥)')+'</th><th>'+TR('操作')+'</th></tr></thead><tbody>';
    for(let k=0;k<view.length;k++){
      const row=rows[view[k]];
      const ncRow=isNonCutting(groupOf(row));
      h+='<tr>'+groupCell(row)+
        '<td><input class="txt" value="'+esc(row.tp||'')+'" style="width:110px" onchange="ToolsPage.saveField(\''+row.id+'\',\'tp\',this.value)"></td>'+
        photoCell(row)+
        categoryCell(row)+
        inputCell(row,'d','42px','0.1')+
        inputCell(row,'ln','50px','0.1')+
        (hideCut?'':(ncRow?blankCell()+blankCell()+blankCell()+blankCell()
                            :inputCell(row,'n','55px','100')+inputCell(row,'vf','60px','1')+fzCell(row)+vcCell(row)))+
        inputCell(row,'life','55px','1')+
        inputCell(row,'price','60px','0.1')+
        actionsCell(row,view[k])+'</tr>';
    }
    if(!view.length)h+='<tr><td colspan="'+(hideCut?9:13)+'" style="text-align:center;color:#718096">'+TR('没有符合条件的刀具，可在下方添加。')+'</td></tr>';
    h+='</tbody></table></div>'+
      '<div class="btn-row"><button class="btn btn-g" onclick="ToolsPage.add()">+ '+TR('添加刀具')+'</button>'+
      '<button class="btn btn-s" onclick="ToolsPage.reload()">'+TR('重新载入')+'</button>'+
      // 回收站入口（阶段 4）：服务端没开回收站或没登录时 TrashPage.button() 返回空串，按钮不出现
      (typeof TrashPage!=='undefined'?TrashPage.button('tools'):'')+
      '<span id="toolsStatus" class="note">'+esc(notice||(rows.length+' '+TR('项刀具')))+'</span></div>'+
      '<div class="note">'+TR('库分类：高压项目刀具 / 差压项目刀具 / 刀柄 / 配件。刀柄与配件类型分国内/进口两类，不设转速、进给等切削参数（自动计算列显示 —）；切削刀具按铣刀/钻头等分类。可按库分类和刀具类型筛选，按录入顺序显示。每行独立保存，图片上传到服务端磁盘。')+'</div>'+
      '</div></div></div>';
    return h;
  }

  // ---------------- 交互 ----------------

  function setFilter(group,category){
    filterGroup=group||'all';
    filterCat=category||'';
    if(filterGroup!=='all'&&filterCat){
      const opts=categoryOptions(isNonCutting(filterGroup));
      let hit=false;
      for(let i=0;i<opts.length;i++)if(opts[i].value===filterCat)hit=true;
      if(!hit)filterCat='';
    }
    syncLegacy();
    repaint();
  }
  const alive=id=>!!(id&&rowById(id));
  async function mergeRow(tool){
    if(!tool)return;
    const row=rowById(tool.id);
    if(row){for(const k in tool)row[k]=tool[k];}
    else await load();
    syncLegacy();
  }
  function normalize(row,key,value){
    const field=fieldByKey(key);
    if(field&&(field.type==='real'||field.type==='int'))row[key]=parseFloat(value)||0;
    else row[key]=value;
  }
  async function saveField(id,key,value){
    const row=rowById(id);
    if(!row)return;
    const previous=row[key];
    normalize(row,key,value);
    if(key==='grp'){ // 与旧页面一致：切到刀柄/配件时类型归到国内，切回切削刀具归到其他
      const nc=isNonCutting(String(value));
      const cat=row.cat||'other';
      if(nc&&cat!=='cn'&&cat!=='im')row.cat='cn';
      if(!nc&&(cat==='cn'||cat==='im'))row.cat='other';
    }
    const payload={[key]:key==='grp'||key==='cat'?String(value):value};
    if(key==='grp')payload.cat=row.cat;
    try{
      setNotice(TR('正在保存')+' '+labelOf(key)+'…');
      const result=await api('/tools/'+encodeURIComponent(id),{method:'PATCH',json:payload});
      await mergeRow(result.tool);
      setNotice(TR('已保存')+' '+labelOf(key)+' · '+String(value));
      if(key==='grp'||key==='cat'||key==='tp')repaint();
    }catch(error){
      setNotice(error.message,true);
      row[key]=previous;
      await load().catch(()=>{});
      repaint();
    }
  }
  async function add(){
    if(pending)return;
    pending=true;
    try{
      const g=(filterGroup==='all'?'hp':filterGroup);
      const nc=isNonCutting(g);
      const payload=nc
        ?{grp:g,tp:'新品',d:0,ln:0,n:0,vf:0,life:0,price:0,cat:'cn'}
        :{grp:g,tp:'新刀具',d:10,ln:0,n:3000,vf:800,life:0,price:0,cat:filterCat&&!isNonCutting(filterGroup)?filterCat:'other'};
      const result=await api('/tools',{method:'POST',json:payload});
      await mergeRow(result.tool);
      setNotice(TR('已新增刀具')+' · '+result.tool.tp);
      repaint();
    }catch(error){setNotice(error.message,true);}
    pending=false;
  }
  async function remove(id){
    const row=rowById(id);
    if(!row)return;
    if(!confirm(TR('确认删除刀具「')+(row.tp||'')+TR('」？')))return;
    try{
      const result=await api('/tools/'+encodeURIComponent(id),{method:'DELETE'});
      await load();
      const usage=(result&&result.usage)||[];
      setNotice(usage.length
        ?TR('已删除刀具；')+usage.length+TR(' 个项目的成本表按名称引用过它，价格将按 0 计算')
        :TR('已删除刀具'));
      repaint();
    }catch(error){setNotice(error.message,true);}
  }
  async function move(id,delta){
    const index=rows.findIndex(row=>row.id===id);
    const target=index+delta;
    if(index<0||target<0||target>=rows.length)return;
    const ids=rows.map(row=>row.id);
    ids.splice(target,0,ids.splice(index,1)[0]);
    try{
      const result=await api('/tools/reorder',{method:'POST',json:{ids}});
      rows=result.tools||rows;
      syncLegacy();
      setNotice(TR('顺序已保存'));
      repaint();
    }catch(error){setNotice(error.message,true);}
  }

  async function uploadBinary(id,blob){
    const headers={};
    if(blob.type)headers['Content-Type']=blob.type;
    setNotice(TR('正在上传图片…'));
    try{
      const result=await api('/tools/'+encodeURIComponent(id)+'/photo',{method:'PUT',body:blob,headers});
      await mergeRow(result.tool);
      setNotice(TR('刀具图片已上传'));
      repaint();
      return true;
    }catch(error){setNotice(error.message,true);await load().catch(()=>{});render();return false;}
  }
  async function uploadDataUrl(id,dataUrl){
    try{
      const blob=await (await fetch(dataUrl)).blob();
      return await uploadBinary(id,blob);
    }catch(error){setNotice(TR('图片读取失败：')+error.message,true);return false;}
  }
  function paste(id){
    if(!alive(id))return;
    if(typeof window.armPaste!=='function'){setNotice(TR('当前页面不支持粘贴上传'),true);return;}
    window.armPaste(function(dataUrl){uploadDataUrl(id,dataUrl);});
  }
  function pickPhoto(id){
    if(!alive(id))return;
    const input=document.createElement('input');
    input.type='file';input.accept='image/*';
    input.onchange=function(){
      const file=input.files&&input.files[0];
      if(!file)return;
      const reader=new FileReader();
      reader.onload=function(event){
        const shrink=(typeof window.imgShrink==='function')?window.imgShrink:function(value,cb){cb(value);};
        shrink(event.target.result,function(dataUrl){uploadDataUrl(id,dataUrl);});
      };
      reader.readAsDataURL(file);
    };
    input.click();
  }
  async function clearAttachment(id){
    if(!alive(id))return;
    if(!confirm(TR('删除这张刀具图片？')))return;
    try{
      const result=await api('/tools/'+encodeURIComponent(id)+'/photo',{method:'DELETE'});
      await mergeRow(result.tool);
      setNotice(TR('图片已删除'));
      repaint();
    }catch(error){setNotice(error.message,true);}
  }
  function view(id){
    const row=rowById(id);
    if(!row||!row.photo_url)return;
    if(typeof window.openImg==='function')window.openImg(row.photo_url);
    else window.open(row.photo_url,'_blank');
  }
  async function reload(){
    setNotice(TR('正在重新载入刀具库…'));
    try{await load();setNotice(rows.length+' '+TR('项刀具'));}catch(error){setNotice(error.message,true);}
    repaint();
  }

  window.ToolsPage={
    render,reload,load,add,remove,move,saveField,setFilter,paste,pickPhoto,clearAttachment,view,uploadDataUrl,uploadBinary,
    rows:function(){return rows;},
    toolById:function(id){return rowById(id);},
    filter:function(){return {group:filterGroup,category:filterCat};},
    syncLegacy
  };
})();
