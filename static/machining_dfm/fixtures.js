'use strict';
/* 夹具库（Fixture Library）——按模具中心分组维护，独立于 legacy_app.js。
 *
 * 数据源：GET /api/machining-dfm/fixtures（类型化 fixtures 表 + assets 图片元数据）；
 * 模具中心来自字典表 fixture_centers（页面下拉/分组顺序与增删都走 /fixture-centers）。
 * 每次编辑只 PATCH 这一行的一个字段；图片二进制 PUT 上传，库里只留外键与 URL。
 * 渲染后把旧读模型 FDB 与 G.fcnX 就地同步，「夹具报价选型」与导出继续可用。
 */
window.FixturesPage=window.createNamedLibraryPage({
  global:'FixturesPage',
  title:'夹具库 / Fixture Library',
  itemLabel:'夹具',
  groupLabel:'模具中心',
  groupKey:'center',
  nameKey:'name',
  endpoint:'/fixtures',
  singular:'fixture',
  listKey:'fixtures',
  dictionary:'/fixture-centers',
  dictStateKey:'fcnX',
  legacyArray:'FDB',
  columns:[
    {key:'name',label:'名称',type:'text',width:'320px'},
    {key:'price',label:'价格(¥)',type:'real',width:'80px'},
    {key:'mc',label:'制造周期(天)',type:'int',width:'80px'},
    {key:'rmk',label:'备注',type:'text',width:'180px'}
  ],
  defaults:center=>({name:'新夹具',price:0,mc:0,rmk:''}),
  note:'夹具库说明：按模具中心分类维护夹具，名称/价格/制造周期/备注可直接编辑（每行独立保存），图片粘贴或上传到服务端；报价在「夹具报价选型」中勾选引用。类别为内置项不可删除，可新增自定义模具中心。'
});
