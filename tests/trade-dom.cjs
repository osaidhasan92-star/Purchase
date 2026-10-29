/* Exercise native transaction resources and verify their React read models.
 * Real form interactions are covered independently by trade-browser.cjs. */
module.exports=async({page,assert})=>{
 let screen=await page('purchase-dashboard');const request=screen.window.eval('BackendPersistence.request');let counter=0;
 const call=(path,body)=>request(path,{method:'POST',body:JSON.stringify(body)});
 const create=async(key,data)=>(await call('/trade/'+key,{...data,requestKey:'dom-trade-'+(++counter)})).record;
 const action=async(key,row,name)=>(await call('/trade/'+key+'/'+row.id+'/actions/'+name,{version:row.version,requestKey:'dom-action-'+(++counter)})).record;
 const get=async(key,id)=>(await request('/trade/'+key+'/'+id)).record;
 const product=(await call('/products',{name:'Workflow raw material',sku:'RAW-UI-1',rate:10,requestKey:'dom-product-raw-001'})).record;
 const vendor=(await request('/vendors?pageSize=100')).items[0];
 const customer=(await call('/customers',{name:'Native workflow customer',requestKey:'dom-customer-flow-001'})).customer;
 let req=await create('requests',{department:'Operations',items:[{productId:product.id,quantity:20,rate:10}]});for(const step of ['submit','approve'])req=await action('requests',req,step);
 let rfq=await create('rfqs',{requestId:req.id,parentVersion:req.version,vendorIds:[vendor.id],dueDate:'2027-12-31'});rfq=await action('rfqs',rfq,'send');
 let quote=await create('quotations',{rfqId:rfq.id,parentVersion:rfq.version,vendorId:vendor.id,validUntil:'2027-12-31',items:[{productId:product.id,quantity:20,rate:10}]});quote=await action('quotations',quote,'award');
 let order=await create('orders',{quotationId:quote.id,parentVersion:quote.version,deliveryDate:'2027-12-31'});for(const step of ['submit','approve','send'])order=await action('orders',order,step);
 for(let part=1;part<=2;part++){
  await create('receipts',{poId:order.id,parentVersion:order.version,items:[{lineIndex:0,receivedQty:10,acceptedQty:10,rejectedQty:0}]});order=await get('orders',order.id);
  let bill=await create('invoices',{poId:order.id,parentVersion:order.version,invoiceNo:'DOM-NATIVE-BILL-'+part,dueDate:'2027-12-31',items:[{lineIndex:0,quantity:10}]});bill=await action('invoices',bill,'approve');
  await create('payments',{invoiceId:bill.id,parentVersion:bill.version,amount:100,method:'Bank Transfer'});order=await get('orders',order.id);
  assert.equal(order.status,part===1?'Partially Received':'Completed');
 }
 let sale=await create('salesQuotations',{customerId:customer.id,items:[{productId:product.id,quantity:4,rate:30}]});for(const step of ['submit','approve','send','accept'])sale=await action('salesQuotations',sale,step);
 let so=await create('salesOrders',{quotationId:sale.id,parentVersion:sale.version});
 let delivery=await create('deliveries',{orderId:so.id,parentVersion:so.version,items:[{lineIndex:0,deliveredQty:4}]});await action('deliveries',delivery,'deliver');so=await get('salesOrders',so.id);
 const invoice=await create('customerInvoices',{orderId:so.id,parentVersion:so.version,dueDate:'2027-12-31',items:[{lineIndex:0,quantity:4}]});
 await create('customerPayments',{invoiceId:invoice.id,parentVersion:invoice.version,amount:40,method:'Cash'});
 const partial=await get('customerInvoices',invoice.id);assert.equal(partial.paidAmount,40);assert.equal(partial.balance,80);
 screen.window.close();
 for(const [view,number,status] of [['orders',order.poNo,'Completed'],['sales-invoices',invoice.invoiceNo,'Partially Paid']]){
  screen=await page(view);assert.match(screen.window.document.body.textContent,new RegExp(number));assert.match(screen.window.document.body.textContent,new RegExp(status));screen.window.close();
 }
 return {rawId:product.id};
};
