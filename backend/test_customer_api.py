"""Record-level API: bounded reads, permissions and stale-edit protection."""
from backend.test_app import app, session, patch


def create(client,headers,name='Modern customer',request_key='modern-customer-001'):
    response=client.post('/api/customers',headers=headers,json=dict(name=name,requestKey=request_key))
    assert response.status_code==200,response.json
    return response.json['customer']


def test_bootstrap_has_no_business_or_payroll_payload(app):
    client,h=session(app)
    assert patch(client,h,dict(customers=[dict(id=1,name='Existing')],vendors=[dict(id=2,name='Supplier')])).status_code==200
    response=client.get('/api/ui/bootstrap')
    assert response.status_code==200
    assert response.json['user']['id']=='admin' and response.json['csrfToken']
    assert not response.json['state']['customers'] and not response.json['state']['vendors']
    assert all(not rows for rows in response.json['hr'].values())
    assert app.test_client().get('/api/ui/bootstrap').status_code==401


def test_customer_record_create_update_and_legacy_visibility(app):
    client,h=session(app)
    assert patch(client,h,dict(vendors=[dict(id=5,name='Preserved supplier')])).status_code==200
    customer=create(client,h)
    assert isinstance(customer['id'],int) and customer['id']<2**53
    assert customer['createdBy']=='admin' and customer['version']
    result=client.get('/api/customers').json
    assert result['total']==1 and result['items'][0]['name']=='Modern customer'
    # Legacy CRM/Sales registers see the new customer without a second import.
    state=client.get('/api/state').json['state']
    assert state['customers'][0]['id']==customer['id'] and state['vendors'][0]['name']=='Preserved supplier'
    response=client.patch('/api/customers/'+str(customer['id']),headers=h,json=dict(name='Updated',version=customer['version']))
    assert response.status_code==200,response.json
    updated=response.json['customer']
    assert updated['version']!=customer['version'] and updated['createdBy']=='admin'
    partial=client.patch('/api/customers/'+str(customer['id']),headers=h,json=dict(contact='Contact update',version=updated['version']))
    assert partial.status_code==200 and partial.json['customer']['name']=='Updated'
    assert partial.json['customer']['contact']=='Contact update'
    assert client.patch('/api/customers/'+str(customer['id']),headers=h,json=dict(name='Stale overwrite',version=customer['version'])).status_code==409
    assert client.patch('/api/customers/'+str(customer['id']),headers=h,json=dict(name='No version')).status_code==428
    assert client.get('/api/customers').json['items'][0]['name']=='Updated'


def test_customer_pagination_search_idempotency_and_permissions(app):
    client,h=session(app)
    for index in range(31):create(client,h,'Customer '+str(index).zfill(2),'modern-key-'+str(index).zfill(4))
    first=client.get('/api/customers?page=1&pageSize=25').json
    second=client.get('/api/customers?page=2&pageSize=25').json
    assert first['total']==31 and len(first['items'])==25 and len(second['items'])==6
    found=client.get('/api/customers?search=customer%2030').json
    assert found['total']==1 and found['items'][0]['name']=='Customer 30'
    assert client.get('/api/customers?pageSize=101').status_code==400
    assert client.get('/api/customers?page=invalid').status_code==400
    again=create(client,h,'Customer 00','modern-key-0000')
    assert again['id']==first['items'][0]['id'] and client.get('/api/customers').json['total']==31
    assert client.post('/api/customers',headers=h,json=dict(name='Different details',requestKey='modern-key-0000')).status_code==409
    viewer,vh=session(app,'viewer')
    assert viewer.get('/api/customers').json['total']==31
    assert viewer.post('/api/customers',headers=vh,json=dict(name='Unauthorized',requestKey='unauthorized-key')).status_code==403
    assert viewer.patch('/api/customers/'+str(again['id']),headers=vh,json=dict(name='Changed',version=again['version'])).status_code==403
    hr,_=session(app,'hr');assert hr.get('/api/customers').status_code==403


def test_native_and_legacy_writers_detect_conflicts(app):
    client,h=session(app)
    customer=create(client,h)
    snapshot=client.get('/api/state').json
    assert client.patch('/api/customers/'+str(customer['id']),headers=h,json=dict(name='Native edit',version=customer['version'])).status_code==200
    assert patch(client,h,dict(customers=snapshot['state']['customers']),revision=snapshot['revision']).status_code==409
    latest=client.get('/api/customers').json['items'][0]
    rows=client.get('/api/state').json['state']['customers'];rows[0]['contact']='Legacy CRM contact'
    assert patch(client,h,dict(customers=rows)).status_code==200
    assert client.patch('/api/customers/'+str(customer['id']),headers=h,json=dict(name='Stale native edit',version=latest['version'])).status_code==409
    assert client.get('/api/customers').json['items'][0]['contact']=='Legacy CRM contact'


def test_customer_details_do_not_leak_other_sales_teams(app):
    from backend.test_app import PASSWORD
    client,h=session(app);customer=create(client,h)
    assert patch(client,h,dict(salesOrders=[dict(id=1,orderNo='SO-PRIVATE',customerId=customer['id'],status='Draft',total=100)])).status_code==200
    seller,_=session(app,'seller')
    details=seller.get('/api/customers/'+str(customer['id'])).json
    assert details['customer']['name']=='Modern customer'
    assert details['orders']==[] and details['orderTotal']==0
    assert client.get('/api/customers/'+str(customer['id'])).json['orderTotal']==1
    response=client.post('/api/users',headers=h,json=dict(name='Finance',email='finance@example.test',role='Finance',password=PASSWORD,active=True))
    assert response.status_code==200
    finance,_=session(app,'finance')
    assert finance.get('/api/customers/'+str(customer['id'])).json['orderTotal']==1
    assert client.post('/api/customers',headers=h,json=dict(name='Forged',requestKey='invalid-owner-key',createdBy='seller')).status_code==400
