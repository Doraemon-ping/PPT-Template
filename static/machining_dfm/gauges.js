'use strict';
/* 检具库（Inspection Tool Library）——按检具类别分组维护，独立于 legacy_app.js。
 *
 * 数据源：GET /api/machining-dfm/gauges（类型化 gauges 表 + assets 图片元数据）；
 * 检具类别来自字典表 gauge_categories（分组顺序与增删都走 /gauge-categories）。
 * 每次编辑只 PATCH 这一行的一个字段；图片二进制 PUT 上传，库里只留外键与 URL。
 * 渲染后把旧读模型 IDB 与 G.icnX 就地同步，「检具选型报价」与导出继续可用。
 * 价格单位是万元（未税），与页面一致。
 */
window.GaugesPage=window.createNamedLibraryPage({
  global:'GaugesPage',
  title:'检具库 / Inspection Tool Library',
  itemLabel:'检具',
  groupLabel:'检具类别',
  groupKey:'type',
  nameKey:'name',
  endpoint:'/gauges',
  singular:'gauge',
  listKey:'gauges',
  dictionary:'/gauge-categories',
  dictStateKey:'icnX',
  legacyArray:'IDB',
  columns:[
    {key:'name',label:'检具名称',type:'text',width:'220px'},
    {key:'drw',label:'检具图号',type:'text',width:'150px'},
    {key:'prdSize',label:'产品尺寸(mm)',type:'text',width:'130px'},
    {key:'inspSize',label:'检具尺寸(mm)',type:'text',width:'130px'},
    {key:'price',label:'价格(万¥)',type:'real',width:'80px'},
    {key:'dc',label:'设计周期(天)',type:'int',width:'80px'},
    {key:'mc',label:'制造周期(天)',type:'int',width:'80px'}
  ],
  defaults:type=>({name:'新检具',drw:'',prdSize:'',inspSize:'',price:0,dc:0,mc:0}),
  note:'检具库说明：按检具类别分类维护检具，名称/图号/产品尺寸/检具尺寸/价格/设计周期/制造周期可直接编辑（每行独立保存），价格单位为万元（未税），图片粘贴或上传到服务端；选型报价在「检具选型报价」中按产品尺寸/检具尺寸检索引用。类别为内置项不可删除，可新增自定义检具类别。'
});
