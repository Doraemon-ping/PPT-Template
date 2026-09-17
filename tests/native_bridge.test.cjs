const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const bridgeSource=fs.readFileSync('static/native_bridge.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(adapter='dfm_quote_v1',autoLoad=true){
  const source=bridgeSource.replace('__CHANNEL__','"test-channel"').replace('__ADAPTER__',JSON.stringify(adapter));
  const handlers={},events={},messages=[],timers=[];
  const parent={postMessage:m=>messages.push(m)};
  const window={G:{cust:'original'},PR:[],MDB:[],TDB:[],IS:[],FDB:[],IDB:[],VH:[],GLBL:{},applyData(){},render(){},addEventListener:(type,fn)=>handlers[type]=fn};
  const document={querySelectorAll:()=>[],addEventListener:(type,fn)=>events[type]=fn};
  vm.runInNewContext(source,{window,document,parent,setTimeout:fn=>timers.push(fn),Event:class{constructor(type){this.type=type;}}});
  if(autoLoad){handlers.load();timers.splice(0).forEach(fn=>fn());}
  const send=data=>handlers.message({source:parent,data:{channel:'test-channel',id:'1',...data}});
  return {window,events,messages,send,handlers,parent,timers};
}
test('snapshot commits onchange-backed edits before reading globals',async()=>{
  const f=fixture();let committed=0;
  const input={isConnected:true,dispatchEvent(){committed++;f.window.G.cust='edited';}};
  f.events.input({target:input});f.send({type:'snapshot'});await tick();
  assert.equal(committed,1);assert.equal(f.messages.at(-1).runtime.state.G.cust,'edited');
});
test('restore preserves empty arrays and source cache is frame-local',async()=>{
  const a=fixture(),b=fixture();
  const state={G:{cust:'restored'},pr:[],mdb:[],tdb:[],is:[],fdb:[],idb:[],vh:[]};
  a.send({type:'restore',runtime:{adapter:'dfm_quote_v1',state}});await tick();
  assert.equal(a.window.G.cust,'restored');assert.equal(a.window.PR.length,0);
  assert.equal(b.window.localStorage.getItem('cncCalcV7'),null);
  assert.equal(a.messages.at(-1).runtime.state.pr.length,0);
});
test('bridge ignores other windows and invalid channels',()=>{
  const f=fixture(),count=f.messages.length;
  f.handlers.message({source:{},data:{channel:'test-channel',type:'snapshot'}});
  f.handlers.message({source:f.parent,data:{channel:'other',type:'snapshot'}});
  assert.equal(f.messages.length,count);
});
test('generic bridge exports and restores complete JSON through the stable contract',async()=>{
  const f=fixture('json_export_v1',false);
  let current={project:{customer:'A'},rows:[{name:'OP10'}]};
  f.window.__DFM_BRIDGE__={
    version:'2',labels:{'project.customer':'客户'},rules:{exclude:['audit']},
    exportData:()=>current,
    importData:value=>{current=value;}
  };
  f.handlers.load();f.timers.splice(0).forEach(fn=>fn());f.messages.length=0;
  f.send({type:'restore',runtime:{adapter:'json_export_v1',raw:{project:{customer:'B'},rows:[]}}});
  await tick();
  assert.equal(f.messages.at(-1).runtime.raw.project.customer,'B');
  assert.equal(f.messages.at(-1).runtime.source_version,'2');
});
