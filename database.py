from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker,scoped_session
from models import Base, Subject, Student, StudentSubject, Teacher, TeacherSubject, Assignment, AssignmentSubmission
import datetime

DATABASE_URI = 'sqlite:///CollabEdu.db'
engine = create_engine(DATABASE_URI, future=True)
#Session = sessionmaker(bind=engine)
#db_session = Session()
SessionLocal = sessionmaker(          # factory
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
db_session = scoped_session(SessionLocal)
def init_db():
    Base.metadata.create_all(engine)

def seed_database():
    session = SessionLocal()
    
    try:        
        print("Database seeded successfully!")
                
    except Exception as e:
        session.rollback()
        print(f"Error seeding database: {str(e)}")
    finally:
        session.close()

if __name__ == '__main__':
    init_db()
    seed_database()