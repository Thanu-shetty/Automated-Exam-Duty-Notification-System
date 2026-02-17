import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import app
from models import db, Faculty

FAC_ID = 'FAC_TEST'
FAC_NAME = 'Test Faculty'
FAC_EMAIL = 'fac_test@example.com'
FAC_DEPT = 'CSE'
FAC_PASS = 'password123'

with app.app_context():
    existing = Faculty.query.filter_by(faculty_id=FAC_ID).first()
    if existing:
        existing.set_password(FAC_PASS)
        db.session.commit()
        print(f"Updated password for existing faculty {FAC_ID} -> {FAC_PASS}")
    else:
        f = Faculty(faculty_id=FAC_ID, name=FAC_NAME, email=FAC_EMAIL, department=FAC_DEPT)
        f.set_password(FAC_PASS)
        db.session.add(f)
        db.session.commit()
        print(f"Created test faculty {FAC_ID} with password {FAC_PASS}")
