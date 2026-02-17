import os
import sys

# Ensure project root is on sys.path so imports work even when path contains parentheses
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import app
from models import db, Faculty

with app.app_context():
    faculties = Faculty.query.all()
    print('Faculty count:', len(faculties))
    for f in faculties:
        print(f.id, f.faculty_id, f.name, f.email)

    if len(faculties) == 0:
        f = Faculty(faculty_id='FAC001', name='Test Faculty', email='test@example.com', department='CSE')
        f.set_password('password123')
        db.session.add(f)
        db.session.commit()
        print('Created test faculty: FAC001 / password123')
