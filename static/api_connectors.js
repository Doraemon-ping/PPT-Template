(function(){
  'use strict';
  const $=selector=>document.querySelector(selector);
  const $$=selector=>Array.from(document.querySelectorAll(selector));
  const state={connections:[],endpoints:[],parameters:[],mappings:[],datasets:[],sources:[],workspaces:[],workspace:null,templates:[],connectionId:null,endpointId:null,editConnectionId:null,editEndpointId:null,editParameterId:null,lastDataset:null,advancedTab:'endpoint'};
  const wizard={step:1,inspect:null,mappings:{},customTargets:[],selectedSource:null,saving:false};
  const openapiImport={preview:null};
  let toastTimer;

  function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function toast(message,bad=false){const el=$('#toast');el.textContent=message;el.className=bad?'show bad':'show';clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.className='',3600);}
  function detailMessage(payload,status){
    const detail=payload&&payload.detail;
    if(typeof detail==='string')return detail;
    if(detail&&detail.message)return detail.message+(detail.upstream_status?'（上游 '+detail.upstream_status+'）':'');
    if(Array.isArray(detail))return detail.map(item=>item.msg||JSON.stringify(item)).join('；');
    return '请求失败（HTTP '+status+'）';
  }
  async function api(path,options={}){
    const opts={cache:'no-store',...options};
    if(opts.body&&!opts.headers&&!(opts.body instanceof FormData))opts.headers={'Content-Type':'application/json'};
    const response=await fetch(path,opts);
    if(response.status===204)return null;
    let payload=null;try{payload=await response.json();}catch(_){payload=null;}
    if(!response.ok){const error=new Error(detailMessage(payload,response.status));error.detail=payload&&payload.detail;error.status=response.status;throw error;}
    return payload;
  }
  function parseJson(id,{empty=null}={}){
    const raw=$(id).value.trim();
    if(!raw)return empty;
    try{return JSON.parse(raw);}catch(_){throw new Error($(id).previousElementSibling.textContent.replace('*','').trim()+'不是有效 JSON');}
  }
  function pretty(value){return JSON.stringify(value,null,2);}

  // 高级设置页：每个 JSON 配置项的示例，以及「填入示例 / 清空示例」按钮。
  // 示例只是可直接使用的起步模板，用户改成自己接口的值即可。
  const EXAMPLE_EMPTY={authConfig:'{}',endpointHeaders:'{}',endpointQuery:'{}',endpointBody:'',pickerEnum:'',pickerColumns:'',runtimeParameters:'{}',runtimeContext:'{}',parameterDefault:''};
  const EXAMPLES={
    authConfig:{none:{},bearer:{token_env:'DFM_API_TOKEN'},basic:{username:'report',password_env:'DFM_API_PASSWORD'},api_key:{name:'X-API-Key',key_env:'DFM_API_KEY',location:'header'}},
    endpointHeaders:{Accept:'application/json','X-Tenant':'hpm'},
    endpointQuery:{pageSize:200,include:'images'},
    endpointBody:{projectId:'',page:{size:200}},
    parameterDefault:'P-2026-001',
    pickerEnum:{'1':'严重','2':'一般','3':'轻微'},
    pickerColumns:{title:'问题标题',level:'等级',image:'问题图片'},
    runtimeParameters:{project_id:'P-2026-001'},
    runtimeContext:{tenant:'hpm',period:'2026-09'}
  };
  function exampleValue(key){
    const spec=EXAMPLES[key];
    if(spec===undefined)return undefined;
    if(key==='authConfig')return spec[$('#authType').value]??{};
    return spec;
  }
  function exampleText(key){const value=exampleValue(key);return typeof value==='string'?value:JSON.stringify(value,null,2);}
  // 认证类型为 none 等情况示例与空值相同，此时不提供「填入示例」，避免按钮点了没反应。
  function hasExample(key){return exampleText(key).trim()!==(EXAMPLE_EMPTY[key]??'').trim();}
  function syncExampleButtons(){
    $$('[data-example]').forEach(button=>{
      const key=button.dataset.example,target=$('#'+key);if(!target)return;
      if(!hasExample(key)){button.disabled=true;button.textContent='当前无需填写';button.title='当前选项留空即可';return;}
      button.disabled=false;button.title='填入一份可用示例，再改成自己的值';
      button.textContent=target.value.trim()===exampleText(key).trim()?'清空示例':'填入示例';
    });
  }
  function wireExampleButtons(){
    $$('[data-example]').forEach(button=>{
      const key=button.dataset.example,target=$('#'+key);if(!target)return;
      button.onclick=()=>{if(!hasExample(key))return;const text=exampleText(key);target.value=target.value.trim()===text.trim()?(EXAMPLE_EMPTY[key]??''):text;target.dispatchEvent(new Event('input',{bubbles:true}));syncExampleButtons();target.focus();};
      target.addEventListener('input',syncExampleButtons);
    });
    $('#authType').addEventListener('change',syncExampleButtons);
    syncExampleButtons();
  }
  function selectedConnection(){return state.connections.find(item=>item.id===state.connectionId);}
  function selectedEndpoint(){return state.endpoints.find(item=>item.id===state.endpointId);}
  function updateConfigNavigation(){
    const connection=selectedConnection(),endpoint=selectedEndpoint();
    $('#configConnectionName').textContent=connection?connection.name:'尚未选择';
    $('#configEndpointName').textContent=endpoint?endpoint.name:'尚未选择';
    $$('[data-config-tab]').forEach(button=>{
      const tab=button.dataset.configTab,needsConnection=tab!=='connection',needsEndpoint=['parameter','mapping','execute'].includes(tab);
      button.disabled=(needsConnection&&!connection)||(needsEndpoint&&!endpoint);
    });
    const requested=$('[data-config-tab="'+state.advancedTab+'"]');
    if(!requested||requested.disabled)state.advancedTab=connection?'endpoint':'connection';
    $$('[data-config-tab]').forEach(button=>{const active=button.dataset.configTab===state.advancedTab;button.classList.toggle('active',active);button.setAttribute('aria-selected',active?'true':'false');});
    $$('[data-config-panel]').forEach(panel=>panel.classList.toggle('hidden',panel.dataset.configPanel!==state.advancedTab));
  }
  function showConfigTab(tab){state.advancedTab=tab;updateConfigNavigation();}

  function renderProgress(){
    if(!$('#step1'))return;
    const done=[!!state.connectionId,!!state.endpointId,state.parameters.length>0,state.mappings.length>0,!!state.lastDataset];
    let current=done.findIndex(value=>!value);if(current<0)current=4;
    done.forEach((value,index)=>{$('#step'+(index+1)).className='step'+(value?' done':index===current?' current':'');});
  }
  function renderMetrics(){
    if($('#connectionCount'))$('#connectionCount').textContent=state.connections.length;
    if($('#endpointCount'))$('#endpointCount').textContent=state.endpoints.length;
    if($('#datasetCount'))$('#datasetCount').textContent=state.datasets.length;
    $('#sidebarCount').textContent=state.connections.length+' 项';
  }
  function renderConnections(){
    const list=$('#connectionList');
    if(!state.connections.length){list.innerHTML='<div class="empty">尚无连接。<br>从右侧第一步开始配置。</div>';}
    else list.innerHTML=state.connections.map(item=>
      '<div class="item '+(item.id===state.connectionId?'selected':'')+'">'+
      '<button class="item-pick" data-select-connection="'+item.id+'"><strong>'+escapeHtml(item.name)+'</strong><small>'+escapeHtml(item.system_name)+' · '+escapeHtml(item.base_url)+'</small></button>'+
      '<span class="item-tools"><button data-edit-connection="'+item.id+'">编辑</button><button class="danger" data-delete-connection="'+item.id+'">删除</button></span></div>'
    ).join('');
    $$('[data-select-connection]').forEach(button=>button.onclick=()=>selectConnection(Number(button.dataset.selectConnection)));
    $$('[data-edit-connection]').forEach(button=>button.onclick=()=>editConnection(Number(button.dataset.editConnection)));
    $$('[data-delete-connection]').forEach(button=>button.onclick=()=>deleteConnection(Number(button.dataset.deleteConnection)));
    const connection=selectedConnection();
    $('#selectedConnection').innerHTML=connection?'<strong>'+escapeHtml(connection.name)+'</strong> · '+escapeHtml(connection.base_url):'请先创建并选择一个 API 连接';
    $('#endpointForm button[type="submit"]').disabled=!connection;
    updateConfigNavigation();renderProgress();renderMetrics();
  }
  function renderEndpoints(){
    const selected=selectedEndpoint();
    $('#endpointRecords').innerHTML=!state.endpoints.length?'<div class="empty">当前连接尚无接口</div>':state.endpoints.map(item=>
      '<div class="record"><strong>'+escapeHtml(item.method)+' · '+escapeHtml(item.name)+(item.id===state.endpointId?' ✓':'')+' · '+(item.status==='active'?'启用':'停用')+'</strong><small>'+escapeHtml(item.path)+'</small><span class="record-actions"><button class="btn small" data-select-endpoint="'+item.id+'">选择</button><button class="btn small" data-edit-endpoint="'+item.id+'">编辑</button><button class="btn small danger" data-delete-endpoint="'+item.id+'">删除</button></span></div>'
    ).join('');
    $$('[data-select-endpoint]').forEach(button=>button.onclick=()=>selectEndpoint(Number(button.dataset.selectEndpoint)));
    $$('[data-edit-endpoint]').forEach(button=>button.onclick=()=>editEndpoint(Number(button.dataset.editEndpoint)));
    $$('[data-delete-endpoint]').forEach(button=>button.onclick=()=>deleteEndpoint(Number(button.dataset.deleteEndpoint)));
    $$('.endpoint-banner').forEach(el=>el.innerHTML=selected?'<strong>'+escapeHtml(selected.method)+' '+escapeHtml(selected.path)+'</strong> · '+escapeHtml(selected.name):'请先选择接口');
    ['#parameterForm','#executeForm'].forEach(form=>$(form).querySelector('button[type="submit"]').disabled=!selected);
    updateConfigNavigation();renderProgress();renderMetrics();
  }
  const LOCATION_LABELS={path:'路径参数',query:'查询参数',header:'请求头参数',body:'Body 参数'};
  const SOURCE_LABELS={input:'执行时传入',context:'上下文传入',fixed:'固定值'};
  function parameterSourceText(item){
    const label=SOURCE_LABELS[item.source_type]||item.source_type;
    const parts=[item.source_type==='fixed'?label:label+'（Source Key：'+escapeHtml(item.source_key||'—')+'）'];
    if(item.default_value!==null&&item.default_value!==undefined)parts.push((item.source_type==='fixed'?'默认值':'兜底值')+' '+escapeHtml(pretty(item.default_value)));
    return parts.join(' · ');
  }
  function renderParameters(){
    $('#parameterRecords').innerHTML=!state.parameters.length?'<div class="empty">还没有参数。无参数接口可以直接进入「4 字段」。</div>':state.parameters.map(item=>
      '<div class="record"><strong>'+escapeHtml(item.name)+'<span class="record-tag">'+escapeHtml(LOCATION_LABELS[item.location]||item.location)+'</span></strong><small>'+parameterSourceText(item)+'</small><span class="record-actions"><button class="btn small" data-edit-parameter="'+item.id+'">编辑</button><button class="btn small danger" data-delete-parameter="'+item.id+'">删除</button></span></div>'
    ).join('');
    $$('[data-edit-parameter]').forEach(button=>button.onclick=()=>editParameter(Number(button.dataset.editParameter)));
    $$('[data-delete-parameter]').forEach(button=>button.onclick=()=>deleteParameter(Number(button.dataset.deleteParameter)));
    renderProgress();
  }
  function editParameter(id){
    const item=state.parameters.find(value=>value.id===id);if(!item)return;
    state.editParameterId=id;
    $('#parameterName').value=item.name;$('#parameterLocation').value=item.location;$('#parameterSourceType').value=item.source_type;$('#parameterSourceKey').value=item.source_key||'';
    $('#parameterDefault').value=item.default_value===null||item.default_value===undefined?'':pretty(item.default_value);
    $('#saveParameter').textContent='更新参数';$('#cancelParameterEdit').classList.remove('hidden');
    updateParameterInputs();syncExampleButtons();showConfigTab('parameter');
  }
  function resetParameterForm(){
    state.editParameterId=null;$('#parameterForm').reset();$('#parameterSourceType').value='input';$('#parameterSourceKey').value='';$('#parameterDefault').value='';
    $('#saveParameter').textContent='添加参数';$('#cancelParameterEdit').classList.add('hidden');
    updateParameterInputs();syncExampleButtons();
  }
  function renderMappings(){
    $('#mappingRecordsHead').classList.toggle('hidden',!state.mappings.length);
    if(!state.mappings.length){$('#mappingRecords').innerHTML='<div class="empty">还没有字段映射。点上面的「读取可选参数」在左栏选字段，配置分组、类型和预览后保存。</div>';renderProgress();return;}
    const groups=new Map();
    state.mappings.forEach(item=>{
      const key=String(item.transform_config?.group||'').trim()||'未分组';
      if(!groups.has(key))groups.set(key,[]);
      groups.get(key).push(item);
    });
    $('#mappingRecords').innerHTML=Array.from(groups.entries()).map(([name,items])=>
      '<div class="record-group">'+escapeHtml(name)+'<span>'+items.length+' 条</span></div>'+items.map(item=>
        '<div class="record"><strong>'+escapeHtml(item.transform_config?.display_name||item.target_field)+' <span class="count">'+escapeHtml(item.target_field)+'</span><span class="record-tag">'+escapeHtml(mappingMethodLabel(item))+'</span></strong><small>'+escapeHtml(item.source_path)+(item.transform_config?.column_labels?' · '+Object.keys(item.transform_config.column_labels).length+' 个中文列名':'')+'</small><span class="record-actions"><button class="btn small" data-open-mapping="'+item.id+'">配置</button><button class="btn small danger" data-delete-mapping="'+item.id+'">删除</button></span></div>'
      ).join('')
    ).join('');
    $$('[data-open-mapping]').forEach(button=>button.onclick=()=>selectMappingInPicker(Number(button.dataset.openMapping)));
    $$('[data-delete-mapping]').forEach(button=>button.onclick=()=>deleteMapping(Number(button.dataset.deleteMapping)));
    renderProgress();
  }
  function mappingMethodLabel(item){
    const target=String(item.target_field||'');
    const shape=target.startsWith('tables.')?'整表':target.startsWith('images.')?'图片':'单值';
    return shape+(item.transform_type==='enum'?' · 值翻译':'');
  }

  // ---- 4 字段：左栏选参数/映射 → 右栏配置（分组 / 类型 / 预览）→ 保存 → 下一个 ----
  const PICKER_GROUPING_KEY='ppt-mapping-grouping';
  const VALUE_TYPE_LABELS={image:'图片',number:'数字',boolean:'是/否',collection:'整组记录',text:'文本'};
  const TYPE_LABELS={fields:'文字',images:'图片',tables:'表格'};
  const TYPE_PREFIX={fields:'fields.',images:'images.',tables:'tables.'};
  const picker={fields:[],config:{},grouping:'group',query:'',error:'',selected:null,selectedMappingId:null,raw:null,rawTruncated:false};
  const PICKER_HINT='还没读取。点「读取可选参数」会调用一次该接口，列出返回 JSON 里的全部字段，不会写入 Dataset。';

  function pickerRestoreGrouping(){
    try{const saved=localStorage.getItem(PICKER_GROUPING_KEY);if(['group','path','type','none'].includes(saved))picker.grouping=saved;}catch(_){}
    $('#pickerGrouping').value=picker.grouping;
  }
  function pickerRuntime(){
    const read=selector=>{try{const raw=$(selector).value.trim();return raw?JSON.parse(raw):{};}catch(_){return{};}};
    return {parameters:read('#runtimeParameters'),context:read('#runtimeContext')};
  }
  function pickerTypeOf(field){return field.value_type==='collection'?'tables':field.value_type==='image'?'images':'fields';}
  function pickerCleanName(value){
    const clean=String(value||'').split(/[.\[]/).filter(Boolean).pop()||'field';
    return clean.replace(/[^A-Za-z0-9_.-]/g,'_').replace(/^[^A-Za-z_]+/,'')||'field';
  }
  function pickerTargetName(field){return pickerCleanName(field.recommended_target||field.external_name||'field');}
  function pickerPathGroup(path){return String(path||'').replace(/^\$\.?/,'').split(/[.\[]/)[0]||'$';}
  function pickerFieldByPath(path){return picker.fields.find(field=>field.source_path===path)||null;}
  // 一组数据（[*]）取第几条：'all' = 全部按整表，数字字符串 = 只取那一条
  function pickerCollectionPath(path){const at=String(path||'').indexOf('[*]');return at<0?null:path.slice(0,at+3);}
  function pickerIndexedPath(path,index){return index&&index!=='all'&&String(path).includes('[*]')?path.replace('[*]','['+index+']'):path;}
  function pickerEffectivePath(path,config){return pickerIndexedPath(path,config?config.index:'all');}
  function pickerPathPattern(path){
    const escaped=String(path).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    return new RegExp('^'+escaped.replace(/\\\[\\\*\\\]/,'\\[\\d+\\]')+'$');
  }
  // 一条映射可能写成 [*]（整表）或 [N]（第 N+1 条），两种都算这条可选参数已配置
  function pickerMappingFor(path){
    const mappings=state.mappings||[];
    const exact=mappings.find(item=>item.source_path===path);
    if(exact)return exact;
    if(!String(path).includes('[*]'))return undefined;
    const pattern=pickerPathPattern(path);
    return mappings.find(item=>pattern.test(item.source_path));
  }
  function pickerIndexFromMapping(path,mapping){
    if(!mapping)return 'all';
    if(mapping.source_path===path)return 'all';
    const matched=/\[(\d+)\]/.exec(mapping.source_path);
    return matched?matched[1]:'all';
  }
  function pickerCollectionSize(path){
    const collection=pickerCollectionPath(path);
    if(!collection||picker.raw===null||picker.raw===undefined)return null;
    const value=resolveJsonPath(picker.raw,collection);
    return Array.isArray(value)?value.length:null;
  }
  function pickerGroupOf(field){
    if(picker.grouping==='none')return '全部参数';
    if(picker.grouping==='path')return pickerPathGroup(field.source_path);
    if(picker.grouping==='type')return VALUE_TYPE_LABELS[field.value_type]||'其他';
    return field.group||'其他';
  }
  function pickerDeriveConfig(path){
    const field=pickerFieldByPath(path),mapping=pickerMappingFor(path);
    const config={type:'fields',target:'',alias:'',group:'',enum:'',enumDefault:'',columns:'',index:'all'};
    if(field){
      config.type=pickerTypeOf(field);
      config.target=pickerTargetName(field);
      config.alias=field.display_name||field.external_name||'';
      config.group=pickerGroupOf(field);
    }else{
      config.target=pickerCleanName(path);
    }
    if(mapping){
      const target=String(mapping.target_field||'');
      config.type=target.startsWith('tables.')?'tables':target.startsWith('images.')?'images':'fields';
      config.target=target.replace(/^(tables|images|fields)\./,'')||config.target;
      config.alias=mapping.transform_config?.display_name||config.alias||config.target;
      config.group=String(mapping.transform_config?.group||'').trim()||config.group;
      const enumMap=mapping.transform_config?.mapping;
      if(enumMap&&typeof enumMap==='object')config.enum=JSON.stringify(enumMap,null,2);
      const fallback=mapping.transform_config?.default;
      if(fallback!==undefined&&fallback!==null)config.enumDefault=typeof fallback==='string'?fallback:JSON.stringify(fallback);
      const labels=mapping.transform_config?.column_labels;
      if(labels&&typeof labels==='object')config.columns=JSON.stringify(labels,null,2);
    }
    config.index=pickerIndexFromMapping(path,mapping);
    return config;
  }
  function pickerConfigFor(path){
    if(!picker.config[path])picker.config[path]=pickerDeriveConfig(path);
    return picker.config[path];
  }
  // 左栏 = 接口返回的可选参数 ∪ 已配置的字段映射（含手工写的自定义 JSONPath）
  function pickerEntries(){
    const entries=[],seen=new Set(),patterns=[];
    picker.fields.forEach(field=>{
      seen.add(field.source_path);
      if(field.source_path.includes('[*]'))patterns.push(pickerPathPattern(field.source_path));
      entries.push({path:field.source_path,field:field,mapping:pickerMappingFor(field.source_path),custom:false});
    });
    (state.mappings||[]).forEach(mapping=>{
      if(seen.has(mapping.source_path))return;
      // 已经是某条可选参数的「取第 N 条」写法（[*] → [N]），由那一项代表，不再单独列一条
      if(patterns.some(pattern=>pattern.test(mapping.source_path)))return;
      entries.push({path:mapping.source_path,field:null,mapping:mapping,custom:true});
    });
    return entries;
  }
  // 只有读取过字段目录、且这条映射不在目录里时，才算「自定义映射」。
  function pickerEntryState(entry){return entry.mapping?(entry.custom&&picker.fields.length?'custom':'done'):'todo';}
  function pickerEntryLabel(entry){
    const config=pickerConfigFor(entry.path);
    if(entry.field)return config.alias||entry.field.external_name||entry.path;
    return entry.mapping?.transform_config?.display_name||entry.mapping?.target_field||entry.path;
  }
  function pickerEntrySub(entry){
    if(entry.field){
      if(entry.mapping&&entry.mapping.source_path!==entry.path)return entry.mapping.source_path+' → '+(entry.mapping.target_field||'');
      const sample=String(entry.field.sample??'').slice(0,40);
      return entry.path+(sample?' · '+sample:'');
    }
    return entry.path+' → '+(entry.mapping?.target_field||'');
  }
  function pickerEntryGroup(entry){
    if(entry.field)return pickerGroupOf(entry.field);
    const group=String(entry.mapping?.transform_config?.group||'').trim();
    return group||'其他已配置映射';
  }
  function pickerConfiguredCount(){return picker.fields.filter(field=>pickerMappingFor(field.source_path)).length;}
  function pickerGroupNames(){
    const names=new Set();
    picker.fields.forEach(field=>names.add(pickerGroupOf(field)));
    (state.mappings||[]).forEach(item=>{const group=String(item.transform_config?.group||'').trim();if(group)names.add(group);});
    return Array.from(names).filter(Boolean);
  }
  function pickerRefreshGroupOptions(){
    $('#pickerGroupOptions').innerHTML=pickerGroupNames().map(name=>'<option value="'+escapeHtml(name)+'"></option>').join('');
  }
  function renderPicker(){
    const list=$('#pickerList'),progress=$('#pickerProgress');
    pickerRefreshGroupOptions();
    const entries=pickerEntries();
    if(picker.fields.length){progress.classList.remove('hidden');progress.textContent='已配置 '+pickerConfiguredCount()+' / '+picker.fields.length;}
    else progress.classList.add('hidden');
    if(!entries.length){
      list.innerHTML='<div class="empty">'+(picker.error?escapeHtml(picker.error):'尚未读取可选参数。')+'</div>';
      $('#pickerConfig').classList.add('hidden');
      return;
    }
    const query=picker.query.trim().toLowerCase();
    const visible=entries.filter(entry=>!query||(pickerEntryLabel(entry)+' '+entry.path).toLowerCase().includes(query));
    const groups=new Map();
    visible.forEach(entry=>{
      const key=pickerEntryGroup(entry);
      if(!groups.has(key))groups.set(key,[]);
      groups.get(key).push(entry);
    });
    const badgeText={done:'已配置',custom:'自定义',todo:'待配置'};
    list.innerHTML=Array.from(groups.entries()).map(([name,items])=>{
      const done=items.filter(entry=>entry.mapping).length;
      return '<div class="picker-group"><header><b>'+escapeHtml(name)+'</b><span>'+items.length+' 个参数'+(done?' · 已配置 '+done:'')+'</span></header>'+
        items.map(entry=>{
          const state=pickerEntryState(entry);
          return '<button class="picker-item'+(picker.selected===entry.path?' selected':'')+'" type="button" data-pick-field="'+escapeHtml(entry.path)+'">'+
            '<span><b>'+escapeHtml(pickerEntryLabel(entry))+'</b><small title="'+escapeHtml(pickerEntrySub(entry))+'">'+escapeHtml(pickerEntrySub(entry))+'</small></span>'+
            '<span class="picker-item-state '+state+'">'+badgeText[state]+'</span></button>';
        }).join('')+'</div>';
    }).join('')||'<div class="empty">没有匹配的参数，换个关键词试试。</div>';
    $$('[data-pick-field]').forEach(button=>button.onclick=()=>selectPickerField(button.dataset.pickField));
    renderPickerConfig();
  }
  function renderPickerConfig(){
    const panel=$('#pickerConfig');
    const path=picker.selected;
    if(!path){panel.classList.add('hidden');return;}
    const entry=pickerEntries().find(item=>item.path===path);
    if(!entry){panel.classList.add('hidden');return;}
    panel.classList.remove('hidden');
    const config=pickerConfigFor(path),state=pickerEntryState(entry),field=entry.field;
    $('#pickerConfigName').textContent=pickerEntryLabel(entry);
    $('#pickerConfigPath').textContent=path;
    const stateTag=$('#pickerConfigState');
    stateTag.textContent=state==='done'?'已配置':state==='custom'?'自定义映射':'待配置';
    stateTag.className='workspace-badge '+(state==='todo'?'warning':'ready');
    const source=$('#pickerSourcePath');
    const effective=pickerEffectivePath(path,config);
    if(document.activeElement!==source)source.value=effective;
    source.readOnly=!(entry.custom&&picker.fields.length);
    $('#pickerSourceHint').textContent=entry.custom&&picker.fields.length?'这条映射不在接口返回的字段目录里（手工写的 JSONPath），可以改路径，保存前会先按新路径预览。':'取值位置由接口返回决定，不用手改；要换成别的字段，直接在左栏选那一项。';
    // 接口返回的是一组数据时，允许只取其中一条（[*] → [N]）
    const indexField=$('#pickerIndexField');
    if(pickerCollectionPath(path)){
      indexField.classList.remove('hidden');
      const size=pickerCollectionSize(path);
      const current=config.index||'all';
      const options=['<option value="all">全部（整表绑定）</option>'];
      const count=size===null?12:Math.min(size,20);
      for(let i=0;i<count;i++)options.push('<option value="'+i+'">第 '+(i+1)+' 条</option>');
      $('#pickerIndex').innerHTML=options.join('');
      if(current!=='all'&&!$('#pickerIndex').querySelector('option[value="'+current+'"]')){
        $('#pickerIndex').insertAdjacentHTML('beforeend','<option value="'+current+'">第 '+(Number(current)+1)+' 条</option>');
      }
      $('#pickerIndex').value=current;
      $('#pickerIndexLabel').textContent='取第几条'+(size===null?'':'（共 '+size+' 条）');
    }else{
      config.index='all';
      indexField.classList.add('hidden');
    }
    if(document.activeElement!==$('#pickerGroup'))$('#pickerGroup').value=config.group||'';
    if(document.activeElement!==$('#pickerTarget'))$('#pickerTarget').value=config.target||'';
    if(document.activeElement!==$('#pickerAlias'))$('#pickerAlias').value=config.alias||'';
    if(document.activeElement!==$('#pickerEnum'))$('#pickerEnum').value=config.enum||'';
    if(document.activeElement!==$('#pickerEnumDefault'))$('#pickerEnumDefault').value=config.enumDefault||'';
    if(document.activeElement!==$('#pickerColumns'))$('#pickerColumns').value=config.columns||'';
    if(config.enum||config.columns)$('#pickerExtra').open=true;
    $$('[data-pick-type]').forEach(button=>button.classList.toggle('active',button.dataset.pickType===config.type));
    $('#pickerSave').textContent=entry.mapping?'保存修改并配置下一个':'保存并配置下一个';
    $('#pickerSaveStay').textContent=entry.mapping?'仅保存修改':'仅保存';
    renderPickerPreview(path,config);
  }
  function selectPickerField(path){
    if(!pickerEntries().some(entry=>entry.path===path))return;
    picker.selected=path;
    picker.selectedMappingId=pickerMappingFor(path)?.id??null;
    renderPicker();
  }
  function selectMappingInPicker(id){
    const mapping=(state.mappings||[]).find(item=>item.id===id);
    if(!mapping)return;
    showConfigTab('mapping');
    selectPickerField(mapping.source_path);
  }
  function joinUrl(base,path){
    const value=String(path||'');
    if(!base||/^(https?:|data:|\/\/)/i.test(value))return value;
    try{return new URL(value,base.replace(/\/?$/,'/')+'/').href;}catch(_){return base.replace(/\/$/,'')+'/'+value.replace(/^\//,'');}
  }
  function resolveJsonPath(payload,path){
    if(!path||path[0]!=='$')return undefined;
    let rest=path.slice(1);const tokens=[];
    while(rest.length){
      if(rest[0]==='.'){rest=rest.slice(1);const matched=/^[A-Za-z0-9_-]+/.exec(rest);if(!matched)return undefined;tokens.push({key:matched[0]});rest=rest.slice(matched[0].length);}
      else if(rest.startsWith('[*]')){tokens.push({each:true});rest=rest.slice(3);}
      else if(/^\[\d+\]/.test(rest)){const matched=/^\[(\d+)\]/.exec(rest);tokens.push({index:Number(matched[1])});rest=rest.slice(matched[0].length);}
      else if(rest.startsWith("['")){const close=rest.indexOf("']");if(close<0)return undefined;tokens.push({key:rest.slice(2,close)});rest=rest.slice(close+2);}
      else return undefined;
    }
    let values=[payload];
    for(const token of tokens){
      const next=[];
      for(const value of values){
        if(token.each){if(Array.isArray(value))next.push(...value);}
        else if(token.index!==undefined){if(Array.isArray(value)&&token.index<value.length)next.push(value[token.index]);}
        else if(value&&typeof value==='object'&&token.key in value)next.push(value[token.key]);
      }
      values=next;
      if(!values.length)return undefined;
    }
    return values.length===1?values[0]:values;
  }
  function pickerValueAt(path){
    const field=pickerFieldByPath(path);
    const sample=field?field.sample:undefined;
    if(picker.raw===null||picker.raw===undefined)return sample;
    const resolved=resolveJsonPath(picker.raw,path);
    return resolved===undefined?sample:resolved;
  }
  function cellText(value){
    if(value===undefined||value===null)return '';
    if(typeof value==='object')return JSON.stringify(value).slice(0,60);
    return String(value).slice(0,60);
  }
  function renderPickerPreview(path,config){
    const effective=pickerEffectivePath(path,config);
    $('#pickerPreviewHint').textContent='保存为 '+TYPE_PREFIX[config.type]+((config.target||'').trim()||pickerCleanName(path));
    if(config.type==='tables')$('#pickerPreview').innerHTML=previewTable(effective);
    else if(config.type==='images'){$('#pickerPreview').innerHTML=previewImage(effective);bindPreviewImageError();}
    else $('#pickerPreview').innerHTML=previewText(effective);
  }
  function previewNote(){
    return picker.rawTruncated?'<div class="preview-note">接口返回内容过大，预览只用了字段样例值。</div>':'';
  }
  function previewText(path){
    const value=pickerValueAt(path);
    if(value===undefined||value===null||value==='')return '<div class="preview-empty">当前返回里这个位置是空值。</div>'+previewNote();
    if(typeof value==='object')return '<div class="preview-value">'+escapeHtml(JSON.stringify(value,null,2).slice(0,1500))+'</div>'+previewNote();
    return '<div class="preview-value">'+escapeHtml(String(value).slice(0,1500))+'</div>'+previewNote();
  }
  function previewImage(path){
    const value=pickerValueAt(path);
    const raw=typeof value==='string'?value.trim():'';
    if(!raw){
      const objectValue=value&&typeof value==='object';
      return '<div class="preview-empty">这个位置不是单个图片地址'+(objectValue?'（当前值是列表或对象，图片类型适合只放一张图的字段，多行图片请用「表格」）':'')+'。</div>'+previewNote();
    }
    const url=joinUrl((selectedConnection()||{}).base_url,raw);
    return '<img src="'+escapeHtml(url)+'" alt="图片预览"><div class="preview-note" id="pickerPreviewNote">'+escapeHtml(url)+'</div>'+previewNote();
  }
  function bindPreviewImageError(){
    const image=$('#pickerPreview img'),note=$('#pickerPreviewNote');
    if(!image)return;
    image.onerror=()=>{image.classList.add('hidden');if(note)note.textContent='浏览器无法直接加载这张图（外部系统可能有认证或跨域限制），映射后仍会按 url_base 解析地址。';};
  }
  function previewTable(path){
    const collection=picker.raw===null||picker.raw===undefined?undefined:resolveJsonPath(picker.raw,path);
    const children=picker.fields.filter(item=>item.source_path.startsWith(path+'.')).slice(0,8);
    const rows=Array.isArray(collection)?collection.slice(0,3):(collection&&typeof collection==='object'?[collection]:[]);
    if(!children.length&&!rows.length)return '<div class="preview-empty">当前返回里这个位置没有可预览的行。</div>'+previewNote();
    const columns=children.length
      ? children.map(child=>({key:child.source_path.slice(path.length+1).replace(/^\['(.*)'\]$/,'$1'),label:child.display_name||child.external_name}))
      : Object.keys(rows[0]||{}).slice(0,8).map(key=>({key:key,label:key}));
    const head='<tr><th>#</th>'+columns.map(column=>'<th>'+escapeHtml(column.label)+'</th>').join('')+'</tr>';
    const body=rows.length
      ? rows.map((row,index)=>'<tr><td>'+(index+1)+'</td>'+columns.map(column=>'<td>'+escapeHtml(cellText(row?row[column.key]:undefined))+'</td>').join('')+'</tr>').join('')
      : '<tr><td colspan="'+(columns.length+1)+'" class="preview-empty">没有可预览的行，列名来自字段目录。</td></tr>';
    return '<table class="preview-table">'+head+body+'</table>'+previewNote();
  }
  function clearPicker(message){
    picker.fields=[];picker.config={};picker.query='';picker.error='';picker.selected=null;picker.selectedMappingId=null;picker.raw=null;picker.rawTruncated=false;
    $('#pickerSearch').value='';$('#pickerStatus').textContent=message||PICKER_HINT;
    renderPicker();
  }
  async function discoverFields(){
    if(!state.endpointId){toast('请先选择接口',true);return;}
    const button=$('#discoverFields'),original=button.textContent;
    try{
      button.disabled=true;button.textContent='正在读取…';
      $('#pickerStatus').textContent='正在调用接口读取返回字段…';
      const result=await api('/api/connectors/endpoints/'+state.endpointId+'/discover',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pickerRuntime())});
      picker.fields=result.fields||[];picker.config={};picker.selected=null;picker.selectedMappingId=null;picker.error='';
      picker.raw=result.raw===undefined?null:result.raw;picker.rawTruncated=!!result.raw_truncated;
      const mappedCount=(result.mapped_paths||[]).length;
      $('#pickerStatus').textContent='读取成功：返回 '+result.record_count+' 条记录、'+picker.fields.length+' 个可选参数'+(mappedCount?('，其中 '+mappedCount+' 个已配置'):'')+'。左栏选中一条即可配置分组、类型并预览。';
      renderPicker();
      const pending=pickerEntries().find(entry=>!entry.mapping);
      if(pending)selectPickerField(pending.path);
      toast('已读取 '+picker.fields.length+' 个可选参数');
    }catch(error){
      picker.fields=[];picker.config={};picker.selected=null;picker.selectedMappingId=null;picker.error='读取失败：'+error.message;
      $('#pickerStatus').textContent=picker.error;
      renderPicker();toast(error.message,true);
    }finally{button.disabled=false;button.textContent=original;}
  }
  function selectNextUnconfigured(afterPath){
    const entries=pickerEntries();
    const index=entries.findIndex(entry=>entry.path===afterPath);
    const ordered=entries.slice(index+1).concat(entries.slice(0,index+1));
    const next=ordered.find(entry=>!entry.mapping);
    if(!next){picker.selected=null;picker.selectedMappingId=null;renderPicker();toast('这个接口的可选参数都已配置完成');return;}
    picker.selected=next.path;picker.selectedMappingId=null;
    renderPicker();
    toast('继续配置下一个：'+pickerEntryLabel(next));
  }
  async function savePickerField(advance){
    if(!picker.selected){toast('请先在左栏选择一条参数',true);return;}
    if(!state.endpointId)return;
    const previousPath=picker.selected;
    const config=pickerConfigFor(previousPath);
    // 以界面上的值为准：程序赋值（如「填入示例」）不会触发 input，不能只信内存里的 config
    config.group=$('#pickerGroup').value;
    config.target=$('#pickerTarget').value;
    config.alias=$('#pickerAlias').value;
    config.enum=$('#pickerEnum').value;
    config.enumDefault=$('#pickerEnumDefault').value;
    config.columns=$('#pickerColumns').value;
    const sourcePath=($('#pickerSourcePath').value.trim()||previousPath);
    if(sourcePath[0]!=='$'){toast('源字段要写 JSONPath，例如 $.data.issue[0].title',true);return;}
    const target=(config.target||'').trim()||pickerCleanName(sourcePath);
    if(!/^[A-Za-z_][A-Za-z0-9_.-]*$/.test(target)){toast('目标字段名只能包含字母、数字、下划线、点，并以字母或下划线开头',true);return;}
    const mapping=(state.mappings||[]).find(item=>item.id===picker.selectedMappingId)||pickerMappingFor(previousPath);
    const type=config.type||'fields';
    const transformConfig=Object.assign({},mapping?mapping.transform_config||{}:{});
    transformConfig.display_name=config.alias||mapping?.transform_config?.display_name||pickerCleanName(sourcePath);
    const group=(config.group||'').trim();
    if(group)transformConfig.group=group;else delete transformConfig.group;
    if(type==='images')transformConfig.url_base=(selectedConnection()||{}).base_url||transformConfig.url_base;
    else delete transformConfig.url_base;
    // 「更多设置」：值翻译（enum）与表格列名，解析失败就不保存，避免写坏配置
    let transformType=mapping?mapping.transform_type||'none':'none';
    const enumRaw=(config.enum||'').trim(),columnsRaw=(config.columns||'').trim();
    if(enumRaw){
      let parsed;try{parsed=JSON.parse(enumRaw);}catch(_){toast('值翻译要填合法 JSON，例如 {"1":"严重","2":"一般"}',true);return;}
      if(!parsed||typeof parsed!=='object'||Array.isArray(parsed)){toast('值翻译要填对象，例如 {"1":"严重","2":"一般"}',true);return;}
      transformConfig.mapping=parsed;
      const fallback=(config.enumDefault||'').trim();
      if(fallback)transformConfig.default=fallback;else delete transformConfig.default;
      transformType='enum';
    }else{
      delete transformConfig.mapping;delete transformConfig.default;
      if(transformType==='enum')transformType='none';
    }
    if(columnsRaw){
      let parsed;try{parsed=JSON.parse(columnsRaw);}catch(_){toast('表格列名要填合法 JSON，例如 {"title":"问题标题"}',true);return;}
      if(!parsed||typeof parsed!=='object'||Array.isArray(parsed)){toast('表格列名要填对象，例如 {"title":"问题标题"}',true);return;}
      transformConfig.column_labels=parsed;
    }else delete transformConfig.column_labels;
    const payload={endpoint_id:state.endpointId,source_path:sourcePath,target_field:TYPE_PREFIX[type]+target,transform_type:transformType,transform_config:transformConfig};
    const button=advance?$('#pickerSave'):$('#pickerSaveStay'),original=button.textContent;
    try{
      button.disabled=true;button.textContent='保存中…';
      await api('/api/connectors/mappings'+(mapping?'/'+mapping.id:''),{method:mapping?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      delete picker.config[previousPath];
      delete picker.config[sourcePath];
      await loadEndpointDetail();
      toast((mapping?'已更新：':'已保存：')+(transformConfig.display_name||target));
      picker.selected=null;picker.selectedMappingId=null;
      renderPicker();
      if(advance)selectNextUnconfigured(mapping?sourcePath:previousPath);
    }catch(error){toast(error.message,true);}
    finally{button.disabled=false;button.textContent=original;}
  }
  $('#discoverFields').onclick=discoverFields;
  $('#pickerSave').onclick=()=>savePickerField(true);
  $('#pickerSaveStay').onclick=()=>savePickerField(false);
  $('#pickerCancel').onclick=()=>{picker.selected=null;picker.selectedMappingId=null;renderPicker();};
  $('#pickerGrouping').addEventListener('change',()=>{
    picker.grouping=$('#pickerGrouping').value;
    try{localStorage.setItem(PICKER_GROUPING_KEY,picker.grouping);}catch(_){}
    renderPicker();
  });
  $('#pickerSearch').addEventListener('input',()=>{picker.query=$('#pickerSearch').value;renderPicker();});
  $$('[data-pick-type]').forEach(button=>button.onclick=()=>{
    if(!picker.selected)return;
    const config=pickerConfigFor(picker.selected);config.type=button.dataset.pickType;
    $$('[data-pick-type]').forEach(item=>item.classList.toggle('active',item===button));
    renderPickerPreview(picker.selected,config);
  });
  $('#pickerSourcePath').addEventListener('input',()=>{
    if(!picker.selected)return;
    renderPickerPreview($('#pickerSourcePath').value.trim()||picker.selected,pickerConfigFor(picker.selected));
  });
  $('#pickerIndex').addEventListener('change',()=>{
    if(!picker.selected)return;
    const config=pickerConfigFor(picker.selected);
    config.index=$('#pickerIndex').value;
    const field=pickerFieldByPath(picker.selected);
    // 取单条时类型跟着从「表格」切到「文字 / 图片」，取全部时切回「表格」
    if(config.index==='all')config.type='tables';
    else if(config.type==='tables')config.type=field&&field.value_type==='image'?'images':'fields';
    renderPickerConfig();
  });
  $('#pickerGroup').addEventListener('input',()=>{if(!picker.selected)return;pickerConfigFor(picker.selected).group=$('#pickerGroup').value;});
  $('#pickerTarget').addEventListener('input',()=>{
    if(!picker.selected)return;
    const config=pickerConfigFor(picker.selected);config.target=$('#pickerTarget').value;
    $('#pickerPreviewHint').textContent='保存为 '+TYPE_PREFIX[config.type]+(config.target.trim()||pickerCleanName(picker.selected));
  });
  $('#pickerAlias').addEventListener('input',()=>{
    if(!picker.selected)return;
    const config=pickerConfigFor(picker.selected);config.alias=$('#pickerAlias').value;
    $('#pickerConfigName').textContent=config.alias||picker.selected;
  });
  $('#pickerEnum').addEventListener('input',()=>{if(picker.selected)pickerConfigFor(picker.selected).enum=$('#pickerEnum').value;});
  $('#pickerEnumDefault').addEventListener('input',()=>{if(picker.selected)pickerConfigFor(picker.selected).enumDefault=$('#pickerEnumDefault').value;});
  $('#pickerColumns').addEventListener('input',()=>{if(picker.selected)pickerConfigFor(picker.selected).columns=$('#pickerColumns').value;});
  function renderDatasets(){
    $('#datasetList').innerHTML=!state.datasets.length?'':('<div class="section-title"><h3>最近生成</h3><span class="count">最多显示 5 项</span></div>'+state.datasets.slice(0,5).map(item=>
      '<button class="dataset" data-dataset="'+escapeHtml(item.id)+'"><strong>'+escapeHtml(item.source)+'</strong><code>'+escapeHtml(item.id)+'</code><time>'+escapeHtml(new Date(item.created_at).toLocaleString())+'</time></button>'
    ).join(''));
    $$('[data-dataset]').forEach(button=>button.onclick=async()=>{try{const data=await api('/api/connectors/datasets/'+encodeURIComponent(button.dataset.dataset));$('#resultView').textContent=pretty(data);}catch(error){toast(error.message,true);}});
    renderMetrics();
  }

  async function refreshDatasets(){const result=await api('/api/connectors/datasets?limit=20');state.datasets=result.items;renderDatasets();}
  async function refreshConnections(preferredId){
    const result=await api('/api/connectors/connections');state.connections=result.items;
    if(preferredId&&state.connections.some(item=>item.id===preferredId))state.connectionId=preferredId;
    else if(!state.connections.some(item=>item.id===state.connectionId))state.connectionId=state.connections[0]?.id??null;
    renderConnections();await loadEndpoints();
  }
  async function loadEndpoints(preferredId){
    if(!state.connectionId){state.endpoints=[];state.endpointId=null;state.parameters=[];state.mappings=[];renderEndpoints();renderParameters();renderMappings();return;}
    const result=await api('/api/connectors/endpoints?connection_id='+state.connectionId);state.endpoints=result.items.slice().sort((a,b)=>(a.status==='active'?0:1)-(b.status==='active'?0:1)||a.id-b.id);
    if(preferredId&&state.endpoints.some(item=>item.id===preferredId))state.endpointId=preferredId;
    else if(!state.endpoints.some(item=>item.id===state.endpointId&&item.status==='active'))state.endpointId=state.endpoints.find(item=>item.status==='active')?.id??state.endpoints[0]?.id??null;
    renderEndpoints();await loadEndpointDetail();
  }
  async function loadEndpointDetail(){
    if(!state.endpointId){state.parameters=[];state.mappings=[];renderParameters();renderMappings();return;}
    const detail=await api('/api/connectors/endpoints/'+state.endpointId);state.parameters=detail.parameters;state.mappings=detail.mappings;renderParameters();renderMappings();renderPicker();
  }
  async function selectConnection(id){state.connectionId=id;state.endpointId=null;state.lastDataset=null;state.advancedTab='endpoint';resetParameterForm();clearPicker();renderConnections();await loadEndpoints();}
  async function selectEndpoint(id){state.endpointId=id;state.lastDataset=null;resetParameterForm();clearPicker();renderEndpoints();await loadEndpointDetail();}

  function editConnection(id){
    const item=state.connections.find(value=>value.id===id);if(!item)return;
    state.editConnectionId=id;$('#connectionName').value=item.name;$('#systemName').value=item.system_name;$('#baseUrl').value=item.base_url;$('#authType').value=item.auth_type;$('#timeout').value=item.timeout;$('#authConfig').value=pretty(item.auth_config);$('#saveConnection').textContent='更新连接';$('#cancelConnectionEdit').classList.remove('hidden');showConfigTab('connection');syncExampleButtons();
  }
  function resetConnectionForm(){state.editConnectionId=null;$('#connectionForm').reset();$('#timeout').value='30';$('#authConfig').value='{}';$('#saveConnection').textContent='保存连接';$('#cancelConnectionEdit').classList.add('hidden');syncExampleButtons();}
  async function deleteConnection(id){
    const item=state.connections.find(value=>value.id===id);if(!item||!confirm('删除连接「'+item.name+'」及其接口、参数和映射？'))return;
    try{await api('/api/connectors/connections/'+id,{method:'DELETE'});if(state.connectionId===id){state.connectionId=null;state.endpointId=null;}await Promise.all([refreshConnections(),state.workspace?refreshWorkspaces(state.workspace.id):Promise.resolve()]);toast('连接已删除');}catch(error){toast(error.message,true);}
  }
  function editEndpoint(id){
    const item=state.endpoints.find(value=>value.id===id);if(!item)return;
    state.editEndpointId=id;$('#endpointName').value=item.name;$('#endpointMethod').value=item.method;$('#endpointStatus').value=item.status;$('#endpointPath').value=item.path;$('#endpointHeaders').value=pretty(item.headers);$('#endpointQuery').value=pretty(item.query_params);$('#endpointBody').value=item.body_template===null?'':pretty(item.body_template);$('#endpointForm button[type="submit"]').textContent='更新接口';$('#cancelEndpointEdit').classList.remove('hidden');$('#endpointEditorTitle').textContent='编辑接口 · '+item.name;$('#endpointEditor').open=true;showConfigTab('endpoint');syncExampleButtons();
  }
  function resetEndpointForm(){state.editEndpointId=null;$('#endpointForm').reset();$('#endpointMethod').value='GET';$('#endpointStatus').value='active';$('#endpointHeaders').value='{}';$('#endpointQuery').value='{}';$('#endpointBody').value='';$('#endpointForm button[type="submit"]').textContent='保存接口';$('#cancelEndpointEdit').classList.add('hidden');$('#endpointEditorTitle').textContent='新增接口';$('#endpointEditor').open=false;syncExampleButtons();}
  async function deleteEndpoint(id){
    const item=state.endpoints.find(value=>value.id===id);if(!item||!confirm('删除接口「'+item.name+'」及其参数和映射？'))return;
    try{await api('/api/connectors/endpoints/'+id,{method:'DELETE'});if(state.endpointId===id)state.endpointId=null;await loadEndpoints();toast('接口已删除');}catch(error){toast(error.message,true);}
  }
  async function deleteParameter(id){try{await api('/api/connectors/parameters/'+id,{method:'DELETE'});if(state.editParameterId===id)resetParameterForm();await loadEndpointDetail();toast('参数已删除');}catch(error){toast(error.message,true);}}
  async function deleteMapping(id){try{await api('/api/connectors/mappings/'+id,{method:'DELETE'});if(picker.selectedMappingId===id){picker.selected=null;picker.selectedMappingId=null;}await loadEndpointDetail();toast('映射已删除');}catch(error){toast(error.message,true);}}

  $('#connectionForm').addEventListener('submit',async event=>{event.preventDefault();try{
    const payload={name:$('#connectionName').value.trim(),system_name:$('#systemName').value.trim(),base_url:$('#baseUrl').value.trim(),auth_type:$('#authType').value,auth_config:parseJson('#authConfig',{empty:{}}),timeout:Number($('#timeout').value),status:'active'};
    const editing=state.editConnectionId;const saved=await api('/api/connectors/connections'+(editing?'/'+editing:''),{method:editing?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});resetConnectionForm();await Promise.all([refreshConnections(saved.id),state.workspace?refreshWorkspaces(state.workspace.id):Promise.resolve()]);toast(editing?'连接已更新':'连接已创建，继续配置接口');
  }catch(error){toast(error.message,true);}});
  $('#cancelConnectionEdit').onclick=resetConnectionForm;

  $('#endpointForm').addEventListener('submit',async event=>{event.preventDefault();if(!state.connectionId)return;try{
    const payload={connection_id:state.connectionId,name:$('#endpointName').value.trim(),path:$('#endpointPath').value.trim(),method:$('#endpointMethod').value,headers:parseJson('#endpointHeaders',{empty:{}}),query_params:parseJson('#endpointQuery',{empty:{}}),body_template:parseJson('#endpointBody',{empty:null}),description:'',status:$('#endpointStatus').value};
    const editing=state.editEndpointId;const saved=await api('/api/connectors/endpoints'+(editing?'/'+editing:''),{method:editing?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});resetEndpointForm();await loadEndpoints(saved.id);toast(editing?'接口已更新':'接口已创建，继续配置参数和映射');
  }catch(error){toast(error.message,true);}});
  $('#cancelEndpointEdit').onclick=resetEndpointForm;

  $('#parameterForm').addEventListener('submit',async event=>{event.preventDefault();if(!state.endpointId)return;try{
    const sourceType=$('#parameterSourceType').value;const defaultRaw=$('#parameterDefault').value.trim();
    if(sourceType==='fixed'&&!defaultRaw)throw new Error('固定参数必须填写默认值');
    const editing=state.editParameterId;
    const payload={endpoint_id:state.endpointId,name:$('#parameterName').value.trim(),location:$('#parameterLocation').value,source_type:sourceType,source_key:sourceType==='fixed'?null:$('#parameterSourceKey').value.trim(),default_value:defaultRaw?parseJson('#parameterDefault'):null};
    await api('/api/connectors/parameters'+(editing?'/'+editing:''),{method:editing?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});resetParameterForm();await loadEndpointDetail();toast(editing?'参数已更新':'动态参数已添加');
  }catch(error){toast(error.message,true);}});
  $('#cancelParameterEdit').onclick=resetParameterForm;


  $('#executeForm').addEventListener('submit',async event=>{event.preventDefault();if(!state.endpointId)return;const button=$('#executeButton');try{
    button.disabled=true;button.textContent='正在调用外部 API…';$('#resultView').textContent='请求执行中…';
    const payload={endpoint_id:state.endpointId,parameters:parseJson('#runtimeParameters',{empty:{}}),context:parseJson('#runtimeContext',{empty:{}})};
    const dataset=await api('/api/connectors/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});state.lastDataset=dataset;$('#resultView').textContent=pretty(dataset);await Promise.all([refreshDatasets(),state.workspace?refreshWorkspaces(state.workspace.id):Promise.resolve()]);renderProgress();toast('接入成功，Dataset 已持久化');
  }catch(error){$('#resultView').textContent='执行失败：'+error.message;toast(error.message,true);}finally{button.disabled=false;button.textContent='执行当前接口';}});

  function updateParameterInputs(){const fixed=$('#parameterSourceType').value==='fixed';$('#parameterSourceKey').disabled=fixed;$('#parameterSourceKey').required=!fixed;}
  $('#parameterSourceType').addEventListener('change',updateParameterInputs);

  function formatTime(value){return value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'尚未同步';}
  function statusLabel(value){return value==='normal'?'正常':value==='failed'?'连接失败':'未测试';}
  function workspaceStatus(item){const labels={ready:'准备就绪',needs_source:'待接入数据',source_error:'数据异常',needs_template:'待上传模板',needs_binding:'待配置绑定'};return labels[item.setup_status]||'配置中';}
  function initials(value){return String(value||'数据').replace(/\s/g,'').slice(0,2).toUpperCase();}

  async function refreshWorkspaces(preferredId){
    const result=await api('/api/connectors/workspaces');state.workspaces=result.items;renderWorkspaceList();
    const workspaceId=preferredId||state.workspace?.id;if(workspaceId&&state.workspaces.some(item=>item.id===workspaceId))await openWorkspace(workspaceId,true);
  }
  function renderWorkspaceList(){
    const total=state.workspaces.length,ready=state.workspaces.filter(item=>item.ready).length,assets=state.workspaces.reduce((sum,item)=>sum+item.source_count+item.template_count,0);
    $('#workspaceCount').textContent=total;$('#readyWorkspaceCount').textContent=ready;$('#workspaceAssetCount').textContent=assets;$('#workspaceEmpty').classList.toggle('hidden',total>0);$('#workspaceCards').classList.toggle('hidden',total===0);
    $('#workspaceCards').innerHTML=state.workspaces.map(item=>'<button class="workspace-card" data-open-workspace="'+item.id+'"><div class="workspace-card-head"><span class="workspace-avatar">'+escapeHtml(initials(item.name))+'</span><div class="workspace-card-title"><h3>'+escapeHtml(item.name)+'</h3><p>'+escapeHtml(item.description||'管理该业务的数据来源和 PPT 模板')+'</p></div><span class="workspace-badge '+(item.ready?'ready':item.setup_status==='needs_binding'?'warning':'')+'">'+escapeHtml(workspaceStatus(item))+'</span></div><div class="workspace-stats"><div><span>数据来源</span><b>'+item.source_count+' 个</b></div><div><span>可绑定模板</span><b>'+item.bindable_template_count+' / '+item.template_count+'</b></div></div><span class="workspace-enter">进入工作空间 →</span></button>').join('');
    $$('[data-open-workspace]').forEach(button=>button.onclick=()=>openWorkspace(Number(button.dataset.openWorkspace)));
    $('#headerStatus').textContent=total?total+' 个工作空间':'尚未创建工作空间';
  }
  async function openWorkspace(id,show=true){
    state.workspace=await api('/api/connectors/workspaces/'+id);state.templates=state.workspace.templates||[];
    $('#workspaceTitle').textContent=state.workspace.name;$('#workspaceDescription').textContent=state.workspace.description||'管理当前空间的数据来源和 PPT 模板。';
    if(show){$('#workspaceListView').classList.add('hidden');$('#workspaceDetailView').classList.remove('hidden');}
    await refreshSourceSummaries();renderTemplates();renderWorkspaceJourney();
  }
  function closeWorkspace(){state.workspace=null;state.sources=[];state.templates=[];$('#workspaceDetailView').classList.add('hidden');$('#workspaceListView').classList.remove('hidden');renderWorkspaceList();}
  function renderWorkspaceJourney(){
    if(!state.workspace)return;const hasSource=state.sources.length>0,healthy=hasSource&&state.sources.every(item=>item.status==='normal'),hasTemplate=state.templates.length>0,hasBinding=state.templates.some(item=>item.bindable);
    $('#journeyWorkspace').className='journey-step done';$('#journeySource').className='journey-step '+(healthy?'done':'current');$('#journeyTemplate').className='journey-step '+(healthy&&hasTemplate?'done':healthy?'current':'');$('#journeyBinding').className='journey-step '+(healthy&&hasBinding?'done':healthy&&hasTemplate?'current':'');
    const ready=$('#workspaceReady');ready.classList.toggle('hidden',!(hasSource&&hasTemplate));ready.classList.toggle('warning',!healthy||!hasBinding);ready.textContent=!healthy?'部分数据来源异常，修复后再进入绑定编辑台。':hasBinding?'全部数据来源正常，模板绑定已保存，工作空间准备就绪。':'模板已上传；进入编辑台后可同时使用全部系统字段完成绑定。';
    ['#uploadTemplate','#assetUploadTemplate','#emptyUploadTemplate'].forEach(id=>{const button=$(id);button.disabled=!hasSource;button.title=hasSource?'':'请先接入数据来源';});
    $('#refreshWorkspaceData').disabled=!hasSource;$('#refreshWorkspaceData').title=hasSource?'刷新当前工作空间全部系统接口':'请先接入数据来源';
    $('#templateEmpty span').textContent=hasSource?'上传 .pptx 文件，保留原始页面和样式。':'完成数据接入后，即可上传该空间的 PPT 模板。';
  }
  function renderTemplates(){
    const total=state.templates.length;$('#templateEmpty').classList.toggle('hidden',total>0);$('#templateCards').classList.toggle('hidden',total===0);
    $('#templateCards').innerHTML=state.templates.map(item=>{const count=item.configured_binding_count||0;return '<article class="template-card"><div class="template-file">PPTX</div><div><strong>'+escapeHtml(item.source_name||item.template_id)+'</strong><small>'+escapeHtml(item.slide_count)+' 页 · PPT 对象绑定 '+escapeHtml(count)+' 处</small></div><div class="template-actions"><span class="workspace-badge '+(item.bindable?'ready':'warning')+'">'+(item.bindable?'已配置':'待配置')+'</span><button class="btn small primary" data-bind-template="'+escapeHtml(item.template_id)+'">'+(item.bindable?'编辑绑定':'开始绑定')+'</button></div></article>';}).join('');
    $$('[data-bind-template]').forEach(button=>button.onclick=()=>{location.href='/template-editor?workspace_id='+state.workspace.id+'&template='+encodeURIComponent(button.dataset.bindTemplate);});
  }
  async function refreshSourceSummaries(){
    if(!state.workspace){state.sources=[];return;}
    const result=await api('/api/connectors/sources?workspace_id='+state.workspace.id);state.sources=result.items;renderSourceSummaries();
  }
  function renderSourceSummaries(){
    const total=state.sources.length;
    $('#sourceEmpty').classList.toggle('hidden',total>0);$('#sourceCards').classList.toggle('hidden',total===0);
    $('#sourceCards').innerHTML=state.sources.map(item=>{const categories=(item.endpoint_names||[]).map(name=>'<span class="source-category">'+escapeHtml(name.replace(/^\d+\s*/,''))+'</span>').join('');return '<article class="source-card"><div class="source-title"><div class="source-avatar">'+escapeHtml(initials(item.name))+'</div><div><h4>'+escapeHtml(item.name)+'</h4><small>'+escapeHtml(item.endpoint_count||0)+' 个当前项目分类接口</small></div><div class="status '+escapeHtml(item.status)+'"><span class="status-dot"></span>'+escapeHtml(statusLabel(item.status))+'</div></div><div class="source-categories">'+categories+'</div><div class="source-meta"><div><span>最后同步</span><b>'+escapeHtml(formatTime(item.last_success_at))+'</b></div><div><span>分类数据</span><b>'+escapeHtml(item.dataset_count||0)+' 组 · '+escapeHtml(item.record_count||0)+' 条</b></div></div>'+(item.status==='failed'?'<div class="source-error">'+escapeHtml(item.reason||'连接失败，请重新检查数据来源')+'</div>':'')+'<div class="source-actions"><button class="btn small" data-view-source="'+escapeHtml(item.system_name)+'" '+(item.record_count?'':'disabled')+'>查看数据</button><button class="btn small" data-source-settings="'+item.id+'">设置</button></div></article>';}).join('');
    const recent=state.sources.filter(item=>item.last_used_at).slice(0,3);$('#recentSection').classList.toggle('hidden',recent.length===0);$('#recentSources').innerHTML=recent.map(item=>'<div class="recent-row"><strong>'+escapeHtml(item.name)+'</strong><span><span class="status-dot"></span> '+escapeHtml(statusLabel(item.status))+'</span><span>'+escapeHtml(formatTime(item.last_used_at))+'</span><div class="recent-actions"><button class="btn small" data-view-source="'+escapeHtml(item.system_name)+'">查看数据</button><button class="btn small" disabled>生成报告</button></div></div>').join('');
    $$('[data-view-source]').forEach(button=>button.onclick=()=>openDataPreview(button.dataset.viewSource));
    $$('[data-source-settings]').forEach(button=>button.onclick=async()=>{showMode('advanced');await selectConnection(Number(button.dataset.sourceSettings));editConnection(Number(button.dataset.sourceSettings));});
    renderWorkspaceJourney();
  }

  function showMode(mode){
    const advanced=mode==='advanced';$('#normalView').classList.toggle('hidden',advanced);$('#advancedView').classList.toggle('hidden',!advanced);$('#normalMode').classList.toggle('active',!advanced);$('#advancedMode').classList.toggle('active',advanced);if(advanced)updateConfigNavigation();
  }
  $('#normalMode').onclick=()=>showMode('normal');$('#advancedMode').onclick=async()=>{showMode('advanced');const workspaceConnection=state.workspace?.sources?.[0]?.id;if(workspaceConnection&&workspaceConnection!==state.connectionId)await selectConnection(workspaceConnection);};
  $$('[data-config-tab]').forEach(button=>button.onclick=()=>showConfigTab(button.dataset.configTab));

  function openWorkspaceModal(){$('#workspaceForm').reset();$('#workspaceModal').classList.remove('hidden');$('#workspaceName').focus();}
  function closeWorkspaceModal(){$('#workspaceModal').classList.add('hidden');}
  $('#newWorkspace').onclick=openWorkspaceModal;$('#emptyNewWorkspace').onclick=openWorkspaceModal;$('#cancelWorkspace').onclick=closeWorkspaceModal;$('#workspaceModal').onclick=event=>{if(event.target===$('#workspaceModal'))closeWorkspaceModal();};
  $('#workspaceForm').onsubmit=async event=>{event.preventDefault();const button=event.submitter;try{button.disabled=true;button.textContent='正在创建…';const workspace=await api('/api/connectors/workspaces',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#workspaceName').value.trim(),description:$('#workspaceDesc').value.trim()})});closeWorkspaceModal();await refreshWorkspaces(workspace.id);toast('工作空间已创建');}catch(error){toast(error.message,true);}finally{button.disabled=false;button.textContent='创建并进入';}};
  $('#backToWorkspaces').onclick=closeWorkspace;
  $('#refreshWorkspaceData').onclick=async()=>{if(!state.workspace)return;const button=$('#refreshWorkspaceData');try{
    button.disabled=true;button.textContent='正在刷新全部系统…';const result=await api('/api/connectors/workspaces/'+state.workspace.id+'/refresh',{method:'POST'});await Promise.all([refreshDatasets(),refreshWorkspaces(state.workspace.id)]);toast(result.failed?'已刷新 '+result.refreshed+' 个接口，'+result.failed+' 个失败':'全部 '+result.refreshed+' 个接口已刷新',result.failed>0);
  }catch(error){toast(error.message,true);}finally{button.disabled=false;button.textContent='刷新全部数据';}};

  function chooseTemplate(){if(!state.workspace){toast('请先进入工作空间',true);return;}if(!state.sources.length){toast('请先接入数据来源，再上传 PPT 模板',true);return;}$('#templateFile').click();}
  $('#uploadTemplate').onclick=chooseTemplate;$('#assetUploadTemplate').onclick=chooseTemplate;$('#emptyUploadTemplate').onclick=chooseTemplate;
  $('#templateFile').onchange=async event=>{const file=event.target.files[0];if(!file)return;const buttons=[$('#uploadTemplate'),$('#assetUploadTemplate'),$('#emptyUploadTemplate')];try{
    buttons.forEach(button=>button.disabled=true);toast('正在上传并检查 PPT 模板…');const form=new FormData();form.append('file',file);const stem=file.name.replace(/\.pptx?$/i,'').toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff_-]+/g,'-').replace(/^-+|-+$/g,'').slice(0,48)||'template';const templateId='workspace-'+state.workspace.id+'-'+stem;const uploaded=await api('/api/templates/upload?template_id='+encodeURIComponent(templateId),{method:'POST',body:form});const scan=await api('/api/template/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({template:uploaded.template.template_id})});await api('/api/connectors/workspaces/'+state.workspace.id+'/templates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({template_id:uploaded.template.template_id,source_name:file.name,slide_count:uploaded.slide_count,size:file.size,placeholder_count:scan.placeholder_count||0,binding_target_count:(scan.binding_targets||[]).length})});await refreshWorkspaces(state.workspace.id);toast(scan.placeholder_count||(scan.binding_targets||[]).length?'PPT 模板已上传并发现可绑定字段':'PPT 已上传，下一步需要配置模板绑定');
  }catch(error){toast(error.message,true);}finally{buttons.forEach(button=>button.disabled=false);event.target.value='';}};

  function resetWizard(){
    wizard.step=1;wizard.inspect=null;wizard.mappings={};wizard.customTargets=[];wizard.selectedSource=null;wizard.saving=false;$('#wizardConnectionForm').reset();$('#wizardApiKeyName').value='X-API-Key';$('#testResult').innerHTML='';$('#discoveredGroups').innerHTML='';$('#externalFields').innerHTML='';$('#targetFields').innerHTML='';$('#customTargetName').value='';$('#fieldSearch').value='';$('#selectedFieldCount').textContent='';$('#wizardRawJson').textContent='';setWizardStep(1);updateWizardAuth();
  }
  function openWizard(){if(!state.workspace){toast('请先创建并进入工作空间',true);return;}resetWizard();$('#wizardBackdrop').classList.remove('hidden');}
  function closeWizard(){if(wizard.saving)return;$('#wizardBackdrop').classList.add('hidden');}
  const stepNames=['选择类型','连接信息','测试连接','查看数据','确认字段','完成'];
  function setWizardStep(step){
    wizard.step=step;$$('[data-wizard-panel]').forEach(panel=>panel.classList.toggle('hidden',Number(panel.dataset.wizardPanel)!==step));$$('#wizardSteps .wizard-step').forEach((item,index)=>item.className='wizard-step'+(index+1<step?' done':index+1===step?' active':''));$('#wizardStepName').textContent='步骤 '+step+' / 6 · '+stepNames[step-1];$('#wizardBack').classList.toggle('hidden',step===1||step===6);
    const next=$('#wizardNext');next.disabled=false;next.classList.remove('hidden');next.textContent=step===5?'保存数据来源':step===6?'完成':'下一步';if(step===3)next.classList.add('hidden');
  }
  function validateConnectionFields(){
    if(!$('#wizardName').value.trim())throw new Error('请填写数据来源名称');
    if(!$('#wizardUrl').value.trim())throw new Error('请填写接口地址');
    try{new URL($('#wizardUrl').value.trim());}catch(_){throw new Error('接口地址格式不正确');}
    if(document.querySelector('[name="wizardAuth"]:checked').value==='api_key'&&!$('#wizardApiKeyValue').value)throw new Error('请填写 API Key');
  }
  function updateWizardAuth(){const usesKey=document.querySelector('[name="wizardAuth"]:checked').value==='api_key';$('#apiKeyNameField').classList.toggle('hidden',!usesKey);$('#apiKeyValueField').classList.toggle('hidden',!usesKey);}
  $$('[name="wizardAuth"]').forEach(input=>input.onchange=updateWizardAuth);
  $('#newSource').onclick=openWizard;$('#assetNewSource').onclick=openWizard;$('#emptyNewSource').onclick=openWizard;$('#closeWizard').onclick=closeWizard;$('#wizardBackdrop').addEventListener('click',event=>{if(event.target===$('#wizardBackdrop'))closeWizard();});
  $('#wizardBack').onclick=()=>setWizardStep(Math.max(1,wizard.step-1));
  $('#wizardNext').onclick=async()=>{try{
    if(wizard.step===1){setWizardStep(2);return;}
    if(wizard.step===2){validateConnectionFields();$('#testSummary').textContent=$('#wizardName').value.trim()+' · '+$('#wizardUrl').value.trim();setWizardStep(3);return;}
    if(wizard.step===4){if(!wizard.inspect.fields.some(field=>field.selected))throw new Error('请至少确认一个字段');renderMappingBoard();setWizardStep(5);return;}
    if(wizard.step===5){await saveWizardSource();return;}
    if(wizard.step===6){closeWizard();}
  }catch(error){toast(error.message,true);}};

  $('#runConnectionTest').onclick=async()=>{const button=$('#runConnectionTest');try{
    validateConnectionFields();button.disabled=true;button.textContent='正在测试…';$('#testResult').innerHTML='';
    const payload={name:$('#wizardName').value.trim(),system_type:'api',url:$('#wizardUrl').value.trim(),auth_type:document.querySelector('[name="wizardAuth"]:checked').value,api_key_name:$('#wizardApiKeyName').value.trim()||'X-API-Key',api_key_value:$('#wizardApiKeyValue').value||null,project_id:$('#wizardProjectId').value.trim()||null};
    wizard.inspect=await api('/api/connectors/wizard/inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});initializeMappings();renderDiscoveredFields();$('#wizardRawJson').textContent=pretty(wizard.inspect.raw);const picked=wizard.inspect.fields.filter(field=>field.selected).length;$('#testResult').innerHTML='<div class="test-result success"><strong>连接成功</strong>发现 '+wizard.inspect.fields.length+' 个字段，已智能选择 '+picked+' 个；最大集合约 '+wizard.inspect.record_count+' 条记录。</div>';setTimeout(()=>setWizardStep(4),350);
  }catch(error){const technical=error.detail&&error.detail.technical_detail;$('#testResult').innerHTML='<div class="test-result failed"><strong>'+escapeHtml(error.message)+'</strong><span>请修改连接信息后重新测试。</span>'+(technical?'<details class="technical"><summary>查看技术详情</summary><pre>'+escapeHtml(technical)+'</pre></details>':'')+'</div>';}finally{button.disabled=false;button.textContent='重新测试连接';}};

  function initializeMappings(){
    wizard.mappings={};wizard.customTargets=[];const used=new Set();wizard.inspect.fields.forEach(field=>{field.display_name=field.display_name||field.external_name;if(field.selected&&field.recommended_target&&!used.has(field.recommended_target)){wizard.mappings[field.source_path]=field.recommended_target;used.add(field.recommended_target);}});
  }
  function renderDiscoveredFields(){
    if(!wizard.inspect)return;const keyword=$('#fieldSearch').value.trim().toLowerCase(),visible=wizard.inspect.fields.filter(field=>!keyword||(field.external_name+' '+field.display_name+' '+field.source_path).toLowerCase().includes(keyword));const groups={};visible.forEach(field=>(groups[field.group]||(groups[field.group]=[])).push(field));const typeLabel={image:'图片',number:'数字',boolean:'是/否',collection:'整组记录',text:'文本'};$('#selectedFieldCount').textContent='已选 '+wizard.inspect.fields.filter(field=>field.selected).length+' / '+wizard.inspect.fields.length;$('#discoveredGroups').innerHTML=Object.entries(groups).map(([name,fields])=>'<div class="group"><div class="group-title"><h4>'+escapeHtml(name)+'</h4><span>'+fields.length+' 个字段</span></div><div class="field-table"><div class="field-row head"><span></span><span>显示名称</span><span>示例数据</span><span>类型</span></div>'+fields.map(field=>'<label class="field-row"><input type="checkbox" data-discovered="'+escapeHtml(field.source_path)+'" '+(field.selected?'checked':'')+'><span class="field-name"><input class="field-label-input" data-field-label="'+escapeHtml(field.source_path)+'" value="'+escapeHtml(field.display_name)+'" maxlength="80"><small>原字段：'+escapeHtml(field.external_name)+' · '+escapeHtml(field.source_path)+'</small></span><span class="sample" title="'+escapeHtml(field.sample)+'">'+escapeHtml(field.sample||'空值')+'</span><span class="type-tag">'+escapeHtml(typeLabel[field.value_type]||'文本')+'</span></label>').join('')+'</div></div>').join('')||'<div class="empty-state"><h3>没有匹配字段</h3><p>请更换搜索关键词。</p></div>';
    $$('[data-discovered]').forEach(input=>input.onchange=()=>{const field=wizard.inspect.fields.find(item=>item.source_path===input.dataset.discovered);field.selected=input.checked;if(!input.checked)delete wizard.mappings[field.source_path];else if(field.recommended_target&&!mappingForTarget(field.recommended_target))wizard.mappings[field.source_path]=field.recommended_target;renderDiscoveredFields();});
    $$('[data-field-label]').forEach(input=>{input.onclick=event=>event.stopPropagation();input.oninput=()=>{const field=wizard.inspect.fields.find(item=>item.source_path===input.dataset.fieldLabel);field.display_name=input.value.trim()||field.external_name;};});
  }
  $('#fieldSearch').oninput=renderDiscoveredFields;
  $('#selectRecommended').onclick=()=>{if(!wizard.inspect)return;const used=new Set();wizard.mappings={};wizard.inspect.fields.forEach(field=>{field.selected=false;if(field.recommended_target&&field.confidence>=.9&&!used.has(field.recommended_target)){field.selected=true;wizard.mappings[field.source_path]=field.recommended_target;used.add(field.recommended_target);}});renderDiscoveredFields();};
  $('#selectAllFields').onclick=()=>{if(!wizard.inspect)return;wizard.inspect.fields.forEach(field=>field.selected=true);renderDiscoveredFields();};
  $('#clearFields').onclick=()=>{if(!wizard.inspect)return;wizard.inspect.fields.forEach(field=>field.selected=false);wizard.mappings={};renderDiscoveredFields();};
  function mappingForTarget(target){return Object.entries(wizard.mappings).find(([,value])=>value===target)?.[0];}
  function assignMapping(sourcePath,target){Object.keys(wizard.mappings).forEach(path=>{if(wizard.mappings[path]===target)delete wizard.mappings[path];});wizard.mappings[sourcePath]=target;wizard.selectedSource=null;renderMappingBoard();}
  function renderMappingBoard(){
    const fields=wizard.inspect.fields.filter(field=>field.selected);$('#externalFields').innerHTML=fields.map(field=>'<div class="mapping-card '+(wizard.selectedSource===field.source_path?'selected':'')+'" draggable="true" data-map-source="'+escapeHtml(field.source_path)+'"><button class="mapping-remove" data-remove-source="'+escapeHtml(field.source_path)+'" type="button">移除</button><b>'+escapeHtml(field.display_name)+'</b><small>'+escapeHtml(field.external_name)+(wizard.mappings[field.source_path]?' · 已匹配':' · 未指定系统字段')+'</small></div>').join('');
    const targets=wizard.inspect.targets.concat(wizard.customTargets);$('#targetFields').innerHTML=targets.map(target=>{const path=mappingForTarget(target.key),field=fields.find(item=>item.source_path===path),custom=target.key.startsWith('custom_');return '<div class="target-slot '+(field?'mapped':'')+'" data-map-target="'+escapeHtml(target.key)+'"><b>'+escapeHtml(target.label)+'</b><span>'+(field?escapeHtml(field.display_name)+' · '+escapeHtml(field.external_name):'拖动或点击选择')+'</span>'+(field?'<button class="target-clear" data-clear-target="'+escapeHtml(target.key)+'" type="button">清除</button>':custom?'<button class="target-clear" data-delete-custom="'+escapeHtml(target.key)+'" type="button">删除</button>':'')+'</div>';}).join('');
    $$('[data-map-source]').forEach(card=>{card.onclick=()=>{wizard.selectedSource=card.dataset.mapSource;renderMappingBoard();};card.ondragstart=event=>event.dataTransfer.setData('text/plain',card.dataset.mapSource);});
    $$('[data-map-target]').forEach(slot=>{slot.ondragover=event=>{event.preventDefault();slot.classList.add('dragover');};slot.ondragleave=()=>slot.classList.remove('dragover');slot.ondrop=event=>{event.preventDefault();assignMapping(event.dataTransfer.getData('text/plain'),slot.dataset.mapTarget);};slot.onclick=()=>{if(wizard.selectedSource)assignMapping(wizard.selectedSource,slot.dataset.mapTarget);};});
    $$('[data-remove-source]').forEach(button=>button.onclick=event=>{event.stopPropagation();const field=wizard.inspect.fields.find(item=>item.source_path===button.dataset.removeSource);field.selected=false;delete wizard.mappings[field.source_path];renderMappingBoard();});
    $$('[data-clear-target]').forEach(button=>button.onclick=event=>{event.stopPropagation();const path=mappingForTarget(button.dataset.clearTarget);if(path)delete wizard.mappings[path];renderMappingBoard();});
    $$('[data-delete-custom]').forEach(button=>button.onclick=event=>{event.stopPropagation();wizard.customTargets=wizard.customTargets.filter(item=>item.key!==button.dataset.deleteCustom);renderMappingBoard();});
  }
  $('#addCustomTarget').onclick=()=>{const input=$('#customTargetName'),label=input.value.trim();if(!label){toast('请填写自定义字段名称',true);return;}const key='custom_'+Date.now().toString(36)+'_'+wizard.customTargets.length;wizard.customTargets.push({key:key,label:label});input.value='';renderMappingBoard();};

  function fallbackTarget(field,index){const clean=field.external_name.replace(/[^A-Za-z0-9_]/g,'_').replace(/^([^A-Za-z_])/,'_$1').slice(0,50);return 'fields.'+(clean||'field_'+(index+1));}
  async function saveWizardSource(){
    if(wizard.saving)return;wizard.saving=true;const next=$('#wizardNext');next.disabled=true;next.textContent='正在保存…';let connectionId=null;
    try{
      const name=$('#wizardName').value.trim(),authType=document.querySelector('[name="wizardAuth"]:checked').value,authConfig=authType==='api_key'?{name:$('#wizardApiKeyName').value.trim()||'X-API-Key',key:$('#wizardApiKeyValue').value,location:'header'}:{};
      const connection=await api('/api/connectors/connections',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,system_name:'SRC-'+Date.now(),base_url:wizard.inspect.configuration.base_url,auth_type:authType,auth_config:authConfig,timeout:30,status:'active'})});connectionId=connection.id;
      const config=wizard.inspect.configuration,endpoint=await api('/api/connectors/endpoints',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({connection_id:connection.id,name:'数据读取接口',path:config.path,method:config.method,headers:{},query_params:config.query_params,body_template:null,description:'由普通模式向导创建',status:'active'})});
      if(config.parameter)await api('/api/connectors/parameters',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({endpoint_id:endpoint.id,name:config.parameter.name,location:config.parameter.location,source_type:'input',source_key:config.parameter.source_key,default_value:null})});
      const selected=wizard.inspect.fields.filter(field=>field.selected),used=new Set();for(let index=0;index<selected.length;index++){const field=selected[index];let target=wizard.mappings[field.source_path]||fallbackTarget(field,index);while(used.has(target))target=fallbackTarget(field,index)+'_'+index;used.add(target);const transformConfig={display_name:field.display_name||field.external_name};if(field.value_type==='image')transformConfig.url_base=wizard.inspect.configuration.base_url;await api('/api/connectors/mappings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({endpoint_id:endpoint.id,source_path:field.source_path,target_field:target,transform_type:'none',transform_config:transformConfig})});}
      const parameters=config.parameter?{project_id:$('#wizardProjectId').value.trim()}:{};const dataset=await api('/api/connectors/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({endpoint_id:endpoint.id,parameters:parameters,context:{}})});state.lastDataset=dataset;
      await api('/api/connectors/workspaces/'+state.workspace.id+'/sources',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({connection_id:connection.id})});
      $('#completeSummary').innerHTML='<div><span>工作空间</span><b>'+escapeHtml(state.workspace.name)+'</b></div><div><span>数据来源</span><b>'+escapeHtml(name)+'</b></div><div><span>已确认字段</span><b>'+selected.length+' 个</b></div><div><span>首份数据</span><b>'+escapeHtml(wizard.inspect.record_count)+' 条</b></div>';setWizardStep(6);await Promise.all([refreshConnections(connection.id),refreshDatasets(),refreshWorkspaces(state.workspace.id)]);toast('数据来源已加入当前工作空间');
    }catch(error){if(connectionId){try{await api('/api/connectors/connections/'+connectionId,{method:'DELETE'});}catch(_){}}toast(error.message,true);next.disabled=false;next.textContent='保存数据来源';}finally{wizard.saving=false;}
  }

  function flattenPreview(value,prefix='',rows=[]){
    if(Array.isArray(value)){if(!value.length)rows.push([prefix,'空列表']);else if(typeof value[0]==='object')flattenPreview(value[0],prefix+'（首条）',rows);else rows.push([prefix,value.slice(0,3).join('、')]);}
    else if(value&&typeof value==='object')Object.entries(value).forEach(([key,child])=>flattenPreview(child,prefix?prefix+' / '+key:key,rows));
    else rows.push([prefix,String(value??'')]);return rows;
  }
  const previewLabels={project_name:'项目名称',issue_title:'问题标题',severity:'严重等级',issue_image:'问题图片',description:'问题描述',status:'处理状态',identifier:'编号',fields:'其他字段'};
  function previewLabel(path,labels={}){const target=path.replaceAll(' / ','.');if(labels[target])return labels[target];return path.split(' / ').map(part=>labels[part]||previewLabels[part]||part).join(' / ');}
  async function openDataPreview(systemName){try{
    const result=await api('/api/connectors/datasets?source='+encodeURIComponent(systemName)+'&limit=1');if(!result.items.length)throw new Error('该数据来源还没有可预览的数据');const dataset=result.items[0],source=state.sources.find(item=>item.system_name===systemName),labels=source?.display_labels||{};$('#dataSourceTitle').textContent=(source?source.name:systemName)+' · 数据预览';$('#dataTimestamp').textContent='同步于 '+formatTime(dataset.created_at);$('#dataSheet').innerHTML=flattenPreview(dataset.data).map(([key,value])=>'<div class="sheet-row"><div>'+escapeHtml(previewLabel(key,labels))+'</div><div>'+escapeHtml(value)+'</div></div>').join('');$('#dataRaw').textContent=pretty(dataset.data);$('#dataBackdrop').classList.remove('hidden');
  }catch(error){toast(error.message,true);}}
  $('#closeData').onclick=()=>$('#dataBackdrop').classList.add('hidden');$('#dataBackdrop').addEventListener('click',event=>{if(event.target===$('#dataBackdrop'))$('#dataBackdrop').classList.add('hidden');});

  function openOpenApiImport(){
    if(!state.workspace){toast('请先创建并进入工作空间',true);return;}
    openapiImport.preview=null;
    $('#openapiSpecUrl').value='';$('#openapiSpecText').value='';$('#openapiConnectionName').value='';
    $('#openapiInputStep').classList.remove('hidden');$('#openapiPreviewStep').classList.add('hidden');$('#openapiConfirmStep').classList.add('hidden');
    $('#openapiImportModal').classList.remove('hidden');
  }
  function closeOpenApiImport(){$('#openapiImportModal').classList.add('hidden');}
  function openapiPayload(){return {spec_url:$('#openapiSpecUrl').value.trim()||null,spec_text:$('#openapiSpecText').value.trim()||null};}
  function openapiSelectedIds(){return $$('[data-openapi-operation]:checked').map(input=>input.value);}
  function renderOpenApiPreview(){
    const preview=openapiImport.preview;if(!preview)return;
    $('#openapiSummary').innerHTML='<b>'+escapeHtml(preview.title)+'</b>'+(preview.version?' · '+escapeHtml(preview.version):'')+'<br><small>'+escapeHtml(preview.base_url)+'</small>';
    $('#openapiOperations').innerHTML=preview.operations.map((operation,index)=>'<label class="openapi-operation"><input type="checkbox" data-openapi-operation value="'+escapeHtml(operation.id)+'" '+(index===0?'checked':'')+'><span><b>'+escapeHtml(operation.name)+'</b><small><code>'+escapeHtml(operation.method)+'</code> '+escapeHtml(operation.path)+(operation.description?' · '+escapeHtml(operation.description):'')+'</small></span><span class="op-count">'+operation.parameters.length+' 个参数 · '+operation.mappings.length+' 个字段</span></label>').join('');
    const ignored=preview.ignored_operations||[];
    $('#openapiIgnored').classList.toggle('hidden',!ignored.length);
    $('#openapiIgnored').textContent=ignored.length?'未导入 '+ignored.map(item=>item.method+' '+item.path).join('、')+'：当前工作台仅支持 GET、POST。':'';
    const update=()=>$('#openapiSelectedCount').textContent='已选 '+openapiSelectedIds().length+' 个接口';
    $$('[data-openapi-operation]').forEach(input=>input.onchange=update);update();
  }
  function renderOpenApiAuth(){
    const preview=openapiImport.preview,selected=$('#openapiAuthType').value,option=(preview.auth_options||[]).find(item=>item.auth_type===selected)||{config:{}};
    $('#openapiAuthHint').textContent=option.label&&selected!=='none'?'接口文档声明：'+option.label:'';
    if(selected==='api_key')$('#openapiAuthFields').innerHTML='<div class="field"><label for="openapiApiKey">API Key <span class="required">*</span></label><input id="openapiApiKey" type="password" autocomplete="off" placeholder="'+escapeHtml(option.config?.name||'X-API-Key')+'"></div>';
    else if(selected==='bearer')$('#openapiAuthFields').innerHTML='<div class="field"><label for="openapiBearerToken">Bearer Token <span class="required">*</span></label><input id="openapiBearerToken" type="password" autocomplete="off"></div>';
    else if(selected==='basic')$('#openapiAuthFields').innerHTML='<div class="form-grid"><div class="field"><label for="openapiUsername">用户名 <span class="required">*</span></label><input id="openapiUsername" autocomplete="username"></div><div class="field"><label for="openapiPassword">密码 <span class="required">*</span></label><input id="openapiPassword" type="password" autocomplete="current-password"></div></div>';
    else $('#openapiAuthFields').innerHTML='';
  }
  $('#openOpenApiImport').onclick=openOpenApiImport;
  $('#closeOpenApiImport').onclick=closeOpenApiImport;
  $('#openapiImportModal').onclick=event=>{if(event.target===$('#openapiImportModal'))closeOpenApiImport();};
  $('#chooseOpenApiFile').onclick=()=>$('#openapiSpecFile').click();
  $('#openapiSpecFile').onchange=async event=>{const file=event.target.files[0];if(!file)return;try{$('#openapiSpecText').value=await file.text();$('#openapiSpecUrl').value='';toast('已读取 '+file.name);}catch(error){toast('无法读取该文件',true);}finally{event.target.value='';}};
  $('#parseOpenApi').onclick=async()=>{const button=$('#parseOpenApi'),original=button.textContent;try{
    button.disabled=true;button.textContent='正在解析…';openapiImport.preview=await api('/api/connectors/imports/openapi/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(openapiPayload())});renderOpenApiPreview();$('#openapiInputStep').classList.add('hidden');$('#openapiPreviewStep').classList.remove('hidden');
  }catch(error){toast(error.message,true);}finally{button.disabled=false;button.textContent=original;}};
  $('#openapiBackToInput').onclick=()=>{$('#openapiPreviewStep').classList.add('hidden');$('#openapiInputStep').classList.remove('hidden');};
  $('#openapiToConfirm').onclick=()=>{const selected=openapiSelectedIds();if(!selected.length){toast('请至少选择一个接口',true);return;}const preview=openapiImport.preview;$('#openapiConnectionName').value=preview.title||'API 数据来源';$('#openapiAuthType').innerHTML=(preview.auth_options||[]).map(option=>'<option value="'+escapeHtml(option.auth_type)+'">'+escapeHtml(option.label||option.auth_type)+'</option>').join('');renderOpenApiAuth();const operations=preview.operations.filter(item=>selected.includes(item.id));const fields=operations.reduce((total,item)=>total+item.mappings.length,0);$('#openapiConfirmSummary').textContent='将导入 '+operations.length+' 个接口、'+fields+' 条字段映射，并关联到当前工作空间。导入后可在高级配置中修改。';$('#openapiPreviewStep').classList.add('hidden');$('#openapiConfirmStep').classList.remove('hidden');};
  $('#openapiBackToPreview').onclick=()=>{$('#openapiConfirmStep').classList.add('hidden');$('#openapiPreviewStep').classList.remove('hidden');};
  $('#openapiAuthType').onchange=renderOpenApiAuth;
  $('#commitOpenApi').onclick=async()=>{const button=$('#commitOpenApi'),original=button.textContent,preview=openapiImport.preview;try{
    const name=$('#openapiConnectionName').value.trim();if(!name)throw new Error('请填写数据来源名称');const authType=$('#openapiAuthType').value;let authConfig={};
    if(authType==='api_key')authConfig={key:$('#openapiApiKey').value};
    if(authType==='bearer')authConfig={token:$('#openapiBearerToken').value};
    if(authType==='basic')authConfig={username:$('#openapiUsername').value,password:$('#openapiPassword').value};
    button.disabled=true;button.textContent='正在导入…';const result=await api('/api/connectors/imports/openapi/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...openapiPayload(),document_hash:preview.document_hash,name:name,auth_type:authType,auth_config:authConfig,selected_operations:openapiSelectedIds(),workspace_id:state.workspace.id})});
    await Promise.all([refreshConnections(result.connection.id),refreshWorkspaces(state.workspace.id)]);closeOpenApiImport();toast('已导入 '+result.endpoints.length+' 个接口；可在高级配置中验证真实数据');showMode('advanced');await selectConnection(result.connection.id);
  }catch(error){toast(error.message,true);}finally{button.disabled=false;button.textContent=original;}};

  async function start(){try{
    updateParameterInputs();wireExampleButtons();pickerRestoreGrouping();clearPicker();await Promise.all([refreshConnections(),refreshDatasets(),refreshWorkspaces()]);
  }catch(error){$('#headerStatus').textContent='加载失败';toast(error.message,true);}}
  start();
})();
