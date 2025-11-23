"""
Daily cleanup script for Face Attendance System.

- For STAFF:
    If they did not mark EXIT (time_out IS NULL) by end of the day,
    their status is set to 'Absent' for that hour.

- For STUDENTS:
    Any attendance record where time_out IS NULL at the end of the day
    is treated as invalid / incomplete and is DELETED.

    Thanks to the MySQL trigger (trg_attendance_students_after_delete),
    deleted student records are archived into the
    'attendance_students_deleted' table automatically.

Run this script once per day AFTER all classes are finished
(e.g., after Hour 8), either manually:

    python daily_cleanup.py

or via a scheduler (Task Scheduler / cron).
"""

from datetime import date
import db  # uses your existing db.py


def cleanup_staff_open_sessions():
    """
    STAFF CLEANUP:
    For today's records in attendance_staff where time_out IS NULL,
    update status to 'Absent'.
    """
    conn = db.create_connection()
    if not conn:
        print("❌ Failed to connect to DB for staff cleanup.")
        return

    try:
        today = date.today().strftime("%Y-%m-%d")
        with conn.cursor() as cursor:
            sql = """
                UPDATE attendance_staff
                SET status = 'Absent'
                WHERE date = %s AND time_out IS NULL;
            """
            rows_affected = cursor.execute(sql, (today,))
            conn.commit()
            print(f"✅ Staff cleanup done. Rows updated: {rows_affected}")
    except Exception as e:
        print(f"❌ Error during staff cleanup: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def cleanup_student_open_sessions():
    """
    STUDENT CLEANUP:
    For today's records in attendance_students where time_out IS NULL,
    delete those rows.

    This means:
      - During the day, you can see everyone who scanned ENTRY.
      - After cleanup, only students who properly stayed and/or exited remain.
      - In reports, students whose rows were deleted are treated as ABSENT
        (because they have no row for that date).

    NOTE: The MySQL trigger 'trg_attendance_students_after_delete' will
    automatically copy deleted rows into 'attendance_students_deleted'
    for history / audit.
    """
    conn = db.create_connection()
    if not conn:
        print("❌ Failed to connect to DB for student cleanup.")
        return

    try:
        today = date.today().strftime("%Y-%m-%d")
        with conn.cursor() as cursor:
            sql = """
                DELETE FROM attendance_students
                WHERE date = %s AND time_out IS NULL;
            """
            rows_affected = cursor.execute(sql, (today,))
            conn.commit()
            print(f"✅ Student cleanup done. Rows deleted: {rows_affected}")
    except Exception as e:
        print(f"❌ Error during student cleanup: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def run_daily_cleanup():
    print("=== Running daily cleanup ===")
    cleanup_staff_open_sessions()
    cleanup_student_open_sessions()
    print("=== Cleanup finished ===")


if __name__ == "__main__":
    run_daily_cleanup()
