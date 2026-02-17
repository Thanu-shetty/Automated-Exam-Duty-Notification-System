import os, sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import app
from models import Faculty

with app.app_context():
    f = Faculty.query.filter_by(faculty_id='FAC00').first()
    if not f:
        print('FAC00 not found, listing all faculties:')
        for x in Faculty.query.all():
            print(x.faculty_id, x.name)
    else:
        print('Found:', f.faculty_id, f.name, f.email)
        try:
            print('Password check for password123:', f.check_password('password123'))
        except Exception as e:
            print('Error running check_password:', e)
        # show stored hash attribute name
        print('Password hash field present:', hasattr(f, 'password_hash'))
        if hasattr(f, 'password_hash'):
            print('Stored hash (truncated):', f.password_hash[:30])
