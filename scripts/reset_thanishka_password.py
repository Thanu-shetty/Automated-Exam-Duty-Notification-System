import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import app
from models import db, Faculty

TARGET_FACULTY_ID = 'FAC00'
TARGET_NAME_FRAGMENT = 'Thanishka'
NEW_PASSWORD = 'password123'

with app.app_context():
    faculty = Faculty.query.filter_by(faculty_id=TARGET_FACULTY_ID).first()
    if not faculty:
        faculty = Faculty.query.filter(Faculty.name.ilike(f"%{TARGET_NAME_FRAGMENT}%")).first()

    if not faculty:
        print('Thanishka not found in Faculty table. Here are all faculties:')
        for f in Faculty.query.all():
            print(f.id, f.faculty_id, f.name, f.email)
    else:
        faculty.set_password(NEW_PASSWORD)
        db.session.commit()
        print(f"Password for {faculty.name} (faculty_id={faculty.faculty_id}) has been set to: {NEW_PASSWORD}")
