(function(root){
  'use strict';
  function copy(value){return JSON.parse(JSON.stringify(value));}
  // 图片字段的值有三种形态：data: 内联图片、http(s) 图片地址（接口接入的图片字段，
  // 地址常常没有扩展名）、以及本地文件路径；i. 前缀是服务端字段目录给出的图片信号。
  function isImageValue(value){
    var sample=Array.isArray(value)?value[0]:value;
    if(typeof sample!=='string')return false;
    var text=sample.trim();
    if(!text)return false;
    if(/^data:image\//i.test(text))return true;
    return /^https?:\/\/[^\s]+\.(png|jpe?g|gif|webp|bmp|svg)(\?[^\s]*)?$/i.test(text);
  }
  function isImageSource(path,value){
    return /^i\./.test(path||'')||isImageValue(value);
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
  /* 工作台 API 路径的作用域：
     普通模式（表单跳转）用 app_id 选择表单提供方取数；
     工作空间模式的数据来自 API Connector（Dataset），带上 app_id 会让后端去解析一个
     并不存在的表单提供方，模板清单/扫描/预览/生成会全部 404 —— 所以工作空间不发 app_id。 */
  function scopedApiPath(path,options){
    var opts=options||{};
    var url=new URL(path,opts.origin||'http://127.0.0.1');
    if(!opts.workspaceId&&opts.appId)url.searchParams.set('app_id',opts.appId);
    return url.pathname+url.search;
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
  var api={copy:copy,isImageSource:isImageSource,isImageValue:isImageValue,cellBindingType:cellBindingType,tableBinding:tableBinding,insertPage:insertPage,scopedApiPath:scopedApiPath,aliases:aliases,toHuman:toHuman,toCode:toCode,parseFormula:parseFormula,serializeFormula:serializeFormula};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.EditorModels=api;
})(typeof window!=='undefined'?window:this);
