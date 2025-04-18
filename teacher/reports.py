from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from models import Project, Task

class ProjectReporter:
    def __init__(self, llm):
        self.report_chain = LLMChain(
            llm=llm,
            prompt=PromptTemplate(
                input_variables=["project_data"],
                template="""
                Generate a project report based on:
                {project_data}
                
                Include:
                - Overall progress
                - Key contributions per member
                - Recent activity highlights
                - Code quality observations
                """
            )
        )

    def generate_report(self, project_id):
        project = db_session.get(Project, project_id)
        if not project:
            return None
            
        project_data = {
            'name': project.name,
            'status': project.status,
            **project.get_contribution_report(),
            'tasks': [t.get_langchain_report_data() for t in project.tasks]
        }
        
        return self.report_chain.run(project_data=project_data)