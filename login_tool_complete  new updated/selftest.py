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

# 6) diagnose regression — real 2026-10-22 capture (generic error dialog)
import os
_fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'generic_error_real.json')
if os.path.exists(_fx):
    _real = open(_fx, encoding='utf-8').read()
    assert L.diagnose_login_response(_real) == 'GENERIC_ERROR', 'real generic-error fixture misdiagnosed'
    print('real fixture diagnose OK: GENERIC_ERROR')
else:
    print('WARN: fixtures/generic_error_real.json missing — real-case regression skipped')
assert L.diagnose_login_response('{"a":"[trait:error_generic] error: generic error"}') == 'GENERIC_ERROR'
assert L.diagnose_login_response('{"a":"generic_error_dialog"}') == 'GENERIC_ERROR'
assert L.diagnose_login_response('{"data":[{"type":"gs","data":{"key":"CAA_LOGIN_FALLBACK:fallback_triggered","mode":"d","initial":true}}]}') == 'FALLBACK'
# initial:false + conditional action-tree mention = FALLBACK nahi (false-positive fix)
assert L.diagnose_login_response('{"data":[{"type":"gs","data":{"key":"CAA_LOGIN_FALLBACK:fallback_triggered","mode":"d","initial":false}}],"b":"(f6m 6 \\"fallback_triggered\\" true)"}') == 'UNKNOWN'
print('diagnose synthetic cases OK')
# 7) app-profile switch (449 = OLD identity)
L.apply_app_profile('449')
assert L.APP_VERSION == '449.0.0.52.84' and L.APP_CODE == '1079242191'
assert 'Instagram 449.0.0.52.84' in json.dumps(L.TEMPLATES), 'templates swap fail'
assert '451.0.0.53.80' not in json.dumps(L.TEMPLATES), '451 leftover in templates'
_m3, _u3, _h3, _b3 = L.build_request('send_login', 'testuser_xyz', enc_pwd='#PWD_INSTAGRAM:4:1234567890:TESTBLOB==')
assert 'Instagram 449.0.0.52.84' in _h3['user-agent'], 'UA not swapped in built request'
print('app-profile 449 switch OK (templates + UA + built request)')
# 8) USDID — instagrapi parity (generate/header/token/ES256 verify)
L.usdid_generate(force=True)
_h = L.usdid_header()
_parts = _h.split('.')
assert len(_parts) == 3 and _parts[0] == L._USDID['id'], 'usdid header format'
assert len(_parts[2]) > 60, 'signature missing'
_tok = L.usdid_registration_token('567067343352427')
import base64 as _b64
def _unb64u(x): return _b64.urlsafe_b64decode(x + '=' * (-len(x) % 4))
_tj = json.loads(_unb64u(_tok))
_pl = json.loads(_unb64u(_tj['payload']))
assert _pl['alg'] == 'ES256' and _pl['aud'] == '567067343352427' and _pl['sub'] == L._USDID['id']
from Cryptodome.Hash import SHA256 as _SHA
from Cryptodome.PublicKey import ECC as _ECC
from Cryptodome.Signature import DSS as _DSS
_sig = _unb64u(_tj['signatures'][0]['signature'])
_prot = _tj['signatures'][0]['protected']
_DSS.new(_ECC.import_key(L._USDID['key']).public_key(), 'fips-186-3', encoding='der').verify(
    _SHA.new(f'{_prot}.{_tj["payload"]}'.encode()), _sig)
print('USDID generate/header/token/ES256-verify OK')
# --- 9) FIX E: uTLS transport adapter (offline) ---
import requests as _rq
assert callable(L.create_curl_h2_adapter) and callable(L.mount_tls_transport)
assert L.mount_tls_transport(_rq.Session(), "requests") == "requests"
try:
    import curl_cffi as _cc  # noqa
    _have9 = True
except ImportError:
    _have9 = False
if _have9:
    assert L.mount_tls_transport(_rq.Session(), "curl") == "curl"
    print("[tls] curl_cffi adapter build+mount OK")
else:
    try:
        L.mount_tls_transport(_rq.Session(), "curl")
        raise SystemExit("curl mode bina curl_cffi ke exit karna chahiye")
    except SystemExit as _e9:
        assert _e9.code == 2
    print("[tls] curl_cffi absent — exit(2) path OK")
print("uTLS transport self-test OK")

# --- 10) FIX O: web-mid wiring (offline) ---
L._WEB_MID = "TESTMID0123456789abcdefgh"
L._SERVER_MID = ""
_m10, _u10, _h10, _b10 = L.build_request("mobileconfig", "testuser_o")
assert _h10.get("x-mid") == L._WEB_MID, f"x-mid header web-mid hona chahiye, mila: {_h10.get('x-mid')!r}"
assert "aomDBgABAAEprcPvkiF" not in json.dumps(_h10), "stale template mid header me nahi jana chahiye"
L._SERVER_MID = "SERVERMID999"
_m10, _u10, _h10, _b10 = L.build_request("mobileconfig", "testuser_o")
assert _h10.get("x-mid") == "SERVERMID999", "server-issued mid ko priority milni chahiye"
L._SERVER_MID = ""
L._WEB_MID = ""
assert callable(L.capture_web_mid)
import ig_login_perdevice as P10
assert callable(P10.capture_web_mid)
P10.apply_app_profile(None)
P10._GEO.update(P10.COUNTRY_PRESETS["IN"])
P10._PROFILE = P10.get_device_profile_for_user("testuser_o", P10._GEO["locale"])
P10._DEVICE = P10.make_device_fingerprint("testuser_o")
P10._DEVICE["x-mid"] = "PERDEVICEMID123"
_m10, _u10, _h10, _b10 = P10.build_request("mobileconfig", "testuser_o")
assert _h10.get("x-mid") == "PERDEVICEMID123"
assert "aomDBgABAAEprcPvkiF" not in json.dumps(_h10)
print("web-mid wiring self-test OK")

print('ALL SELF-TESTS PASSED')
