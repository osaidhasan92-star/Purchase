/* Administration uses compact bootstrap and dedicated resource APIs. */
window.addEventListener('workspace:ready',async()=>{
 const view=nativeAdminView();if(!view)return;
 await initAppState();if(!APP_STATE)return;
 const titles={approvals:'Pending Approvals',users:'Users & Roles',activities:'Activity Log',data:'Import / Export Records'};
 if(view==='activities'&&!guard('activities'))return;
 if(view!=='activities'&&view!=='approvals'&&currentUser()?.role!=='Admin'){renderModernWorkspace('admin',titles[view],'Administrator access required','<p>Administrator access is required.</p>');return;}
 renderModernWorkspace(view==='users'?'users':view==='activities'?'activities':'admin',titles[view],'Pakistan · PKR','', 'admin',{adminView:view});
});
