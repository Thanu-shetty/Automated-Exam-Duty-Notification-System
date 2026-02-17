import smtplib
import schedule
import time
import threading
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from models import db, ExamDuty, Faculty, Exam, ReminderSetting, Notification, Admin
from config import Config
import socket

class NotificationService:
    def __init__(self, app):
        self.app = app
    
    def send_email(self, to_email, subject, body):
        """Send REAL email notification - FIXED VERSION"""
        try:
            print("=" * 60)
            print("📧 ATTEMPTING TO SEND EMAIL")
            print("=" * 60)
            print(f"To: {to_email}")
            print(f"Subject: {subject}")
            print(f"From: {Config.MAIL_DEFAULT_SENDER}")
            print(f"Server: {Config.MAIL_SERVER}:{Config.MAIL_PORT}")
            print("=" * 60)
            
            # Validate
            if not Config.MAIL_USERNAME or not Config.MAIL_PASSWORD:
                print("[ERROR] Email credentials missing")
                return False
            
            if not to_email or '@' not in to_email:
                print(f"[ERROR] Invalid email: {to_email}")
                return False
            
            # Create SIMPLER message to avoid issues
            msg = MIMEMultipart('alternative')
            msg['From'] = Config.MAIL_DEFAULT_SENDER
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Add both plain text and HTML
            text_part = MIMEText("Please view this email in HTML format.", 'plain')
            html_part = MIMEText(body, 'html')
            
            msg.attach(text_part)
            msg.attach(html_part)
            
            # Connect with SHORTER timeout to prevent hanging
            print(f"[DEBUG] Connecting to SMTP server (timeout: 15s)...")
            server = smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT, timeout=15)
            
            # Don't use debuglevel - it can cause hanging
            # server.set_debuglevel(1)  # REMOVED THIS LINE
            
            # Set socket timeout
            server.sock.settimeout(15)
            
            server.ehlo()
            
            print("[DEBUG] Starting TLS...")
            server.starttls()
            server.ehlo()
            
            print(f"[DEBUG] Logging in...")
            server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
            print("[DEBUG] Login successful!")
            
            print(f"[DEBUG] Sending email...")
            # Use sendmail instead of send_message (more reliable)
            email_content = msg.as_string()
            server.sendmail(Config.MAIL_DEFAULT_SENDER, to_email, email_content)
            
            print("[DEBUG] Closing connection...")
            server.quit()
            
            print("✅ EMAIL SENT SUCCESSFULLY!")
            print(f"Sent to: {to_email}")
            print("=" * 60)
            return True
            
        except socket.timeout:
            print("[ERROR] Connection timeout - email sending took too long")
            return False
        except smtplib.SMTPAuthenticationError as e:
            print(f"[ERROR] Authentication failed: {e}")
            return False
        except smtplib.SMTPException as e:
            print(f"[ERROR] SMTP error: {e}")
            return False
        except Exception as e:
            print(f"[ERROR] General error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def generate_notification(self, faculty_name, exam_details, notification_type):
        """Generate notification messages"""
        if notification_type == "assignment":
            return f"Dear {faculty_name}, you have been assigned exam duty. Details: {exam_details}. Please log in to the Exam Duty System to accept or decline this duty."
        elif notification_type == "reminder":
            return f"Reminder: {faculty_name}, your exam duty is scheduled soon. Details: {exam_details}. Please be prepared and arrive on time."
        elif notification_type == "accepted":
            return f"Confirmation: {faculty_name}, you have accepted the exam duty. Details: {exam_details}. Thank you for your commitment."
        elif notification_type == "declined":
            return f"Notification: {faculty_name}, you have declined the exam duty. Details: {exam_details}. The admin will assign this duty to another faculty member."
        else:
            return f"Notification for {faculty_name}: {exam_details}"
    
    def send_duty_assignment_notification(self, faculty_id, exam_duty_id):
        """Send notification when duty is assigned - FIXED VERSION"""
        print(f"\n[INFO] === STARTING DUTY ASSIGNMENT NOTIFICATION ===")
        print(f"[INFO] Faculty ID: {faculty_id}, Duty ID: {exam_duty_id}")
        
        with self.app.app_context():
            try:
                # Refresh the database session to see newly committed data
                db.session.expire_all()
                
                # Get the duty with a fresh query
                duty = ExamDuty.query.get(exam_duty_id)
                if not duty:
                    print(f"[ERROR] Duty with ID {exam_duty_id} not found")
                    print(f"[DEBUG] Checking all duty IDs in database: {[d.id for d in ExamDuty.query.all()]}")
                    return False
                
                # Also refresh related objects
                if not duty.faculty or not duty.exam:
                    print(f"[WARNING] Reloading duty data...")
                    duty = ExamDuty.query.options(
                        db.joinedload(ExamDuty.faculty),
                        db.joinedload(ExamDuty.exam)
                    ).get(exam_duty_id)
                
                if not duty.faculty:
                    print(f"[ERROR] Faculty not found for duty ID {exam_duty_id}")
                    return False
                
                if not duty.exam:
                    print(f"[ERROR] Exam not found for duty ID {exam_duty_id}")
                    return False
                
                faculty = duty.faculty
                exam = duty.exam
                
                print(f"[INFO] Found duty details:")
                print(f"  - Faculty: {faculty.name}")
                print(f"  - Faculty Email: {faculty.email}")
                print(f"  - Exam: {exam.subject_name}")
                print(f"  - Exam Date: {exam.exam_date}")
                print(f"  - Hall: {exam.hall}")
                
                # Check if faculty has valid email
                if not faculty.email or '@' not in faculty.email:
                    print(f"[ERROR] Invalid email for faculty {faculty.name}: {faculty.email}")
                    return False
                
                exam_details = f"{exam.subject_name} ({exam.subject_code}) on {exam.exam_date} at {exam.start_time} in {exam.hall}"
                
                # Generate message
                message = self.generate_notification(
                    faculty.name, 
                    exam_details, 
                    "assignment"
                )
                
                # Send REAL email with SIMPLER HTML
                subject = f"Exam Duty Assignment - {exam.subject_name}"
                email_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                    <h2>Exam Duty Assignment</h2>
                    <p>{message}</p>
                    
                    <h3>Exam Details:</h3>
                    <ul>
                        <li><strong>Subject:</strong> {exam.subject_name} ({exam.subject_code})</li>
                        <li><strong>Date:</strong> {exam.exam_date}</li>
                        <li><strong>Time:</strong> {exam.start_time} - {exam.end_time}</li>
                        <li><strong>Hall:</strong> {exam.hall}</li>
                        <li><strong>Semester:</strong> {exam.semester}</li>
                    </ul>
                    
                    <p><strong>Action Required:</strong> Please log in to the Exam Duty System to accept or decline this duty.</p>
                    
                    <p>Best regards,<br>
                    <strong>Exam Duty System Administration</strong></p>
                </body>
                </html>
                """
                
                print(f"[INFO] Attempting to send email to {faculty.email}...")
                email_sent = self.send_email(faculty.email, subject, email_body)
                
                if email_sent:
                    print(f"✅ Email sent successfully to {faculty.email}")
                else:
                    print(f"❌ Email sending failed for {faculty.email}")
                
                # Create in-app notification regardless of email success
                notification_message = f"You have been assigned exam duty for {exam.subject_name} on {exam.exam_date} at {exam.hall}"
                notification = Notification(
                    faculty_id=faculty_id,
                    message=notification_message,
                    notification_type='info'
                )
                db.session.add(notification)
                db.session.commit()
                
                print(f"[INFO] In-app notification created for faculty {faculty.name}")
                print(f"[INFO] === DUTY ASSIGNMENT NOTIFICATION COMPLETE ===\n")
                
                return email_sent
                
            except Exception as e:
                print(f"[ERROR] Error in send_duty_assignment_notification: {e}")
                print(f"[ERROR] Error type: {type(e).__name__}")
                import traceback
                traceback.print_exc()
                db.session.rollback()
                return False
    
    def send_duty_assignment_direct(self, faculty_id, exam_details):
        """Send duty assignment notification without querying database - FOR AUTO-ALLOCATION"""
        print(f"\n[INFO] === STARTING DIRECT DUTY ASSIGNMENT NOTIFICATION ===")
        print(f"[INFO] Faculty ID: {faculty_id}, Exam Details: {exam_details}")
        
        with self.app.app_context():
            try:
                # Get faculty directly (should exist)
                faculty = Faculty.query.get(faculty_id)
                if not faculty:
                    print(f"[ERROR] Faculty with ID {faculty_id} not found")
                    return False
                
                print(f"[INFO] Found faculty: {faculty.name} ({faculty.email})")
                
                # Check if faculty has valid email
                if not faculty.email or '@' not in faculty.email:
                    print(f"[ERROR] Invalid email for faculty {faculty.name}: {faculty.email}")
                    return False
                
                # Extract exam details from the passed dictionary
                exam_name = exam_details.get('exam_name', 'Unknown Exam')
                exam_date = exam_details.get('exam_date', 'Unknown Date')
                start_time = exam_details.get('start_time', 'Unknown Time')
                end_time = exam_details.get('end_time', 'Unknown Time')
                hall = exam_details.get('hall', 'Unknown Hall')
                subject_code = exam_details.get('subject_code', '')
                department = exam_details.get('department', '')
                
                exam_details_str = f"{exam_name} ({subject_code}) on {exam_date} at {start_time} in {hall}"
                
                # Generate message
                message = self.generate_notification(
                    faculty.name, 
                    exam_details_str, 
                    "assignment"
                )
                
                # Send REAL email
                subject = f"Exam Duty Assignment - {exam_name}"
                email_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                    <h2>Exam Duty Assignment</h2>
                    <p>{message}</p>
                    
                    <h3>Exam Details:</h3>
                    <ul>
                        <li><strong>Subject:</strong> {exam_name} ({subject_code})</li>
                        <li><strong>Date:</strong> {exam_date}</li>
                        <li><strong>Time:</strong> {start_time} - {end_time}</li>
                        <li><strong>Hall:</strong> {hall}</li>
                        <li><strong>Department:</strong> {department}</li>
                    </ul>
                    
                    <p><strong>Action Required:</strong> Please log in to the Exam Duty System to accept or decline this duty.</p>
                    
                    <p>Best regards,<br>
                    <strong>Exam Duty System Administration</strong></p>
                </body>
                </html>
                """
                
                print(f"[INFO] Attempting to send email to {faculty.email}...")
                email_sent = self.send_email(faculty.email, subject, email_body)
                
                if email_sent:
                    print(f"✅ Direct email sent successfully to {faculty.email}")
                else:
                    print(f"❌ Direct email sending failed for {faculty.email}")
                
                # Create in-app notification regardless of email success
                notification_message = f"You have been assigned exam duty for {exam_name} on {exam_date} at {hall}"
                notification = Notification(
                    faculty_id=faculty_id,
                    message=notification_message,
                    notification_type='info'
                )
                db.session.add(notification)
                db.session.commit()
                
                print(f"[INFO] In-app notification created for faculty {faculty.name}")
                print(f"[INFO] === DIRECT DUTY ASSIGNMENT NOTIFICATION COMPLETE ===\n")
                
                return email_sent
                
            except Exception as e:
                print(f"[ERROR] Error in send_duty_assignment_direct: {e}")
                print(f"[ERROR] Error type: {type(e).__name__}")
                import traceback
                traceback.print_exc()
                db.session.rollback()
                return False
    
    def send_duty_response_notification(self, faculty_id, exam_duty_id, response):
        """Send notification when faculty responds to duty"""
        print(f"\n[INFO] === SENDING DUTY RESPONSE NOTIFICATION ===")
        print(f"[INFO] Faculty ID: {faculty_id}, Duty ID: {exam_duty_id}, Response: {response}")
        
        with self.app.app_context():
            try:
                # Refresh session
                db.session.expire_all()
                
                duty = ExamDuty.query.get(exam_duty_id)
                if not duty:
                    print(f"[ERROR] Duty not found with ID {exam_duty_id}")
                    return
                    
                if not duty.faculty:
                    print(f"[ERROR] Faculty not found for duty")
                    return
                    
                if not duty.exam:
                    print(f"[ERROR] Exam not found for duty")
                    return
                    
                faculty = duty.faculty
                exam = duty.exam
                
                print(f"[INFO] Found: {faculty.name} ({faculty.email}) - {exam.subject_name}")
                
                exam_details = f"{exam.subject_name} on {exam.exam_date} at {exam.hall}"
                
                # Generate message based on response
                message_type = "accepted" if response.lower() in ['accepted', 'accept'] else "declined"
                message = self.generate_notification(faculty.name, exam_details, message_type)
                
                # Send REAL email to FACULTY
                subject = f"Duty {response.capitalize()} - {exam.subject_name}"
                email_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif;">
                    <h2>Duty {response.capitalize()}</h2>
                    <p>{message}</p>
                    
                    <h3>Exam Details:</h3>
                    <ul>
                        <li><strong>Subject:</strong> {exam.subject_name} ({exam.subject_code})</li>
                        <li><strong>Date:</strong> {exam.exam_date}</li>
                        <li><strong>Time:</strong> {exam.start_time} - {exam.end_time}</li>
                        <li><strong>Hall:</strong> {exam.hall}</li>
                    </ul>
                    
                    <p>Best regards,<br>
                    <strong>Exam Duty System</strong></p>
                </body>
                </html>
                """
                
                email_sent = self.send_email(faculty.email, subject, email_body)
                if email_sent:
                    print(f"✅ Duty response email sent to {faculty.email}")
                else:
                    print(f"❌ Duty response email failed for {faculty.email}")
                
                print(f"[INFO] === DUTY RESPONSE NOTIFICATION COMPLETE ===\n")
                
                # ALSO NOTIFY ADMIN
                self.send_admin_duty_response_notification(faculty, exam, response, getattr(duty, 'notes', ''))
                
            except Exception as e:
                print(f"[ERROR] Error sending duty response notification: {e}")
                import traceback
                traceback.print_exc()

    def send_admin_duty_response_notification(self, faculty, exam, response, reason=''):
        """Notify admin about faculty response"""
        try:
            # We want to send this to the configured admin email (sender) or a hardworking admin email if we knew it
            # For now use the MAIL_USERNAME as the admin email since current_user might be faculty here
            admin_email = Config.MAIL_USERNAME 
            
            subject = f"Faculty Response: {faculty.name} {response.capitalize()} Duty"
            
            color = "#27ae60" if response.lower() in ['accepted', 'accept'] else "#c0392b"
            
            email_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <h2>Faculty Duty Response</h2>
                
                <div style="padding: 15px; border-left: 5px solid {color}; background-color: #f9f9f9;">
                    <p><strong>Faculty:</strong> {faculty.name} ({faculty.email})</p>
                    <p><strong>Response:</strong> <span style="color: {color}; font-weight: bold;">{response.capitalize()}</span></p>
                    {f'<p><strong>Reason:</strong> {reason}</p>' if reason and response.lower() not in ['accepted', 'accept'] else ''}
                </div>
                
                <h3>Exam Details:</h3>
                <ul>
                    <li><strong>Subject:</strong> {exam.subject_name}</li>
                    <li><strong>Date:</strong> {exam.exam_date}</li>
                    <li><strong>Hall:</strong> {exam.hall}</li>
                </ul>
                
                <p>Please log in to the admin dashboard to manage duties.</p>
            </body>
            </html>
            """
            
            print(f"[INFO] Sending admin notification to {admin_email}")
            self.send_email(admin_email, subject, email_body)
            
        except Exception as e:
            print(f"[ERROR] Error sending admin notification: {e}")
    
    def send_admin_auto_allocation_report(self, admin_email, assignments_made, assignment_details):
        """Send report to admin about auto-allocation results"""
        print(f"\n[INFO] === SENDING ADMIN AUTO-ALLOCATION REPORT ===")
        
        try:
            subject = f"Auto-Allocation Complete - {assignments_made} Duties Assigned"
            
            # Create HTML table of assignments
            assignments_html = ""
            for i, assignment in enumerate(assignment_details, 1):
                assignments_html += f"""
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{i}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{assignment['faculty_name']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{assignment['faculty_email']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{assignment['exam_name']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{assignment['exam_date']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{assignment['hall']}</td>
                </tr>
                """
            
            if not assignments_html:
                assignments_html = """
                <tr>
                    <td colspan="6" style="padding: 20px; text-align: center; color: #666;">
                        No assignments were made during this auto-allocation.
                    </td>
                </tr>
                """
            
            email_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <h2>Auto-Allocation Report</h2>
                
                <div style="background-color: #e8f4fd; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p style="font-size: 16px;">
                        <strong>Auto-allocation completed successfully!</strong><br>
                        Total duties assigned: <span style="color: #27ae60; font-weight: bold;">{assignments_made}</span>
                    </p>
                </div>
                
                <h3>Assignment Details:</h3>
                
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <thead>
                        <tr style="background-color: #3498db; color: white;">
                            <th style="padding: 10px; border: 1px solid #ddd;">#</th>
                            <th style="padding: 10px; border: 1px solid #ddd;">Faculty Name</th>
                            <th style="padding: 10px; border: 1px solid #ddd;">Faculty Email</th>
                            <th style="padding: 10px; border: 1px solid #ddd;">Exam Subject</th>
                            <th style="padding: 10px; border: 1px solid #ddd;">Exam Date</th>
                            <th style="padding: 10px; border: 1px solid #ddd;">Hall</th>
                        </tr>
                    </thead>
                    <tbody>
                        {assignments_html}
                    </tbody>
                </table>
                
                <p><strong>Note:</strong> Email notifications have been sent to all assigned faculty members.</p>
                
                <p>Best regards,<br>
                <strong>Exam Duty System - Automated Allocation</strong><br>
                <small>Report generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
            </body>
            </html>
            """
            
            email_sent = self.send_email(admin_email, subject, email_body)
            if email_sent:
                print(f"✅ Admin report sent to {admin_email}")
            else:
                print(f"❌ Failed to send admin report to {admin_email}")
                
            print(f"[INFO] === ADMIN REPORT COMPLETE ===\n")
            return email_sent
            
        except Exception as e:
            print(f"[ERROR] Error sending admin report: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def send_reminder_notifications(self):
        """Send reminder notifications based on admin settings"""
        print("\n[INFO] === CHECKING FOR REMINDER NOTIFICATIONS ===")
        
        with self.app.app_context():
            try:
                reminder_setting = ReminderSetting.query.first()
                if not reminder_setting:
                    print("[WARNING] No reminder settings found")
                    return
                
                reminder_intervals = [interval.strip() for interval in reminder_setting.reminder_before_exam.split(',')]
                print(f"[INFO] Reminder intervals: {reminder_intervals}")
                
                # Get all accepted duties for today and tomorrow
                today = datetime.now().date()
                duties = ExamDuty.query.join(Exam).filter(
                    ExamDuty.status == 'Accepted',
                    Exam.exam_date >= today,
                    Exam.exam_date <= today + timedelta(days=1)
                ).all()
                
                print(f"[INFO] Found {len(duties)} accepted duties for reminder check")
                
                for duty in duties:
                    exam = duty.exam
                    faculty = duty.faculty
                    
                    # Create datetime object for exam start
                    exam_datetime = datetime.combine(exam.exam_date, exam.start_time)
                    time_until_exam = exam_datetime - datetime.now()
                    
                    print(f"[INFO] Checking duty: {faculty.name} - {exam.subject_name} - Time until: {time_until_exam}")
                    
                    for interval in reminder_intervals:
                        interval = interval.strip().lower()
                        reminder_time = None
                        
                        if 'hour' in interval:
                            try:
                                hours = int(interval.split()[0])
                                reminder_time = timedelta(hours=hours)
                            except (ValueError, IndexError):
                                continue
                        elif 'minute' in interval:
                            try:
                                minutes = int(interval.split()[0])
                                reminder_time = timedelta(minutes=minutes)
                            except (ValueError, IndexError):
                                continue
                        else:
                            continue
                        
                        # Check if we're within 1 minute of the reminder time
                        if reminder_time and (reminder_time - timedelta(minutes=1) <= time_until_exam <= reminder_time + timedelta(minutes=1)):
                            print(f"[INFO] Sending {interval} reminder to {faculty.name}")
                            
                            # Send reminder
                            exam_details = f"{exam.subject_name} in {exam.hall} at {exam.start_time}"
                            message = self.generate_notification(
                                faculty.name, 
                                exam_details, 
                                "reminder"
                            )
                            
                            subject = f"Reminder: Exam Duty - {exam.subject_name}"
                            email_body = f"""
                            <html>
                            <body style="font-family: Arial, sans-serif;">
                                <h2>Exam Duty Reminder</h2>
                                <p><strong>{message}</strong></p>
                                
                                <h3>Exam Details:</h3>
                                <ul>
                                    <li><strong>Subject:</strong> {exam.subject_name}</li>
                                    <li><strong>Hall:</strong> {exam.hall}</li>
                                    <li><strong>Time:</strong> {exam.start_time}</li>
                                    <li><strong>Date:</strong> {exam.exam_date}</li>
                                </ul>
                                
                                <p><strong>Reminder:</strong> Your exam duty starts in {interval}.</p>
                                
                                <p>Please ensure you arrive at least 15 minutes before the scheduled time.</p>
                                
                                <p>Best regards,<br>
                                <strong>Exam Duty System</strong></p>
                            </body>
                            </html>
                            """
                            
                            email_sent = self.send_email(faculty.email, subject, email_body)
                            if email_sent:
                                print(f"✅ Reminder email sent to {faculty.email}")
                            else:
                                print(f"❌ Reminder email failed for {faculty.email}")
                            
                            # Create in-app notification for reminder
                            notification = Notification(
                                faculty_id=faculty.id,
                                message=f"Reminder: Your exam duty for {exam.subject_name} starts in {interval}",
                                notification_type='warning'
                            )
                            db.session.add(notification)
                            db.session.commit()
                            
                            break  # Send only one reminder per duty per check
                
                print("[SUCCESS] Reminder check completed")
                print("[INFO] === REMINDER NOTIFICATIONS CHECK COMPLETE ===\n")
                
            except Exception as e:
                print(f"[ERROR] Error in send_reminder_notifications: {e}")
                import traceback
                traceback.print_exc()
    
    def start_reminder_scheduler(self):
        """Start the reminder scheduler in a separate thread"""
        def run_scheduler():
            print("[INFO] Starting reminder scheduler...")
            
            # Schedule reminder checks every minute
            schedule.every(1).minutes.do(self.send_reminder_notifications)
            
            # Also run once immediately on startup
            self.send_reminder_notifications()
            
            while True:
                try:
                    schedule.run_pending()
                    time.sleep(60)  # Check every minute
                except Exception as e:
                    print(f"[ERROR] Scheduler error: {e}")
                    time.sleep(60)  # Continue even if there's an error
        
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        print("[SUCCESS] Reminder scheduler started successfully")