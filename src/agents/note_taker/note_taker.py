# Python standard library imports
from typing import Dict, List, TYPE_CHECKING, Optional, Type, TypedDict
import os
from dotenv import load_dotenv
import asyncio
from datetime import datetime

from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool, ToolException
from langchain_core.callbacks.manager import CallbackManagerForToolRun


from agents.base_agent import BaseAgent
from agents.interviewer.interviewer import Recall
from agents.note_taker.prompts import get_prompt
from agents.note_taker.tools import AddInterviewQuestion, DecideFollowups, UpdateSessionNote
from agents.prompt_utils import format_prompt
from content.memory_bank.memory_bank_base import MemoryBankBase
from interview_session.session_models import Participant, Message
from utils.logger import SessionLogger

if TYPE_CHECKING:
    from interview_session.interview_session import InterviewSession
    

load_dotenv()

class NoteTakerConfig(TypedDict, total=False):
    """Configuration for the NoteTaker agent."""
    user_id: str

class NoteTaker(BaseAgent, Participant):
    def __init__(self, config: NoteTakerConfig, interview_session: 'InterviewSession'):
        BaseAgent.__init__(
            self,name="NoteTaker",
            description="Agent that takes notes and manages the user's memory bank",
            config=config
        )
        Participant.__init__(self, title="NoteTaker", interview_session=interview_session)
        
        # Config variables
        self.user_id = config.get("user_id")
        self.max_events_len = int(os.getenv("MAX_EVENTS_LEN", 40))
        self.max_consideration_iterations = int(os.getenv("MAX_CONSIDERATION_ITERATIONS", 3))

        # New memories added in current session
        self.new_memories = []  

        # Locks and processing flags
        self._notes_lock = asyncio.Lock()   # Lock for write_session_notes
        self._memory_lock = asyncio.Lock()  # Lock for update_memory_bank
        self.processing_in_progress = False # Signal to indicate if processing is in progress
        
        self.tools = {
            "update_memory_bank": UpdateMemoryBank(
                memory_bank=self.interview_session.memory_bank,
                note_taker=self
            ),
            "update_session_note": UpdateSessionNote(session_note=self.interview_session.session_note),
            "add_interview_question": AddInterviewQuestion(session_note=self.interview_session.session_note),
            "recall": Recall(memory_bank=self.interview_session.memory_bank),
            "decide_followups": DecideFollowups()
        }
            
    async def on_message(self, message: Message):
        '''Handle incoming messages'''
        if not self.interview_session.session_in_progress:
            return  # Ignore messages after session ended
        
        print(f"{datetime.now()} ✅ Note taker received message from {message.role}")
        self.add_event(sender=message.role, tag="message", content=message.content)
        
        if message.role == "User" and self.interview_session.session_in_progress:
            asyncio.create_task(self._process_user_message())

    async def _process_user_message(self):
        self.processing_in_progress = True
        try:
            # Run both updates concurrently, each with their own lock
            await asyncio.gather(
                self._locked_write_session_notes(),
                self._locked_update_memory_bank()
            )
        finally:
            self.processing_in_progress = False

    async def _locked_write_session_notes(self) -> None:
        """Wrapper to handle write_session_notes with lock"""
        async with self._notes_lock:
            await self.write_session_notes()

    async def _locked_update_memory_bank(self) -> None:
        """Wrapper to handle update_memory_bank with lock"""
        async with self._memory_lock:
            await self.update_memory_bank()

    async def write_session_notes(self) -> None:
        """Process user's response by updating session notes and considering follow-up questions."""
        # First update the direct response in session notes
        await self.update_session_note()
        
        # Then consider and propose follow-up questions if appropriate
        await self.consider_and_propose_followups()

    async def consider_and_propose_followups(self) -> None:
        """Determine if follow-up questions should be proposed and propose them if appropriate."""
        # Get prompt for considering and proposing followups

        iterations = 0
        while iterations < self.max_consideration_iterations:
            ## Decide if we need to propose follow-ups + propose follow-ups if needed
            prompt = self._get_formatted_prompt("consider_and_propose_followups")
            self.add_event(sender=self.name, tag="consider_and_propose_followups_prompt", content=prompt)

            tool_call = await self.call_engine_async(prompt)
            self.add_event(sender=self.name, tag="consider_and_propose_followups_response", content=tool_call)

            tool_responses = self.handle_tool_calls(tool_call)

            if "add_interview_question" in tool_call:
                SessionLogger.log_to_file("chat_history", f"[PROPOSE_FOLLOWUPS]\n{tool_call}")
                SessionLogger.log_to_file("chat_history", f"{self.interview_session.session_note.visualize_topics()}")
                break
            elif "recall" in tool_call:
                # Get recall response and confidence level
                self.add_event(sender=self.name, tag="recall_response", content=tool_responses)
            else:
                break
            iterations += 1
        
        if iterations >= self.max_consideration_iterations:
            self.add_event(
                sender="system",
                tag="error",
                content=f"Exceeded maximum number of consideration iterations ({self.max_consideration_iterations})"
            )

    async def update_memory_bank(self) -> None:
        """Process the latest conversation and update the memory bank if needed."""
        prompt = self._get_formatted_prompt("update_memory_bank")
        self.add_event(sender=self.name, tag="update_memory_bank_prompt", content=prompt)
        response = await self.call_engine_async(prompt)
        self.add_event(sender=self.name, tag="update_memory_bank_response", content=response)
        self.handle_tool_calls(response)

    async def update_session_note(self) -> None:
        prompt = self._get_formatted_prompt("update_session_note")
        self.add_event(sender=self.name, tag="update_session_note_prompt", content=prompt)
        response = await self.call_engine_async(prompt)
        self.add_event(sender=self.name, tag="update_session_note_response", content=response)
        self.handle_tool_calls(response)
    
    def _get_formatted_prompt(self, prompt_type: str) -> str:
        '''Gets the formatted prompt for the NoteTaker agent.'''
        prompt = get_prompt(prompt_type)
        if prompt_type == "consider_and_propose_followups":
            # Get all message events
            events = self.get_event_stream_str(filter=[
                {"tag": "message"},
                {"sender": self.name, "tag": "recall_response"},
            ], as_list=True)
            
            recent_events = events[-self.max_events_len:] if len(events) > self.max_events_len else events
            
            return format_prompt(prompt, {
                "event_stream": "\n".join(recent_events),
                "questions_and_notes": self.interview_session.session_note.get_questions_and_notes_str(),
                "tool_descriptions": self.get_tools_description(
                    selected_tools=["recall", "add_interview_question"]
                )
            })
        elif prompt_type == "update_memory_bank":
            events = self.get_event_stream_str(filter=[
                {"tag": "message"}, 
                {"sender": self.name, "tag": "update_memory_bank_response"},
            ], as_list=True)
            current_qa = events[-2:] if len(events) >= 2 else []
            previous_events = events[:-2] if len(events) >= 2 else events
            
            if len(previous_events) > self.max_events_len:
                previous_events = previous_events[-self.max_events_len:]
            
            return format_prompt(prompt, {
                "previous_events": "\n".join(previous_events),
                "current_qa": "\n".join(current_qa),
                "tool_descriptions": self.get_tools_description(selected_tools=["update_memory_bank"])
            })
        elif prompt_type == "update_session_note":
            events = self.get_event_stream_str(filter=[{"tag": "message"}], as_list=True)
            current_qa = events[-2:] if len(events) >= 2 else []
            previous_events = events[:-2] if len(events) >= 2 else events
            
            if len(previous_events) > self.max_events_len:
                previous_events = previous_events[-self.max_events_len:]
            
            return format_prompt(prompt, {
                "previous_events": "\n".join(previous_events),
                "current_qa": "\n".join(current_qa),
                "questions_and_notes": self.interview_session.session_note.get_questions_and_notes_str(hide_answered="qa"),
                "tool_descriptions": self.get_tools_description(selected_tools=["update_session_note"])
            })
    
    def add_new_memory(self, memory: Dict):
        """Track newly added memory"""
        self.new_memories.append(memory)

    def get_session_memories(self) -> List[Dict]:
        """Get all memories added during current session"""
        return self.new_memories



class UpdateMemoryBankInput(BaseModel):
    title: str = Field(description="A concise but descriptive title for the memory")
    text: str = Field(description="A clear summary of the information")
    metadata: dict = Field(description=(
        "Additional metadata about the memory. "
        "This can include topics, people mentioned, emotions, locations, dates, relationships, life events, achievements, goals, aspirations, beliefs, values, preferences, hobbies, interests, education, work experience, skills, challenges, fears, dreams, etc. "
        "Of course, you don't need to include all of these in the metadata, just the most relevant ones."
    ))
    importance_score: int = Field(description=(
        "This field represents the importance of the memory on a scale from 1 to 10. "
        "A score of 1 indicates everyday routine activities like brushing teeth or making the bed. "
        "A score of 10 indicates major life events like a relationship ending or getting accepted to college. "
        "Use this scale to rate how significant this memory is likely to be."
    ))
    source_interview_response: str = Field(description=(
        "The original user response from the interview that this memory is derived from. "
        "This should be the exact message from the user that contains this information."
    ))

class UpdateMemoryBank(BaseTool):
    """Tool for updating the memory bank."""
    name: str = "update_memory_bank"
    description: str = "A tool for storing new memories in the memory bank."
    args_schema: Type[BaseModel] = UpdateMemoryBankInput
    memory_bank: MemoryBankBase = Field(...)  # Use the base class for type hint
    note_taker: NoteTaker = Field(...)

    def _run(
        self,
        title: str,
        text: str,
        metadata: dict,
        importance_score: int,
        source_interview_response: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        try:
            memory = self.memory_bank.add_memory(
                title=title, 
                text=text, 
                metadata=metadata, 
                importance_score=importance_score,
                source_interview_response=source_interview_response
            )
            self.note_taker.add_new_memory(memory.to_dict())
            return f"Successfully stored memory: {title}"
        except Exception as e:
            raise ToolException(f"Error storing memory: {e}")