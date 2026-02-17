from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class Admin(db.Model):
    __tablename__ = 'admin'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def is_active(self):
        return True
    
    @property
    def is_authenticated(self):
        return True
    
    @property
    def is_anonymous(self):
        return False
    
    def get_id(self):
        return str(self.id)

class Faculty(db.Model):
    __tablename__ = 'faculty'
    
    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    profile_image = db.Column(db.String(200), default='default.png')
    max_duties = db.Column(db.Integer, default=5)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def is_active(self):
        return True
    
    @property
    def is_authenticated(self):
        return True
    
    @property
    def is_anonymous(self):
        return False
    
    def get_id(self):
        return str(self.id)

class Exam(db.Model):
    __tablename__ = 'exam'
    
    id = db.Column(db.Integer, primary_key=True)
    subject_code = db.Column(db.String(50), nullable=False)
    subject_name = db.Column(db.String(100), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    exam_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    hall = db.Column(db.String(50), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ExamDuty(db.Model):
    __tablename__ = 'exam_duty'
    
    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)
    status = db.Column(db.String(20), default='Pending')
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    responded_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)
    
    faculty = db.relationship('Faculty', backref='duties')
    exam = db.relationship('Exam', backref='duties')

class Notification(db.Model):
    __tablename__ = 'notification'
    
    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notification_type = db.Column(db.String(50))
    duty_id = db.Column(db.Integer, db.ForeignKey('exam_duty.id'), nullable=True)
    
    faculty = db.relationship('Faculty', backref='notifications')
    admin = db.relationship('Admin', backref='notifications')
    duty = db.relationship('ExamDuty', backref='notification')

class DutySwap(db.Model):
    __tablename__ = 'duty_swap'
    
    id = db.Column(db.Integer, primary_key=True)
    requester_duty_id = db.Column(db.Integer, db.ForeignKey('exam_duty.id'), nullable=False)
    requester_faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=False)
    requested_faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=False)
    status = db.Column(db.String(20), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    responded_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    requester_duty = db.relationship('ExamDuty', foreign_keys=[requester_duty_id])
    requester_faculty = db.relationship('Faculty', foreign_keys=[requester_faculty_id])
    requested_faculty = db.relationship('Faculty', foreign_keys=[requested_faculty_id])

class ReminderSetting(db.Model):
    __tablename__ = 'reminder_setting'
    
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    reminder_before_exam = db.Column(db.String(100), default='1 day, 1 hour')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    admin = db.relationship('Admin', backref='reminder_settings')

class Timetable(db.Model):
    __tablename__ = 'timetable'
    
    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=False)
    day_of_week = db.Column(db.String(20), nullable=False)  # Monday, Tuesday, etc.
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    subject = db.Column(db.String(100), nullable=True)
    
    faculty = db.relationship('Faculty', backref='timetable_entries')