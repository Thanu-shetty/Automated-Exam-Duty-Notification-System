from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_session import Session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from models import db, Admin, Faculty, Exam, ExamDuty, Notification, DutySwap, ReminderSetting, Timetable
from database import init_db
from notification_service import NotificationService
from config import Config
import pandas as pd
import os
from datetime import datetime, timedelta, date, time
import csv
import io
import logging
import sys
import traceback
import json
from sqlalchemy import text, func, or_, and_
from collections import defaultdict
from ai_service import AIAssignmentService

app = Flask(__name__)
app.config.from_object(Config)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)

# Initialize extensions
db.init_app(app)

# Ensure instance folder exists
instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
if not os.path.exists(instance_path):
    os.makedirs(instance_path)
    print(f"Created instance directory at {instance_path}")

# Database helper functions
def get_db():
    try:
        db.session.remove()
        db.session.begin()
        return True
    except Exception as e:
        print(f"Database connection error: {str(e)}")
        return False

# Initialize database connection
print("\n=== Initializing Database Connection ===")
with app.app_context():
    try:
        db.create_all()
        print("Database tables created successfully")

        if get_db():
            print("Successfully connected to database")
            from sqlalchemy import text
            result = db.session.execute(text('SELECT COUNT(*) FROM admin')).scalar()
            print(f"Found {result} admin accounts")    
        print("Database connection successful")
          
        # Create default admin if not exists
        admin = Admin.query.filter_by(username='admin').first()
        if not admin:
            admin = Admin(username='admin', email='admin@examduty.com')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("Default admin account created")
            
        # Create default reminder settings
        if not ReminderSetting.query.first():
            admin = Admin.query.filter_by(username='admin').first()
            if admin:
                default_settings = ReminderSetting(
                    admin_id=admin.id,
                    reminder_before_exam='1 day, 1 hour'
                )
                db.session.add(default_settings)
                db.session.commit()
                print("Default reminder settings created")
            
        print("Database initialization completed successfully")
        print("No test data created automatically")
        print("Only admin account is available")
        print("\nNEXT STEPS:")
        print("1. Login as admin (username: admin, password: admin123)")
        print("2. Upload faculty data using CSV in Admin Dashboard")
        print("3. Upload exam data using CSV")
        print("4. Assign duties to faculty")
        
    except Exception as e:
        print(f"Database initialization error: {str(e)}")
        print("Please ensure the database file exists and is writable")
        print(f"Database path: {app.config['SQLALCHEMY_DATABASE_URI']}")
        raise e

# Configure session handling
app.config['SESSION_FILE_DIR'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_session')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=5)
Session(app)

# Configure login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'danger'
login_manager.session_protection = "strong"

def handle_database_error(e, route_name=None):
    error_msg = str(e)
    print(f"\n=== Database Error ===")
    print(f"Error in route: {route_name}")
    print(f"Error message: {error_msg}")
    print(f"Error type: {type(e).__name__}")
    
    try:
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()
        print("Successfully cleaned up database session")
    except Exception as cleanup_error:
        print(f"Error during cleanup: {str(cleanup_error)}")
    
    if isinstance(e, db.exc.OperationalError):
        flash('Database is temporarily unavailable. Please try again in a moment.', 'danger')
    elif isinstance(e, db.exc.IntegrityError):
        flash('Data validation error. Please check your input.', 'danger')
    else:
        flash('A database error occurred. Please try again.', 'danger')
    
    return False

@app.before_request
def before_request():
    if request.endpoint == 'static':
        return
        
    try:
        if '_id' not in session:
            session['_id'] = os.urandom(16).hex()
    except Exception as e:
        print(f"Session error: {str(e)}")
        session.clear()
        session['_id'] = os.urandom(16).hex()
        
    if request.endpoint not in ['static']:
        try:
            with db.engine.connect() as conn:
                conn.execute(db.text('SELECT 1'))
                conn.commit()
        except Exception as e:
            print("\n=== Database Connection Error ===")
            print(f"Error details: {str(e)}")
            print(f"Current endpoint: {request.endpoint}")
            print(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
            handle_database_error(e, request.endpoint)

@app.errorhandler(Exception)
def handle_exception(e):
    if "SQLAlchemy" in str(type(e)):
        handle_database_error(e)
        return redirect(url_for('faculty_login'))
    raise e

notification_service = NotificationService(app)
ai_service = AIAssignmentService()

@login_manager.user_loader
def load_user(user_id):
    try:
        user_id = int(user_id)
        user_type = session.get('user_type')
        
        if user_type == 'admin':
            return db.session.get(Admin, user_id)
        elif user_type == 'faculty':
            return db.session.get(Faculty, user_id)
            
        # Fallback logic if user_type not in session
        # Try to load as admin first
        admin = db.session.get(Admin, user_id)
        if admin:
            return admin
        
        # If not admin, try to load as faculty
        faculty = db.session.get(Faculty, user_id)
        if faculty:
            return faculty
            
        return None
    except Exception as e:
        print(f"Error loading user: {str(e)}")
        return None

def is_admin_user():
    if not current_user.is_authenticated: 
        return False
    try:
        if session.get('user_type') == 'admin': 
            return True
        # Check if current_user is actually an Admin instance
        return isinstance(current_user._get_current_object() if hasattr(current_user, '_get_current_object') else current_user, Admin)
    except Exception as e:
        print(f"Error checking admin status: {str(e)}")
        return False

def is_faculty_user():
    if not current_user.is_authenticated: 
        return False
    try:
        # Check if current_user is actually a Faculty instance
        return isinstance(current_user._get_current_object() if hasattr(current_user, '_get_current_object') else current_user, Faculty)
    except Exception as e:
        print(f"Error checking faculty status: {str(e)}")
        return False

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    try:
        if current_user.is_authenticated and is_admin_user():
            return redirect(url_for('admin_dashboard'))
        
        if request.method == 'POST':
            if current_user.is_authenticated:
                logout_user()
            session.clear()

            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            
            if not username or not password:
                flash('Please enter both username and password', 'danger')
                return render_template('admin_login.html')
            
            admin = Admin.query.filter_by(username=username).first()
            if not admin:
                flash('Invalid username or password', 'danger')
                return render_template('admin_login.html')
            
            if admin.check_password(password):
                session['user_type'] = 'admin'
                session['admin_id'] = admin.id
                session.modified = True
                login_user(admin)
                flash('Login successful', 'success')
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Invalid username or password', 'danger')
                return render_template('admin_login.html')
    except Exception as e:
        print(f"Login error: {str(e)}")
        flash('An error occurred during login', 'danger')
    
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not is_admin_user():
        return redirect(url_for('admin_login'))
    
    try:
        total_faculty = Faculty.query.count()
        total_exams = Exam.query.count()
        pending_swaps = DutySwap.query.filter_by(status='Pending').count()
        
        # Get recent duties with proper joins
        recent_duties = ExamDuty.query\
            .join(Faculty, ExamDuty.faculty_id == Faculty.id)\
            .join(Exam, ExamDuty.exam_id == Exam.id)\
            .order_by(ExamDuty.assigned_at.desc())\
            .limit(5)\
            .all()
        
        # Get statistics for dashboard
        total_duties = ExamDuty.query.count()
        accepted_duties = ExamDuty.query.filter_by(status='Accepted').count()
        declined_duties = ExamDuty.query.filter_by(status='Declined').count()
        pending_duties = ExamDuty.query.filter_by(status='Pending').count()
        
        # Get recent notifications for admin
        try:
            recent_notifications = Notification.query.filter(
                (Notification.admin_id == current_user.id) | (Notification.admin_id.is_(None))
            ).order_by(Notification.created_at.desc()).limit(10).all()
        except Exception as e:
            print(f"Notification query error: {str(e)}")
            recent_notifications = []
        
        # Get recent swap requests
        recent_swaps = DutySwap.query\
            .join(Faculty, DutySwap.requester_faculty_id == Faculty.id)\
            .order_by(DutySwap.created_at.desc())\
            .limit(5)\
            .all()
        
        # Get upcoming exams (next 7 days)
        upcoming_exams = Exam.query.filter(
            Exam.exam_date >= date.today(),
            Exam.exam_date <= date.today() + timedelta(days=7)
        ).order_by(Exam.exam_date.asc()).limit(5).all()
        
        # Get system statistics
        system_stats = {
            'database_size': get_database_size(),
            'backup_count': len([f for f in os.listdir('backups') if f.endswith('.db')]) if os.path.exists('backups') else 0,
            'log_size': os.path.getsize('app.log') if os.path.exists('app.log') else 0
        }
        
        return render_template('admin_dashboard.html',
                             total_faculty=total_faculty,
                             total_exams=total_exams,
                             pending_swaps=pending_swaps,
                             recent_duties=recent_duties,
                             recent_notifications=recent_notifications,
                             recent_swaps=recent_swaps,
                             total_duties=total_duties,
                             accepted_duties=accepted_duties,
                             declined_duties=declined_duties,
                             pending_duties=pending_duties,
                             upcoming_exams=upcoming_exams,
                             system_stats=system_stats)
    except Exception as e:
        print(f"Error in admin_dashboard: {str(e)}")
        flash('An error occurred while loading the dashboard.', 'danger')
        return redirect(url_for('admin_login'))

def get_database_size():
    """Get the size of the database file"""
    try:
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        if os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
            # Convert to MB
            size_mb = size_bytes / (1024 * 1024)
            return f"{size_mb:.2f} MB"
    except:
        pass
    return "Unknown"

@app.route('/admin/duty-management')
@login_required
def duty_management():
    if not is_admin_user():
        return redirect(url_for('admin_login'))
        
    try:
        faculties = Faculty.query.all()
        exams = Exam.query.all()
        duties = ExamDuty.query.all()
        
        # Get duty statistics
        duty_stats = {
            'total': len(duties),
            'accepted': len([d for d in duties if d.status == 'Accepted']),
            'pending': len([d for d in duties if d.status == 'Pending']),
            'declined': len([d for d in duties if d.status == 'Declined'])
        }
        
        return render_template('duty_management.html',
                             faculties=faculties,
                             exams=exams,
                             duties=duties,
                             duty_stats=duty_stats)
    except Exception as e:
        print(f"Error in duty_management: {str(e)}")
        flash('An error occurred while loading duty management.', 'danger')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/upload-data', methods=['GET', 'POST'])
@login_required
def upload_data():
    if not is_admin_user():
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        file_type = request.form.get('file_type')
        if 'file' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)

        if file:
            try:
                if file.filename.endswith('.csv'):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)

                # Normalize column names
                df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]
                print(f"CSV Columns detected: {list(df.columns)}")

                if file_type == 'faculty':
                    # Required columns
                    required = ['faculty_id', 'name', 'email', 'department']
                    if not all(col in df.columns for col in required):
                         flash(f'Missing columns. Required: {", ".join(required)}', 'danger')
                         return redirect(request.url)

                    # Check if max_duties column exists
                    has_max_duties = 'max_duties' in df.columns
                    
                    count = 0
                    errors = []
                    skipped = 0
                    for idx, row in df.iterrows():
                        try:
                            # Check if faculty already exists by faculty_id
                            existing = Faculty.query.filter_by(faculty_id=str(row['faculty_id'])).first()
                            if existing:
                                # Update existing record
                                existing.name = row['name']
                                existing.email = row['email']
                                existing.department = row['department']
                                if has_max_duties:
                                    try:
                                        existing.max_duties = int(row['max_duties'])
                                    except (ValueError, KeyError):
                                        existing.max_duties = 5
                                count += 1
                                continue
                            
                            # Check if email already exists
                            if Faculty.query.filter_by(email=str(row['email'])).first():
                                errors.append(f"Row {idx+1}: Email '{row['email']}' already exists")
                                continue
                            
                            # Prepare faculty data
                            faculty_data = {
                                'faculty_id': str(row['faculty_id']),
                                'name': row['name'],
                                'email': row['email'],
                                'department': row['department']
                            }
                            
                            # Add max_duties if column exists, otherwise use default
                            if has_max_duties:
                                try:
                                    max_duties_val = int(row['max_duties'])
                                    faculty_data['max_duties'] = max_duties_val
                                except (ValueError, KeyError):
                                    faculty_data['max_duties'] = 5  # Default value
                                    errors.append(f"Row {idx+1}: Invalid max_duties value, using default 5")
                            else:
                                faculty_data['max_duties'] = 5  # Default value
                            
                            # Create faculty object
                            faculty = Faculty(**faculty_data)
                            faculty.set_password('default123')  # Default password
                            db.session.add(faculty)
                            count += 1
                            print(f"Added faculty: {row['faculty_id']} - {row['name']} - Max Duties: {faculty_data['max_duties']}")
                        except Exception as row_error:
                            errors.append(f"Row {idx+1}: {str(row_error)}")
                            skipped += 1
                            continue
                    
                    db.session.commit()
                    
                    if errors:
                        flash(f'Successfully processed {count} faculty members. Skipped: {skipped}. Errors: {len(errors)}', 'warning')
                        if len(errors) <= 5:
                            for err in errors:
                                flash(err, 'warning')
                    else:
                        flash(f'Successfully processed {count} faculty members', 'success')
                        
                    print(f"✅ Imported {count} faculty members from CSV")

                elif file_type == 'exams':
                    required = ['subject_code', 'subject_name', 'semester', 'exam_date', 'start_time', 'end_time', 'hall', 'department']
                    if not all(col in df.columns for col in required):
                        flash(f'Missing columns. Required: {", ".join(required)}', 'danger')
                        return redirect(request.url)
                    
                    count = 0
                    errors = []
                    skipped = 0
                    for idx, row in df.iterrows():
                        try:
                            # Parse exam date
                            try:
                                e_date = pd.to_datetime(row['exam_date']).date()
                            except:
                                e_date = datetime.strptime(str(row['exam_date']), '%Y-%m-%d').date()
                            
                            # Parse start time
                            s_time_val = row['start_time']
                            if isinstance(s_time_val, str):
                                try:
                                    s_time = datetime.strptime(s_time_val, '%H:%M:%S').time()
                                except:
                                    s_time = datetime.strptime(s_time_val, '%H:%M').time()
                            else:
                                s_time = pd.to_datetime(s_time_val).time()
                                
                            # Parse end time
                            e_time_val = row['end_time']
                            if isinstance(e_time_val, str):
                               try:
                                    e_time = datetime.strptime(e_time_val, '%H:%M:%S').time()
                               except:
                                    e_time = datetime.strptime(e_time_val, '%H:%M').time()
                            else:
                                e_time = pd.to_datetime(e_time_val).time()
                            
                            # Check if exam already exists
                            existing = Exam.query.filter_by(
                                subject_code=str(row['subject_code']),
                                exam_date=e_date,
                                hall=str(row['hall'])
                            ).first()
                            
                            if existing:
                                # Update existing exam
                                existing.subject_name = row['subject_name']
                                existing.semester = int(row['semester'])
                                existing.start_time = s_time
                                existing.end_time = e_time
                                existing.department = row['department']
                                count += 1
                                continue
                            
                            exam = Exam(
                                subject_code=str(row['subject_code']),
                                subject_name=row['subject_name'],
                                semester=int(row['semester']),
                                exam_date=e_date,
                                start_time=s_time,
                                end_time=e_time,
                                hall=str(row['hall']),
                                department=row['department']
                            )
                            db.session.add(exam)
                            count += 1
                            print(f"Added exam: {row['subject_code']} - {row['subject_name']}")
                        except Exception as e:
                            errors.append(f"Row {idx+1}: {str(e)}")
                            skipped += 1
                            continue

                    db.session.commit()
                    
                    if errors:
                        flash(f'Successfully processed {count} exams. Skipped: {skipped}. Errors: {len(errors)}', 'warning')
                    else:
                        flash(f'Successfully processed {count} exams', 'success')
                    
                    print(f"✅ Imported {count} exams from CSV")

                elif file_type == 'timetable':
                    required = ['faculty_id', 'day_of_week', 'start_time', 'end_time']
                    if not all(col in df.columns for col in required):
                        flash(f'Missing columns. Required: {", ".join(required)}', 'danger')
                        return redirect(request.url)
                    
                    count = 0
                    errors = []
                    skipped = 0
                    
                    for idx, row in df.iterrows():
                        try:
                            # Verify faculty exists
                            faculty = Faculty.query.filter_by(faculty_id=str(row['faculty_id'])).first()
                            if not faculty:
                                errors.append(f"Row {idx+1}: Faculty {row['faculty_id']} not found")
                                skipped += 1
                                continue
                            
                            # Parse start time
                            s_time_val = row['start_time']
                            if isinstance(s_time_val, str):
                                try:
                                    s_time = datetime.strptime(s_time_val, '%H:%M:%S').time()
                                except:
                                    s_time = datetime.strptime(s_time_val, '%H:%M').time()
                            else:
                                s_time = pd.to_datetime(s_time_val).time()
                                
                            # Parse end time
                            e_time_val = row['end_time']
                            if isinstance(e_time_val, str):
                               try:
                                    e_time = datetime.strptime(e_time_val, '%H:%M:%S').time()
                               except:
                                    e_time = datetime.strptime(e_time_val, '%H:%M').time()
                            else:
                                e_time = pd.to_datetime(e_time_val).time()

                            # Normalize day
                            day = str(row['day_of_week']).strip().capitalize()
                            subject = str(row['subject']) if 'subject' in df.columns else None
                            
                            # Skip if subject indicates free time
                            if subject and any(x in subject.lower() for x in ['free', 'lunch', 'break']):
                                skipped += 1
                                continue
                            
                            entry = Timetable(
                                faculty_id=faculty.id,
                                day_of_week=day,
                                start_time=s_time,
                                end_time=e_time,
                                subject=subject
                            )
                            db.session.add(entry)
                            count += 1
                        except Exception as e:
                            errors.append(f"Row {idx+1}: {str(e)}")
                            skipped += 1
                            continue
                            
                    db.session.commit()
                    
                    if errors:
                        flash(f'Processed {count} entries. Errors: {len(errors)}', 'warning')
                    else:
                        flash(f'Successfully imported {count} timetable entries', 'success')
                        
                    print(f"✅ Imported {count} timetable entries")
            
            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'danger')
                print(f"❌ File processing error: {str(e)}")
                
    faculties = Faculty.query.all()
    exams = Exam.query.all()
    return render_template('upload_data.html', faculties=faculties, exams=exams)

@app.route('/admin/recent-duties')
@login_required
def get_recent_duties():
    if not is_admin_user():
         return jsonify({'error': 'Unauthorized'}), 401
    duties = ExamDuty.query.order_by(ExamDuty.assigned_at.desc()).limit(10).all()
    return jsonify([{
        'faculty': d.faculty.name,
        'date': str(d.exam.exam_date),
        'exam': d.exam.subject_name,
        'hall': d.exam.hall,
        'status': d.status
    } for d in duties])

@app.route('/admin/declined-duties')
@login_required
def get_declined_duties():
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        duties = ExamDuty.query.filter_by(status='Declined').order_by(ExamDuty.updated_at.desc()).limit(10).all()
        return jsonify([{
            'faculty': d.faculty.name,
            'exam': d.exam.subject_name,
            'date': str(d.exam.exam_date),
            'reason_type': 'Other', 
            'details': d.notes or 'No details provided'
        } for d in duties])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/delete-exam/<int:id>', methods=['POST'])
@login_required
def delete_exam(id):
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        exam = Exam.query.get(id)
        if not exam:
            return jsonify({'error': 'Exam not found'}), 404
        
        # Check if there are any duties assigned to this exam
        duties_count = ExamDuty.query.filter_by(exam_id=id).count()
        if duties_count > 0:
            return jsonify({
                'error': f'Cannot delete exam. There are {duties_count} duties assigned to this exam. Remove duties first.'
            }), 400
        
        db.session.delete(exam)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Exam deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/assign-duty', methods=['POST'])
@login_required
def assign_duty():
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    faculty_id = request.form['faculty_id']
    exam_id = request.form['exam_id']
    
    existing_duty = ExamDuty.query.filter_by(faculty_id=faculty_id, exam_id=exam_id).first()
    if existing_duty:
        return jsonify({'error': 'Duty already assigned'}), 400
    
    try:
        duty = ExamDuty(faculty_id=faculty_id, exam_id=exam_id)
        db.session.add(duty)
        db.session.commit()
        
        notification_sent = notification_service.send_duty_assignment_notification(faculty_id, duty.id)
        
        if notification_sent:
            return jsonify({'success': 'Duty assigned successfully and notification sent!'})
        else:
            return jsonify({'success': 'Duty assigned successfully but notification failed!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@app.route('/admin/delete-duty/<int:duty_id>', methods=['POST'])
@login_required
def delete_duty(duty_id):
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        duty = ExamDuty.query.get(duty_id)
        if not duty:
            return jsonify({'error': 'Duty not found'}), 404
        
        # Check if there are any swap requests for this duty
        swap_requests = DutySwap.query.filter_by(requester_duty_id=duty_id).all()
        if swap_requests:
            for swap in swap_requests:
                db.session.delete(swap)
        
        db.session.delete(duty)
        db.session.commit()
        return jsonify({'success': 'Duty deleted successfully'})
    except Exception as e:
        db.session.rollback()
        error_msg = f'Failed to delete duty: {str(e)}'
        if 'foreign key constraint' in str(e).lower():
            error_msg += '. There are related records that prevent deletion.'
        return jsonify({'error': error_msg}), 500

@app.route('/admin/delete-faculty/<int:id>', methods=['POST'])
@login_required
def delete_faculty(id):
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        faculty = Faculty.query.get(id)
        if faculty:
            # Check if faculty has any duties
            duties_count = ExamDuty.query.filter_by(faculty_id=id).count()
            if duties_count > 0:
                return jsonify({
                    'error': f'Cannot delete faculty. There are {duties_count} duties assigned to this faculty. Remove duties first.'
                }), 400
            
            # Delete related records
            DutySwap.query.filter(
                or_(DutySwap.requester_faculty_id == id, DutySwap.requested_faculty_id == id)
            ).delete()
            
            Notification.query.filter_by(faculty_id=id).delete()
            # Also delete timetable entries
            try:
                Timetable.query.filter_by(faculty_id=id).delete()
            except Exception as e:
                print(f"Error deleting timetable: {str(e)}")
            
            db.session.delete(faculty)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Faculty deleted successfully'})
        return jsonify({'error': 'Faculty not found'}), 404
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/admin/reminder-settings', methods=['POST'])
@login_required
def update_reminder_settings():
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    reminders = request.form['reminders']
    
    setting = ReminderSetting.query.filter_by(admin_id=current_user.id).first()
    if not setting:
        setting = ReminderSetting(admin_id=current_user.id, reminder_before_exam=reminders)
        db.session.add(setting)
    else:
        setting.reminder_before_exam = reminders
        setting.updated_at = datetime.utcnow()
    
    db.session.commit()
    return jsonify({'success': 'Reminder settings updated'})

@app.route('/admin/bulk-assign', methods=['GET', 'POST'])
@login_required
def bulk_assign_duties():
    if not is_admin_user():
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        try:
            data = request.get_json()
            assignments = data.get('assignments', [])
            
            success_count = 0
            failed_count = 0
            created_duties = []
            errors = []
            
            for assignment in assignments:
                faculty_id = assignment.get('faculty_id')
                exam_id = assignment.get('exam_id')
                
                if not faculty_id or not exam_id: 
                    failed_count += 1
                    errors.append(f"Missing faculty_id or exam_id")
                    continue
                
                existing = ExamDuty.query.filter_by(faculty_id=faculty_id, exam_id=exam_id).first()
                if existing: 
                    failed_count += 1
                    errors.append(f"Duty already exists for faculty {faculty_id} and exam {exam_id}")
                    continue
                
                duty = ExamDuty(faculty_id=faculty_id, exam_id=exam_id)
                db.session.add(duty)
                success_count += 1
                created_duties.append(duty)
            
            db.session.commit()
            
            # Send notifications for successful assignments
            for duty in created_duties:
                try:
                    notification_service.send_duty_assignment_notification(duty.faculty_id, duty.id)
                except Exception as e:
                    print(f"Notification failed for duty: {e}")
            
            return jsonify({
                'success': True, 
                'message': f'Successfully assigned {success_count} duties. Failed: {failed_count}',
                'success_count': success_count,
                'failed_count': failed_count,
                'errors': errors[:10]  # Limit errors to first 10
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    departments = db.session.query(Faculty.department).distinct().all()
    departments = [dept[0] for dept in departments]
    return render_template('bulk_assignment.html', departments=departments)

@app.route('/admin/get-faculty-by-department/<department>')
@login_required
def get_faculty_by_department(department):
    faculties = Faculty.query.filter_by(department=department).all()
    faculty_list = []
    
    for faculty in faculties:
        duty_count = ExamDuty.query.filter_by(faculty_id=faculty.id).count()
        max_duties = faculty.max_duties if hasattr(faculty, 'max_duties') else 5
        faculty_list.append({
            'id': faculty.id,
            'faculty_id': faculty.faculty_id,
            'name': faculty.name,
            'email': faculty.email,
            'department': faculty.department,
            'current_duties': duty_count,
            'max_duties': max_duties,
            'available_slots': max_duties - duty_count
        })
    return jsonify(faculty_list)

@app.route('/admin/get-exams-by-filters')
@login_required
def get_exams_by_filters():
    department = request.args.get('department')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = Exam.query
    if department and department != 'all':
        query = query.filter_by(department=department)
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(Exam.exam_date >= date_from_obj)
        except ValueError: 
            pass
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(Exam.exam_date <= date_to_obj)
        except ValueError: 
            pass
            
    exams = query.order_by(Exam.exam_date.asc()).all()
    exam_list = []
    for exam in exams:
        # Check if exam already has duties assigned
        duty_count = ExamDuty.query.filter_by(exam_id=exam.id).count()
        exam_list.append({
            'id': exam.id,
            'subject_code': exam.subject_code,
            'subject_name': exam.subject_name,
            'exam_date': str(exam.exam_date),
            'start_time': str(exam.start_time),
            'end_time': str(exam.end_time),
            'hall': exam.hall,
            'department': exam.department,
            'duty_count': duty_count,
            'is_available': duty_count == 0
        })
    return jsonify(exam_list)

@app.route('/admin/auto-assign-duties', methods=['POST'])
@login_required
def auto_assign_duties():
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        print("\n=== STARTING AI AUTO-ALLOCATION ===")
        data = request.get_json()
        department = data.get('department')
            
        # Fetch data for AI Service
        if department and department != 'all':
            faculties = Faculty.query.filter_by(department=department).all()
            exams = Exam.query.filter_by(department=department).all()
        else:
            faculties = Faculty.query.all()
            exams = Exam.query.all()
            
        # Filter for unassigned exams only
        unassigned_exams = [e for e in exams if not ExamDuty.query.filter_by(exam_id=e.id).first()]
        
        if not unassigned_exams:
             return jsonify({'success': True, 'message': 'No unassigned exams found.', 'assignments_made': 0})

        # Use AI Service
        assignments_data, insights = ai_service.auto_assign_duties(faculties, unassigned_exams)
        
        print(f"AI Service generated {len(assignments_data)} assignments")
        
        count = 0
        success_notifications = 0
        
        for item in assignments_data:
            faculty = item['faculty']
            exam = item['exam']
            score = item['score']
            
            # Double check existence
            exists = ExamDuty.query.filter_by(exam_id=exam.id).first()
            if exists:
                continue
                
            # Create new duty
            new_duty = ExamDuty(
                faculty_id=faculty.id,
                exam_id=exam.id,
                status='Pending',
                notes=f"AI Score: {score:.2f}. Assigned via AI Service."
            )
            
            db.session.add(new_duty)
        
        # Commit all assignments first
        db.session.commit()
        print(f"Successfully committed assignments to database")
        
        # Now send notifications and prepare admin report
        assignment_details = []
        
        # We need to re-fetch the duties to ensure we have the IDs and proper relationships
        # Or better, just iterate through what we assigned if we can track it.
        # But 'assignments_data' has faculty and exam objects.
        # Let's iterate assignments_data again and look up the duty.
        
        for item in assignments_data:
            faculty = item['faculty']
            exam = item['exam']
            score = item['score']
            
            # Find the duty we just created
            duty = ExamDuty.query.filter_by(faculty_id=faculty.id, exam_id=exam.id).first()
            if not duty:
                continue
                
            count += 1
            
            # Track for admin report
            assignment_details.append({
                'faculty_name': faculty.name,
                'faculty_email': faculty.email,
                'exam_name': exam.subject_name,
                'exam_date': str(exam.exam_date),
                'hall': exam.hall
            })
            
            # Send notification
            try:
                if notification_service.send_duty_assignment_notification(duty.faculty_id, duty.id):
                    success_notifications += 1
            except Exception as ne:
                print(f"Notification error for duty {duty.id}: {ne}")

        # Send admin report
        try:
            admin_email = current_user.email
            # Check if admin email is the default fake one or invalid
            if not admin_email or admin_email == 'admin@examduty.com' or '@' not in admin_email:
                print(f"[INFO] Using configured mail username for admin report instead of {admin_email}")
                admin_email = Config.MAIL_USERNAME
                
            if admin_email:
                notification_service.send_admin_auto_allocation_report(admin_email, count, assignment_details)
        except Exception as ae:
            print(f"Admin report error: {ae}")
            
        print(f"Successfully processed {count} assignments")
        
        return jsonify({
            'success': True, 
            'message': f'AI successfully assigned {count} duties.', 
            'assignments_made': count,
            'notifications_sent': success_notifications
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Auto-assign error: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)})


# Rule-based algorithm for intelligent duty assignment
@app.route('/admin/rule-based-assign-duties', methods=['POST'])
@login_required
def rule_based_assign_duties():
    """Rule-based intelligent duty assignment algorithm"""
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        print("\n=== STARTING RULE-BASED AUTO-ALLOCATION ===")
        data = request.get_json()
        department = data.get('department')
        
        # Configuration parameters
        config = {
            'max_duties_default': int(data.get('max_duties', 5)),
            'prefer_same_department': data.get('prefer_same_department', True),
            'balance_workload': data.get('balance_workload', True),
            'consider_time_conflicts': data.get('consider_time_conflicts', True),
            'avoid_consecutive_days': data.get('avoid_consecutive_days', True),
            'prefer_experienced_faculty': data.get('prefer_experienced_faculty', False),
            'max_duties_per_day': int(data.get('max_duties_per_day', 2)),
            'min_break_between_duties': timedelta(hours=2)  # Minimum 2 hours between duties
        }
        
        print(f"Rule-based configuration: {config}")
        
        # Get unassigned exams
        query = Exam.query.outerjoin(ExamDuty, Exam.id == ExamDuty.exam_id).filter(ExamDuty.id.is_(None))
        if department and department != 'all':
            query = query.filter(Exam.department == department)
        unassigned_exams = query.order_by(Exam.exam_date.asc(), Exam.start_time.asc()).all()
        
        print(f"Found {len(unassigned_exams)} unassigned exams")
        
        if not unassigned_exams:
            return jsonify({'success': True, 'message': 'No unassigned exams found.', 'assignments_made': 0})

        # Get available faculty
        faculty_query = Faculty.query
        if department and department != 'all':
            faculty_query = faculty_query.filter_by(department=department)
        all_faculty = faculty_query.all()
        
        print(f"Found {len(all_faculty)} faculty members")
        
        if not all_faculty:
            return jsonify({'success': False, 'error': 'No faculty found to assign duties to.'})

        # Step 1: Pre-process faculty data with enhanced metrics
        faculty_data = []
        for faculty in all_faculty:
            # Get all duties (accepted, pending, and declined)
            duties = ExamDuty.query.filter_by(faculty_id=faculty.id).all()
            accepted_duties = [d for d in duties if d.status == 'Accepted']
            
            # Calculate various metrics
            max_allowed = faculty.max_duties if hasattr(faculty, 'max_duties') and faculty.max_duties else config['max_duties_default']
            
            # Calculate duty distribution by date
            duty_by_date = defaultdict(list)
            for duty in accepted_duties:
                if duty.exam:
                    duty_by_date[duty.exam.exam_date].append(duty)
            
            # Check for consecutive days
            consecutive_days = False
            if len(accepted_duties) >= 2:
                sorted_dates = sorted(duty_by_date.keys())
                for i in range(len(sorted_dates) - 1):
                    if (sorted_dates[i+1] - sorted_dates[i]).days == 1:
                        consecutive_days = True
                        break
            
            # Calculate average duties per day
            avg_duties_per_day = len(accepted_duties) / max(len(duty_by_date), 1)
            
            faculty_data.append({
                'faculty': faculty,
                'duty_count': len(accepted_duties),
                'total_duty_count': len(duties),  # Includes all statuses
                'max_allowed': max_allowed,
                'available_slots': max_allowed - len(accepted_duties),
                'duty_by_date': duty_by_date,
                'consecutive_days': consecutive_days,
                'avg_duties_per_day': avg_duties_per_day,
                'department': faculty.department,
                'score': 0,  # Will be calculated based on rules
                'preferred_dates': [],  # Can be extended to include faculty preferences
                'unavailable_dates': [],  # Can be extended to include faculty unavailability
                'time_preferences': {}  # Can be extended to include time preferences
            })
        
        # Step 2: Rule-based scoring system
        def calculate_faculty_score(faculty_info, exam, existing_assignments_today):
            """Calculate score for a faculty member for a specific exam based on rules"""
            score = 100  # Base score
            
            # Rule 1: Workload balancing (higher score for less loaded faculty)
            workload_penalty = faculty_info['duty_count'] * 10
            score -= workload_penalty
            
            # Rule 2: Department matching (if enabled)
            if config['prefer_same_department'] and faculty_info['department'] == exam.department:
                score += 20
            
            # Rule 3: Avoid consecutive days (if enabled)
            if config['avoid_consecutive_days'] and faculty_info['consecutive_days']:
                score -= 15
            
            # Rule 4: Avoid too many duties on same day
            duties_today = len(faculty_info['duty_by_date'].get(exam.exam_date, [])) + existing_assignments_today
            if duties_today >= config['max_duties_per_day']:
                score -= 50  # Strong penalty
            
            # Rule 5: Check for time conflicts
            if config['consider_time_conflicts']:
                for duty in faculty_info['duty_by_date'].get(exam.exam_date, []):
                    if duty.exam:
                        # Check if exams overlap
                        existing_start = datetime.combine(duty.exam.exam_date, duty.exam.start_time)
                        existing_end = datetime.combine(duty.exam.exam_date, duty.exam.end_time)
                        new_start = datetime.combine(exam.exam_date, exam.start_time)
                        new_end = datetime.combine(exam.exam_date, exam.end_time)
                        
                        if not (new_end <= existing_start or new_start >= existing_end):
                            score -= 100  # Strong penalty for time conflicts
                        
                        # Check minimum break between duties
                        time_between = abs((new_start - existing_end).total_seconds() / 3600)
                        if 0 < time_between < config['min_break_between_duties'].total_seconds() / 3600:
                            score -= 30

            # Rule 5.5: Check for Timetable conflicts (Regular Classes)
            if config['consider_time_conflicts']:
                day_name = exam.exam_date.strftime('%A')
                timetable_conflicts = Timetable.query.filter_by(
                    faculty_id=faculty_info['faculty'].id,
                    day_of_week=day_name
                ).filter(
                    ((Timetable.start_time <= exam.start_time) & (Timetable.end_time > exam.start_time)) |
                    ((Timetable.start_time < exam.end_time) & (Timetable.end_time >= exam.end_time)) |
                    ((Timetable.start_time >= exam.start_time) & (Timetable.end_time <= exam.end_time))
                ).count()
                
                if timetable_conflicts > 0:
                     score = -1000 # Strong penalty for class conflict
            
            # Rule 6: Prefer experienced faculty (if enabled)
            if config['prefer_experienced_faculty']:
                # Higher score for faculty with more accepted duties (experience)
                experience_bonus = min(faculty_info['duty_count'] * 2, 20)
                score += experience_bonus
            
            # Rule 7: Penalize faculty who frequently decline duties
            decline_ratio = (faculty_info['total_duty_count'] - faculty_info['duty_count']) / max(faculty_info['total_duty_count'], 1)
            if decline_ratio > 0.5:  # If more than 50% duties declined
                score -= 25
            
            # Rule 8: Ensure faculty doesn't exceed max duties
            if faculty_info['duty_count'] >= faculty_info['max_allowed']:
                score = -1000  # Disqualify
            
            return max(score, 0)  # Ensure non-negative score
        
        # Step 3: Enhanced assignment algorithm
        assignments_made = 0
        assignment_details = []
        failed_assignments = []
        
        # Track assignments made in this batch
        current_assignments = defaultdict(lambda: defaultdict(int))  # faculty_id -> date -> count
        
        # Sort exams by priority (date, then department complexity)
        for exam in unassigned_exams:
            print(f"\nProcessing exam: {exam.subject_name} on {exam.exam_date}")
            
            # Find suitable faculty for this exam
            suitable_faculty = []
            
            for faculty_info in faculty_data:
                # Quick filter: must have available slots
                if faculty_info['available_slots'] <= 0:
                    continue
                
                # Calculate score for this faculty for this exam
                existing_today = current_assignments[faculty_info['faculty'].id].get(exam.exam_date, 0)
                score = calculate_faculty_score(faculty_info, exam, existing_today)
                
                if score > 0:  # Only consider faculty with positive score
                    suitable_faculty.append({
                        'faculty_info': faculty_info,
                        'score': score,
                        'existing_today': existing_today
                    })
            
            if not suitable_faculty:
                print(f"  No suitable faculty found for {exam.subject_name}")
                failed_assignments.append({
                    'exam': exam.subject_name,
                    'date': str(exam.exam_date),
                    'reason': 'No suitable faculty available'
                })
                continue
            
            # Sort by score (descending)
            suitable_faculty.sort(key=lambda x: x['score'], reverse=True)
            
            # Select the best faculty
            selected = suitable_faculty[0]
            faculty_info = selected['faculty_info']
            faculty = faculty_info['faculty']
            
            print(f"  Selected faculty: {faculty.name} (Score: {selected['score']})")
            
            # Create duty assignment
            duty = ExamDuty(faculty_id=faculty.id, exam_id=exam.id)
            db.session.add(duty)
            
            # Update tracking
            faculty_info['duty_count'] += 1
            faculty_info['available_slots'] -= 1
            current_assignments[faculty.id][exam.exam_date] += 1
            
            assignments_made += 1
            
            # Record assignment details
            assignment_details.append({
                'faculty_name': faculty.name,
                'faculty_email': faculty.email,
                'faculty_department': faculty.department,
                'exam_name': exam.subject_name,
                'exam_code': exam.subject_code,
                'exam_date': str(exam.exam_date),
                'exam_time': f"{exam.start_time} - {exam.end_time}",
                'hall': exam.hall,
                'department': exam.department,
                'duty_id': duty.id,
                'assignment_score': selected['score'],
                'faculty_current_duties': faculty_info['duty_count'],
                'faculty_max_duties': faculty_info['max_allowed']
            })
        
        # Commit all assignments
        db.session.commit()
        print(f"\nSuccessfully committed {assignments_made} rule-based assignments")
        
        # Step 4: Send notifications and reports
        # Send notifications for each created duty
        for detail in assignment_details:
            try:
                print(f"Sending notification to {detail['faculty_email']}...")
                # Find faculty by email
                faculty = Faculty.query.filter_by(email=detail['faculty_email']).first()
                if faculty:
                    notification_sent = notification_service.send_duty_assignment_direct(
                        faculty.id,
                        {
                            'exam_name': detail['exam_name'],
                            'subject_code': detail['exam_code'],
                            'exam_date': detail['exam_date'],
                            'start_time': detail['exam_time'].split(' - ')[0],
                            'end_time': detail['exam_time'].split(' - ')[1],
                            'hall': detail['hall'],
                            'department': detail['department']
                        }
                    )
                    if notification_sent:
                        print(f"✓ Notification sent to {detail['faculty_email']}")
                    else:
                        print(f"✗ Notification failed for {detail['faculty_email']}")
            except Exception as email_error:
                print(f"Email error (non-critical): {email_error}")
        
        # Send admin report
        if assignments_made > 0:
            try:
                admin = Admin.query.get(current_user.id)
                if admin and admin.email:
                    print(f"Sending admin report to {admin.email}")
                    
                    # Prepare statistics for report
                    stats = {
                        'total_assignments': assignments_made,
                        'failed_assignments': len(failed_assignments),
                        'average_score': sum(d['assignment_score'] for d in assignment_details) / assignments_made if assignments_made > 0 else 0,
                        'department_distribution': defaultdict(int),
                        'workload_distribution': defaultdict(int)
                    }
                    
                    for detail in assignment_details:
                        stats['department_distribution'][detail['faculty_department']] += 1
                        workload_key = f"{detail['faculty_current_duties']}/{detail['faculty_max_duties']}"
                        stats['workload_distribution'][workload_key] += 1
                    
                    # Send report using existing notification service
                    subject = f"📊 Rule-Based Duty Allocation Report: {assignments_made} Assignments"
                    
                    # Prepare report body
                    body = f"""
                    **RULE-BASED DUTY ALLOCATION REPORT**
                    
                    **Summary:**
                    - Total Assignments Made: {assignments_made}
                    - Failed Assignments: {len(failed_assignments)}
                    - Average Assignment Score: {stats.get('average_score', 0):.2f}
                    
                    **Statistics:**
                    - Department Distribution: {dict(stats.get('department_distribution', {}))}
                    - Workload Distribution: {dict(stats.get('workload_distribution', {}))}
                    
                    **Detailed Assignments ({len(assignment_details)}):**
                    """
                    
                    for i, detail in enumerate(assignment_details[:20], 1):  # Limit to first 20
                        body += f"""
                        {i}. **Faculty:** {detail['faculty_name']} ({detail['faculty_department']})
                           **Exam:** {detail['exam_name']} ({detail['exam_code']})
                           **Date/Time:** {detail['exam_date']} at {detail['exam_time']}
                           **Hall:** {detail['hall']}
                           **Score:** {detail['assignment_score']:.2f}
                           **Workload:** {detail['faculty_current_duties']}/{detail['faculty_max_duties']}
                        """
                    
                    if len(assignment_details) > 20:
                        body += f"\n... and {len(assignment_details) - 20} more assignments\n"
                    
                    if failed_assignments:
                        body += f"""
                        **Failed Assignments ({len(failed_assignments)}):**
                        """
                        for i, failed in enumerate(failed_assignments[:10], 1):  # Limit to first 10
                            body += f"""
                            {i}. **Exam:** {failed['exam']}
                               **Date:** {failed['date']}
                               **Reason:** {failed['reason']}
                            """
                    
                    body += """
                    
                    **Recommendations:**
                    1. Review workload distribution for fairness
                    2. Check for time conflicts
                    3. Consider faculty preferences if available
                    
                    ---
                    This is an automated report from the Exam Duty System.
                    """
                    
                    notification_service.send_email(admin.email, subject, body)
            except Exception as admin_email_error:
                print(f"Admin report error (non-critical): {admin_email_error}")
        
        # Step 5: Return results
        print(f"\n=== RULE-BASED ALLOCATION COMPLETE ===")
        print(f"Total assignments made: {assignments_made}")
        print(f"Failed assignments: {len(failed_assignments)}")
        
        return jsonify({
            'success': True, 
            'message': f'Rule-based assignment completed. Assigned {assignments_made} duties.',
            'assignments_made': assignments_made,
            'failed_assignments': len(failed_assignments),
            'details': assignment_details,
            'failed_details': failed_assignments,
            'statistics': {
                'average_score': sum(d['assignment_score'] for d in assignment_details) / assignments_made if assignments_made > 0 else 0,
                'department_coverage': len(set(d['faculty_department'] for d in assignment_details))
            }
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"\n=== RULE-BASED ALLOCATION FAILED: {str(e)} ===")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Rule-based allocation failed: {str(e)}'})

@app.route('/admin/send-test-email', methods=['POST'])
@login_required
def send_test_email():
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        admin_email = current_user.email
        if not admin_email:
            return jsonify({'error': 'Admin email not found'}), 400

        subject = "Test Email from Exam Duty System"
        body = "This is a test email to verify the email sending functionality."
        notification_service.send_email(admin_email, subject, body)
        return jsonify({'success': True, 'message': 'Test email sent successfully.'})
    except Exception as e:
        print(f"Error sending test email: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

# Faculty Routes - FIXED VERSION
@app.route('/faculty/login', methods=['GET', 'POST'])
def faculty_login():
    """Faculty login page - FIXED VERSION"""
    # Check if already logged in as faculty
    if current_user.is_authenticated and is_faculty_user():
        return redirect(url_for('faculty_dashboard'))
    
    try:
        if request.method == 'POST':
            # Only clear session on POST request when user is trying to login
            if current_user.is_authenticated:
                logout_user()
            session.clear()

            faculty_id = request.form.get('faculty_id', '').strip()
            password = request.form.get('password', '').strip()
            
            if not faculty_id or not password:
                flash('Please enter both faculty ID and password', 'danger')
                return render_template('faculty_login.html')

            faculty = Faculty.query.filter_by(faculty_id=faculty_id).first()
            if faculty and faculty.check_password(password):
                # Set session variables
                session['user_type'] = 'faculty'
                session['faculty_id'] = faculty.id
                session['faculty_email'] = faculty.email
                session.modified = True
                
                # Log in the user
                login_user(faculty, remember=False)
                flash('Login successful!', 'success')
                return redirect(url_for('faculty_dashboard'))
            else:
                flash('Invalid faculty ID or password', 'danger')
                return render_template('faculty_login.html')
        
        # GET request - show login form
        return render_template('faculty_login.html')
        
    except Exception as e:
        print(f"Faculty login error: {str(e)}")
        flash('An error occurred during login. Please try again.', 'danger')
        return render_template('faculty_login.html')

@app.route('/faculty/dashboard')
@login_required
def faculty_dashboard():
    if not is_faculty_user():
        flash('Please log in as a faculty member.', 'danger')
        return redirect(url_for('faculty_login'))

    try:
        faculty = db.session.get(Faculty, current_user.id)
        if not faculty:
            logout_user()
            flash('Faculty account not found.', 'danger')
            return redirect(url_for('faculty_login'))

        # Get duties with exam details
        duties = ExamDuty.query\
            .join(Exam, ExamDuty.exam_id == Exam.id)\
            .filter(ExamDuty.faculty_id == faculty.id)\
            .order_by(Exam.exam_date.asc())\
            .all()
        
        notifications = Notification.query.filter_by(faculty_id=faculty.id).order_by(Notification.created_at.desc()).limit(5).all()
        
        # Get all faculties for swap dropdown (exclude current user)
        all_faculties = Faculty.query.filter(Faculty.id != faculty.id).all()

        total_duties = len(duties)
        accepted_duties = len([d for d in duties if d.status == 'Accepted'])
        declined_duties = len([d for d in duties if d.status == 'Declined'])
        pending_duties = len([d for d in duties if d.status in ('Assigned', 'Pending')])
        
        # Get max_duties for current faculty
        max_duties = faculty.max_duties if hasattr(faculty, 'max_duties') else 5

        # Add current timestamp for cache busting
        current_time = datetime.now().strftime('%Y%m%d%H%M%S')
        
        # Create profile image URL
        profile_image = faculty.profile_image if faculty.profile_image else 'default.png'
        profile_image_url = url_for('uploaded_profile_pic', filename=profile_image)
        
        # Add timestamp for cache busting
        if '?' not in profile_image_url:
            profile_image_url += f'?t={current_time}'

        return render_template('faculty_dashboard.html',
                             faculty=faculty,
                             duties=duties,
                             notifications=notifications,
                             all_faculties=all_faculties,
                             total_duties=total_duties,
                             accepted_duties=accepted_duties,
                             declined_duties=declined_duties,
                             pending_duties=pending_duties,
                             max_duties=max_duties,
                             current_time=current_time,
                             profile_image_url=profile_image_url)
    except Exception as e:
        print(f"Error in faculty_dashboard: {str(e)}")
        flash('An error occurred while loading the dashboard.', 'danger')
        return redirect(url_for('faculty_login'))

@app.route('/faculty/profile', methods=['GET', 'POST'])
@login_required
def faculty_profile():
    if not is_faculty_user():
        return redirect(url_for('faculty_login'))

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'upload_photo':
            if 'profile_photo' not in request.files:
                flash('No file part', 'danger')
                return redirect(request.url)
            
            file = request.files['profile_photo']
            if file.filename == '':
                flash('No selected file', 'danger')
                return redirect(request.url)

            if file:
                # Validate file
                if not file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    flash('Only PNG, JPG, and JPEG files are allowed', 'danger')
                    return redirect(request.url)
                
                # Check file size (5MB max)
                file.seek(0, 2)  # Seek to end
                file_size = file.tell()
                file.seek(0)  # Reset pointer
                
                if file_size > 5 * 1024 * 1024:  # 5MB
                    flash('File size must be less than 5MB', 'danger')
                    return redirect(request.url)
                
                filename = secure_filename(f"{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                upload_path = os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics', filename)
                os.makedirs(os.path.dirname(upload_path), exist_ok=True)
                
                # Remove old photo if exists
                if current_user.profile_image and current_user.profile_image != 'default.png':
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics', current_user.profile_image)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                
                file.save(upload_path)
                
                current_user.profile_image = filename
                db.session.commit()
                flash('Profile photo updated successfully!', 'success')
                return redirect(url_for('faculty_profile'))

        elif action == 'change_password':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')

            if not current_user.check_password(current_password):
                flash('Current password is incorrect.', 'danger')
            elif new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
            elif len(new_password) < 6:
                flash('New password must be at least 6 characters long.', 'danger')
            else:
                current_user.set_password(new_password)
                db.session.commit()
                flash('Password changed successfully!', 'success')
        
        return redirect(url_for('faculty_profile'))

    # For GET request, create profile image URL
    profile_image = current_user.profile_image if current_user.profile_image else 'default.png'
    profile_image_url = url_for('uploaded_profile_pic', filename=profile_image)
    
    # Add timestamp for cache busting
    current_time = datetime.now().strftime('%Y%m%d%H%M%S')
    if '?' not in profile_image_url:
        profile_image_url += f'?t={current_time}'
    
    return render_template('faculty_profile.html', profile_image_url=profile_image_url, current_time=current_time)

    return render_template('faculty_profile.html', profile_image_url=profile_image_url, current_time=current_time)

@app.route('/faculty/get-timetable', methods=['GET'])
@login_required
def get_faculty_timetable():
    if not is_faculty_user():
        return jsonify({'error': 'Unauthorized'}), 401
        
    try:
        timetable = Timetable.query.filter_by(faculty_id=current_user.id).all()
        return jsonify([{
            'id': t.id,
            'day_of_week': t.day_of_week,
            'start_time': str(t.start_time),
            'end_time': str(t.end_time),
            'subject': t.subject
        } for t in timetable])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/faculty/add-timetable', methods=['POST'])
@login_required
def add_faculty_timetable():
    if not is_faculty_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        
        # Parse times
        try:
            start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            end_time = datetime.strptime(data['end_time'], '%H:%M').time()
        except ValueError:
            return jsonify({'error': 'Invalid time format. Use HH:MM'}), 400
            
        entry = Timetable(
            faculty_id=current_user.id,
            day_of_week=data['day_of_week'],
            start_time=start_time,
            end_time=end_time,
            subject=data.get('subject')
        )
        
        db.session.add(entry)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Timetable entry added'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/faculty/delete-timetable/<int:id>', methods=['POST'])
@login_required
def delete_faculty_timetable(id):
    if not is_faculty_user():
        return jsonify({'error': 'Unauthorized'}), 401
        
    try:
        entry = Timetable.query.filter_by(id=id, faculty_id=current_user.id).first()
        if not entry:
            return jsonify({'error': 'Entry not found'}), 404
            
        db.session.delete(entry)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/faculty/upload-timetable', methods=['POST'])
@login_required
def faculty_upload_timetable():
    if not is_faculty_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
        
    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'Only CSV files allowed'}), 400

    try:
        df = pd.read_csv(file)
        # Normalize headers
        df.columns = [c.strip().lower() for c in df.columns]
        
        required = ['day_of_week', 'start_time', 'end_time']
        if not all(col in df.columns for col in required):
            return jsonify({'error': f'Missing required columns: {", ".join(required)}'}), 400
            
        count = 0
        errors = []
        
        # Optional: Clear existing timetable?
        # db.session.query(Timetable).filter_by(faculty_id=current_user.id).delete()
        
        for idx, row in df.iterrows():
            try:
                # Time parsing logic
                start_val = str(row['start_time']).strip()
                end_val = str(row['end_time']).strip()
                
                try:
                    s_time = datetime.strptime(start_val, '%H:%M').time()
                    e_time = datetime.strptime(end_val, '%H:%M').time()
                except ValueError:
                    # Try with seconds just in case
                     s_time = datetime.strptime(start_val, '%H:%M:%S').time()
                     e_time = datetime.strptime(end_val, '%H:%M:%S').time()

                entry = Timetable(
                    faculty_id=current_user.id,
                    day_of_week=str(row['day_of_week']).strip().capitalize(),
                    start_time=s_time,
                    end_time=e_time,
                    subject=str(row['subject']) if 'subject' in df.columns else None
                )
                db.session.add(entry)
                count += 1
            except Exception as e:
                errors.append(f"Row {idx+1}: {str(e)}")
        
        db.session.commit()
        
        if errors:
            return jsonify({'success': True, 'message': f'Imported {count} entries with {len(errors)} warnings. Check data.'})
        else:
            return jsonify({'success': True, 'message': f'Successfully imported {count} timetable entries.'})
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/faculty/download-timetable-template')
@login_required
def download_timetable_template():
    # Create simple CSV
    output = "day_of_week,start_time,end_time,subject\nMonday,09:00,10:00,CS101\nTuesday,11:00,12:30,Meeting"
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=timetable_template.csv"}
    )
    
@app.route('/admin/faculty-details')
@login_required
def faculty_details():
    if not is_admin_user():
        return redirect(url_for('admin_login'))
    return render_template('faculty_details.html')

@app.route('/admin/get-departments', methods=['GET'])
@login_required
def get_departments_list():
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        # Get unique departments
        departments = [d[0] for d in db.session.query(Faculty.department).distinct().all()]
        return jsonify(departments)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/get-faculty-list', methods=['GET'])
@login_required
def get_faculty_list_admin():
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
        
    try:
        dept = request.args.get('department')
        query = Faculty.query
        if dept and dept != 'null' and dept != 'None':
            query = query.filter_by(department=dept)
            
        faculties = query.order_by(Faculty.name).all()
        return jsonify([{
            'id': f.id,
            'name': f.name,
            'department': f.department
        } for f in faculties])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/get-faculty-details/<int:id>', methods=['GET'])
@login_required
def get_faculty_details_admin(id):
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        faculty = db.session.get(Faculty, id)
        if not faculty:
            return jsonify({'error': 'Faculty not found'}), 404
            
        # Get Stats
        total_duties = ExamDuty.query.filter_by(faculty_id=id).count()
        completed = ExamDuty.query.filter_by(faculty_id=id, status='Accepted').count()
        pending = ExamDuty.query.filter_by(faculty_id=id).filter(ExamDuty.status.in_(['Pending', 'Assigned'])).count()
        
        # Get Timetable
        timetable = Timetable.query.filter_by(faculty_id=id).all()
        timetable_data = [{
            'day': t.day_of_week,
            'start': str(t.start_time),
            'end': str(t.end_time),
            'subject': t.subject
        } for t in timetable]
        
        # Get Recent Duties
        recent = ExamDuty.query.filter_by(faculty_id=id).join(Exam).order_by(Exam.exam_date.desc()).limit(5).all()
        recent_data = [{
            'date': str(d.exam.exam_date),
            'subject': d.exam.subject_name,
            'status': d.status
        } for d in recent]
        
        # Profile Image
        profile_image = faculty.profile_image if faculty.profile_image else 'default.png'
        profile_image_url = url_for('uploaded_profile_pic', filename=profile_image)
        
        return jsonify({
            'id': faculty.id,
            'faculty_id': faculty.faculty_id,
            'name': faculty.name,
            'email': faculty.email,
            'department': faculty.department,
            'profile_image': profile_image_url,
            'stats': {
                'total': total_duties,
                'completed': completed,
                'pending': pending
            },
            'timetable': timetable_data,
            'recent_duties': recent_data
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/faculty/respond-duty', methods=['POST'])
@login_required
def respond_duty():
    """
    Handle faculty response to exam duty assignment - COMPLETELY FIXED VERSION
    """
    try:
        print(f"\n=== RESPOND DUTY CALLED ===")
        
        # Get current faculty
        faculty = db.session.get(Faculty, current_user.id)
        if not faculty:
            return jsonify({'error': 'Faculty not found'}), 404
        
        print(f"Faculty: {faculty.name} ({faculty.email})")
        
        # Get JSON data from request
        if request.content_type and 'application/json' in request.content_type:
            data = request.get_json() or {}
        else:
            data = {
                'duty_id': request.form.get('duty_id'),
                'notification_id': request.form.get('notification_id'),
                'response': request.form.get('response'),
                'reason': request.form.get('reason', '')
            }
        
        # Extract data
        notification_id = data.get('notification_id')
        duty_id = data.get('duty_id', 0)
        response_action = data.get('response')  # 'accept' or 'deny'
        reason = data.get('reason', '')
        
        print(f"Duty ID: {duty_id}")
        print(f"Notification ID: {notification_id}")
        print(f"Response: {response_action}")
        print(f"Reason: {reason}")
        
        # Validate response action
        if response_action not in ['accept', 'deny']:
            return jsonify({'error': 'Invalid response action. Use "accept" or "deny"'}), 400
        
        # If duty_id is 0 or invalid, try to get it from notification
        if not duty_id or duty_id == 0 or duty_id == '0':
            if notification_id:
                notification = db.session.get(Notification, notification_id)
                if notification and notification.duty_id:
                    duty_id = notification.duty_id
                    print(f"Using duty_id from notification: {duty_id}")
                else:
                    return jsonify({'error': 'Could not determine duty ID from notification'}), 400
            else:
                return jsonify({'error': 'Duty ID is required'}), 400
        
        # Get the duty record
        duty = db.session.get(ExamDuty, duty_id)
        if not duty:
            print(f"ERROR: Duty {duty_id} not found")
            return jsonify({'error': f'Duty {duty_id} not found'}), 404
        
        print(f"Duty found: Faculty ID: {duty.faculty_id}, Exam: {duty.exam.subject_name}")
        
        # Check if faculty is assigned to this duty
        if duty.faculty_id != faculty.id:
            print(f"ERROR: Faculty {faculty.id} not assigned to duty {duty_id}. Duty faculty: {duty.faculty_id}")
            return jsonify({'error': 'You are not assigned to this duty'}), 403
        
        # Update the duty status
        if response_action == 'accept':
            duty.status = 'Accepted'
            print(f"Duty {duty_id} accepted by {faculty.email}")
        elif response_action == 'deny':
            duty.status = 'Declined'
            duty.notes = reason or "No reason provided"
            print(f"Duty {duty_id} denied by {faculty.email}. Reason: {reason}")
        
        duty.responded_at = datetime.utcnow()
        duty.updated_at = datetime.utcnow()
        
        # Update notification status if notification_id is provided
        if notification_id:
            notification = db.session.get(Notification, notification_id)
            if notification and notification.faculty_id == faculty.id:
                notification.is_read = True
                notification.updated_at = datetime.utcnow()
                print(f"Notification {notification_id} marked as read")
        
        # Create a notification for the faculty
        faculty_notification = Notification(
            faculty_id=faculty.id,
            message=f"You have {response_action}ed duty for {duty.exam.subject_name} on {duty.exam.exam_date}",
            notification_type='success' if response_action == 'accept' else 'warning',
            is_read=False,
            created_at=datetime.utcnow()
        )
        db.session.add(faculty_notification)
        
        # If denied, create a notification for all admins
        if response_action == 'deny':
            admins = Admin.query.all()
            for admin in admins:
                admin_notification = Notification(
                    admin_id=admin.id,
                    message=f'Faculty {faculty.name} ({faculty.faculty_id}) denied duty for {duty.exam.subject_name} on {duty.exam.exam_date}. Reason: {reason}',
                    notification_type='danger',
                    is_read=False,
                    created_at=datetime.utcnow()
                )
                db.session.add(admin_notification)
                print(f"Created admin notification for denial to admin {admin.email}")
        
        # Commit all changes
        db.session.commit()
        
        # Trigger notification service for emails (Faculty confirmation & Admin notification)
        # Use threading to prevent UI blocking
        import threading
        def send_notification_async():
            with app.app_context():
                try:
                    notification_service.send_duty_response_notification(
                        faculty.id, 
                        duty_id, 
                        response_action
                    )
                except Exception as e:
                    print(f"Error sending async notification: {e}")

        # Start thread
        notification_thread = threading.Thread(target=send_notification_async)
        notification_thread.start()
        
        print(f"SUCCESS: Duty {duty_id} {response_action}ed")
        print(f"===================================\n")
        
        return jsonify({
            'success': True,
            'message': f'Duty {response_action}ed successfully',
            'duty_id': duty_id,
            'status': duty.status,
            'notification_id': notification_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"\n=== ERROR in respond_duty ===")
        print(f"Exception: {str(e)}")
        traceback.print_exc()
        print(f"=============================\n")
        
        return jsonify({
            'error': 'Internal server error',
            'details': str(e)
        }), 500

@app.route('/faculty/upload-profile-photo-ajax', methods=['POST'])
@login_required
def upload_profile_photo_ajax():
    """AJAX endpoint for profile photo upload from dashboard"""
    if not is_faculty_user():
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        print(f"\n=== UPLOAD PROFILE PHOTO AJAX ===")
        
        if 'profile_photo' not in request.files:
            return jsonify({'success': False, 'error': 'No file part'}), 400
        
        file = request.files['profile_photo']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No selected file'}), 400

        # Validate file
        if not file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            return jsonify({'success': False, 'error': 'Only PNG, JPG, and JPEG files are allowed'}), 400
        
        # Check file size (5MB max)
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset pointer
        
        if file_size > 5 * 1024 * 1024:  # 5MB
            return jsonify({'success': False, 'error': 'File size must be less than 5MB'}), 400
        
        # Create unique filename with timestamp to prevent caching issues
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = secure_filename(f"{current_user.id}_{timestamp}_{file.filename}")
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics', filename)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(upload_path), exist_ok=True)
        
        # Remove old photo if exists and not default
        if current_user.profile_image and current_user.profile_image != 'default.png':
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics', current_user.profile_image)
            if os.path.exists(old_path):
                os.remove(old_path)
                print(f"Removed old photo: {old_path}")
        
        # Save new photo
        file.save(upload_path)
        print(f"Saved new photo to: {upload_path}")
        
        # Update database
        current_user.profile_image = filename
        db.session.commit()
        
        # Create the URL for the uploaded photo
        profile_image_url = url_for('uploaded_profile_pic', filename=filename)
        
        # Return success with filename and URL for cache busting
        return jsonify({
            'success': True, 
            'message': 'Profile photo updated successfully!',
            'filename': filename,
            'profile_image_url': profile_image_url,
            'timestamp': timestamp
        })

    except Exception as e:
        db.session.rollback()
        print(f"Error uploading photo: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Error uploading photo: {str(e)}'}), 500

@app.route('/uploads/profile_pics/<filename>')
def uploaded_profile_pic(filename):
    """Serve uploaded profile pictures"""
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics', filename)
        if os.path.exists(file_path):
            return send_file(file_path)
        else:
            # Return default profile picture
            default_path = os.path.join(app.static_folder, 'profile_pics', 'default.png')
            if os.path.exists(default_path):
                return send_file(default_path)
            else:
                # Create a simple default image
                from PIL import Image, ImageDraw
                img = Image.new('RGB', (200, 200), color='#007bff')
                d = ImageDraw.Draw(img)
                d.text((100, 100), "User", fill='white', anchor='mm')
                img.save(file_path)
                return send_file(file_path)
    except Exception as e:
        print(f"Error serving profile picture {filename}: {str(e)}")
        # Return 404 if image not found
        return '', 404

# Swap Request Routes
@app.route('/faculty/get-swap-requests')
@login_required
def get_swap_requests():
    """Get swap requests for current faculty"""
    if not is_faculty_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        print(f"\n=== GET SWAP REQUESTS for faculty {current_user.id} ===")
        
        # Get swap requests where current faculty is the requested faculty
        swap_requests = DutySwap.query.filter_by(
            requested_faculty_id=current_user.id,
            status='Pending'
        ).order_by(DutySwap.created_at.desc()).all()
        
        print(f"Found {len(swap_requests)} pending swap requests")
        
        requests_list = []
        for swap in swap_requests:
            # Get duty details
            duty = db.session.get(ExamDuty, swap.requester_duty_id)
            if duty and hasattr(duty, 'exam') and duty.exam:
                # Get requester faculty details
                requester = db.session.get(Faculty, swap.requester_faculty_id)
                if requester:
                    requests_list.append({
                        'swap_id': swap.id,
                        'duty_id': duty.id,
                        'requester_id': requester.id,
                        'requester_name': requester.name,
                        'requester_faculty_id': requester.faculty_id,
                        'requester_department': requester.department,
                        'requester_email': requester.email,
                        'exam_name': duty.exam.subject_name,
                        'subject_code': duty.exam.subject_code,
                        'exam_date': str(duty.exam.exam_date),
                        'exam_time': f"{duty.exam.start_time} - {duty.exam.end_time}",
                        'hall': duty.exam.hall,
                        'created_at': swap.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        'notes': swap.notes or ''
                    })
                    print(f"  - Swap request {swap.id}: {requester.name} wants to swap duty for {duty.exam.subject_name}")
            else:
                print(f"  - Warning: Duty {swap.requester_duty_id} not found or has no exam")
        
        # Also get swap requests made by current user
        sent_requests = DutySwap.query.filter_by(
            requester_faculty_id=current_user.id
        ).order_by(DutySwap.created_at.desc()).all()
        
        sent_list = []
        for swap in sent_requests:
            duty = db.session.get(ExamDuty, swap.requester_duty_id)
            if duty and hasattr(duty, 'exam') and duty.exam:
                requested_faculty = db.session.get(Faculty, swap.requested_faculty_id)
                if requested_faculty:
                    sent_list.append({
                        'swap_id': swap.id,
                        'duty_id': duty.id,
                        'requested_faculty_name': requested_faculty.name,
                        'exam_name': duty.exam.subject_name,
                        'exam_date': str(duty.exam.exam_date),
                        'status': swap.status,
                        'created_at': swap.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        'responded_at': swap.responded_at.strftime('%Y-%m-%d %H:%M:%S') if swap.responded_at else None,
                        'notes': swap.notes or ''
                    })
        
        return jsonify({
            'success': True, 
            'received_requests': requests_list,
            'sent_requests': sent_list
        })
    
    except Exception as e:
        print(f"Error getting swap requests: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/faculty/request-swap', methods=['POST'])
@login_required
def request_swap():
    """Request a duty swap with another faculty"""
    print(f"\n=== REQUEST SWAP ===")
    
    if not is_faculty_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # Parse request data
        if request.content_type and 'application/json' in request.content_type:
            data = request.get_json() or {}
        else:
            data = {
                'duty_id': request.form.get('duty_id'),
                'target_faculty_id': request.form.get('target_faculty_id'),
                'reason': request.form.get('reason', '')
            }
        
        duty_id = data.get('duty_id')
        target_faculty_id = data.get('target_faculty_id')
        reason = data.get('reason', '')
        
        print(f"Swap request data: duty_id={duty_id}, target_faculty_id={target_faculty_id}, reason={reason}")
        
        if not duty_id or not target_faculty_id:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Convert to integers
        try:
            duty_id = int(duty_id)
            target_faculty_id = int(target_faculty_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid ID format'}), 400
        
        # Get duty
        duty = db.session.get(ExamDuty, duty_id)
        if not duty:
            return jsonify({'success': False, 'error': 'Duty not found'}), 404
        
        # Check if duty belongs to current user
        if duty.faculty_id != current_user.id:
            return jsonify({'success': False, 'error': 'You can only request swaps for your own duties'}), 403
        
        # Check if duty is already accepted
        if duty.status != 'Accepted':
            return jsonify({'success': False, 'error': 'You can only request swaps for accepted duties'}), 400
        
        # Get target faculty
        target_faculty = db.session.get(Faculty, target_faculty_id)
        if not target_faculty:
            return jsonify({'success': False, 'error': 'Target faculty not found'}), 404
        
        # Check if target faculty is the same as current user
        if target_faculty_id == current_user.id:
            return jsonify({'success': False, 'error': 'Cannot request swap with yourself'}), 400
        
        # Check for existing pending swap request for this duty
        existing_swap = DutySwap.query.filter_by(
            requester_duty_id=duty_id,
            status='Pending'
        ).first()
        
        if existing_swap:
            return jsonify({'success': False, 'error': 'A pending swap request already exists for this duty'}), 400
        
        # Create swap request
        swap_request = DutySwap(
            requester_duty_id=duty_id,
            requester_faculty_id=current_user.id,
            requested_faculty_id=target_faculty_id,
            status='Pending',
            notes=reason
        )
        
        db.session.add(swap_request)
        
        # Create notification for target faculty
        notification = Notification(
            faculty_id=target_faculty_id,
            message=f"{current_user.name} has requested to swap duty for {duty.exam.subject_name} on {duty.exam.exam_date}",
            notification_type='info'
        )
        db.session.add(notification)
        
        # Create notification for requester
        requester_notification = Notification(
            faculty_id=current_user.id,
            message=f"Swap request sent to {target_faculty.name} for duty on {duty.exam.exam_date}",
            notification_type='info'
        )
        db.session.add(requester_notification)
        
        db.session.commit()
        
        print(f"Swap request created: ID {swap_request.id}")
        
        # Send email notification to target faculty
        try:
            subject = f"🔁 Swap Request: {duty.exam.subject_name}"
            body = f"""
            **SWAP REQUEST NOTIFICATION**
            
            **Requester:**
            - Name: {current_user.name}
            - Faculty ID: {current_user.faculty_id}
            - Department: {current_user.department}
            
            **Duty Details:**
            - Subject: {duty.exam.subject_name} ({duty.exam.subject_code})
            - Date: {duty.exam.exam_date}
            - Time: {duty.exam.start_time} - {duty.exam.end_time}
            - Hall: {duty.exam.hall}
            
            **Reason for Swap:**
            {reason if reason else 'No reason provided'}
            
            **Action Required:**
            Please log in to the Exam Duty System to accept or reject this swap request.
            
            ---
            This is an automated notification from the Exam Duty System.
            """
            
            notification_service.send_email(
                target_faculty.email,
                subject,
                body
            )
            print(f"✓ Email notification sent to {target_faculty.email}")
        except Exception as email_error:
            print(f"✗ Email notification failed: {email_error}")
        
        return jsonify({
            'success': True, 
            'message': f'Swap request sent to {target_faculty.name}',
            'swap_id': swap_request.id
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error creating swap request: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/faculty/respond-swap', methods=['POST'])
@login_required
def respond_swap():
    """Respond to a swap request (accept or reject)"""
    print(f"\n=== RESPOND SWAP ===")
    
    if not is_faculty_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # Parse request data
        if request.content_type and 'application/json' in request.content_type:
            data = request.get_json() or {}
        else:
            data = {
                'swap_id': request.form.get('swap_id'),
                'response': request.form.get('response'),
                'reason': request.form.get('reason', '')
            }
        
        swap_id = data.get('swap_id')
        response = data.get('response')
        reason = data.get('reason', '')
        
        print(f"Swap response data: swap_id={swap_id}, response={response}, reason={reason}")
        
        if not swap_id or not response:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Convert to integer
        try:
            swap_id = int(swap_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid swap ID format'}), 400
        
        # Get swap request
        swap_request = db.session.get(DutySwap, swap_id)
        if not swap_request:
            return jsonify({'success': False, 'error': 'Swap request not found'}), 404
        
        # Check if current user is the requested faculty
        if swap_request.requested_faculty_id != current_user.id:
            return jsonify({'success': False, 'error': 'You are not authorized to respond to this swap request'}), 403
        
        # Check if swap request is still pending
        if swap_request.status != 'Pending':
            return jsonify({'success': False, 'error': 'This swap request has already been processed'}), 400
        
        # Determine response
        response_lower = str(response).lower().strip()
        if response_lower in ['accept', 'accepted', 'yes', 'true', 'approve']:
            new_status = 'Accepted'
            action_verb = 'accepted'
        elif response_lower in ['reject', 'deny', 'decline', 'denied', 'declined', 'no', 'false', 'rejected']:
            new_status = 'Rejected'
            action_verb = 'rejected'
        else:
            return jsonify({'success': False, 'error': 'Invalid response. Use "accept" or "reject"'}), 400
        
        # Get duty details
        duty = db.session.get(ExamDuty, swap_request.requester_duty_id)
        if not duty or not hasattr(duty, 'exam') or not duty.exam:
            return jsonify({'success': False, 'error': 'Associated duty not found'}), 404
        
        # Get requester details
        requester = db.session.get(Faculty, swap_request.requester_faculty_id)
        if not requester:
            return jsonify({'success': False, 'error': 'Requester not found'}), 404
        
        if new_status == 'Accepted':
            # Swap the duty
            original_faculty_id = duty.faculty_id
            
            # Update duty to new faculty
            duty.faculty_id = current_user.id
            duty.status = 'Accepted'  # Ensure status remains Accepted
            duty.updated_at = datetime.utcnow()
            
            # Create notification for both parties
            success_message = f"Swap accepted! Duty for {duty.exam.subject_name} on {duty.exam.exam_date} has been transferred to you."
            
        else:  # Rejected
            success_message = f"Swap request rejected."
        
        # Update swap request
        swap_request.status = new_status
        swap_request.responded_at = datetime.utcnow()
        if reason:
            swap_request.notes = f"{swap_request.notes or ''}\nResponse: {reason}"
        
        # Create notifications
        # For current user (responder)
        responder_notification = Notification(
            faculty_id=current_user.id,
            message=f"You {action_verb} swap request from {requester.name} for {duty.exam.subject_name}",
            notification_type='success' if new_status == 'Accepted' else 'warning'
        )
        db.session.add(responder_notification)
        
        # For requester
        requester_notification = Notification(
            faculty_id=requester.id,
            message=f"{current_user.name} has {action_verb} your swap request for {duty.exam.subject_name} on {duty.exam.exam_date}",
            notification_type='success' if new_status == 'Accepted' else 'warning'
        )
        db.session.add(requester_notification)
        
        db.session.commit()
        
        print(f"Swap request {swap_id} {action_verb}")
        
        # Send email notifications
        try:
            # Email to requester
            subject = f"🔁 Swap Request {new_status}: {duty.exam.subject_name}"
            
            if new_status == 'Accepted':
                body = f"""
                **SWAP REQUEST ACCEPTED**
                
                **Responder:**
                - Name: {current_user.name}
                - Faculty ID: {current_user.faculty_id}
                - Department: {current_user.department}
                
                **Duty Details:**
                - Subject: {duty.exam.subject_name} ({duty.exam.subject_code})
                - Date: {duty.exam.exam_date}
                - Time: {duty.exam.start_time} - {duty.exam.end_time}
                - Hall: {duty.exam.hall}
                
                **Status:**
                The duty has been successfully transferred to {current_user.name}.
                
                ---
                This is an automated notification from the Exam Duty System.
                """
            else:
                body = f"""
                **SWAP REQUEST REJECTED**
                
                **Responder:**
                - Name: {current_user.name}
                - Faculty ID: {current_user.faculty_id}
                - Department: {current_user.department}
                
                **Duty Details:**
                - Subject: {duty.exam.subject_name} ({duty.exam.subject_code})
                - Date: {duty.exam.exam_date}
                - Time: {duty.exam.start_time} - {duty.exam.end_time}
                - Hall: {duty.exam.hall}
                
                **Response Reason:**
                {reason if reason else 'No reason provided'}
                
                **Status:**
                Your swap request has been rejected. The duty remains assigned to you.
                
                ---
                This is an automated notification from the Exam Duty System.
                """
            
            # Send to requester
            notification_service.send_email(requester.email, subject, body)
            print(f"✓ Email sent to requester {requester.email}")
            
            # Send to responder if accepted
            if new_status == 'Accepted':
                responder_body = f"""
                **SWAP ACCEPTED - DUTY ASSIGNED**
                
                You have accepted a swap request from {requester.name}.
                
                **Duty Details:**
                - Subject: {duty.exam.subject_name} ({duty.exam.subject_code})
                - Date: {duty.exam.exam_date}
                - Time: {duty.exam.start_time} - {duty.exam.end_time}
                - Hall: {duty.exam.hall}
                
                **Previous Faculty:**
                - Name: {requester.name}
                - Faculty ID: {requester.faculty_id}
                
                **Status:**
                This duty is now assigned to you. Please make necessary arrangements.
                
                ---
                This is an automated notification from the Exam Duty System.
                """
                
                notification_service.send_email(current_user.email, f"✅ New Duty Assigned via Swap: {duty.exam.subject_name}", responder_body)
                print(f"✓ Email sent to responder {current_user.email}")
                
        except Exception as email_error:
            print(f"✗ Email notification failed: {email_error}")
        
        return jsonify({
            'success': True, 
            'message': success_message,
            'status': new_status,
            'swap_id': swap_id
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error responding to swap request: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/faculty/cancel-swap/<int:swap_id>', methods=['POST'])
@login_required
def cancel_swap(swap_id):
    """Cancel a pending swap request"""
    if not is_faculty_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        swap_request = db.session.get(DutySwap, swap_id)
        if not swap_request:
            return jsonify({'success': False, 'error': 'Swap request not found'}), 404
        
        # Check if user is the requester
        if swap_request.requester_faculty_id != current_user.id:
            return jsonify({'success': False, 'error': 'You can only cancel your own swap requests'}), 403
        
        # Check if still pending
        if swap_request.status != 'Pending':
            return jsonify({'success': False, 'error': 'Cannot cancel a processed swap request'}), 400
        
        # Get duty details for notification
        duty = db.session.get(ExamDuty, swap_request.requester_duty_id)
        
        # Delete the swap request
        db.session.delete(swap_request)
        
        # Create notification
        notification = Notification(
            faculty_id=current_user.id,
            message=f"Swap request cancelled for duty on {duty.exam.exam_date if duty and duty.exam else 'unknown date'}",
            notification_type='info'
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Swap request cancelled successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/faculty/get-available-faculty')
@login_required
def get_available_faculty():
    """Get list of faculty available for swap (excluding current user)"""
    if not is_faculty_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # Get all faculties except current user
        faculties = Faculty.query.filter(Faculty.id != current_user.id).all()
        
        faculty_list = []
        for faculty in faculties:
            # Get current duty count
            duty_count = ExamDuty.query.filter_by(faculty_id=faculty.id, status='Accepted').count()
            
            # Get max duties
            max_duties = faculty.max_duties if hasattr(faculty, 'max_duties') and faculty.max_duties else 5
            
            faculty_list.append({
                'id': faculty.id,
                'faculty_id': faculty.faculty_id,
                'name': faculty.name,
                'department': faculty.department,
                'email': faculty.email,
                'current_duties': duty_count,
                'max_duties': max_duties,
                'available_slots': max_duties - duty_count,
                'is_available': (max_duties - duty_count) > 0
            })
        
        # Sort by available slots (descending)
        faculty_list.sort(key=lambda x: x['available_slots'], reverse=True)
        
        return jsonify({
            'success': True,
            'faculties': faculty_list
        })
        
    except Exception as e:
        print(f"Error getting available faculty: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/faculty/notifications')
@login_required
def faculty_notifications():
    try:
        faculty = db.session.get(Faculty, current_user.id)
        if faculty:
            # Get all notifications for the faculty
            notifications = Notification.query.filter_by(faculty_id=faculty.id).order_by(Notification.created_at.desc()).all()
            
            # For each notification, try to find associated duty if it's a duty assignment notification
            notification_data = []
            for notification in notifications:
                notification_dict = {
                    'id': notification.id,
                    'message': notification.message,
                    'notification_type': notification.notification_type,
                    'is_read': notification.is_read,
                    'created_at': notification.created_at,
                    'duty_id': None
                }
                
                # Try to extract duty_id from the notification
                # This assumes notification message contains duty information
                # You might need to adjust this based on how you create notifications
                if 'duty' in notification.message.lower() and 'assigned' in notification.message.lower():
                    # Try to find a pending duty for this faculty
                    pending_duties = ExamDuty.query.filter_by(
                        faculty_id=faculty.id, 
                        status='Pending'
                    ).all()
                    
                    if pending_duties:
                        # Use the most recent pending duty
                        notification_dict['duty_id'] = pending_duties[0].id
                
                notification_data.append(notification_dict)
            
            return render_template('notifications.html', notifications=notification_data, user=faculty)
        else:
            flash('Faculty account not found', 'danger')
            return redirect(url_for('faculty_login'))
    except Exception as e:
        print(f"Error loading notifications: {str(e)}")
        flash('Error loading notifications', 'danger')
        return render_template('notifications.html', notifications=[], user=None)

@app.route('/faculty/mark-notification-read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    if not is_faculty_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    notification = db.session.get(Notification, notification_id)
    if notification and notification.faculty_id == current_user.id:
        notification.is_read = True
        db.session.commit()
        return jsonify({'success': 'Notification marked as read'})
    
    return jsonify({'error': 'Notification not found'}), 404

# New Backup and Restore Routes
@app.route('/admin/backup', methods=['POST'])
@login_required
def backup_database():
    """Create a backup of the database"""
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # Create backups directory if it doesn't exist
        backup_dir = 'backups'
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'exam_duty_backup_{timestamp}.db'
        backup_path = os.path.join(backup_dir, backup_filename)
        
        # Get the current database path
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        
        # Copy the database file
        import shutil
        shutil.copy2(db_path, backup_path)
        
        # Also backup important CSV files if they exist
        data_dir = 'data'
        if os.path.exists(data_dir):
            backup_data_dir = os.path.join(backup_dir, f'data_{timestamp}')
            shutil.copytree(data_dir, backup_data_dir)
        
        # Log the backup
        print(f"Database backup created: {backup_filename}")
        
        return jsonify({
            'success': True,
            'message': f'Backup created successfully: {backup_filename}',
            'backup_file': backup_filename,
            'backup_size': f"{os.path.getsize(backup_path) / (1024*1024):.2f} MB"
        })
        
    except Exception as e:
        print(f"Backup error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/list-backups')
@login_required
def list_backups():
    """List all available backups"""
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        backup_dir = 'backups'
        if not os.path.exists(backup_dir):
            return jsonify({'backups': []})
        
        backups = []
        for filename in os.listdir(backup_dir):
            if filename.endswith('.db'):
                filepath = os.path.join(backup_dir, filename)
                file_info = {
                    'filename': filename,
                    'size': os.path.getsize(filepath),
                    'created': datetime.fromtimestamp(os.path.getctime(filepath)).strftime('%Y-%m-%d %H:%M:%S'),
                    'size_formatted': f"{os.path.getsize(filepath) / (1024*1024):.2f} MB"
                }
                backups.append(file_info)
        
        # Sort by creation time (newest first)
        backups.sort(key=lambda x: x['created'], reverse=True)
        
        return jsonify({'backups': backups})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/restore-backup/<filename>', methods=['POST'])
@login_required
def restore_backup(filename):
    """Restore database from backup"""
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        backup_dir = 'backups'
        backup_path = os.path.join(backup_dir, filename)
        
        if not os.path.exists(backup_path):
            return jsonify({'error': 'Backup file not found'}), 404
        
        # Get the current database path
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        
        # Create a backup of the current database before restoring
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pre_restore_backup = f'pre_restore_{timestamp}.db'
        pre_restore_path = os.path.join(backup_dir, pre_restore_backup)
        import shutil
        shutil.copy2(db_path, pre_restore_path)
        
        # Stop the Flask app's database connections
        db.session.close_all()
        db.engine.dispose()
        
        # Copy the backup to the database location
        shutil.copy2(backup_path, db_path)
        
        # Reinitialize the database connection
        db.create_all()
        
        print(f"Database restored from backup: {filename}")
        
        return jsonify({
            'success': True,
            'message': f'Database restored successfully from {filename}. Current database backed up as {pre_restore_backup}.'
        })
        
    except Exception as e:
        print(f"Restore error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/delete-backup/<filename>', methods=['POST'])
@login_required
def delete_backup(filename):
    """Delete a backup file"""
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        backup_dir = 'backups'
        backup_path = os.path.join(backup_dir, filename)
        
        if not os.path.exists(backup_path):
            return jsonify({'error': 'Backup file not found'}), 404
        
        os.remove(backup_path)
        
        return jsonify({
            'success': True,
            'message': f'Backup {filename} deleted successfully'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Password Reset Routes
@app.route('/admin/reset-faculty-password', methods=['POST'])
@login_required
def reset_faculty_password():
    """Reset a faculty member's password"""
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        faculty_id = request.form.get('faculty_id')
        new_password = request.form.get('new_password')
        
        if not faculty_id or not new_password:
            return jsonify({'error': 'Faculty ID and new password are required'}), 400
        
        faculty = Faculty.query.filter_by(faculty_id=faculty_id).first()
        if not faculty:
            return jsonify({'error': 'Faculty not found'}), 404
        
        faculty.set_password(new_password)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Password reset successfully for {faculty.name}'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/admin/send-password-reset-link', methods=['POST'])
@login_required
def send_password_reset_link():
    """Send password reset link to faculty"""
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        faculty_id = request.form.get('faculty_id')
        
        if not faculty_id:
            return jsonify({'error': 'Faculty ID is required'}), 400
        
        faculty = Faculty.query.filter_by(faculty_id=faculty_id).first()
        if not faculty:
            return jsonify({'error': 'Faculty not found'}), 404
        
        # Generate a temporary reset token
        import secrets
        reset_token = secrets.token_urlsafe(32)
        
        # Store the reset token in session (in production, use a database table)
        session[f'reset_token_{faculty.id}'] = {
            'token': reset_token,
            'expires': (datetime.utcnow() + timedelta(hours=24)).isoformat()
        }
        
        # Create reset link
        reset_link = url_for('faculty_reset_password', token=reset_token, faculty_id=faculty.id, _external=True)
        
        # Send email with reset link
        subject = "Password Reset - Exam Duty System"
        body = f"""
        **PASSWORD RESET REQUEST**
        
        Hello {faculty.name},
        
        You have requested to reset your password for the Exam Duty System.
        
        To reset your password, please click the link below:
        {reset_link}
        
        This link will expire in 24 hours.
        
        If you did not request a password reset, please ignore this email.
        
        ---
        This is an automated notification from the Exam Duty System.
        """
        
        notification_service.send_email(faculty.email, subject, body)
        
        return jsonify({
            'success': True,
            'message': f'Password reset link sent to {faculty.email}'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/faculty/reset-password/<token>/<int:faculty_id>', methods=['GET', 'POST'])
def faculty_reset_password(token, faculty_id):
    """Faculty password reset page"""
    try:
        # Verify the reset token
        token_key = f'reset_token_{faculty_id}'
        if token_key not in session:
            flash('Invalid or expired reset link', 'danger')
            return redirect(url_for('faculty_login'))
        
        token_data = session[token_key]
        if token_data['token'] != token:
            flash('Invalid reset token', 'danger')
            return redirect(url_for('faculty_login'))
        
        # Check if token is expired
        expires = datetime.fromisoformat(token_data['expires'])
        if datetime.utcnow() > expires:
            flash('Reset link has expired', 'danger')
            del session[token_key]
            return redirect(url_for('faculty_login'))
        
        if request.method == 'POST':
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if new_password != confirm_password:
                flash('Passwords do not match', 'danger')
                return render_template('reset_password.html', token=token, faculty_id=faculty_id)
            
            if len(new_password) < 6:
                flash('Password must be at least 6 characters long', 'danger')
                return render_template('reset_password.html', token=token, faculty_id=faculty_id)
            
            faculty = Faculty.query.get(faculty_id)
            if not faculty:
                flash('Faculty not found', 'danger')
                return redirect(url_for('faculty_login'))
            
            faculty.set_password(new_password)
            db.session.commit()
            
            # Clear the reset token
            del session[token_key]
            
            flash('Password reset successfully! Please log in with your new password.', 'success')
            return redirect(url_for('faculty_login'))
        
        return render_template('reset_password.html', token=token, faculty_id=faculty_id)
        
    except Exception as e:
        print(f"Password reset error: {str(e)}")
        flash('An error occurred during password reset', 'danger')
        return redirect(url_for('faculty_login'))

# Add advanced rule configuration endpoint
@app.route('/admin/rule-configuration', methods=['GET', 'POST'])
@login_required
def rule_configuration():
    """Manage rule-based assignment configuration"""
    if not is_admin_user():
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        try:
            # Save configuration to database or file
            config_data = {
                'max_duties_default': int(request.form.get('max_duties_default', 5)),
                'prefer_same_department': request.form.get('prefer_same_department') == 'on',
                'balance_workload': request.form.get('balance_workload') == 'on',
                'consider_time_conflicts': request.form.get('consider_time_conflicts') == 'on',
                'avoid_consecutive_days': request.form.get('avoid_consecutive_days') == 'on',
                'prefer_experienced_faculty': request.form.get('prefer_experienced_faculty') == 'on',
                'max_duties_per_day': int(request.form.get('max_duties_per_day', 2)),
                'min_break_hours': int(request.form.get('min_break_hours', 2))
            }
            
            # Save to database or file
            config_path = os.path.join(app.instance_path, 'rule_config.json')
            with open(config_path, 'w') as f:
                json.dump(config_data, f)
            
            flash('Rule configuration saved successfully!', 'success')
            return redirect(url_for('rule_configuration'))
            
        except Exception as e:
            flash(f'Error saving configuration: {str(e)}', 'danger')
    
    # Load existing configuration
    default_config = {
        'max_duties_default': 5,
        'prefer_same_department': True,
        'balance_workload': True,
        'consider_time_conflicts': True,
        'avoid_consecutive_days': True,
        'prefer_experienced_faculty': False,
        'max_duties_per_day': 2,
        'min_break_hours': 2
    }
    
    config_path = os.path.join(app.instance_path, 'rule_config.json')
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
        except:
            config = default_config
    else:
        config = default_config
    
    return render_template('rule_configuration.html', config=config)

# Add faculty preference management
@app.route('/faculty/preferences', methods=['GET', 'POST'])
@login_required
def faculty_preferences():
    """Faculty preference management"""
    if not is_faculty_user():
        return redirect(url_for('faculty_login'))
    
    if request.method == 'POST':
        try:
            # Save faculty preferences
            preferences = {
                'preferred_days': request.form.getlist('preferred_days'),
                'unavailable_dates': request.form.get('unavailable_dates', '').split(','),
                'time_preferences': {
                    'morning': request.form.get('prefer_morning') == 'on',
                    'afternoon': request.form.get('prefer_afternoon') == 'on',
                    'evening': request.form.get('prefer_evening') == 'on'
                },
                'max_duties_per_day': int(request.form.get('max_duties_per_day', 2)),
                'department_preference': request.form.get('department_preference', 'any')
            }
            
            # Save to database or file
            pref_path = os.path.join(app.instance_path, f'preferences_{current_user.id}.json')
            with open(pref_path, 'w') as f:
                json.dump(preferences, f)
            
            flash('Preferences saved successfully!', 'success')
            return redirect(url_for('faculty_preferences'))
            
        except Exception as e:
            flash(f'Error saving preferences: {str(e)}', 'danger')
    
    # Load existing preferences
    default_preferences = {
        'preferred_days': [],
        'unavailable_dates': [],
        'time_preferences': {
            'morning': True,
            'afternoon': True,
            'evening': False
        },
        'max_duties_per_day': 2,
        'department_preference': 'any'
    }
    
    pref_path = os.path.join(app.instance_path, f'preferences_{current_user.id}.json')
    if os.path.exists(pref_path):
        try:
            with open(pref_path, 'r') as f:
                preferences = json.load(f)
        except:
            preferences = default_preferences
    else:
        preferences = default_preferences
    
    return render_template('faculty_preferences.html', preferences=preferences)

# Add advanced analytics endpoint
@app.route('/admin/assignment-analytics')
@login_required
def assignment_analytics():
    """Show analytics for duty assignments"""
    if not is_admin_user():
        return redirect(url_for('admin_login'))
    
    try:
        # Get all duties with faculty and exam info
        duties = ExamDuty.query\
            .join(Faculty, ExamDuty.faculty_id == Faculty.id)\
            .join(Exam, ExamDuty.exam_id == Exam.id)\
            .all()
        
        # Calculate statistics
        total_duties = len(duties)
        accepted_duties = [d for d in duties if d.status == 'Accepted']
        pending_duties = [d for d in duties if d.status == 'Pending']
        declined_duties = [d for d in duties if d.status == 'Declined']
        
        # Workload distribution
        faculty_workload = defaultdict(int)
        for duty in accepted_duties:
            faculty_workload[duty.faculty.name] += 1
        
        # Department distribution
        dept_distribution = defaultdict(int)
        for duty in accepted_duties:
            if duty.exam:
                dept_distribution[duty.exam.department] += 1
        
        # Time slot analysis
        time_slots = defaultdict(int)
        for duty in accepted_duties:
            if duty.exam:
                hour = duty.exam.start_time.hour
                if hour < 12:
                    time_slots['Morning (8-12)'] += 1
                elif hour < 17:
                    time_slots['Afternoon (12-5)'] += 1
                else:
                    time_slots['Evening (5-8)'] += 1
        
        # Calculate fairness metrics
        faculty_duties = list(faculty_workload.values())
        if faculty_duties:
            avg_duties = sum(faculty_duties) / len(faculty_duties)
            max_duties = max(faculty_duties)
            min_duties = min(faculty_duties)
            fairness_score = (min_duties / max_duties * 100) if max_duties > 0 else 100
        else:
            avg_duties = max_duties = min_duties = 0
            fairness_score = 100
        
        analytics = {
            'total_duties': total_duties,
            'accepted_duties': len(accepted_duties),
            'pending_duties': len(pending_duties),
            'declined_duties': len(declined_duties),
            'acceptance_rate': (len(accepted_duties) / total_duties * 100) if total_duties > 0 else 0,
            'faculty_workload': dict(sorted(faculty_workload.items(), key=lambda x: x[1], reverse=True)),
            'department_distribution': dict(dept_distribution),
            'time_distribution': dict(time_slots),
            'fairness_metrics': {
                'average_duties': round(avg_duties, 2),
                'max_duties': max_duties,
                'min_duties': min_duties,
                'fairness_score': round(fairness_score, 2)
            }
        }
        
        return render_template('assignment_analytics.html', analytics=analytics)
        
    except Exception as e:
        print(f"Analytics error: {str(e)}")
        flash('Error loading analytics', 'danger')
        return redirect(url_for('admin_dashboard'))

# Add optimization suggestion endpoint
@app.route('/admin/optimization-suggestions')
@login_required
def optimization_suggestions():
    """Get optimization suggestions for duty assignments"""
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        suggestions = []
        
        # Get all faculty with their duties
        faculties = Faculty.query.all()
        
        for faculty in faculties:
            duties = ExamDuty.query.filter_by(faculty_id=faculty.id, status='Accepted').all()
            max_duties = faculty.max_duties if hasattr(faculty, 'max_duties') else 5
            
            # Check for overloading
            if len(duties) > max_duties:
                suggestions.append({
                    'type': 'warning',
                    'faculty': faculty.name,
                    'message': f'Overloaded: {len(duties)} duties assigned (max: {max_duties})',
                    'suggestion': 'Consider reassigning some duties'
                })
            
            # Check for time conflicts
            duty_by_date = defaultdict(list)
            for duty in duties:
                if duty.exam:
                    duty_by_date[duty.exam.exam_date].append(duty)
            
            for date, date_duties in duty_by_date.items():
                if len(date_duties) > 2:  # More than 2 duties in a day
                    suggestions.append({
                        'type': 'warning',
                        'faculty': faculty.name,
                        'message': f'Heavy schedule on {date}: {len(date_duties)} duties',
                        'suggestion': 'Consider redistributing duties'
                    })
                
                # Check for time conflicts
                date_duties.sort(key=lambda d: d.exam.start_time if d.exam else time())
                for i in range(len(date_duties) - 1):
                    current = date_duties[i]
                    next_duty = date_duties[i + 1]
                    
                    if current.exam and next_duty.exam:
                        current_end = datetime.combine(date, current.exam.end_time)
                        next_start = datetime.combine(date, next_duty.exam.start_time)
                        
                        if (next_start - current_end).total_seconds() / 3600 < 2:
                            suggestions.append({
                                'type': 'warning',
                                'faculty': faculty.name,
                                'message': f'Short break on {date}: {current.exam.subject_name} ends at {current.exam.end_time}, {next_duty.exam.subject_name} starts at {next_duty.exam.start_time}',
                                'suggestion': 'Consider adding more break time'
                            })
        
        # Check for underutilized faculty
        for faculty in faculties:
            duties = ExamDuty.query.filter_by(faculty_id=faculty.id, status='Accepted').count()
            max_duties = faculty.max_duties if hasattr(faculty, 'max_duties') else 5
            
            if duties < max_duties / 2:  # Less than half of capacity
                suggestions.append({
                    'type': 'info',
                    'faculty': faculty.name,
                    'message': f'Underutilized: {duties} duties assigned (capacity: {max_duties})',
                    'suggestion': 'Consider assigning more duties'
                })
        
        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'count': len(suggestions)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/fix-database')
def fix_database():
    try:
        db.drop_all()
        db.create_all()
        
        admin = Admin(username='admin', email='admin@examduty.com')
        admin.set_password('admin123')
        db.session.add(admin)
        
        faculty = Faculty(
            faculty_id='FAC001',
            name='Test Faculty',
            email='faculty@example.com',
            department='Computer Science'
        )
        faculty.set_password('password123')
        db.session.add(faculty)
        
        db.session.commit()
        
        return "<h1>Database Fixed Successfully!</h1>"
    except Exception as e:
        return f"Error fixing database: {str(e)}"

@app.route('/fix-schema')
def fix_schema():
    try:
        from sqlalchemy import text
        
        # Check and add profile_image column if it doesn't exist
        result = db.session.execute(text("PRAGMA table_info(faculty)"))
        columns = [row[1] for row in result]
        
        if 'profile_image' not in columns:
            print("Adding profile_image column to faculty table...")
            db.session.execute(text("ALTER TABLE faculty ADD COLUMN profile_image VARCHAR(200) DEFAULT 'default.png'"))
            db.session.commit()
            print("profile_image column added successfully!")
        
        # Check exam_duty table
        result = db.session.execute(text("PRAGMA table_info(exam_duty)"))
        columns = [row[1] for row in result]
        
        if 'responded_at' not in columns:
            db.session.execute(text("ALTER TABLE exam_duty ADD COLUMN responded_at DATETIME"))
            db.session.commit()
        
        required_columns = ['status', 'assigned_at', 'updated_at', 'notes']
        for column in required_columns:
            if column not in columns:
                if column == 'status':
                    db.session.execute(text(f"ALTER TABLE exam_duty ADD COLUMN {column} VARCHAR(20) DEFAULT 'Pending'"))
                elif column in ['assigned_at', 'updated_at', 'responded_at']:
                    db.session.execute(text(f"ALTER TABLE exam_duty ADD COLUMN {column} DATETIME"))
                elif column == 'notes':
                    db.session.execute(text(f"ALTER TABLE exam_duty ADD COLUMN {column} TEXT"))
                db.session.commit()
        
        # Add max_duties column to faculty if it doesn't exist
        if 'max_duties' not in columns:
            print("Adding max_duties column to faculty table...")
            db.session.execute(text("ALTER TABLE faculty ADD COLUMN max_duties INTEGER DEFAULT 5"))
            db.session.commit()
            print("max_duties column added successfully!")
        
        return "<h1>Database Schema Fixed Successfully!</h1>"
    except Exception as e:
        db.session.rollback()
        return f"Error fixing schema: {str(e)}"

@app.route('/debug/check-faculty')
def debug_check_faculty():
    try:
        faculty = Faculty.query.filter_by(faculty_id='FAC001').first()
        if faculty:
            faculty.set_password('password123')
            db.session.commit()
        else:
            new_faculty = Faculty(faculty_id='FAC001', name='Test Faculty', email='test@example.com', department='Test Department')
            new_faculty.set_password('password123')
            db.session.add(new_faculty)
            db.session.commit()

        faculties = Faculty.query.all()
        result = [{'id': f.id, 'faculty_id': f.faculty_id, 'name': f.name, 'profile_image': f.profile_image, 'max_duties': f.max_duties if hasattr(f, 'max_duties') else 5} for f in faculties]
        return jsonify({'success': True, 'faculties': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/debug-data')
@login_required
def debug_data():
    if not isinstance(current_user, Admin):
        return redirect(url_for('admin_login'))
    
    faculties = Faculty.query.all()
    exams = Exam.query.all()
    duties = ExamDuty.query.all()
    
    debug_info = {
        'faculty_count': len(faculties),
        'exam_count': len(exams),
        'duty_count': len(duties),
        'faculties': [{'id': f.id, 'faculty_id': f.faculty_id, 'name': f.name, 'profile_image': f.profile_image, 'max_duties': f.max_duties if hasattr(f, 'max_duties') else 5} for f in faculties],
        'exams': [{'id': e.id, 'subject': e.subject_name} for e in exams],
        'duties': [{'id': d.id, 'faculty': d.faculty.name, 'exam': d.exam.subject_name, 'status': d.status} for d in duties]
    }
    return jsonify(debug_info)

@app.route('/admin/clear-data', methods=['POST'])
@login_required
def clear_data():
    if not isinstance(current_user, Admin):
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        ExamDuty.query.delete()
        DutySwap.query.delete()
        Notification.query.delete()
        Exam.query.delete()
        Faculty.query.filter(Faculty.faculty_id != 'admin').delete()
        db.session.commit()
        return jsonify({'success': 'All data cleared successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error clearing data: {str(e)}'}), 500

@app.route('/admin/reset-database', methods=['POST'])
@login_required
def reset_database():
    if not is_admin_user():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        db.drop_all()
        db.create_all()
        admin = Admin(username='admin', email='admin@examduty.com')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        return jsonify({'success': 'Database reset successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error resetting database: {str(e)}'}), 500

# Test endpoint for debugging respond-duty
@app.route('/test-respond-duty', methods=['GET', 'POST'])
def test_respond_duty():
    """Test endpoint for respond-duty debugging"""
    if request.method == 'POST':
        print(f"Test endpoint received: {request.form}")
        return jsonify({
            'success': True,
            'message': 'Test successful',
            'received_data': dict(request.form)
        })
    
    return '''
    <html>
    <body>
        <h2>Test Respond Duty Endpoint</h2>
        <form method="POST">
            <input type="text" name="duty_id" placeholder="Duty ID" value="1" required><br><br>
            <input type="text" name="response" placeholder="accept/deny" value="accept" required><br><br>
            <textarea name="reason" placeholder="Reason">Test reason</textarea><br><br>
            <button type="submit">Test Submit</button>
        </form>
        <hr>
        <h3>Test with JavaScript:</h3>
        <button onclick="testAccept()">Test Accept</button>
        <button onclick="testDeny()">Test Deny</button>
        
        <script>
        function testAccept() {
            fetch('/faculty/respond-duty', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    duty_id: 1,
                    response: 'accept',
                    reason: ''
                })
            })
            .then(r => r.json())
            .then(data => alert(JSON.stringify(data)))
            .catch(err => alert('Error: ' + err));
        }
        
        function testDeny() {
            fetch('/faculty/respond-duty', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    duty_id: 1,
                    response: 'deny',
                    reason: 'Test reason for denial'
                })
            })
            .then(r => r.json())
            .then(data => alert(JSON.stringify(data)))
            .catch(err => alert('Error: ' + err));
        }
        </script>
    </body>
    </html>
    '''

# Add favicon route to fix 404 error
@app.route('/favicon.ico')
def favicon():
    try:
        return send_file('static/favicon.ico', mimetype='image/vnd.microsoft.icon')
    except:
        # Return a 204 No Content if favicon doesn't exist
        return '', 204

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('admin_login'))

def create_default_admin():
    with app.app_context():
        if Admin.query.count() == 0:
            admin = Admin(username='admin', email='admin@example.com')
            admin.set_password('admin123')
            db.session.add(admin)
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()

if __name__ == '__main__':
    with app.app_context():
        init_db(app, force=False)
        create_default_admin()
        notification_service.start_reminder_scheduler()
    
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics'), exist_ok=True)
    
    # Create backups directory
    os.makedirs('backups', exist_ok=True)
    
    # Create instance directory for configurations
    os.makedirs(app.instance_path, exist_ok=True)
    
    # Copy default profile picture if it doesn't exist
    default_profile_path = os.path.join(app.static_folder, 'profile_pics', 'default.png')
    if not os.path.exists(default_profile_path):
        # Create a simple default image or copy from somewhere
        import shutil
        default_src = os.path.join(app.root_path, 'static', 'img', 'default-avatar.png')
        if os.path.exists(default_src):
            shutil.copy(default_src, default_profile_path)
        else:
            # Create directory
            os.makedirs(os.path.dirname(default_profile_path), exist_ok=True)
            # Create a simple default image with PIL or leave it empty
            try:
                from PIL import Image, ImageDraw
                img = Image.new('RGB', (200, 200), color='#007bff')
                d = ImageDraw.Draw(img)
                d.text((100, 100), "User", fill='white', anchor='mm')
                img.save(default_profile_path)
                print(f"Created default profile picture at {default_profile_path}")
            except ImportError:
                print("PIL not available, skipping default image creation")
    
    print("\n" + "="*50)
    print("Application is running!")
    print("Access the Admin Login here:   http://localhost:5000/admin/login")
    print("Access the Faculty Login here: http://localhost:5000/faculty/login")
    print("="*50 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)