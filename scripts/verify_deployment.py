"""Run on the VM: internal authenticated feed check and FCM validation-only request.

Does not prove a real user can sign in or a browser displays notifications.
"""
from datetime import datetime, timezone
import json
import requests
from execution.auth import AuthConfig, COOKIE, make_session

base='http://127.0.0.1:8000'
cfg=AuthConfig.from_env()
origin='https://cryptox-5a848.web.app'
r=requests.get(base+'/api/ob1h',headers={'Origin':origin},timeout=15)
assert r.status_code==401 and r.headers.get('Access-Control-Allow-Origin')==origin
pre=requests.options(base+'/api/ob1h',headers={'Origin':origin,'Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'authorization'},timeout=15)
assert pre.status_code==204
bad=requests.get(base+'/api/ob1h',headers={'Authorization':'Bearer invalid'},timeout=15)
assert bad.status_code==401
cookie=make_session(cfg.secret,'admin@cryptox.com',60)
r=requests.get(base+'/api/ob1h',cookies={COOKIE:cookie},timeout=15);r.raise_for_status()
d=r.json();assert d['status']=='ok',d['status']
age=(datetime.now(timezone.utc)-datetime.fromisoformat(d['last_update'])).total_seconds()
assert age<120,age
assert d['mark_price']>0
print(json.dumps({'api_protected':True,'hosted_cors':True,'engine_status':d['status'],'feed_age_seconds':round(age,1),'mark_price':d['mark_price'],'started_at':d['started_at']}))
session=cfg.backend._authed();assert session is not None
r=session.post(f'https://fcm.googleapis.com/v1/projects/{cfg.web_config["projectId"]}/messages:send',json={'validate_only':True,'message':{'topic':'cryptox-deployment-check','data':{'title':'validation-only'}}},timeout=20)
print('FCM validation-only HTTP',r.status_code)
if r.status_code!=200:
 print(r.json().get('error',{}).get('status','unknown error'))
 r.raise_for_status()
print('No notification sent; real browser receipt remains to be tested.')
