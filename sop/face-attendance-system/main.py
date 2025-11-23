"""
Face Attendance System - Main Application (V18 - Staff Verification + Embedded Report)
- Main menu to select between Student and Staff.
- Strict time-windowed attendance for staff.
- Confirmation and verification for both students and staff.
- Robust error handling for face detection during registration.
- Course-wise attendance report accessible from Staff Portal.
"""

import warnings
warnings.filterwarnings('ignore', category=UserWarning)

import tkinter as tk
from tkinter import messagebox, simpledialog, scrolledtext
from datetime import datetime, date
import cv2
from PIL import Image, ImageTk
import face_recognition
import util
from anti_spoof_test import test as liveness_test
from db import init_database
import db  # for report function


# --- Configuration ---
ENABLE_LIVENESS_CHECK = True


def generate_course_report(course_id):
    """
    Generates a detailed attendance report for a given course on the current day,
    AND shows overall attendance info:

      - Total classes conducted so far (each staff hour = one class)
      - For each student: number of class hours attended and percentage.

    A student gets attendance for a class hour only if they have at least one
    entry on that date AND their time_in is on/before the staff's time_out for
    that hour.
    """
    conn = db.create_connection()
    if not conn:
        return "Database Connection Error:\nCould not connect to the database."

    try:
        with conn.cursor() as cursor:
            today = date.today().strftime('%Y-%m-%d')
            report_lines = []
            
            report_lines.append("=" * 70)
            report_lines.append(f"ATTENDANCE REPORT FOR COURSE: {course_id.upper()}")
            report_lines.append(f"Date: {today}")
            report_lines.append("=" * 70)

            # 1. Find the staff member assigned to this course
            cursor.execute("SELECT name, staff_id FROM staff WHERE course_id = %s", (course_id,))
            staff_info = cursor.fetchone()
            
            if not staff_info:
                return f"Report Error:\nNo staff member found for Course ID '{course_id}'."

            staff_name = staff_info['name']
            staff_id = staff_info['staff_id']
            report_lines.append(f"Instructor: {staff_name} (ID: {staff_id})\n")

            # 2. Staff attendance for TODAY (per hour)
            cursor.execute("""
                SELECT hour, status 
                FROM attendance_staff 
                WHERE staff_id = %s AND date = %s 
                ORDER BY hour
            """, (staff_id, today))
            staff_attendance_today = cursor.fetchall()
            
            if staff_attendance_today:
                report_lines.append("Instructor Attendance (Today):")
                for record in staff_attendance_today:
                    report_lines.append(f"  - {record['hour']}: {record['status']}")
            else:
                report_lines.append("Instructor Attendance: Not Marked Today")
            
            report_lines.append("-" * 70)

            # 3. OVERALL CLASS COUNT (each hour = 1 class)
            cursor.execute("""
                SELECT COUNT(*) AS total_classes
                FROM attendance_staff
                WHERE staff_id = %s
            """, (staff_id,))
            total_classes_row = cursor.fetchone()
            total_classes_held = total_classes_row['total_classes'] if total_classes_row else 0

            report_lines.append("Overall Class Summary (Till Today):")
            if total_classes_held > 0:
                report_lines.append(f"  Total Classes Conducted: {total_classes_held}")
            else:
                report_lines.append("  No classes have been conducted yet.")
            report_lines.append("-" * 70)

            # 4. Enrolled students
            cursor.execute("""
                SELECT s.reg_no, s.name 
                FROM students s
                JOIN student_enrollment se ON s.reg_no = se.reg_no
                WHERE se.course_id = %s 
                ORDER BY s.name
            """, (course_id,))
            enrolled_students = cursor.fetchall()

            if not enrolled_students:
                report_lines.append("No students are enrolled in this course.")
                report_lines.append("=" * 70)
                return "\n".join(report_lines)
                
            report_lines.append("Student Attendance:")

            # 5. Per-student: today's status + overall (per class hour)
            present_today_count = 0
            for student in enrolled_students:
                reg_no = student['reg_no']

                # --- TODAY'S STATUS (present if any open session today) ---
                cursor.execute("""
                    SELECT time_in 
                    FROM attendance_students
                    WHERE reg_no = %s AND date = %s AND time_out IS NULL 
                """, (reg_no, today))
                student_today_attendance = cursor.fetchone()
                
                if student_today_attendance:
                    daily_status = "Present"
                    present_today_count += 1
                else:
                    daily_status = "Absent / Exited"

                # --- OVERALL ATTENDANCE (per class hour) ---
                overall_line_1 = "    Overall Attendance: N/A"
                overall_line_2 = ""
                if total_classes_held > 0:
                    # Count how many staff class-hours this student attended:
                    # We join on date, match student reg_no, and require that the
                    # student's time_in is <= staff's time_out for that hour.
                    cursor.execute("""
                        SELECT COUNT(DISTINCT t.date, t.hour) AS attended_count
                        FROM attendance_staff t
                        JOIN attendance_students s
                          ON s.date = t.date
                         AND s.reg_no = %s
                         AND (t.time_out IS NULL OR s.time_in <= t.time_out)
                        WHERE t.staff_id = %s
                    """, (reg_no, staff_id))

                    row = cursor.fetchone()
                    classes_attended = row['attended_count'] if row and row['attended_count'] is not None else 0
                    percentage = (classes_attended / total_classes_held) * 100 if total_classes_held > 0 else 0.0

                    overall_line_1 = f"    Overall Attendance: {classes_attended} / {total_classes_held} classes"
                    overall_line_2 = f"    Percentage: {percentage:.2f}%"

                report_lines.append(f"  - {student['name']} ({reg_no}):")
                report_lines.append(f"    Today's Status: {daily_status}")
                report_lines.append(overall_line_1)
                if overall_line_2:
                    report_lines.append(overall_line_2)

            # 6. Summary for today (current presence)
            total_students = len(enrolled_students)
            absent_today_count = total_students - present_today_count
            report_lines.append("\n" + "-" * 25)
            report_lines.append("Today's Summary:")
            report_lines.append(f"  Total Enrolled: {total_students}")
            report_lines.append(f"  Present (Currently): {present_today_count}")
            report_lines.append(f"  Absent / Exited:   {absent_today_count}")
            report_lines.append("=" * 70)
            
            return "\n".join(report_lines)

    except Exception as e:
        return f"An unexpected error occurred while generating the report:\n\n{e}"
    finally:
        if conn:
            conn.close()



class App:
    def __init__(self):
        self.win = tk.Tk()
        self.win.title("Face Attendance System")
        self.win.geometry("1200x560+100+50")
        
        util.load_known_faces()

        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            util.msg_box("Camera Error", "Could not open webcam.")
            self.win.destroy()
            return
        self.frame = None
        self.current_user_type = None
        self.widgets = {}
        self.captured_image = None
        
        self.setup_ui()
        self.update_cam()

    def setup_ui(self):
        self.cam_label = util.get_img_label(self.win)
        self.cam_label.place(x=10, y=10, width=700, height=520)

        self.feedback_label = tk.Label(
            self.win,
            text="Welcome!",
            font=('Arial', 18, 'bold'),
            justify='left',
            bg='black',
            fg='white',
            wraplength=450
        )
        self.feedback_label.place(x=730, y=20)
        
        status_text = "✓ Liveness Check: ENABLED" if ENABLE_LIVENESS_CHECK else "⚠️ Liveness Check: DISABLED"
        fg_color = "green" if ENABLE_LIVENESS_CHECK else "red"
        tk.Label(self.win, text=status_text, font=("Arial", 12), fg=fg_color).place(x=750, y=500)

        self.show_main_menu()

    def clear_widgets(self):
        for widget in self.widgets.values():
            widget.place_forget()
        self.widgets = {}

    def show_main_menu(self):
        self.clear_widgets()
        self.current_user_type = None
        self.clear_feedback()
        self.widgets['student_btn'] = util.get_button(self.win, "Student Portal", "#007BFF", self.show_student_ui)
        self.widgets['student_btn'].place(x=820, y=150)
        self.widgets['staff_btn'] = util.get_button(self.win, "Staff Portal", "#28a745", self.show_staff_ui)
        self.widgets['staff_btn'].place(x=820, y=250)
        self.widgets['logout_btn'] = util.get_button(self.win, "Exit Application", "red", self.logout)
        self.widgets['logout_btn'].place(x=820, y=350)
        
    def show_student_ui(self):
        self.clear_widgets()
        self.current_user_type = 'student'
        self.feedback_label.config(text="Student Portal")
        self.widgets['mark_entry_btn'] = util.get_button(self.win, "Mark Entry", "green", lambda: self.handle_attendance('entry'))
        self.widgets['mark_entry_btn'].place(x=750, y=100)
        self.widgets['mark_exit_btn'] = util.get_button(self.win, "Mark Exit", "orange", lambda: self.handle_attendance('exit'))
        self.widgets['mark_exit_btn'].place(x=970, y=100)
        self.widgets['register_btn'] = util.get_button(self.win, "Register New Student", "gray", self.register_student, fg="black")
        self.widgets['register_btn'].place(x=860, y=200)
        self.widgets['back_btn'] = util.get_button(self.win, "< Back to Main Menu", "blue", self.show_main_menu)
        self.widgets['back_btn'].place(x=860, y=350)

    def show_staff_ui(self):
        self.clear_widgets()
        self.current_user_type = 'staff'
        self.feedback_label.config(text="Staff Portal")
        self.widgets['mark_entry_btn'] = util.get_button(self.win, "Mark Attendance", "green", lambda: self.handle_attendance('entry'))
        self.widgets['mark_entry_btn'].place(x=750, y=100)
        self.widgets['mark_exit_btn'] = util.get_button(self.win, "Mark Exit", "orange", lambda: self.handle_attendance('exit'))
        self.widgets['mark_exit_btn'].place(x=970, y=100)
        self.widgets['register_btn'] = util.get_button(self.win, "Register New Staff", "gray", self.register_staff, fg="black")
        self.widgets['register_btn'].place(x=860, y=200)
        self.widgets['view_students_btn'] = util.get_button(self.win, "View Students", "#17a2b8", self.show_all_students)
        self.widgets['view_students_btn'].place(x=860, y=260)
        self.widgets['report_btn'] = util.get_button(self.win, "Course Report", "#6f42c1", self.open_report_window)
        self.widgets['report_btn'].place(x=860, y=320)
        self.widgets['back_btn'] = util.get_button(self.win, "< Back to Main Menu", "blue", self.show_main_menu)
        self.widgets['back_btn'].place(x=860, y=380)

    def show_all_students(self):
        students = util.get_all_students()
        if not students:
            util.msg_box("Student Roster", "No students have been registered yet.")
            return
        header = f"{'Reg No':<15} | {'Name':<25} | {'Department'}\n"
        separator = "-" * 65 + "\n"
        student_rows = [f"{s['reg_no']:<15} | {s['name']:<25} | {s['department']}" for s in students]
        display_string = header + separator + "\n".join(student_rows)
        util.msg_box("Registered Students List", display_string)

    def open_report_window(self):
        """Opens a window for staff to generate course-wise attendance report."""
        report_win = tk.Toplevel(self.win)
        report_win.title("Course Attendance Report")
        report_win.geometry("750x650+420+80")

        # Top frame: Course ID entry + button
        top_frame = tk.Frame(report_win, pady=10)
        top_frame.pack(fill='x')

        tk.Label(top_frame, text="Course ID:", font=("Arial", 12)).pack(side='left', padx=(20, 10))
        course_entry = tk.Entry(top_frame, font=("Arial", 12), width=20)
        course_entry.pack(side='left', fill='x', expand=True)

        text_frame = tk.Frame(report_win, padx=10, pady=5)
        text_frame.pack(fill='both', expand=True)

        report_text = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.WORD,
            font=("Courier New", 11),
            state='disabled'
        )
        report_text.pack(fill='both', expand=True)

        def do_generate():
            course_id = course_entry.get().strip()
            if not course_id:
                report_content = "Please enter a Course ID to generate a report."
            else:
                report_content = generate_course_report(course_id)

            report_text.config(state='normal')
            report_text.delete('1.0', tk.END)
            report_text.insert(tk.INSERT, report_content)
            report_text.config(state='disabled')

        generate_btn = tk.Button(
            top_frame,
            text="Generate Report",
            font=("Arial", 12, "bold"),
            bg="#28a745",
            fg="white",
            command=do_generate
        )
        generate_btn.pack(side='left', padx=(10, 20))

    def prompt_for_staff_hours(self, staff_id, staff_name):
        dialog = tk.Toplevel(self.win)
        dialog.title("Select Hours")
        dialog.geometry("400x500+500+200")
        dialog.resizable(False, False)
        dialog.grab_set()

        tk.Label(dialog, text=f"Marking for: {staff_name}", font=("Arial", 12, "bold")).pack(pady=10)
        tk.Label(dialog, text="Please select the hour(s) for this class.", font=("Arial", 10)).pack()

        schedule = util.get_class_schedule()
        if not schedule:
            util.msg_box("Error", "Could not load class schedule.")
            dialog.destroy()
            return
        hours_to_display = [item['hour_name'] for item in schedule]
        hour_vars = {}

        main_frame = tk.Frame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=1, pady=10)

        my_canvas = tk.Canvas(main_frame)
        my_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=1)

        scrollbar = tk.Scrollbar(main_frame, orient=tk.VERTICAL, command=my_canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        my_canvas.configure(yscrollcommand=scrollbar.set)
        my_canvas.bind('<Configure>', lambda e: my_canvas.configure(scrollregion=my_canvas.bbox("all")))

        checkbox_frame = tk.Frame(my_canvas)
        my_canvas.create_window((0, 0), window=checkbox_frame, anchor="nw")

        def validate_selection():
            is_any_selected = any(var.get() for var in hour_vars.values())
            submit_btn.config(
                state='normal' if is_any_selected else 'disabled',
                bg='green' if is_any_selected else 'grey'
            )

        for hour in hours_to_display:
            var = tk.StringVar(value="")
            cb = tk.Checkbutton(
                checkbox_frame,
                text=hour,
                variable=var,
                onvalue=hour,
                offvalue="",
                font=("Arial", 12),
                command=validate_selection
            )
            cb.pack(anchor='w', padx=120, pady=2)
            hour_vars[hour] = var

        def on_submit():
            selected_hours = [var.get() for var in hour_vars.values() if var.get()]
            dialog.destroy()
            success_msgs, fail_msgs = [], []
            for hour in selected_hours:
                success, message = util.mark_staff_entry(staff_id, hour)
                if success:
                    success_msgs.append(f"✓ {hour} marked successfully.")
                else:
                    fail_msgs.append(f"✗ {hour} (Already marked).")

            final_message = f"Report for {staff_name}:\n" + "\n".join(success_msgs) + "\n" + "\n".join(fail_msgs)
            final_color = "green" if success_msgs else "red"
            self.feedback_label.config(text=final_message.strip(), fg=final_color)
            self.win.after(5000, self.clear_feedback)

        submit_btn = tk.Button(
            dialog,
            text="Submit",
            command=on_submit,
            font=("Arial", 12, "bold"),
            bg="grey",
            fg="white",
            width=15,
            state='disabled'
        )
        submit_btn.pack(pady=20)
        self.win.wait_window(dialog)

    def handle_attendance(self, attendance_type):
        if ENABLE_LIVENESS_CHECK:
            live, recognition_frame = liveness_test(camera_object=self.cap, ui_feedback_label=self.feedback_label)
            if live != 1:
                self.win.after(2000, self.clear_feedback)
                return
        else:
            self.feedback_label.config(text="Liveness check disabled.", fg="orange")
            self.win.update_idletasks()
            recognition_frame = self.frame.copy()

        self.feedback_label.config(text="Recognizing face...", fg="cyan")
        self.win.update_idletasks()
        user_id = util.recognize(recognition_frame, self.current_user_type)

        if user_id in ['no_persons_found', 'unknown_person']:
            result_text = "No face found." if user_id == 'no_persons_found' else f"Unknown {self.current_user_type}."
            self.feedback_label.config(text=result_text, fg="red")
            self.win.after(3000, self.clear_feedback)
            return

        if self.current_user_type == 'student':
            student = util.get_student_by_reg_no(user_id)
            if not student:
                self.feedback_label.config(text=f"Error: Student data not found for {user_id}.", fg="red")
                self.win.after(3000, self.clear_feedback)
                return
            
            confirm = messagebox.askyesno(
                "Confirm Identity",
                f"Are you {student['name']} ({student['reg_no']})?",
                parent=self.win
            )
            if confirm:
                self.mark_student_attendance(user_id, attendance_type, student['name'])
            else:
                self.handle_misidentification(recognition_frame, attendance_type)
        
        else:  # staff
            user_data = util.get_staff_by_id(user_id)
            if not user_data:
                self.feedback_label.config(text=f"Error: Staff data not found for {user_id}.", fg="red")
                self.win.after(3000, self.clear_feedback)
                return

            confirm = messagebox.askyesno(
                "Confirm Identity",
                f"Are you {user_data['name']} ({user_data['staff_id']})?",
                parent=self.win
            )
            if confirm:
                self.mark_staff_attendance(user_id, attendance_type, user_data['name'])
            else:
                self.handle_staff_misidentification(recognition_frame, attendance_type)

    def mark_student_attendance(self, reg_no, attendance_type, name):
        greeting = "Welcome" if attendance_type == 'entry' else "Goodbye"
        if attendance_type == 'entry':
            success, message = util.mark_student_entry(reg_no)
        else:
            success, message = util.mark_student_exit(reg_no)

        color = "green" if success else "orange"
        final_message = f"{message}\n{greeting}, {name}!" if success else f"Notice: {message}"
        self.feedback_label.config(text=final_message, fg=color)
        self.win.after(4000, self.clear_feedback)

    def mark_staff_attendance(self, staff_id, attendance_type, name):
        """Helper function to process staff attendance after confirmation."""
        if attendance_type == 'entry':
            self.prompt_for_staff_hours(staff_id, name)
        else:  # exit
            success, message = util.mark_staff_exit(staff_id)
            color = "green" if success else "red"
            final_message = f"{message}\nGoodbye, {name}!" if success else f"Failed: {message}"
            self.feedback_label.config(text=final_message, fg=color)
            self.win.after(3000, self.clear_feedback)

    def handle_misidentification(self, frame, attendance_type):
        """Handles the workflow when initial student face recognition is incorrect."""
        manual_reg_no = simpledialog.askstring(
            "Incorrect Identification",
            "Please enter your correct Register Number:",
            parent=self.win
        )
        if not manual_reg_no:
            self.feedback_label.config(text="Correction cancelled.", fg="orange")
            self.win.after(2000, self.clear_feedback)
            return

        manual_reg_no = manual_reg_no.strip()
        self.feedback_label.config(text=f"Verifying face for\n{manual_reg_no}...", fg="cyan")
        self.win.update_idletasks()

        if util.verify_face(frame, manual_reg_no):
            self.feedback_label.config(text="Verification Success!", fg="green")
            self.win.update_idletasks()
            student = util.get_student_by_reg_no(manual_reg_no)
            if student:
                self.mark_student_attendance(manual_reg_no, attendance_type, student['name'])
            else:
                self.feedback_label.config(text="Error: Student data not found.", fg="red")
                self.win.after(3000, self.clear_feedback)
        else:
            self.feedback_label.config(
                text="Verification FAILED.\nFace does not match Reg No.",
                fg="red"
            )
            self.win.after(3000, self.clear_feedback)

    def handle_staff_misidentification(self, frame, attendance_type):
        manual_staff_id = simpledialog.askstring(
            "Incorrect Identification",
            "Please enter your correct Staff ID:",
            parent=self.win
        )
        if not manual_staff_id:
            self.feedback_label.config(text="Correction cancelled.", fg="orange")
            self.win.after(2000, self.clear_feedback)
            return

        manual_staff_id = manual_staff_id.strip()
        self.feedback_label.config(text=f"Verifying face for\n{manual_staff_id}...", fg="cyan")
        self.win.update_idletasks()

        if util.verify_staff_face(frame, manual_staff_id):
            self.feedback_label.config(text="Verification Success!", fg="green")
            self.win.update_idletasks()
            staff = util.get_staff_by_id(manual_staff_id)
            if staff:
                self.mark_staff_attendance(manual_staff_id, attendance_type, staff['name'])
            else:
                self.feedback_label.config(text="Error: Staff data not found.", fg="red")
                self.win.after(3000, self.clear_feedback)
        else:
            self.feedback_label.config(
                text="Verification FAILED.\nFace does not match Staff ID.",
                fg="red"
            )
            self.win.after(3000, self.clear_feedback)

    def register_student(self):
        self.reg_win = tk.Toplevel(self.win)
        self.reg_win.title("Register New Student")
        self.reg_win.geometry("600x400+370+120")

        tk.Label(self.reg_win, text="Name:", font=("sans-serif", 14)).place(x=330, y=30)
        self.name_e = tk.Entry(self.reg_win, font=("Arial", 16))
        self.name_e.place(x=330, y=60, width=220)

        tk.Label(self.reg_win, text="Reg No:", font=("sans-serif", 14)).place(x=330, y=110)
        self.regno_e = tk.Entry(self.reg_win, font=("Arial", 16))
        self.regno_e.place(x=330, y=140, width=220)

        tk.Label(self.reg_win, text="Department:", font=("sans-serif", 14)).place(x=330, y=190)
        self.dept_e = tk.Entry(self.reg_win, font=("Arial", 16))
        self.dept_e.place(x=330, y=220, width=220)

        self.prev_lbl = util.get_img_label(self.reg_win)
        self.prev_lbl.place(x=10, y=10, width=300, height=300)

        util.get_button(self.reg_win, "Capture & Save", "green", self.save_student).place(x=350, y=300)
        self.update_preview()

    def register_staff(self):
        self.reg_win = tk.Toplevel(self.win)
        self.reg_win.title("Register New Staff")
        self.reg_win.geometry("600x450+370+120")

        tk.Label(self.reg_win, text="Name:", font=("sans-serif", 14)).place(x=330, y=30)
        self.name_e = tk.Entry(self.reg_win, font=("Arial", 16))
        self.name_e.place(x=330, y=60, width=220)

        tk.Label(self.reg_win, text="Staff ID:", font=("sans-serif", 14)).place(x=330, y=110)
        self.staffid_e = tk.Entry(self.reg_win, font=("Arial", 16))
        self.staffid_e.place(x=330, y=140, width=220)

        tk.Label(self.reg_win, text="Course ID:", font=("sans-serif", 14)).place(x=330, y=190)
        self.courseid_e = tk.Entry(self.reg_win, font=("Arial", 16))
        self.courseid_e.place(x=330, y=220, width=220)

        tk.Label(self.reg_win, text="Subject:", font=("sans-serif", 14)).place(x=330, y=270)
        self.subject_e = tk.Entry(self.reg_win, font=("Arial", 16))
        self.subject_e.place(x=330, y=300, width=220)

        self.prev_lbl = util.get_img_label(self.reg_win)
        self.prev_lbl.place(x=10, y=10, width=300, height=300)

        util.get_button(self.reg_win, "Capture & Save", "green", self.save_staff).place(x=350, y=350)
        self.update_preview()
        
    def save_student(self):
        name = self.name_e.get().strip()
        reg = self.regno_e.get().strip()
        dept = self.dept_e.get().strip()
        if not (name and reg):
            util.msg_box("Error", "Please fill in both Name and Reg No fields.")
            return
        if self.captured_image is None:
            util.msg_box("Error", "Could not capture an image.")
            return
        encodings = face_recognition.face_encodings(self.captured_image)
        if not encodings:
            util.msg_box("Face Detection Failed", "Could not detect a face in the image. Please try again.")
            return
        if util.add_student(name, reg, dept, encodings[0]):
            util.msg_box("Success", f"✓ {name} ({reg}) registered successfully!")
            self.reg_win.destroy()
        else:
            util.msg_box("Error", "Registration number may already exist.")
        
    def save_staff(self):
        name = self.name_e.get().strip()
        staff_id = self.staffid_e.get().strip()
        course = self.courseid_e.get().strip()
        subject = self.subject_e.get().strip()
        if not (name and staff_id):
            util.msg_box("Error", "Please fill in both the Name and Staff ID fields.")
            return
        if self.captured_image is None:
            util.msg_box("Error", "Could not capture an image from the camera.")
            return
        encodings = face_recognition.face_encodings(self.captured_image)
        if not encodings:
            util.msg_box(
                "Face Detection Failed",
                "Could not detect a face in the image.\n\nPlease ensure your face is centered and well-lit."
            )
            return
        if util.add_staff(name, staff_id, course, subject, encodings[0]):
            util.msg_box("Success", f"✓ {name} ({staff_id}) registered successfully!")
            self.reg_win.destroy()
        else:
            util.msg_box("Error", "Failed to register.\nStaff ID may already exist.")

    def update_preview(self):
        if not hasattr(self, 'reg_win') or not self.reg_win.winfo_exists():
            return
        if self.frame is not None:
            self.captured_image = self.frame.copy()
            rgb = cv2.cvtColor(self.captured_image, cv2.COLOR_BGR2RGB)
            imgtk = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.prev_lbl.imgtk = imgtk
            self.prev_lbl.configure(image=imgtk)
        self.prev_lbl.after(20, self.update_preview)

    def update_cam(self):
        ret, frame = self.cap.read()
        if ret:
            self.frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
            imgtk = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.cam_label.imgtk = imgtk
            self.cam_label.configure(image=imgtk)
        self.update_cam_job = self.cam_label.after(10, self.update_cam)

    def clear_feedback(self):
        default_text = "Welcome! Please select a portal."
        if self.current_user_type == 'student':
            default_text = "Student Portal"
        elif self.current_user_type == 'staff':
            default_text = "Staff Portal"
        self.feedback_label.config(text=default_text, fg="white")

    def logout(self):
        if hasattr(self, 'update_cam_job') and self.update_cam_job:
            self.cam_label.after_cancel(self.update_cam_job)
        self.cap.release()
        self.win.destroy()

    def start(self):
        self.win.protocol("WM_DELETE_WINDOW", self.logout)
        self.win.mainloop()


if __name__ == "__main__":
    if init_database():
        app = App()
        app.start()
    else:
        print("DATABASE INITIALIZATION FAILED!")
        input("Press Enter to exit...")
