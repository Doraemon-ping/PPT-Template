'use strict';
/* Workflow helpers layered on the existing workbench; saved deck schemas stay compatible. */
var UX=EditorModels;
var formulaExtraFields={
  'ppt.force.pressure':'铸造压力（公式显示）','ppt.force.area_part':'产品投影面积（公式显示）',
  'ppt.force.area_slider':'滑块投影面积（公式显示）','ppt.force.area_runner':'流道投影面积（公式显示）',
  'ppt.force.area_overflow':'渣包投影面积（公式显示）','ppt.force.part':'产品胀型力',
  'ppt.force.slider':'滑块胀型力','ppt.force.runner':'流道胀型力','ppt.force.overflow':'渣包胀型力',
  'ppt.force.total':'总胀型力','ppt.force.slider_angle':'滑块夹角（公式显示）',
  'ppt.force.slider_term':'滑块角度修正项','ppt.force.clamp_factor':'锁模安全系数（公式显示）',
  'ppt.force.clamp_required':'所需锁模力'
};
function bindingDraftKey(info){
  var page=currentPage();if(!page._editorId)page._editorId=crypto.randomUUID();
  return page._editorId+':'+info.key;
}
function rememberBindingDraft(){
  var bar=$('#selBar');if(!bar||!bar._info||bar._skipRemember||!bar._draftId)return;
  if(!bar._dirty)return;
  state.bindingDrafts=state.bindingDrafts||{};
  if(bar._mapTbl&&$('#inpRowsPerPage')){
    var columns={};$$('#selBar .mapcol').forEach(function(el){columns[el.dataset.col]=el.value;});
    state.bindingDrafts[bar._draftId]={type:'table_rows',table:bar._mapTbl,columns:columns,
      keepRows:$('#inpKeepRows').value,styleRow:$('#inpStyleRow').value,rowsPerPage:$('#inpRowsPerPage').value};
    return;
  }
  if(!$('#inpSource'))return;
  state.bindingDrafts[bar._draftId]={source:$('#inpSource').value,type:$('#selBindType').value,
    template:$('#inpDisplayTemplate').value,partial:UX.copy(bar._partialDraft||[]),
    blocks:bar._formulaBlocks?UX.copy(bar._formulaBlocks):null,map:bar._formulaMap?UX.copy(bar._formulaMap):null};
}
function markBindingDirty(){
  var bar=$('#selBar');if(!bar._info)return;bar._dirty=true;
  $('#bindingDraftStatus').textContent='有未保存修改 · 切换对象会保留本次草稿；请保存绑定后再保存方案。';
  rememberBindingDraft();
}
function clearBindingDraft(info){
  var bar=$('#selBar'),key=bar._draftId||bindingDraftKey(info);
  if(state.bindingDrafts)delete state.bindingDrafts[key];
  if(state.partialDrafts)delete state.partialDrafts[key];
  bar._dirty=false;bar._skipRemember=true;
}
function hasPendingBindingDrafts(){rememberBindingDraft();return Object.keys(state.bindingDrafts||{}).some(function(key){return state.deck.some(function(p){return p._editorId&&key.startsWith(p._editorId+':');});});}
function restoreBindingDraft(info,existing){
  var bar=$('#selBar');bar._draftId=bindingDraftKey(info);bar._skipRemember=false;
  var draft=(state.bindingDrafts||{})[bar._draftId];bar._dirty=!!draft;
  if(draft){$('#inpSource').value=draft.source;$('#selBindType').value=draft.type;
    $('#inpDisplayTemplate').value=draft.template;bar._partialDraft=UX.copy(draft.partial);renderPartialDraft();}
  $('#bindingDraftStatus').textContent=draft?'已恢复未保存草稿 · 保存绑定后生效。':(existing?'已保存绑定 · 修改后请保存绑定并预览。':'尚未绑定 · 先选择内容和字段，再保存绑定。');
  bar.oninput=function(e){if(e.target.id!=='partialSearch'&&e.target.id!=='formulaSearch')markBindingDirty();};
  bar.onchange=function(e){if(!['formulaField','partialField'].includes(e.target.id))markBindingDirty();};
  bar.onclick=function(e){if(e.target.closest('#btnAddPartial,[data-remove-partial]'))markBindingDirty();};
  initFormulaEditor(existing,draft);
}
function refreshObjectNavigator(){
  var query=$('#objectSearch').value.trim().toLowerCase(),select=$('#selObject'),previous=select.value;
  var shapes=shapesOf(state.previewSource),items=[];
  var kinds={text:'文本',picture:'图片',table:'整表',ole:'公式',group:'组合',shape:'形状'};
  shapes.forEach(function(sh){
    var key=shapeKey(sh),name=(kinds[sh.kind]||'对象')+' · '+sh.shape_name+' [ID '+sh.shape_id+']';
    items.push({key:key,label:name+' '+(sh.text||'').slice(0,30),tableBound:sh.kind==='table'&&!!UX.tableBinding((editablePage()||{}).bindings,{name:sh.shape_name,shape_id:sh.shape_id})});
    var wholeTable=Object.values((editablePage()||{}).bindings||{}).some(function(b){return b.type==='table_rows'&&(b.options&&b.options.shape_id?b.options.shape_id===sh.shape_id:b.shape===sh.shape_name);});
    (wholeTable&&$('#chkLivePreview').checked?[]:sh.cells||[]).forEach(function(c){items.push({key:key+'#'+c.row+'x'+c.column,
      label:'单元格 · '+sh.shape_name+' 第'+(c.row+1)+'行'+(c.column+1)+'列 · '+(c.text||'空白').slice(0,32)});});
  });
  var page=editablePage(),bound=(page||{}).bindings||{};
  select.innerHTML='<option value="">选择对象或单元格</option>'+items.filter(function(x){return x.label.toLowerCase().includes(query);})
    .map(function(x){return '<option value="'+esc(x.key)+'">'+esc(x.label)+(bound[x.key]||x.tableBound?' · 已绑定':'')+'</option>';}).join('');
  select.value=previous;
  $('#objectSummary').textContent='本页 '+shapes.length+' 个对象 · 已保存 '+Object.keys(bound).length+' 处绑定。重叠对象可从列表选择。';
  $$('#canvas .sbox,#canvas .k-cell').forEach(function(el){el.tabIndex=0;el.setAttribute('role','button');
    el.setAttribute('aria-label',(el.dataset.name||'对象')+(el.classList.contains('k-cell')?' 第'+(+el.dataset.row+1)+'行'+(+el.dataset.col+1)+'列':''));});
}
/* Imported PPT placeholders are target slots. Keep them separate from the
 * HTML field catalog so the user always sees the direction: PPT target ->
 * current form source. */
function renderTemplateTargets(){
  var box=$('#templateTargets');if(!box)return;
  var page=editablePage()||currentPage();
  var slide=page&&slidesOf().find(function(x){return x.slide_index===page.source;});
  var shapes=(slide&&slide.shapes)||[];
  var targets=shapes.filter(function(sh){return (sh.placeholder_paths||[]).length;});
  if(!targets.length){box.hidden=true;box.innerHTML='';return;}
  var bindings=(page&&page.bindings)||{};
  function boundFor(sh){
    return Object.keys(bindings).map(function(k){return bindings[k];}).filter(function(b){
      return b && ((b.options&&String(b.options.shape_id)===String(sh.shape_id)) ||
        ((!b.options||b.options.shape_id==null) && b.shape===sh.shape_name));
    });
  }
  var rows=targets.map(function(sh){
    var bs=boundFor(sh),paths=sh.placeholder_paths||[];
    var mapped=bs.length?bs.map(function(b){
      if(b.type==='text_replace')return '局部替换 '+((b.options&&b.options.replacements)||[]).length+' 处';
      return b.source||'已绑定';
    }).join('；'):'';
    var pending=!bs.length;
    return '<div class="target-row '+(pending?'pending':'')+'">'
      +'<div style="flex:1"><div><b>'+esc(sh.shape_name)+'</b> <span class="hint">'+esc(sh.kind)+' · ID '+esc(sh.shape_id)+'</span></div>'
      +paths.map(function(p){return '<span class="target-tag">{'+esc(p)+'}</span>';}).join(' ')
      +(mapped?'<div class="hint">当前来源：<span class="mono">'+esc(mapped)+'</span></div>':'<div class="hint">请选择来源表单字段</div>')
      +'</div><span class="target-state">'+(pending?'待绑定':'✓ 已绑定')+'</span>'
      +'<button class="sm target-select" data-shape-id="'+esc(sh.shape_id)+'" data-shape-name="'+esc(sh.shape_name)+'">选择对象</button></div>';
  }).join('');
  box.hidden=false;
  box.innerHTML='<h4>当前 PPT 页的模板目标（'+targets.length+' 个对象）</h4>'
    +'<div class="hint">占位符来自导入的 PPT。它们不会自动映射到固定业务字段，请为每个对象选择当前 HTML 表单字段。</div>'
    +rows;
}
$('#templateTargets').addEventListener('click',function(e){
  var b=e.target.closest('.target-select');if(!b)return;
  var id=b.getAttribute('data-shape-id'),name=b.getAttribute('data-shape-name');
  var el=$$('#canvas .sbox').find(function(x){return String(x.dataset.shapeid)===String(id);})
    ||$$('#canvas .sbox').find(function(x){return x.dataset.name===name;});
  if(!el){toast('该模板目标当前不在画布中，请重新加载模板页');return;}
  selectCanvasObject(el);$('#selBar').scrollIntoView({behavior:'smooth',block:'start'});
});
function syncObjectSelection(key){
  if(!Array.from($('#selObject').options).some(function(o){return o.value===key;})){$('#objectSearch').value='';refreshObjectNavigator();}
  $('#selObject').value=key;
  $$('#canvas .sel').forEach(function(el){el.classList.remove('sel');});
  var el=$('#canvas [data-bindkey="'+CSS.escape(key)+'"]');if(el)el.classList.add('sel');
}
$('#objectSearch').addEventListener('input',refreshObjectNavigator);
$('#btnSelectObject').addEventListener('click',function(){var el=$('#canvas [data-bindkey="'+CSS.escape($('#selObject').value)+'"]');
  if(!el){toast('请先选择对象');return;}selectCanvasObject(el);$('#selBar').scrollIntoView({behavior:'smooth',block:'start'});});
$('#selObject').addEventListener('change',function(){if(this.value)$('#btnSelectObject').click();});
$('#canvas').addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){var el=e.target.closest('.sbox,.k-cell');if(el){e.preventDefault();selectCanvasObject(el);$('#selBar').scrollIntoView({behavior:'smooth',block:'start'});}}});
$('#pageList').addEventListener('click',function(e){var button=e.target.closest('.move-page');if(!button)return;
  rememberBindingDraft();var i=Number(button.dataset.i),to=i+Number(button.dataset.delta),active=currentPage();
  if(to<0||to>=state.deck.length)return;
  var page=state.deck.splice(i,1)[0];state.deck.splice(to,0,page);state.current=state.deck.indexOf(active);persistDeck();renderPageList();});

/* Formula rows preserve existing expressions, with Chinese parameter tokens instead of paths. */
function formulaEntries(){
  var entries=CAT.fields.map(function(f){return {path:f.path,label:f.label};});
  Object.keys(CAT.derived).forEach(function(k){entries.push({path:'derived.'+k,label:CAT.derived[k]});});
  if(FORM_APP==='dfm')Object.keys(formulaExtraFields).forEach(function(path){entries.push({path:path,label:formulaExtraFields[path]});});
  return entries;
}
function initFormulaEditor(existing,draft){
  disposeFormulaPreview();var bar=$('#selBar');bar._formulaBlocks=null;bar._formulaMap=null;
  if($('#selBindType').value!=='formula')return;
  var expression=existing&&existing.options?existing.options.template||'':'';
  if(draft)expression=draft.template||expression;
  bar._formulaMap=draft&&draft.map?draft.map:UX.aliases(formulaEntries(),expression);
  try{bar._formulaBlocks=draft&&draft.blocks?draft.blocks:UX.parseFormula(UX.toHuman(expression,bar._formulaMap));}
  catch(e){$('#formulaEditor').innerHTML='<p class="bad">'+esc(e.message)+'。原绑定仍保留，请先修复来源公式。</p>';return;}
  $('#formulaEditor').innerHTML='<h3>公式编辑器</h3><p class="hint">点击文字、分子或分母，将中文参数插入光标处。数值来自表单和现有计算结果，此处只编排公式显示。</p>'
    +'<label for="formulaSearch">查找参数</label><input type="text" id="formulaSearch" placeholder="如：投影面积、铸造压力、锁模力">'
    +'<div class="object-toolbar"><select id="formulaField" aria-label="公式参数"></select><button id="btnInsertFormulaField">插入参数</button></div>'
    +'<div class="formula-tools" id="formulaOperators"></div><div id="formulaBlocks"></div>'
    +'<div class="formula-tools"><button id="btnFormulaText">添加文字段</button><button id="btnFormulaFraction">添加分式</button></div>'
    +'<label>当前数据的公式预览</label><img id="formulaPreviewImage" alt="代入当前数据后的公式" hidden><p class="hint" id="formulaStatus" role="status"></p>';
  $('#formulaSearch').addEventListener('input',renderFormulaFields);
  $('#btnInsertFormulaField').addEventListener('click',function(){insertFormulaField($('#formulaField').value);});
  ['+','−','×','÷','=','≥','(',')','²','°'].forEach(function(op){var b=document.createElement('button');b.type='button';b.textContent=op;b.setAttribute('aria-label','插入运算符 '+op);b.onclick=function(){insertFormulaText(op);};$('#formulaOperators').appendChild(b);});
  $('#btnFormulaText').onclick=function(){bar._formulaBlocks.push({kind:'text',text:''});renderFormulaBlocks();markBindingDirty();};
  $('#btnFormulaFraction').onclick=function(){bar._formulaBlocks.push({kind:'fraction',numerator:'',denominator:'10'});renderFormulaBlocks();markBindingDirty();};
  renderFormulaFields();renderFormulaBlocks();
}
function renderFormulaFields(){
  var bar=$('#selBar'),q=$('#formulaSearch').value.toLowerCase();
  $('#formulaField').innerHTML=Object.keys(bar._formulaMap.paths).filter(function(p){return bar._formulaMap.paths[p].toLowerCase().includes(q);})
    .map(function(p){return '<option value="'+esc(p)+'">'+esc(bar._formulaMap.paths[p])+'</option>';}).join('')||'<option value="">没有匹配参数</option>';
}
function renderFormulaBlocks(){
  var bar=$('#selBar'),blocks=bar._formulaBlocks;bar._formulaTarget=null;
  $('#formulaBlocks').innerHTML=blocks.map(function(b,i){
    function area(key,label){return '<label>'+label+'<textarea class="formula-input" data-block="'+i+'" data-part="'+key+'" aria-label="第'+(i+1)+'段'+label+'">'+esc(b[key])+'</textarea></label>';}
    return '<div class="formula-block"><div class="block-actions"><strong>第 '+(i+1)+' 段 · '+(b.kind==='text'?'文字与参数':'分式')+'</strong>'
      +'<button class="sm" data-formula-move="'+i+'" data-delta="-1" '+(i===0?'disabled':'')+'>上移</button>'
      +'<button class="sm" data-formula-remove="'+i+'" '+(blocks.length===1?'disabled':'')+'>移除</button></div>'
      +(b.kind==='text'?area('text','文字'):area('numerator','分子')+area('denominator','分母'))+'</div>';
  }).join('');
  $$('#formulaBlocks textarea').forEach(function(el){el.value=blocks[+el.dataset.block][el.dataset.part];
    el.onfocus=function(){bar._formulaTarget=this;};el.oninput=function(){blocks[+this.dataset.block][this.dataset.part]=this.value;queueFormulaPreview();};});
  $$('#formulaBlocks [data-formula-remove]').forEach(function(b){b.onclick=function(){blocks.splice(+this.dataset.formulaRemove,1);renderFormulaBlocks();markBindingDirty();};});
  $$('#formulaBlocks [data-formula-move]').forEach(function(b){b.onclick=function(){var i=+this.dataset.formulaMove;var block=blocks.splice(i,1)[0];blocks.splice(i-1,0,block);renderFormulaBlocks();markBindingDirty();};});
  queueFormulaPreview();
}
function formulaCode(){
  var bar=$('#selBar');if(!bar._formulaBlocks)throw new Error('公式尚未加载');
  var code=UX.toCode(UX.serializeFormula(bar._formulaBlocks),bar._formulaMap);
  if(!code.trim())throw new Error('请添加文字或公式参数');return code;
}
function insertFormulaField(path){
  var map=$('#selBar')._formulaMap;if(!map||!map.paths[path]){toast('请选择公式参数列表中的字段');return;}
  insertFormulaText('【'+map.paths[path]+'】');
}
function insertFormulaText(text){
  var bar=$('#selBar'),el=bar._formulaTarget;
  if(!el||!el.isConnected)el=$('#formulaBlocks textarea');if(!el)return;
  var start=el.selectionStart,end=el.selectionEnd;el.value=el.value.slice(0,start)+text+el.value.slice(end);
  bar._formulaBlocks[+el.dataset.block][el.dataset.part]=el.value;el.focus();el.setSelectionRange(start+text.length,start+text.length);
  markBindingDirty();queueFormulaPreview();
}
function disposeFormulaPreview(){
  var bar=$('#selBar');clearTimeout(bar._formulaTimer);bar._formulaVersion=(bar._formulaVersion||0)+1;
  if(bar._formulaAbort)bar._formulaAbort.abort();if(bar._formulaUrl)URL.revokeObjectURL(bar._formulaUrl);bar._formulaUrl=null;
}
function queueFormulaPreview(){
  var bar=$('#selBar');disposeFormulaPreview();var token=bar._formulaVersion,status=$('#formulaStatus');
  if(!status)return;$('#formulaPreviewImage').hidden=true;
  var expression;try{expression=formulaCode();$('#inpDisplayTemplate').value=expression;}catch(e){status.textContent=e.message;return;}
  status.textContent='正在更新公式预览…';var controller=new AbortController();bar._formulaAbort=controller;
  bar._formulaTimer=setTimeout(async function(){try{
    var res=await api('/api/template/formula-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expression:expression,data:state.data||{}}),signal:controller.signal});
    var blob=await res.blob();if(bar._formulaVersion!==token)return;
    bar._formulaUrl=URL.createObjectURL(blob);$('#formulaPreviewImage').src=bar._formulaUrl;$('#formulaPreviewImage').hidden=false;
    var missing=Number(res.headers.get('x-dfm-formula-missing'))||0;
    status.textContent=missing?'有 '+missing+' 个参数未填写，请补齐数据后生成。':'预览已更新 · 保存绑定后应用到当前 PPT 对象。';
  }catch(e){if(e.name!=='AbortError'&&bar._formulaVersion===token)status.textContent='公式预览失败：'+e.message;}},250);
}
function saveFormulaBinding(info){
  var expression;try{expression=formulaCode();}catch(e){toast(e.message);return;}
  var existing=currentPage().bindings[info.key],options=UX.copy(existing&&existing.options||{});
  options.shape_id=info.shape_id;options.template=expression;
  currentPage().bindings[info.key]={type:'formula',source:'f',shape:info.name,required:existing?existing.required!==false:true,options:options};
  clearBindingDraft(info);persistDeck();renderPageList();renderPage();showSelBar(info);syncObjectSelection(info.key);
  toast('公式绑定已保存，正在更新当前页预览');
}

/* Reuse a single saved-scheme page. Browsing never changes the current report. */
var reuseState={version:0,record:null,page:null,meta:null,previewUrl:null};
async function fetchTemplateMeta(template){
  var request={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({template:template})};
  var values=await Promise.all([api('/api/template/inspect',request).then(function(r){return r.json();}),api('/api/template/scan',request).then(function(r){return r.json();})]);
  return {inspect:values[0],scan:values[1]};
}
function invalidateReuse(){reuseState.version++;reuseState.page=null;reuseState.meta=null;$('#btnConfirmReuse').disabled=true;
  if(reuseState.controller)reuseState.controller.abort();if(reuseState.previewUrl)URL.revokeObjectURL(reuseState.previewUrl);reuseState.previewUrl=null;$('#reusePreviewImage').hidden=true;}
$('#btnReusePage').onclick=async function(){
  rememberBindingDraft();invalidateReuse();$('#reusePageDialog').showModal();$('#reuseStatus').textContent='正在加载已保存方案…';
  $('#reuseScheme').innerHTML='';$('#reuseSlide').innerHTML='';$('#reuseDetails').textContent='';var version=reuseState.version;
  try{var response=await (await api('/api/schemes')).json();if(version!==reuseState.version)return;
    $('#reuseScheme').innerHTML=response.schemes.map(function(s){return '<option value="'+esc(s.name)+'">'+esc(s.name)+'（'+s.slide_count+' 页）</option>';}).join('');
    if(!response.schemes.length){$('#reuseStatus').textContent='暂无已保存方案。请先保存一个包含绑定的方案。';return;}
    var other=response.schemes.find(function(s){return s.name!==$('#inpSchemeName').value.trim();});if(other)$('#reuseScheme').value=other.name;
    await loadReuseScheme();
  }catch(e){$('#reuseStatus').textContent='无法加载方案：'+e.message;}
};
$('#btnCloseReuse').onclick=function(){$('#reusePageDialog').close();};
$('#reusePageDialog').addEventListener('close',invalidateReuse);
$('#reuseScheme').onchange=loadReuseScheme;
async function loadReuseScheme(){
  invalidateReuse();var version=reuseState.version;$('#reuseSlide').innerHTML='';$('#reuseStatus').textContent='正在读取方案页面…';
  try{var record=await (await api('/api/schemes/'+encodeURIComponent($('#reuseScheme').value))).json();if(version!==reuseState.version)return;
    reuseState.record=record;var pages=record.deck.slides||[];
    $('#reuseSlide').innerHTML=pages.map(function(p,i){return '<option value="'+i+'">方案第 '+(i+1)+' 页 · '+esc(p.template||record.template)+' / 原第 '+p.source+' 页</option>';}).join('');
    if(!pages.length){$('#reuseStatus').textContent='该方案没有可复用页面。';return;}await loadReusePage();
  }catch(e){if(version===reuseState.version)$('#reuseStatus').textContent='读取方案失败：'+e.message;}
}
$('#reuseSlide').onchange=loadReusePage;
async function loadReusePage(){
  invalidateReuse();var version=reuseState.version,record=reuseState.record;
  var page=UX.copy(record.deck.slides[Number($('#reuseSlide').value)]);page.template=page.template||record.template;
  $('#reuseStatus').textContent='正在加载这一页…';
  $('#reuseDetails').textContent=Object.keys(page.bindings||{}).length+' 处绑定'+(page.repeat?' · 含重复规则':'')+(page.condition?' · 含显示条件':'')+'，将全部复制。';
  try{var meta=await fetchTemplateMeta(page.template);if(version!==reuseState.version)return;
    if(!meta.inspect.slides.some(function(s){return s.slide_index===page.source;}))throw new Error('来源模板中已不存在该页');
    reuseState.page=page;reuseState.meta=meta;$('#btnConfirmReuse').disabled=false;
    if(state.inspect&&(state.inspect.slide_width!==meta.inspect.slide_width||state.inspect.slide_height!==meta.inspect.slide_height))$('#reuseDetails').textContent+=' 注意：来源页面尺寸与当前模板不同，导出后请核对版式。';
    var controller=new AbortController();reuseState.controller=controller;
    var res=await api('/api/template/live-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({template:page.template,slide:page,data:state.data||{}}),signal:controller.signal});
    var blob=await res.blob();if(version!==reuseState.version)return;
    reuseState.previewUrl=URL.createObjectURL(blob);$('#reusePreviewImage').src=reuseState.previewUrl;$('#reusePreviewImage').hidden=false;
    var missing=Number(res.headers.get('x-dfm-preview-skipped'))||0;
    $('#reuseStatus').textContent='来源页绑定 + 当前数据的预览'+(missing?' · '+missing+' 处未填写，保留原内容':'');
  }catch(e){if(version!==reuseState.version||e.name==='AbortError')return;$('#reuseStatus').textContent='预览不可用：'+e.message+(reuseState.page?'。仍可插入并继续编辑。':'');}
}
$('#btnConfirmReuse').onclick=function(){
  if(!reuseState.page||!reuseState.meta)return;
  rememberBindingDraft();var page=normalizeDeckPage(UX.copy(reuseState.page)),meta=reuseState.meta;
  var index=$('#reusePosition').value==='end'?state.deck.length:Math.min(state.deck.length,state.current+1);
  state.deck=UX.insertPage(state.deck,page,index);state.current=index;
  if(!state.baseTemplate)state.baseTemplate=page.template;
  state.template=page.template;state.inspect=meta.inspect;state.scan=meta.scan;state.previewSource=page.source;state.previewVersion=Date.now();
  if(!Array.from($('#selTemplate').options).some(function(o){return o.value===page.template;}))$('#selTemplate').add(new Option(page.template,page.template));
  $('#selTemplate').value=page.template;
  $('#selPageNo').innerHTML=slidesOf().map(function(s){return '<option value="'+s.slide_index+'">第 '+s.slide_index+' 页（'+s.shapes.length+' 对象）</option>';}).join('');
  $('#tplHint').textContent='当前查看模板 '+page.template+'，共 '+meta.inspect.slide_count+' 页';
  $('#reusePageDialog').close();persistDeck();renderPageList();renderPage();renderFieldHint();
  toast('已插入独立页面副本，来源方案不变；请保存当前方案。');
};
