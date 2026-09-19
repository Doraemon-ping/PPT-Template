'use strict';
/* 设备数据库（Machines）——独立于体量巨大的 legacy_app.js。
 *
 * 数据源：GET /api/machining-dfm/machines（数据库 machines 表 + assets 附件元数据）。
 * 每次编辑只提交这一行的一个字段（PATCH），不再整个库整体覆盖保存；
 * 图片/资料以二进制 PUT 上传，库里只留外键与 URL。
 * 渲染后会把旧版读模型 MDB 同步成同样内容，流程图/工序下拉/PPT 导出继续可用。
 */
(function(){
  const API='/api/machining-dfm';
  let rows=[],fields=[],fallbackId='',loaded=false,pending=false,notice='';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const TR=v=>(typeof window.TR==='function')?window.TR(v):v;

  function hostToken(){return (window.MachiningDFMHost&&window.MachiningDFMHost.token)?window.MachiningDFMHost.token('admin'):'';}
  function syncLegacy(){ // 旧页面靠全局 MDB 读取设备；这里就地同步，保持数组身份不变。
    if(!Array.isArray(window.MDB))return;
    window.MDB.length=0;
    for(let i=0;i<rows.length;i++)window.MDB.push(rows[i]);
  }
  function rowById(id){for(let i=0;i<rows.length;i++)if(rows[i].id===id)return rows[i];return null;}
  function fieldByKey(key){for(let i=0;i<fields.length;i++)if(fields[i].key===key)return fields[i];return null;}
  function labelOf(key){const f=fieldByKey(key);return f?(f.label+(f.unit?' '+f.unit:'')):key;}

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

  async function load(){
    const data=await api('/machines');
    rows=data.machines||[];
    fields=data.fields||fields;
    fallbackId=data.fallback_id||'';
    loaded=true;
    syncLegacy();
    return rows;
  }
  function setNotice(text,error){
    notice=text;
    const el=document.getElementById('machinesStatus');
    if(el){el.textContent=text;el.classList.toggle('error',!!error);}
  }
  // 本模块的 render() 只生成 HTML，真正换画面要交给旧的整页 render()。
  // 旧页面的增删按钮就是直接调它；漏掉这一步会让"新增/删除/换图"在界面上没反应。
  function repaint(){
    if(typeof window.render==='function'&&document.getElementById('mainPanels')){window.render();return true;}
    return false;
  }

  function headerCell(field){
    return '<th>'+esc(field.label+(field.unit?' '+field.unit:''))+'</th>';
  }
  function photoCell(row,index){
    const photo=row.photo_url;
    return '<td style="text-align:center;white-space:nowrap">'+
      (photo
        ? '<img class="mimg-thumb" src="'+esc(photo)+'" onclick="MachinesPage.view(\''+row.id+'\')">'+
          ' <a style="cursor:pointer;font-size:10px;color:var(--p)" title="'+TR('点击后按 Ctrl+V 粘贴新图')+'" onclick="MachinesPage.paste(\''+row.id+'\')">'+TR('换图')+'</a>'+
          ' <a style="cursor:pointer;font-size:10px;color:#e53e3e" title="'+TR('删除图片')+'" onclick="MachinesPage.clearAttachment(\''+row.id+'\',\'photo\')">✕</a>'
        : '<span class="mimg-ph" style="width:40px" title="'+TR('点击后粘贴新图')+'" onclick="MachinesPage.paste(\''+row.id+'\')">+'+TR('粘贴')+'</span>'+
          ' <a style="cursor:pointer;font-size:10px;color:#2c5282" title="'+TR('上传图片')+'" onclick="MachinesPage.pickPhoto(\''+row.id+'\')">📁</a>')+
      '</td>';
  }
  function inputCell(row,field){
    const value=row[field.key];
    const numeric=(field.type==='real'||field.type==='int');
    const step=field.type==='int'?'1':(field.key==='tc'?'0.1':(field.key==='spm'?'100':'0.1'));
    const width=field.key==='brand'?'90px':field.key==='model'?'110px':field.key==='desc'?'80px':
      (field.key==='xyz'?'90px':(field.key==='atc'?'40px':(field.key==='spm'?'55px':(field.key==='price'?'70px':(field.type==='text'?'60px':'50px')))));
    const cls=field.type==='text'?' class="txt"':'';
    const shown=numeric?Number(value||0):(value||'');
    return '<td><input'+cls+' value="'+esc(shown)+'" style="width:'+width+'"'+(numeric?' type="number" step="'+step+'" min="0"':'')+
      ' onchange="MachinesPage.saveField(\''+row.id+'\',\''+field.key+'\',this.value)"></td>';
  }
  function docCell(row){
    if(!row.doc_url)return '<td><a style="cursor:pointer;color:#2c5282;font-size:10px" onclick="MachinesPage.pickDoc(\''+row.id+'\')">'+TR('上传资料')+'</a></td>';
    const name=esc(row.doc_name||TR('资料'));
    return '<td><a href="'+esc(row.doc_url)+'" download="'+name+'" title="'+TR('下载资料')+'" style="color:#2c5282;font-size:11px">📄 '+name+'</a>'+
      ' <a style="cursor:pointer;color:#e53e3e;font-size:10px" onclick="MachinesPage.clearAttachment(\''+row.id+'\',\'doc\')">✕</a></td>';
  }
  function actionsCell(row,index){
    const first=index===0,last=index===rows.length-1;
    return '<td style="white-space:nowrap">'+
      (row.is_fallback
        ? '<span class="note" style="color:#b7791f" title="'+TR('项目未指定设备或设备被删除时使用该机型')+'">'+TR('兜底')+'</span> '
        : '<a style="cursor:pointer;color:#2c5282;font-size:10px" title="'+TR('设为兜底机型')+'" onclick="MachinesPage.setDefault(\''+row.id+'\')">'+TR('设兜底')+'</a> ')+
      '<a style="cursor:pointer;font-size:11px;color:'+(first?'#cbd5e0':'#2c5282')+'" onclick="MachinesPage.move(\''+row.id+'\',-1)">▲</a>'+
      '<a style="cursor:pointer;font-size:11px;color:'+(last?'#cbd5e0':'#2c5282')+'" onclick="MachinesPage.move(\''+row.id+'\',1)">▼</a> '+
      '<button class="act" onclick="MachinesPage.remove(\''+row.id+'\')">X</button></td>';
  }

  function render(){
    if(!loaded&&Array.isArray(window.MDB)&&window.MDB.length){
      rows=window.MDB.slice();
      const fallback=rows.filter(function(row){return row.is_fallback;});
      fallbackId=fallback.length?fallback[0].id:'';
      // 先用旧读模型立刻出画面，再向服务端取权威数据（字段表 + 兜底机型）后刷新。
      load().then(function(){if(document.getElementById('tabBar')&&typeof window.render==='function')window.render();})
            .catch(function(error){setNotice(TR('离线/未登录：设备库为只读（')+error.message+'）',true);});
    }
    const list=fields.length?fields:[{key:'brand',label:'品牌 Brand',type:'text',unit:''}];
    let h='<div class="panel on"><div class="card"><div class="card-hd"><h2>'+TR('设备数据库 / Machine DB')+'</h2></div><div class="card-bd">'+
      '<div class="note" style="margin-bottom:6px">'+TR('每一行是一台设备，字段独立存放在数据库 machines 表；图片与资料上传后保存在服务端磁盘（数据库只存元数据与链接）。修改后立即保存，无需点“保存”。')+'</div>'+
      '<div class="tbw"><table><thead><tr><th>'+TR('图片 Photo')+'</th>';
    for(let i=0;i<list.length;i++)h+=headerCell(list[i]);
    h+='<th>'+TR('上传资料')+'</th><th>'+TR('操作')+'</th></tr></thead><tbody>';
    for(let r=0;r<rows.length;r++){
      const row=rows[r];
      h+='<tr>'+photoCell(row,r);
      for(let c=0;c<list.length;c++)h+=inputCell(row,list[c]);
      h+=docCell(row)+actionsCell(row,r)+'</tr>';
    }
    if(!rows.length)h+='<tr><td colspan="'+(list.length+3)+'" style="text-align:center;color:#718096">'+TR('设备库为空，点击下方按钮添加第一台设备。')+'</td></tr>';
    h+='</tbody></table></div>'+
      '<div class="btn-row"><button class="btn btn-g" onclick="MachinesPage.add()">+ '+TR('添加设备')+'</button>'+
      '<button class="btn btn-s" onclick="MachinesPage.reload()">'+TR('重新载入')+'</button>'+
      // 回收站入口（阶段 4）：服务端没开回收站或没登录时 TrashPage.button() 返回空串，按钮不出现
      (typeof TrashPage!=='undefined'?TrashPage.button('machines'):'')+
      '<span id="machinesStatus" class="note">'+esc(notice||(rows.length+' '+TR('台设备')+(fallbackId?'':'（未设置兜底机型）')))+'</span></div>'+
      '<div class="note">'+TR('设备库为管理员维护；工艺设置人员只能选择设备。兜底机型用于工序未指定设备或原设备被删除的情况。')+'</div>'+
      '</div></div></div>';
    return h;
  }

  const alive=id=>!!(id&&rowById(id));
  async function mergeRow(machine){if(!machine)return;const row=rowById(machine.id);if(row){for(const k in machine)row[k]=machine[k];}else{await load();}syncLegacy();}

  async function saveField(id,key,value){
    const row=rowById(id);
    if(!row)return;
    const previous=row[key];
    row[key]=/^\s*-?\d+(\.\d+)?\s*$/.test(value)?Number(value):value;
    try{
      setNotice(TR('正在保存')+' '+labelOf(key)+'…');
      const result=await api('/machines/'+encodeURIComponent(id),{method:'PATCH',json:{[key]:value}});
      await mergeRow(result.machine);
      setNotice(TR('已保存')+' '+labelOf(key)+' · '+String(value));
      if(key==='brand'||key==='model')repaint();
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
      const result=await api('/machines',{method:'POST',json:{brand:'新品牌',model:'新设备',rapid:30,tc:2,spm:8000,atc:20}});
      await mergeRow(result.machine);
      setNotice(TR('已新增设备')+' · '+result.machine.brand+' '+result.machine.model);
      repaint();
    }catch(error){setNotice(error.message,true);}
    pending=false;
  }
  async function remove(id){
    const row=rowById(id);
    if(!row)return;
    if(!confirm(TR('确认删除设备「')+(row.brand||'')+' '+(row.model||'')+TR('」？')))return;
    try{
      await api('/machines/'+encodeURIComponent(id),{method:'DELETE'});
      await load();
      setNotice(TR('已删除设备'));
      repaint();
    }catch(error){
      if(error.status===409){
        const detail=error.detail;
        const names=(detail&&detail.projects)?detail.projects.map(p=>p.name+' · v'+p.revision).join('\n'):'';
        setNotice(TR('该设备已被项目引用，不能直接删除'),true);
        if(confirm(TR('该设备正被以下项目引用：')+'\n'+names+'\n\n'+TR('仍要删除吗？引用它的工序会自动改用兜底机型。'))){
          try{
            await api('/machines/'+encodeURIComponent(id)+'?force=true',{method:'DELETE'});
            await load();
            setNotice(TR('已强制删除设备，引用改为兜底机型'));
            repaint();
          }catch(forceError){setNotice(forceError.message,true);}
        }
      }else setNotice(error.message,true);
    }
  }
  async function setDefault(id){
    try{
      const result=await api('/machines/'+encodeURIComponent(id)+'/default',{method:'PUT'});
      rows=(result.machines||rows);
      fallbackId=(result.fallback_id||id);
      syncLegacy();
      setNotice(TR('已设为兜底机型'));
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
      const result=await api('/machines/reorder',{method:'POST',json:{ids}});
      rows=result.machines||rows;
      syncLegacy();
      setNotice(TR('顺序已保存'));
      repaint();
    }catch(error){setNotice(error.message,true);}
  }

  async function uploadBinary(id,kind,blob,name){
    const query=(kind==='doc'&&name)?'?name='+encodeURIComponent(name):'';
    const headers={};
    if(blob.type)headers['Content-Type']=blob.type;
    if(name)headers['X-File-Name']=encodeURIComponent(name);
    setNotice(TR('正在上传…'));
    try{
      const result=await api('/machines/'+encodeURIComponent(id)+'/'+kind+query,{method:'PUT',body:blob,headers});
      await mergeRow(result.machine);
      setNotice(kind==='photo'?TR('设备图片已上传'):TR('设备资料已上传'));
      repaint();
      return true;
    }catch(error){setNotice(error.message,true);await load().catch(()=>{});render();return false;}
  }
  async function uploadDataUrl(id,kind,dataUrl,name){
    try{
      const blob=await (await fetch(dataUrl)).blob();
      return await uploadBinary(id,kind,blob,name);
    }catch(error){setNotice(TR('图片读取失败：')+error.message,true);return false;}
  }
  function paste(id){
    if(!alive(id))return;
    if(typeof window.armPaste!=='function'){setNotice(TR('当前页面不支持粘贴上传'),true);return;}
    window.armPaste(function(dataUrl){uploadDataUrl(id,'photo',dataUrl);});
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
        shrink(event.target.result,function(dataUrl){uploadDataUrl(id,'photo',dataUrl);});
      };
      reader.readAsDataURL(file);
    };
    input.click();
  }
  function pickDoc(id){
    if(!alive(id))return;
    const input=document.createElement('input');
    input.type='file';
    input.onchange=function(){
      const file=input.files&&input.files[0];
      if(!file)return;
      const name=file.name||'资料';
      if(!/\.(pdf|docx?|xlsx?|pptx?|txt|csv|zip|rar|7z)$/i.test(name)){
        if(!confirm(TR('该文件类型可能不受支持，仍要上传吗？')))return;
      }
      uploadBinary(id,'doc',file,name);
    };
    input.click();
  }
  async function clearAttachment(id,kind){
    if(!alive(id))return;
    if(!confirm(kind==='photo'?TR('删除这张设备图片？'):TR('删除这份设备资料？')))return;
    try{
      const result=await api('/machines/'+encodeURIComponent(id)+'/'+kind,{method:'DELETE'});
      await mergeRow(result.machine);
      setNotice(kind==='photo'?TR('图片已删除'):TR('资料已删除'));
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
    setNotice(TR('正在重新载入设备库…'));
    try{await load();setNotice(rows.length+' '+TR('台设备'));}catch(error){setNotice(error.message,true);}
    repaint();
  }
  function defaultId(){
    if(fallbackId&&rowById(fallbackId))return fallbackId;
    for(let i=0;i<rows.length;i++)if(rows[i].is_fallback)return rows[i].id;
    return rows.length?rows[rows.length-1].id:'';
  }
  function machineById(id){return rowById(id);}

  window.MachinesPage={render,reload,load,add,remove,setDefault,move,saveField,paste,pickPhoto,pickDoc,clearAttachment,view,uploadDataUrl,uploadBinary,defaultId,machineById,rows:function(){return rows;},syncLegacy};
})();
