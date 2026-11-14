from unittest.mock import Mock
import pytest
from execution.firebase_backend import FirebaseBackend
from execution.push import Notifier, PushStore
import asyncio


def response(status, code=None):
    r=Mock(status_code=status)
    r.json.return_value={'error': {'details': [{'@type':'type.googleapis.com/google.firebase.fcm.v1.FcmError','errorCode':code}]}}
    return r


def test_push_counts_acceptance_and_only_prunes_unregistered():
    b=FirebaseBackend('project')
    b._session=Mock()
    b._session.post.side_effect=[response(200),response(403,'SENDER_ID_MISMATCH'),response(404),response(404,'UNREGISTERED'),OSError('offline')]
    assert b.send_push(['a','b','c','d','e'],{})=={'sent':1,'failed':4,'dead':['d']}


def test_missing_credentials_never_reports_success_or_removes_tokens(tmp_path):
    b=FirebaseBackend('project');b.push_disabled_reason='No credentials'
    store=PushStore(tmp_path/'tokens.json');store.add('token','admin@example.com')
    result=asyncio.run(Notifier(b,store).send({'title':'test'}))
    assert result=={'sent':0,'failed':1,'registered':1}
    assert store.tokens()==['token']


@pytest.mark.parametrize('claims',[
    {'iss':'https://accounts.google.com','sub':'user'},
    {'iss':'https://securetoken.google.com/project','sub':''},
    {'iss':'https://securetoken.google.com/project','sub':'x'*129},
])
def test_token_issuer_and_subject_rejected(monkeypatch,claims):
    monkeypatch.setattr('execution.firebase_backend.id_token.verify_firebase_token',lambda *a,**k:claims)
    with pytest.raises(ValueError):FirebaseBackend('project').verify_id_token('token')


def test_valid_token_claims_preserved(monkeypatch):
    claims={'iss':'https://securetoken.google.com/project','sub':'user'}
    verifier=Mock(return_value=claims)
    monkeypatch.setattr('execution.firebase_backend.id_token.verify_firebase_token',verifier)
    assert FirebaseBackend('project').verify_id_token('token')==claims
    assert verifier.call_args.kwargs['audience']=='project'
