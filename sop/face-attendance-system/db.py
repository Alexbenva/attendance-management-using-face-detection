import pymysql
from pymysql.cursors import DictCursor
import os

# --- IMPORTANT ---
# Make sure these credentials are correct for your MySQL setup.
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "Alexbenva@123")  # ← CHANGE if needed
DB_NAME = os.environ.get("DB_NAME", "face_attendance")


def create_connection(db: str = None):
    """Return a pymysql connection."""
    try:
        db_to_connect = db if db is not None else DB_NAME
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=db_to_connect,
            cursorclass=DictCursor,
            autocommit=False
        )
        return conn
    except pymysql.err.OperationalError as e:
        if "Unknown database" in str(e):
            return None
        print(f"❌ Database connection error: {e}")
        return None
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        return None


def init_database():
    """Create the database and all required tables if they do not exist."""
    try:
        # 1) Ensure database exists
        server_conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            cursorclass=DictCursor
        )
        with server_conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            )
        server_conn.commit()
        server_conn.close()
        print(f"✅ Database '{DB_NAME}' created or already exists.")

        # 2) Connect to that database
        conn = create_connection()
        if not conn:
            print("❌ Failed to connect to the database after ensuring its existence.")
            return False

        with conn.cursor() as cur:
            # --- students table ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS students (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    reg_no VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    department VARCHAR(100),
                    face_encoding LONGTEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # --- staff table ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS staff (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    staff_id VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    course_id VARCHAR(100),
                    subject VARCHAR(100),
                    face_encoding LONGTEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # --- class_schedule table ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS class_schedule (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    hour_name VARCHAR(50) UNIQUE NOT NULL,
                    start_time TIME NOT NULL,
                    end_time TIME NOT NULL,
                    entry_deadline TIME NOT NULL,
                    early_entry_minutes INT DEFAULT 15
                );
            """)

            # --- attendance_students table (NO UNIQUE(reg_no, date)) ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS attendance_students (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    reg_no VARCHAR(50) NOT NULL,
                    date DATE NOT NULL,
                    time_in TIME NOT NULL,
                    time_out TIME,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (reg_no) REFERENCES students(reg_no) ON DELETE CASCADE
                );
            """)

            # Ensure index on reg_no for FK & speed
            # Older MySQL doesn't support "IF NOT EXISTS" for indexes,
            # so just try to create it and ignore duplicate name errors.
            try:
                cur.execute("""
                    CREATE INDEX idx_attendance_students_reg_no
                    ON attendance_students (reg_no);
                """)
            except Exception as e:
                print(f"(Info) Skipping index creation on attendance_students.reg_no: {e}")

            # --- attendance_staff table ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS attendance_staff (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    staff_id VARCHAR(50) NOT NULL,
                    date DATE NOT NULL,
                    hour VARCHAR(20) NOT NULL,
                    time_in TIME NOT NULL,
                    time_out TIME,
                    status VARCHAR(10) DEFAULT 'Present',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (staff_id) REFERENCES staff(staff_id) ON DELETE CASCADE,
                    UNIQUE KEY unique_attendance_staff (staff_id, date, hour)
                );
            """)

            # Populate the schedule table if it's empty
            cur.execute("SELECT COUNT(*) as count FROM class_schedule")
            if cur.fetchone()['count'] == 0:
                print("Populating class schedule with 8 hours for the first time...")
                schedule_data = [
                    ('Hour 1', '08:30:00', '09:20:00', '09:15:00', 15),
                    ('Hour 2', '09:25:00', '10:15:00', '10:10:00', 15),
                    ('Hour 3', '10:20:00', '11:10:00', '11:05:00', 15),
                    ('Hour 4', '11:15:00', '12:05:00', '12:00:00', 15),
                    ('Hour 5', '13:00:00', '13:50:00', '13:45:00', 15),
                    ('Hour 6', '13:55:00', '14:45:00', '14:40:00', 15),
                    ('Hour 7', '14:50:00', '15:40:00', '15:35:00', 15),
                    ('Hour 8', '15:45:00', '16:35:00', '16:30:00', 15)
                ]
                cur.executemany("""
                    INSERT INTO class_schedule
                    (hour_name, start_time, end_time, entry_deadline, early_entry_minutes)
                    VALUES (%s, %s, %s, %s, %s)
                """, schedule_data)

        conn.commit()
        print("✅ All tables initialized successfully!")
        return True

    except Exception as e:
        print(f"❌ Database initialization error: {e}")
        if 'conn' in locals() and conn.open:
            conn.rollback()
        return False
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()


if __name__ == "__main__":
    init_database()
