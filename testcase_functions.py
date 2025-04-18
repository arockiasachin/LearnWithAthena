from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_deepseek import ChatDeepSeek
import json
import os
from flask import current_app

os.environ["DEEPSEEK_API_KEY"] = "API KEY"

llm = ChatDeepSeek(model="deepseek-chat", temperature=0)

system_message = """You are an AI assistant specialized in generating comprehensive test cases for programming assignments through a structured process:
1. Analyze the problem description for input/output requirements
2. Identify edge cases and boundary conditions
3. Create visible test cases (with explanations)
4. Generate hidden test cases for validation
5. Format according to specification"""

testcase_prompt = """**Strict JSON Format Required**
Generate test cases for this programming problem:

**Problem Description:**
{description}

**Requirements:**
- Visible tests (3-5): simple inputs with explanations
- Hidden tests (5-7): edge cases, large inputs
- Starter code: {language} skeleton with TODO comments

**Output Format (JSON):**
{{
  "visible": [
    {{
      "input": "test input", 
      "expected_output": "expected result",
      "explanation": "description of test case"
    }}
  ],
  "hidden": [
    {{
      "input": "test input", 
      "expected_output": "expected result"
    }}
  ],
  "starter_code": "code template"
}}

**Important:** 
1. Input must be a single string (use spaces/commas for multiple values)
2. Expected output must exactly match program output (including whitespace)
3. No trailing whitespace in expected outputs"""

testcase_template = ChatPromptTemplate.from_messages([
    ("system", system_message),
    ("human", testcase_prompt)
])

testcase_chain = (
    testcase_template 
    | llm
    | StrOutputParser()
)

def parse_testcases(response: str) -> dict:
    """Enhanced validation for test case generation"""
    try:
        # Remove markdown code blocks
        clean_response = response.replace("```json", "").replace("```", "")
        
        # Find JSON boundaries
        start = clean_response.find('{')
        end = clean_response.rfind('}') + 1
        parsed = json.loads(clean_response[start:end])
        
        # Validate structure
        required_keys = {"visible", "hidden", "starter_code"}
        if not all(k in parsed for k in required_keys):
            raise ValueError("Missing required test case sections")
            
        # Validate each test case
        for section in ["visible", "hidden"]:
            for tc in parsed[section]:
                if not isinstance(tc.get("input", ""), str):
                    raise ValueError("Test case input must be string")
                if not isinstance(tc.get("expected_output", ""), str):
                    raise ValueError("Expected output must be string")
                if section == "visible" and not isinstance(tc.get("explanation", ""), str):
                    raise ValueError("Visible tests need explanations")
        
        return parsed
        
    except Exception as e:
        current_app.logger.error(f"Test case validation failed: {str(e)}")
        # Return safe defaults
        return {
            "visible": [{
                "input": "5",
                "expected_output": "120",
                "explanation": "Sample factorial input"
            }],
            "hidden": [{
                "input": "10",
                "expected_output": "3628800"
            }],
            "starter_code": "# Default starter code\n# Implement your solution here"
        }