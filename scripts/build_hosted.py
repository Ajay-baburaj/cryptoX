"""Build the public Firebase Hosting assets; never copies server state or secrets."""
import argparse
import json
from pathlib import Path
import shutil
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--api-base',required=True);args=p.parse_args()
u=urlparse(args.api_base)
if u.scheme!='https' or not u.netloc or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
    p.error('--api-base must be an HTTPS origin')
config=json.loads((ROOT/'config/firebase_web.json').read_text())
keys=('apiKey','authDomain','projectId','appId','messagingSenderId','storageBucket','vapidKey')
public={k:config[k] for k in keys if k in config}
assert public['projectId']=='cryptox-5a848'
out=ROOT/'dist-hosted';shutil.rmtree(out,ignore_errors=True);shutil.copytree(ROOT/'frontend',out)
(out/'runtime-config.js').write_text('window.CryptoXConfig = '+json.dumps({'apiBase':args.api_base.rstrip('/'),'firebase':public})+';\n')
print('Hosting assets built in',out)
