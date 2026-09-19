// ===== DEFAULTS =====
var D={mdb:[],tdb:[],pr:[],is:[],fdb:[],idb:[],vh:[]};

var MDB=[],TDB=[],PR=[],IS=[],IDB=[],VH=[],toolGrp='all',toolCat='',G={cust:"",part:"",hpd:0,sft:0,dpm:0,avl:0,pI:null,pf:null,len:0,wid:0,hgt:0,wgt:0,showFlow:1,bInspType:"",bInspImg:null,fInspType:"",fInspImg:null,bInspPrice:0,fInspPrice:0,msInspPrice:0,custVer:"",dfmDate:"",prj:"hp",insp:[],fixQ:[],fixQC:[],inspQ:[],icnX:[],fcnX:[],lang:"zh"};
function dc(o){return JSON.parse(JSON.stringify(o))}
var ICN=[];
function inspByKey(k){if(!k)return null;var a=String(k).split('|');if(a.length<3)return null;for(var i=0;i<IDB.length;i++){if((IDB[i].type||'')===a[0]&&(IDB[i].name||'')===a[1]&&(IDB[i].drw||'')===a[2])return IDB[i];}return null;}
function iqEsc(s){return String(s==null?'':s).split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;').split('"').join('&quot;');}
function iqFilter(k){var pk='',sk='';var pe=document.getElementById('iqP'+k);if(pe)pk=(pe.value||'').toLowerCase();var se=document.getElementById('iqS'+k);if(se)sk=(se.value||'').toLowerCase();var box=document.getElementById('iqL'+k);if(!box)return;var IC=inspClasses();var ct=IC[k]||'';var cur=(G.insp&&G.insp[k])||'';if(!pk&&!sk){box.innerHTML='';return;}var n=0,h='';for(var i=0;i<IDB.length;i++){var it=IDB[i];if((it.type||'')!==ct)continue;var pp=String(it.prdSize||'').toLowerCase();var ss=String(it.inspSize||'').toLowerCase();if(pk&&(!pp||(pp.indexOf(pk)<0&&pk.indexOf(pp)<0)))continue;if(sk&&(!ss||(ss.indexOf(sk)<0&&sk.indexOf(ss)<0)))continue;var kk=(it.type||'')+'|'+(it.name||'')+'|'+(it.drw||'');var lb=(it.prdSize||'-')+' / '+(it.inspSize||'-')+'  '+(it.name||'')+'  ('+(it.price||0)+'万)';h+='<div class="iqcand'+(kk===cur?' on':'')+'" data-i="'+k+'" data-k="'+iqEsc(kk)+'" onclick="setInspSel2(this)">'+iqEsc(lb)+'</div>';n++;if(n>=50)break;}box.innerHTML=n?h:'<div class="iqnone">'+TR('无匹配')+'</div>';}
function setInspSel(k,v){if(spOn()){SelectionPage.setSelection('gauge',k,v);return;}G.insp[k]=v;save();var e=inspByKey(v);var q=document.getElementById('iqQ'+k),d2=document.getElementById('iqD'+k),m2=document.getElementById('iqM'+k);if(q)q.textContent=(e?(e.price||0):'-');if(d2)d2.textContent=(e?(e.dc||0):'-');if(m2)m2.textContent=(e?(e.mc||0):'-');var n=0,t=0,dsc=[];for(var q2=0;q2<inspClasses().length;q2++){if(G.inspQ&&!G.inspQ[q2])continue;var ee=inspByKey((G.insp&&G.insp[q2])||'');if(ee){n++;t+=(ee.price||0);dsc.push(inspClasses()[q2]+'(产品'+(ee.prdSize||'-')+'/检具'+(ee.inspSize||'-')+') '+f(ee.price||0,2)+'万');}}var el2=document.getElementById('inspCostLine');if(el2)el2.innerHTML='<b>'+TR('检具价格（检具库选型报价）：')+'</b>'+n+' / '+inspClasses().length+' '+TR('类')+' · <b>'+f(t,2)+' 万¥</b>'+(dsc.length?'（'+dsc.join('；')+')':'');}
var GLBL={"cust":"客户","part":"零件号","hpd":"每月工作日","sft":"班次","dpm":"每月天数","avl":"稼动率","pI":"产品图片","pf":"产品图片2","len":"长度","wid":"宽度","hgt":"高度","wgt":"重量","showFlow":"流程图显示","bInspType":"毛坯检具类型","bInspImg":"毛坯检具图片","fInspType":"成品检具类型","fInspImg":"成品检具图片","bInspPrice":"毛坯检具价格","fInspPrice":"成品检具价格","msInspPrice":"测量支架价格","custVer":"客户版本","dfmDate":"DFM完成时间","prj":"项目","insp":"检具选型"};
function snapG(){var o={_pr:PR.length};for(var k in G){if(k==='_vSnap'||k==='lang'||k==='pI'||k==='pf'||k==='bInspImg'||k==='fInspImg')continue;o[k]=JSON.stringify(G[k]);}return o;}
function verRec(ov,nv){var d=new Date();var dt=d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+d.getDate()).slice(-2);var lines=[];var snap=G._vSnap;if(snap){for(var k in snap){if(k==='_pr'){if(snap[k]!==PR.length)lines.push('工序数: '+snap[k]+' → '+PR.length);continue;}if(!(k in G)){lines.push((GLBL[k]||k)+': '+snap[k]+' → (已删除)');continue;}var nvv=JSON.stringify(G[k]);if(nvv!==snap[k]){var so=(snap[k]==='""'||snap[k]===undefined)?'(空)':snap[k];var sn=(nvv==='""')?'(空)':nvv;lines.push((GLBL[k]||k)+': '+so+' → '+sn);}}for(var k2 in G){if(k2==='_vSnap'||k2==='lang'||k2==='pI'||k2==='pf'||k2==='bInspImg'||k2==='fInspImg')continue;if(!(k2 in snap))lines.push((GLBL[k2]||k2)+': (新增) '+JSON.stringify(G[k2]));}}var _rec={dt:dt,ver:nv||'(未命名)',ds:'客户版本切换: '+(ov||'(空)')+' → '+(nv||'(空)')+(lines.length?'；自动导入变更内容: '+lines.join('；'):'；未检出参数变更'),by:'自动'};if(typeof HistoryPage!=='undefined'&&HistoryPage.enabled()){HistoryPage.add(_rec);}else{VH.push(_rec);}G._vSnap=snapG();}
var FDB=[];
var FCN=[];
function fixByKey(k){if(!k)return null;var a=String(k).split('|');if(a.length<2)return null;var nm=a.slice(1).join('|');for(var i=0;i<FDB.length;i++){if((FDB[i].center||'')===a[0]&&(FDB[i].name||'')===nm)return FDB[i];}return null;}
function fixFilter(k){var sel=document.getElementById('fqSel'+k);if(!sel)return;var FC=fixClasses();var cur=(G.fixQ&&G.fixQ[k])||'';var opts='<option value="">— '+TR('未选型')+' —</option>';var n=0;for(var i=0;i<FDB.length;i++){var it=FDB[i];if((it.center||'')!==FC[k])continue;var kk=(it.center||'')+'|'+(it.name||'');var lb=(it.name||'-')+'  (¥'+f(it.price||0,0)+')';opts+='<option value="'+iqEsc(kk)+'"'+(kk===cur?' selected':'')+'>'+iqEsc(lb)+'</option>';n++;if(n>=300)break;}sel.innerHTML=opts;}
function setFixSel(k,v){if(spOn()){SelectionPage.setSelection('fixture',k,v);return;}G.fixQ[k]=v;save();var e=fixByKey(v);var q=document.getElementById('fqP'+k);if(q)q.textContent=(e?(e.price||0):'-');var n=0,t=0;for(var q2=0;q2<fixClasses().length;q2++){if(G.fixQC&&!G.fixQC[q2])continue;var ee=fixByKey((G.fixQ&&G.fixQ[q2])||'');if(ee){n++;t+=(ee.price||0);}}var el2=document.getElementById('fixCostLine');if(el2)el2.innerHTML='<b>'+TR('夹具价格（夹具库选型报价）：')+'</b>'+n+' / '+fixClasses().length+' '+TR('中心')+' · <b>¥'+f(t,1)+'</b>';}
function fixQuoteTable(){var FC=fixClasses();var h='<div class="card"><div class="card-hd"><h2>'+TR('夹具报价选型')+'</h2></div><div class="card-bd">';h+='<div class="tbw"><table><thead><tr><th>'+TR('模具中心')+'</th><th>'+TR('是否报价')+'</th><th>'+TR('夹具选型')+'</th><th>'+TR('价格(¥)')+'</th></tr></thead><tbody>';for(var k=0;k<FC.length;k++){var sel=(G.fixQ&&G.fixQ[k])||'';var e=fixByKey(sel);var qc=(G.fixQC&&G.fixQC[k])!==0;h+='<tr><td>'+FC[k]+'</td><td style="text-align:center"><input type="checkbox"'+(qc?' checked':'')+' onchange="'+fxQuoteCall(k)+'"></td><td><select class="txt" id="fqSel'+k+'" style="width:320px" onchange="setFixSel('+k+',this.value)"></select></td><td id="fqP'+k+'">'+(e?(e.price||0):'-')+'</td></tr>';}h+='</tbody></table></div></div></div>';return h;}function init(){MDB=dc(D.mdb);TDB=dc(D.tdb);PR=dc(D.pr);IS=dc(D.is);FDB=dc(D.fdb||[]);IDB=dc(D.idb||[]);VH=dc(D.vh||[]);for(var _fb0=0;_fb0<FDB.length;_fb0++){if(!('mc' in FDB[_fb0]))FDB[_fb0].mc=0;if(!('rmk' in FDB[_fb0]))FDB[_fb0].rmk='';if(!('img' in FDB[_fb0]))FDB[_fb0].img=null;}G={cust:"",part:"",hpd:0,sft:0,dpm:0,avl:0,pI:null,pf:null,len:0,wid:0,hgt:0,wgt:0,showFlow:1,bInspType:"",bInspImg:null,fInspType:"",fInspImg:null,bInspPrice:0,fInspPrice:0,msInspPrice:0,custVer:"",dfmDate:"",prj:"hp",insp:[],fixQ:[],fixQC:[],inspQ:[],icnX:[],fcnX:[],lang:"zh"};for(var p=0;p<PR.length;p++){if(!('fixP' in PR[p]))PR[p].fixP=0;if(!('eqP' in PR[p]))PR[p].eqP=0;for(var w=0;w<PR[p].tl.length;w++){if(!('cat' in PR[p].tl[w]))PR[p].tl[w].cat='other';PR[p].tl[w].cat=migCat(PR[p].tl[w].cat,PR[p].tl[w].tp);if(!('hld' in PR[p].tl[w]))PR[p].tl[w].hld='';if(!('acc' in PR[p].tl[w]))PR[p].tl[w].acc='';}}for(var i=0;i<MDB.length;i++){if(!('img' in MDB[i]))MDB[i].img=null;if(!('doc' in MDB[i]))MDB[i].doc=null;if(!('docName' in MDB[i]))MDB[i].docName='';if(!('xyz' in MDB[i]))MDB[i].xyz='';if(!('pa' in MDB[i]))MDB[i].pa='';if(!('rpa' in MDB[i]))MDB[i].rpa='';if(!('price' in MDB[i]))MDB[i].price=0;}for(var j=0;j<TDB.length;j++){if(!('tI' in TDB[j]))TDB[j].tI='';if(!('life' in TDB[j]))TDB[j].life=0;if(!('price' in TDB[j]))TDB[j].price=0;if(!('grp' in TDB[j]))TDB[j].grp='hp';if(!('ln' in TDB[j]))TDB[j].ln=0;TDB[j].cat=migCat(TDB[j].cat,TDB[j].tp);}}

// Clipboard paste
document.addEventListener('paste',function(e){var it=e.clipboardData&&e.clipboardData.items;if(!it)return;for(var i=0;i<it.length;i++){if(it[i].type.indexOf('image')!==-1){var b=it[i].getAsFile();var r=new FileReader();r.onload=function(ev){var cb0=window._icb;imgShrink(ev.target.result,function(u){if(cb0)cb0(u);});window._icb=null;var ht=document.getElementById('pasteHint');if(ht)ht.style.display='none';};r.readAsDataURL(b);e.preventDefault();return;}}});

// Load
var ld=false;
function applyData(d){
  if(d.mdb&&d.mdb.length>0)MDB=d.mdb;else MDB=dc(D.mdb);
  if(d.tdb&&d.tdb.length>0)TDB=d.tdb;else TDB=dc(D.tdb);
  if(d.pr&&d.pr.length>0)PR=d.pr;else PR=dc(D.pr);
  if(d.is&&d.is.length>=0)IS=d.is;else IS=[];
  if(d.fdb&&d.fdb.length>0)FDB=d.fdb;else FDB=dc(D.fdb||[]);
  if(d.idb)IDB=d.idb;else IDB=dc(D.idb||[]);
  if(d.vh)VH=d.vh;else VH=dc(D.vh||[]);for(var _fb=0;_fb<FDB.length;_fb++){if(!('mc' in FDB[_fb]))FDB[_fb].mc=0;if(!('rmk' in FDB[_fb]))FDB[_fb].rmk='';if(!('img' in FDB[_fb]))FDB[_fb].img=null;}
  if(d.G)for(var k in d.G)G[k]=d.G[k];if(!G.icnX)G.icnX=[];if(!G.fcnX)G.fcnX=[];
  for(var p=0;p<PR.length;p++){if(!('fixP' in PR[p]))PR[p].fixP=0;if(!('eqP' in PR[p]))PR[p].eqP=0;for(var w=0;w<PR[p].tl.length;w++){if(!('cat' in PR[p].tl[w]))PR[p].tl[w].cat='other';PR[p].tl[w].cat=migCat(PR[p].tl[w].cat,PR[p].tl[w].tp);if(!('hld' in PR[p].tl[w]))PR[p].tl[w].hld='';if(!('acc' in PR[p].tl[w]))PR[p].tl[w].acc='';}}for(var i=0;i<MDB.length;i++){if(!('img' in MDB[i]))MDB[i].img=null;if(!('doc' in MDB[i]))MDB[i].doc=null;if(!('docName' in MDB[i]))MDB[i].docName='';if(!('xyz' in MDB[i]))MDB[i].xyz='';if(!('pa' in MDB[i]))MDB[i].pa='';if(!('rpa' in MDB[i]))MDB[i].rpa='';if(!('price' in MDB[i]))MDB[i].price=0;}for(var j=0;j<TDB.length;j++){if(!('tI' in TDB[j]))TDB[j].tI='';if(!('life' in TDB[j]))TDB[j].life=0;if(!('price' in TDB[j]))TDB[j].price=0;if(!('grp' in TDB[j]))TDB[j].grp='hp';if(!('ln' in TDB[j]))TDB[j].ln=0;TDB[j].cat=migCat(TDB[j].cat,TDB[j].tp);}
  ['len','wid','hgt','wgt','showFlow'].forEach(function(k){if(!(k in G))G[k]=(k==='showFlow'?1:0);});['bInspType','fInspType','custVer','dfmDate'].forEach(function(k){if(!(k in G))G[k]='';});['bInspImg','fInspImg'].forEach(function(k){if(!(k in G))G[k]=null;});['bInspPrice','fInspPrice','msInspPrice'].forEach(function(k){if(!(k in G))G[k]=0;});
  if(!G.fixQ||G.fixQ.length<4)G.fixQ=["","","",""];while(G.fixQ.length<fixClasses().length)G.fixQ.push('');if(!G.fixQC||G.fixQC.length<4)G.fixQC=[1,1,1,1];while(G.fixQC.length<fixClasses().length)G.fixQC.push(1);if(!G.inspQ||G.inspQ.length<5)G.inspQ=[1,1,1,1,1];while(G.inspQ.length<inspClasses().length)G.inspQ.push(1);if(!G.insp)G.insp=["","","",""];else{while(G.insp.length<5)G.insp.push('');for(var _mi=0;_mi<inspClasses().length;_mi++){var _mv=G.insp[_mi];if(_mv&&String(_mv).indexOf('|')<0){var _me=null;for(var _mj=0;_mj<IDB.length;_mj++){if((IDB[_mj].name||'')===_mv&&(!_me||(IDB[_mj].type||'')===inspClasses()[_mi]))_me=IDB[_mj];}G.insp[_mi]=_me?((_me.type||'')+'|'+(_me.name||'')+'|'+(_me.drw||'')):'';}}}if(!('lang' in G))G.lang='zh';if(!G._vSnap)G._vSnap=snapG();
}
init();
function save(){if(window.MachiningDFMHost)window.MachiningDFMHost.scheduleSave();}
// 设备/夹具/检具图片现在存服务端文件、表里只有 URL；**导出 JSON 备份与 PPT** 前
// 统一换成 data URL，保证导出文件离线也能显示图片。
// （导出文件包走另一条路：服务端直接发原图字节，见下面的 exportPackage()，不需要内联。）
var _assetCache={};
function assetToDataUrl(src){
  if(!src||typeof src!=='string')return Promise.resolve(src||null);
  if(src.indexOf('data:')===0)return Promise.resolve(src);
  if(src.indexOf('/api/machining-dfm/assets/')<0)return Promise.resolve(src);
  if(_assetCache[src])return _assetCache[src];
  _assetCache[src]=fetch(src,{cache:'force-cache'}).then(function(r){if(!r.ok)throw new Error('附件读取失败');return r.blob();}).then(function(b){return new Promise(function(res,rej){var fr=new FileReader();fr.onload=function(){res(fr.result);};fr.onerror=function(){rej(new Error('附件读取失败'));};fr.readAsDataURL(b);});}).catch(function(){return null;});
  return _assetCache[src];
}
function inlineSheetImages(){
  var jobs=[];
  function slot(get,set){var v=get();if(v&&typeof v==='string'&&v.indexOf('/api/machining-dfm/assets/')===0)jobs.push(assetToDataUrl(v).then(function(u){if(u)set(u);}));}
  // 四个基础库的图片字段都叫 img（设备/刀具/夹具/检具）——阶段 1b~2b 起都是附件引用
  [MDB,TDB,FDB,IDB].forEach(function(list){for(var i=0;i<list.length;i++){(function(row){slot(function(){return row.img;},function(u){row.img=u;});})(list[i]);}});
  // 项目信息四张图：产品图 pI、产品图2 pf、毛坯检具图 bInspImg、成品检具图 fInspImg
  ['pI','pf','bInspImg','fInspImg'].forEach(function(k){slot(function(){return G[k];},function(u){G[k]=u;});});
  // 工序夹具示意图 cI
  for(var p=0;p<PR.length;p++){(function(row){slot(function(){return row.cI;},function(u){row.cI=u;});})(PR[p]);}
  // 问题清单优化前/后 bI / aI
  for(var q=0;q<IS.length;q++){(function(row){slot(function(){return row.bI;},function(u){row.bI=u;});slot(function(){return row.aI;},function(u){row.aI=u;});})(IS[q]);}
  return Promise.all(jobs);
}
// ---------------- 导出文件包（zip，阶段 5 · 口径 §7.0） ----------------
// 便携单文件 HTML 已退休（index.html 里本来就没有 DATA_MARKER，那条路早就出不了文件），
// 导出改成两条能兑现的路：下面这条「文件包」由**服务端**按需出包
// （GET /api/machining-dfm/projects/{id}/export.zip，只读）：包里是 project.json（读模型，
// 附件字段换成包内相对路径 assets/<id>.<ext>）+ 本项目真引用到的原图 + README.txt。
// 所以这里不内联图片、**不保存也不改任何数据**：只发一个 GET，取的是服务端当前已保存版本。
function dlBlob(blob,nm){var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=nm;document.body.appendChild(a);a.click();document.body.removeChild(a);setTimeout(function(){try{URL.revokeObjectURL(a.href);}catch(e){}},3000);}
// 文件名以服务端 Content-Disposition 为准（DFM_<项目名>.zip，中文项目名走 filename*）
function packageFileName(r){try{var cd=(r.headers&&r.headers.get)?String(r.headers.get('content-disposition')||''):'';var m=/filename\*=UTF-8''([^;]+)/i.exec(cd);if(m)return decodeURIComponent(m[1].trim());var m2=/filename="?([^";]+)"?/i.exec(cd);if(m2)return m2[1].trim();}catch(e){}return '';}
function exportPackage(){
  var p=(window.MachiningDFMHost&&window.MachiningDFMHost.current)?window.MachiningDFMHost.current():null;
  if(!p||!p.id){alert(TR('还没有服务端项目，无法导出文件包'));return;}
  var url='/api/machining-dfm/projects/'+encodeURIComponent(p.id)+'/export.zip';
  fetch(url,{cache:'no-store'}).then(function(r){
    if(!r.ok)throw new Error('文件包导出失败（HTTP '+r.status+'）');
    var nm=packageFileName(r)||('DFM_'+String(G.part||'project').replace(/\s/g,'_')+'.zip');
    return r.blob().then(function(b){dlBlob(b,nm);});
  }).catch(function(e){alert(TR('导出失败：')+(e&&e.message||e));});
}
function usedParts(grp){var list=[],seenP={};for(var p=0;p<PR.length;p++){var pr=PR[p],m2={};for(var i=0;i<pr.tl.length;i++){var t2=pr.tl[i],nm=(grp==='hld')?t2.hld:t2.acc;if(!nm)continue;if(m2[nm]){m2[nm].q++;continue;}var hp=0,hl=0;for(var j=0;j<TDB.length;j++){if((TDB[j].grp||'hp')===grp&&TDB[j].tp===nm){hp=TDB[j].price||0;hl=TDB[j].life||0;break;}}var rec={pn:pr.nm,tp:nm,price:hp,life:hl,q:1};m2[nm]=rec;list.push(rec);}}var sum=0,qty=0;for(var k=0;k<list.length;k++){sum+=list[k].price*list[k].q;qty+=list[k].q;}return{n:list.length,total:sum,qty:qty,list:list};}
function usedHld(){return usedParts('hld');}
// 导出数据备份(JSON)：**单文件、图片内联**（离线打开也有图），便于他人「导入数据(.json)」恢复。
// 「数据保存与导出」卡片里的「导出 JSON（单文件·图内联）」按钮走这里。
function exportData(){
  inlineSheetImages().then(function(){
  var st={mdb:dc(MDB),tdb:dc(TDB),pr:dc(PR),is:dc(IS),fdb:dc(FDB),idb:dc(IDB),vh:dc(VH),G:dc(G)};
  var blob=new Blob([JSON.stringify(st)],{type:'application/json'});
  var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='DFM_Data_'+G.part.replace(/\s/g,'_')+'.json';
  document.body.appendChild(a);a.click();document.body.removeChild(a);URL.revokeObjectURL(a.href);
  }).catch(function(e){alert(TR('导出失败：')+(e&&e.message||e));});
}
// 从 JSON 备份导入数据
function importData(){
  var f=document.createElement('input');f.type='file';f.accept='.json,application/json';
  f.onchange=function(e){var file=e.target.files[0];if(!file)return;var r=new FileReader();
    r.onload=function(ev){try{var d=JSON.parse(ev.target.result);applyData(d);render();alert(TR('数据导入成功，已覆盖当前数据!'));}catch(err){alert(TR('文件格式错误，请选择导出的 JSON 数据文件。'));}};
    r.readAsText(file);};
  f.click();
}
function resetData(){if(!confirm('Reset all data?'))return;init();curTab=0;render();}
var dbUnl=false,adUnl=false;
function checkPwd(){return window.MachiningDFMHost?window.MachiningDFMHost.requireRole('process'):false;}
function checkAdm(){return window.MachiningDFMHost?window.MachiningDFMHost.requireRole('admin'):false;}
function setGo(){if(checkPwd()){curTab=SI+2;render();}}
function inspQuoteTable(){
  var IC=inspClasses();
  var h='<div class="card"><div class="card-hd"><h2>'+TR('检具报价选型 / Inspection Quoting')+'</h2></div><div class="card-bd"><div class="note" style="margin-bottom:6px">'+TR('按五大类从检具库选型：输入产品尺寸/检具尺寸关键词检索，从匹配结果中选定，价格/设计周期/制造周期直接引用检具库数据，成本信息与导出价格清单同步报价。')+'</div><div class="tbw"><table><thead><tr><th>'+TR('检具类别')+'</th><th>'+TR('是否报价')+'</th><th>'+TR('产品尺寸检索')+'</th><th>'+TR('检具尺寸检索')+'</th><th>'+TR('匹配选型（产品尺寸 / 检具尺寸）')+'</th><th>'+TR('价格(万¥)')+'</th><th>'+TR('设计周期(天)')+'</th><th>'+TR('制造周期(天)')+'</th></tr></thead><tbody>';
  for(var k=0;k<IC.length;k++){
    var sel=(G.insp&&G.insp[k])||'';
    var e=inspByKey(sel);
    var qc=(G.inspQ&&G.inspQ[k])!==0;
    h+='<tr><td>'+IC[k]+'</td><td style="text-align:center"><input type="checkbox"'+(qc?' checked':'')+' onchange="'+iqQuoteCall(k)+'"></td><td><input class="txt" id="iqP'+k+'" style="width:110px" placeholder="'+TR('如 347*326')+'" oninput="iqFilter('+k+')"></td><td><input class="txt" id="iqS'+k+'" style="width:110px" placeholder="'+TR('如 600*400')+'" oninput="iqFilter('+k+')"></td><td><div class="iqlist" id="iqL'+k+'"></div></td><td id="iqQ'+k+'">'+(e?(e.price||0):'-')+'</td><td id="iqD'+k+'">'+(e?(e.dc||0):'-')+'</td><td id="iqM'+k+'">'+(e?(e.mc||0):'-')+'</td></tr>';
  }
  h+='</tbody></table></div></div></div>';
  return h;
}
function lockAdmin(){if(window.MachiningDFMHost)window.MachiningDFMHost.logout();else{dbUnl=false;adUnl=false;curTab=0;render();}}
var LANGCN={zh:'中文',en:'English',th:'ไทย',es:'Español'};
function _wl(n,d,fd){if(!n||!n.childNodes)return;for(var i=0;i<n.childNodes.length;i++){var c=n.childNodes[i];if(c.nodeType===3){var t=(c.nodeValue||'').replace(/^\s+|\s+$/g,'');if(t&&d[t])c.nodeValue=c.nodeValue.replace(t,d[t]);else if(t&&fd&&_cjk(t))c.nodeValue=c.nodeValue.replace(t,_fr(t,fd));}else if(c.nodeType===1&&c.tagName!=='SCRIPT'&&c.tagName!=='STYLE'){if(c.placeholder&&d[c.placeholder])c.placeholder=d[c.placeholder];_wl(c,d,fd);}}}
function applyLang(){var d=I18N[G.lang];if(!d)return;var fd=FRAG[G.lang]||null;var rt=document.getElementById('mainPanels');if(rt)_wl(rt,d,fd);var bb=document.getElementById('tabBar');if(bb)_wl(bb,d,fd);try{var sps=document.querySelectorAll('#tabBar .tab span');for(var i=0;i<sps.length;i++){sps[i].style.display='none';}}catch(e){}}
function setLang(l){G.lang=l||'zh';save();render();}
var I18N={"en":{"项目信息":"Project Info","问题清单":"Issues","版本履历":"Versions","设备库":"Machines","工艺设置":"Settings","刀具库":"Tools","夹具库":"Fixtures","检具库":"Gauges","退出":"Exit","保存":"Save","另存为":"Save As","重置":"Reset","操作":"Action","上传":"Upload","粘贴":"Paste","+图片":"+Image","图片":"Image","名称":"Name","类型":"Type","型号":"Model","未选择":"Not Selected","全部":"All","全部类型":"All Types","库分类":"Library","库分类：":"Library:","版本":"Version","日期":"Date","变更人":"Changed By","变更内容":"Changes","其他":"Others","刀柄":"Holder","配件":"Accessory","国内":"Domestic","进口":"Imported","高压项目":"High-Pressure","差压项目":"Differential","高压项目刀具":"High-Pressure Tools","差压项目刀具":"Differential Tools","毛坯检具":"Blank Gauge","成品机械检具":"Mechanical Gauge","成品总成检具":"Assembly Gauge","成品电子检具":"Electronic Gauge","铣刀":"Mill","钻头":"Drill","丝锥":"Tap","中心钻":"Center Drill","倒角刀":"Chamfer","新检具":"New Gauge","新刀具":"New Tool","新夹具":"New Fixture","新品牌":"New Brand","新设备":"New Machine","新品":"New","⚙ 工艺设置":"⚙ Settings","🔒 管理设置":"🔒 Admin","品牌 Brand":"Brand","型号 Model":"Model","说明 Desc":"Description","图片 Photo":"Photo","快移 Rapid m/min":"Rapid m/min","换刀 TC s":"TC s","转速 RPM":"RPM","刀库 ATC":"ATC","+ 添加刀具 / Add Tool":"+ Add Tool","产品图片 / Product Image":"Product Image","客户与零件 / Customer & Part":"Customer & Part","产品尺寸与重量 / Dimensions":"Dimensions","工艺流程图 / Process Flow":"Process Flow","机加工艺路线 / Machining Process Route":"Machining Process Route","夹具设计 / Fixture Design（与机加工序对应）":"Fixture Design (per process)","节拍产能 / Cycle Time & Capacity":"Cycle Time & Capacity","非加工时间明细 / Non-Cut Details":"Non-Cut Details","夹具示意图 / Fixture Layout":"Fixture Layout","工艺设置 / Settings":"Settings","工序管理 / Process Management":"Process Management","成本信息 / Cost Information":"Cost Information","检具选择 / Inspection Fixtures":"Inspection Fixtures","检具报价选型 / Inspection Quoting":"Inspection Quoting","数据保存与导出 / Save & Export":"Save & Export","公式 / Formulas":"Formulas","设备数据库 / Machine DB":"Machine DB","刀具类型参数库 / Tool Type Library":"Tool Type Library","夹具库 / Fixture Library":"Fixture Library","检具库 / Inspection Tool Library":"Inspection Tool Library","版本变更履历 / Version History":"Version History","问题清单 / Issue List (DFM Format)":"Issue List (DFM Format)","项目类型":"Project Type","日可动时间":"Daily Hours","日班次":"Shifts/Day","月可动日":"Days/Month","可动率":"Availability","客户名称":"Customer","零件名称":"Part Name","客户版本":"Customer Ver.","DFM完成时间":"DFM Date","长度 L":"Length L","宽度 W":"Width W","高度 H":"Height H","重量":"Weight","上传产品图":"Upload Product Image","未上传设备图":"No Machine Image","未上传夹具图":"No Fixture Image","工序":"Process","台":"Mch","件":"pcs","次":"passes","刀号":"Tool No.","刀具型号":"Tool Model","刀柄选型":"Holder","配件选型":"Accessory","加工内容":"Content","加工特征":"Feature","加工节拍":"Cycle Time","切削参数与时间":"Cutting Params & Time","转速n(rpm)":"n (rpm)","进给vf(mm/min)":"vf (mm/min)","每齿进给fz":"fz","线速度Vc":"Vc","长度L(mm)":"L (mm)","寿命(min)":"Life (min)","定位精度":"Positioning Acc.","重复定位精度":"Repeatability","XYZ行程":"XYZ Travel","自定义":"Custom","基本":"Basic","大刀":"Big Tool","辅压紧":"Aux. Clamp","主压紧":"Main Clamp","支撑缸":"Support Cyl.","开门":"Door Open","关门":"Door Close","检测/吹屑":"Check / Blow","快移时":"Rapid T","换刀时":"Tool Change T","转台时":"Index T","主轴延时":"Spindle Delay","总切削":"Total Cutting","总非切削":"Total Non-Cut","总时间":"Total Time","非切削":"Non-Cut","切削:":"Cutting:","非切削(每刀):":"Non-Cut (per tool):","产能:":"Capacity:","节拍:":"Cycle:","月产能(1台)":"Monthly Cap. (1 Mch)","刀具类型：":"Tool Type:","刀具类型":"Tool Type","刀具数":"Tools","刀具总价(¥)":"Tool Cost (¥)","单件刀具成本(¥)":"Tool Cost/pc (¥)","夹具价格(¥)":"Fixture (¥)","设备价格(万¥)":"Machine (×10k ¥)","价格(¥)":"Price (¥)","🔧 刀具系统":"🔧 Tool System","快移距":"Rapid Dist","检具名称":"Gauge Name","检具图号":"Drawing No.","产品尺寸(mm)":"Product Size (mm)","检具尺寸(mm)":"Gauge Size (mm)","价格(万¥)":"Price (×10k ¥)","设计周期(天)":"Design (days)","制造周期(天)":"Mfg. (days)","检具类别":"Category","检具名称（检具库选型）":"Gauge Name (from library)","刀柄价格（刀具库-刀柄类）：":"Holder cost (Tool Lib): ","配件价格（刀具库-配件类）：":"Accessory cost (Tool Lib): ","本报价单按工序使用的配件小计：":"Accessories used in this quote: ","夹具价格（夹具库）：":"Fixture cost (Fixture Lib): ","检具价格（检具库选型报价）：":"Gauge cost (selected from Gauge Lib): ","刀具成本：":"Tool cost: ","设备价格：":"Machine price: ","夹具/设备价格：":"Fixture / Machine price: ","以下参数用于节拍/产能计算，保存后立即生效。":"These parameters drive cycle/capacity calculation. Effective immediately after saving.","点击此处后按 Ctrl+V 粘贴图片":"Click here then press Ctrl+V to paste an image","点击此处后按 Ctrl+V 粘贴":"Click here then press Ctrl+V to paste","点击图片区域后按 Ctrl+V 粘贴/替换夹具图":"Click the image area then press Ctrl+V to paste/replace the fixture image","点击粘贴成品检具图":"Click to paste finished gauge image","点击粘贴毛坯检具图":"Click to paste blank gauge image","已选定图片位置，请按 Ctrl+V 粘贴":"Image slot armed - press Ctrl+V to paste","默认显示上次夹具图":"Last fixture image shown by default","在设备库中为该设备上传图片":"Upload an image for this machine in Machine DB","显示自动生成的工艺流程图":"Show auto-generated process flow","记录项目版本变更历史，无需密码即可查看和编辑。":"Records project version history. Viewable and editable without password.","请在「产品尺寸与重量」中填写尺寸":"Please fill in dimensions in \"Dimensions\"","选择毛坯检具与成品检具类型后，「项目信息」页工艺流程图自动显示对应节点（图片可点击粘贴上传）。检具价格请在「检具库」中维护。":"After selecting blank/finished gauge types, the flow chart on Project Info shows the nodes automatically (click to paste images). Maintain gauge prices in the Gauge Library.","按四大类从检具库选型，价格/设计周期/制造周期直接引用检具库数据，成本信息与导出价格清单同步报价。":"Select gauges from the library by four categories. Price / design / mfg. cycles are referenced live from the Gauge Library and quoted in Cost Information and the exported price list.","已按检具清单导入五大类检具数据，可按产品尺寸/检具尺寸检索选型报价，价格单位为万元（未税）。":"Five gauge categories imported from the list; search by product/gauge size to select and quote; unit: ×10⁴ CNY (excl. tax).","修改后自动保存。设备图片点击上传或 Ctrl+V 粘贴，点击已上传图片可放大。设备库、刀具库、夹具库、检具库为管理员设置，工艺设置为独立密码。":"Auto-saved after edit. Click to upload or Ctrl+V to paste machine images; click an image to enlarge. Machine/Tool/Fixture/Gauge libraries are admin-protected; Settings uses a separate password.","库分类：高压项目刀具 / 差压项目刀具 / 刀柄 / 配件。刀柄与配件类型分国内/进口两类，不设转速、进给等切削参数（自动计算列显示 —）；切削刀具按铣刀/钻头等分类。可按库分类和刀具类型筛选，按录入顺序显示。修改后自动保存。":"Library groups: High-Pressure tools / Differential tools / Holders / Accessories. Holders & accessories are Domestic/Imported without cutting parameters (auto columns show -). Cutting tools are classified as mill/drill etc. Filter by group and type; displayed in entry order. Auto-saved.","流程按「工艺设置」中的「工序管理」自动生成：包含机加工艺路线、夹具设计、节拍产能三大模块，检具在工艺设置中选择。工序数量变化或更换设备后自动更新。":"The flow is auto-generated from Process Management in Settings: machining route, fixture design and cycle/capacity modules. Gauges are selected in Settings. Updates automatically when processes or machines change.","数据自动保存在 FastAPI 服务端。顶部可切换项目、立即保存、查看历史版本或恢复已删除项目；「导出数据(.json)」可生成离线备份。":"Data is auto-saved in this browser. To share: export a shared HTML file with all data; others open it directly. Use export/import JSON to sync backups.","「导出DFM报告(PPT)」按DFM模版生成PPTX（封面/设备选型/工件信息/工序刀具表/检具/Open issue）；项目完整数据由服务端保存，也可导出 JSON 离线备份。":"\"Export DFM Report (PPT)\" generates a PPTX per the DFM template; \"Export Shared File\" generates a single HTML with all data and images that opens with a double-click.","Vc=π*D*n/1000 | vf=n*fz | t切=L/vf*60*次数*件数 | fz=vf/n":"Vc=π*D*n/1000 | vf=n*fz | tc=L/vf*60*passes*pcs | fz=vf/n","快移时=L快移/快移速度 + 换刀时(大刀×2) + 转台时 + 主轴延时":"Rapid=Lrapid/Vrapid + tool change (big ×2) + index + spindle delay","总切削+总非切削":"Total cutting + total non-cut","月可动时间*可动率/瓶颈节拍*机床数":"Monthly hours × availability / bottleneck cycle × machines","+ 添加刀具":"+ Add Tool","+ 添加工序":"+ Add Process","+ 添加设备":"+ Add Machine","+ 添加三轴夹具":"+ Add 3-Axis Fixture","+ 添加四轴夹具":"+ Add 4-Axis Fixture","+ 添加五轴夹具":"+ Add 5-Axis Fixture","+ 添加毛坯检具":"+ Add Blank Gauge","+ 添加成品机械检具":"+ Add Mechanical Gauge","+ 添加成品总成检具":"+ Add Assembly Gauge","+ 添加成品电子检具":"+ Add Electronic Gauge","+ 新增版本记录":"+ New Version","+ 新增问题":"+ New Issue","夹具示意图":"Fixture Schematic","加工":"Machining","t切":"t_cut","设备型号":"Machine Model","每把刀成本 = 刀具库价格 ÷ 刀具库寿命（自动引用刀具库数据）":"Cost per tool = library price ÷ library life (auto from tool library)","选设备时自动引用设备库价格（万元），也可手工修改":"Auto-filled from Machine DB on machine selection (×10⁴ CNY); editable","产品尺寸":"Product Size","检具尺寸":"Gauge Size","毛坯检具类型":"Blank Gauge Type","通用游标卡尺":"Vernier Caliper","三坐标测量机":"CMM","专用毛坯检具":"Dedicated Blank Gauge","通止规":"GO/NO-GO Gauge","高度尺+杠杆表":"Height Gauge + Lever Indicator","成品检具类型":"Finished Gauge Type","高性能副车架 （整形检具）":"High-Perf. Subframe (Reshaping Gauge)","高性能副车架 （全检检具）":"High-Perf. Subframe (100% Inspection Gauge)","导出价格清单":"Export Price List","导出DFM报告(PPT)":"Export DFM Report (PPT)","导出共享文件(含图片)":"Export Shared File (with images)","导出数据(.json)":"Export Data (.json)","导入数据(.json)":"Import Data (.json)","(自动)":"(Auto)","三轴夹具":"3-Axis Fixture","四轴夹具":"4-Axis Fixture","五轴夹具":"5-Axis Fixture","测量支架":"Measuring Bracket","未选型":"Not Selected","— 未选型 —":"— Not Selected —","产品尺寸检索":"Product Size Search","检具尺寸检索":"Gauge Size Search","匹配选型（产品尺寸 / 检具尺寸）":"Matched Selection (Product / Gauge Size)","按五大类从检具库选型：输入产品尺寸/检具尺寸关键词检索，从匹配结果中选定，价格/设计周期/制造周期直接引用检具库数据，成本信息与导出价格清单同步报价。":"Select from the gauge library in 5 categories: search by product/gauge size keywords and pick from the matches; price/design/mfg cycles reference library data; cost info and export list stay in sync.","请输入工艺设置密码":"Enter process settings password","请输入管理员密码":"Enter admin password","密码错误":"Wrong password","确认删除该版本记录？":"Delete this version record?","数据已保存到本机浏览器":"Data saved to this browser","请输入文件名：":"Enter file name:","PPTX 组件未加载，请检查文件完整性":"PPTX component not loaded; check file integrity","暂无工序数据，请先在「工序管理」中添加工序":"No process data; add processes first","删除图片?":"Delete image?","数据导入成功，已覆盖当前数据!":"Data imported; current data overwritten!","文件格式错误，请选择导出的 JSON 数据文件。":"Invalid format; select an exported JSON file.","如 A / B / C 版":"e.g. A / B / C","变更内容描述":"Change description","如 347*326":"e.g. 347*326","如 600*400":"e.g. 600*400","+ 添加":"+ Add","夹具报价选型":"Fixture Quote Selection","模具中心":"Mold Center","是否报价":"Quote?","夹具选型":"Fixture Selection","价格":"Price","共":"Total","条":"items","类":"cat.","中心":"center","夹具价格（夹具库选型报价）：":"Fixture cost (selected from Fixture Lib): ","XYZ行程<br>mm":"XYZ travel<br>mm","定位精度<br>mm":"Pos. accuracy<br>mm","重复定位精度<br>mm":"Repeatability<br>mm","上传资料":"Upload Doc","资料":"Doc","资料过大（限 2MB），请压缩后上传":"File too large (max 2MB), please compress","删除资料?":"Delete doc?","已按类别导入检具数据，可按产品尺寸/检具尺寸检索选型报价，价格单位为万元（未税）；支持新增/删除自定义类别。":"Gauge data imported by category. Search by product/gauge size to select and quote; prices in 10k CNY (excl. tax). Custom categories can be added/removed.","新增类别":"+ New Category","删除类别":"Del. Category","该类别已存在":"Category exists","基础类别不可删除":"Base category kept","请输入新增检具类别名称：":"New gauge category name:","请输入新增模具中心名称：":"New fixture center name:","夹具库说明：按模具中心分类维护夹具，名称/价格/制造周期/备注可直接编辑，报价在「夹具报价选型」中勾选引用。":"Maintain fixtures by mold center; name/price/mfg-days/remark are editable. Quoting is enabled via checkboxes in Fixture Quoting.","+ 添加夹具":"+ Add Fixture","备注":"Remark","项":"items","（按录入顺序显示）":"(in entry order)","D(mm)":"D(mm)","每齿进给fz<br>(自动)":"Per-tooth fz<br>(auto)","线速度Vc<br>(自动)":"Speed Vc<br>(auto)","无匹配":"No match","删除类别「":"Delete category ","」及其下 ":" with its "," 条数据？":" item(s)?","PPTX 生成失败: ":"PPTX generation failed: ","导出失败: ":"Export failed: ","点击后粘贴新图":"Click then paste new image","点击后按 Ctrl+V 粘贴新图":"Click, then Ctrl+V to paste new image","点击后按 Ctrl+V 粘贴/替换夹具图":"Click, then Ctrl+V to paste/replace fixture image","下载资料":"Download document","从刀具库选":"Pick from Tool DB","转速":"Spindle","高性能副车架\n（整形检具）":"High-Perf. Subframe (Reshaping Gauge)","高性能副车架\n（全检检具）":"High-Perf. Subframe (100% Inspection Gauge)","」？":"\"?","面铣刀":"Face Mill","PCD面铣刀":"PCD Face Mill","PCD-T型刀":"PCD T-Slot Cutter","PCD倒角刀":"PCD Chamfer Mill","PCD反勾刀":"PCD Back-Chamfer Mill","PCD复合切槽刀":"PCD Combo Groove Cutter","PCD锪刀":"PCD Countersink","PCD铰刀":"PCD Reamer","PCD精镗刀":"PCD Fine Boring Bar","PCD盘刀":"PCD Disc Cutter","PCD球刀":"PCD Ball Nose","PCD铣刀":"PCD End Mill","PCD玉米铣刀":"PCD Corn Mill","PCD锥度刀":"PCD Taper Mill","PCD钻铰刀":"PCD Drill-Reamer","PCD钻头":"PCD Drill","U钻":"U Drill","波纹合金铣刀":"Corrugated Carbide Mill","粗镗刀（刀片）":"Rough Boring Bar (Insert)","合金倒角刀":"Carbide Chamfer Mill","合金挤压丝锥":"Carbide Roll Tap","合金内R铣刀":"Carbide Inner-R Mill","合金球刀":"Carbide Ball Nose","合金球头铣刀":"Carbide Ball-End Mill","合金铣刀":"Carbide End Mill","合金锥度铣刀":"Carbide Taper Mill","合金钻头":"Carbide Drill","网纹铣刀（刀片）":"Serrated Mill (Insert)","合金钻铣刀":"Carbide Drill-Mill","PCD成型刀":"PCD Form Cutter","PCD成型钻头":"PCD Form Drill","合金阶梯钻":"Carbide Step Drill","合金台阶钻":"Carbide Subland Drill","开粗镗刀":"Rough Boring Bar","合金深孔钻":"Carbide Deep-Hole Drill","PCD导条刀":"PCD Guide-Pad Tool","PCD阶梯铰刀":"PCD Step Reamer","合金导条刀":"Carbide Guide-Pad Tool","合金铰刀":"Carbide Reamer","合金阶梯铰刀":"Carbide Step Reamer","合金钻铰刀":"Carbide Drill-Reamer","挤压丝锥":"Roll Tap","切削丝锥":"Cut Tap","螺纹铣刀":"Thread Mill","PCD套刀":"PCD Trepan","毛刷":"Brush","换图":"Replace","+粘贴":"+ Paste","上传图片":"Upload Image","保存失败：本机浏览器存储空间已满，请减少粘贴的图片数量，或使用另存为导出文件保存":"Save failed: browser storage is full. Reduce pasted images or use Save As to export a file.","从设备库引用价格":"Pull prices from Machine DB","已按设备库价格刷新设备成本":"Machine costs refreshed from Machine DB","已保存：全部数据已写入本文件":"Saved: all data written into this file","已保存：并已导出一份含全部数据的文件（见浏览器下载）":"Saved: a file containing all data was downloaded (see downloads)","提示：「保存」会把全部数据写入服务端当前项目，并保留历史版本。":"Note: Save writes all data into this file (asks location the first time); send that file to share your work.","本报价单按工序使用的刀柄小计：":"Holders used in this quote: "},"th":{"项目信息":"ข้อมูลโครงการ","问题清单":"รายการปัญหา","版本履历":"ประวัติเวอร์ชัน","设备库":"คลังเครื่องจักร","工艺设置":"ตั้งค่ากระบวนการ","刀具库":"คลังเครื่องมือตัด","夹具库":"คลังจิ๊ก","检具库":"คลังเกจวัด","退出":"ออก","保存":"บันทึก","另存为":"บันทึกเป็น","重置":"รีเซ็ต","操作":"จัดการ","上传":"อัปโหลด","粘贴":"วาง","+图片":"+รูป","图片":"รูป","名称":"ชื่อ","类型":"ชนิด","型号":"รุ่น","未选择":"ไม่ได้เลือก","全部":"ทั้งหมด","全部类型":"ทุกชนิด","库分类":"หมวดคลัง","库分类：":"หมวดคลัง:","版本":"เวอร์ชัน","日期":"วันที่","变更人":"ผู้แก้ไข","变更内容":"รายการแก้ไข","其他":"อื่นๆ","刀柄":"ด้ามมีด","配件":"อะไหล่","国内":"ในประเทศ","进口":"นำเข้า","高压项目":"แรงดันสูง","差压项目":"แรงดันต่าง","高压项目刀具":"เครื่องมือแรงดันสูง","差压项目刀具":"เครื่องมือแรงดันต่าง","毛坯检具":"เกจวัดชิ้นงานดิบ","成品机械检具":"เกจวัดเชิงกล","成品总成检具":"เกจวัดชุดประกอบ","成品电子检具":"เกจวัดอิเล็กทรอนิกส์","铣刀":"ฟราย","钻头":"สว่าน","丝锥":"ต๊าป","中心钻":"สว่านเซ็นเตอร์","倒角刀":"ฟรายลบมุม","新检具":"เกจใหม่","新刀具":"เครื่องมือใหม่","新夹具":"จิ๊กใหม่","新品牌":"ยี่ห้อใหม่","新设备":"เครื่องจักรใหม่","新品":"ใหม่","⚙ 工艺设置":"⚙ ตั้งค่า","🔒 管理设置":"🔒 ผู้ดูแล","品牌 Brand":"ยี่ห้อ","型号 Model":"รุ่น","说明 Desc":"รายละเอียด","图片 Photo":"รูปภาพ","快移 Rapid m/min":"เร็ว m/min","换刀 TC s":"เปลี่ยนเครื่องมือ s","转速 RPM":"รอบ RPM","刀库 ATC":"ATC","+ 添加刀具 / Add Tool":"+ เพิ่มเครื่องมือตัด","产品图片 / Product Image":"รูปชิ้นงาน","客户与零件 / Customer & Part":"ลูกค้าและชิ้นส่วน","产品尺寸与重量 / Dimensions":"ขนาดและน้ำหนัก","工艺流程图 / Process Flow":"ผังกระบวนการ","机加工艺路线 / Machining Process Route":"เส้นทางกระบวนการกัด","夹具设计 / Fixture Design（与机加工序对应）":"ออกแบบจิ๊ก (ตามกระบวนการ)","节拍产能 / Cycle Time & Capacity":"เวลาไซเคิลและกำลังผลิต","非加工时间明细 / Non-Cut Details":"รายละเอียดเวลานอกการตัด","夹具示意图 / Fixture Layout":"ผังจิ๊ก","工艺设置 / Settings":"ตั้งค่ากระบวนการ","工序管理 / Process Management":"จัดการกระบวนการ","成本信息 / Cost Information":"ข้อมูลต้นทุน","检具选择 / Inspection Fixtures":"เลือกเกจวัด","检具报价选型 / Inspection Quoting":"เลือกเกจเพื่อเสนอราคา","数据保存与导出 / Save & Export":"บันทึกและส่งออก","公式 / Formulas":"สูตร","设备数据库 / Machine DB":"ฐานข้อมูลเครื่องจักร","刀具类型参数库 / Tool Type Library":"คลังพารามิเตอร์เครื่องมือ","夹具库 / Fixture Library":"คลังจิ๊ก","检具库 / Inspection Tool Library":"คลังเกจวัด","版本变更履历 / Version History":"ประวัติการเปลี่ยนแปลง","问题清单 / Issue List (DFM Format)":"รายการปัญหา (DFM)","项目类型":"ชนิดโครงการ","日可动时间":"ชั่วโมงทำงาน/วัน","日班次":"กะ/วัน","月可动日":"วันทำงาน/เดือน","可动率":"อัตราพร้อมใช้งาน","客户名称":"ลูกค้า","零件名称":"ชื่อชิ้นส่วน","客户版本":"เวอร์ชันลูกค้า","DFM完成时间":"วันที่เสร็จ DFM","长度 L":"ยาว L","宽度 W":"กว้าง W","高度 H":"สูง H","重量":"น้ำหนัก","上传产品图":"อัปโหลดรูปชิ้นงาน","未上传设备图":"ไม่มีรูปเครื่องจักร","未上传夹具图":"ไม่มีรูปจิ๊ก","工序":"กระบวนการ","台":"เครื่อง","件":"ชิ้น","次":"ครั้ง","刀号":"หมายเลขเครื่องมือ","刀具型号":"รุ่นเครื่องมือ","刀柄选型":"เลือกด้ามมีด","配件选型":"เลือกอะไหล่","加工内容":"เนื้อหาการกัด","加工特征":"ลักษณะการกัด","加工节拍":"เวลาไซเคิล","切削参数与时间":"พารามิเตอร์และเวลาตัด","转速n(rpm)":"รอบ n(rpm)","进给vf(mm/min)":"ฟีด vf(mm/min)","每齿进给fz":"ฟีดต่อฟัน fz","线速度Vc":"ความเร็วตัด Vc","长度L(mm)":"ยาว L(mm)","寿命(min)":"อายุการใช้งาน(นาที)","定位精度":"ความแม่นยำตำแหน่ง","重复定位精度":"ความแม่นยำซ้ำ","XYZ行程":"ระยะเคลื่อน XYZ","自定义":"กำหนดเอง","基本":"พื้นฐาน","大刀":"เครื่องมือใหญ่","辅压紧":"แคลมป์รอง","主压紧":"แคลมป์หลัก","支撑缸":"ลูกสูบรองรับ","开门":"เปิดประตู","关门":"ปิดประตู","检测/吹屑":"ตรวจ/เป่าเศษ","快移时":"เวลาเคลื่อนเร็ว","换刀时":"เวลาเปลี่ยนเครื่องมือ","转台时":"เวลาหมุนโต๊ะ","主轴延时":"หน่วงสปินเดิล","总切削":"ตัดรวม","总非切削":"นอกการตัดรวม","总时间":"เวลารวม","非切削":"นอกการตัด","切削:":"ตัด:","非切削(每刀):":"นอกการตัด(ต่อเครื่องมือ):","产能:":"กำลังผลิต:","节拍:":"ไซเคิล:","月产能(1台)":"กำลังผลิต/เดือน(1เครื่อง)","刀具类型：":"ชนิดเครื่องมือ:","刀具类型":"ชนิดเครื่องมือ","刀具数":"จำนวนเครื่องมือ","刀具总价(¥)":"ราคาเครื่องมือรวม(¥)","单件刀具成本(¥)":"ต้นทุนเครื่องมือ/ชิ้น(¥)","夹具价格(¥)":"ราคาจิ๊ก(¥)","设备价格(万¥)":"ราคาเครื่องจักร(หมื่น¥)","价格(¥)":"ราคา(¥)","🔧 刀具系统":"🔧 ระบบเครื่องมือตัด","快移距":"ระยะเคลื่อนเร็ว","检具名称":"ชื่อเกจวัด","检具图号":"เลขแบบ","产品尺寸(mm)":"ขนาดชิ้นงาน (มม.)","检具尺寸(mm)":"ขนาดเกจ (มม.)","价格(万¥)":"ราคา(หมื่น¥)","设计周期(天)":"ระยะออกแบบ(วัน)","制造周期(天)":"ระยะผลิต(วัน)","检具类别":"หมวดเกจวัด","检具名称（检具库选型）":"ชื่อเกจ (เลือกจากคลัง)","刀柄价格（刀具库-刀柄类）：":"ราคาด้ามมีด (คลังเครื่องมือ): ","配件价格（刀具库-配件类）：":"ราคาอะไหล่ (คลังเครื่องมือ): ","本报价单按工序使用的配件小计：":"อะไหล่ที่ใช้ในใบเสนอราคานี้: ","夹具价格（夹具库）：":"ราคาจิ๊ก (คลังจิ๊ก): ","检具价格（检具库选型报价）：":"ราคาเกจวัด (เลือกจากคลัง): ","刀具成本：":"ต้นทุนเครื่องมือ: ","设备价格：":"ราคาเครื่องจักร: ","夹具/设备价格：":"ราคาจิ๊ก/เครื่องจักร: ","以下参数用于节拍/产能计算，保存后立即生效。":"พารามิเตอร์เหล่านี้ใช้คำนวณเวลาไซเคิล/กำลังผลิต บันทึกแล้วมีผลทันที","点击此处后按 Ctrl+V 粘贴图片":"คลิกที่นี่แล้วกด Ctrl+V เพื่อวางรูปภาพ","点击此处后按 Ctrl+V 粘贴":"คลิกที่นี่แล้วกด Ctrl+V เพื่อวาง","点击图片区域后按 Ctrl+V 粘贴/替换夹具图":"คลิกบริเวณรูปแล้วกด Ctrl+V เพื่อวาง/เปลี่ยนรูปจิ๊ก","点击粘贴成品检具图":"คลิกเพื่อวางรูปเกจชิ้นงานสำเร็จ","点击粘贴毛坯检具图":"คลิกเพื่อวางรูปเกจชิ้นงานดิบ","已选定图片位置，请按 Ctrl+V 粘贴":"เลือกตำแหน่งรูปแล้ว กรุณากด Ctrl+V เพื่อวาง","默认显示上次夹具图":"แสดงรูปจิ๊กล่าสุดเป็นค่าเริ่มต้น","在设备库中为该设备上传图片":"อัปโหลดรูปเครื่องจักรนี้ในคลังเครื่องจักร","显示自动生成的工艺流程图":"แสดงผังกระบวนการที่สร้างอัตโนมัติ","记录项目版本变更历史，无需密码即可查看和编辑。":"บันทึกประวัติการเปลี่ยนแปลงเวอร์ชันของโครงการ ดูและแก้ไขได้โดยไม่ต้องใช้รหัสผ่าน","请在「产品尺寸与重量」中填写尺寸":"กรุณากรอกขนาดในส่วน \"ขนาดและน้ำหนัก\"","选择毛坯检具与成品检具类型后，「项目信息」页工艺流程图自动显示对应节点（图片可点击粘贴上传）。检具价格请在「检具库」中维护。":"หลังเลือกชนิดเกจชิ้นงานดิบ/สำเร็จ ผังกระบวนการในหน้าข้อมูลโครงการจะแสดงโหนดที่เกี่ยวข้องอัตโนมัติ (คลิกเพื่อวางรูป) ราคาเกจดูแลใน \"คลังเกจวัด\"","按四大类从检具库选型，价格/设计周期/制造周期直接引用检具库数据，成本信息与导出价格清单同步报价。":"เลือกเกจจากคลังตามสี่หมวด ราคา/ระยะออกแบบ/ระยะผลิตอ้างอิงข้อมูลคลังเกจโดยตรง และแสดงในข้อมูลต้นทุนและใบเสนอราคาที่ส่งออก","已按检具清单导入五大类检具数据，可按产品尺寸/检具尺寸检索选型报价，价格单位为万元（未税）。":"นำเข้าเกจ 5 ประเภทตามรายการ เลือกและเสนอราคาโดยค้นหาขนาดชิ้นงาน/เกจ หน่วย: หมื่นหยวน (ไม่รวมภาษี)","修改后自动保存。设备图片点击上传或 Ctrl+V 粘贴，点击已上传图片可放大。设备库、刀具库、夹具库、检具库为管理员设置，工艺设置为独立密码。":"บันทึกอัตโนมัติหลังแก้ไข รูปเครื่องจักรคลิกเพื่ออัปโหลดหรือกด Ctrl+V วาง คลิกรูปที่อัปโหลดแล้วเพื่อขยาย คลังเครื่องจักร/เครื่องมือ/จิ๊ก/เกจเป็นส่วนผู้ดูแล ส่วนตั้งค่ากระบวนการใช้รหัสแยก","库分类：高压项目刀具 / 差压项目刀具 / 刀柄 / 配件。刀柄与配件类型分国内/进口两类，不设转速、进给等切削参数（自动计算列显示 —）；切削刀具按铣刀/钻头等分类。可按库分类和刀具类型筛选，按录入顺序显示。修改后自动保存。":"หมวดคลัง: เครื่องมือแรงดันสูง / เครื่องมือแรงดันต่าง / ด้ามมีด / อะไหล่ ด้ามมีดและอะไหล่แบ่งในประเทศ/นำเข้า ไม่มีพารามิเตอร์การตัด (คอลัมน์คำนวณอัตโนมัติแสดง —) เครื่องมือตัดแบ่งเป็นฟราย/สว่าน ฯลฯ กรองตามหมวดและชนิด แสดงตามลำดับการบันทึก บันทึกอัตโนมัติ","流程按「工艺设置」中的「工序管理」自动生成：包含机加工艺路线、夹具设计、节拍产能三大模块，检具在工艺设置中选择。工序数量变化或更换设备后自动更新。":"ผังสร้างอัตโนมัติจาก \"จัดการกระบวนการ\" ในตั้งค่า ประกอบด้วย เส้นทางกระบวนการกัด การออกแบบจิ๊ก และเวลาไซเคิล/กำลังผลิต เกจเลือกในตั้งค่า อัปเดตอัตโนมัติเมื่อจำนวนกระบวนการหรือเครื่องจักรเปลี่ยน","数据自动保存在 FastAPI 服务端。顶部可切换项目、立即保存、查看历史版本或恢复已删除项目；「导出数据(.json)」可生成离线备份。":"ข้อมูลบันทึกอัตโนมัติในเบราว์เซอร์เครื่องนี้ การแชร์: กด \"ส่งออกไฟล์แชร์\" เพื่อสร้าง HTML ที่มีข้อมูลทั้งหมด ผู้อื่นเปิดดูได้ทันที ใช้ส่งออก/นำเข้า JSON เพื่อสำรองข้อมูล","「导出DFM报告(PPT)」按DFM模版生成PPTX（封面/设备选型/工件信息/工序刀具表/检具/Open issue）；项目完整数据由服务端保存，也可导出 JSON 离线备份。":"\"ส่งออกรายงาน DFM (PPT)\" สร้าง PPTX ตามเทมเพลต DFM \"ส่งออกไฟล์แชร์\" สร้าง HTML ไฟล์เดียวมีข้อมูลและรูปทั้งหมด เปิดได้ด้วยดับเบิลคลิก","Vc=π*D*n/1000 | vf=n*fz | t切=L/vf*60*次数*件数 | fz=vf/n":"Vc=π*D*n/1000 | vf=n*fz | tตัด=L/vf*60×จำนวนครั้ง×จำนวนชิ้น | fz=vf/n","快移时=L快移/快移速度 + 换刀时(大刀×2) + 转台时 + 主轴延时":"เวลาเร็ว=ระยะเร็ว/ความเร็วเร็ว + เปลี่ยนเครื่องมือ(ใหญ่×2) + หมุนโต๊ะ + หน่วงสปินเดิล","总切削+总非切削":"ตัดรวม+นอกการตัดรวม","月可动时间*可动率/瓶颈节拍*机床数":"ชั่วโมงทำงาน/เดือน×อัตราพร้อมใช้งาน/ไซเคิลคอขวด×จำนวนเครื่อง","+ 添加刀具":"+ เพิ่มเครื่องมือตัด","+ 添加工序":"+ เพิ่มกระบวนการ","+ 添加设备":"+ เพิ่มเครื่องจักร","+ 添加三轴夹具":"+ เพิ่มจิ๊ก 3 แกน","+ 添加四轴夹具":"+ เพิ่มจิ๊ก 4 แกน","+ 添加五轴夹具":"+ เพิ่มจิ๊ก 5 แกน","+ 添加毛坯检具":"+ เพิ่มเกจชิ้นงานดิบ","+ 添加成品机械检具":"+ เพิ่มเกจเชิงกล","+ 添加成品总成检具":"+ เพิ่มเกจชุดประกอบ","+ 添加成品电子检具":"+ เพิ่มเกจอิเล็กทรอนิกส์","+ 新增版本记录":"+ เพิ่มเวอร์ชัน","+ 新增问题":"+ เพิ่มปัญหา","夹具示意图":"แผนภาพจิ๊ก","加工":"การกลึง","t切":"t_ตัด","设备型号":"รุ่นเครื่องจักร","每把刀成本 = 刀具库价格 ÷ 刀具库寿命（自动引用刀具库数据）":"ต้นทุนต่อ tool = ราคาคลัง ÷ อายุ tool (อ้างอิงอัตโนมัติจากคลัง tool)","选设备时自动引用设备库价格（万元），也可手工修改":"เลือกเครื่องจักรแล้วดึงราคาจากคลังเครื่องจักรอัตโนมัติ (หมื่น¥) แก้ไขได้","产品尺寸":"ขนาดชิ้นงาน","检具尺寸":"ขนาดเกจ","毛坯检具类型":"ประเภทเกจชิ้นงานดิบ","通用游标卡尺":"คัลลิปเปอร์เวอร์เนียร์","三坐标测量机":"เครื่องวัดสามพิกัด (CMM)","专用毛坯检具":"เกจเฉพาะชิ้นงานดิบ","通止规":"เกจ GO/NO-GO","高度尺+杠杆表":"ไม้วัดความสูง+เข็มวัด","成品检具类型":"ประเภทเกจชิ้นงานสำเร็จ","高性能副车架 （整形检具）":"ซับเฟรมสมรรถนะสูง (เกจจัดรูปทรง)","高性能副车架 （全检检具）":"ซับเฟรมสมรรถนะสูง (เกจตรวจ 100%)","导出价格清单":"ส่งออกรายการราคา","导出DFM报告(PPT)":"ส่งออกรายงาน DFM (PPT)","导出共享文件(含图片)":"ส่งออกไฟล์แชร์ (รวมรูป)","导出数据(.json)":"ส่งออกข้อมูล (.json)","导入数据(.json)":"นำเข้าข้อมูล (.json)","(自动)":"(อัตโนมัติ)","三轴夹具":"จิ๊ก 3 แกน","四轴夹具":"จิ๊ก 4 แกน","五轴夹具":"จิ๊ก 5 แกน","测量支架":"ขาตั้งวัด","未选型":"ยังไม่เลือก","— 未选型 —":"— ยังไม่เลือก —","产品尺寸检索":"ค้นหาขนาดชิ้นงาน","检具尺寸检索":"ค้นหาขนาดเกจ","匹配选型（产品尺寸 / 检具尺寸）":"รายการที่ตรง (ขนาดชิ้นงาน / เกจ)","按五大类从检具库选型：输入产品尺寸/检具尺寸关键词检索，从匹配结果中选定，价格/设计周期/制造周期直接引用检具库数据，成本信息与导出价格清单同步报价。":"เลือกจากคลังเกจ 5 ประเภท: ค้นหาด้วยคำสำคัญขนาดชิ้นงาน/เกจ แล้วเลือกจากผลที่ตรง ราคา/รอบออกแบบ/รอบผลิตอ้างอิงข้อมูลคลัง ต้นทุนและรายการส่งออกซิงก์กัน","请输入工艺设置密码":"กรุณากรอกรหัสผ่านตั้งค่ากระบวนการ","请输入管理员密码":"กรุณากรอกรหัสผ่านผู้ดูแล","密码错误":"รหัสผ่านไม่ถูกต้อง","确认删除该版本记录？":"ลบรายการเวอร์ชันนี้?","数据已保存到本机浏览器":"บันทึกข้อมูลลงเบราว์เซอร์เครื่องนี้แล้ว","请输入文件名：":"กรุณากรอกชื่อไฟล์:","PPTX 组件未加载，请检查文件完整性":"คอมโพเนนต์ PPTX ไม่ได้โหลด กรุณาตรวจสอบความสมบูรณ์ของไฟล์","暂无工序数据，请先在「工序管理」中添加工序":"ยังไม่มีข้อมูลกระบวนการ กรุณาเพิ่มใน「การจัดการกระบวนการ」ก่อน","删除图片?":"ลบรูปภาพ?","数据导入成功，已覆盖当前数据!":"นำเข้าข้อมูลสำเร็จ ข้อมูลปัจจุบันถูกแทนที่!","文件格式错误，请选择导出的 JSON 数据文件。":"รูปแบบไฟล์ไม่ถูกต้อง กรุณาเลือกไฟล์ JSON ที่ส่งออก","如 A / B / C 版":"เช่น A / B / C","变更内容描述":"คำอธิบายการเปลี่ยนแปลง","如 347*326":"เช่น 347*326","如 600*400":"เช่น 600*400","+ 添加":"+ เพิ่ม","夹具报价选型":"เลือกใบเสนอราคาจิ๊ก","模具中心":"ศูนย์แม่พิมพ์","是否报价":"เสนอราคา?","夹具选型":"เลือกจิ๊ก","价格":"ราคา","共":"รวม","条":"รายการ","类":"ประเภท","中心":"ศูนย์","夹具价格（夹具库选型报价）：":"ราคาจิ๊ก (เลือกจากคลังจิ๊ก): ","XYZ行程<br>mm":"ระยะ XYZ<br>mm","定位精度<br>mm":"ความแม่นยำตำแหน่ง<br>mm","重复定位精度<br>mm":"ความแม่นยำซ้ำ<br>mm","上传资料":"อัปโหลดเอกสาร","资料":"เอกสาร","资料过大（限 2MB），请压缩后上传":"ไฟล์ใหญ่เกิน (สูงสุด 2MB) กรุณาบีบอัด","删除资料?":"ลบเอกสาร?","已按类别导入检具数据，可按产品尺寸/检具尺寸检索选型报价，价格单位为万元（未税）；支持新增/删除自定义类别。":"นำเข้าเกจตามหมวดหมู่ ค้นหาด้วยขนาดชิ้นงาน/เกจเพื่อเลือกและอ้างอิงราคา ราคาหน่วยหมื่นหยวน (ไม่รวมภาษี) เพิ่ม/ลบหมวดหมู่ได้","新增类别":"+ เพิ่มหมวดหมู่","删除类别":"ลบหมวดหมู่","该类别已存在":"หมวดหมู่นี้มีแล้ว","基础类别不可删除":"หมวดหมู่พื้นฐานลบไม่ได้","请输入新增检具类别名称：":"ป้อนชื่อหมวดหมู่เกจใหม่:","请输入新增模具中心名称：":"ป้อนชื่อศูนย์แม่พิมพ์ใหม่:","夹具库说明：按模具中心分类维护夹具，名称/价格/制造周期/备注可直接编辑，报价在「夹具报价选型」中勾选引用。":"ดูแลฟิกซ์เจอร์ตามศูนย์แม่พิมพ์ แก้ไขชื่อ/ราคา/ระยะเวลาผลิต/หมายเหตุได้ การอ้างอิงราคาเปิดด้วย checkbox ในหน้าการเลือกฟิกซ์เจอร์","+ 添加夹具":"+ เพิ่มฟิกซ์เจอร์","备注":"หมายเหตุ","项":"รายการ","（按录入顺序显示）":"(แสดงตามลำดับการบันทึก)","D(mm)":"D(mm)","每齿进给fz<br>(自动)":"fz ต่อฟัน<br>(อัตโนมัติ)","线速度Vc<br>(自动)":"ความเร็วตัด Vc<br>(อัตโนมัติ)","无匹配":"ไม่พบ","删除类别「":"ลบหมวดหมู่ ","」及其下 ":" พร้อมข้อมูล "," 条数据？":" รายการ?","PPTX 生成失败: ":"สร้าง PPTX ล้มเหลว: ","导出失败: ":"ส่งออกล้มเหลว: ","点击后粘贴新图":"คลิกแล้ววางรูปใหม่","点击后按 Ctrl+V 粘贴新图":"คลิกแล้วกด Ctrl+V เพื่อวางรูปใหม่","点击后按 Ctrl+V 粘贴/替换夹具图":"คลิกแล้วกด Ctrl+V เพื่อวาง/แทนที่รูปจิ๊ก","下载资料":"ดาวน์โหลดเอกสาร","从刀具库选":"เลือกจากคลังเครื่องมือตัด","转速":"รอบ","高性能副车架\n（整形检具）":"ซับเฟรมสมรรถนะสูง (เกจจัดรูปทรง)","高性能副车架\n（全检检具）":"ซับเฟรมสมรรถนะสูง (เกจตรวจ 100%)","」？":"\"?","面铣刀":"ฟรายหน้า","PCD面铣刀":"ฟรายหน้า PCD","PCD-T型刀":"ฟรายร่อง T PCD","PCD倒角刀":"ฟรายลบมุม PCD","PCD反勾刀":"ฟรายลบมุมย้อน PCD","PCD复合切槽刀":"คัตเตอร์ร่องรวม PCD","PCD锪刀":"เจาะจุ่ม PCD","PCD铰刀":"รีมเมอร์ PCD","PCD精镗刀":"โบริ่งละเอียด PCD","PCD盘刀":"ฟรายจาน PCD","PCD球刀":"ฟรายปลายมน PCD","PCD铣刀":"ฟรายหัว PCD","PCD玉米铣刀":"ฟรายข้าวโพด PCD","PCD锥度刀":"ฟรายกรวย PCD","PCD钻铰刀":"เจาะ-รีม PCD","PCD钻头":"สว่าน PCD","U钻":"สว่าน U","波纹合金铣刀":"ฟรายลอนคาร์ไบด์","粗镗刀（刀片）":"โบริ่งหยาบ (แผ่นเม็ด)","合金倒角刀":"ฟรายลบมุมคาร์ไบด์","合金挤压丝锥":"ต๊าปอัดคาร์ไบด์","合金内R铣刀":"ฟราย R ด้านในคาร์ไบด์","合金球刀":"ฟรายปลายมนคาร์ไบด์","合金球头铣刀":"ฟรายหัวกลมคาร์ไบด์","合金铣刀":"ฟรายหัวคาร์ไบด์","合金锥度铣刀":"ฟรายกรวยคาร์ไบด์","合金钻头":"สว่านคาร์ไบด์","网纹铣刀（刀片）":"ฟรายลายตาข่าย (แผ่นเม็ด)","合金钻铣刀":"เจาะ-ฟรายคาร์ไบด์","PCD成型刀":"ฟรายขึ้นรูป PCD","PCD成型钻头":"สว่านขึ้นรูป PCD","合金阶梯钻":"สว่านบันไดคาร์ไบด์","合金台阶钻":"สว่านขั้นคาร์ไบด์","开粗镗刀":"โบริ่งหยาบ","合金深孔钻":"สว่านรูลึกคาร์ไบด์","PCD导条刀":"มีดนำทาง PCD","PCD阶梯铰刀":"รีมเมอร์บันได PCD","合金导条刀":"มีดนำทางคาร์ไบด์","合金铰刀":"รีมเมอร์คาร์ไบด์","合金阶梯铰刀":"รีมเมอร์บันไดคาร์ไบด์","合金钻铰刀":"เจาะ-รีมคาร์ไบด์","挤压丝锥":"ต๊าปอัด","切削丝锥":"ต๊าปตัด","螺纹铣刀":"ฟรายเกลียว","PCD套刀":"ทรีแพน PCD","毛刷":"แปรง","换图":"เปลี่ยนรูป","+粘贴":"+ วาง","上传图片":"อัปโหลดรูปภาพ","保存失败：本机浏览器存储空间已满，请减少粘贴的图片数量，或使用另存为导出文件保存":"บันทึกไม่สำเร็จ: พื้นที่เก็บข้อมูลของเบราว์เซอร์เต็ม โปรดลดจำนวนรูปภาพที่วาง หรือใช้บันทึกเป็นไฟล์แทน","从设备库引用价格":"ดึงราคาจากคลังเครื่องจักร","已按设备库价格刷新设备成本":"รีเฟรชต้นทุนเครื่องจักรจากคลังเครื่องจักรแล้ว","已保存：全部数据已写入本文件":"บันทึกแล้ว: ข้อมูลทั้งหมดถูกเขียนลงในไฟล์นี้","已保存：并已导出一份含全部数据的文件（见浏览器下载）":"บันทึกแล้ว: ดาวน์โหลดไฟล์ที่มีข้อมูลทั้งหมดแล้ว (ดูรายการดาวน์โหลด)","提示：「保存」会把全部数据写入服务端当前项目，并保留历史版本。":"หมายเหตุ: การบันทึกจะเขียนข้อมูลทั้งหมดลงในไฟล์นี้ (ครั้งแรกจะถามตำแหน่ง) ส่งไฟล์นี้ให้ผู้อื่น","本报价单按工序使用的刀柄小计：":"ด้ามมีดที่ใช้ในใบเสนอราคานี้: "},"es":{"项目信息":"Info del Proyecto","问题清单":"Problemas","版本履历":"Versiones","设备库":"Máquinas","工艺设置":"Configuración","刀具库":"Herramientas","夹具库":"Utillajes","检具库":"Galgas","退出":"Salir","保存":"Guardar","另存为":"Guardar como","重置":"Reiniciar","操作":"Acción","上传":"Subir","粘贴":"Pegar","+图片":"+Imagen","图片":"Imagen","名称":"Nombre","类型":"Tipo","型号":"Modelo","未选择":"No seleccionado","全部":"Todo","全部类型":"Todos los tipos","库分类":"Categoría","库分类：":"Categoría:","版本":"Versión","日期":"Fecha","变更人":"Modificado por","变更内容":"Cambios","其他":"Otros","刀柄":"Portaherr.","配件":"Accesorio","国内":"Nacional","进口":"Importado","高压项目":"Alta Presión","差压项目":"Presión Dif.","高压项目刀具":"Herram. Alta Presión","差压项目刀具":"Herram. Presión Dif.","毛坯检具":"Galga de Bruto","成品机械检具":"Galga Mecánica","成品总成检具":"Galga de Conjunto","成品电子检具":"Galga Electrónica","铣刀":"Fresa","钻头":"Broca","丝锥":"Macho","中心钻":"Broca de Centro","倒角刀":"Chamfer","新检具":"Nueva Galga","新刀具":"Nueva Herramienta","新夹具":"Nuevo Utillaje","新品牌":"Nueva Marca","新设备":"Nueva Máquina","新品":"Nuevo","⚙ 工艺设置":"⚙ Configuración","🔒 管理设置":"🔒 Admin","品牌 Brand":"Marca","型号 Model":"Modelo","说明 Desc":"Descripción","图片 Photo":"Foto","快移 Rapid m/min":"Rápido m/min","换刀 TC s":"TC s","转速 RPM":"RPM","刀库 ATC":"ATC","+ 添加刀具 / Add Tool":"+ Añadir Herramienta","产品图片 / Product Image":"Imagen del Producto","客户与零件 / Customer & Part":"Cliente y Pieza","产品尺寸与重量 / Dimensions":"Dimensiones","工艺流程图 / Process Flow":"Flujo de Proceso","机加工艺路线 / Machining Process Route":"Ruta de Mecanizado","夹具设计 / Fixture Design（与机加工序对应）":"Diseño de Utillaje (por proceso)","节拍产能 / Cycle Time & Capacity":"Ciclo y Capacidad","非加工时间明细 / Non-Cut Details":"Detalles No Corte","夹具示意图 / Fixture Layout":"Esquema de Utillaje","工艺设置 / Settings":"Configuración","工序管理 / Process Management":"Gestión de Procesos","成本信息 / Cost Information":"Información de Costos","检具选择 / Inspection Fixtures":"Selección de Galgas","检具报价选型 / Inspection Quoting":"Cotización de Galgas","数据保存与导出 / Save & Export":"Guardar y Exportar","公式 / Formulas":"Fórmulas","设备数据库 / Machine DB":"Banco de Máquinas","刀具类型参数库 / Tool Type Library":"Biblioteca de Herramientas","夹具库 / Fixture Library":"Biblioteca de Utillajes","检具库 / Inspection Tool Library":"Biblioteca de Galgas","版本变更履历 / Version History":"Historial de Versiones","问题清单 / Issue List (DFM Format)":"Lista de Problemas (DFM)","项目类型":"Tipo de Proyecto","日可动时间":"Horas/Día","日班次":"Turnos/Día","月可动日":"Días/Mes","可动率":"Disponibilidad","客户名称":"Cliente","零件名称":"Nombre de Pieza","客户版本":"Versión Cliente","DFM完成时间":"Fecha DFM","长度 L":"Largo L","宽度 W":"Ancho W","高度 H":"Alto H","重量":"Peso","上传产品图":"Subir Imagen de Producto","未上传设备图":"Sin Imagen de Máquina","未上传夹具图":"Sin Imagen de Utillaje","工序":"Proceso","台":"u.","件":"pzs","次":"pasadas","刀号":"Nº Herr.","刀具型号":"Modelo Herr.","刀柄选型":"Portaherr.","配件选型":"Accesorio","加工内容":"Contenido","加工特征":"Característica","加工节拍":"Tiempo de Ciclo","切削参数与时间":"Parám. y Tiempos de Corte","转速n(rpm)":"n (rpm)","进给vf(mm/min)":"vf (mm/min)","每齿进给fz":"fz","线速度Vc":"Vc","长度L(mm)":"L (mm)","寿命(min)":"Vida (min)","定位精度":"Precisión","重复定位精度":"Repetibilidad","XYZ行程":"Recorrido XYZ","自定义":"Personalizado","基本":"Básico","大刀":"Herr. Grande","辅压紧":"Suj. Aux.","主压紧":"Suj. Principal","支撑缸":"Cilindro","开门":"Abrir Puerta","关门":"Cerrar Puerta","检测/吹屑":"Control/Soplado","快移时":"T. Rápido","换刀时":"T. Cambio","转台时":"T. Índice","主轴延时":"Retardo Husillo","总切削":"Corte Total","总非切削":"No Corte Total","总时间":"Tiempo Total","非切削":"No Corte","切削:":"Corte:","非切削(每刀):":"No Corte (por herr.):","产能:":"Capacidad:","节拍:":"Ciclo:","月产能(1台)":"Cap. Mensual (1 máq)","刀具类型：":"Tipo de Herr.:","刀具类型":"Tipo de Herr.","刀具数":"Herramientas","刀具总价(¥)":"Costo Herr. (¥)","单件刀具成本(¥)":"Costo/pza (¥)","夹具价格(¥)":"Utillaje (¥)","设备价格(万¥)":"Máquina (×10k ¥)","价格(¥)":"Precio (¥)","🔧 刀具系统":"🔧 Sistema de Herr.","快移距":"Dist. Rápida","检具名称":"Nombre de Galga","检具图号":"Nº de Plano","产品尺寸(mm)":"Tamaño producto (mm)","检具尺寸(mm)":"Tamaño galga (mm)","价格(万¥)":"Precio (×10k ¥)","设计周期(天)":"Diseño (días)","制造周期(天)":"Fabricación (días)","检具类别":"Categoría","检具名称（检具库选型）":"Nombre de Galga (desde biblioteca)","刀柄价格（刀具库-刀柄类）：":"Costo portaherr. (Bibl. Herr.): ","配件价格（刀具库-配件类）：":"Costo accesorios (Bibl. Herr.): ","本报价单按工序使用的配件小计：":"Accesorios usados en esta cotización: ","夹具价格（夹具库）：":"Costo utillaje (Bibl. Utill.): ","检具价格（检具库选型报价）：":"Costo galgas (selección): ","刀具成本：":"Costo de herramientas: ","设备价格：":"Precio de máquina: ","夹具/设备价格：":"Precio utillaje/máquina: ","以下参数用于节拍/产能计算，保存后立即生效。":"Estos parámetros se usan para el cálculo de ciclo/capacidad. Efectivos al guardar.","点击此处后按 Ctrl+V 粘贴图片":"Haga clic aquí y pulse Ctrl+V para pegar una imagen","点击此处后按 Ctrl+V 粘贴":"Haga clic aquí y pulse Ctrl+V para pegar","点击图片区域后按 Ctrl+V 粘贴/替换夹具图":"Haga clic en la zona de imagen y pulse Ctrl+V para pegar/reemplazar la imagen del utillaje","点击粘贴成品检具图":"Haga clic para pegar la imagen de la galga de producto terminado","点击粘贴毛坯检具图":"Haga clic para pegar la imagen de la galga de bruto","已选定图片位置，请按 Ctrl+V 粘贴":"Posición de imagen seleccionada; pulse Ctrl+V para pegar","默认显示上次夹具图":"Se muestra la última imagen de utillaje por defecto","在设备库中为该设备上传图片":"Suba una imagen para esta máquina en el Banco de Máquinas","显示自动生成的工艺流程图":"Mostrar el flujo de proceso autogenerado","记录项目版本变更历史，无需密码即可查看和编辑。":"Registra el historial de versiones del proyecto. Se puede ver y editar sin contraseña.","请在「产品尺寸与重量」中填写尺寸":"Complete las dimensiones en \"Dimensiones\"","选择毛坯检具与成品检具类型后，「项目信息」页工艺流程图自动显示对应节点（图片可点击粘贴上传）。检具价格请在「检具库」中维护。":"Al seleccionar los tipos de galga de bruto/producto terminado, el diagrama de flujo muestra los nodos correspondientes automáticamente (clic para pegar imágenes). Mantenga los precios de galgas en la Biblioteca de Galgas.","按四大类从检具库选型，价格/设计周期/制造周期直接引用检具库数据，成本信息与导出价格清单同步报价。":"Seleccione galgas de la biblioteca por cuatro categorías. Precio y ciclos de diseño/fabricación se referencian directamente de la biblioteca y se cotizan en Costos y en la lista de precios exportada.","已按检具清单导入五大类检具数据，可按产品尺寸/检具尺寸检索选型报价，价格单位为万元（未税）。":"Cinco categorías importadas de la lista; seleccione buscando por tamaño producto/galga; unidad: ×10⁴ CNY (sin impuestos).","修改后自动保存。设备图片点击上传或 Ctrl+V 粘贴，点击已上传图片可放大。设备库、刀具库、夹具库、检具库为管理员设置，工艺设置为独立密码。":"Guardado automático al editar. Suba imágenes de máquina con clic o Ctrl+V; clic en la imagen para ampliar. Máquinas/Herramientas/Utillajes/Galgas son de administrador; Configuración usa contraseña independiente.","库分类：高压项目刀具 / 差压项目刀具 / 刀柄 / 配件。刀柄与配件类型分国内/进口两类，不设转速、进给等切削参数（自动计算列显示 —）；切削刀具按铣刀/钻头等分类。可按库分类和刀具类型筛选，按录入顺序显示。修改后自动保存。":"Grupos: Herram. Alta Presión / Presión Diferencial / Portaherr. / Accesorios. Portaherramientas y accesorios: Nacional/Importado, sin parámetros de corte (columnas automáticas muestran -). Herramientas de corte clasificadas por fresa/broca etc. Filtre por grupo y tipo; en orden de registro. Guardado automático.","流程按「工艺设置」中的「工序管理」自动生成：包含机加工艺路线、夹具设计、节拍产能三大模块，检具在工艺设置中选择。工序数量变化或更换设备后自动更新。":"El flujo se autogenera desde la Gestión de Procesos en Configuración: ruta de mecanizado, diseño de utillaje y ciclo/capacidad. Las galgas se seleccionan en Configuración. Se actualiza al cambiar procesos o máquinas.","数据自动保存在 FastAPI 服务端。顶部可切换项目、立即保存、查看历史版本或恢复已删除项目；「导出数据(.json)」可生成离线备份。":"Los datos se guardan automáticamente en este navegador. Para compartir: exporte el archivo HTML compartido con todos los datos; use exportar/importar JSON para sincronizar copias.","「导出DFM报告(PPT)」按DFM模版生成PPTX（封面/设备选型/工件信息/工序刀具表/检具/Open issue）；项目完整数据由服务端保存，也可导出 JSON 离线备份。":"\"Exportar Informe DFM (PPT)\" genera un PPTX según la plantilla DFM; \"Exportar Archivo Compartido\" genera un HTML único con todos los datos e imágenes, se abre con doble clic.","Vc=π*D*n/1000 | vf=n*fz | t切=L/vf*60*次数*件数 | fz=vf/n":"Vc=π*D*n/1000 | vf=n*fz | tc=L/vf*60*pasadas*pzs | fz=vf/n","快移时=L快移/快移速度 + 换刀时(大刀×2) + 转台时 + 主轴延时":"Rápido=Lrápido/Vrápido + cambio de herr. (grande×2) + indexado + retardo de husillo","总切削+总非切削":"Corte total + no corte total","月可动时间*可动率/瓶颈节拍*机床数":"Horas mensuales × disponibilidad / ciclo cuello de botella × máquinas","+ 添加刀具":"+ Añadir Herramienta","+ 添加工序":"+ Añadir Proceso","+ 添加设备":"+ Añadir Máquina","+ 添加三轴夹具":"+ Añadir Utillaje 3 Ejes","+ 添加四轴夹具":"+ Añadir Utillaje 4 Ejes","+ 添加五轴夹具":"+ Añadir Utillaje 5 Ejes","+ 添加毛坯检具":"+ Añadir Galga de Bruto","+ 添加成品机械检具":"+ Añadir Galga Mecánica","+ 添加成品总成检具":"+ Añadir Galga de Conjunto","+ 添加成品电子检具":"+ Añadir Galga Electrónica","+ 新增版本记录":"+ Nueva Versión","+ 新增问题":"+ Nuevo Problema","夹具示意图":"Esquema de utillaje","加工":"Mecanizado","t切":"t_corte","设备型号":"Modelo de máquina","每把刀成本 = 刀具库价格 ÷ 刀具库寿命（自动引用刀具库数据）":"Coste por herramienta = precio biblio. ÷ vida biblio. (auto)","选设备时自动引用设备库价格（万元），也可手工修改":"Se rellena desde la BB.DD. de máquinas al seleccionar (×10⁴ CNY); editable","产品尺寸":"Tamaño de producto","检具尺寸":"Tamaño de galga","毛坯检具类型":"Tipo de galga en bruto","通用游标卡尺":"Calibre vernier","三坐标测量机":"MMC (coordenadas)","专用毛坯检具":"Galga dedicada en bruto","通止规":"Calibre pasa/no pasa","高度尺+杠杆表":"Altímetro + comparador","成品检具类型":"Tipo de galga acabada","高性能副车架 （整形检具）":"Subchasis alto rend. (galga conformación)","高性能副车架 （全检检具）":"Subchasis alto rend. (galga 100%)","导出价格清单":"Exportar lista de precios","导出DFM报告(PPT)":"Exportar informe DFM (PPT)","导出共享文件(含图片)":"Exportar archivo compartido (con imágenes)","导出数据(.json)":"Exportar datos (.json)","导入数据(.json)":"Importar datos (.json)","(自动)":"(Auto)","三轴夹具":"Utillaje 3 ejes","四轴夹具":"Utillaje 4 ejes","五轴夹具":"Utillaje 5 ejes","测量支架":"Soporte de medición","未选型":"Sin selección","— 未选型 —":"— Sin selección —","产品尺寸检索":"Buscar tamaño producto","检具尺寸检索":"Buscar tamaño galga","匹配选型（产品尺寸 / 检具尺寸）":"Selección coincidente (prod. / galga)","按五大类从检具库选型：输入产品尺寸/检具尺寸关键词检索，从匹配结果中选定，价格/设计周期/制造周期直接引用检具库数据，成本信息与导出价格清单同步报价。":"Seleccione de la biblioteca en 5 categorías: busque por tamaño producto/galga y elija entre coincidencias; precio/ciclos referencian la biblioteca; coste y exportación sincronizados.","请输入工艺设置密码":"Introduzca contraseña de ajustes","请输入管理员密码":"Introduzca contraseña de admin","密码错误":"Contraseña incorrecta","确认删除该版本记录？":"¿Eliminar este registro de versión?","数据已保存到本机浏览器":"Datos guardados en este navegador","请输入文件名：":"Introduzca nombre de archivo:","PPTX 组件未加载，请检查文件完整性":"Componente PPTX no cargado; verifique el archivo","暂无工序数据，请先在「工序管理」中添加工序":"Sin datos de proceso; añada primero en «Gestión de procesos»","删除图片?":"¿Eliminar imagen?","数据导入成功，已覆盖当前数据!":"¡Datos importados; datos actuales sobrescritos!","文件格式错误，请选择导出的 JSON 数据文件。":"Formato inválido; seleccione un archivo JSON exportado.","如 A / B / C 版":"p. ej. A / B / C","变更内容描述":"Descripción del cambio","如 347*326":"p. ej. 347*326","如 600*400":"p. ej. 600*400","+ 添加":"+ Añadir","夹具报价选型":"Selección de Cotización de Útiles","模具中心":"Centro de Molde","是否报价":"¿Cotizar?","夹具选型":"Selección de Útil","价格":"Precio","共":"Total","条":"ítems","类":"cat.","中心":"centro","夹具价格（夹具库选型报价）：":"Costo de útiles (selec. de Bib. Útiles): ","XYZ行程<br>mm":"Recorrido XYZ<br>mm","定位精度<br>mm":"Precisión pos.<br>mm","重复定位精度<br>mm":"Repetibilidad<br>mm","上传资料":"Subir Doc.","资料":"Doc.","资料过大（限 2MB），请压缩后上传":"Archivo grande (máx 2MB), comprímelo","删除资料?":"¿Borrar doc.?","已按类别导入检具数据，可按产品尺寸/检具尺寸检索选型报价，价格单位为万元（未税）；支持新增/删除自定义类别。":"Datos de calibres importados por categoría. Busque por tamaño de producto/calibre para cotizar; precios en 10k CNY (sin impuestos). Categorías personalizadas añadibles/eliminables.","新增类别":"+ Nueva Categoría","删除类别":"Borrar Categoría","该类别已存在":"Categoría existente","基础类别不可删除":"Categoría base fija","请输入新增检具类别名称：":"Nombre de nueva categoría de útiles:","请输入新增模具中心名称：":"Nombre de nuevo centro de molde:","夹具库说明：按模具中心分类维护夹具，名称/价格/制造周期/备注可直接编辑，报价在「夹具报价选型」中勾选引用。":"Mantenga útiles por centro de molde; nombre/precio/días/nota editables. La cotización se activa con casillas en Selección de Útiles.","+ 添加夹具":"+ Añadir Útil","备注":"Nota","项":"ítems","（按录入顺序显示）":"(en orden de registro)","D(mm)":"D(mm)","每齿进给fz<br>(自动)":"fz/diente<br>(auto)","线速度Vc<br>(自动)":"Vel. corte Vc<br>(auto)","无匹配":"Sin coincidencias","删除类别「":"Borrar categoría ","」及其下 ":" con sus "," 条数据？":" elementos?","PPTX 生成失败: ":"Error al generar PPTX: ","导出失败: ":"Error al exportar: ","点击后粘贴新图":"Haga clic y pegue imagen nueva","点击后按 Ctrl+V 粘贴新图":"Haga clic y pulse Ctrl+V para pegar imagen nueva","点击后按 Ctrl+V 粘贴/替换夹具图":"Haga clic y pulse Ctrl+V para pegar/reemplazar imagen de utillaje","下载资料":"Descargar documento","从刀具库选":"Elegir de la bibl. de herramientas","转速":"RPM","高性能副车架\n（整形检具）":"Subchasis alto rend. (galga conformación)","高性能副车架\n（全检检具）":"Subchasis alto rend. (galga 100%)","」？":"\"?","面铣刀":"Fresa plana","PCD面铣刀":"Fresa plana PCD","PCD-T型刀":"Fresa de ranura en T PCD","PCD倒角刀":"Fresa de chaflán PCD","PCD反勾刀":"Fresa de chaflán inverso PCD","PCD复合切槽刀":"Cortador de ranuras PCD","PCD锪刀":"Avellanador PCD","PCD铰刀":"Escariador PCD","PCD精镗刀":"Mandrinadora de precisión PCD","PCD盘刀":"Fresa de disco PCD","PCD球刀":"Fresa bola PCD","PCD铣刀":"Fresa PCD","PCD玉米铣刀":"Fresa de maíz PCD","PCD锥度刀":"Fresa cónica PCD","PCD钻铰刀":"Broca-escariador PCD","PCD钻头":"Broca PCD","U钻":"Broca U","波纹合金铣刀":"Fresa ondulada carburo","粗镗刀（刀片）":"Mandrinadora desbaste (pastilla)","合金倒角刀":"Fresa de chaflán carburo","合金挤压丝锥":"Machuelo de laminado carburo","合金内R铣刀":"Fresa R interior carburo","合金球刀":"Fresa bola carburo","合金球头铣刀":"Fresa de punta esférica carburo","合金铣刀":"Fresa carburo","合金锥度铣刀":"Fresa cónica carburo","合金钻头":"Broca carburo","网纹铣刀（刀片）":"Fresa estriada (pastilla)","合金钻铣刀":"Fresa-taladro carburo","PCD成型刀":"Fresa de forma PCD","PCD成型钻头":"Broca de forma PCD","合金阶梯钻":"Broca escalonada carburo","合金台阶钻":"Broca subland carburo","开粗镗刀":"Mandrinadora de desbaste","合金深孔钻":"Broca de agujero profundo carburo","PCD导条刀":"Herr. de guía PCD","PCD阶梯铰刀":"Escariador escalonado PCD","合金导条刀":"Herr. de guía carburo","合金铰刀":"Escariador carburo","合金阶梯铰刀":"Escariador escalonado carburo","合金钻铰刀":"Broca-escariador carburo","挤压丝锥":"Machuelo de laminado","切削丝锥":"Machuelo de corte","螺纹铣刀":"Fresa de roscar","PCD套刀":"Trepanadora PCD","毛刷":"Cepillo","换图":"Reemplazar","+粘贴":"+ Pegar","上传图片":"Subir imagen","保存失败：本机浏览器存储空间已满，请减少粘贴的图片数量，或使用另存为导出文件保存":"Error al guardar: el almacenamiento del navegador esta lleno. Reduzca las imagenes pegadas o use Guardar como para exportar.","从设备库引用价格":"Tomar precios de la BB.DD. de máquinas","已按设备库价格刷新设备成本":"Costos de máquina actualizados desde la BB.DD. de máquinas","已保存：全部数据已写入本文件":"Guardado: todos los datos escritos en este archivo","已保存：并已导出一份含全部数据的文件（见浏览器下载）":"Guardado: se descargó un archivo con todos los datos (ver descargas)","提示：「保存」会把全部数据写入服务端当前项目，并保留历史版本。":"Nota: Guardar escribe todos los datos en este archivo (la primera vez pregunta la ubicación); envíe ese archivo.","本报价单按工序使用的刀柄小计：":"Portaherramientas usados en esta cotización: "}};
function _cjk(s){return /[\u4e00-\u9fff]/.test(s);}
function _fr(t,fd){var ks=Object.keys(fd).sort(function(a,b){return b.length-a.length;});for(var i=0;i<ks.length;i++){if(t.indexOf(ks[i])>-1)t=t.split(ks[i]).join(fd[ks[i]]);}return t;}
function TR(s){if(!G||!G.lang||G.lang==='zh'||typeof s!=='string')return s;var d=I18N[G.lang];if(!d)return s;if(d[s])return d[s];var fd=AFRAG[G.lang];if(fd&&_cjk(s))return _fr(s,fd);return s;}
var FRAG={"en":{"机加工序-":"Machining ","节拍":"Cycle","月产能":"Cap./mo","快移":"Rapid","换刀":"TC","定位精度":"Pos. acc.","重复定位精度":"Repeatability","XYZ行程":"XYZ travel","把刀":"tools","切削":"Cutting","非切削":"Non-cut","装夹":"Load","主轴延时":"Dwell","把":"pcs","个":"pcs","种":"types","项（按录入顺序显示）":" items (entry order)","万¥":"×10⁴ CNY","对应":"Refs","模具中心":" Mold Center"},"th":{"机加工序-":"กลึง","节拍":"ไซเคิล","月产能":"ผลิต/เดือน","快移":"เร็ว","换刀":"TC","定位精度":"ความแม่น","重复定位精度":"แม่นซ้ำ","XYZ行程":"ระยะ XYZ","把刀":"ดอก","切削":"ตัด","非切削":"ไม่ตัด","装夹":"จับชิ้นงาน","主轴延时":"หน่วงเวลา","把":"ชิ้น","个":"ชิ้น","种":"ชนิด","项（按录入顺序显示）":" รายการ (ตามลำดับบันทึก)","万¥":"×10⁴ CNY","对应":"อ้างอิง","模具中心":" ศูนย์แม่พิมพ์"},"es":{"机加工序-":"Mecanizado ","节拍":"Ciclo","月产能":"Cap./mes","快移":"Rápido","换刀":"TC","定位精度":"Prec. pos.","重复定位精度":"Repetibilidad","XYZ行程":"Recorrido XYZ","把刀":"herr.","切削":"Corte","非切削":"No corte","装夹":"Carga","主轴延时":"Dwell","把":"pza","个":"pza","种":"tipos","项（按录入顺序显示）":" ítems (orden de registro)","万¥":"×10⁴ CNY","对应":"Ref.","模具中心":" Centro de moldes"}};
var AFRAG={"en":{"确认删除":"Confirm delete ","请输入":"Enter ","检具":"gauge ","刀具":"tool ","夹具":"fixture ","设备":"machine ","版本记录":"version record ","图片":"image ","生成失败":" failed","导出失败":"Export failed","「":"\"","」":"\"","？":"?"},"th":{"确认删除":"ยืนยันลบ ","请输入":"กรุณากรอก ","检具":"เกจ ","刀具":"tool ","夹具":"จิ๊ก ","设备":"เครื่องจักร ","版本记录":"รายการเวอร์ชัน ","图片":"รูปภาพ ","生成失败":" ล้มเหลว","导出失败":"ส่งออกล้มเหลว","「":"\"","」":"\"","？":"?"},"es":{"确认删除":"Confirmar eliminar ","请输入":"Introduzca ","检具":"galga ","刀具":"herramienta ","夹具":"utillaje ","设备":"máquina ","版本记录":"registro de versión ","图片":"imagen ","生成失败":" falló","导出失败":"Exportación fallida","「":"\"","」":"\"","？":"?"}};
(function(){try{var _a=window.alert,_p=window.prompt,_c=window.confirm;if(_a)window.alert=function(m){return _a(TR(m));};if(_p)window.prompt=function(m,dft){return _p(TR(m),dft);};if(_c)window.confirm=function(m){return _c(TR(m));};}catch(e){}})();
function admGo(){if(checkAdm()){curTab=SI+3;render();}}

// ===== CALC =====
function calcT(t){var n=t.n||0,vf=t.vf||0;t._ct=vf>0?(t.ln/vf*60)*t.ps*t.cn:0;t._vc=Math.round((Math.PI*t.d*n)/1000);t._vf=vf;t._fz=n>0?vf/n:0;return t._ct;}
function st(tl){var s=0;for(var i=0;i<tl.length;i++)s+=calcT(tl[i]);return s;}
function gm(pi){var pr=PR[pi]||{},mid=pr.mid;
  if(mid&&typeof MachinesPage!=='undefined'){var hit=MachinesPage.machineById(mid);if(hit)return hit;}
  var idx=pr.mi;return(idx>=0&&idx<MDB.length)?MDB[idx]:MDB[MDB.length-1];}
// 工序默认设备：新增工序时用设备库里的兜底机型。
function midOf(pi){var pr=PR[pi]||{};if(pr.mid)return pr.mid;var m=gm(pi);return(m&&m.id)||'';}
function midIndex(mid){for(var i=0;i<MDB.length;i++)if(MDB[i].id===mid)return i;return -1;}
function midOf2(i){return(MDB[i]&&MDB[i].id)||'';}
// 工序设备改用稳定 id：同时更新派生下标 mi，供旧计算/导出路径使用。
function setProcMachine(p,mid){if(ppOn()){ProcessPage.setMachine(p,mid);return;}var idx=midIndex(mid);PR[p].mid=mid;PR[p].mi=idx<0?(MDB.length?MDB.length-1:0):idx;var m=MDB[PR[p].mi];var np=parseFloat(m&&m.price);if(!isNaN(np)&&np>0)PR[p].eqP=np;render();}
function gR(pi){var r=(gm(pi).rapid||0)*1000/60;return r>0?r:500;}
function gTC(pi){return gm(pi).tc;}
function nct(pi){var pr=PR[pi],nc=pr.nc||{cc:2,co:2,mc_:2,sc:2,ac:1,it:5},m=gm(pi),rs=gR(pi),tc=gTC(pi);var cl=nc.cc+nc.co+nc.mc_+nc.sc+nc.ac,tt=0,ttc=0,tbl=0,sd=0;for(var i=0;i<pr.tl.length;i++){var t=pr.tl[i];tt+=rs>0?(t.td||500)/rs:0;ttc+=t.bg?tc*2:tc;tbl+=t.tt||2;sd+=t.sd||1;}return cl+ttc+tt+tbl+sd+(nc.it||5);}
function getNCperTool(pi,i){var pr=PR[pi],nc=pr.nc,m=gm(pi),rs=gR(pi),tc=gTC(pi);var t=pr.tl[i];var trav=(t.td||500)/rs,tcT=t.bg?tc*2:tc;return trav+tcT+(t.tt||2)+(t.sd||1);}
function sec(){return G.hpd*3600*G.dpm*G.avl;}
function cap(takt,mc){return takt>0?sec()/takt*mc:0;}
function f(v,d){d=d||1;return parseFloat(v||0).toFixed(d);}
function fi(v){return Math.round(v).toLocaleString();}

// 页签序号（**固定**，不再跟工序数量挂钩）：
//   0 项目信息 → 1 工序（总表，行内选设备，点「刀具」进单道工序详情）→ 2 夹具选型 → 3 检具选型
//   → 4 问题清单 → 5 版本履历 →（后台）6 工艺设置 → 7 设备库 → 8 刀具库 → 9 夹具库 → 10 检具库
// 老版本把"每道工序"各做成一个页签，工序一多页签就爆掉；现在工序只有一张总表，
// 单道工序的刀具明细在总表里点进去看（procView = 正在看的那道工序下标，-1 表示看总表）。
var SI=4;
var curTab=0;
var procView=-1;
function openProc(pi){procView=pi;curTab=1;render();}
function closeProc(){procView=-1;render();}
function bInspDB(){
  if(!checkAdm())return;
  // 检具库由 gauges.js 独立维护（按检具类别分组，每行独立存库，图片走 assets 接口）。
  if(typeof GaugesPage!=='undefined')return GaugesPage.render();
  return '<div class="panel on"><div class="card"><div class="card-bd"><div class="note">'+TR('检具库模块未加载，请刷新页面。')+'</div></div></div></div>';
}
function addI(ct){if(typeof GaugesPage!=='undefined'){GaugesPage.add(ct);return;}IDB.push({type:ct,name:'新检具',img:null,price:0,drw:'',prdSize:'',inspSize:'',dc:0,mc:0});render();}
function delI(i){if(confirm(TR('确认删除检具「')+IDB[i].name+TR('」？'))){IDB.splice(i,1);render();}}
function inspClasses(){return ICN.concat(G.icnX||[]);}
function fixClasses(){return FCN.concat(G.fcnX||[]);}
function addInspClass(){if(typeof GaugesPage!=='undefined'){GaugesPage.addGroup();return;}var nm=prompt(TR('请输入新增检具类别名称：'));if(nm==null)return;nm=String(nm).trim();if(!nm)return;var L=inspClasses();for(var i=0;i<L.length;i++){if(L[i]===nm){alert(TR('该类别已存在'));return;}}G.icnX=G.icnX||[];G.icnX.push(nm);save();render();}
function delInspClass(k){var nm=inspClasses()[k];if(nm==null)return;if(typeof GaugesPage!=='undefined'){GaugesPage.removeGroup(nm);return;}var L=inspClasses();if(k<ICN.length){alert(TR('基础类别不可删除'));return;}var c=0;for(var i=0;i<IDB.length;i++){if((IDB[i].type||'')===nm)c++;}if(!confirm(TR('删除类别「')+nm+TR('」及其下 ')+c+TR(' 条数据？')))return;var nv=[];for(var j=0;j<IDB.length;j++){if((IDB[j].type||'')!==nm)nv.push(IDB[j]);}IDB=nv;G.icnX.splice(k-ICN.length,1);save();render();}
function addFixClass(){if(typeof FixturesPage!=='undefined'){FixturesPage.addGroup();return;}var nm=prompt(TR('请输入新增模具中心名称：'));if(nm==null)return;nm=String(nm).trim();if(!nm)return;var L=fixClasses();for(var i=0;i<L.length;i++){if(L[i]===nm){alert(TR('该类别已存在'));return;}}G.fcnX=G.fcnX||[];G.fcnX.push(nm);save();render();}
function delFixClass(k){var nm=fixClasses()[k];if(nm==null)return;if(typeof FixturesPage!=='undefined'){FixturesPage.removeGroup(nm);return;}var L=fixClasses();if(k<FCN.length){alert(TR('基础类别不可删除'));return;}var c=0;for(var i=0;i<FDB.length;i++){if((FDB[i].center||'')===nm)c++;}if(!confirm(TR('删除类别「')+nm+TR('」及其下 ')+c+TR(' 条数据？')))return;var nv=[];for(var j=0;j<FDB.length;j++){if((FDB[j].center||'')!==nm)nv.push(FDB[j]);}FDB=nv;G.fcnX.splice(k-FCN.length,1);save();render();}
function setInspSel2(el){var k=parseInt(el.getAttribute('data-i'),10);var v=el.getAttribute('data-k');if(v==null)return;setInspSel(k,v);}
function addFByEl(el){var ct=el.getAttribute('data-ct');if(ct)addF(ct);}
function addIByEl(el){var ct=el.getAttribute('data-ct');if(ct)addI(ct);}
function uploadDoc(i){var row=MDB[i];if(typeof MachinesPage!=='undefined'&&row&&row.id){MachinesPage.pickDoc(row.id);return;}var f=document.createElement('input');f.type='file';f.onchange=function(e){if(!e.target.files||!e.target.files[0])return;var fl=e.target.files[0];if(fl.size>2*1024*1024){alert(TR('资料过大（限 2MB），请压缩后上传'));return;}var r=new FileReader();r.onload=function(ev){MDB[i].doc=ev.target.result;MDB[i].docName=fl.name||'资料';render();};r.readAsDataURL(fl);};f.click();}
function bVersion(){
  var h='<div class="panel on"><div class="card"><div class="card-hd"><h2>版本变更履历 / Version History</h2></div><div class="card-bd"><div class="tbw"><table><thead><tr><th>日期</th><th>版本</th><th>变更内容</th><th>变更人</th><th>操作</th></tr></thead><tbody>';
  for(var i=0;i<VH.length;i++){var v=VH[i];
    h+='<tr><td><input type="date" value="'+(v.dt||'')+'" style="width:125px" onchange="hpSet('+i+',\'dt\',this)"></td>'+
    '<td><input class="txt" value="'+(v.ver||'')+'" style="width:80px" placeholder="V1.0" onchange="hpSet('+i+',\'ver\',this)"></td>'+
    '<td><textarea rows="2" style="width:330px;resize:vertical" placeholder="变更内容描述" onchange="hpSet('+i+',\'ds\',this)">'+String(v.ds||'').split('&').join('&amp;').split('<').join('&lt;')+'</textarea></td>'+
    '<td><input class="txt" value="'+(v.by||'')+'" style="width:80px" placeholder="变更人" onchange="hpSet('+i+',\'by\',this)"></td>'+
    '<td><button class="act" onclick="delVH('+i+')">X</button></td></tr>';}
  h+='</tbody></table></div><button class="btn btn-g" onclick="addVH()">+ 新增版本记录</button><div class="note">记录项目版本变更历史，无需密码即可查看和编辑。</div></div></div></div>';
  // 下半部分：变更流水时间线（阶段 4）：label 是主行、extra 折行小字，只读 + 按实体过滤。
  // 段落外壳由 changes_page.js 出；真正的接口请求发生在切到这个页签（sw）或点过滤按钮时。
  if(typeof ChangesPage!=='undefined')h+=ChangesPage.section();
  return h;
}
// 版本履历已落表（3a）时，下面这些"写入点"统一交给 HistoryPage 走行级保存；
// 开关没开就还是老路子：改内存 + 整份保存（行为与改造前完全一致）。
function hpOn(){return typeof HistoryPage!=='undefined'&&HistoryPage.enabled();}
function hpSet(i,k,el){var v=el?el.value:'';if(hpOn()){HistoryPage.setField(i,k,v);return;}VH[i][k]=v;render();}
function hpToday(){var d=new Date();return d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+d.getDate()).slice(-2);}
function addVH(){var rec={dt:hpToday(),ver:'',ds:'',by:''};if(hpOn()){HistoryPage.add(rec);return;}VH.push(rec);render();}
function delVH(i){if(confirm(TR('确认删除该版本记录？'))){if(hpOn()){HistoryPage.remove(i);return;}VH.splice(i,1);render();}}
// 「保存」（写服务端当前项目）与「另存为新项目」由 host.js 接管：
// 页面起来后 window.saveAll 立刻把当前项目存到服务端、window.saveAs 复制成新项目；
// 卡片里的两个入口是导出（导出 JSON / 导出文件包），不再有"保存成单文件"的承诺。
// 切到「版本履历」页签时，下半部分的变更流水才去拉一次（之后的纯重绘不重复打接口）。
function sw(i){curTab=i;if(i===SI+1&&typeof ChangesPage!=='undefined')ChangesPage.enter();render();}

function render(){
  var bar=document.getElementById("tabBar"),si=SI;
  if(curTab===si+2&&!dbUnl)curTab=0;
  if(curTab>=si+3&&curTab<=si+6&&!adUnl)curTab=0;if(curTab>si+6)curTab=0;
  var h='<button class="tab setup-tab'+(curTab===0?' on':'')+'" onclick="sw(0)">项目信息<br><span style="font-size:8px;opacity:0.6">Project</span></button>';
  h+='<button class="tab setup-tab'+(curTab===1?' on':'')+'" onclick="sw(1)">工序<br><span style="font-size:8px;opacity:0.6">Processes</span></button>';
  h+='<button class="tab setup-tab'+(curTab===2?' on':'')+'" onclick="sw(2)">夹具选型<br><span style="font-size:8px;opacity:0.6">Fixtures</span></button>';
  h+='<button class="tab setup-tab'+(curTab===3?' on':'')+'" onclick="sw(3)">检具选型<br><span style="font-size:8px;opacity:0.6">Gauges</span></button>';
  h+='<button class="tab'+(curTab===si?' on':'')+'" onclick="sw('+si+')">问题清单<br><span style="font-size:8px;opacity:0.6">Issues</span></button>';
  h+='<button class="tab'+(curTab===si+1?' on':'')+'" onclick="sw('+(si+1)+')">版本履历<br><span style="font-size:8px;opacity:0.6">Versions</span></button>';
  if(dbUnl)h+='<button class="tab db-tab dash-tab'+(curTab===si+2?' on':'')+'" onclick="sw('+(si+2)+')">工艺设置<br><span style="font-size:8px;opacity:0.6">Settings</span></button>';
  else h+='<button class="tab db-tab dash-tab" onclick="setGo()">⚙ 工艺设置<br><span style="font-size:8px;opacity:0.6">Settings</span></button>';
  if(adUnl){
  h+='<button class="tab db-tab'+(curTab===si+3?' on':'')+'" onclick="sw('+(si+3)+')">设备库<br><span style="font-size:8px;opacity:0.6">Machines</span></button>';
  h+='<button class="tab db-tab'+(curTab===si+4?' on':'')+'" onclick="sw('+(si+4)+')">刀具库<br><span style="font-size:8px;opacity:0.6">Tool Lib</span></button>';
  h+='<button class="tab db-tab'+(curTab===si+5?' on':'')+'" onclick="sw('+(si+5)+')">夹具库<br><span style="font-size:8px;opacity:0.6">Fixtures</span></button>';
  h+='<button class="tab db-tab'+(curTab===si+6?' on':'')+'" onclick="sw('+(si+6)+')">检具库<br><span style="font-size:8px;opacity:0.6">Insp Tools</span></button>';
  }else h+='<button class="tab db-tab" onclick="admGo()">🔒 管理设置<br><span style="font-size:8px;opacity:0.6">Admin</span></button>';
  // 回收站（阶段 4）：只读入口，登录后才有；服务端没开这个接口时 TrashPage 自己降级成空串（整块不出现）
  if(typeof TrashPage!=='undefined')h+=TrashPage.tabEntry();
  if(dbUnl||adUnl)h+='<button class="tab db-tab" onclick="lockAdmin()">退出<br><span style="font-size:8px;opacity:0.6">Exit</span></button>';
  bar.innerHTML=h;
  var main=document.getElementById("mainPanels");
  if(curTab===0)main.innerHTML=bSetup();
  else if(curTab===1)main.innerHTML=procView>=0?bProcess(procView):bProcessTable();
  else if(curTab===2)main.innerHTML=bFixtureSelect();
  else if(curTab===3)main.innerHTML=bGaugeSelect();
  else if(curTab===si)main.innerHTML=bIssues();
  else if(curTab===si+1)main.innerHTML=bVersion();
  else if(curTab===si+2)main.innerHTML=bSettings();
  else if(curTab===si+3)main.innerHTML=bMachDB();
  else if(curTab===si+4)main.innerHTML=bToolDB();
  else if(curTab===si+5)main.innerHTML=bFixDB();
  else if(curTab===si+6)main.innerHTML=bInspDB();

  var hc=document.getElementById("hdrCust"),hp=document.getElementById("hdrPart");
  if(hc)hc.textContent=G.cust;if(hp)hp.textContent=G.part;
  var _ls=document.getElementById("langSel");if(_ls&&_ls.value!==(G.lang||"zh"))_ls.value=G.lang||"zh";
  try{if(G.lang&&G.lang!=="zh")applyLang();}catch(e){}
  try{for(var _qi=0;_qi<inspClasses().length;_qi++)iqFilter(_qi);for(var _fi=0;_fi<fixClasses().length;_fi++)fixFilter(_fi);}catch(e){}
  save();
}
function imgShrink(d,cb){try{if(!d||typeof Image==='undefined'||!document.createElement){cb(d);return;}if(d.length<120000){cb(d);return;}var im=new Image();im.onload=function(){try{var mx=900,w=im.width,h=im.height;if(!w||!h){cb(d);return;}if(w>mx||h>mx){var k2=mx/Math.max(w,h);w=Math.round(w*k2);h=Math.round(h*k2);}var c=document.createElement('canvas');c.width=w;c.height=h;var g=c.getContext('2d');if(!g){cb(d);return;}g.fillStyle='#fff';g.fillRect(0,0,w,h);g.drawImage(im,0,0,w,h);var u=c.toDataURL('image/jpeg',0.8);cb(u&&u.length<d.length?u:d);}catch(e2){cb(d);}};im.onerror=function(){cb(d);};im.src=d;}catch(e){cb(d);}}
function shrinkImgs(){try{var lst=[];function _col(A,f){for(var i=0;i<A.length;i++){var v=A[i][f];if(typeof v==='string'&&v.length>150000)lst.push([A,i,f,v]);}}_col(MDB,'img');_col(IDB,'img');_col(FDB,'img');_col(TDB,'tI');_col(PR,'cI');_col(IS,'bI');_col(IS,'aI');if(!lst.length)return;var done=0;lst.forEach(function(it){imgShrink(it[3],function(u){if(u!==it[3])it[0][it[1]][it[2]]=u;done++;if(done===lst.length)save();});});}catch(e){}}
function pickImg(fn){var f=document.createElement('input');f.type='file';f.accept='image/*';f.onchange=function(e){var r=new FileReader();r.onload=function(ev){imgShrink(ev.target.result,fn)};if(e.target.files[0])r.readAsDataURL(e.target.files[0])};f.click();}
function armPaste(fn){window._icb=fn;var t=document.getElementById('pasteHint');if(!t){t=document.createElement('div');t.id='pasteHint';t.style.cssText='position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(26,54,93,0.92);color:#fff;padding:14px 26px;border-radius:10px;font-size:13px;z-index:99999;pointer-events:none;box-shadow:0 4px 16px rgba(0,0,0,0.3)';document.body.appendChild(t);}t.textContent=TR('已选定图片位置，请按 Ctrl+V 粘贴');t.style.display='block';clearTimeout(window._pht);window._pht=setTimeout(function(){t.style.display='none'},8000);}
function imgSlot(setter,src,ph){var fn='function(u){'+setter+'=u;render()}';return '<div style="text-align:center">'+(src?'<img src="'+src+'" style="max-width:100%;max-height:400px;border-radius:8px;cursor:pointer" title="'+TR('点击后按 Ctrl+V 粘贴新图')+'" onclick="armPaste('+fn+')">':'<div style="padding:54px;border:2px dashed #cbd5e0;border-radius:8px;color:#a0aec0;font-size:11px;cursor:pointer" onclick="armPaste('+fn+')">'+ph+'<br><span style="font-size:9px">点击此处后按 Ctrl+V 粘贴图片</span></div>')+(src?'<div style="margin-top:5px;font-size:10px"><a style="cursor:pointer;color:#e53e3e" onclick="if(confirm(\'删除图片?\')){('+fn+')(null);render()}">删除</a></div>':'')+'</div>';}

function bSetup(){
  // 项目信息已重构：字段落在服务端 project_settings 表（一行一个项目），
  // 由 ProjectInfoPage 逐字段读写；旧内存对象 G 仍由服务端组合视图喂满，其它页面不受影响。
  if(window.ProjectInfoPage)return window.ProjectInfoPage.render();
  var h='<div class="panel on">'+
    '<div class="card"><div class="card-hd"><h2>客户与零件 / Customer & Part</h2></div><div class="card-bd">'+
      '<div class="r"><span class="l">客户名称<br><span class="u">Customer</span></span><input id="gs0" class="txt" value="'+G.cust+'" onchange="sve();render()"></div>'+
      '<div class="r"><span class="l">零件名称<br><span class="u">Part Name</span></span><input id="gs1" class="txt" value="'+G.part+'" onchange="sve();render()"></div>'+
      '<div class="r"><span class="l">客户版本<br><span class="u">Customer Ver</span></span><input id="gsVer" class="txt" value="'+(G.custVer||'')+'" placeholder="如 A / B / C 版" onchange="sve();render()"></div>'+
      '<div class="r"><span class="l">DFM完成时间<br><span class="u">DFM Date</span></span><input id="gsDate" class="txt" type="date" value="'+(G.dfmDate||'')+'" onchange="sve();render()"></div>'+
    '</div></div>'+
    '<div class="card"><div class="card-hd"><h2>产品图片 / Product Image</h2></div><div class="card-bd">'+
      '<div style="text-align:center">'+imgSlot('G.pI',G.pI,'上传产品图')+'</div>'+
      '<div style="margin-top:6px;text-align:center;font-size:10px;color:var(--s)">'+(G.len||G.wid||G.hgt||G.wgt?'尺寸 '+G.len+' × '+G.wid+' × '+G.hgt+' mm · 重量 '+G.wgt+' kg':'请在「产品尺寸与重量」中填写尺寸')+'</div>'+
    '</div></div>'+
    '<div class="card"><div class="card-hd"><h2>产品尺寸与重量 / Dimensions</h2></div><div class="card-bd"><div class="size-grid">'+
      '<div class="r"><span class="l">长度 L<br><span class="u">Length</span></span><input id="gsLen" class="size-card" type="number" value="'+G.len+'" step="0.1" onchange="sve();render()"><span class="u">mm</span></div>'+
      '<div class="r"><span class="l">宽度 W<br><span class="u">Width</span></span><input id="gsWid" class="size-card" type="number" value="'+G.wid+'" step="0.1" onchange="sve();render()"><span class="u">mm</span></div>'+
      '<div class="r"><span class="l">高度 H<br><span class="u">Height</span></span><input id="gsHgt" class="size-card" type="number" value="'+G.hgt+'" step="0.1" onchange="sve();render()"><span class="u">mm</span></div>'+
      '<div class="r"><span class="l">重量<br><span class="u">Weight</span></span><input id="gsWgt" class="size-card" type="number" value="'+G.wgt+'" step="0.01" onchange="sve();render()"><span class="u">kg</span></div>'+
    '</div></div></div>'+
    '<div class="fbox" style="background:#ebf8ff;border-color:#90cdf4;color:#2b6cb0">数据自动保存在 FastAPI 服务端。顶部可切换项目、立即保存、查看历史版本或恢复已删除项目；「导出数据(.json)」可生成离线备份。</div>'+
    '<div class="card"><div class="card-hd"><h2>工艺流程图 / Process Flow</h2></div><div class="card-bd">'+
      '<label style="display:flex;align-items:center;gap:6px;font-size:12px;margin-bottom:8px;cursor:pointer"><input type="checkbox" id="flowChk"'+(G.showFlow?' checked':'')+' onchange="G.showFlow=this.checked?1:0;render()"> 显示自动生成的工艺流程图</label>'+
      (G.showFlow?bFlow()+'<div class="flow-legend">流程按「工艺设置」中的「工序管理」自动生成：包含机加工艺路线、夹具设计、节拍产能三大模块，检具在工艺设置中选择。工序数量变化或更换设备后自动更新。</div>':'<div style="padding:20px;text-align:center;color:#a0aec0;font-size:11px;border:2px dashed #cbd5e0;border-radius:8px">自动工艺流程图已关闭<br><span style="font-size:9px">可在上方开关中重新开启</span></div>')+
      '</div></div>';
  return h;
}
// 工艺流程自动生成：每道工序一个节点，显示设备图片与信息
function bFlow(){
  var h='<div class="flow-modules">';
  // 模块1：机加工艺路线（毛坯检具→工序设备→成品检具，同一 flow-wrap）
  h+='<div class="card" style="margin-top:0"><div class="card-hd"><h2>机加工艺路线 / Machining Process Route</h2></div><div class="card-bd"><div class="flow-wrap">';
  if(G.bInspType){
    h+='<div class="flow-node"><div class="fn-name">毛坯检具</div>'+
      '<div class="fn-img">'+(G.bInspImg?'<img src="'+G.bInspImg+'" onclick="openImg(\''+G.bInspImg+'\')">':'<span>未上传检具图</span>')+'</div>'+
      '<div class="fn-m">'+G.bInspType+'</div>'+
      '<div class="fn-i">毛坯检具<br>Blank Inspection</div></div>';
    h+='<div class="flow-arrow">→</div>';
  }
  for(var p=0;p<PR.length;p++){
    var m=gm(p);
    if(p>0)h+='<div class="flow-arrow">→</div>';
    h+='<div class="flow-node"><div class="fn-name">'+PR[p].nm+'</div>'+
      '<div class="fn-img">'+(m.img?'<img src="'+m.img+'" onclick="openImg(\''+m.img+'\')">':'<span>未上传设备图</span>')+'</div>'+
      '<div class="fn-m">'+m.brand+' '+m.model+'</div>'+
      '<div class="fn-i">快移 '+m.rapid+' m/min · 换刀 '+m.tc+'s<br>'+TR('转速')+' '+m.spm+' rpm · ATC '+m.atc+'</div>'+
      '<div class="fn-info">'+(m.xyz?'XYZ行程 '+m.xyz+'<br>':'')+(m.pa?'定位精度 '+m.pa+'<br>':'')+(m.rpa?'重复定位精度 '+m.rpa:'')+'</div>'+
      '</div>';
  }
  if(G.fInspType){
    h+='<div class="flow-arrow">→</div>';
    h+='<div class="flow-node"><div class="fn-name">成品检具</div>'+
      '<div class="fn-img">'+(G.fInspImg?'<img src="'+G.fInspImg+'" onclick="openImg(\''+G.fInspImg+'\')">':'<span>未上传检具图</span>')+'</div>'+
      '<div class="fn-m">'+G.fInspType+'</div>'+
      '<div class="fn-i">成品检具<br>Finished Inspection</div></div>';
  }
  h+='</div></div></div>';
  // 模块2：夹具设计（与机加工序对应）
  h+='<div class="card" style="margin-top:8px"><div class="card-hd"><h2>夹具设计 / Fixture Design（与机加工序对应）</h2></div><div class="card-bd"><div class="flow-wrap">';
  for(var p=0;p<PR.length;p++){
    if(p>0)h+='<div class="flow-arrow">→</div>';
    h+='<div class="flow-node"><div class="fn-name">'+PR[p].nm+'</div>'+
      '<div class="fn-img">'+(PR[p].cI?'<img src="'+PR[p].cI+'" onclick="openImg(\''+PR[p].cI+'\')">':'<span>未上传夹具图</span>')+'</div>'+
      '<div class="fn-i">夹具示意图</div>'+
      '<div class="fn-info">对应 '+PR[p].nm+'</div></div>';
  }
  h+='</div></div></div>';
  // 模块3：节拍产能（每道工序，无汇总页）
  h+='<div class="card" style="margin-top:8px"><div class="card-hd"><h2>节拍产能 / Cycle Time & Capacity</h2></div><div class="card-bd"><div class="flow-wrap">';
  for(var p=0;p<PR.length;p++){
    var tk=st(PR[p].tl)+nct(p),cp=cap(tk,PR[p].mc);
    if(p>0)h+='<div class="flow-arrow">→</div>';
    h+='<div class="flow-node"><div class="fn-name">'+PR[p].nm+'</div>'+
      '<div class="fn-stat">节拍 '+f(tk,0)+'s<br>月产能 '+fi(cp)+' 件</div></div>';
  }
  h+='</div></div></div>';
  h+='</div>';
  return h;
}
function sve(){var el=document.getElementById("gs0");if(el)G.cust=el.value||G.cust;el=document.getElementById("gs1");if(el)G.part=el.value||G.part;el=document.getElementById("gsVer");if(el){if((el.value||'')!==(G.custVer||''))verRec(G.custVer,el.value);G.custVer=el.value;}el=document.getElementById("gsDate");if(el)G.dfmDate=el.value;el=document.getElementById("gs4");if(el)G.hpd=parseFloat(el.value)||G.hpd;el=document.getElementById("gs5");if(el)G.sft=parseFloat(el.value)||G.sft;el=document.getElementById("gs6");if(el)G.dpm=parseFloat(el.value)||G.dpm;el=document.getElementById("gs7");if(el)G.avl=parseFloat(el.value)/100||G.avl;el=document.getElementById("gsLen");if(el)G.len=parseFloat(el.value)||0;el=document.getElementById("gsWid");if(el)G.wid=parseFloat(el.value)||0;el=document.getElementById("gsHgt");if(el)G.hgt=parseFloat(el.value)||0;el=document.getElementById("gsWgt");if(el)G.wgt=parseFloat(el.value)||0;el=document.getElementById("gsPrj");if(el)G.prj=el.value;}
// 工序已落表（1b）时，下面这些"写入点"统一交给 ProcessPage 走行级保存；
// 开关没开就还是老路子：改内存 + 整份保存（行为与改造前完全一致）。
function ppOn(){return typeof ProcessPage!=='undefined'&&ProcessPage.enabled();}
function addProc(){if(ppOn()){ProcessPage.addProcess();return;}var mid=(typeof MachinesPage!=='undefined')?MachinesPage.defaultId():'';var idx=midIndex(mid);PR.push({nm:"机加工序-OP"+(PR.length+1)*10,mid:mid,mi:idx<0?(MDB.length?MDB.length-1:0):idx,mc:1,cI:null,fixP:0,eqP:0,nc:{cc:2,co:2,mc_:2,sc:2,ac:1,it:5},tl:[]});procView=-1;render();}
function delProc(pi){if(ppOn()){ProcessPage.removeProcess(pi);return;}if(PR.length<=1)return;PR.splice(pi,1);if(procView===pi)procView=-1;else if(procView>pi)procView=procView-1;render();}

// ---------------- 工序（总表）：项目 → 工序 → 设备 ----------------
// 一行 = 一道工序：名字、台数、**这台工序用哪台设备**（行内直接选）、节拍与月产能，
// 再往右是"点进单道工序看刀具"的入口。设备写在工序行上（每道工序一台），
// 所以换设备不用进工序详情、也不用跳"工艺设置"。
function bProcessTable(){
  var h='<div class="panel on"><div class="card"><div class="card-hd"><h2>工序 / Processes</h2><p>'+TR('每道工序一台设备：先在设备库里维护好设备，再在这里逐道工序选设备；点"刀具"进单道工序明细。')+'</p></div><div class="card-bd">';
  if(!PR.length)h+='<div class="note">'+TR('还没有工序，点下面的「添加工序」开始。')+'</div>';
  else{
    h+='<div class="tbw"><table><thead><tr><th style="width:40px">#</th><th>'+TR('工序名')+'</th><th>'+TR('设备')+'</th><th style="width:60px">'+TR('台数')+'</th><th>'+TR('刀具')+'</th><th>'+TR('节拍(s)')+'</th><th>'+TR('月产能(pcs)')+'</th><th style="width:120px"></th></tr></thead><tbody>';
    for(var p=0;p<PR.length;p++){
      var pr=PR[p],m=gm(p),c=st(pr.tl),ncut=nct(p),takt=c+ncut;
      var mimg=m.img;
      h+='<tr><td>'+(p+1)+'</td>'+
        '<td><input value="'+pr.nm+'" style="width:140px" onchange="'+(ppOn()?('ProcessPage.setProcessField('+p+',\'nm\',this.value)'):('PR['+p+'].nm=this.value'))+'"></td>'+
        '<td>'+(mimg?'<img class="proc-thumb" src="'+mimg+'" onclick="openImg(\''+mimg+'\')">':'')+
        '<select onchange="setProcMachine('+p+',this.value)" style="max-width:260px">';
      // 空值 = 不指定（读模型退回兜底机型），比"悄悄替你选一台"更清楚
      h+='<option value=""'+(midOf(p)?'':' selected')+'>'+TR('（未指定·用兜底机型）')+'</option>';
      for(var mi=0;mi<MDB.length;mi++)h+='<option value="'+midOf2(mi)+'"'+(midOf(p)===midOf2(mi)?' selected':'')+'>'+MDB[mi].brand+' '+MDB[mi].model+(MDB[mi].is_fallback?'（兜底）':'')+'</option>';
      h+='</select>'+((midOf(p)&&!m.brand)?'<span class="note" style="color:#c53030"> '+TR('设备库里找不到，请重选')+'</span>':'')+'</td>'+
        '<td><input type="number" value="'+pr.mc+'" style="max-width:50px" min="1" onchange="'+(ppOn()?('ProcessPage.setProcessField('+p+',\'mc\',this.value)'):('PR['+p+'].mc=parseFloat(this.value)||1'))+'"></td>'+
        '<td>'+pr.tl.length+' '+TR('把')+'</td><td>'+f(takt,0)+'</td><td>'+fi(cap(takt,pr.mc))+'</td>'+
        '<td><button class="act" onclick="openProc('+p+')">'+TR('刀具')+'</button>'+
        '<button class="act" onclick="delProc('+p+')">X</button></td></tr>';
    }
    h+='</tbody></table></div>';
    h+='<div class="fbox" style="margin-top:8px">'+TR('合计：')+PR.length+TR(' 道工序 · 总节拍 ')+f((function(){var t=0;for(var q=0;q<PR.length;q++)t+=st(PR[q].tl)+nct(q);return t;})(),0)+TR(' s · 瓶颈月产能 ')+(PR.length?fi(Math.min.apply(null,PR.map(function(_,q){return cap(st(PR[q].tl)+nct(q),PR[q].mc)}))):'0')+TR(' pcs（按最慢的一道工序算）')+'</div>';
  }
  h+='<div class="btn-row"><button class="btn btn-g" onclick="addProc()">+ '+TR('添加工序')+'</button><button class="btn btn-s" onclick="refEqPrice()">'+TR('按设备库价格刷新设备成本')+'</button></div>';
  h+='</div></div></div>';
  return h;
}

// 两页选型的合计行（与 setFixSel/setInspSel 现算的口径一致：只算勾了"要报价"的格子）
function fixCostHtml(){
  var FC=fixClasses(),n=0,t=0;
  for(var k=0;k<FC.length;k++){if(G.fixQC&&!G.fixQC[k])continue;var e=fixByKey((G.fixQ&&G.fixQ[k])||'');if(e){n++;t+=(e.price||0);}}
  return '<b>'+TR('夹具价格（夹具库选型报价）：')+'</b>'+n+' / '+FC.length+' '+TR('中心')+' · <b>¥'+f(t,1)+'</b>';
}
function inspCostHtml(){
  var IC=inspClasses(),n=0,t=0,dsc=[];
  for(var k=0;k<IC.length;k++){if(G.inspQ&&!G.inspQ[k])continue;var e=inspByKey((G.insp&&G.insp[k])||'');if(e){n++;t+=(e.price||0);dsc.push(IC[k]+'(产品'+(e.prdSize||'-')+'/检具'+(e.inspSize||'-')+') '+f(e.price||0,2)+'万');}}
  return '<b>'+TR('检具价格（检具库选型报价）：')+'</b>'+n+' / '+IC.length+' '+TR('类')+' · <b>'+f(t,2)+' 万¥</b>'+(dsc.length?'（'+dsc.join('；')+'）':'');
}

// ---------------- 夹具选型（项目级） ----------------
function bFixtureSelect(){
  var h='<div class="panel on"><div class="card"><div class="card-hd"><h2>夹具选型 / Fixture Selection</h2><p>'+TR('每个模具中心一格：这一格选中的夹具（来自夹具库）。夹具是按项目选的，与具体哪道工序无关。')+'</p></div><div class="card-bd">';
  h+='<div class="fbox" style="background:#ebf8ff;border-color:#90cdf4;color:#2a4365">'+TR('夹具库（供货商/单价/寿命）在后台「夹具库」维护；这里的下拉框直接读库里当前的行。')+'</div>';
  h+='</div></div></div>';
  h+=fixQuoteTable();
  h+='<div class="card"><div class="card-hd"><h2>'+TR('夹具费用 / Fixture Cost')+'</h2></div><div class="card-bd"><span id="fixCostLine">'+fixCostHtml()+'</span></div></div>';
  return h;
}

// ---------------- 检具选型（项目级） ----------------
function bGaugeSelect(){
  var _bL=['通用游标卡尺','三坐标测量机','专用毛坯检具','通止规','高度尺+杠杆表','其他'];for(var _q=0;_q<IDB.length;_q++){if((IDB[_q].type||'')==='毛坯检具'&&IDB[_q].name&&_bL.indexOf(IDB[_q].name)<0)_bL.push(IDB[_q].name);}var _bO='<option value=""'+(G.bInspType===''?' selected':'')+'>未选择</option>';if(G.bInspType&&_bL.indexOf(G.bInspType)<0)_bO+='<option value="'+G.bInspType+'" selected>'+G.bInspType+'</option>';for(var _q2=0;_q2<_bL.length;_q2++)_bO+='<option value="'+_bL[_q2]+'"'+(G.bInspType===_bL[_q2]?' selected':'')+'>'+_bL[_q2]+'</option>';
  var _fL=['成品机械检具','成品电子检具'];for(var _q3=0;_q3<IDB.length;_q3++){var _ft=IDB[_q3].type||'';if((_ft==='成品电子检具'||_ft==='成品机械检具'||_ft==='测量支架')&&IDB[_q3].name&&_fL.indexOf(IDB[_q3].name)<0)_fL.push(IDB[_q3].name);}var _fO='<option value=""'+(G.fInspType===''?' selected':'')+'>未选择</option>';if(G.fInspType&&_fL.indexOf(G.fInspType)<0)_fO+='<option value="'+G.fInspType+'" selected>'+G.fInspType+'</option>';for(var _q4=0;_q4<_fL.length;_q4++)_fO+='<option value="'+_fL[_q4]+'"'+(G.fInspType===_fL[_q4]?' selected':'')+'>'+_fL[_q4]+'</option>';
  var h='<div class="panel on"><div class="card"><div class="card-hd"><h2>检具选型 / Gauge Selection</h2><p>'+TR('每个检具类别一格：这一格选中的检具（来自检具库）。检具也是按项目选的。')+'</p></div><div class="card-bd">';
  h+='<div class="note" style="margin-bottom:6px">'+TR('选择毛坯检具与成品检具类型后，「项目信息」页工艺流程图自动显示对应节点（图片可点击粘贴上传）。检具价格请在后台「检具库」中维护。')+'</div>'+
    '<div class="r"><span class="l">毛坯检具类型<br><span class="u">Blank Insp Type</span></span><select onchange="G.bInspType=this.value;render()">'+_bO+'</select></div>'+
    '<div style="text-align:center;margin-top:6px">'+imgSlot('G.bInspImg',G.bInspImg,'点击粘贴毛坯检具图')+'</div>'+
    '<div class="r" style="margin-top:12px"><span class="l">成品检具类型<br><span class="u">Finished Insp Type</span></span><select onchange="G.fInspType=this.value;render()">'+_fO+'</select></div>'+
    '<div style="text-align:center;margin-top:6px">'+imgSlot('G.fInspImg',G.fInspImg,'点击粘贴成品检具图')+'</div>'+
    '</div></div></div>';
  h+=inspQuoteTable();
  h+='<div class="card"><div class="card-hd"><h2>'+TR('检具费用 / Gauge Cost')+'</h2></div><div class="card-bd"><span id="inspCostLine">'+inspCostHtml()+'</span></div></div>';
  return h;
}

function bProcess(pi){
  var pr=PR[pi],m=gm(pi),c=st(pr.tl),ncut=nct(pi),nc=pr.nc||{cc:2,co:2,mc_:2,sc:2,ac:1,it:5},takt=c+ncut,rs=gR(pi),tc=gTC(pi);
  var h='<div class="panel on"><div class="card"><div class="card-hd"><button class="act" onclick="closeProc()">← '+TR('返回工序总表')+'</button><h2>'+pr.nm+' - '+m.brand+' '+m.model+'</h2><p>'+TR('第 ')+(pi+1)+TR(' 道工序 | ')+pr.tl.length+'把刀 | 切削 '+f(c,1)+'s | 非切削 '+f(ncut,1)+'s | 节拍 '+f(takt,0)+'s | '+pr.mc+'台</p></div><div class="card-bd">'+
    '<div class="sg"><div class="si"><div class="sl">总切削<br><span style="font-size:8px">Total Cut</span></div><div class="sv">'+f(c,1)+'<span class="su"> s</span></div></div><div class="si"><div class="sl">加工节拍<br><span style="font-size:8px">Cycle Time</span></div><div class="sv a">'+f(takt,0)+'<span class="su"> s</span></div></div><div class="si"><div class="sl">总非切削<br><span style="font-size:8px">Non-Cut</span></div><div class="sv">'+f(ncut,1)+'<span class="su"> s</span></div></div><div class="si"><div class="sl">月产能('+pr.mc+'台)<br><span style="font-size:8px">Monthly Cap.</span></div><div class="sv">'+fi(cap(takt,pr.mc))+'<span class="su"> pcs</span></div></div></div>'+
    '<div class="card" style="margin-top:8px"><div class="card-hd"><h2>夹具示意图 / Fixture Layout</h2></div><div class="card-bd" style="text-align:center">'+
      '<div onclick="armPaste(function(u){'+(ppOn()?'ProcessPage.setProcessPhoto('+pi+',u)':'PR['+pi+'].cI=u;render()')+'})" title="'+TR('点击后按 Ctrl+V 粘贴/替换夹具图')+'">'+
      (pr.cI?'<img src="'+pr.cI+'" style="max-width:100%;max-height:400px;border-radius:8px;cursor:pointer" onclick="openImg(this.src)">':'<div style="padding:40px;border:2px dashed #cbd5e0;border-radius:8px;color:#a0aec0;font-size:11px;cursor:pointer">默认显示上次夹具图<br>点击此处后按 Ctrl+V 粘贴</div>')+
      '</div><div style="margin-top:4px;font-size:10px;color:#a0aec0">点击图片区域后按 Ctrl+V 粘贴/替换夹具图'+(pr.cI?' · <a style="cursor:pointer;color:#e53e3e" onclick="if(confirm(\'删除图片?\')){'+(ppOn()?'ProcessPage.setProcessPhoto('+pi+',\'\')':'PR['+pi+'].cI=\'\';render()')+'}">删除</a>':'')+'</div></div></div>'+
    '<div class="card" style="margin-top:8px"><div class="card-hd"><h2>非加工时间明细 / Non-Cut Details</h2></div><div class="card-bd"><div class="clamp-grid">'+
    '<div class="r"><span class="l">关门</span><input type="number" value="'+nc.cc+'" onchange="updNC('+pi+',\'cc\',this.value)"><span class="u">s</span></div>'+
    '<div class="r"><span class="l">主压紧</span><input type="number" value="'+nc.mc_+'" onchange="updNC('+pi+',\'mc_\',this.value)"><span class="u">s</span></div>'+
    '<div class="r"><span class="l">支撑缸</span><input type="number" value="'+nc.sc+'" onchange="updNC('+pi+',\'sc\',this.value)"><span class="u">s</span></div>'+
    '<div class="r"><span class="l">辅压紧</span><input type="number" value="'+nc.ac+'" onchange="updNC('+pi+',\'ac\',this.value)"><span class="u">s</span></div>'+
    '<div class="r"><span class="l">开门</span><input type="number" value="'+nc.co+'" onchange="updNC('+pi+',\'co\',this.value)"><span class="u">s</span></div>'+
    '<div class="r"><span class="l">检测/吹屑</span><input type="number" value="'+nc.it+'" onchange="updNC('+pi+',\'it\',this.value)"><span class="u">s</span></div></div>'+bNCDetail(pi,rs,tc)+'</div></div>'+
    '<button class="btn btn-a" onclick="addTool('+pi+')">+ 添加刀具 / Add Tool</button><div class="tbw">'+bToolTable(pi,pr.tl,rs,tc)+'</div></div></div>';
  return h;
}
function updNC(pi,field,val){if(ppOn()){ProcessPage.setNC(pi,field,val);return;}if(!PR[pi].nc)PR[pi].nc={cc:2,co:2,mc_:2,sc:2,ac:1,it:5};PR[pi].nc[field]=parseFloat(val)||0;render();}
function bNCDetail(pi,rs,tc){var pr=PR[pi],nc=pr.nc,cl=nc.cc+nc.co+nc.mc_+nc.sc+nc.ac,tcSum=0,trSum=0,tblS=0,sdS=0;for(var i=0;i<pr.tl.length;i++){var t=pr.tl[i];tcSum+=t.bg?tc*2:tc;trSum+=rs>0?(t.td||500)/rs:0;tblS+=t.tt||2;sdS+=t.sd||1;}return '<div style="margin-top:6px;background:var(--g);padding:6px 10px;border-radius:6px;font-size:10px;color:#4a5568">'+f(cl,1)+'(装夹)+'+f(tcSum,1)+'(换刀)+'+f(trSum,1)+'(快移)+'+f(tblS,1)+'(转台)+'+f(sdS,1)+'(主轴延时)+'+(nc.it||5)+'(检测) = <b>'+f(cl+tcSum+trSum+tblS+sdS+(nc.it||5),1)+'s</b></div>';}
function bToolTable(pi,tl,rs,tc){
  var CATCN={f:'面铣刀',pf:'PCD面铣刀',pt:'PCD-T型刀',pc:'PCD倒角刀',pb:'PCD反勾刀',pg:'PCD复合切槽刀',pk:'PCD锪刀',pr:'PCD铰刀',pj:'PCD精镗刀',pd:'PCD盘刀',pq:'PCD球刀',pm:'PCD铣刀',py:'PCD玉米铣刀',pz:'PCD锥度刀',pa:'PCD钻铰刀',po:'PCD钻头',ud:'U钻',bm:'波纹合金铣刀',cb:'粗镗刀（刀片）',hc:'合金倒角刀',ht:'合金挤压丝锥',hr:'合金内R铣刀',hb:'合金球刀',he:'合金球头铣刀',hm:'合金铣刀',hz:'合金锥度铣刀',hd:'合金钻头',nw:'网纹铣刀（刀片）',hq:'合金钻铣刀',ps:'PCD成型刀',pv:'PCD成型钻头',hs:'合金阶梯钻',hu:'合金台阶钻',kb:'开粗镗刀',hp:'合金深孔钻',pgd:'PCD导条刀',psr:'PCD阶梯铰刀',hgd:'合金导条刀',hj:'合金铰刀',hjr:'合金阶梯铰刀',hda:'合金钻铰刀',rt:'挤压丝锥',ct:'切削丝锥',tm:'螺纹铣刀',pts:'PCD套刀',br:'毛刷',other:'其他'};
  var h='';
  for(var ck in CATCN){h+='<datalist id="tdbCat-'+ck+'-'+pi+'">';for(var j=0;j<TDB.length;j++){var _g=TDB[j].grp||'hp';if(_g!=='hld'&&_g!=='acc'&&(_g!==G.prj||(TDB[j].cat||'other')!==ck))continue;h+='<option value="'+TDB[j].tp+'">';}h+='</datalist>';}
  h+='<table><thead><tr><th colspan="2">基本</th><th colspan="3">🔧 刀具系统</th><th colspan="2">加工</th><th colspan="17">切削参数与时间</th><th></th></tr><tr><th>刀号</th><th>类型</th><th>刀具型号</th><th>刀柄选型</th><th>配件选型</th><th>加工特征</th><th>加工内容</th><th>D<br>mm</th><th>n<br>rpm</th><th>vf<br>mm/min</th><th>fz<br>mm/r</th><th>Vc<br>m/min</th><th>L<br>mm</th><th>次</th><th>件</th><th>大刀</th><th>快移距</th><th>快移时</th><th>换刀时</th><th>转台时</th><th>主轴延时</th><th>t切</th><th>非切削</th><th>总时间</th><th></th></tr></thead><tbody>';
  for(var i=0;i<tl.length;i++){
    var t=tl[i];calcT(t);
    var trav=rs>0?(t.td||500)/rs:0,tcT=t.bg?tc*2:tc,ncPer=getNCperTool(pi,i),tt=trav+tcT+(t.tt||2)+(t.sd||1),totalT=t._ct+tt;
    var curCat=t.cat||'other';if(!CATCN[curCat])curCat='other';var curHld=t.hld||'';
    var catSel='';for(var ck2 in CATCN){catSel+='<option value="'+ck2+'"'+(curCat===ck2?' selected':'')+'>'+CATCN[ck2]+'</option>';}
    var hldSel='<option value="">—</option>';var hldFound=false;
    for(var j2=0;j2<TDB.length;j2++){if((TDB[j2].grp||'hp')!=='hld')continue;if(TDB[j2].tp===curHld)hldFound=true;hldSel+='<option value="'+TDB[j2].tp+'"'+(curHld===TDB[j2].tp?' selected':'')+'>'+TDB[j2].tp+'</option>';}
    if(curHld&&!hldFound)hldSel+='<option value="'+curHld+'" selected>'+curHld+'</option>';
    var curAcc=t.acc||'';var accSel='<option value="">—</option>';var accFound=false;
    for(var j3=0;j3<TDB.length;j3++){if((TDB[j3].grp||'hp')!=='acc')continue;if(TDB[j3].tp===curAcc)accFound=true;accSel+='<option value="'+TDB[j3].tp+'"'+(curAcc===TDB[j3].tp?' selected':'')+'>'+TDB[j3].tp+'</option>';}
    if(curAcc&&!accFound)accSel+='<option value="'+curAcc+'" selected>'+curAcc+'</option>';
    var fiFn=ppOn()?('function(u){ProcessPage.setToolPhoto('+pi+','+i+',u)}'):('function(u){PR['+pi+'].tl['+i+'].fi=u;render()}');
    var fiDel=ppOn()?('ProcessPage.setToolPhoto('+pi+','+i+',\'\')'):('PR['+pi+'].tl['+i+'].fi=\'\';render()');
    h+='<tr><td><input class="txt" value="'+t.id+'" onchange="sS('+pi+','+i+',\'id\',this.value)" style="width:45px"></td>'+
      '<td><select style="width:70px" onchange="sS('+pi+','+i+',\'cat\',this.value)">'+catSel+'</select></td>'+
      '<td style="background:#f0f7ff"><input class="txt" list="tdbCat-'+curCat+'-'+pi+'" value="'+t.tp+'" placeholder="'+TR('从刀具库选')+'" onchange="atT('+pi+','+i+',this.value)" style="width:110px"></td>'+
      '<td style="background:#f0f7ff"><select style="width:90px" onchange="sS('+pi+','+i+',\'hld\',this.value)">'+hldSel+'</select></td>'+
      '<td style="background:#f0f7ff"><select style="width:90px" onchange="sS('+pi+','+i+',\'acc\',this.value)">'+accSel+'</select></td>'+
      '<td style="text-align:center;min-width:70px">'+(t.fi?'<img src="'+t.fi+'" style="max-width:50px;max-height:35px;border-radius:4px;cursor:pointer;vertical-align:middle" onclick="openImg(this.src)"> ':'')+'<a style="cursor:pointer;color:#2c5282;font-size:10px" onclick="armPaste('+fiFn+')">'+(t.fi?'换图':'粘贴')+'</a>'+(t.fi?' <a style="cursor:pointer;color:#e53e3e;font-size:10px" onclick="if(confirm(\'删除图片?\')){'+fiDel+'}">删</a>':' <a style="cursor:pointer;color:#2c5282;font-size:10px" onclick="pickImg('+fiFn+')">上传</a>')+'</td>'+
      '<td><input class="txt" value="'+t.ds+'" onchange="sS('+pi+','+i+',\'ds\',this.value)" style="width:80px"></td>'+
      '<td><input value="'+t.d+'" onchange="sN('+pi+','+i+',\'d\',this.value)" style="width:42px"></td>'+
      '<td><input value="'+t.n+'" onchange="sN('+pi+','+i+',\'n\',this.value)" style="width:50px"></td>'+
      '<td><input value="'+t.vf+'" onchange="sN('+pi+','+i+',\'vf\',this.value)" style="width:55px"></td>'+
      '<td class="ro">'+f(t._fz,3)+'</td>'+
      '<td class="ro">'+fi(t._vc)+'</td>'+
      '<td><input value="'+t.ln+'" onchange="sN('+pi+','+i+',\'ln\',this.value)" style="width:42px"></td>'+
      '<td><input value="'+t.ps+'" onchange="sN('+pi+','+i+',\'ps\',this.value)" style="width:30px"></td>'+
      '<td><input value="'+t.cn+'" onchange="sN('+pi+','+i+',\'cn\',this.value)" style="width:30px"></td>'+
      '<td><input type="checkbox"'+(t.bg?' checked':'')+' onchange="sB('+pi+','+i+',this.checked)"></td>'+
      '<td><input value="'+t.td+'" onchange="sN('+pi+','+i+',\'td\',this.value)" style="width:42px"></td>'+
      '<td class="ro2">'+f(trav,1)+'</td><td class="ro2">'+f(tcT,1)+'</td>'+
      '<td><input value="'+t.tt+'" onchange="sN('+pi+','+i+',\'tt\',this.value)" style="width:40px"></td>'+
      '<td><input value="'+t.sd+'" onchange="sN('+pi+','+i+',\'sd\',this.value)" style="width:40px"></td>'+
      '<td class="ro"><b>'+f(t._ct,1)+'</b></td>'+
      '<td class="ro2">'+f(tt,1)+'</td>'+
      '<td class="ro"><b style="color:var(--acc)">'+f(totalT,1)+'</b></td>'+
      '<td><button class="act" onclick="delTool('+pi+','+i+')">X</button></td></tr>';
  }
  h+='</tbody></table>';return h;
}
function openImg(src){document.getElementById("modalOverlay").classList.add("show");document.getElementById("modalBox").innerHTML='<img src="'+src+'" style="max-width:100%;max-height:60vh;border-radius:8px"><button class="btn btn-s" onclick="closeModal()" style="margin-top:8px">关闭</button>';}
function closeModal(){document.getElementById("modalOverlay").classList.remove("show");}
function atT(pi,i,tp){if(ppOn()){ProcessPage.setToolFromLibrary(pi,i,tp);return;}for(var j=0;j<TDB.length;j++){if(TDB[j].tp===tp&&((TDB[j].grp||'hp')===G.prj||(TDB[j].grp||'hp')==='hld'||(TDB[j].grp||'hp')==='acc')){var t=PR[pi].tl[i];t.tp=tp;t.d=TDB[j].d||0;t.n=TDB[j].n||0;t.vf=TDB[j].vf||0;t.ln=TDB[j].ln||0;t.cat=TDB[j].cat||'other';t.life=TDB[j].life||0;t.price=TDB[j].price||0;t.grp=TDB[j].grp||'hp';break;}}render();}
function sS(pi,i,f,v){if(ppOn()){ProcessPage.setToolText(pi,i,f,v);return;}PR[pi].tl[i][f]=v;render();}
function sN(pi,i,f,v){if(ppOn()){ProcessPage.setToolNumber(pi,i,f,v);return;}PR[pi].tl[i][f]=parseFloat(v)||0;render();}
function sB(pi,i,c){if(ppOn()){ProcessPage.setBigTool(pi,i,c);return;}PR[pi].tl[i].bg=c;render();}
function delTool(pi,i){if(ppOn()){ProcessPage.removeTool(pi,i);return;}if(PR[pi].tl.length<=1)return;PR[pi].tl.splice(i,1);render();}
function addTool(pi){if(ppOn()){ProcessPage.addTool(pi);return;}var tls=PR[pi].tl;tls.push({id:"T"+(tls.length+1),tp:"",ds:"新特征",d:10,n:3000,vf:1200,ln:50,ps:1,cn:1,bg:false,td:500,fi:null,tt:2,sd:1,cat:"other",hld:"",acc:""});render();}

function bSummary(){
  var h='<div class="panel on"><div class="card"><div class="card-hd"><h2>节拍汇总 - '+G.cust+' '+G.part+'</h2></div><div class="card-bd">';
  var ta=[],ca=[],total=0,mx=0;
  for(var p=0;p<PR.length;p++){var c=st(PR[p].tl),nc=nct(p),tk=c+nc;ta.push({nm:PR[p].nm,tk:tk});ca.push(cap(tk,PR[p].mc));total+=tk;if(tk>mx)mx=tk;}
  h+='<div class="sg">';for(var p=0;p<PR.length;p++)h+='<div class="si"><div class="sl">'+ta[p].nm+'<br><span style="font-size:8px">Cycle Time</span></div><div class="sv">'+f(ta[p].tk,0)+'<span class="su"> s</span></div></div>';
  h+='<div class="si" style="background:#fefcbf"><div class="sl">总节拍<br><span style="font-size:8px">Total</span></div><div class="sv a" style="font-size:20px">'+f(total,0)+'<span class="su"> s</span></div></div>';
  var bn='';for(var p=0;p<PR.length;p++){if(ta[p].tk>=mx)bn=ta[p].nm;}
  h+='<div class="si"><div class="sl">瓶颈<br><span style="font-size:8px">Bottleneck</span></div><div class="sv">'+bn+'<span class="su"> '+f(mx,0)+'s</span></div></div></div>';
  h+='<div class="sg"><div class="si"><div class="sl">月可动时间<br><span style="font-size:8px">Monthly Avail.</span></div><div class="sv">'+fi(sec()/3600)+'<span class="su"> h</span></div></div>';
  for(var p=0;p<PR.length;p++)h+='<div class="si"><div class="sl">'+ta[p].nm+'月产能<br><span style="font-size:8px">Monthly Cap.</span></div><div class="sv">'+fi(ca[p])+'<span class="su"> pcs</span></div></div>';
  h+='<div class="si" style="background:#c6f6d5"><div class="sl">实际月产能<br><span style="font-size:8px">Actual Cap.</span></div><div class="sv g" style="font-size:20px">'+fi(Math.min.apply(null,ca))+'<span class="su"> pcs/mo</span></div></div></div>'+
    '<div style="margin-top:10px;background:#f7fafc;padding:10px;border-radius:10px"><b style="font-size:11px">节拍构成 / Takt Breakdown</b><br>';
  for(var p=0;p<PR.length;p++)h+='<div class="bar"><span style="font-size:10px;min-width:60px">'+ta[p].nm+'</span><div class="bar-t"><div class="bar-f '+(['h','m','l'][p%3])+'" style="width:'+f(total>0?ta[p].tk/total*100:0,0)+'%"></div></div><span style="font-size:10px">'+f(total>0?ta[p].tk/total*100:0,0)+'%</span></div>';
  h+='</div><div class="btn-row"><button class="btn btn-g" onclick="exportData()">导出 JSON（单文件·图内联）</button><button class="btn btn-p" onclick="exportPackage()">导出文件包(.zip)</button><button class="btn btn-s" onclick="importData()">导入数据(.json)</button></div></div></div></div>';
  return h;
}

// ===== 选型报价（2b）=====
// 选型报价落表后，下面这些"写入点"统一交给 SelectionPage 按**格子**走行级保存；
// 开关没开就一切照旧（改内存 + 整份保存），老行为一字不变。
// 坐标是 (类别, 格子下标)：夹具='fixture'（模具中心顺序）、检具='gauge'（检具类别顺序）。
function spOn(){return typeof SelectionPage!=='undefined'&&SelectionPage.enabled();}
// "是否报价"勾选框的 onchange：落表后只改这一个格子，没落表还是老的改内存 + 整份保存
function fxQuoteCall(k){
  if(spOn())return 'SelectionPage.setQuoted(\'fixture\','+k+',this.checked)';
  return 'G.fixQC['+k+']=this.checked?1:0;save();render()';
}
function iqQuoteCall(k){
  if(spOn())return 'SelectionPage.setQuoted(\'gauge\','+k+',this.checked)';
  return 'G.inspQ['+k+']=this.checked?1:0;save();render()';
}

// ===== ISSUES (DFM format) =====
// 问题清单已落表（2a）时，下面这些"写入点"统一交给 IssuePage 走行级保存；
// 开关没开就一切照旧（改内存 + 整份保存），老行为一字不变。
function ipOn(){return typeof IssuePage!=='undefined'&&IssuePage.enabled();}
function iSet(i,key,value){if(ipOn()){IssuePage.setField(i,key,value);return;}IS[i][key]=value;render();}
function iPhoto(i,key,value){if(ipOn()){IssuePage.setPhoto(i,key,value);return;}IS[i][key]=value;render();}
// 工序一栏：落表后存的是**外键**（选工序行、写 process_id），不再存名字
// （工序改名时问题清单跟着走；工序进回收站时读模型回退到名字快照）。
// 下拉框给的是页面序号（PR 下标），IssuePage 写之前会读一次行列表把它换成工序行 id。
function iPrField(i,iss){
  if(!ipOn())return '<input class="txt" value="'+iss.pr+'" placeholder="工序" style="max-width:130px" onchange="IS['+i+'].pr=this.value;render()">';
  var hit=-1;
  for(var k=0;k<PR.length;k++){if(PR[k].nm===iss.pr)hit=k;}
  var opts='<option value=""'+(hit<0?' selected':'')+'>未指定</option>';
  for(var k2=0;k2<PR.length;k2++){
    opts+='<option value="'+k2+'"'+(k2===hit?' selected':'')+'>'+PR[k2].nm+'</option>';
  }
  return '<select class="txt" style="max-width:170px" title="'+TR('绑到工序行（工序改名时这里自动跟随）')+'" onchange="IssuePage.setProcess('+i+',this.value)">'+opts+'</select>';
}
function issueImgBtns(i,k,has){if(ipOn()){return '<div style="font-size:10px;margin-top:3px;text-align:center"><a style="cursor:pointer;color:#2c5282" onclick="armPaste(function(u){IssuePage.setPhoto('+i+',\''+k+'\',u)})">粘贴</a>'+(has?' · <a style="cursor:pointer;color:#e53e3e" onclick="if(confirm(\'删除图片?\')){IssuePage.setPhoto('+i+',\''+k+'\',null)}">删除</a>':'')+'</div>';}var fn='function(u){IS['+i+'].'+k+'=u;render()}';return '<div style="font-size:10px;margin-top:3px;text-align:center"><a style="cursor:pointer;color:#2c5282" onclick="armPaste('+fn+')">粘贴</a>'+(has?' · <a style="cursor:pointer;color:#e53e3e" onclick="if(confirm(\'删除图片?\')){IS['+i+'].'+k+'=null;render()}">删除</a>':'')+'</div>';}
function bIssues(){
  var h='<div class="panel on"><div class="card"><div class="card-hd"><h2>问题清单 / Issue List (DFM Format)</h2></div><div class="card-bd">';
  for(var i=0;i<IS.length;i++){
    var iss=IS[i];
    h+='<div style="background:#f7fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px;margin-bottom:8px">'+
      '<div class="issue-row"><input class="txt" value="'+iss.tp+'" placeholder="问题类型" onchange="iSet('+i+',\'tp\',this.value)">'+
      iPrField(i,iss)+
      '<select onchange="iSet('+i+',\'st\',this.value)"><option value="进行中"'+(iss.st==='进行中'?' selected':'')+'>进行中</option><option value="已完成"'+(iss.st==='已完成'?' selected':'')+'>已完成</option></select></div>'+
      '<div class="issue-row"><textarea placeholder="问题描述 / Problem Description" onchange="iSet('+i+',\'ds\',this.value)">'+iss.ds+'</textarea></div>'+
      '<div class="issue-row"><textarea placeholder="修改方案 / Modification Plan" onchange="iSet('+i+',\'fx\',this.value)">'+iss.fx+'</textarea></div>'+
      '<div style="display:flex;gap:8px;margin-bottom:8px">'+
        '<div class="issue-img-wrap"><div class="lab">优化前 Before</div>'+
        (iss.bI?'<img class="issue-thumb" src="'+iss.bI+'" onclick="openIssueImg('+i+',\'bI\')">':'<div class="issue-img-box" onclick="armPaste('+(ipOn()?'function(u){IssuePage.setPhoto('+i+',\'bI\',u)}':'function(u){IS['+i+'].bI=u;render()}')+')">+ 点击粘贴优化前图片</div>')+issueImgBtns(i,'bI',!!iss.bI)+
        '</div>'+
        '<div class="issue-img-wrap"><div class="lab">优化后 After</div>'+
        (iss.aI?'<img class="issue-thumb" src="'+iss.aI+'" onclick="openIssueImg('+i+',\'aI\')">':'<div class="issue-img-box" onclick="armPaste('+(ipOn()?'function(u){IssuePage.setPhoto('+i+',\'aI\',u)}':'function(u){IS['+i+'].aI=u;render()}')+')">+ 点击粘贴优化后图片</div>')+issueImgBtns(i,'aI',!!iss.aI)+
        '</div>'+
      '</div>'+
      '<div class="issue-row"><textarea placeholder="客户回复 / Customer Reply" onchange="iSet('+i+',\'cr\',this.value)">'+iss.cr+'</textarea></div>'+
      '<div style="display:flex;justify-content:flex-end;margin-top:4px"><button class="act" onclick="delIssue('+i+')">删除</button></div></div>';
  }
  h+='<button class="btn btn-g" onclick="addIssue()">+ 新增问题</button></div></div></div>';
  return h;
}
function addIssue(){if(ipOn()){IssuePage.addIssue();return;}IS.push({tp:"尺寸",pr:"",ds:"",fx:"",cr:"",st:"进行中",bI:null,aI:null});render();}
function delIssue(i){if(ipOn()){IssuePage.removeIssue(i);return;}IS.splice(i,1);render();}
function openIssueImg(i,k){document.getElementById("modalOverlay").classList.add("show");document.getElementById("modalBox").innerHTML='<h3>'+(k==='bI'?'优化前':'优化后')+'</h3><img src="'+IS[i][k]+'" style="max-width:100%;max-height:60vh;border-radius:8px"><button class="btn btn-s" onclick="closeModal()">关闭</button>';}

// ===== 工艺设置（密码锁定，与设备库一致）=====
function refEqPrice(){if(ppOn()){ProcessPage.refreshEquipmentPrice();return;}var n=0;for(var p=0;p<PR.length;p++){var v=parseFloat(gm(p).price);if(!isNaN(v)&&v>0){PR[p].eqP=v;n++;}}render();if(n>0)alert(TR('已按设备库价格刷新设备成本'));}
function bCostTable(){
  var h='<div class="card"><div class="card-hd"><h2>成本信息 / Cost Information</h2></div><div class="card-bd">';
  h+='<div class="tbw"><table><thead><tr><th>工序</th><th>设备型号</th><th>设备价格(万¥)</th><th>刀具数</th><th>刀具总价(¥)</th><th>单件刀具成本(¥)</th></tr></thead><tbody>';
  var eqTotal=0,toolPerTotal=0;
  for(var p=0;p<PR.length;p++){
    var pr=PR[p],m=gm(p);
    var tcSum=0;for(var i=0;i<pr.tl.length;i++)tcSum+=toolCost(pr.tl[i]);
    eqTotal+=(pr.eqP||0);toolPerTotal+=tcSum;
    h+='<tr><td>'+pr.nm+'</td><td>'+m.brand+' '+m.model+'</td>';
    h+='<td><input type="number" value="'+(pr.eqP||0)+'" style="width:80px" onchange="'+(ppOn()?('ProcessPage.setProcessField('+p+',\'eqP\',this.value)'):('PR['+p+'].eqP=parseFloat(this.value)||0;render()'))+'"></td>';
    h+='<td>'+pr.tl.length+'把</td><td>'+f(tcSum,1)+'</td><td>'+f(tcSum,2)+'</td></tr>';
  }
  h+='</tbody></table></div>';
  var hldTotal=0,hldCnt=0;for(var q=0;q<TDB.length;q++){if((TDB[q].grp||'hp')==='hld'){hldTotal+=(TDB[q].price||0);hldCnt++;}}
  var inspSelN=0,inspSelTotal=0,inspSelDesc=[];for(var q3=0;q3<inspClasses().length;q3++){if(G.inspQ&&!G.inspQ[q3])continue;var _ie=inspByKey((G.insp&&G.insp[q3])||'');if(_ie){inspSelN++;inspSelTotal+=(_ie.price||0);inspSelDesc.push(inspClasses()[q3]+'(产品'+(_ie.prdSize||'-')+'/检具'+(_ie.inspSize||'-')+') '+f(_ie.price||0,2)+'万');}}
  h+='<div style="margin-top:10px;padding:8px 12px;background:var(--g);border-radius:6px;font-size:11px">';
  h+='<b>刀柄价格（刀具库-刀柄类）：</b>'+hldCnt+' 个 · <b>¥'+f(hldTotal,1)+'</b><br>';
  var accTotal=0,accCnt=0;for(var q4=0;q4<TDB.length;q4++){if((TDB[q4].grp||'hp')==='acc'){accTotal+=(TDB[q4].price||0);accCnt++;}}
  h+='<b>配件价格（刀具库-配件类）：</b>'+accCnt+' 个 · <b>¥'+f(accTotal,1)+'</b><br>'+
    '<b>本报价单按工序使用的配件小计：</b>'+(function(){var _uc=usedParts('acc');return _uc.n+' 种 · <b>¥'+f(_uc.total,1)+'</b>'})()+'<br>';
  var _uhr=usedHld();
  h+='<b>'+TR('本报价单按工序使用的刀柄小计：')+'</b>'+_uhr.n+' '+TR('种')+' · <b>¥'+f(_uhr.total,1)+'</b><br>';  h+='<span id="inspCostLine"><b>'+TR('检具价格（检具库选型报价）：')+'</b>'+inspSelN+' / '+inspClasses().length+' '+TR('类')+' · <b>'+f(inspSelTotal,2)+' 万¥</b>'+(inspSelDesc.length?'（'+inspSelDesc.join('；')+'）':'')+'</span><br>';
  h+='<b>刀具成本：</b>每把刀成本 = 刀具库价格 ÷ 刀具库寿命（自动引用刀具库数据）<br>';
  h+='<b>设备价格：</b><button class="act" onclick="refEqPrice()">'+TR('从设备库引用价格')+'</button> <span style="font-size:11px">'+TR('选设备时自动引用设备库价格（万元），也可手工修改')+'</span></div></div></div>';
  return h;
}
function bSettings(){
  if(!checkPwd())return;
    var h='<div class="panel on"><div class="card"><div class="card-hd"><h2>工艺设置 / Settings</h2></div><div class="card-bd">'+
    '<div class="fbox" style="background:#fefcbf;border-color:#ecc94b;color:#744210">以下参数用于节拍/产能计算，保存后立即生效。</div>'+
    '<div class="fbox" style="background:#ebf8ff;border-color:#90cdf4;color:#2a4365">项目类型与产能参数（日可动时间/日班次/月可动日/可动率）已移到「项目信息」页按字段单独保存。</div>'+
    bCostTable()+
    '<div class="card"><div class="card-hd"><h2>数据保存与导出 / Save & Export</h2></div><div class="card-bd"><div class="btn-row"><button class="btn btn-g" onclick="exportData()">导出 JSON（单文件·图内联）</button><button class="btn btn-p" onclick="exportPackage()">导出文件包(.zip)</button><button class="btn btn-b" onclick="MachiningDFMHost.saveAs()">另存为新项目</button><button class="btn btn-s" onclick="exportCost()" style="background:#2b6cb0;color:#fff">导出价格清单</button><button class="btn btn-s" onclick="exportDFM()" style="background:#2b6cb0;color:#fff">导出DFM报告(PPT)</button><button class="btn btn-s" onclick="importData()">导入数据(.json)</button><button class="btn btn-r" onclick="resetData()">重置</button></div><div class="note">「导出 JSON（单文件·图内联）」= 一个 .json 文件，图片内联在里面，离线打开也有图，也便于别人再用「导入数据(.json)」恢复；「导出文件包(.zip)」= 由服务端现打包的 zip（project.json + 本项目引用到的原图 assets/ + README.txt），适合存档与转发，导出是只读的、不改服务端数据。</div><div class="note">「导出DFM报告(PPT)」按DFM模版生成PPTX（封面/设备选型/工件信息/工序刀具表/检具/Open issue）。</div><div class="note">'+TR('提示：项目数据由服务端保存到当前项目并保留历史版本（顶部「立即保存」可立即落库）；上面两条导出取的都是服务端当前已保存的版本。')+'</div></div></div>'+
    '<div class="card"><div class="card-hd"><h2>公式 / Formulas</h2></div><div class="card-bd"><div class="fbox"><b>切削:</b> Vc=π*D*n/1000 | vf=n*fz | t切=L/vf*60*次数*件数 | fz=vf/n<br><b>非切削(每刀):</b> 快移时=L快移/快移速度 + 换刀时(大刀×2) + 转台时 + 主轴延时<br><b>节拍:</b> 总切削+总非切削<br><b>产能:</b> 月可动时间*可动率/瓶颈节拍*机床数</div></div></div>';
  return h;
}

function bMachDB(){
  if(!checkAdm())return;
  // 设备库由 machines.js 独立维护（每行独立存库、图片/资料走 assets 接口）。
  if(typeof MachinesPage!=='undefined')return MachinesPage.render();
  return '<div class="panel on"><div class="card"><div class="card-bd"><div class="note">'+TR('设备库模块未加载，请刷新页面。')+'</div></div></div></div>';
}
function addM(){if(typeof MachinesPage!=='undefined'){MachinesPage.add();return;}MDB.splice(MDB.length-1,0,{brand:"新品牌",model:"新设备",rapid:30,tc:2.0,spm:8000,atc:20,desc:"",img:null,xyz:'',pa:'',rpa:'',price:0});render();}
function delM(i){var row=MDB[i];if(!row)return;if(typeof MachinesPage!=='undefined'&&row.id){MachinesPage.remove(row.id);return;}if(confirm(TR('确认删除设备「')+row.brand+' '+row.model+TR('」？'))){MDB.splice(i,1);render();}}

function migCat(c,tp){if(c!=='milling'&&c!=='drill'&&c!=='tap'&&c!=='chamfer'&&c!=='spot')return c;var s=tp||'',p=/PCD/i.test(s);if(c==='tap')return /挤/.test(s)?'ht':'ct';if(c==='spot')return p?'pk':'other';if(c==='chamfer')return p?'pc':'hc';if(c==='milling'){if(p){if(/玉米/.test(s))return 'py';if(/球/.test(s))return 'pq';if(/锥/.test(s))return 'pz';if(/盘刀/.test(s))return 'pd';if(/盘铣|面铣/.test(s))return 'pf';if(/成型/.test(s))return 'ps';if(/倒角/.test(s))return 'pc';if(/镗/.test(s))return 'pj';return 'pm';}if(/波纹/.test(s))return 'bm';if(/球头/.test(s))return 'he';if(/球/.test(s))return 'hb';if(/锥/.test(s))return 'hz';if(/内R/.test(s))return 'hr';if(/网纹/.test(s))return 'nw';if(/盘铣|面铣|盘刀/.test(s))return 'f';if(/倒角/.test(s))return 'hc';if(/镗/.test(s))return 'kb';return 'hm';}if(p){if(/钻铰/.test(s))return 'pa';if(/铰/.test(s))return 'pr';if(/锪/.test(s))return 'pk';if(/成型/.test(s))return 'pv';if(/导条/.test(s))return 'pgd';if(/镗/.test(s))return 'pj';if(/套/.test(s))return 'pts';return 'po';}if(/U钻/.test(s))return 'ud';if(/钻铰/.test(s))return 'hda';if(/阶梯铰/.test(s))return 'hjr';if(/铰/.test(s))return 'hj';if(/深孔/.test(s))return 'hp';if(/阶梯钻/.test(s))return 'hs';if(/台阶/.test(s))return 'hu';if(/锪/.test(s))return 'other';if(/导条/.test(s))return 'hgd';if(/镗/.test(s))return 'kb';if(/螺纹/.test(s))return 'tm';return 'hd';}
function bToolDB(){
  if(!checkAdm())return;
  // 刀具库由 tools.js 独立维护（每行独立存库、图片走 assets 接口、分类下拉来自字段登记表）。
  if(typeof ToolsPage!=='undefined')return ToolsPage.render();
  return '<div class="panel on"><div class="card"><div class="card-bd"><div class="note">'+TR('刀具库模块未加载，请刷新页面。')+'</div></div></div></div>';
}
function addT(){if(typeof ToolsPage!=='undefined'){ToolsPage.add();return;}var g=(toolGrp==='all'?'hp':toolGrp);var nc=(g==='hld'||g==='acc');TDB.push({tp:(nc?"新品":"新刀具"),d:(nc?0:10),n:(nc?0:3000),vf:(nc?0:800),cat:(nc?'cn':'other'),grp:g,tI:"",life:0,price:0,ln:0});render();}
function delT(i){var row=TDB[i];if(!row)return;if(typeof ToolsPage!=='undefined'&&row.id){ToolsPage.remove(row.id);return;}if(confirm(TR('确认删除刀具「')+row.tp+TR('」？'))){TDB.splice(i,1);render();}}
function delM(i){var row=MDB[i];if(!row)return;if(typeof MachinesPage!=='undefined'&&row.id){MachinesPage.remove(row.id);return;}if(confirm(TR('确认删除设备「')+row.brand+' '+row.model+TR('」？'))){MDB.splice(i,1);render();}}
function addF(ft){if(typeof FixturesPage!=='undefined'){FixturesPage.add(ft);return;}FDB.push({center:ft,name:'新夹具',img:null,price:0,mc:0,rmk:''});render();}
function delF(i){if(confirm(TR('确认删除夹具「')+FDB[i].name+TR('」？'))){FDB.splice(i,1);render();}}
function bFixDB(){
  if(!checkAdm())return;
  // 夹具库由 fixtures.js 独立维护（按模具中心分组，每行独立存库，图片走 assets 接口）。
  if(typeof FixturesPage!=='undefined')return FixturesPage.render();
  return '<div class="panel on"><div class="card"><div class="card-bd"><div class="note">'+TR('夹具库模块未加载，请刷新页面。')+'</div></div></div></div>';
}

function toolCost(t){for(var j=0;j<TDB.length;j++){if(TDB[j].tp===t.tp){var life=TDB[j].life||0,price=TDB[j].price||0;return life>0?price/life:0;}}return 0;}
function procToolCost(pi){var s=0;for(var i=0;i<PR[pi].tl.length;i++)s+=toolCost(PR[pi].tl[i]);return s;}
function exportCost(){
  var CATCN={f:'面铣刀',pf:'PCD面铣刀',pt:'PCD-T型刀',pc:'PCD倒角刀',pb:'PCD反勾刀',pg:'PCD复合切槽刀',pk:'PCD锪刀',pr:'PCD铰刀',pj:'PCD精镗刀',pd:'PCD盘刀',pq:'PCD球刀',pm:'PCD铣刀',py:'PCD玉米铣刀',pz:'PCD锥度刀',pa:'PCD钻铰刀',po:'PCD钻头',ud:'U钻',bm:'波纹合金铣刀',cb:'粗镗刀（刀片）',hc:'合金倒角刀',ht:'合金挤压丝锥',hr:'合金内R铣刀',hb:'合金球刀',he:'合金球头铣刀',hm:'合金铣刀',hz:'合金锥度铣刀',hd:'合金钻头',nw:'网纹铣刀（刀片）',hq:'合金钻铣刀',ps:'PCD成型刀',pv:'PCD成型钻头',hs:'合金阶梯钻',hu:'合金台阶钻',kb:'开粗镗刀',hp:'合金深孔钻',pgd:'PCD导条刀',psr:'PCD阶梯铰刀',hgd:'合金导条刀',hj:'合金铰刀',hjr:'合金阶梯铰刀',hda:'合金钻铰刀',rt:'挤压丝锥',ct:'切削丝锥',tm:'螺纹铣刀',pts:'PCD套刀',br:'毛刷',other:'其他'};
  var R='<html xmlns:x="urn:schemas-microsoft-com:office:excel"><head><meta charset="utf-8"><style>td,th{border:1px solid #999;padding:4px 8px;font-size:11px;white-space:nowrap}th{background:#1F4E79;color:#fff;font-weight:bold}.section{background:#DCE6F1;font-weight:bold;font-size:12px}.total{background:#B8CCE4;font-weight:bold}.title{font-size:16px;font-weight:bold}</style></head><body><table>';
  R+='<tr><td class="title" colspan="8">工模检价格清单</td></tr>';
  R+='<tr><td colspan="8">客户：'+(G.cust||'')+'  零件：'+(G.part||'')+'  日期：'+new Date().toISOString().slice(0,10)+'</td></tr>';
  R+='<tr><td colspan="8"></td></tr>';
  // 1. 产品节拍
  R+='<tr><td class="section" colspan="8">产品节拍</td></tr>';
  R+='<tr><th>工序号</th><th colspan="2">设备型号</th><th>节拍（s/件）</th><th colspan="4">备注</th></tr>';
  for(var p=0;p<PR.length;p++){var pr=PR[p],m=gm(p),c=st(pr.tl),ncut=nct(p),takt=c+ncut;
    R+='<tr><td>'+pr.nm+'</td><td colspan="2">'+m.brand+' '+m.model+'</td><td>'+f(takt,1)+'</td><td colspan="4">'+pr.mc+'台</td></tr>';}
  R+='<tr><td colspan="8"></td></tr>';
  // 2. 刀具价格
  R+='<tr><td class="section" colspan="8">刀具价格</td></tr>';
  R+='<tr><th>工序号</th><th>序号</th><th>刀具名称</th><th>刀具类型</th><th>刀具价格（未税：元）</th><th>刀具寿命（min）</th><th>单件成本（元/min）</th><th>备注</th></tr>';
  var toolTotal=0,toolPerPiece=0;
  for(var p2=0;p2<PR.length;p2++){var pr2=PR[p2];
    for(var i=0;i<pr2.tl.length;i++){var t=pr2.tl[i];var tc=toolCost(t);var life=0,price=0;
      for(var j=0;j<TDB.length;j++){if(TDB[j].tp===t.tp){life=TDB[j].life||0;price=TDB[j].price||0;break;}}
      var _rk=[];if(t.hld)_rk.push('刀柄 '+t.hld);if(t.acc)_rk.push('配件 '+t.acc);
      R+='<tr><td>'+pr2.nm+'</td><td>'+(t.id||'')+'</td><td>'+(t.tp||'')+'</td><td>'+(CATCN[t.cat]||'其他')+'</td><td>'+price+'</td><td>'+life+'</td><td>'+f(tc,2)+'</td><td>'+_rk.join(' / ')+'</td></tr>';
      toolTotal+=price;toolPerPiece+=tc;}}
  R+='<tr class="total"><td colspan="4">刀具总价（未税：元）</td><td>'+f(toolTotal,1)+'</td><td></td><td>'+f(toolPerPiece,2)+'</td><td>单件成本=价格/寿命</td></tr>';
  R+='<tr><td colspan="8"></td></tr>';
  // 3. 刀柄价格（按工序选择的刀柄）
  R+='<tr><td class="section" colspan="8">刀柄价格</td></tr>';
  R+='<tr><th>工序</th><th>序号</th><th>刀柄型号</th><th>数量</th><th>刀柄单价（未税：元）</th><th>寿命</th><th colspan="2">备注</th></tr>';
  var _uh=usedHld();for(var hx=0;hx<_uh.list.length;hx++){var _u2=_uh.list[hx];R+='<tr><td>'+_u2.pn+'</td><td>'+(hx+1)+'</td><td>'+_u2.tp+'</td><td>'+_u2.q+'</td><td>'+_u2.price+'</td><td>'+_u2.life+'</td><td colspan="2"></td></tr>';}
  R+='<tr class="total"><td colspan="4">刀柄总价（未税：元）</td><td>'+f(_uh.total,1)+'</td><td></td><td colspan="2">'+_uh.qty+' 把 / '+_uh.n+' 条</td></tr>';
  R+='<tr><td class="section" colspan="8">配件价格</td></tr>';
  R+='<tr><th>工序</th><th>序号</th><th>配件型号</th><th>数量</th><th>配件单价（未税：元）</th><th>寿命</th><th colspan="2">备注</th></tr>';
  var _ua=usedParts('acc');for(var h2=0;h2<_ua.list.length;h2++){var _a2=_ua.list[h2];R+='<tr><td>'+_a2.pn+'</td><td>'+(h2+1)+'</td><td>'+_a2.tp+'</td><td>'+_a2.q+'</td><td>'+_a2.price+'</td><td>'+_a2.life+'</td><td colspan="2"></td></tr>';}
  R+='<tr class="total"><td colspan="4">配件总价（未税：元）</td><td>'+f(_ua.total,1)+'</td><td></td><td colspan="2">'+_ua.qty+' 个 / '+_ua.n+' 条</td></tr>';
  R+='<tr><td colspan="8"></td></tr>';
  
  R+='<tr><td colspan="8"></td></tr>';
  // 4. 夹具价格清单
  R+='<tr><td class="section" colspan="8">夹具价格清单</td></tr>';
  R+='<tr><th>工序</th><th colspan="5">预估价格（未税：元）</th><th colspan="2">备注</th></tr>';
  var fixTotal=0;
  for(var p3=0;p3<PR.length;p3++){fixTotal+=(PR[p3].fixP||0);
    R+='<tr><td>'+PR[p3].nm+'</td><td colspan="5">'+(PR[p3].fixP||0)+'</td><td colspan="2"></td></tr>';}
  for(var f1=0;f1<fixClasses().length;f1++){if(G.fixQC&&!G.fixQC[f1])continue;var fe=fixByKey((G.fixQ&&G.fixQ[f1])||'');if(!fe)continue;fixTotal+=(fe.price||0);R+='<tr><td>'+fixClasses()[f1]+'</td><td colspan="5">'+(fe.price||0)+'</td><td colspan="2">'+(fe.name||'')+'</td></tr>';}
  R+='<tr class="total"><td>夹具总价</td><td colspan="5">'+f(fixTotal,1)+'</td><td colspan="2"></td></tr>';
  R+='<tr><td colspan="8"></td></tr>';
  // 5. 检具价格
  R+='<tr><td class="section" colspan="8">检具价格</td></tr>';
  R+='<tr><th>类型</th><th colspan="5">预估价格（未税：万元）</th><th colspan="2">备注</th></tr>';
  var inspTotal=0;
  for(var ic=0;ic<inspClasses().length;ic++){if(G.inspQ&&!G.inspQ[ic])continue;var _ie=inspByKey((G.insp&&G.insp[ic])||'');var isub=_ie?(_ie.price||0):0;
    inspTotal+=isub;
    R+='<tr><td>'+inspClasses()[ic]+'</td><td colspan="5">'+f(isub,1)+'</td><td colspan="2">'+(_ie?('产品'+(_ie.prdSize||'-')+' / 检具'+(_ie.inspSize||'-')):'未选型')+'</td></tr>';}
  R+='<tr class="total"><td>检具总价</td><td colspan="5">'+f(inspTotal,1)+'</td><td colspan="2"></td></tr>';
  R+='<tr><td colspan="8"></td></tr>';
  // 6. 设备价格
  R+='<tr><td class="section" colspan="8">设备价格</td></tr>';
  R+='<tr><th>工序</th><th colspan="2">设备型号</th><th colspan="2">预估价格（未税：万元）</th><th colspan="3">备注</th></tr>';
  var eqTotal=0;
  for(var p4=0;p4<PR.length;p4++){var m4=gm(p4);eqTotal+=(PR[p4].eqP||0);
    R+='<tr><td>'+PR[p4].nm+'</td><td colspan="2">'+m4.brand+' '+m4.model+'</td><td colspan="2">'+(PR[p4].eqP||0)+'</td><td colspan="3">'+PR[p4].mc+'台</td></tr>';}
  R+='<tr class="total"><td colspan="3">设备总价（未税：万元）</td><td colspan="2">'+f(eqTotal,1)+'</td><td colspan="3"></td></tr>';
  R+='<tr><td colspan="8"></td></tr>';
  // 7. 变更履历
  R+='<tr><td class="section" colspan="8">变更履历</td></tr>';
  R+='<tr><th>版本</th><th>日期</th><th>修改人</th><th colspan="5">修改内容</th></tr>';
  if(VH.length===0){R+='<tr><td>A0</td><td>'+new Date().toISOString().slice(0,10)+'</td><td></td><td colspan="5">初版</td></tr>';}
  else{for(var v1=0;v1<VH.length;v1++){R+='<tr><td>'+(VH[v1].ver||'')+'</td><td>'+(VH[v1].dt||'')+'</td><td>'+(VH[v1].by||'')+'</td><td colspan="5">'+(VH[v1].ds||'')+'</td></tr>';}}
  R+='</table></body></html>';
  var blob=new Blob(['\ufeff'+R],{type:'application/vnd.ms-excel'});
  var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='工模检价格清单_'+(G.part||'').replace(/\s/g,'_')+'.xls';
  document.body.appendChild(a);a.click();document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(a.href);},3000);
}
function exportCSV(){
  var rows=[['DFM Report'],['Customer',G.cust,'Part',G.part,'Daily Hrs',G.hpd,'Shifts',G.sft,'Days/Mo',G.dpm,'Avail%',(G.avl*100).toFixed(0)+'%'],['']];
  rows.push(['Process','Machine','Tool#','Type','Description','D(mm)','n(rpm)','vf(mm/min)','fz(mm/r)','Vc(m/min)','L(mm)','Passes','Count','Big','RapidDist','RapidTime','TCTime','TableTime','SpindleDly','CutTime','NonCut','TotalTime']);
  for(var p=0;p<PR.length;p++){var pr=PR[p],m=gm(p),rs=gR(p),tc=gTC(p),c=st(pr.tl),ncut=nct(p),takt=c+ncut;
    for(var i=0;i<pr.tl.length;i++){var t=pr.tl[i];calcT(t);var trav=rs>0?(t.td||500)/rs:0,tcT=t.bg?tc*2:tc,ncPer=getNCperTool(p,i),tt=trav+tcT+(t.tt||2)+(t.sd||1);
      rows.push([pr.nm,m.brand+' '+m.model,t.id,t.tp,t.ds,f(t.d,0),f(t.n||0,0),f(t.vf||0,0),f(t._fz,3),fi(t._vc),f(t.ln,0),t.ps,t.cn,t.bg?'Yes':'',f(t.td,0),f(trav,1),f(tcT,1),f(t.tt||2,1),f(t.sd||1,1),f(t._ct,1),f(tt,1),f(t._ct+tt,1)]);}
    rows.push(['','','','','','','','','','','','','','','','','','','','','',pr.nm+' Total',f(c,1)+'s','(Non-Cut '+f(ncut,1)+'s)','Takt '+f(takt,0)+'s','M.Cap '+fi(cap(takt,pr.mc))]);rows.push(['']);}
  rows.push(['Total Takt',f((function(){var t=0;for(var p=0;p<PR.length;p++)t+=st(PR[p].tl)+nct(p);return t;})(),0)+'s','Monthly Cap',fi(Math.min.apply(null,PR.map(function(_,p){return cap(st(PR[p].tl)+nct(p),PR[p].mc)})))+'pcs']);
  var csv='';for(var i=0;i<rows.length;i++){csv+=rows[i].join('\t')+'\n';}
  var blob=new Blob(['﻿'+csv],{type:'text/csv'});
  var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='DFM_'+G.part.replace(/\s/g,'_')+'.csv';
  document.body.appendChild(a);a.click();document.body.removeChild(a);
}


function embMerge(){
  try{
    var raw=null;if(!raw)return;
    var d=JSON.parse(raw);var ch=false;
    for(var mg0=0;d.tdb&&mg0<d.tdb.length;mg0++){var mgv=migCat(d.tdb[mg0].cat,d.tdb[mg0].tp);if(mgv!==d.tdb[mg0].cat){d.tdb[mg0].cat=mgv;ch=true;}}
    for(var mg1=0;d.pr&&mg1<d.pr.length;mg1++){var mgt=(d.pr[mg1]&&d.pr[mg1].tl)||[];for(var mg2=0;mg2<mgt.length;mg2++){if(mgt[mg2]&&'cat' in mgt[mg2]){var mgw=migCat(mgt[mg2].cat,mgt[mg2].tp);if(mgw!==mgt[mg2].cat){mgt[mg2].cat=mgw;ch=true;}}}}
    if(typeof _EMB==='undefined'||!_EMB)return;
    if(_EMB.mdb&&d.mdb&&d.mdb.length>0){var s={};for(var i=0;i<d.mdb.length;i++)s[d.mdb[i].brand+'|'+d.mdb[i].model]=i;
      for(var j=0;j<_EMB.mdb.length;j++){var m=_EMB.mdb[j];var kk=m.brand+'|'+m.model;
      if(s[kk]===undefined){s[kk]=d.mdb.length;d.mdb.push(m);ch=true;}
      else{var ex=d.mdb[s[kk]];if(m.img&&!ex.img){ex.img=m.img;ch=true;}if((!ex.rapid||ex.rapid<=0)&&m.rapid>0){ex.rapid=m.rapid;ch=true;}if((!ex.tc||ex.tc<=0)&&m.tc>0){ex.tc=m.tc;ch=true;}if((!ex.spm||ex.spm<=0)&&m.spm>0){ex.spm=m.spm;ch=true;}if((!ex.atc||ex.atc<=0)&&m.atc>0){ex.atc=m.atc;ch=true;}}}}
    if(_EMB.tdb&&d.tdb&&d.tdb.length>0){var s2={};for(var a=0;a<d.tdb.length;a++)s2[d.tdb[a].tp+'|'+d.tdb[a].d+'|'+d.tdb[a].n+'|'+d.tdb[a].vf+'|'+d.tdb[a].cat]=1;
      for(var b=0;b<_EMB.tdb.length;b++){var t=_EMB.tdb[b];var k=t.tp+'|'+t.d+'|'+t.n+'|'+t.vf+'|'+t.cat;if(!s2[k]){s2[k]=1;d.tdb.push(t);ch=true;}}}
    if(_EMB.fdb){if(!d.fdb||d.fdb.length===0){d.fdb=_EMB.fdb;ch=true;}else{var s4={};for(var f0=0;f0<d.fdb.length;f0++)s4[(d.fdb[f0].center||'')+'|'+(d.fdb[f0].name||'')]=1;for(var f2=0;f2<_EMB.fdb.length;f2++){var fe=_EMB.fdb[f2];var kf=(fe.center||'')+'|'+(fe.name||'');if(!s4[kf]){s4[kf]=1;d.fdb.push(fe);ch=true;}}}}
    if(_EMB.idb){if(!d.idb||d.idb.length===0){d.idb=_EMB.idb;ch=true;}else{var s3={};for(var c1=0;c1<d.idb.length;c1++){var it=d.idb[c1];if((it.name||'').indexOf('测量支架')>-1&&(it.type||'')!=='测量支架'){it.type='测量支架';ch=true;}s3[(it.type||'')+'|'+(it.name||'')+'|'+(it.drw||'')]=1;}for(var c2=0;c2<_EMB.idb.length;c2++){var ie=_EMB.idb[c2];var k3=(ie.type||'')+'|'+(ie.name||'')+'|'+(ie.drw||'');if(!s3[k3]){s3[k3]=1;d.idb.push(ie);ch=true;}}}}
    if(_EMB.vh&&(!d.vh||d.vh.length===0)){d.vh=_EMB.vh;ch=true;}
    if(ch){applyData(d);save();render();}
  if(d.G){['bInspPrice','fInspPrice','msInspPrice'].forEach(function(k){if(!(k in d.G))d.G[k]=0;});['custVer','dfmDate'].forEach(function(k){if(!(k in d.G))d.G[k]='';});if(!('prj' in d.G))d.G.prj='hp';if(!d.G.insp)d.G.insp=["","","","",""];if(!('lang' in d.G))d.G.lang='zh';if(!d.G.icnX)d.G.icnX=[];if(!d.G.fcnX)d.G.fcnX=[];}
  if(d.pr){for(var pp=0;pp<d.pr.length;pp++){if(!('fixP' in d.pr[pp]))d.pr[pp].fixP=0;if(!('eqP' in d.pr[pp]))d.pr[pp].eqP=0;}}
  }catch(e){}
}

function exportDFM(){inlineSheetImages().then(buildDFM).catch(function(e){alert(TR('导出失败：')+(e&&e.message||e));});}
function buildDFM(){
  if(typeof PptxGenJS==='undefined'&&(!window.PptxGenJs)){alert(TR('PPTX 组件未加载，请检查文件完整性'));return;}
  var P=PptxGenJS||window.PptxGenJs;
  if(!PR.length){alert(TR('暂无工序数据，请先在「工序管理」中添加工序'));return;}
  try{
    var pptx=new P();
    pptx.layout='LAYOUT_WIDE';
    pptx.author='DFM Tool';pptx.company='Machining';
    var C1='1F4E79',CG='DCE6F1',CB='B8CCE4';
    var d=new Date(),dt=d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+(d.getDate())).slice(-2);
    var s1=pptx.addSlide();s1.background={color:C1};
    s1.addText('Machining Design',{x:0.8,y:2.1,w:11.7,h:1.1,fontSize:48,bold:true,color:'FFFFFF',align:'center'});
    s1.addText((G.cust||'')+'  |  '+(G.part||''),{x:0.8,y:3.4,w:11.7,h:0.6,fontSize:20,color:'DCE6F1',align:'center'});
    s1.addText('DFM Report  '+dt,{x:0.8,y:4.2,w:11.7,h:0.5,fontSize:14,color:'9DC3E6',align:'center'});
    for(var p=0;p<PR.length;p++){
      var m=gm(p);
      var s=pptx.addSlide();s.background={color:'FFFFFF'};
      s.addText('Machining — Equipment Selection',{x:0.3,y:0.12,w:9,h:0.5,fontSize:22,bold:true,color:C1});
      var info='Equipment type（设备类型）: '+(m.desc||'-')+'\nEquipment model（设备型号）: '+m.brand+' '+m.model+'\nTravel X/Y/Z（行程）: '+(m.xyz||'-')+' mm';
      if(m.pa)info+='\nPositioning accuracy（定位精度）: '+m.pa+' mm';
      if(m.rpa)info+='\nRe positioning accuracy（重复定位精度）: '+m.rpa+' mm';
      if(m.spm)info+='\nSpindle speed（主轴转速）: '+m.spm+' rpm';
      if(m.atc)info+='\nTool capacity（刀库容量）: '+m.atc;
      if(m.rapid)info+='\nRapid traverse（快移速度）: '+m.rapid+' m/min';
      info+='\nQuantity（数量）: '+PR[p].mc+' 台';
      var rows=[
        [{text:'Equipment Selection',options:{bold:true,color:'FFFFFF',fill:{color:C1},fontSize:13}},{text:PR[p].nm,options:{bold:true,fill:{color:CG},fontSize:13}}],
        [{text:'',options:{fill:{color:C1}}},{text:info,options:{fontSize:11,valign:'top'}}],
        [{text:'Fixture Analysis',options:{bold:true,color:'FFFFFF',fill:{color:C1},fontSize:13}},{text:'（详见夹具设计）',options:{fontSize:11}}],
        [{text:'Machining Scheme',options:{bold:true,color:'FFFFFF',fill:{color:C1},fontSize:13}},{text:'（详见工序刀具表）',options:{fontSize:11}}]
      ];
      s.addTable(rows,{x:0.3,y:0.85,w:7.3,colW:[2.0,5.3],border:{type:'solid',color:CB},valign:'middle'});
      if(m.img){try{s.addImage({data:m.img,x:8.0,y:1.2,w:5.0,h:4.4,sizing:{type:'contain',w:5.0,h:4.4}});}catch(e){}}
    }
    var sw=pptx.addSlide();sw.background={color:'FFFFFF'};
    sw.addText('Workpiece',{x:0.3,y:0.12,w:9,h:0.5,fontSize:22,bold:true,color:C1});
    var wr=[
      [{text:'Workpiece Information',options:{bold:true,color:'FFFFFF',fill:{color:C1},fontSize:13}},{text:'',options:{fill:{color:CG}}}],
      [{text:'',options:{fill:{color:C1}}},{text:'Material（材质）: n/a',options:{fontSize:12}}],
      [{text:'',options:{fill:{color:C1}}},{text:'Weight（重量）: '+(G.wgt||'-')+' kg',options:{fontSize:12}}],
      [{text:'',options:{fill:{color:C1}}},{text:'Length（长）: '+(G.len||'-')+' mm',options:{fontSize:12}}],
      [{text:'',options:{fill:{color:C1}}},{text:'Width（宽）: '+(G.wid||'-')+' mm',options:{fontSize:12}}],
      [{text:'',options:{fill:{color:C1}}},{text:'Height（高）: '+(G.hgt||'-')+' mm',options:{fontSize:12}}]
    ];
    sw.addTable(wr,{x:0.3,y:0.85,w:6.0,colW:[2.0,4.0],border:{type:'solid',color:CB},valign:'middle'});
    if(G.pI){try{sw.addImage({data:G.pI,x:6.8,y:1.2,w:6.2,h:5.4,sizing:{type:'contain',w:6.2,h:5.4}});}catch(e){}}
    for(var p2=0;p2<PR.length;p2++){
      var pr=PR[p2],rs=gR(p2),tc=gTC(p2),c=st(pr.tl),ncut=nct(p2),takt=c+ncut;
      var s2_=pptx.addSlide();s2_.background={color:'FFFFFF'};
      s2_.addText('Machining — '+pr.nm+' Processing procedure',{x:0.3,y:0.12,w:12,h:0.5,fontSize:20,bold:true,color:C1});
      var hd=['Tool number','Tool Type','Processing Content','Processing Area','Processing time(s)','Non-processing time(s)','Total Time(s)'].map(function(h){return {text:h,options:{bold:true,color:'FFFFFF',fill:{color:C1},fontSize:10}};});
      var rows2=[hd];
      for(var i2=0;i2<pr.tl.length;i2++){var t=pr.tl[i2];calcT(t);
        var trav=rs>0?(t.td||500)/rs:0,tcT=t.bg?tc*2:tc,tt=trav+tcT+(t.tt||2)+(t.sd||1);
        rows2.push([t.id||'',t.tp||'',t.ds||'',(t.ln?f(t.ln,0)+'mm×'+t.ps+'次':''),f(t._ct,1),f(tt,1),f(t._ct+tt,1)]);}
      rows2.push([{text:'Total',options:{bold:true,fill:{color:CG}}},{text:'',options:{fill:{color:CG}}},{text:'',options:{fill:{color:CG}}},{text:'',options:{fill:{color:CG}}},{text:''+f(c,1),options:{bold:true,fill:{color:CG}}},{text:''+f(ncut,1),options:{bold:true,fill:{color:CG}}},{text:'Takt '+f(takt,1)+'s',options:{bold:true,fill:{color:CG}}}]);
      rows2.push([{text:'Monthly Cap',options:{bold:true,fill:{color:CG}}},{text:'',options:{fill:{color:CG}}},{text:'',options:{fill:{color:CG}}},{text:'',options:{fill:{color:CG}}},{text:'',options:{fill:{color:CG}}},{text:'',options:{fill:{color:CG}}},{text:fi(cap(takt,pr.mc))+' pcs',options:{bold:true,fill:{color:CG}}}]);
      s2_.addTable(rows2,{x:0.3,y:0.8,w:12.7,colW:[1.1,2.6,2.6,1.6,1.6,1.6,1.6],border:{type:'solid',color:CB},fontSize:9,valign:'middle'});
    }
    if(G.bInspType||G.fInspType||G.bInspImg||G.fInspImg){
      var sg=pptx.addSlide();sg.background={color:'FFFFFF'};
      sg.addText('Finished part gauge',{x:0.3,y:0.12,w:9,h:0.5,fontSize:22,bold:true,color:C1});
      var gr=[
        [{text:'Finished part gauge',options:{bold:true,color:'FFFFFF',fill:{color:C1},fontSize:13}},{text:'',options:{fill:{color:CG}}}],
        [{text:'',options:{fill:{color:C1}}},{text:'Blank Insp Type（毛坯检具）: '+(G.bInspType||'-'),options:{fontSize:12}}],
        [{text:'',options:{fill:{color:C1}}},{text:'Finished Insp Type（成品检具）: '+(G.fInspType||'-'),options:{fontSize:12}}]
      ];
      sg.addTable(gr,{x:0.3,y:0.85,w:6.0,colW:[2.0,4.0],border:{type:'solid',color:CB},valign:'middle'});
      if(G.bInspImg){try{sg.addImage({data:G.bInspImg,x:6.8,y:1.0,w:6.0,h:2.6,sizing:{type:'contain',w:6.0,h:2.6}});}catch(e){}}
      if(G.fInspImg){try{sg.addImage({data:G.fInspImg,x:6.8,y:3.8,w:6.0,h:2.6,sizing:{type:'contain',w:6.0,h:2.6}});}catch(e){}}
    }
    for(var q=0;q<IS.length;q++){var iss=IS[q];
      var si=pptx.addSlide();si.background={color:'FFFFFF'};
      si.addText('Open issue',{x:0.3,y:0.12,w:9,h:0.5,fontSize:22,bold:true,color:C1});
      var ir=[
        [{text:'Information',options:{bold:true,color:'FFFFFF',fill:{color:C1},fontSize:11}},{text:'',options:{fill:{color:CG}}},{text:'Before optimization',options:{bold:true,fill:{color:CG},fontSize:11}},{text:'After optimization',options:{bold:true,fill:{color:CG},fontSize:11}}],
        [{text:'Problem description',options:{bold:true,fill:{color:'F2F7FC'}}},{text:(iss.tp?iss.tp+'：':'')+(iss.ds||'')+'\n工序: '+(iss.pr||'')+'  状态: '+(iss.st||''),options:{fontSize:10,valign:'top'}},{text:'',options:{}},{text:'',options:{}}],
        [{text:'Modified Proposal',options:{bold:true,fill:{color:'F2F7FC'}}},{text:iss.fx||'',options:{fontSize:10,valign:'top'}},{text:'',options:{}},{text:'',options:{}}],
        [{text:"Customer's feedback",options:{bold:true,fill:{color:'F2F7FC'}}},{text:iss.cr||'',options:{fontSize:10,valign:'top'}},{text:'',options:{}},{text:'',options:{}}]
      ];
      si.addTable(ir,{x:0.3,y:0.8,w:12.7,colW:[1.8,5.5,2.7,2.7],border:{type:'solid',color:CB},valign:'top'});
      if(iss.bI){try{si.addImage({data:iss.bI,x:7.6,y:2.6,w:2.6,h:2.2,sizing:{type:'contain',w:2.6,h:2.2}});}catch(e){}}
      if(iss.aI){try{si.addImage({data:iss.aI,x:10.4,y:2.6,w:2.6,h:2.2,sizing:{type:'contain',w:2.6,h:2.2}});}catch(e){}}
    }
    var s9=pptx.addSlide();s9.background={color:C1};
    s9.addText('OUR MISSION\nProvide more secure, comfortable and environmentally\nfriendly technologies and products for cars',{x:6.2,y:0.9,w:6.6,h:1.6,fontSize:13,color:'FFFFFF',bold:true,lineSpacing:20});
    s9.addText('OUR VISION\nSatisfy Customers, Employees, Society,\nShareholders and Partners',{x:6.2,y:2.9,w:6.6,h:1.4,fontSize:13,color:'DCE6F1',lineSpacing:20});
    s9.addText('NINGBO TUOPU GROUP CO., LTD',{x:6.2,y:5.2,w:6.6,h:0.4,fontSize:14,bold:true,color:'FFFFFF'});
    s9.addText('No.1, Longtanshan Road, Beilun, Ningbo, China',{x:6.2,y:5.7,w:6.6,h:0.4,fontSize:10,color:'9DC3E6'});
    var canBlob=(typeof Blob!=='undefined'&&typeof URL!=='undefined'&&typeof URL.createObjectURL==='function');
    pptx.write({outputType:canBlob?'blob':'nodebuffer'}).then(function(out){
      if(canBlob){
        var a=document.createElement('a');a.href=URL.createObjectURL(out);a.download='DFM_'+G.part.replace(/\s/g,'_')+'.pptx';
        document.body.appendChild(a);a.click();document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(a.href);},3000);
      }else{window.__DFM_OUT=out;}
    }).catch(function(e){alert(TR('PPTX 生成失败: ')+(e&&e.message||e));});
  }catch(e){alert(TR('导出失败: ')+(e&&e.message||e));}
}
