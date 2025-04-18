import csv
import io
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_deepseek import ChatDeepSeek
import json
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
import os
os.environ['DEEPSEEK_API_KEY'] = "API KEY"
CSV_HEADER = "Week,Module Number,Module Title,Assignment Type,Assignment Title,Due Date,Description"


class ScheduleGenerator:
    def __init__(self):
        self.llm = ChatDeepSeek(
            model="deepseek-chat",
            temperature=0,
        )
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len
        )

    def _validate_dates(self, start_date: str, end_date: str) -> Tuple[datetime, datetime]:
        """Validate and parse date inputs"""
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            if start > end:
                raise ValueError("Start date must be before end date")
            if (end - start).days < 7:
                raise ValueError("Course duration must be at least 1 week")
            return start, end
        except ValueError as e:
            logger.error(f"Invalid date format: {str(e)}")
            raise

    def _extract_modules(self, syllabus_text: str) -> List[Dict[str, str]]:
        """Extract modules with numbers and titles from syllabus text using JSON"""
        MAX_RETRIES = 3
        retry_count = 0
        
        while retry_count < MAX_RETRIES:
            try:
                prompt = ChatPromptTemplate.from_messages([
                    SystemMessagePromptTemplate.from_template(
                        "You are an expert academic syllabus analyzer. Return ONLY valid JSON."
                    ),
                    HumanMessagePromptTemplate.from_template(
                        """Extract ALL topics from this syllabus as JSON with EXACTLY this structure:
                        {{
                            "modules": [
                                {{
                                    "number": 1,
                                    "title": "Module Title (Theory/Lab/Both)",
                                    "type": "theory/lab/both",
                                    "difficulty": "easy/medium/hard"
                                }}
                            ]
                        }}
                        
                        RULES:
                        1. Order by increasing difficulty
                        2. Remove the last module
                        3. Add (Theory)/(Lab)/(Lab+Theory) to titles
                        
                        Syllabus: {text}
                        """
                    )
                ])
                
                chain = prompt | self.llm | StrOutputParser()
                response = chain.invoke({"text": syllabus_text})
                # Clean response before parsing
                cleaned_response = self._clean_json_response(response)
                
                # Parse and validate
                data = json.loads(cleaned_response)
                if not isinstance(data.get("modules"), list):
                    raise ValueError("Modules list missing in response")
                    
                validated_modules = []
                for idx, module in enumerate(data["modules"]):
                    if not all(key in module for key in ["number", "title"]):
                        raise ValueError(f"Module {idx+1} missing required fields")
                    
                    validated_modules.append({
                        "number": str(module["number"]).strip(),
                        "title": module["title"].strip()
                    })
                    
                return validated_modules
                
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"JSON parse attempt {retry_count+1} failed: {str(e)}")
                logger.debug(f"Raw LLM response: {response}")
                retry_count += 1
                if retry_count == MAX_RETRIES:
                    raise ValueError(f"Failed to parse valid modules after {MAX_RETRIES} attempts")
                continue
                
        return []

    def _clean_json_response(self, response: str) -> str:
        """Extract JSON from potentially wrapped response"""
        # Remove markdown code fences
        response = response.replace('```json', '').replace('```', '')
        
        # Find first { and last } to capture JSON
        start = response.find('{')
        end = response.rfind('}') + 1
        if start == -1 or end == 0:
            return response
        
        return response[start:end]
        
    def _generate_assignments_json(self, modules: List[Dict], due_dates: List[str], subject_name: str) -> Dict:
        """Generate assignments in JSON format first with enhanced validation"""
        prompt = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(
                """You are an expert Computer Science educator with 15+ years experience creating effective assignment schedules.
                Generate a rigorous but achievable assignment timeline that balances theory and practical application.
                
                Pedagogical Guidelines:
                1. Cognitive Load Management:
                - Space similar assignment types across different weeks
                - Gradually increase complexity (Bloom's Taxonomy)
                2. Assessment Variety:
                - Mix conceptual understanding (quizzes) with applied skills (coding)
                - Alternate between individual and group-friendly assignments
                3. Real-World Relevance:
                - Include practical scenarios in descriptions
                - Reference industry practices where applicable
                
                Return assignments as JSON with this exact structure:
            {{
                "assignments": [
                    {{
                        "week": 1,
                        "module_number": 1,
                        "module_title": "Title",
                        "type": "Quiz/Coding/Debugging/Descriptive",
                        "title": "Assignment Title",
                        "due_date": "YYYY-MM-DD",
                        "description": "Detailed description",
                        "difficulty": "easy/medium/hard"
                    }}
                ]
            }}"""
            ),
            HumanMessagePromptTemplate.from_template(
                """Course: {subject_name}
                Modules:
                {modules}
                
                Temporal Constraints:
                - Assignment Due Dates (must use in this exact order):
                {due_dates}
                
                Assignment Matrix Requirements:
                Per Week:
                - 1 Conceptual Quiz (10-15 MCQs testing key concepts)
                - 1 Analytical Descriptive (300-500 word analysis)
                - 1 Applied Coding (1-2 hour implementation)
                - 1 Critical Debugging (3-5 intentional errors)
                
                Quality Assurance Checklist:
                [ ] All modules represented proportionally
                [ ] No two similar assignments are consecutive
                [ ] Descriptions provide clear success criteria
                [ ] Dates match exactly with provided sequence
                [ ] Difficulty progresses appropriately
                
                Generate the complete assignment schedule:"""
            )
        ])
        #print(prompt)
        chain = prompt | self.llm | StrOutputParser()
        response = chain.invoke({
            "subject_name": subject_name,
            "modules": json.dumps([f"Module {m['number']}: {m['title']}" for m in modules]),
            "due_dates": ", ".join(due_dates)
        })
        #print(response)
        try:
            cleaned_response = self._clean_json_response(response)  # Add this line
            data = json.loads(cleaned_response)  # Use cleaned response
            if not isinstance(data.get("assignments"), list):
                raise ValueError("Invalid assignments structure in LLM response")
                
            # Validate each assignment
            for i, assignment in enumerate(data["assignments"]):
                if not all(key in assignment for key in ["week", "module_number", "type", "title", "due_date"]):
                    raise ValueError(f"Assignment {i+1} missing required fields")
                    
                # Validate date format
                datetime.strptime(assignment["due_date"], "%Y-%m-%d")
                
            return data
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON response from LLM: {str(e)}")
        except ValueError as e:
            raise ValueError(f"Assignment validation failed: {str(e)}")
        
        
    def _json_to_csv(self, assignments_data: Dict) -> str:
        """Convert validated JSON assignments to CSV format"""
        if not assignments_data.get("assignments"):
            raise ValueError("No assignments in JSON data")
            
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            "Week", "Module Number", "Module Title",
            "Assignment Type", "Assignment Title",
            "Due Date", "Description"
        ])
        
        writer.writeheader()
        for assignment in assignments_data["assignments"]:
            writer.writerow({
                "Week": assignment["week"],
                "Module Number": assignment["module_number"],
                "Module Title": assignment["module_title"],
                "Assignment Type": assignment["type"],
                "Assignment Title": assignment["title"],
                "Due Date": assignment["due_date"],
                "Description": assignment.get("description", "")
            })
            
        return output.getvalue()        

    def _generate_due_dates(self, start: datetime, end: datetime) -> List[str]:
        """Generate assignment due dates following the pattern:
        Week 1: Wed, Fri
        Week 2: Mon, Wed
        Repeating until end date"""
        dates = []
        current = start
        
        while current <= end:
            # Week 1 assignments
            wed1 = current + timedelta(days=(2 - current.weekday() + 7) % 7)
            fri1 = wed1 + timedelta(days=2)
            
            # Week 2 assignments
            mon2 = wed1 + timedelta(days=5)
            wed2 = wed1 + timedelta(days=7)
            
            for date in [wed1, fri1, mon2, wed2]:
                if date <= end:
                    dates.append(date.strftime("%Y-%m-%d"))
            
            current = wed2  # Move to next cycle
            
        return dates
    def _create_assignment_prompt(self, modules: List[Dict], due_dates: List[str], subject_name: str) -> ChatPromptTemplate:
        """Create a comprehensive assignment generation prompt with detailed guidelines"""
        module_list = "\n".join([f"Module {m['number']}: {m['title']}" for m in modules])
        date_chunks = [due_dates[i:i+4] for i in range(0, len(due_dates), 4)]
        
        # Detailed example with realistic assignments
        example = """
        Example Schedule:
        Week,Module Number,Module Title,Assignment Type,Assignment Title,Due Date,Description
        1,1,Introduction to Python,Quiz,"Python Basics Quiz",2024-09-04,"15 MCQs covering: variables, data types, basic syntax"
        1,1,Introduction to Python,Coding,"Temperature Converter",2024-09-06,"Implement Celsius to Fahrenheit conversion with user input"
        2,2,Control Structures,Descriptive,"Loop Comparison",2024-09-09,"400-word analysis comparing for/while loops with 3 real-world use cases"
        2,2,Control Structures,Debugging,"Loop Fix Exercise",2024-09-11,"Identify and fix 4 logical errors in the provided loop examples"
        """
        
        return ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(
                """You are an expert Computer Science educator and curriculum designer with 15 years of 
                experience creating effective assignment schedules for {subject_name} courses. Your task 
                is to create a rigorous but achievable assignment timeline that balances theory and 
                practical application while maintaining student engagement throughout the semester.
                
                Pedagogical Guidelines:
                1. Cognitive Load Management:
                - Space similar assignment types across different weeks
                - Gradually increase complexity (Bloom's Taxonomy)
                
                2. Assessment Variety:
                - Mix conceptual understanding (quizzes) with applied skills (coding)
                - Alternate between individual and potentially group-friendly assignments
                
                3. Real-World Relevance:
                - Include practical scenarios in descriptions
                - Reference industry practices where applicable
                """
            ),
            HumanMessagePromptTemplate.from_template(
                """Course Module Inventory:
                {module_list}
                
                Temporal Constraints:
                - Course Duration: {duration_weeks} weeks
                - Assignment Due Dates (must use in exact order):
                {date_sequence}
                
                Assignment Matrix Requirements:
                Per Week:
                - 1 Conceptual Quiz (MCQ/True-False)
                - 1 Analytical Descriptive (300-500 words)
                - 1 Applied Coding (1-2 hour implementation)
                - 1 Critical Debugging (3-5 intentional errors)
                
                Content Guidelines:
                - Quiz: 10-15 questions testing key module concepts
                - Descriptive: Comparative analysis or problem decomposition
                - Coding: Practical implementation with clear specifications
                - Debugging: Functional but flawed code with educational value
                
                Formatting Specifications:
                - STRICT CSV format with header : {{CSV_HEADER}}
                - Double-quote any text containing commas
                - No additional commentary outside CSV data
                - Use exactly these column names in this order
                - No Preamble, No decorator, just the plain csv text
                                
                STRICT DATE FORMAT REQUIREMENTS:
                - All dates MUST be in YYYY-MM-DD format
                - No empty or invalid dates allowed
                - Dates must be within the course start/end range
                
                Quality Assurance Checklist:
                [ ] All modules are represented proportionally
                [ ] No two similar assignments are consecutive
                [ ] Descriptions provide clear success criteria
                [ ] Dates match exactly with provided sequence
                
                {example}
                
                Please generate the complete assignment schedule:"""
            )
        ])

    def generate_schedule(
        self,
        syllabus_text: str,
        start_date: str,
        end_date: str,
        subject_id: str,
        subject_name: str
    ) -> Dict:
        """Main schedule generation with JSON-first approach"""
        try:
            # Validate dates
            start, end = self._validate_dates(start_date, end_date)
            
            # Extract modules as JSON
            modules = self._extract_modules(syllabus_text)
            if not modules:
                raise ValueError("No modules found in syllabus text")
                
            # Generate due dates
            due_dates = self._generate_due_dates(start, end)
            if len(due_dates) < 4:
                raise ValueError("Insufficient duration for complete schedule")
                
            # Generate assignments as JSON
            assignments_json = self._generate_assignments_json(modules, due_dates, subject_name)
            
            # Convert to CSV
            csv_content = self._json_to_csv(assignments_json)
            
            # Parse for return
            schedule = self._parse_csv(csv_content)
            
            return {
                "schedule": schedule,
                "csv_content": csv_content,
                "filename": f"{subject_id}_{start_date}_schedule.csv",
                "modules": modules
            }
            
        except Exception as e:
            logger.error(f"Schedule generation failed: {str(e)}")
            raise

    def clean_csv(self, csv_content: str) -> str: 
        """
        Robust CSV cleaner that handles multiple edge cases:
        1. Markdown code fences (```csv)
        2. Explanatory text before/after data
        3. Multiple header rows
        4. Empty/malformed rows
        5. Inconsistent quoting
        Returns clean CSV content with exactly one header row
        """
        # Normalize line endings and remove empty lines
        lines = [line.strip() for line in csv_content.splitlines() if line.strip()]
        
        # Case 1: Remove markdown code fences
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].startswith('```'):
            lines = lines[:-1]
        
        # Case 2: Remove non-header explanatory text
        header_index = None
        for i, line in enumerate(lines):
            if line.startswith('Week,Module Number') or line.startswith('Week, Module Number'):
                header_index = i
                break
        
        if header_index is None:
            raise ValueError("No valid CSV header found")
        
        # Keep only from header onward
        lines = lines[header_index:]
        
        # Case 3: Handle multiple header-like rows
        cleaned_lines = [lines[0]]  # Keep first valid header
        for line in lines[1:]:
            # Skip lines that look like secondary headers
            if line.lower().startswith(('week', 'module')) and len(line.split(',')) < 4:
                continue
            cleaned_lines.append(line)
        
        # Case 4: Validate and clean each data row
        final_lines = [cleaned_lines[0]]  # Header
        expected_columns = len(cleaned_lines[0].split(','))
        
        for line in cleaned_lines[1:]:
            parts = [part.strip().strip('"') for part in line.split(',')]
            
            # Skip malformed rows
            if len(parts) != expected_columns:
                continue
            
            # Case 5: Validate date format
            date_str = parts[5]  # Due Date is 6th column (0-indexed 5)
            try:
                datetime.strptime(date_str, '%Y-%m-%d')
                final_lines.append(','.join(f'"{p}"' if ',' in p else p for p in parts))
            except ValueError:
                continue
        
        return '\n'.join(final_lines)
    
    def _parse_csv(self, csv_content: str) -> List[Dict]:
        """Robust CSV parser with comprehensive error handling and data validation
        
        Features:
        - Handles quoted fields with embedded commas and newlines
        - Multiple fallback mechanisms for delimiter detection
        - Strict date format validation
        - Comprehensive field validation
        - Detailed error logging
        
        Args:
            csv_content: Raw CSV string to parse
            
        Returns:
            List of dictionaries representing parsed rows
            
        Raises:
            ValueError: If fundamental CSV structure is invalid
        """
        try:
            print(csv_content)
            # Initial content validation
            if not csv_content or not csv_content.strip():
                logger.warning("Empty CSV content received")
                return []

            # Clean the CSV content first
            cleaned_content = self.clean_csv(csv_content)
            if not cleaned_content.strip():
                logger.error("CSV cleaning resulted in empty content")
                return []
            print("cleaned_content:")
            print(cleaned_content)
            # Log sample content for debugging
            logger.debug(f"CSV content sample (first 200 chars):\n{cleaned_content[:200]}...")

            # Standardize line endings and remove empty lines
            lines = [line.strip() for line in cleaned_content.splitlines() if line.strip()]
            if not lines:
                logger.error("No valid lines after cleaning")
                return []

            expected_headers = [h.strip() for h in CSV_HEADER.split(',')]
            
            # Create StringIO object for reading
            csv_file = io.StringIO('\n'.join(lines))

            # Enhanced dialect detection with multiple fallbacks
            dialect = None
            sniffer = csv.Sniffer()
            
            try:
                # Try with larger sample size and explicit delimiters
                sample = csv_file.read(2048)
                csv_file.seek(0)
                dialect = sniffer.sniff(sample, delimiters=',\t;')
                dialect.doublequote = True
                dialect.skipinitialspace = True
                dialect.quoting = csv.QUOTE_MINIMAL
                
                # Verify header detection
                csv_file.seek(0)
                has_header = sniffer.has_header(sample)
            except csv.Error as e:
                logger.warning(f"CSV sniffing failed, using fallback: {str(e)}")
                dialect = csv.excel()
                dialect.delimiter = ','  # Default to comma delimiter
                dialect.quoting = csv.QUOTE_MINIMAL
                dialect.doublequote = True
                has_header = True  # Assume header exists

            # Configure reader with appropriate settings
            reader = None
            try:
                if has_header:
                    reader = csv.DictReader(csv_file, dialect=dialect)
                    # Validate headers if they exist
                    if reader.fieldnames:
                        normalized_fields = [f.strip().lower().replace(' ', '_') 
                                        for f in reader.fieldnames]
                        expected_normalized = [h.strip().lower().replace(' ', '_') 
                                            for h in expected_headers]
                        if normalized_fields != expected_normalized:
                            logger.warning(f"Header mismatch. Expected: {expected_headers}, Got: {reader.fieldnames}")
                            # Fallback to using our expected headers
                            csv_file.seek(0)
                            reader = csv.DictReader(csv_file, fieldnames=expected_headers,
                                                dialect=dialect)
                else:
                    reader = csv.DictReader(csv_file, fieldnames=expected_headers, 
                                        dialect=dialect)
            except csv.Error as e:
                logger.error(f"CSV reader initialization failed: {str(e)}")
                return []

            # Parse rows with comprehensive validation
            parsed_data = []
            line_num = 0
            for row in reader:
                line_num += 1
                try:
                    # Convert empty strings to None and strip whitespace
                    processed_row = {
                        k: v.strip() if isinstance(v, str) and v.strip() else None
                        for k, v in row.items()
                    }

                    # Skip empty rows
                    if not any(processed_row.values()):
                        logger.debug(f"Skipping empty row at line {line_num}")
                        continue

                    # Validate required fields
                    required_fields = ['Week', 'Module Number', 'Assignment Type', 
                                    'Assignment Title', 'Due Date']
                    missing_fields = [f for f in required_fields 
                                    if not processed_row.get(f)]
                    if missing_fields:
                        logger.warning(f"Missing required fields {missing_fields} in row {line_num}")
                        continue

                    # Validate date format
                    try:
                        datetime.strptime(processed_row['Due Date'], '%Y-%m-%d')
                    except ValueError:
                        logger.warning(f"Invalid date format in row {line_num}: {processed_row['Due Date']}")
                        continue

                    # Validate week and module number are integers
                    try:
                        int(processed_row['Week'])
                        int(processed_row['Module Number'])
                    except ValueError:
                        logger.warning(f"Invalid numeric value in row {line_num}")
                        continue

                    # Normalize field names and ensure consistent structure
                    final_row = {
                        'Week': processed_row['Week'],
                        'Module Number': processed_row['Module Number'],
                        'Module Title': processed_row.get('Module Title', ''),
                        'Assignment Type': processed_row['Assignment Type'],
                        'Assignment Title': processed_row['Assignment Title'],
                        'Due Date': processed_row['Due Date'],
                        'Description': processed_row.get('Description', '')
                    }

                    parsed_data.append(final_row)
                except Exception as e:
                    logger.warning(f"Error parsing row {line_num}: {str(e)}")
                    continue

            if not parsed_data:
                logger.error("No valid rows parsed from CSV")
                return []

            logger.info(f"Successfully parsed {len(parsed_data)} rows from CSV")
            return parsed_data

        except Exception as e:
            logger.error(f"CSV parsing failed: {str(e)}", exc_info=True)
            return []
    
# Singleton instance
schedule_generator = ScheduleGenerator()

def generate_course_schedule(
    syllabus_text: str,
    start_date: str,
    end_date: str,
    subject_id: str,
    subject_name: str
) -> Dict:
    """Public interface for schedule generation"""
    return schedule_generator.generate_schedule(
        syllabus_text=syllabus_text,
        start_date=start_date,
        end_date=end_date,
        subject_id=subject_id,
        subject_name=subject_name
    )