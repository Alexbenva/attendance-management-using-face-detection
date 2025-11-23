import tkinter as tk
from tkinter import messagebox
import db
import face_recognition
import numpy as np
import json
from datetime import date, datetime, timedelta

# --- Globals for caching face data ---
known_face_encodings_students = []
known_face_ids_students = []
known_face_encodings_staff = []
known_face_ids_staff = []

#region UI Helpers
def get_button(window, text, color, command, fg='white'):
    return tk.Button(window, text=text, bg=color, fg=fg, command=command,
                     font=('Arial', 14, 'bold'), relief=tk.FLAT, width=20, height=2)

def get_img_label(window):
    return tk.Label(window, bg='black')

def msg_box(title, description):
    messagebox.showinfo(title, description)
#endregion

#region Face Data Loading and Recognition
def load_known_faces():
    """Loads all student and staff face encodings from the database into memory."""
    global known_face_encodings_students, known_face_ids_students
    global known_face_encodings_staff, known_face_ids_staff
    
    conn = db.create_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cursor:
            # Load students
            cursor.execute("SELECT reg_no, face_encoding FROM students")
            students = cursor.fetchall()
            known_face_encodings_students = [
                np.array(json.loads(s['face_encoding'])) for s in students
            ]
            known_face_ids_students = [s['reg_no'] for s in students]
            print("Loaded", len(known_face_ids_students), "student faces.")
            
            # Load staff
            cursor.execute("SELECT staff_id, face_encoding FROM staff")
            staff = cursor.fetchall()
            known_face_encodings_staff = [
                np.array(json.loads(s['face_encoding'])) for s in staff
            ]
            known_face_ids_staff = [s['staff_id'] for s in staff]
            print("Loaded", len(known_face_ids_staff), "staff faces.")
    except Exception as e:
        print(f"Error loading faces: {e}")
    finally:
        if conn:
            conn.close()

def recognize(frame, user_type):
    """Recognizes a face in the frame and returns the corresponding ID."""
    face_locations = face_recognition.face_locations(frame)
    if not face_locations:
        return 'no_persons_found'
    
    face_encodings = face_recognition.face_encodings(frame, face_locations)
    
    if user_type == 'student':
        encodings_to_check, ids_to_check = (
            known_face_encodings_students,
            known_face_ids_students
        )
    else:
        encodings_to_check, ids_to_check = (
            known_face_encodings_staff,
            known_face_ids_staff
        )

    if not encodings_to_check:
        return 'unknown_person'
        
    matches = face_recognition.compare_faces(encodings_to_check, face_encodings[0])
    
    if True in matches:
        first_match_index = matches.index(True)
        return ids_to_check[first_match_index]
    else:
        return 'unknown_person'

def verify_face(frame, reg_no):
    """Verifies if the face in the frame matches the registered face for the given reg_no."""
    try:
        target_index = known_face_ids_students.index(reg_no)
        known_encoding = known_face_encodings_students[target_index]
    except ValueError:
        print(f"Verification Error: Register number '{reg_no}' not found.")
        return False

    face_locations = face_recognition.face_locations(frame)
    if not face_locations:
        print("Verification Error: No face detected in the frame to verify.")
        return False

    unknown_encoding = face_recognition.face_encodings(frame, face_locations)[0]
    matches = face_recognition.compare_faces([known_encoding], unknown_encoding, tolerance=0.5)
    
    return matches[0]
#endregion

#region Student Functions
def add_student(name, reg_no, department, encoding):
    conn = db.create_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO students (name, reg_no, department, face_encoding)
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(sql, (name, reg_no, department, json.dumps(encoding.tolist())))
        conn.commit()
        load_known_faces()
        return True
    except db.pymysql.err.IntegrityError:
        return False
    finally:
        if conn:
            conn.close()

def get_student_by_reg_no(reg_no):
    conn = db.create_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM students WHERE reg_no = %s", (reg_no,))
            return cursor.fetchone()
    finally:
        if conn:
            conn.close()

def get_all_students():
    """Fetches all registered students from the database."""
    conn = db.create_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT reg_no, name, department
                FROM students
                ORDER BY name
            """)
            return cursor.fetchall()
    except Exception as e:
        print(f"Error fetching all students: {e}")
        return []
    finally:
        if conn:
            conn.close()

def mark_student_entry(reg_no):
    """
    Mark a student's ENTRY.

    Rules:
      - Student can have multiple sessions per day.
      - At any moment, only ONE 'open' session is allowed (time_out IS NULL).
      - If an open session already exists for today, do NOT create another.

    Returns:
      (success: bool, message: str)
    """
    conn = db.create_connection()
    if not conn:
        return False, "DB Error"
    try:
        with conn.cursor() as cursor:
            today = date.today().strftime('%Y-%m-%d')

            # 1. Check if there is already an OPEN session for today
            cursor.execute("""
                SELECT id
                FROM attendance_students
                WHERE reg_no = %s AND date = %s AND time_out IS NULL
                ORDER BY time_in DESC
                LIMIT 1
            """, (reg_no, today))
            open_session = cursor.fetchone()

            if open_session:
                # Student already has an active entry without exit
                return False, "You have already marked ENTRY and haven't EXITED yet for today."

            # 2. Insert a new session for today
            now_time = datetime.now().strftime('%H:%M:%S')
            sql = """
                INSERT INTO attendance_students (reg_no, date, time_in, time_out)
                VALUES (%s, %s, %s, NULL)
            """
            cursor.execute(sql, (reg_no, today, now_time))

        conn.commit()
        return True, f"Entry marked at {now_time}."
    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"Error while marking entry: {e}"
    finally:
        if conn:
            conn.close()

def mark_student_exit(reg_no):
    """
    Mark a student's EXIT.

    Rules:
      - Exit is only allowed if there is an OPEN session for today (time_out IS NULL).
      - If no open session exists, exit is rejected.

    Returns:
      (success: bool, message: str)
    """
    conn = db.create_connection()
    if not conn:
        return False, "DB Error"
    try:
        with conn.cursor() as cursor:
            today = date.today().strftime('%Y-%m-%d')

            # 1. Find latest OPEN session for today
            cursor.execute("""
                SELECT id, time_in
                FROM attendance_students
                WHERE reg_no = %s AND date = %s AND time_out IS NULL
                ORDER BY time_in DESC
                LIMIT 1
            """, (reg_no, today))
            open_session = cursor.fetchone()

            if not open_session:
                # No active session to close
                return False, "No open entry found for today. You haven't entered (or already exited)."

            session_id = open_session['id']
            now_time = datetime.now().strftime('%H:%M:%S')

            # 2. Close this session by setting time_out
            sql = """
                UPDATE attendance_students
                SET time_out = %s
                WHERE id = %s
            """
            cursor.execute(sql, (now_time, session_id))

        conn.commit()
        return True, f"Exit marked at {now_time}."
    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"Error while marking exit: {e}"
    finally:
        if conn:
            conn.close()
#endregion

#region Staff Functions
def get_class_schedule():
    """
    Fetches the entire class schedule from the database, including the early
    entry grace period, and converts timedelta objects to time objects.
    """
    conn = db.create_connection()
    if not conn:
            return []
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT hour_name, start_time, end_time, entry_deadline, early_entry_minutes
                FROM class_schedule
                ORDER BY start_time
            """)
            schedule_data = cursor.fetchall()

            corrected_schedule = []
            for row in schedule_data:
                for key, value in row.items():
                    if isinstance(value, timedelta):
                        total_seconds = int(value.total_seconds())
                        hours, remainder = divmod(total_seconds, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        row[key] = datetime.strptime(
                            f"{hours:02}:{minutes:02}:{seconds:02}",
                            '%H:%M:%S'
                        ).time()
                corrected_schedule.append(row)
            
            return corrected_schedule

    except Exception as e:
        print(f"Error fetching class schedule: {e}")
        return []
    finally:
        if conn:
            conn.close()

def add_staff(name, staff_id, course_id, subject, encoding):
    conn = db.create_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO staff (name, staff_id, course_id, subject, face_encoding)
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (name, staff_id, course_id, subject, json.dumps(encoding.tolist())))
        conn.commit()
        load_known_faces()
        return True
    except db.pymysql.err.IntegrityError:
        return False
    finally:
        if conn:
            conn.close()

def get_staff_by_id(staff_id):
    conn = db.create_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM staff WHERE staff_id = %s", (staff_id,))
            return cursor.fetchone()
    finally:
        if conn:
            conn.close()
        
def mark_staff_entry(staff_id, hour):
    """Marks entry for a specific hour and sets status to 'Present'."""
    conn = db.create_connection()
    if not conn:
        return False, "DB Error"
    try:
        with conn.cursor() as cursor:
            today = date.today().strftime('%Y-%m-%d')
            now_time = datetime.now().strftime('%H:%M:%S')
            sql = """
                INSERT INTO attendance_staff (staff_id, date, hour, time_in, status)
                VALUES (%s, %s, %s, %s, 'Present')
            """
            cursor.execute(sql, (staff_id, today, hour, now_time))
        conn.commit()
        return True, f"Entry for {hour} marked."
    except db.pymysql.err.IntegrityError:
        return False, f"Already marked entry for {hour} today."
    finally:
        if conn:
            conn.close()

def mark_staff_exit(staff_id):
    conn = db.create_connection()
    if not conn:
        return False, "DB Error"
    try:
        with conn.cursor() as cursor:
            today = date.today().strftime('%Y-%m-%d')
            now_time = datetime.now().strftime('%H:%M:%S')
            sql = """
                UPDATE attendance_staff
                SET time_out = %s 
                WHERE staff_id = %s AND date = %s AND time_out IS NULL 
                ORDER BY time_in DESC LIMIT 1
            """
            rows_affected = cursor.execute(sql, (now_time, staff_id, today))
            if rows_affected > 0:
                conn.commit()
                return True, "Exit marked successfully."
            else:
                return False, "No open entry found for today."
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()
#endregion

# In util.py, add this new function
def verify_staff_face(frame, staff_id):
    """Verifies if the face in the frame matches the registered face for the given staff_id."""
    try:
        # Search in the global list of known staff faces
        target_index = known_face_ids_staff.index(staff_id)
        known_encoding = known_face_encodings_staff[target_index]
    except ValueError:
        # This happens if the manually entered staff_id doesn't exist
        print(f"Verification Error: Staff ID '{staff_id}' not found.")
        return False

    face_locations = face_recognition.face_locations(frame)
    if not face_locations:
        print("Verification Error: No face detected in the frame to verify.")
        return False

    # Compare the face in the camera with the known face for that staff ID
    unknown_encoding = face_recognition.face_encodings(frame, face_locations)[0]
    matches = face_recognition.compare_faces([known_encoding], unknown_encoding, tolerance=0.5)
    
    return matches[0]
