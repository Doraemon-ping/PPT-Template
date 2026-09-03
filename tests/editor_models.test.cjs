const test=require('node:test'),assert=require('node:assert/strict');
const m=require('../static/editor_models.js');

test('cell image binding keeps image type even when field currently has no image',()=>{
  assert.equal(m.cellBindingType('table_cell','i.front[0]',undefined),'image_region');
  assert.equal(m.cellBindingType('table_cell','custom.photo','data:image/png;base64,AAA'),'image_region');
  assert.equal(m.cellBindingType('image_region','custom.photo',undefined),'image_region');
  assert.equal(m.cellBindingType('text_template','f.name','part'),'text_template');
  assert.equal(m.cellBindingType('table_cell','f.name','part'),'table_cell');
  assert.equal(m.isImageSource('f.name','part'),false);
});

test('table config is recovered by shape identity across legacy and new binding keys',()=>{
  const bindings={
    'rows:表格':{type:'table_rows',shape:'表格',source:'t.fileStat',options:{shape_id:4,rows_per_page:5}},
    'rows:shape:5':{type:'table_rows',shape:'表格',source:'t.issues',options:{shape_id:5,rows_per_page:2}}
  };
  assert.equal(m.tableBinding(bindings,{name:'表格',shape_id:4}).binding.options.rows_per_page,5);
  assert.equal(m.tableBinding(bindings,{name:'表格',shape_id:'5'}).binding.options.rows_per_page,2);
  assert.equal(m.tableBinding(bindings,{name:'表格',shape_id:6}),null);
  assert.equal(m.tableBinding({old:{type:'table_rows',shape:'表格'}},{name:'表格',shape_id:4}).key,'old');
});

test('unsaved table pagination and column mapping are retained and block generation until saved',()=>{
  const fs=require('node:fs'),vm=require('node:vm');
  const source=fs.readFileSync(require.resolve('../static/editor_ux.js'),'utf8');
  const bar={_info:{key:'shape:4'},_draftId:'page1:shape:4',_mapTbl:'fileStat',_dirty:true};
  const els={'#selBar':bar,'#inpKeepRows':{value:'1'},'#inpStyleRow':{value:'2'},'#inpRowsPerPage':{value:'5'}};
  const context={state:{deck:[{_editorId:'page1'}]},$:k=>els[k],$$:()=>[{dataset:{col:'0'},value:'name'}]};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function bindingDraftKey'),source.indexOf('function restoreBindingDraft')),context);
  assert.equal(context.hasPendingBindingDrafts(),true);
  assert.equal(context.state.bindingDrafts['page1:shape:4'].rowsPerPage,'5');
  assert.equal(context.state.bindingDrafts['page1:shape:4'].columns[0],'name');
  context.clearBindingDraft(bar._info);
  assert.equal(context.hasPendingBindingDrafts(),false);
});
test('reuse deep copies bindings, formula, images and page rules without touching source',()=>{
  const source={source:3,template:'other',repeat:'t.issues',condition:'f.show',images:{logo:'i.logo[0]'},bindings:{a:{type:'formula',source:'f',options:{template:'F = [[{f.a}|10]]'}}}};
  const old=[{source:1,template:'base',bindings:{text:{source:'f.partNo'}}}];
  const snapshot=JSON.stringify(source),before=JSON.stringify(old),next=m.insertPage(old,source,1);
  assert.deepEqual(next[1],source);next[1].bindings.a.options.template='changed';next[1].images.logo='different';
  assert.equal(JSON.stringify(source),snapshot);assert.equal(JSON.stringify(old),before);assert.equal(next[0],old[0]);
});
test('reusing same source twice makes independent instances',()=>{const s={source:1,bindings:{a:{source:'f.x'}}};const d=m.insertPage(m.insertPage([],s,0),s,1);d[0].bindings.a.source='f.y';assert.equal(d[1].bindings.a.source,'f.x');});
test('invalid insertion fails without mutation',()=>{const d=[{}];assert.throws(()=>m.insertPage(d,{},-1));assert.throws(()=>m.insertPage(d,{},2));assert.equal(d.length,1);});
test('legacy formulas round trip through Chinese tokens and fraction rows',()=>{
  const raw='F产 = [[A产|10]] = [[{ppt.force.area_part} cm² × {f.castP} MPa|10]] = {ppt.force.part} kN';
  const aliases=m.aliases([{path:'f.castP',label:'铸造压力'},{path:'ppt.force.area_part',label:'产品面积'},{path:'ppt.force.part',label:'产品胀型力'}],raw);
  const human=m.toHuman(raw,aliases);assert.ok(human.includes('【铸造压力】'));assert.ok(!human.includes('f.castP'));
  assert.equal(m.toCode(m.serializeFormula(m.parseFormula(human)),aliases),raw);
});
test('duplicate labels get unique tokens and unknown existing paths are not lost',()=>{
  const raw='{f.a} + {f.b} + {custom.value}',aliases=m.aliases([{path:'f.a',label:'面积'},{path:'f.b',label:'面积'}],raw);
  assert.notEqual(aliases.paths['f.a'],aliases.paths['f.b']);assert.equal(m.toCode(m.toHuman(raw,aliases),aliases),raw);
});
test('invalid fields and incomplete fractions cannot silently save',()=>{
  const aliases=m.aliases([{path:'f.a',label:'面积'}],'');assert.throws(()=>m.toCode('【未知】',aliases));assert.throws(()=>m.toCode('【面积',aliases));
  assert.throws(()=>m.parseFormula('[[a|b'));assert.throws(()=>m.serializeFormula([{kind:'fraction',numerator:'',denominator:'10'}]));
  assert.throws(()=>m.serializeFormula([{kind:'text',text:'[[a|b'}]));
});
