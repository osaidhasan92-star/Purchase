/* Shared approval inbox, loaded in every workspace. Text-only DOM rendering. */
(() => {
  const el = (tag, text, parent) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.append(node);
    return node;
  };
  const style = el('style', undefined, document.head);
  style.textContent = '.approval-launch{position:fixed;right:18px;bottom:18px;z-index:900;padding:12px 18px;background:#173b53;color:white;border:0;border-radius:8px}.approval-inbox{width:min(1000px,94vw);max-height:90vh;padding:24px;border:1px solid #ccd4dc;border-radius:12px;color:#172338}.approval-inbox::backdrop{background:#10203099}.approval-inbox header{display:flex;justify-content:space-between;align-items:center;gap:12px}.approval-inbox article{padding:16px 0;border-bottom:1px solid #dae1e7}.approval-inbox button,.approval-inbox select,.approval-inbox input,.approval-inbox textarea{font:inherit;padding:8px;margin:4px;max-width:100%}.approval-inbox textarea{display:block;width:95%;min-height:65px}.approval-inbox pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f8;padding:12px}.approval-inbox [role=alert]{color:#a12121}.approval-inbox form{display:flex;flex-wrap:wrap;gap:8px;align-items:center}';
  const launch = el('button', 'Pending Approvals', document.body);
  launch.className = 'approval-launch'; launch.type = 'button';
  const bodyRoot=document.body;
  const observer=new MutationObserver(()=>{if(!bodyRoot.isConnected)observer.disconnect();else if(!launch.isConnected)bodyRoot.append(launch);});
  observer.observe(bodyRoot,{childList:true});
  let dialog;
  const api = (path, data, method='POST') => BackendPersistence.request(path, data ? {method, body:JSON.stringify(data)} : {});
  launch.onclick = async () => {
    if (dialog?.open) return;
    dialog?.remove();
    dialog = el('dialog', undefined, document.body); dialog.className='approval-inbox';
    dialog.setAttribute('aria-label','Pending Approvals');
    const header=el('header',undefined,dialog);el('h2','Pending Approvals',header);
    const close=el('button','Close',header);close.onclick=()=>dialog.close();
    const notice=el('p','Review financial actions and record a reason for each decision.',dialog);
    const error=el('p','',dialog);error.setAttribute('role','alert');
    const controls=el('div',undefined,dialog),content=el('section',undefined,dialog);
    const filter=el('select',undefined,controls);filter.setAttribute('aria-label','Approval status');
    for(const status of ['Pending','Approved','Rejected','All']){const option=el('option',status,filter);option.value=status;}
    const refresh=el('button','Refresh',controls);
    let page=1;const previous=el('button','Previous',controls),next=el('button','Next',controls);
    previous.onclick=()=>{page=Math.max(1,page-1);void load();};next.onclick=()=>{page++;void load();};
    const load=async()=>{
      error.textContent='';content.replaceChildren();
      try{
        const data=await api('/approvals?page='+page+'&status='+(filter.value==='All'?'':filter.value));const rows=data.items;previous.disabled=page===1;next.disabled=page*data.pageSize>=data.total;
        notice.textContent=data.total+' '+filter.value.toLowerCase()+' request(s). Amounts are in PKR. Creators and requesters cannot approve their own work.';
        if(!rows.length)el('p','No requests to display.',content);
        for(const row of rows){
          const card=el('article',undefined,content);
          el('h3','#'+row.id+' · '+row.module+' · PKR '+Number(row.amount).toLocaleString('en-PK',{minimumFractionDigits:2}),card);
          el('p',row.status+' · Requested '+row.createdAt+' · Requester: '+row.requesterId,card);
          el('p',row.blocked?'No independent approver has sufficient authority. Ask an administrator to configure a limit.':'Authorized approvers: '+row.approvers.map(a=>a.name).join(', '),card);
          const details=el('details',undefined,card);el('summary','Review requested action',details);
          const action=row.path.split('/').slice(3).filter(p=>!['commands','actions'].includes(p)).join(' / ');
          el('p',action,details);
          const fields=Object.fromEntries(Object.entries(row.payload).filter(([key])=>!['version','parentVersion','requestKey','lineVersion','debitVersion','creditVersion'].includes(key)));
          if(row.source&&Object.keys(row.source).length)el('pre',JSON.stringify(Object.fromEntries(Object.entries(row.source).filter(([key])=>!['version','actions'].includes(key))),null,2),details);
          el('pre',JSON.stringify(fields,null,2),details);
          if(row.reason)el('p','Decision: '+row.reason+' · '+row.decidedBy+' · '+row.decidedAt,card);
          if(row.canDecide){
            const reason=el('textarea',undefined,card);reason.maxLength=1000;reason.placeholder='Reason for this decision';reason.setAttribute('aria-label','Decision reason for request '+row.id);
            for(const decision of ['approve','reject']){
              const button=el('button',decision==='approve'?'Approve and execute':'Reject',card);
              button.onclick=async()=>{
                if(!reason.value.trim()){error.textContent='Enter a reason for your decision.';reason.focus();return;}
                card.querySelectorAll('button').forEach(b=>b.disabled=true);
                try{await api('/approvals/'+row.id+'/'+decision,{reason:reason.value});await load();}
                catch(e){error.textContent=e.message;card.querySelectorAll('button').forEach(b=>b.disabled=false);}
              };
            }
          }
        }
      }catch(e){error.textContent=e.message;}
    };
    filter.onchange=()=>{page=1;void load();};refresh.onclick=load;dialog.showModal();
    try{
      await api('/auth/me');await load();
      let limits;try{limits=await api('/approvals/limits');}catch(e){if(e.status!==403)throw e;}
      if(limits){
        const settings=el('details',undefined,dialog);el('summary','Approval limits (administrator)',settings);
        el('p','Defaults: Manager PKR 100,000; Finance PKR 1,000,000; Admin PKR 10,000,000. Existing module permissions still apply. Set a limit of zero for zero-value actions only.',settings);
        const form=el('form',undefined,settings),user=el('select',undefined,form),module=el('select',undefined,form),amount=el('input',undefined,form);
        user.setAttribute('aria-label','Approver');module.setAttribute('aria-label','Module');amount.setAttribute('aria-label','PKR approval limit');
        for(const u of limits.users){const o=el('option',u.name+' ('+u.role+')',user);o.value=u.id;}
        for(const m of limits.modules){const o=el('option',m,module);o.value=m;}
        amount.type='number';amount.min='0';amount.step='.01';amount.required=true;
        const existing=el('p','',settings);
        const show=()=>{const custom=limits.items.find(r=>r.userId===user.value&&r.module===module.value);amount.value=custom?.amount||'';existing.textContent=custom?'Current override: PKR '+custom.amount:'Role default applies.';};
        user.onchange=show;module.onchange=show;show();
        el('button','Save limit',form).type='submit';
        form.onsubmit=async event=>{event.preventDefault();try{limits=await api('/approvals/limits',{userId:user.value,module:module.value,amount:amount.value},'PUT');show();await load();}catch(e){error.textContent=e.message;}};
      }
    }catch(e){error.textContent=e.message;}
  };
})();
