# generate_report.py

import db
from datetime import date
import tkinter as tk
from tkinter import scrolledtext

def generate_course_report(course_id):
    """
    Generates a detailed attendance report for a given course on the current day,
    AND shows overall attendance info:
      - Total classes conducted so far for this course (based on staff attendance)
      - Each student's total attended classes and percentage.
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

            # 2. Get the attendance for that staff member for today
            cursor.execute("""
                SELECT hour, status 
                FROM attendance_staff 
                WHERE staff_id = %s AND date = %s 
                ORDER BY hour
            """, (staff_id, today))
            staff_attendance = cursor.fetchall()
            
            if staff_attendance:
                report_lines.append("Instructor Attendance (Today):")
                for record in staff_attendance:
                    report_lines.append(f"  - {record['hour']}: {record['status']}")
            else:
                report_lines.append("Instructor Attendance: Not Marked Today")
            
            report_lines.append("-" * 70)

            # --- OVERALL CLASS-DAY LOGIC (for percentages) ---
            # All distinct dates this staff has any attendance recorded = classes held
            cursor.execute("SELECT DISTINCT date FROM attendance_staff WHERE staff_id = %s", (staff_id,))
            class_dates_records = cursor.fetchall()
            class_dates = [record['date'] for record in class_dates_records]
            total_classes_held = len(class_dates)

            # Show total classes conducted so far
            report_lines.append("Overall Class Summary (Till Today):")
            if total_classes_held > 0:
                report_lines.append(f"  Total Classes Conducted: {total_classes_held}")
            else:
                report_lines.append("  No classes have been conducted yet.")
            report_lines.append("-" * 70)

            # 3. Find all students enrolled in the course
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

            # 4. For each student, check their daily status AND overall attendance
            present_today_count = 0
            for student in enrolled_students:
                reg_no = student['reg_no']

                # --- TODAY'S STATUS ---
                # Present today ONLY if there is an entry with NO exit yet
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

                # --- OVERALL ATTENDANCE (TOTAL CLASSES + TOTAL ATTENDED) ---
                overall_line_1 = "    Overall Attendance: N/A"
                overall_line_2 = ""
                if total_classes_held > 0 and class_dates:
                    # Build IN (...) placeholders for dates
                    date_placeholders = ','.join(['%s'] * len(class_dates))
                    query_params = [reg_no] + class_dates

                    cursor.execute(f"""
                        SELECT COUNT(DISTINCT date) AS attended_count
                        FROM attendance_students
                        WHERE reg_no = %s AND date IN ({date_placeholders})
                    """, query_params)

                    row = cursor.fetchone()
                    classes_attended = row['attended_count'] if row and row['attended_count'] is not None else 0
                    percentage = (classes_attended / total_classes_held) * 100 if total_classes_held > 0 else 0.0

                    # Line 1: raw counts
                    overall_line_1 = f"    Overall Attendance: {classes_attended} / {total_classes_held} classes"
                    # Line 2: percentage
                    overall_line_2 = f"    Percentage: {percentage:.2f}%"

                report_lines.append(f"  - {student['name']} ({reg_no}):")
                report_lines.append(f"    Today's Status: {daily_status}")
                report_lines.append(overall_line_1)
                if overall_line_2:
                    report_lines.append(overall_line_2)

            # Add summary for the day
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


class ReportApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Attendance Report Generator")
        self.root.geometry("700x650+400+100")
        
        top_frame = tk.Frame(self.root, pady=10)
        top_frame.pack(fill='x')

        tk.Label(top_frame, text="Course ID:", font=("Arial", 12)).pack(side='left', padx=(20, 10))
        self.course_id_entry = tk.Entry(top_frame, font=("Arial", 12), width=20)
        self.course_id_entry.pack(side='left', fill='x', expand=True)
        
        self.generate_btn = tk.Button(
            top_frame,
            text="Generate Report",
            font=("Arial", 12, "bold"),
            bg="#28a745",
            fg="white",
            command=self.display_report
        )
        self.generate_btn.pack(side='left', padx=(10, 20))

        text_frame = tk.Frame(self.root, padx=10, pady=5)
        text_frame.pack(fill='both', expand=True)

        self.report_text = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.WORD,
            font=("Courier New", 11),
            state='disabled'
        )
        self.report_text.pack(fill='both', expand=True)
        
    def display_report(self):
        course_id = self.course_id_entry.get().strip()
        if not course_id:
            report_content = "Please enter a Course ID to generate a report."
        else:
            report_content = generate_course_report(course_id)
        
        self.report_text.config(state='normal')
        self.report_text.delete('1.0', tk.END)
        self.report_text.insert(tk.INSERT, report_content)
        self.report_text.config(state='disabled')


if __name__ == "__main__":
    app_root = tk.Tk()
    app = ReportApp(app_root)
    app_root.mainloop()
