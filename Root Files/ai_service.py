try:
    from transformers import pipeline
    TRANSFORMERS_AVAILABLE = True
except:
    TRANSFORMERS_AVAILABLE = False
    
import numpy as np
from sqlalchemy import or_, and_
from models import Faculty, Exam, ExamDuty, Timetable
from models import db, Faculty, Exam, ExamDuty, Timetable
from collections import defaultdict
from datetime import datetime, timedelta

class AIAssignmentService:
    def __init__(self):
        # Load AI model for text analysis if available
        self.nlp = None
        if TRANSFORMERS_AVAILABLE:
            try:
                self.nlp = pipeline("text-classification", model="distilbert-base-uncased")
            except:
                pass
    
    def analyze_faculty_expertise(self, faculty, exam):
        """Use NLP to analyze how well a faculty's expertise matches an exam subject"""
        if self.nlp:
            try:
                text = f"{faculty.department} {faculty.name} {exam.subject_name}"
                result = self.nlp(text)[0]
                return result['score']
            except:
                pass
        return 0.5 # Default
    
    def get_workload_score(self, faculty):
        """Calculate faculty workload score"""
        # Exclude declined duties from workload calculation
        current_duties = ExamDuty.query.filter(
            ExamDuty.faculty_id == faculty.id,
            ExamDuty.status != 'Declined'
        ).count()
        
        max_duties = faculty.max_duties if hasattr(faculty, 'max_duties') and faculty.max_duties else 5
        
        # If already at max, return 0
        if current_duties >= max_duties:
            return 0.0
            
        return 1.0 - (current_duties / max_duties)
    
    def check_schedule_conflicts(self, faculty, exam):
                # Using a feature extraction model might be more suitable for similarity than classification
                self.nlp = pipeline("feature-extraction", model="distilbert-base-uncased")
            except Exception as e:
                print(f"Could not load NLP model: {e}")
                self.nlp = None

    def _calculate_faculty_score(self, faculty_info, exam, existing_assignments_today, config):
        """Calculate score for a faculty member for a specific exam based on rules"""
        score = 100  # Base score

        # Rule: Ensure faculty doesn't exceed max duties
        if faculty_info['duty_count'] >= faculty_info['max_allowed']:
            return -1  # Disqualify

        # Rule: Workload balancing (higher score for less loaded faculty)
        if config.get('balance_workload', True):
            workload_penalty = faculty_info['duty_count'] * 10
            score -= workload_penalty

        # Rule: Department matching
        if config.get('prefer_same_department', True):
            if faculty_info['department'] == exam.department:
                score += 20
            else:
                score -= 10 # Minor penalty for cross-department assignment

        # Rule: Avoid consecutive days
        if config.get('avoid_consecutive_days', True):
            yesterday = exam.exam_date - timedelta(days=1)
            tomorrow = exam.exam_date + timedelta(days=1)
            if yesterday in faculty_info['duty_by_date'] or tomorrow in faculty_info['duty_by_date']:
                score -= 15

        # Rule: Avoid too many duties on same day
        duties_today = len(faculty_info['duty_by_date'].get(exam.exam_date, [])) + existing_assignments_today
        if duties_today >= config.get('max_duties_per_day', 2):
            return -1  # Disqualify

        # Rule: Check for time conflicts with other EXAM duties
        if config.get('consider_time_conflicts', True):
            for duty in faculty_info['duty_by_date'].get(exam.exam_date, []):
                if duty and duty.exam:
                    existing_start = datetime.combine(duty.exam.exam_date, duty.exam.start_time)
                    existing_end = datetime.combine(duty.exam.exam_date, duty.exam.end_time)
                    new_start = datetime.combine(exam.exam_date, exam.start_time)
                    new_end = datetime.combine(exam.exam_date, exam.end_time)

                    # Check for overlap
                    if not (new_end <= existing_start or new_start >= existing_end):
                        return -1  # Disqualify for direct time conflict

                    # Check minimum break
                    min_break = config.get('min_break_between_duties', timedelta(hours=2))
                    time_between = abs((new_start - existing_end).total_seconds())
                    if 0 < time_between < min_break.total_seconds():
                        score -= 30

        # Rule: Check for Timetable conflicts (Regular Classes)
        if config.get('consider_time_conflicts', True):
            day_name = exam.exam_date.strftime('%A')
            timetable_conflicts = Timetable.query.filter_by(
                faculty_id=faculty_info['faculty'].id,
                day_of_week=day_name
            ).filter(
                or_(
                    and_(Timetable.start_time >= exam.start_time, Timetable.start_time < exam.end_time),
                    and_(Timetable.end_time > exam.start_time, Timetable.end_time <= exam.end_time),
                    and_(Timetable.start_time <= exam.start_time, Timetable.end_time >= exam.end_time)
                )
            ).count()
            if timetable_conflicts > 0:
                return -1 # Disqualify for class conflict

        # Rule: Prefer experienced faculty
        if config.get('prefer_experienced_faculty', False):
            experience_bonus = min(faculty_info['duty_count'] * 2, 20)
            score += experience_bonus

        # Rule: Penalize faculty who frequently decline duties
        decline_ratio = (faculty_info['total_duty_count'] - faculty_info['duty_count']) / max(faculty_info['total_duty_count'], 1)
        if decline_ratio > 0.5:
            score -= 25

        return max(score, 0)

    def run_rule_based_assignment(self, department, config):
        """
        Check for schedule conflicts with:
        1. Existing Exam Duties (same day)
        2. Regular Class Timetable (overlapping time)
        3. Maximum Duties Limit
        Runs the rule-based assignment algorithm.
        Returns lists of assignments to create, details for reports, and failed assignments.
        """
        max_duties = faculty.max_duties if hasattr(faculty, 'max_duties') and faculty.max_duties else 5
        
        # 1. Check Maximum Duties (excluding declined)
        current_duties_count = ExamDuty.query.filter(
            ExamDuty.faculty_id == faculty.id,
            ExamDuty.status != 'Declined'
        ).count()
        
        if current_duties_count >= max_duties:
            return True # Conflict: Max duties reached
        # Get unassigned exams
        query = Exam.query.outerjoin(ExamDuty, Exam.id == ExamDuty.exam_id).filter(ExamDuty.id.is_(None))
        if department and department != 'all':
            query = query.filter(Exam.department == department)
        unassigned_exams = query.order_by(Exam.exam_date.asc(), Exam.start_time.asc()).all()

        # 2. Check Existing Exam Duties on the same day
        # Join with Exam table to get the date, and exclude declined duties
        existing_duties = ExamDuty.query.join(Exam).filter(
            ExamDuty.faculty_id == faculty.id,
            Exam.exam_date == exam.exam_date,
            ExamDuty.status != 'Declined'
        ).all()
        
        if len(existing_duties) > 0:
            return True 
        if not unassigned_exams:
            return [], [], [], {'message': 'No unassigned exams found.'}

        # 3. Check Timetable (Class Schedule)
        day_name = exam.exam_date.strftime('%A')
        
        timetable_conflicts = Timetable.query.filter_by(
            faculty_id=faculty.id,
            day_of_week=day_name
        ).filter(
            or_(
                and_(Timetable.start_time >= exam.start_time, Timetable.start_time < exam.end_time),
                and_(Timetable.end_time > exam.start_time, Timetable.end_time <= exam.end_time),
                and_(Timetable.start_time <= exam.start_time, Timetable.end_time >= exam.end_time)
            )
        ).count()
        
        if timetable_conflicts > 0:
            return True
        # Get all faculty
        faculty_query = Faculty.query
        if department and department != 'all':
            faculty_query = faculty_query.filter_by(department=department)
        all_faculty = faculty_query.all()

        return False
        
    def auto_assign_duties(self, faculties, exams, mode='balanced'):
        """Auto-assign duties using AI analysis"""
        assignments = []
        insights = []
        
        # Track assignments temporarily to respect limits within this batch
        # Initialize with current active duty counts
        temp_duty_counts = {}
        for f in faculties:
            count = ExamDuty.query.filter(
                ExamDuty.faculty_id == f.id, 
                ExamDuty.status != 'Declined'
            ).count()
            temp_duty_counts[f.id] = count
        
        for exam in exams:
            best_faculty = None
            best_score = -1
        if not all_faculty:
            return [], [], [], {'message': 'No faculty found to assign duties to.'}

        # Pre-process faculty data
        faculty_data = []
        for faculty in all_faculty:
            duties = ExamDuty.query.filter_by(faculty_id=faculty.id).all()
            accepted_duties = [d for d in duties if d.status == 'Accepted' and d.exam is not None]
            max_allowed = faculty.max_duties if hasattr(faculty, 'max_duties') and faculty.max_duties else config.get('max_duties_default', 5)
            
            for faculty in faculties:
                # Check Max Duties (including temp assignments)
                max_duties = faculty.max_duties if hasattr(faculty, 'max_duties') and faculty.max_duties else 5
                if temp_duty_counts[faculty.id] >= max_duties:
                    continue
            duty_by_date = defaultdict(list)
            for duty in accepted_duties:
                duty_by_date[duty.exam.exam_date].append(duty)

                # Check schedule conflicts (Database Only)
                if self.check_schedule_conflicts(faculty, exam):
                    continue
            faculty_data.append({
                'faculty': faculty,
                'duty_count': len(accepted_duties),
                'total_duty_count': len(duties),
                'max_allowed': max_allowed,
                'duty_by_date': duty_by_date,
                'department': faculty.department,
            })

        # Assignment process
        assignments_to_create = []
        assignment_details = []
        failed_assignments = []
        temp_assignments = defaultdict(lambda: defaultdict(int))  # faculty_id -> date -> count

        for exam in exams:
            suitable_faculty = []
            for f_info in faculty_data:
                # Check against temp assignments for the day
                existing_today = temp_assignments[f_info['faculty'].id].get(exam.exam_date, 0)
                
                # Calculate scores
                expertise_score = self.analyze_faculty_expertise(faculty, exam)
                
                # Calculate workload score using temp counts
                workload_score = 1.0 - (temp_duty_counts[faculty.id] / max_duties)
                    
                # Calculate combined score based on mode
                if mode == "expertise":
                    score = expertise_score
                elif mode == "balanced":
                    score = 0.4 * expertise_score + 0.6 * workload_score
                else:  # optimal
                    score = 0.6 * expertise_score + 0.4 * workload_score
                
                if score > best_score:
                    best_score = score
                    best_faculty = faculty
                score = self._calculate_faculty_score(f_info, exam, existing_today, config)
                if score >= 0:
                    suitable_faculty.append({'faculty_info': f_info, 'score': score})

            if not suitable_faculty:
                failed_assignments.append({'exam': exam.subject_name, 'date': str(exam.exam_date), 'reason': 'No suitable faculty available based on rules.'})
                continue

            # Select the best faculty
            suitable_faculty.sort(key=lambda x: x['score'], reverse=True)
            selected = suitable_faculty[0]
            faculty_info = selected['faculty_info']
            faculty = faculty_info['faculty']

            # Add to assignments list
            assignments_to_create.append({'faculty_id': faculty.id, 'exam_id': exam.id})
            
            if best_faculty:
                assignments.append({
                    'faculty': best_faculty,
                    'exam': exam,
                    'score': best_score
                })
                # Increment temp count
                temp_duty_counts[best_faculty.id] += 1
                
                insights.append(
                    f"Assigned {exam.subject_name} to {best_faculty.name} "
                    f"(Match Score: {best_score:.2f})"
                )
            else:
                insights.append(f"Could not assign {exam.subject_name} - No suitable faculty found.")
        
        return assignments, insights
            # Record details for report
            assignment_details.append({
                'faculty_name': faculty.name, 'faculty_email': faculty.email,
                'exam_name': exam.subject_name, 'exam_code': exam.subject_code,
                'exam_date': str(exam.exam_date), 'exam_time': f"{exam.start_time} - {exam.end_time}",
                'hall': exam.hall, 'department': exam.department,
                'assignment_score': selected['score'],
                'faculty_current_duties': faculty_info['duty_count'] + 1,
                'faculty_max_duties': faculty_info['max_allowed']
            })

            # Update faculty_info and temp_assignments for next iteration
            faculty_info['duty_count'] += 1
            # Create a dummy duty object to represent the new assignment for conflict checking
            dummy_duty = ExamDuty(exam=exam)
            faculty_info['duty_by_date'][exam.exam_date].append(dummy_duty)
            temp_assignments[faculty.id][exam.exam_date] += 1

        stats = {
            'total_assignments': len(assignments_to_create),
            'failed_assignments': len(failed_assignments),
            'average_score': sum(d['assignment_score'] for d in assignment_details) / len(assignment_details) if assignment_details else 0,
        }

        return assignments_to_create, assignment_details, failed_assignments, stats