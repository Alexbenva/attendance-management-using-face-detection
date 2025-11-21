import db
from datetime import date

def enforce_absence_rule():
    """
    Finds all staff attendance records for today that have no 'time_out'
    and updates their status to 'Absent'.
    """
    conn = db.create_connection()
    if not conn:
        print("Could not connect to the database.")
        return

    try:
        with conn.cursor() as cursor:
            today = date.today().strftime('%Y-%m-%d')
            
            sql = """
                UPDATE attendance_staff
                SET status = 'Absent'
                WHERE date = %s AND time_out IS NULL;
            """
            
            rows_affected = cursor.execute(sql, (today,))
            conn.commit()
            
            print(f"Daily cleanup complete. Marked {rows_affected} record(s) as 'Absent'.")

    except Exception as e:
        print(f"An error occurred during cleanup: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    print("Running the daily attendance cleanup process...")
    enforce_absence_rule()
    print("Process finished.")