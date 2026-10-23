import json, re, urllib.parse, ig_login as L

# 1) template loading + patching
m, url, hdrs, body = L.build_request('send_login', 'testuser_xyz', enc_pwd='#PWD_INSTAGRAM:4:1234567890:TESTBLOB==')
assert 'testuser_xyz' in body and 'duck.88424236' not in body, 'username patch fail'
assert '#PWD_INSTAGRAM:4:1234567890:TESTBLOB==' in urllib.parse.unquote(body), 'encpwd patch fail'
assert L.TEMPLATE_WATERFALL not in body, 'waterfall patch fail'
pairs = dict(urllib.parse.parse_qsl(body))
pj = json.loads(pairs['params'])
assert pj['client_input_params']['contact_point'] == 'testuser_xyz'
assert pj['client_input_params']['password'].startswith('#PWD_INSTAGRAM:4:')
print('send_login patching OK; params keys:', len(pj['client_input_params']), len(pj['server_params']))

# 2) headers dynamic
assert re.match(r'\d{10}\.\d{3}$', hdrs['x-pigeon-rawclienttime'])
assert hdrs['x-fb-conn-uuid-client'] != L.TEMPLATES['send_login']['headers']['x-fb-conn-uuid-client']
assert hdrs['user-agent'] == L.TEMPLATES['send_login']['headers']['user-agent']
print('headers OK, UA:', hdrs['user-agent'][:40])

# 3) 2fa verify patching
m2, u2, h2, b2 = L.build_request('twostep_verify', 'testuser_xyz', code='123456', ctx='CTXTEST123')
p2 = dict(urllib.parse.parse_qsl(b2))
j2 = json.loads(p2['params'])
assert j2['client_input_params']['code'] == '123456'
assert j2['server_params']['two_step_verification_context'] == 'CTXTEST123'
print('2fa patching OK')

# 4) password encryption round trip shape
from Cryptodome.PublicKey import RSA
import base64
key = RSA.generate(2048)
enc = L.password_encrypt('dummypw', 12, base64.b64encode(key.publickey().export_key('DER')).decode())
assert enc.startswith('#PWD_INSTAGRAM:4:')
print('encryption OK, len:', len(enc))

# 5) credential extraction on sample escaped text
sample = r'...IG-Set-Authorization\": \"Bearer IGT:2:eyJkc191c2VyX2lkIjoiNDExIn0\"...Set-Cookie: sessionid=123%3AABC%3A1; Domain=.instagram.com...Set-Cookie: csrftoken=xyz123; Domain...'
c = L.extract_credentials(sample)
assert c['authorization'] and c['cookies'].get('sessionid') == '123:ABC:1' and c['cookies']['csrftoken'] == 'xyz123'
print('credential extraction OK:', c['cookies'])
print('ALL SELF-TESTS PASSED')
