# submissions.py
from flask import render_template, session, redirect, url_for, flash, request, jsonify
from models import Student
from database import db_session
import os
from openai import OpenAI
from moviepy import *
from langchain_deepseek import ChatDeepSeek
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
import tempfile
import json

# Load environment variables
os.environ['OPENAI_API_KEY'] = "API KEY"
os.environ["DEEPSEEK_API_KEY"] = "API KEY"
 # Replace with your actual key

class GradingOutput(BaseModel):
    project_grade: int = Field(description="Grade (1-10) for innovation, practicality, and potential impact.")
    project_reasoning: str = Field(description="Detailed reasoning behind the project idea grade.")
    presentation_grade: int = Field(description="Grade (1-10) for clarity, structure, and overall delivery.")
    presentation_reasoning: str = Field(description="Detailed reasoning behind the presentation grade.")
    feedback: str = Field(description="Constructive feedback highlighting strengths and areas for improvement.")

def transcribe_video(video_path):
    """Transcribe video to text using Whisper"""
    client = OpenAI()
    
    # Extract audio
    audio_path = os.path.join(tempfile.gettempdir(), "temp_audio.mp3")
    video = VideoFileClip(video_path)
    video.audio.write_audiofile(audio_path)
    video.close()
    
    # Transcribe
    with open(audio_path, "rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text"
        )
    
    os.remove(audio_path)
    return transcription

def evaluate_transcript(transcript):
    """Evaluate the transcript using DeepSeek"""
    llm = ChatDeepSeek(model="deepseek-reasoner", temperature=0.3)
    output_parser = JsonOutputParser(pydantic_object=GradingOutput)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an experienced evaluator for academic project presentations."),
        ("user", """
        Evaluate this project presentation transcript:
        {transcript}
        
        Provide evaluation in this format:
        {format_instructions}
        """)
    ])
    
    chain = prompt | llm | output_parser
    return chain.invoke({
        "transcript": transcript,
        "format_instructions": output_parser.get_format_instructions()
    })

def submissions():
    if 'student_id' not in session:
        flash('Please log in first', 'danger')
        return redirect(url_for('auth.student_login'))
    
    student = db_session.get(Student, session['student_id'])
    if not student.groups:
        return redirect(url_for('group.formation_step1'))
    
    group = student.groups[0].group
    
    # Handle video submission and evaluation
    evaluation_result = None
    transcript = None
    
    if request.method == 'POST' and 'video_file' in request.files:
        video_file = request.files['video_file']
        if video_file.filename != '':
            # Save temporary video file
            temp_video_path = os.path.join(tempfile.gettempdir(), video_file.filename)
            video_file.save(temp_video_path)
            
            try:
                # Process the video
                transcript = transcribe_video(temp_video_path)
                evaluation_result = evaluate_transcript(transcript)
                
                # Save results to session
                session['last_evaluation'] = {
                    'transcript': transcript,
                    'evaluation': evaluation_result
                }
                
                flash('Video evaluated successfully!', 'success')
            except Exception as e:
                flash(f'Error processing video: {str(e)}', 'danger')
            finally:
                # Clean up
                if os.path.exists(temp_video_path):
                    os.remove(temp_video_path)
    
    return render_template('group/submissions.html', 
                         group=group,
                         evaluation=evaluation_result,
                         transcript=transcript)