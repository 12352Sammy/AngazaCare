import urllib.request

try:
    with urllib.request.urlopen('http://127.0.0.1:5000/') as r:
        print('STATUS', r.status)
        print(r.read(200).decode('utf-8'))
except Exception as exc:
    print('ERROR', exc)
