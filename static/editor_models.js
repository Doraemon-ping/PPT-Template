(function(root){
  'use strict';
  function copy(value){return JSON.parse(JSON.stringify(value));}
  function isImageSource(path,value){
    var sample=Array.isArray(value)?value[0]:value;
    return /^i\./.test(path||'')||typeof sample==='string'&&/^data:image\//.test(sample);
  }
  function cellBindingType(selectedType,path,value){
    return isImageSource(path,value)||selectedType==='image_region'?'image_region':selectedType==='text_template'?'text_template':'table_cell';
  }
  function tableBinding(bindings,info){
    var key=Object.keys(bindings||{}).find(function(k){var b=bindings[k];
      return b.type==='table_rows'&&(b.options&&b.options.shape_id!=null
        ?String(b.options.shape_id)===String(info.shape_id):b.shape===info.name);
    });
    return key===undefined?null:{key:key,binding:bindings[key]};
  }
  function insertPage(deck,page,index){
    if(!Number.isInteger(index)||index<0||index>deck.length)throw new Error('插入位置无效');
    var next=deck.slice();next.splice(index,0,copy(page));return next;
  }
  function aliases(entries,expression){
    var paths={},labels={};
    entries.forEach(function(e){if(paths[e.path])return;var label=e.label,n=2;
      while(labels[label]&&labels[label]!==e.path)label=e.label+'（'+n+++'）';
      paths[e.path]=label;labels[label]=e.path;
    });
    (expression||'').replace(/\{([A-Za-z_][A-Za-z0-9_.\[\]-]*)\}/g,function(_,path){
      if(!paths[path]){var label='其他已绑定参数 '+(Object.keys(paths).length+1);paths[path]=label;labels[label]=path;}
      return _;
    });
    return {paths:paths,labels:labels};
  }
  function toHuman(text,map){return text.replace(/\{([A-Za-z_][A-Za-z0-9_.\[\]-]*)\}/g,function(_,path){return '【'+map.paths[path]+'】';});}
  function toCode(text,map){
    var result=text.replace(/【([^【】]+)】/g,function(_,label){if(!map.labels[label])throw new Error('无法识别参数「'+label+'」，请从字段列表重新插入');return '{'+map.labels[label]+'}';});
    if(/[【】]/.test(result))throw new Error('参数标签不完整，请重新插入参数');
    return result;
  }
  function parseFormula(text){
    var blocks=[],re=/\[\[([^\[\]]*)\|([^\[\]]*)\]\]/g,match,cursor=0;
    while((match=re.exec(text))){if(match[1].includes('|')||match[2].includes('|'))throw new Error('分式结构无效');
      if(match.index>cursor)blocks.push({kind:'text',text:text.slice(cursor,match.index)});
      blocks.push({kind:'fraction',numerator:match[1],denominator:match[2]});cursor=re.lastIndex;
    }
    if(cursor<text.length)blocks.push({kind:'text',text:text.slice(cursor)});
    if(blocks.some(function(b){return b.kind==='text'&&(/\[\[|\]\]/.test(b.text));}))throw new Error('分式不完整；请使用“添加分式”');
    return blocks.length?blocks:[{kind:'text',text:''}];
  }
  function serializeFormula(blocks){return blocks.map(function(b){
    if(b.kind==='text'){
      if(/\[\[|\]\]/.test(b.text))throw new Error('请使用“添加分式”编辑分子和分母');
      return b.text;
    }
    if(!b.numerator.trim()||!b.denominator.trim())throw new Error('请填写分子和分母');
    if(/[\[\]|]/.test(b.numerator.replace(/\{[^}]*\}/g,''))||/[\[\]|]/.test(b.denominator.replace(/\{[^}]*\}/g,'')))throw new Error('暂不支持嵌套分式');
    return '[['+b.numerator+'|'+b.denominator+']]';
  }).join('');}
  var api={copy:copy,isImageSource:isImageSource,cellBindingType:cellBindingType,tableBinding:tableBinding,insertPage:insertPage,aliases:aliases,toHuman:toHuman,toCode:toCode,parseFormula:parseFormula,serializeFormula:serializeFormula};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.EditorModels=api;
})(typeof window!=='undefined'?window:this);
