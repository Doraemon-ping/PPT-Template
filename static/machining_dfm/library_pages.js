'use strict';
/* 「按类别分组」的基础库页面工厂：夹具库（模具中心）与检具库（检具类别）共用。
 *
 * 与 machines.js / tools.js 同一套约定：
 *  - 数据源是服务端类型化表（GET /fixtures、/gauges），每行有稳定 id；
 *  - 每次编辑只 PATCH 这一行的一个字段，图片二进制 PUT 上传（库里只留外键与 URL）；
 *  - 类别（模具中心 / 检具类别）来自字典表，页面新增/删除类别走字典接口，
 *    删被引用的类别要显式带 ?cascade=1（与后端 409 提示一致）；
 *  - 渲染后把旧读模型（FDB / IDB 与 G.fcnX / G.icnX）就地同步，
 *    报价选型表、成本表与导出继续可用；
 *  - 页面外观保持原来的「按类别多卡片表格」，只是数据源与保存方式换了。
 */
(function(){
  const API='/api/machining-dfm';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const TR=v=>(typeof window.TR==='function')?window.TR(v):v;
  const fnum=(v,n)=>(typeof window.f==='function')?window.f(v,n):Number(v||0).toFixed(n);

  function hostToken(){
    return (window.MachiningDFMHost&&window.MachiningDFMHost.token)?window.MachiningDFMHost.token('admin'):'';
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

  function createNamedLibraryPage(cfg){
    let rows=[],fields=[],groups=[],usage={},loaded=false,pending=false,notice='';
    const statusId=cfg.endpoint.replace(/\//g,'')+'Status';

    const rowById=id=>{for(let i=0;i<rows.length;i++)if(rows[i].id===id)return rows[i];return null;};
    const fieldByKey=key=>{for(let i=0;i<fields.length;i++)if(fields[i].key===key)return fields[i];return null;};
    const labelOf=key=>{const f=fieldByKey(key);return f?(f.label+(f.unit?' '+f.unit:'')):key;};
    const groupOf=row=>row[cfg.groupKey]||'';
    const countOf=name=>Number(usage[name]||0);
    function rowsOf(name){return rows.filter(row=>groupOf(row)===name);}

    function syncLegacy(){
      const legacy=window[cfg.legacyArray];
      if(Array.isArray(legacy)){legacy.length=0;for(let i=0;i<rows.length;i++)legacy.push(rows[i]);}
      if(window.G&&Array.isArray(groups))window.G[cfg.dictStateKey]=groups.map(item=>item.name);
    }
    function setNotice(text,error){
      notice=text;
      const el=document.getElementById(statusId);
      if(el){el.textContent=text;el.classList.toggle('error',!!error);}
    }
    // 本模块的 render() 只负责"生成 HTML"，把画面换掉要交给旧的整页 render()：
    // 旧页面的 addF/delF 就是直接调它，改造时漏了这一步会导致增删/换图"没反应"。
    function repaint(){
      if(typeof window.render==='function'&&document.getElementById('mainPanels')){window.render();return true;}
      return false;
    }
    function readMeta(data){
      const spec=(data&&data.fields)||{};
      if(spec&&Array.isArray(spec.fields))fields=spec.fields;
      const groupField=fieldByKey(cfg.groupKey);
      if(groupField&&Array.isArray(groupField.choices)){
        groups=groupField.choices.map(item=>({
          name:item.value,label:item.label,builtin:item.builtin!==false
        }));
      }
    }
    async function load(){
      const data=await api(cfg.endpoint);
      rows=data[cfg.listKey]||[];
      if(data.fields)readMeta({fields:data.fields});
      const dict=await api(cfg.dictionary);
      if(Array.isArray(dict.rows))groups=dict.rows;
      usage=(dict&&dict.usage)||{};
      loaded=true;
      syncLegacy();
      return rows;
    }

    // ---------------- 渲染 ----------------

    function photoCell(row){
      const photo=row.photo_url;
      const id=esc(row.id);
      return '<td style="text-align:center;min-width:70px;white-space:nowrap">'+
        (photo
          ? '<img src="'+esc(photo)+'" style="height:34px;border-radius:4px;cursor:pointer;vertical-align:middle" title="'+TR('点击查看大图')+'" onclick="'+cfg.global+'.view(\''+id+'\')">'+
            ' <a style="cursor:pointer;font-size:10px;color:var(--p)" title="'+TR('按 Ctrl+V 粘贴新图')+'" onclick="'+cfg.global+'.paste(\''+id+'\')">'+TR('换图')+'</a>'+
            ' <a style="cursor:pointer;color:#e53e3e;font-size:10px" title="'+TR('删除图片')+'" onclick="'+cfg.global+'.clearAttachment(\''+id+'\')">✕</a>'
          : '<a style="cursor:pointer;color:#2c5282;font-size:10px" title="'+TR('点击后按 Ctrl+V 粘贴')+'" onclick="'+cfg.global+'.paste(\''+id+'\')">'+TR('粘贴')+'</a>'+
            ' <a style="cursor:pointer;color:#2c5282;font-size:10px" title="'+TR('上传图片')+'" onclick="'+cfg.global+'.pickPhoto(\''+id+'\')">📁</a>')+
        '</td>';
    }
    function cell(row,column){
      const id=esc(row.id);
      const value=row[column.key];
      if(column.type==='text'){
        return '<td><input class="txt" value="'+esc(value??'')+'" style="width:'+(column.width||'140px')+'"'+
          ' onchange="'+cfg.global+'.saveField(\''+id+'\',\''+column.key+'\',this.value)"></td>';
      }
      const shown=(value===null||value===undefined)?0:value;
      const step=column.type==='int'?'1':'0.01';
      return '<td><input type="number" step="'+step+'" min="0" value="'+esc(shown)+'" style="width:'+(column.width||'70px')+'"'+
        ' onchange="'+cfg.global+'.saveField(\''+id+'\',\''+column.key+'\',this.value)"></td>';
    }
    function groupCard(name,index){
      const list=rowsOf(name);
      const info=groups[index]||{builtin:false};
      let h='<div class="card" style="margin-top:8px"><div class="card-hd"><h3>'+esc(TR(name))+
        ' <span style="font-size:10px;color:var(--s)">'+list.length+' '+TR('条')+(info.builtin?' · '+TR('内置类别'):'')+'</span>'+
        (info.builtin?'':' <a style="cursor:pointer;color:#e53e3e;font-size:10px" onclick="'+cfg.global+'.removeGroup(\''+esc(name)+'\')">'+TR('删除类别')+'</a>')+
        '</h3></div><div class="card-bd"><div class="tbw"><table><thead><tr><th>'+TR('图片')+'</th>';
      for(let c=0;c<cfg.columns.length;c++)h+='<th>'+TR(cfg.columns[c].label)+'</th>';
      h+='<th>'+TR('操作')+'</th></tr></thead><tbody>';
      for(let i=0;i<list.length;i++){
        const row=list[i];
        h+='<tr>'+photoCell(row);
        for(let c=0;c<cfg.columns.length;c++)h+=cell(row,cfg.columns[c]);
        h+='<td style="white-space:nowrap"><button class="act" onclick="'+cfg.global+'.remove(\''+esc(row.id)+'\')">X</button></td></tr>';
      }
      if(!list.length)h+='<tr><td colspan="'+(cfg.columns.length+2)+'" style="text-align:center;color:#718096">'+TR('该类别下暂无记录')+'</td></tr>';
      h+='</tbody></table></div>'+
        '<div class="btn-row"><button class="btn btn-g" onclick="'+cfg.global+'.add(\''+esc(name)+'\')">+ '+TR('添加')+TR(cfg.itemLabel)+'</button></div>'+
        '</div></div>';
      return h;
    }
    function render(){
      if(!loaded&&Array.isArray(window[cfg.legacyArray])&&window[cfg.legacyArray].length){
        rows=window[cfg.legacyArray].slice();
        load().then(function(){if(document.getElementById('tabBar')&&typeof window.render==='function')window.render();})
              .catch(function(error){setNotice(TR('离线/未登录：本库为只读（')+error.message+'）',true);});
      }
      if(!groups.length&&window.G&&Array.isArray(window.G[cfg.dictStateKey])){
        groups=window.G[cfg.dictStateKey].map(name=>({name:name,label:name,builtin:false}));
      }
      let h='<div class="panel on"><div class="card"><div class="card-hd"><h2>'+TR(cfg.title)+'</h2></div><div class="card-bd">';
      h+='<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">'+
        '<span style="font-size:11px;color:var(--s)">'+TR(cfg.groupLabel)+'：'+groups.length+' '+TR('个类别')+' · '+rows.length+' '+TR('条记录')+TR('（按录入顺序显示）')+'</span></div>';
      for(let i=0;i<groups.length;i++)h+=groupCard(groups[i].name,i);
      h+='<div class="btn-row"><button class="btn btn-g" onclick="'+cfg.global+'.addGroup()">+ '+TR('新增')+TR(cfg.groupLabel)+'</button>'+
        '<button class="btn btn-s" onclick="'+cfg.global+'.reload()">'+TR('重新载入')+'</button>'+
        // 回收站入口（阶段 4）：作用域名 = 本库的表名（'/fixtures' → 'fixtures'）；没登录/没开接口就不出现
        (typeof TrashPage!=='undefined'?TrashPage.button(cfg.endpoint.replace(/^\//,'')):'')+
        '<span id="'+statusId+'" class="note">'+esc(notice||(rows.length+' '+TR('条')+TR(cfg.itemLabel)))+'</span></div>'+
        '<div class="note">'+TR(cfg.note)+'</div>'+
        '</div></div></div>';
      return h;
    }

    // ---------------- 交互 ----------------

    async function mergeRow(item){
      if(!item)return;
      const row=rowById(item.id);
      if(row){for(const k in item)row[k]=item[k];}
      else await load();
      syncLegacy();
    }
    function coerce(key,value){
      const field=fieldByKey(key);
      if(field&&(field.type==='real'||field.type==='int'))return parseFloat(value)||0;
      return value;
    }
    async function saveField(id,key,value){
      const row=rowById(id);
      if(!row)return;
      const previous=row[key];
      row[key]=coerce(key,value);
      try{
        setNotice(TR('正在保存')+' '+labelOf(key)+'…');
        const result=await api(cfg.endpoint+'/'+encodeURIComponent(id),{method:'PATCH',json:{[key]:row[key]}});
        await mergeRow(result[cfg.singular]);
        setNotice(TR('已保存')+' '+labelOf(key)+' · '+String(value));
        repaint();
      }catch(error){
        setNotice(error.message,true);
        row[key]=previous;
        await load().catch(()=>{});
        repaint();
      }
    }
    async function add(group){
      if(pending)return;
      pending=true;
      try{
        const name=group||(groups[0]&&groups[0].name)||'';
        if(!name){setNotice(TR('请先新增一个')+TR(cfg.groupLabel),true);pending=false;return;}
        const payload={...cfg.defaults(name),[cfg.groupKey]:name};
        const result=await api(cfg.endpoint,{method:'POST',json:payload});
        await mergeRow(result[cfg.singular]);
        await refreshUsage();
        setNotice(TR('已新增')+TR(cfg.itemLabel));
        repaint();
      }catch(error){setNotice(error.message,true);}
      pending=false;
    }
    async function remove(id){
      const row=rowById(id);
      if(!row)return;
      if(!confirm(TR('确认删除')+TR(cfg.itemLabel)+'「'+(row[cfg.nameKey]||'')+TR('」？')))return;
      try{
        const result=await api(cfg.endpoint+'/'+encodeURIComponent(id),{method:'DELETE'});
        await load();
        const used=(result&&result.usage)||[];
        setNotice(used.length
          ?TR('已删除；')+used.length+TR(' 个项目引用过它，报价将按 0 计算')
          :TR('已删除')+TR(cfg.itemLabel));
        repaint();
      }catch(error){setNotice(error.message,true);}
    }
    async function refreshUsage(){
      const dict=await api(cfg.dictionary);
      if(Array.isArray(dict.rows))groups=dict.rows;
      usage=(dict&&dict.usage)||{};
      syncLegacy();
    }
    async function addGroup(){
      const name=prompt(TR('请输入新增')+TR(cfg.groupLabel)+TR('名称：'));
      if(name==null)return;
      const trimmed=String(name).trim();
      if(!trimmed)return;
      try{
        const result=await api(cfg.dictionary,{method:'POST',json:{name:trimmed}});
        await load();
        setNotice(TR('已新增')+TR(cfg.groupLabel)+'「'+result.row.name+'」');
        repaint();
      }catch(error){setNotice(error.message,true);}
    }
    async function removeGroup(name){
      const used=countOf(name);
      const info=groups.filter(item=>item.name===name);
      if(info.length&&info[0].builtin){setNotice(TR('内置类别不可删除，可新增自定义类别'),true);return;}
      if(used&&!confirm(TR('类别「')+name+TR('」下还有 ')+used+TR(' 条数据，确认连同数据一起删除？')))return;
      if(!used&&!confirm(TR('确认删除类别「')+name+TR('」？')))return;
      try{
        const query=used?'?cascade=1':'';
        const result=await api(cfg.dictionary+'/'+encodeURIComponent(name)+query,{method:'DELETE'});
        await load();
        setNotice(TR('已删除类别「')+name+TR('」')+(result.removed&&result.removed.removed_rows
          ?TR('，连同 ')+result.removed.removed_rows+TR(' 条数据'):''));
        repaint();
      }catch(error){setNotice(error.message,true);}
    }

    async function uploadBinary(id,blob){
      const headers={};
      if(blob.type)headers['Content-Type']=blob.type;
      setNotice(TR('正在上传图片…'));
      try{
        const result=await api(cfg.endpoint+'/'+encodeURIComponent(id)+'/photo',{method:'PUT',body:blob,headers});
        await mergeRow(result[cfg.singular]);
        setNotice(TR('图片已上传'));
        repaint();
        return true;
      }catch(error){setNotice(error.message,true);await load().catch(()=>{});repaint();return false;}
    }
    async function uploadDataUrl(id,dataUrl){
      try{
        const blob=await (await fetch(dataUrl)).blob();
        return await uploadBinary(id,blob);
      }catch(error){setNotice(TR('图片读取失败：')+error.message,true);return false;}
    }
    function paste(id){
      if(!rowById(id))return;
      if(typeof window.armPaste!=='function'){setNotice(TR('当前页面不支持粘贴上传'),true);return;}
      window.armPaste(function(dataUrl){uploadDataUrl(id,dataUrl);});
    }
    function pickPhoto(id){
      if(!rowById(id))return;
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
      if(!rowById(id))return;
      if(!confirm(TR('删除这张图片？')))return;
      try{
        const result=await api(cfg.endpoint+'/'+encodeURIComponent(id)+'/photo',{method:'DELETE'});
        await mergeRow(result[cfg.singular]);
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
      setNotice(TR('正在重新载入…'));
      try{await load();setNotice(rows.length+' '+TR('条')+TR(cfg.itemLabel));}
      catch(error){setNotice(error.message,true);}
      repaint();
    }

    return {
      render,reload,load,add,remove,addGroup,removeGroup,saveField,paste,pickPhoto,clearAttachment,view,
      uploadDataUrl,uploadBinary,
      rows:function(){return rows;},
      groups:function(){return groups.slice();},
      usage:function(){return {...usage};},
      rowById,
      countOf,
      syncLegacy
    };
  }

  window.createNamedLibraryPage=createNamedLibraryPage;
})();
