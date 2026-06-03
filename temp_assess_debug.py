import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
login_data = urllib.parse.urlencode({'email': 'demo@angazacare.com', 'password': 'password123'}).encode()
login_req = urllib.request.Request('http://127.0.0.1:5000/login', data=login_data)
response = opener.open(login_req)
print('LOGIN', response.getcode())
try:
    assessment = opener.open('http://127.0.0.1:5000/assessment')
    print('ASSESS', assessment.getcode())
    print(assessment.read(2000).decode('utf-8'))
except urllib.error.HTTPError as e:
    print('ERROR', e.code)
    print(e.read().decode('utf-8'))
