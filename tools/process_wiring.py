"""1b 前端改造的"写入点清单"（单一来源）。

工序数据落表后，页面上**每一个会改工序/刀具行的动作**都必须走
`ProcessPage` 的行级保存；同时旧路径（改内存 + 整份保存）要原样留着，
因为开关没开时页面还要照旧工作。

清单里每条 = (说明, 新写法必须含的片段, 旧写法必须含的片段)。
`tools/check_process_wiring.py` 会：
1. 逐条核对两种写法都在；
2. 再扫一遍 legacy_app.js，找出**没被接管**的工序/刀具行写入点（漏一个就会
   "界面上改了、表里没变"），允许的例外写在 EXEMPT 里并写明原因。
"""

from __future__ import annotations

#: (说明, 行级保存的写法, 旧写法（开关关着时用）)
WRITE_POINTS: tuple[tuple[str, str, str], ...] = (
    ("新增工序", "ProcessPage.addProcess()", 'PR.push({nm:"机加工序-OP"'),
    ("删除工序", "ProcessPage.removeProcess(pi)", "PR.splice(pi,1)"),
    ("非加工时间计数", "ProcessPage.setNC(pi,field,val)", "PR[pi].nc[field]=parseFloat(val)||0"),
    ("换设备", "ProcessPage.setMachine(p,mid)", "PR[p].mid=mid"),
    ("设备成本刷新", "ProcessPage.refreshEquipmentPrice()", "PR[p].eqP=v"),
    ("工序名（工艺设置页）", "ProcessPage.setProcessField('+p+',\\'nm\\',this.value)", "PR['+p+'].nm=this.value"),
    ("设备台数（工艺设置页）", "ProcessPage.setProcessField('+p+',\\'mc\\',this.value)", "PR['+p+'].mc=parseFloat(this.value)||1"),
    ("设备价格（成本表）", "ProcessPage.setProcessField('+p+',\\'eqP\\',this.value)", "PR['+p+'].eqP=parseFloat(this.value)||0;render()"),
    ("夹具示意图·粘贴", "ProcessPage.setProcessPhoto('+pi+',u)", "PR['+pi+'].cI=u;render()"),
    ("夹具示意图·删除", "ProcessPage.setProcessPhoto('+pi+',\\'\\')", "PR['+pi+'].cI=\\'\\';render()"),
    ("从刀具库选刀", "ProcessPage.setToolFromLibrary(pi,i,tp)", "t.tp=tp;t.d=TDB[j].d||0"),
    ("刀具文本字段", "ProcessPage.setToolText(pi,i,f,v)", "PR[pi].tl[i][f]=v;render();"),
    ("刀具数字字段", "ProcessPage.setToolNumber(pi,i,f,v)", "PR[pi].tl[i][f]=parseFloat(v)||0;render();"),
    ("大刀标记", "ProcessPage.setBigTool(pi,i,c)", "PR[pi].tl[i].bg=c;render();"),
    ("新增刀具行", "ProcessPage.addTool(pi)", "tls.push({id:\"T\"+(tls.length+1)"),
    ("删除刀具行", "ProcessPage.removeTool(pi,i)", "PR[pi].tl.splice(i,1)"),
    ("刀具图片·粘贴/上传", "ProcessPage.setToolPhoto('+pi+','+i+',u)", "PR['+pi+'].tl['+i+'].fi=u;render()"),
    ("刀具图片·删除", "ProcessPage.setToolPhoto('+pi+','+i+',\\'\\')", "PR['+pi+'].tl['+i+'].fi=\\'\\';render()"),
)

#: 扫描"直接改工序数据"的赋值时要忽略的行（写明为什么安全）
EXEMPT: tuple[tuple[str, str], ...] = (
    ("PR=d.pr", "初始化：把服务端读模型灌进内存，不是用户改数据"),
    ("if(d.pr&&d.pr.length>0)PR=d.pr", "同上"),
    ("if(d.pr){for(var pp=0;pp<d.pr.length;pp++)", "applyData 里给老数据补默认值，不产生保存动作"),
    ("PR[pi].fixP", "init() 里给老数据补默认值（界面上没有夹具费输入框）"),
    ("PR[pi].eqP", "init() 里给老数据补默认值"),
    ("PR[p].fixP", "init() 里给老数据补默认值（界面上没有夹具费输入框）"),
    ("PR[p].eqP", "init() 里给老数据补默认值"),
    ("for(var p=0;p<PR.length;p++){if(!('fixP' in PR[p]))", "init() 补默认值整段"),
    ("return PR[k].cI;", "导出前把附件地址换成 data URL（只影响导出快照，表仍是权威）"),
)  # type: ignore[assignment]

#: 页面里必须出现的东西（index.html / legacy_app.js）
#: 注意：`?v=` 后面的版本号**故意不写死**（阶段 4 已经从 process-v1 升到 trash-v1）；
#: "所有脚本用同一个版本号"由 tools/check_served_page.py 与 tools/check_host_css.py 盯着。
STATIC_SNIPPETS: tuple[tuple[str, str], ...] = (
    ("index.html 加载 process_page.js", '<script src="/static/machining_dfm/process_page.js?v='),
    ("index.html 加载 issue_page.js", '<script src="/static/machining_dfm/issue_page.js?v='),
    ("index.html 加载 selection_page.js", '<script src="/static/machining_dfm/selection_page.js?v='),
    ("index.html 的脚本都带缓存版本号（?v=…）", "/static/machining_dfm/host.js?v="),
    ("legacy_app.js 有 ppOn() 开关", "function ppOn(){return typeof ProcessPage!=='undefined'&&ProcessPage.enabled();}"),
    ("legacy_app.js 有 ipOn() 开关", "function ipOn(){return typeof IssuePage!=='undefined'&&IssuePage.enabled();}"),
    ("legacy_app.js 有 spOn() 开关", "function spOn(){return typeof SelectionPage!=='undefined'&&SelectionPage.enabled();}"),
    ("host.js 暴露 status（模块提示用）", "api:request,adopt,current:()=>current,status,"),
    ("process_page.js 只认服务端开关", "return !!(project&&project.process_table);"),
    ("issue_page.js 只认服务端开关", "return !!(project&&project.issue_table);"),
    ("selection_page.js 只认服务端开关", "return !!(project&&project.selection_table);"),
    ("index.html 加载 history_page.js", '<script src="/static/machining_dfm/history_page.js?v='),
    ("index.html 加载 trash_page.js", '<script src="/static/machining_dfm/trash_page.js?v='),
    ("index.html 加载 changes_page.js", '<script src="/static/machining_dfm/changes_page.js?v='),
    ("legacy_app.js 有 hpOn() 开关", "function hpOn(){return typeof HistoryPage!=='undefined'&&HistoryPage.enabled();}"),
    ("history_page.js 只认服务端开关", "return !!(project&&project.history_table);"),
    ("process_page.js 写前先读行 id", "行 id 不缓存：DOM 里的下标只有对着最新列表才可靠。"),
    ("issue_page.js 写前先读行 id", "行 id 不缓存：DOM 下标只有对着最新列表才可靠"),
    ("selection_page.js 按格子写（下标不缓存）", "格子必须真的还在（字典可能刚被改过）"),
    ("history_page.js 按行写（下标不缓存）", "行必须真的还在（列表可能刚被别处改过）"),
)

# ---------------- 阶段 2a：问题清单（project_issues） ----------------

#: (说明, 行级保存的写法, 旧写法（开关关着时用）)
#: 说明：开关关着时的旧写法现在收在 iSet()/iPhoto() 两个小helper里
#: （`iSet` → `IS[i][key]=value;render()`），所以"旧路径"这一列写的是 helper 里的那一句。
ISSUE_WRITE_POINTS: tuple[tuple[str, str, str], ...] = (
    ("问题类型", "iSet('+i+',\\'tp\\',this.value)", "IS[i][key]=value;render()"),
    ("问题状态", "iSet('+i+',\\'st\\',this.value)", "IS[i][key]=value;render()"),
    ("问题描述", "iSet('+i+',\\'ds\\',this.value)", "IS[i][key]=value;render()"),
    ("修改方案", "iSet('+i+',\\'fx\\',this.value)", "IS[i][key]=value;render()"),
    ("客户回复", "iSet('+i+',\\'cr\\',this.value)", "IS[i][key]=value;render()"),
    ("挂到哪道工序（外键）", "IssuePage.setProcess('+i+',this.value)", "IS['+i+'].pr=this.value;render()"),
    ("优化前/后图片·粘贴", "IssuePage.setPhoto('+i+',\\''+k+'\\',u)", "IS['+i+'].'+k+'=u;render()"),
    ("优化前/后图片·删除", "IssuePage.setPhoto('+i+',\\''+k+'\\',null)", "IS['+i+'].'+k+'=null;render()"),
    ("新增问题", "IssuePage.addIssue()", 'IS.push({tp:"尺寸"'),
    ("删除问题", "IssuePage.removeIssue(i)", "IS.splice(i,1)"),
)

#: 扫问题时清单：直接改 IS[] 的地方要忽略的行（写明为什么安全）
ISSUE_EXEMPT: tuple[tuple[str, str], ...] = (
    ("IS=dc(D.is)", "初始化：把服务端读模型灌进内存，不是用户改数据"),
    ("if(d.is&&d.is.length>=0)IS=d.is", "同上"),
    ("IS=d.is", "同上"),
    ("_col(IS,'bI')", "shrinkImgs：压缩内存里的超大图后再整份保存（2a 之后图片走附件库，这段只对未落表的项目生效）"),
    ("_col(IS,'aI')", "同上"),
    ("for(var q=0;q<IS.length;q++)", "导出 PPT 只读 IS[]，不写回"),
)  # type: ignore[assignment]

# ---------------- 阶段 2b：选型（拆表后 = project_fixtures / project_gauges） ----------------

#: (说明, 按格子行级保存的写法, 旧写法（开关关着时用）)
SELECTION_WRITE_POINTS: tuple[tuple[str, str, str], ...] = (
    ("夹具选型", "SelectionPage.setSelection('fixture',k,v)", "G.fixQ[k]=v;save();"),
    ("夹具是否报价", "SelectionPage.setQuoted(\\'fixture\\',",
     "G.fixQC['+k+']=this.checked?1:0;save();render()"),
    ("检具选型", "SelectionPage.setSelection('gauge',k,v)", "G.insp[k]=v;save();"),
    ("检具是否报价", "SelectionPage.setQuoted(\\'gauge\\',",
     "G.inspQ['+k+']=this.checked?1:0;save();render()"),
)

#: 选型模块里必须按"这类选型的路径 + 格子下标"打接口（两类各一套：/fixtures、/gauges）
SELECTION_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("KIND_PATH={fixture:'fixtures',gauge:'gauges'}", "类别 → 路径段：夹具 /fixtures、检具 /gauges"),
    ("+(KIND_PATH[kind]||KIND_PATH.fixture)+'/'", "写入路径按类别拼（不再有 /selections/{kind}/{slot} 这种多态路径）"),
)

#: 扫选型时清单：直接改 fixQ/fixQC/insp/inspQ 的地方要忽略的行（写明为什么安全）
#: 注意 "是否报价"的两个旧写法收在 fxQuoteCall()/iqQuoteCall() 里（开关关着时返回的那一句），
#: 所以豁免清单里要按原文写上。
SELECTION_EXEMPT: tuple[tuple[str, str], ...] = (
    ("if(!G.fixQ||G.fixQ.length<4)G.fixQ=", "初始化的补齐（把数组撑到类别个数），不是用户改数据"),
    ("while(G.fixQ.length<fixClasses().length)G.fixQ.push('')", "同上"),
    ("if(!G.fixQC||G.fixQC.length<4)G.fixQC=", "同上"),
    ("while(G.fixQC.length<fixClasses().length)G.fixQC.push(1)", "同上"),
    ("if(!G.inspQ||G.inspQ.length<5)G.inspQ=", "同上"),
    ("while(G.inspQ.length<inspClasses().length)G.inspQ.push(1)", "同上"),
    ("if(!G.insp)G.insp=", "同上"),
    ("G.insp[_mi]=_me?", "初始化：把『只写了名字』的老值补成 类别|名称|图号（读时规整，不改用户数据）"),
    ("if(!d.G.insp)d.G.insp=", "applyData 里给老数据补默认值"),
    ("return 'G.fixQC['+k+']=this.checked?1:0;save();render()';",
     "夹具是否报价：开关关着时的旧写法（落在 fxQuoteCall 里，落表后走 SelectionPage.setQuoted）"),
    ("return 'G.inspQ['+k+']=this.checked?1:0;save();render()';",
     "检具是否报价：同上（落在 iqQuoteCall 里）"),
)  # type: ignore[assignment]

# ---------------- 阶段 3a：版本履历（project_versions，kind='history'） ----------------

#: (说明, 行级保存的写法, 旧写法（开关关着时用）)
#: 说明：四个格子与新增/删除收在 hpSet()/addVH()/delVH() 三个 helper 里，
#: 所以"旧路径"这一列写的是 helper 里的那一句；verRec() 的自动追加走 HistoryPage.add()。
HISTORY_WRITE_POINTS: tuple[tuple[str, str, str], ...] = (
    ("履历·日期格", "hpSet('+i+',\\'dt\\',this)", "VH[i][k]=v"),
    ("履历·版本号格", "hpSet('+i+',\\'ver\\',this)", "VH[i][k]=v"),
    ("履历·变更内容格", "hpSet('+i+',\\'ds\\',this)", "VH[i][k]=v"),
    ("履历·变更人格", "hpSet('+i+',\\'by\\',this)", "VH[i][k]=v"),
    ("履历·新增一行", "HistoryPage.add(rec)", "VH.push(rec)"),
    ("履历·删除一行（逻辑删除）", "HistoryPage.remove(i)", "VH.splice(i,1)"),
    ("履历·改客户版本时自动追加", "HistoryPage.add(_rec)", "VH.push(_rec)"),
)

#: 扫版本履历时清单：直接改 VH[] 的地方要忽略的行（写明为什么安全）
HISTORY_EXEMPT: tuple[tuple[str, str], ...] = (
    ("var MDB=[],TDB=[],PR=[],IS=[],IDB=[],VH=[],", "全局变量的声明与置空，不是用户改数据"),
    ("VH=dc(D.vh||[]);", "applyData：把服务端读模型灌进内存，不是用户改数据"),
    ("if(d.vh)VH=d.vh;else VH=dc(D.vh||[]);", "初始化：把服务端读模型灌进内存，不是用户改数据"),
    ("if(_EMB.vh&&(!d.vh||d.vh.length===0)){d.vh=_EMB.vh;", "导入便携 HTML 时把内嵌履历补进内存（随后照旧整份保存）"),
    ("var st={mdb:dc(MDB),tdb:dc(TDB),pr:dc(PR),is:dc(IS),fdb:dc(FDB),idb:dc(IDB),vh:dc(VH),G:dc(G)};",
     "导出 JSON 备份的载荷组装：读 VH[]，不写"),
    # 阶段 5 · §7.0：便携单文件 HTML 那一套已退休（buildPortableHTML / writeDataFile / dlPortable /
    # exportHTML 与 DATA_MARKER 全删了），原来豁免的那行"导出便携 HTML"载荷组装（var dd={…}）跟着
    # 一起没了，所以这里不再留它的豁免条目 —— 留一条对不上任何代码的豁免，等于给下一个写入点开后门。
    ("for(var i=0;i<VH.length;i++){var v=VH[i];", "版本履历卡片渲染：只读 VH[]"),
    ("if(VH.length===0)", "PPT 导出的版本表：只读 VH[]"),
    ("else{for(var v1=0;v1<VH.length;v1++)", "同上"),
)  # type: ignore[assignment]
