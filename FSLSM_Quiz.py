from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import sqlite3

quiz_bp = Blueprint('quiz', __name__)
DATABASE = 'CollabEdu.db'



# Example questions for each dimension
FSLSM_QUESTIONS = [

  {"number": 1, "dimension": "Active-Reflective", "question": "I understand something better after I", "a": "try it out", "b": "think it through", "a_score": 1, "b_score": -1},
  {"number": 2, "dimension": "Sensing-Intuitive", "question": "I would rather be considered", "a": "realistic", "b": "innovative", "a_score": 1, "b_score": -1},
  {"number": 3, "dimension": "Visual-Verbal", "question": "When I think about what I did yesterday, I am most likely to get", "a": "a picture", "b": "words", "a_score": 1, "b_score": -1},
  {"number": 4, "dimension": "Sequential-Global", "question": "I tend to", "a": "understand details of a subject but may be fuzzy about its overall structure", "b": "understand the overall structure but may be fuzzy about details", "a_score": 1, "b_score": -1},

  {"number": 5, "dimension": "Active-Reflective", "question": "When I am learning something new, it helps me to", "a": "talk about it", "b": "think about it", "a_score": 1, "b_score": -1},
  {"number": 6, "dimension": "Sensing-Intuitive", "question": "If I were a teacher, I would rather teach a course", "a": "that deals with facts and real life situations", "b": "that deals with ideas and theories", "a_score": 1, "b_score": -1},
  {"number": 7, "dimension": "Visual-Verbal", "question": "I prefer to get new information in", "a": "pictures, diagrams, graphs, or maps", "b": "written directions or verbal information", "a_score": 1, "b_score": -1},
  {"number": 8, "dimension": "Sequential-Global", "question": "Once I understand", "a": "all the parts, I understand the whole thing", "b": "the whole thing, I see how the parts fit", "a_score": 1, "b_score": -1},

  {"number": 9, "dimension": "Active-Reflective", "question": "In a study group working on difficult material, I am more likely to", "a": "jump in and contribute ideas", "b": "sit back and listen", "a_score": 1, "b_score": -1},
  {"number": 10, "dimension": "Sensing-Intuitive", "question": "I find it easier", "a": "to learn facts", "b": "to learn concepts", "a_score": 1, "b_score": -1},
  {"number": 11, "dimension": "Visual-Verbal", "question": "In a book with lots of pictures and charts, I am likely to", "a": "look over the pictures and charts carefully", "b": "focus on the written text", "a_score": 1, "b_score": -1},
  {"number": 12, "dimension": "Sequential-Global", "question": "When I solve math problems", "a": "I usually work my way to the solutions one step at a time", "b": "I often just see the solutions but then have to struggle to figure out the steps to get to them", "a_score": 1, "b_score": -1},

  {"number": 13, "dimension": "Active-Reflective", "question": "In classes I have taken", "a": "I have usually gotten to know many of the students", "b": "I have rarely gotten to know many of the students", "a_score": 1, "b_score": -1},
  {"number": 14, "dimension": "Sensing-Intuitive", "question": "In reading nonfiction, I prefer", "a": "something that teaches me new facts or tells me how to do something", "b": "something that gives me new ideas to think about", "a_score": 1, "b_score": -1},
  {"number": 15, "dimension": "Visual-Verbal", "question": "I like teachers", "a": "who put a lot of diagrams on the board", "b": "who spend a lot of time explaining", "a_score": 1, "b_score": -1},
  {"number": 16, "dimension": "Sequential-Global", "question": "When I'm analyzing a story or a novel", "a": "I think of the incidents and try to put them together to figure out the themes", "b": "I just know what the themes are when I finish reading and then I have to go back and find the incidents that demonstrate them", "a_score": 1, "b_score": -1},

  {"number": 17, "dimension": "Active-Reflective", "question": "When I start a homework problem, I am more likely to", "a": "start working on the solution immediately", "b": "try to fully understand the problem first", "a_score": 1, "b_score": -1},
  {"number": 18, "dimension": "Sensing-Intuitive", "question": "I prefer the idea of", "a": "certainty", "b": "theory", "a_score": 1, "b_score": -1},
  {"number": 19, "dimension": "Visual-Verbal", "question": "I remember best", "a": "what I see", "b": "what I hear", "a_score": 1, "b_score": -1},
  {"number": 20, "dimension": "Sequential-Global", "question": "It is more important to me that an instructor", "a": "lay out the material in clear sequential steps", "b": "give me an overall picture and relate the material to other subjects", "a_score": 1, "b_score": -1},
  {"number": 21, "dimension": "Active-Reflective", "question": "I prefer to study", "a": "in a study group", "b": "alone", "a_score": 1, "b_score": -1},
  {"number": 22, "dimension": "Sensing-Intuitive", "question": "I am more likely to be considered", "a": "careful about the details of my work", "b": "creative about how to do my work", "a_score": 1, "b_score": -1},
  {"number": 23, "dimension": "Visual-Verbal", "question": "When I get directions to a new place, I prefer", "a": "a map", "b": "written instructions", "a_score": 1, "b_score": -1},
  {"number": 24, "dimension": "Sequential-Global", "question": "I learn", "a": "at a fairly regular pace. If I study hard, I'll 'get it.'", "b": "in fits and starts. I'll be totally confused and then suddenly it all 'clicks.'", "a_score": 1, "b_score": -1},
  {"number": 25, "dimension": "Active-Reflective", "question": "I would rather first", "a": "try things out", "b": "think about how I'm going to do it", "a_score": 1, "b_score": -1},
  {"number": 26, "dimension": "Sensing-Intuitive", "question": "When I am reading for enjoyment, I like writers to", "a": "clearly say what they mean", "b": "say things in creative, interesting ways", "a_score": 1, "b_score": -1},
  {"number": 27, "dimension": "Visual-Verbal", "question": "When I see a diagram or sketch in class, I am most likely to remember", "a": "the picture", "b": "what the instructor said about it", "a_score": 1, "b_score": -1},
  {"number": 28, "dimension": "Sequential-Global", "question": "When considering a body of information, I am more likely to", "a": "focus on details and miss the big picture", "b": "try to understand the big picture before getting into the details", "a_score": 1, "b_score": -1},
  {"number": 29, "dimension": "Active-Reflective", "question": "I more easily remember", "a": "something I have done", "b": "something I have thought a lot about", "a_score": 1, "b_score": -1},
  {"number": 30, "dimension": "Sensing-Intuitive", "question": "When I have to perform a task, I prefer to", "a": "master one way of doing it", "b": "come up with new ways of doing it", "a_score": 1, "b_score": -1},
  {"number": 31, "dimension": "Visual-Verbal", "question": "When someone is showing me data, I prefer", "a": "charts or graphs", "b": "text summarizing the results", "a_score": 1, "b_score": -1},
  {"number": 32, "dimension": "Sequential-Global", "question": "When writing a paper, I am more likely to", "a": "work on (think about or write) the beginning of the paper and progress forward", "b": "work on (think about or write) different parts of the paper and then order them", "a_score": 1, "b_score": -1},
  {"number": 33, "dimension": "Active-Reflective", "question": "When I have to work on a group project, I first want to", "a": "have 'group brainstorming' where everyone contributes ideas", "b": "brainstorm individually and then come together as a group to compare ideas", "a_score": 1, "b_score": -1},
  {"number": 34, "dimension": "Sensing-Intuitive", "question": "I consider it higher praise to call someone", "a": "sensible", "b": "imaginative", "a_score": 1, "b_score": -1},
  {"number": 35, "dimension": "Visual-Verbal", "question": "When I meet people at a party, I am more likely to remember", "a": "what they looked like", "b": "what they said about themselves", "a_score": 1, "b_score": -1},
  {"number": 36, "dimension": "Sequential-Global", "question": "When I am learning a new subject, I prefer to", "a": "stay focused on that subject, learning as much about it as I can", "b": "try to make connections between that subject and related subjects", "a_score": 1, "b_score": -1},
  {"number": 37, "dimension": "Active-Reflective", "question": "I am more likely to be considered", "a": "outgoing", "b": "reserved", "a_score": 1, "b_score": -1},
  {"number": 38, "dimension": "Sensing-Intuitive", "question": "I prefer courses that emphasize", "a": "concrete material (facts, data)", "b": "abstract material (concepts, theories)", "a_score": 1, "b_score": -1},
  {"number": 39, "dimension": "Visual-Verbal", "question": "For entertainment, I would rather", "a": "watch television", "b": "read a book", "a_score": 1, "b_score": -1},
  {"number": 40, "dimension": "Sequential-Global", "question": "Some teachers start their lectures with an outline of what they will cover. Such outlines are", "a": "somewhat helpful to me", "b": "very helpful to me", "a_score": 1, "b_score": -1},
  {"number": 41, "dimension": "Active-Reflective", "question": "The idea of doing homework in groups, with one grade for the entire group", "a": "appeals to me", "b": "does not appeal to me", "a_score": 1, "b_score": -1},
  {"number": 42, "dimension": "Sensing-Intuitive", "question": "When I am doing long calculations,", "a": "I tend to repeat all my steps and check my work carefully", "b": "I find checking my work tiresome and have to force myself to do it", "a_score": 1, "b_score": -1},
  {"number": 43, "dimension": "Visual-Verbal", "question": "I tend to picture places I have been", "a": "easily and fairly accurately", "b": "with difficulty and without much detail", "a_score": 1, "b_score": -1},
  {"number": 44, "dimension": "Sequential-Global", "question": "When solving problems in a group, I would be more likely to", "a": "think of the steps in the solution process", "b": "think of possible consequences or applications of the solution in a wide range of areas", "a_score": 1, "b_score": -1}

]

@quiz_bp.route('/quiz_dashboard')
def quiz_dashboard():
    if 'student_id' not in session:
        flash("Please log in as a student first.", 'danger')
        return redirect(url_for('auth.student_login'))

    student_id = session['student_id']
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT active_reflective, sensing_intuitive, visual_verbal, sequential_global
            FROM fslsm_results WHERE student_id = ?
        """, (student_id,))
        row = cursor.fetchone()
    print("Fetched Result for Dashboard:", row)
    return render_template('quiz_dashboard.html', 
                         fslsm_result=row,
                         has_completed_quiz=row is not None)


@quiz_bp.route('/fslsm/start')
def start_quiz():
    if 'student_id' not in session:
        flash("Please log in first.", 'danger')
        return redirect(url_for('auth.student_login'))
    
    session.pop('fslsm_answers', None)
    return redirect(url_for('quiz.fslsm_quiz_step', step=1))

@quiz_bp.route('/fslsm/step/<int:step>', methods=['GET', 'POST'])
def fslsm_quiz_step(step):
    if 'student_id' not in session:
        flash("Please log in first.", 'danger')
        return redirect(url_for('auth.student_login'))

    dimensions = ["Active-Reflective", "Sensing-Intuitive", "Visual-Verbal", "Sequential-Global"]
    
    if step < 1 or step > len(dimensions):
        flash("Invalid quiz step.", 'danger')
        return redirect(url_for('quiz.quiz_dashboard'))

    current_dim = dimensions[step - 1]
    questions = [q for q in FSLSM_QUESTIONS if q["dimension"] == current_dim]

    if request.method == 'POST':
        answered = {int(k) for k in request.form if k.isdigit()}
        required = {q["number"] for q in questions}
        
        if answered != required:
            flash("Please answer all questions before proceeding.", 'warning')
            return redirect(url_for('quiz.fslsm_quiz_step', step=step))

        session.setdefault('fslsm_answers', {}).update(request.form)
        session.modified = True

        if step < len(dimensions):
            return redirect(url_for('quiz.fslsm_quiz_step', step=step + 1))
        return redirect(url_for('quiz.fslsm_calculate'))

    progress = int((step - 1) / len(dimensions) * 100)
    return render_template('fslsm_step.html',
                         step=step,
                         total_steps=len(dimensions),
                         dimension=current_dim,
                         questions=questions,
                         progress=progress)

def calculate_scores(answers):
    # Initialize counts of 'a' and 'b' per dimension
    counts = {
        "Active-Reflective": {"a": 0, "b": 0},
        "Sensing-Intuitive": {"a": 0, "b": 0},
        "Visual-Verbal": {"a": 0, "b": 0},
        "Sequential-Global": {"a": 0, "b": 0}
    }

    # Count 'a' and 'b' per dimension
    for question in FSLSM_QUESTIONS:
        q_num = str(question["number"])
        if q_num in answers:
            answer = answers[q_num]
            if answer == 'a':
                counts[question["dimension"]]['a'] += 1
            elif answer == 'b':
                counts[question["dimension"]]['b'] += 1

    # Calculate final scores based on (a - b)
    scores = {
        "Active-Reflective": counts["Active-Reflective"]['a'] - counts["Active-Reflective"]['b'],
        "Sensing-Intuitive": counts["Sensing-Intuitive"]['a'] - counts["Sensing-Intuitive"]['b'],
        "Visual-Verbal": counts["Visual-Verbal"]['a'] - counts["Visual-Verbal"]['b'],
        "Sequential-Global": counts["Sequential-Global"]['a'] - counts["Sequential-Global"]['b'],
    }

    print("Dimension-wise counts:", counts)
    print("Calculated FSLSM Scores:", scores)
    return scores


@quiz_bp.route('/fslsm/calculate')
def fslsm_calculate():
    if 'fslsm_answers' not in session or 'student_id' not in session:
        flash("Quiz data not found. Please start the quiz.", 'danger')
        return redirect(url_for('quiz.quiz_dashboard'))

    try:
        scores = calculate_scores(session['fslsm_answers'])
        print(f"Saving results for student_id: {session['student_id']}")
        print(f"Scores being saved: {scores}")

        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO fslsm_results (student_id, active_reflective, sensing_intuitive, visual_verbal, sequential_global)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(student_id) DO UPDATE SET 
                    active_reflective=excluded.active_reflective,
                    sensing_intuitive=excluded.sensing_intuitive,
                    visual_verbal=excluded.visual_verbal,
                    sequential_global=excluded.sequential_global
            ''', (
                session['student_id'],
                scores["Active-Reflective"],
                scores["Sensing-Intuitive"],
                scores["Visual-Verbal"],
                scores["Sequential-Global"]
            ))
            conn.commit()

        session.pop('fslsm_answers', None)
        flash("Your learning style results have been saved!", 'success')
        return redirect(url_for('quiz.quiz_dashboard'))

    except Exception as e:
        flash(f"Error saving results: {str(e)}", 'danger')
        return redirect(url_for('quiz.quiz_dashboard'))
