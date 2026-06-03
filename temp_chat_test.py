import os
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

url = 'http://127.0.0.1:5000/api/chat'
data = json.dumps({'message': 'hello'}).encode('utf-8')
req = Request(url, data=data, headers={'Content-Type': 'application/json'})
try:
    with urlopen(req, timeout=30) as resp:
        body = resp.read().decode('utf-8')
        print('STATUS', resp.status)
        print('BODY', body)
except HTTPError as e:
    print('HTTP ERROR', e.code)
    print(e.read().decode('utf-8'))
except URLError as e:
    print('URL ERROR', e)
except Exception as e:
    print('EXCEPTION', type(e).__name__, e)
