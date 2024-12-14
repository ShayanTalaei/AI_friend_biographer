from typing import Dict, List, Type, Optional, TYPE_CHECKING
from dataclasses import dataclass
from pydantic import BaseModel, Field
from langchain_core.callbacks.manager import CallbackManagerForToolRun
from langchain_core.tools import BaseTool, ToolException

from agents.biography_team.base_biography_agent import BiographyTeamAgent
from agents.biography_team.models import TodoItem
import xml.etree.ElementTree as ET

from biography.biography import Biography

if TYPE_CHECKING:
    from interview_session.interview_session import InterviewSession

@dataclass
class UpdateResult:
    success: bool
    message: str

class SectionWriter(BiographyTeamAgent):
    def __init__(self, config: Dict, interview_session: 'InterviewSession'):
        super().__init__(
            name="SectionWriter",
            description="Updates individual biography sections based on plans",
            config=config,
            interview_session=interview_session
        )
        self.follow_up_questions = []
        
        self.tools = {
            "get_section": GetSection(biography=self.biography),
            "update_section": UpdateSection(biography=self.biography),
            "add_section": AddSection(biography=self.biography),
            "save_biography": SaveBiography(biography=self.biography)
        }
        
    async def update_section(self, todo_item: TodoItem) -> UpdateResult:
        """
        Update a biography section based on a plan.
        """
        self.add_event(sender=self.name, tag="update_start", 
                      content=f"Starting to {todo_item.action_type} section: {todo_item.section_path}")
        
        prompt = self._create_section_write_prompt(todo_item)
        self.add_event(sender=self.name, tag="section_write_prompt", content=prompt)
        
        response = self.call_engine(prompt)
        self.add_event(sender=self.name, tag="llm_response", content=response)
        
        # Parse response and update section
        success = self._handle_section_update(response, todo_item)
        self.follow_up_questions.extend(self._parse_questions(response))
        
        result_message = "Section updated successfully" if success else "Failed to update section"
        self.add_event(sender=self.name, tag="update_result", 
                      content=result_message)
        
        return UpdateResult(
            success=success,
            message=result_message
        )

    def save_biography(self) -> str:
        """
        Save the current state of the biography to file.
        """
        self.add_event(sender=self.name, tag="save_biography", content="Saving biography to file")
        result = self.tools["save_biography"]._run()
        self.add_event(sender=self.name, tag="save_result", content=result)
        return result

    def _create_section_write_prompt(self, todo_item: TodoItem) -> str:
        """
        Create a prompt for the section writer to update a biography section.
        """
        current_content = self.tools["get_section"]._run(todo_item.section_path) or "Section does not exist yet."
        
        return SECTION_WRITER_PROMPT.format(
            section_path=todo_item.section_path,
            update_plan=todo_item.update_plan,
            current_content=current_content,
            relevant_memories=todo_item.relevant_memories
        )

    def _handle_section_update(self, response: str, todo_item: TodoItem) -> bool:
        """
        Handle the section update response and update the biography.
        """
        try:
            if "<section_update>" in response:
                start_tag = "<section_update>"
                end_tag = "</section_update>"
                start_pos = response.find(start_tag)
                end_pos = response.find(end_tag) + len(end_tag)
                update_text = response[start_pos:end_pos]
                root = ET.fromstring(update_text)
                content = root.find("content").text.strip()
                
                self.add_event(sender=self.name, tag="parsed_content", 
                             content=f"Parsed content for {todo_item.section_path}:\n{content}")
                
                if todo_item.action_type == "update":
                    # Use the update_section tool to apply changes
                    result = self.tools["update_section"]._run(
                        path=todo_item.section_path,
                        content=content
                    )
                    self.add_event(sender=self.name, tag="update_section_result", content=result)
                    return "Successfully" in result

                elif todo_item.action_type == "create":
                    # Use the add_section tool to create a new section
                    result = self.tools["add_section"]._run(
                        path=todo_item.section_path,
                        content=content
                    )
                    self.add_event(sender=self.name, tag="create_section_result", content=result)
                    return "Successfully" in result
                
                else:
                    self.add_event(sender=self.name, tag="error", 
                                  content=f"Invalid action type: {todo_item.action_type}")
                    return False

        except Exception as e:
            self.add_event(sender=self.name, tag="error", 
                          content=f"Error updating section {todo_item.section_path}: {str(e)}\nResponse: {response}")
            return False
        return False

    def _parse_questions(self, response: str) -> List[Dict]:
        """
        Parse the response to extract follow-up questions.
        """
        questions = []
        try:
            if "<follow_up_questions>" in response:
                start_tag = "<follow_up_questions>"
                end_tag = "</follow_up_questions>"
                start_pos = response.find(start_tag)
                end_pos = response.find(end_tag) + len(end_tag)
                questions_text = response[start_pos:end_pos]
                root = ET.fromstring(questions_text)
                for question in root.findall("question"):
                    questions.append({
                        "question": question.text.strip(),
                        "type": "depth"
                    })
                
                self.add_event(sender=self.name, tag="follow_up_questions", 
                             content="Parsed questions:\n" + 
                                    "\n".join([f"- {q['question']}" for q in questions]))
        except Exception as e:
            self.add_event(sender=self.name, tag="error", 
                          content=f"Error parsing questions: {str(e)}\nResponse: {response}")
        return questions

SECTION_WRITER_PROMPT = """
You are a professional biography writer responsible for crafting and updating biography sections. Your output must be factual, engaging, and based strictly on provided source materials.

Input Context:
<section_path>{section_path}</section_path>
<update_plan>{update_plan}</update_plan>
<current_content>{current_content}</current_content>
<relevant_memories>{relevant_memories}</relevant_memories>

Core Responsibilities:
1. Write/update the biography section according to the update plan
2. Generate targeted follow-up questions to gather additional relevant information

Requirements for Section Writing:
1. Content Standards
   - Use ONLY information explicitly present in provided memories
   - Follow the update plan precisely
   - NO speculation, assumptions, or creative embellishments
   - Maintain strict factual accuracy
2. Writing Style
   - Professional biographical tone
   - Third-person perspective
   - Clear paragraph structure
   - Smooth transitions between ideas
   - Chronological flow where appropriate
   - Active voice preferred
   - Concise yet engaging narrative
3. Memory Integration Rules
   - Reference only provided memories
   - Integrate information naturally into the narrative
   - Select relevant details based on update plan
   - Maintain context when incorporating quotes
   - Exclude irrelevant memories even if provided

Requirements for Follow-Up Questions:
- Target specific information gaps
- Be clear and direct
- Focus on one topic per question
- Aim to enhance the current section

Required Output Format:
<section_update>
    <content>
[Write biography section here]
- Use plain text only
- Include paragraph breaks
- No formatting tags
- No markdown
    </content>
</section_update>

<follow_up_questions>
    <question>[Single specific question focused on filling information gaps]</question>
    <question>[Another specific question to clarify or expand content]</question>
    [Add more questions as needed]
</follow_up_questions>
"""

class GetSectionInput(BaseModel):
    path: str = Field(description="Path to the section to retrieve")

class UpdateSectionInput(BaseModel):
    path: str = Field(description="Path to the section to update")
    content: str = Field(description="New content for the section")

class AddSectionInput(BaseModel):
    path: str = Field(description="Full path to the new section (e.g., '1 Early Life/1.1 Childhood')")
    content: str = Field(description="Content of the new section")

class SaveBiographyInput(BaseModel):
    pass  # No input needed for saving

class SaveBiography(BaseTool):
    name: str = "save_biography"
    description: str = "Save the current state of the biography to file"
    args_schema: Type[BaseModel] = SaveBiographyInput
    biography: Biography

    def _run(self, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        try:
            self.biography.save()
            self.biography.export_to_markdown()
            return "Successfully saved biography to file"
        except Exception as e:
            raise ToolException(f"Error saving biography: {e}")

class GetSection(BaseTool):
    name: str = "get_section"
    description: str = "Retrieve content of a biography section by its path"
    args_schema: Type[BaseModel] = GetSectionInput
    biography: Biography

    def _run(self, path: str, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        section = self.biography.get_section_by_path(path)
        if not section:
            return f"Section at path '{path}' not found"
        return section.content

class UpdateSection(BaseTool):
    name: str = "update_section"
    description: str = "Update content of an existing section"
    args_schema: Type[BaseModel] = UpdateSectionInput
    biography: Biography

    def _run(self, path: str, content: str, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        section = self.biography.update_section(path, content)
        if not section:
            raise ToolException(f"Section at path '{path}' not found")
        return f"Successfully updated section at path '{path}'"

class AddSection(BaseTool):
    name: str = "add_section"
    description: str = "Add a new section to the biography"
    args_schema: Type[BaseModel] = AddSectionInput
    biography: Biography

    def _run(self, path: str, content: str, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        try:
            self.biography.add_section(path, content)
            return f"Successfully added section at path '{path}'"
        except Exception as e:
            raise ToolException(f"Error adding section: {e}")