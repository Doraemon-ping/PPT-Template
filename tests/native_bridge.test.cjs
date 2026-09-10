const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('static/native_bridge.js','utf8').replace('__CHANNEL__','"test-channel"');
function fixture(){
  const handlers={},events={},messages=[],timers=[];
  const parent={postMessage:m=>messages.push(m)};
  const window={G:{cust:'original'},PR:[],MDB:[],TDB:[],IS:[],FDB:[],IDB:[],VH:[],GLBL:{},applyData(){},render(){},addEventListener:(type,fn)=>handlers[type]=fn};
  const document={querySelectorAll:()=>[],addEventListener:(type,fn)=>events[type]=fn};
  vm.runInNewContext(source,{window,document,parent,setTimeout:fn=>timers.push(fn),Event:class{constructor(type){this.type=type;}}});
  handlers.load();timers.splice(0).forEach(fn=>fn());
  const send=data=>handlers.message({source:parent,data:{channel:'test-channel',id:'1',...data}});
  return {window,events,messages,send,handlers,parent};
}
test('snapshot commits onchange-backed edits before reading globals',()=>{
  const f=fixture();let committed=0;
  const input={isConnected:true,dispatchEvent(){committed++;f.window.G.cust='edited';}};
  f.events.input({target:input});f.send({type:'snapshot'});
  assert.equal(committed,1);assert.equal(f.messages.at(-1).runtime.state.G.cust,'edited');
});
test('restore preserves empty arrays and source cache is frame-local',()=>{
  const a=fixture(),b=fixture();
  const state={G:{cust:'restored'},pr:[],mdb:[],tdb:[],is:[],fdb:[],idb:[],vh:[]};
  a.send({type:'restore',runtime:{adapter:'dfm_quote_v1',state}});
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
