import os, sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import app

with app.test_client() as client:
    resp = client.post('/faculty/login', data={'faculty_id':'FAC00','password':'password123'}, follow_redirects=True)
    print('POST /faculty/login ->', resp.status_code)
    body = resp.data.decode('utf-8')
    print('Response length:', len(body))
    print('Response starts with:')
    print(body[:800])
