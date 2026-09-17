'use strict';
// Forms discover the workbench URL from their own backend (same-origin).
document.addEventListener('click',async function(event){
  const anchor=event.target.closest('a');
  if(!anchor)return;
  const target=new URL(anchor.href,location.href);
  if(target.pathname!=='/template-editor')return;
  event.preventDefault();
  try{
    const source=target.searchParams.get('app_id')||'dfm';
    let project=target.searchParams.get('project_id')||'';
    if(window.NamedProjects&&source==='dfm')project=await window.NamedProjects.saveForWorkbench();
    const query=new URLSearchParams({app_id:source,project_id:project});
    const response=await fetch('/api/integration/workbench-link?'+query);
    if(!response.ok)throw new Error('无法读取 PPT 工作台地址');
    const url=new URL((await response.json()).url,location.href);
    if(target.searchParams.has('scheme'))url.searchParams.set('scheme',target.searchParams.get('scheme'));
    location.href=url.href;
  }catch(error){if(typeof toast==='function')toast(error.message);else alert(error.message);}
});
