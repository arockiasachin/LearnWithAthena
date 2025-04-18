import sqlite3

DATABASE = 'CollabEdu.db'

import sqlite3

DATABASE = 'CollabEdu.db'

def create_fslsm_table():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fslsm_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER UNIQUE NOT NULL,
                active_reflective INTEGER NOT NULL,
                sensing_intuitive INTEGER NOT NULL,
                visual_verbal INTEGER NOT NULL,
                sequential_global INTEGER NOT NULL,
                FOREIGN KEY(student_id) REFERENCES students(id)
            )
        ''')
        conn.commit()
    print("✅ FSLSM results table created successfully with UNIQUE student_id constraint.")

if __name__ == '__main__':
    create_fslsm_table()

