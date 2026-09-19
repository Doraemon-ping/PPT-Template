'use strict';
// 项目信息（业务数据重构第一部分）：项目信息落在服务端 project_settings 表里，
// 一行一个项目、一个字段一列；页面上改一个格就存一个格（PATCH），每次保存都会留一个版本。
//
// 约定（与四个基础库改造一致）：
// * 本模块的 render() 只生成 HTML，动作之后要换画面必须调 repaint()；
// * 保存成功后把服务端返回的记录交给 MachiningDFMHost.adopt()，顺带刷新版本号与指纹，
//   避免下一次整份保存把已经落表的新值拿旧内存覆盖回去。
(function(){
  const API='/api/machining-dfm';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const TR=v=>(typeof window.TR==='function')?window.TR(v):v;

  // 页面字段 = 服务端字段登记表（app/machining_project.py 的 SETTINGS_FIELDS）
  const FIELDS=[
    {key:'cust',label:'客户名称',en:'Customer',type:'text',limit:120},
    {key:'part',label:'零件名称',en:'Part Name',type:'text',limit:200},
    {key:'prj',label:'项目类型',en:'Project Type',type:'select',
     options:[{value:'hp',label:'高压项目'},{value:'dp',label:'差压项目'}],
     note:'同时决定选刀时优先匹配哪一组刀具（高压项目刀具 / 差压项目刀具）'},
    {key:'custVer',label:'客户版本',en:'Customer Ver',type:'text',limit:60},
    {key:'dfmDate',label:'DFM完成时间',en:'DFM Date',type:'text',limit:40,placeholder:'2026-09-17'},
    {key:'hpd',label:'日可动时间',en:'Daily Hrs',type:'number',unit:'小时',step:0.5,min:0,max:24},
    {key:'sft',label:'日班次',en:'Shifts/Day',type:'number',step:1,min:0,max:10},
    {key:'dpm',label:'月可动日',en:'Days/Month',type:'number',step:1,min:0,max:31},
    {key:'avl',label:'可动率',en:'Availability',type:'number',unit:'%',step:1,min:0,max:200,percent:true},
    {key:'len',label:'长度 L',en:'Length',type:'number',unit:'mm',step:1,min:0},
    {key:'wid',label:'宽度 W',en:'Width',type:'number',unit:'mm',step:1,min:0},
    {key:'hgt',label:'高度 H',en:'Height',type:'number',unit:'mm',step:1,min:0},
    {key:'wgt',label:'重量',en:'Weight',type:'number',unit:'kg',step:0.1,min:0},
    {key:'showFlow',label:'流程图显示',en:'Show Flow',type:'checkbox',
     note:'关闭后导出与打印里不显示流程图'}
  ];
  const PHOTOS=[
    {slot:'product',key:'pI',label:'产品图片',en:'Product Photo'},
    {slot:'product2',key:'pf',label:'产品图片2',en:'Product Photo 2'}
  ];

  const host=()=>window.MachiningDFMHost||null;
  const general=()=>(typeof G!=='undefined'&&G)?G:{};
  function currentProject(){
    const h=host();
    if(h&&typeof h.current==='function')return h.current();
    return null;
  }
  function fieldByKey(key){
    for(let i=0;i<FIELDS.length;i++)if(FIELDS[i].key===key)return FIELDS[i];
    return null;
  }
  function setNotice(text,error){
    const el=document.getElementById('piStatus');
    if(el){el.textContent=text;el.classList.toggle('error',!!error);}
  }
  // 本模块的 render() 只负责"生成 HTML"，把画面换掉要交给旧的整页 render()
  function repaint(){
    if(typeof window.render==='function'&&document.getElementById('mainPanels')){window.render();return true;}
    return false;
  }
  function show(value){
    if(value==null)return '';
    return String(value);
  }
  function inputValue(field){
    const raw=general()[field.key];
    if(field.percent)return Number(((raw==null?0:raw))*100);
    return raw==null?field.type==='checkbox'?1:'' :raw;
  }

  function fieldHtml(field){
    const value=inputValue(field);
    let control='';
    if(field.type==='select'){
      control='<select id="pi_'+field.key+'" class="txt" onchange="ProjectInfoPage.saveField(\''+field.key+'\',this)">'+
        field.options.map(item=>'<option value="'+esc(item.value)+'"'+(String(value)===String(item.value)?' selected':'')+'>'+esc(item.label)+'</option>').join('')+
        '</select>';
    }else if(field.type==='checkbox'){
      control='<input id="pi_'+field.key+'" type="checkbox"'+(Number(value)?' checked':'')+
        ' onchange="ProjectInfoPage.saveField(\''+field.key+'\',this)">';
    }else if(field.type==='number'){
      control='<input id="pi_'+field.key+'" class="txt" type="number" value="'+esc(value)+'"'+
        (field.step!=null?' step="'+field.step+'"':'')+
        (field.min!=null?' min="'+field.min+'"':'')+
        (field.max!=null?' max="'+field.max+'"':'')+
        ' onchange="ProjectInfoPage.saveField(\''+field.key+'\',this)">'+
        (field.unit?'<span class="u">'+esc(field.unit)+'</span>':'');
    }else{
      control='<input id="pi_'+field.key+'" class="txt" value="'+esc(show(value))+'"'+
        (field.limit?' maxlength="'+field.limit+'"':'')+
        (field.placeholder?' placeholder="'+esc(field.placeholder)+'"':'')+
        ' onchange="ProjectInfoPage.saveField(\''+field.key+'\',this)">';
    }
    return '<div class="r"><span class="l">'+esc(field.label)+'<br><span class="u">'+esc(field.en||'')+'</span></span>'+
      control+'</div>'+(field.note?'<div class="muted" style="margin:-4px 0 8px 0">'+esc(field.note)+'</div>':'');
  }

  function photoHtml(photo){
    const url=general()[photo.key];
    const preview=url
      ?'<img src="'+esc(url)+'" alt="'+esc(photo.label)+'" style="max-height:120px;max-width:240px;border:1px solid #e2e8f0;border-radius:6px;cursor:zoom-in" onclick="ProjectInfoPage.view(\''+photo.slot+'\')">'
      :'<span class="muted">'+TR('未上传')+'</span>';
    return '<div class="r"><span class="l">'+esc(photo.label)+'<br><span class="u">'+esc(photo.en||'')+'</span></span>'+
      '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'+preview+
      '<button class="act" onclick="ProjectInfoPage.pickPhoto(\''+photo.slot+'\')">'+TR('选择图片')+'</button>'+
      (url?'<button class="act" onclick="ProjectInfoPage.clearPhoto(\''+photo.slot+'\')">'+TR('清除')+'</button>':'')+
      '</div></div>';
  }

  function render(){
    const project=currentProject();
    if(!project){
      return '<div class="panel on"><div class="card"><div class="card-bd">'+TR('正在载入项目信息…')+'</div></div></div>';
    }
    const basic=FIELDS.slice(0,5).map(fieldHtml).join('');
    const physics=FIELDS.slice(5,13).map(fieldHtml).join('');
    const view=FIELDS.slice(13).map(fieldHtml).join('');
    return '<div class="panel on">'+
      '<div class="card"><div class="card-hd"><h2>'+TR('项目信息')+' / Project Info</h2>'+
      '<span class="muted">'+esc(project.name||'')+' · v'+esc(project.revision)+'</span></div><div class="card-bd">'+
      '<div class="fbox" style="background:#ebf8ff;border-color:#90cdf4;color:#2a4365">'+
      TR('项目信息按字段存服务端（每个项目一行），改一个格存一个格，每次保存都会留一个版本；维护新项目时先在这里把客户、零件与产能参数填好。')+
      '</div>'+basic+
      '</div></div>'+
      '<div class="card"><div class="card-hd"><h2>'+TR('产能与零件参数')+' / Capacity &amp; Part</h2></div><div class="card-bd">'+
      '<div class="fbox" style="background:#fefcbf;border-color:#ecc94b;color:#744210">'+
      TR('以下参数用于节拍/产能计算，保存后立即生效。')+'</div>'+physics+
      '</div></div>'+
      '<div class="card"><div class="card-hd"><h2>'+TR('项目图片')+' / Project Images</h2></div><div class="card-bd">'+
      PHOTOS.map(photoHtml).join('')+
      '</div></div>'+
      '<div class="card"><div class="card-hd"><h2>'+TR('显示与状态')+'</h2></div><div class="card-bd">'+view+
      '<div class="btn-row"><button class="btn btn-g" onclick="ProjectInfoPage.reload()">'+TR('重新载入项目信息')+'</button>'+
      '<span id="piStatus" class="muted">'+TR('已同步服务端')+'</span></div>'+
      '</div></div>'+
      '</div>';
  }

  async function patch(payload){
    const h=host(),project=currentProject();
    if(!h||!project){setNotice(TR('没有打开的项目'),true);return null;}
    setNotice(TR('正在保存…'));
    try{
      const result=await h.api('/projects/'+encodeURIComponent(project.id)+'/settings',
        {method:'PATCH',json:payload});
      const record=result.project;
      if(typeof h.adopt==='function')h.adopt(record,TR('项目信息已保存')+' · v'+record.revision);
      repaint();
      return record;
    }catch(error){
      repaint();
      setNotice(TR('保存失败：')+error.message,true);
      return null;
    }
  }

  async function saveField(key,element){
    const field=fieldByKey(key);
    if(!field||!element)return null;
    let value;
    if(field.type==='checkbox')value=element.checked?1:0;
    else if(field.type==='number')value=Number(element.value||0);
    else value=element.value;
    if(field.percent)value=Number(value||0)/100;
    const payload={};
    payload[key]=value;
    const record=await patch(payload);
    if(record){
      const stored=record.state.G[key];
      element.value=field.percent?(Number(stored||0)*100):(stored==null?'':stored);
      element.classList.toggle('error',false);
      setNotice(TR(field.label)+' '+TR('已保存')+' · v'+record.revision);
      return record;
    }
    // 服务端拒绝（比如超过上限）时把输入框退回服务端的真实值
    const back=inputValue(field);
    if(field.type==='checkbox')element.checked=!!Number(back);
    else element.value=back==null?'':back;
    return null;
  }

  function view(slot){
    const photo=PHOTOS.filter(item=>item.slot===slot)[0];
    const url=photo?general()[photo.key]:null;
    if(!url)return;
    if(typeof window.openImg==='function')window.openImg(url);
    else window.open(url,'_blank');
  }

  async function uploadBlob(slot,blob){
    const h=host(),project=currentProject();
    if(!h||!project){setNotice(TR('没有打开的项目'),true);return false;}
    const headers={};
    if(blob.type)headers['Content-Type']=blob.type;
    setNotice(TR('正在上传图片…'));
    try{
      const response=await fetch(API+'/projects/'+encodeURIComponent(project.id)+'/photos/'+slot,
        {method:'PUT',cache:'no-store',headers,body:blob});
      if(!response.ok){
        let detail=TR('上传失败');
        try{detail=(await response.json()).detail||detail;}catch(e){}
        throw new Error(detail);
      }
      const result=await response.json();
      if(typeof h.adopt==='function')h.adopt(result.project,TR('项目图片已更新')+' · v'+result.project.revision);
      repaint();
      setNotice(TR('项目图片已上传')+' · v'+result.project.revision);
      return true;
    }catch(error){
      repaint();
      setNotice(TR('上传失败：')+error.message,true);
      return false;
    }
  }

  function pickPhoto(slot){
    const input=document.createElement('input');
    input.type='file';
    input.accept='image/*';
    input.onchange=function(){
      const file=input.files&&input.files[0];
      if(!file)return;
      const reader=new FileReader();
      reader.onload=function(event){
        const shrink=(typeof window.imgShrink==='function')?window.imgShrink:function(value,cb){cb(value);};
        shrink(event.target.result,function(dataUrl){
          fetch(dataUrl).then(response=>response.blob()).then(blob=>uploadBlob(slot,blob))
            .catch(error=>setNotice(TR('图片读取失败：')+error.message,true));
        });
      };
      reader.readAsDataURL(file);
    };
    input.click();
  }

  async function clearPhoto(slot){
    const h=host(),project=currentProject();
    if(!h||!project)return;
    if(!confirm(TR('删除这张项目图片？')))return;
    try{
      const result=await h.api('/projects/'+encodeURIComponent(project.id)+'/photos/'+slot,{method:'DELETE'});
      if(typeof h.adopt==='function')h.adopt(result.project,TR('项目图片已清除')+' · v'+result.project.revision);
      repaint();
      setNotice(TR('项目图片已清除')+' · v'+result.project.revision);
    }catch(error){
      repaint();
      setNotice(TR('清除失败：')+error.message,true);
    }
  }

  async function reload(){
    const h=host(),project=currentProject();
    if(!h||!project)return;
    setNotice(TR('正在重新载入…'));
    try{
      const result=await h.api('/projects/'+encodeURIComponent(project.id)+'/settings');
      const record=await h.api('/projects/'+encodeURIComponent(project.id));
      if(typeof h.adopt==='function')h.adopt(record,TR('项目信息已重新载入')+' · v'+record.revision);
      repaint();
      setNotice(Object.keys(result.settings||{}).length+TR(' 个字段已从服务端同步'));
    }catch(error){
      repaint();
      setNotice(TR('重新载入失败：')+error.message,true);
    }
  }

  window.ProjectInfoPage={render,saveField,patch,reload,pickPhoto,clearPhoto,view,repaint,fields:()=>FIELDS.slice(),photos:()=>PHOTOS.slice()};
})();
