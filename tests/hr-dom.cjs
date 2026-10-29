/* Native HR API simulations and React read models; real forms in hr-browser.cjs. */
module.exports=async({page,assert})=>{
 let dom=await page('hr-dashboard'),request=dom.window.eval('BackendPersistence.request'),counter=0;
 const post=async(key,data)=>(await request('/hr/records/'+key,{method:'POST',body:JSON.stringify({...data,requestKey:'dom-hr-'+(++counter)})})).record;
 const action=async(key,row,act)=>post(key+'/'+row.id+'/actions/'+act,{version:row.version});
 const employee=await post('employees',{employeeId:'EMP-1',name:'Database Employee',department:'Finance',designation:'Accountant',joiningDate:'2026-10-26',salary:10000});
 let p=await post('payroll',{employeeKey:employee.id,month:'2026-10',basic:10000,allowances:500,deductions:100});p=await action('payroll',p,'approve');p=await action('payroll',p,'pay');assert.equal(p.status,'Paid');
 const entries=await request('/erp/entries');assert.ok(entries.entries.some(e=>e.source==='payroll:'+p.id));assert.ok(entries.entries.some(e=>e.source==='payroll:'+p.id+':payment'));
 let m=await post('manpower',{department:'Production',position:'Operator',count:1,reason:'Expansion',requestedBy:'Manager'});m=await action('manpower',m,'approve');
 let c=await post('candidates',{name:'Candidate',position:'Operator',contact:'test@example.test',manpowerId:m.id});for(const act of ['shortlist','interview','select','offer'])c=await action('candidates',c,act);
 await post('attendance',{employeeKey:employee.id,date:'2026-10-26',attendanceStatus:'Present'});
 let leave=await post('leaves',{employeeKey:employee.id,from:'2026-11-01',to:'2026-11-02',leaveType:'Annual',reason:'Holiday'});leave=await action('leaves',leave,'approve');assert.equal(leave.days,2);
 let sep=await post('separations',{employeeKey:employee.id,lastWorkingDate:'2026-11-30',reason:'Exit',finalSettlement:0});sep=await action('separations',sep,'approve');sep=await action('separations',sep,'complete');
 dom.window.close();
 for(const [view,text] of [['hr-employees','Database Employee'],['hr-payroll','Paid'],['hr-recruitment','Offer Issued'],['hr-attendance','Present'],['hr-leave','Approved'],['hr-separation','Completed'],['hr-reports','Paid payroll total']]){dom=await page(view);assert.ok(dom.window.document.body.textContent.includes(text),view+' missing '+text);dom.window.close();}
};
