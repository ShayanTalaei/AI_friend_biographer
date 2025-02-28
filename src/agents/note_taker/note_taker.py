from typing import List, TYPE_CHECKING, TypedDict
import os
from dotenv import load_dotenv
import asyncio
import time


from agents.base_agent import BaseAgent
from agents.note_taker.prompts import get_prompt
from agents.note_taker.tools import UpdateSessionNote, UpdateMemoryBank, AddHistoricalQuestion
from agents.shared.memory_tools import Recall
from agents.shared.note_tools import AddInterviewQuestion
from agents.shared.feedback_prompts import SIMILAR_QUESTIONS_WARNING, PROCEED_WITH_WARNING_OUTPUT_FORMAT
from content.question_bank.question import QuestionSearchResult, SimilarQuestionsGroup
from utils.llm.prompt_utils import format_prompt
from utils.llm.xml_formatter import extract_tool_arguments, extract_tool_calls_xml
from utils.logger.session_logger import SessionLogger
from utils.formatter import format_similar_questions
from interview_session.session_models import Participant, Message
from content.memory_bank.memory import Memory

if TYPE_CHECKING:
    from interview_session.interview_session import InterviewSession


load_dotenv()


class NoteTakerConfig(TypedDict, total=False):
    """Configuration for the NoteTaker agent."""
    user_id: str


class NoteTaker(BaseAgent, Participant):
    def __init__(self, config: NoteTakerConfig, interview_session: 'InterviewSession'):
        BaseAgent.__init__(
            self, name="NoteTaker",
            description="Agent that takes notes and manages the user's memory bank",
            config=config
        )
        Participant.__init__(self, title="NoteTaker",
                             interview_session=interview_session)

        # Config variables
        self._max_events_len = int(os.getenv("MAX_EVENTS_LEN", 30))
        self._max_consideration_iterations = int(
            os.getenv("MAX_CONSIDERATION_ITERATIONS", 3))

        # New memories added in current session
        self._new_memories: List[Memory] = []
        # Mapping from temporary memory IDs to real IDs
        self._memory_id_map = {}

        # Track last interviewer message
        self._last_interviewer_message = None

        # Locks and processing flags
        self.processing_in_progress = False # If processing is in progress
        self._pending_tasks = 0             # Track number of pending tasks
        self._notes_lock = asyncio.Lock()   # Lock for _write_notes_and_questions
        self._memory_lock = asyncio.Lock()  # Lock for update_memory_bank
        self._tasks_lock = asyncio.Lock()   # Lock for updating task counter

        # Tools agent can use
        self.tools = {
            "update_memory_bank": UpdateMemoryBank(
                memory_bank=self.interview_session.memory_bank,
                on_memory_added=self._add_new_memory,
                update_memory_map=self._update_memory_map,
                get_current_response=self._get_safe_current_response
            ),
            "add_historical_question": AddHistoricalQuestion(
                question_bank=self.interview_session.historical_question_bank,
                memory_bank=self.interview_session.memory_bank,
                get_real_memory_ids=self._get_real_memory_ids
            ),
            "update_session_note": UpdateSessionNote(
                session_note=self.interview_session.session_note
            ),
            "add_interview_question": AddInterviewQuestion(
                session_note=self.interview_session.session_note,
                historical_question_bank=self.interview_session.historical_question_bank,
                proposed_question_bank=self.interview_session.proposed_question_bank,
                proposer="NoteTaker"
            ),
            "recall": Recall(
                memory_bank=self.interview_session.memory_bank
            ),
        }

    async def on_message(self, message: Message):
        '''Handle incoming messages'''
        SessionLogger.log_to_file(
            "execution_log",
            f"[NOTIFY] Note taker received message from {message.role}"
        )

        if message.role == "Interviewer":
            self._last_interviewer_message = message
        elif message.role == "User":
            if self._last_interviewer_message:
                asyncio.create_task(self._process_qa_pair(
                    interviewer_message=self._last_interviewer_message,
                    user_message=message
                ))
                self._last_interviewer_message = None

    async def _process_qa_pair(self, interviewer_message: Message, user_message: Message):
        """Process a Q&A pair with task tracking"""
        await self._increment_pending_tasks()
        try:
            # Run both updates concurrently, each with their own lock
            await asyncio.gather(
                self._locked_write_notes_and_questions(
                    interviewer_message, user_message),
                self._locked_write_memory_and_question_bank(
                    interviewer_message, user_message)
            )
        finally:
            await self._decrement_pending_tasks()

    async def _locked_write_notes_and_questions(self, interviewer_message: Message, user_message: Message) -> None:
        """Wrapper to handle _write_notes_and_questions with lock"""
        async with self._notes_lock:
            self.add_event(sender=interviewer_message.role,
                           tag="notes_lock_message", 
                           content=interviewer_message.content)
            self.add_event(sender=user_message.role,
                           tag="notes_lock_message", 
                           content=user_message.content)
            await self._write_notes_and_questions()

    async def _locked_write_memory_and_question_bank(self, interviewer_message: Message, user_message: Message) -> None:
        """Wrapper to handle update_memory_bank with lock"""
        async with self._memory_lock:
            self.add_event(sender=interviewer_message.role,
                           tag="memory_lock_message", 
                           content=interviewer_message.content)
            self.add_event(sender=user_message.role,
                           tag="memory_lock_message", 
                           content=user_message.content)
            await self._write_memory_and_question_bank()

    async def _write_notes_and_questions(self) -> None:
        """
        Process user's response by updating session notes 
        and considering follow-up questions.
        """
        # First update the direct response in session notes
        await self._update_session_note()

        # Then consider and propose follow-up questions if appropriate
        await self._propose_followups()

    async def _propose_followups(self) -> None:
        """
        Determine if follow-up questions should be proposed 
        and propose them if appropriate.
        """
        iterations = 0
        previous_tool_call = None
        similar_questions: List[SimilarQuestionsGroup] = []
        
        while iterations < self._max_consideration_iterations:
            prompt = self._get_formatted_prompt(
                "consider_and_propose_followups",
                previous_tool_call=previous_tool_call,
                similar_questions=similar_questions
            )
            
            self.add_event(
                sender=self.name,
                tag=f"consider_and_propose_followups_prompt_{iterations}",
                content=prompt
            )

            response = await self.call_engine_async(prompt)
            self.add_event(
                sender=self.name,
                tag=f"consider_and_propose_followups_response_{iterations}",
                content=response
            )

            # Check if agent wants to proceed with previous tool calls
            if "<proceed>true</proceed>" in response.lower():
                self.add_event(
                    sender=self.name,
                    tag=f"add_questions",
                    content=f"<ToolCalls>{previous_tool_call}</ToolCalls>"
                )
                # Execute the previous tool calls instead of the new response
                if previous_tool_call:
                    await self.handle_tool_calls_async(previous_tool_call)
                break

            # Extract proposed questions from add_interview_question tool calls
            proposed_questions = extract_tool_arguments(
                response, "add_interview_question", "question"
            )
            
            if not proposed_questions:
                if "recall" in response:
                    # Handle recall response
                    result = await self.handle_tool_calls_async(response)
                    self.add_event(
                        sender=self.name, 
                        tag="recall_response", 
                        content=result
                    )
                else:
                    # No questions proposed and no recall needed
                    break
            else:
                # Search for similar questions
                similar_questions: List[SimilarQuestionsGroup] = []
                for question in proposed_questions:
                    # Search in both question banks
                    historical_results = \
                        self.interview_session.historical_question_bank \
                            .search_questions(query=question, k=3)
                    proposed_results = \
                        self.interview_session.proposed_question_bank \
                            .search_questions(query=question, k=3)
                    
                    # Combine results and remove duplicates
                    all_results: List[QuestionSearchResult] = []
                    seen_questions = set()
                    
                    # Process all results and keep track of seen questions
                    for result_list in [historical_results, proposed_results]:
                        if result_list:
                            for result in result_list:
                                # Only add if we haven't seen before
                                if result.content not in seen_questions:
                                    all_results.append(result)
                                    seen_questions.add(result.content)
                    
                    # Sort by similarity score (higher score = more similar)
                    all_results.sort(key=lambda x: x.similarity_score, reverse=True)
                    
                    # Take top 3 unique results if available
                    top_results = all_results[:3] if all_results else []
                    
                    if top_results:
                        similar_questions.append(SimilarQuestionsGroup(
                            proposed=question,
                            similar=top_results
                        ))
                
                if not similar_questions:
                    # No similar questions found, proceed with adding
                    await self.handle_tool_calls_async(response)
                    break
                else:
                    # Save tool calls for next iteration
                    previous_tool_call = extract_tool_calls_xml(response)
            
            iterations += 1

        if iterations >= self._max_consideration_iterations:
            self.add_event(
                sender="system",
                tag="error",
                content=(
                    f"Exceeded maximum number of consideration iterations "
                    f"({self._max_consideration_iterations})"
                )
            )

    async def _write_memory_and_question_bank(self) -> None:
        """Process the latest conversation and update both memory and question banks."""
        prompt = self._get_formatted_prompt("update_memory_question_bank")
        self.add_event(
            sender=self.name, 
            tag="update_memory_question_bank_prompt", 
            content=prompt
        )
        response = await self.call_engine_async(prompt)
        self.add_event(
            sender=self.name, 
            tag="update_memory_question_bank_response", 
            content=response
        )
        self.handle_tool_calls(response)

    async def _update_session_note(self) -> None:
        """Update session note with user's response"""
        prompt = self._get_formatted_prompt("update_session_note")
        self.add_event(
            sender=self.name,
            tag="update_session_note_prompt",
            content=prompt
        )
        response = await self.call_engine_async(prompt)
        self.add_event(
            sender=self.name,
            tag="update_session_note_response",
            content=response
        )
        self.handle_tool_calls(response)

    def _get_formatted_prompt(self, prompt_type: str, **kwargs) -> str:
        '''Gets the formatted prompt for the NoteTaker agent.'''
        prompt = get_prompt(prompt_type)
        if prompt_type == "consider_and_propose_followups":
            # Get all message events
            events = self.get_event_stream_str(filter=[
                {"tag": "notes_lock_message"},
                {"sender": self.name, "tag": "recall_response"},
                {"tag": "add_questions"}
            ], as_list=True)

            recent_events = events[-self._max_events_len:] if len(
                events) > self._max_events_len else events

            # Format warning if needed
            similar_questions = kwargs.get('similar_questions', [])
            previous_tool_call = kwargs.get('previous_tool_call')
            warning = (
                SIMILAR_QUESTIONS_WARNING.format(
                    previous_tool_call=previous_tool_call,
                    similar_questions= \
                        format_similar_questions(similar_questions)
                ) if similar_questions and previous_tool_call 
                else ""
            )

            return format_prompt(prompt, {
                "user_portrait": self.interview_session.session_note \
                    .get_user_portrait_str(),
                "event_stream": "\n".join(recent_events),
                "questions_and_notes": (
                    self.interview_session.session_note \
                        .get_questions_and_notes_str()
                ),
                "similar_questions_warning": warning,
                "warning_output_format": PROCEED_WITH_WARNING_OUTPUT_FORMAT \
                                         if similar_questions else "",
                "tool_descriptions": self.get_tools_description(
                    selected_tools=["recall", "add_interview_question"]
                )
            })
        elif prompt_type == "update_memory_question_bank":
            events = self.get_event_stream_str(filter=[
                {"tag": "memory_lock_message"},
            ], as_list=True)
            current_qa = events[-2:] if len(events) >= 2 else []
            previous_events = events[:-2] if len(events) >= 2 else events

            if len(previous_events) > self._max_events_len:
                previous_events = previous_events[-self._max_events_len:]

            return format_prompt(prompt, {
                "user_portrait": self.interview_session.session_note.user_portrait,
                "previous_events": "\n".join(previous_events),
                "current_qa": "\n".join(current_qa),
                "tool_descriptions": self.get_tools_description(
                    selected_tools=["update_memory_bank",
                                    "add_historical_question"]
                )
            })
        elif prompt_type == "update_session_note":
            events = self.get_event_stream_str(
                filter=[{"tag": "notes_lock_message"}], as_list=True)
            current_qa = events[-2:] if len(events) >= 2 else []
            previous_events = events[:-2] if len(events) >= 2 else events

            if len(previous_events) > self._max_events_len:
                previous_events = previous_events[-self._max_events_len:]

            return format_prompt(prompt, {
                "user_portrait": self.interview_session.session_note.user_portrait,
                "previous_events": "\n".join(previous_events),
                "current_qa": "\n".join(current_qa),
                "questions_and_notes": (
                    self.interview_session.session_note \
                        .get_questions_and_notes_str(
                            hide_answered="qa"
                        )
                ),
                "tool_descriptions": self.get_tools_description(
                    selected_tools=["update_session_note"]
                )
            })

    async def get_session_memories(self) -> List[Memory]:
        """Get all memories added by note taker during current session.
        Waits for all pending memory updates to complete before returning."""
        start_time = time.time()

        SessionLogger.log_to_file(
            "execution_log",
            f"[MEMORY] Waiting for memory updates to complete..."
        )
        
        while self.processing_in_progress:
            await asyncio.sleep(0.1)
            if time.time() - start_time > 300:  # 5 minutes timeout
                SessionLogger.log_to_file(
                    "execution_log",
                    f"[MEMORY] Timeout waiting for memory updates"
                )
                break

        SessionLogger.log_to_file(
            "execution_log",
            (
                f"[MEMORY] Collected {len(self._new_memories)} memories "
                f"from current session"
            )
        )
        return self._new_memories

    def _add_new_memory(self, memory: Memory):
        """Callback to track newly added memory in the session"""
        self._new_memories.append(memory)

    def _update_memory_map(self, temp_id: str, real_id: str) -> None:
        """Callback to update the memory ID mapping"""
        self._memory_id_map[temp_id] = real_id
        SessionLogger.log_to_file("execution_log",
                                  f"[MEMORY] Write a new memory with {real_id}")

    def _get_real_memory_ids(self, temp_ids: List[str]) -> List[str]:
        """Callback to get real memory IDs from temporary IDs"""
        real_ids = [
            self._memory_id_map[temp_id]
            for temp_id in temp_ids
            if temp_id in self._memory_id_map
        ]
        return real_ids

    async def _increment_pending_tasks(self):
        """Increment the pending tasks counter"""
        async with self._tasks_lock:
            self._pending_tasks += 1
            self.processing_in_progress = True

    async def _decrement_pending_tasks(self):
        """Decrement the pending tasks counter"""
        async with self._tasks_lock:
            self._pending_tasks -= 1
            if self._pending_tasks <= 0:
                self._pending_tasks = 0
                self.processing_in_progress = False

    def _get_safe_current_response(self) -> str:
        """Safely get the current user response, with error handling."""
        try:
            messages = self.get_event_stream_str(filter=[
                {"tag": "memory_lock_message", "sender": "User"}
            ], as_list=True)
                        
            if not messages:
                return "No user response available"
            
            last_message = messages[-1]
            
            result = last_message. \
                removeprefix("<User>\n"). \
                removesuffix("\n</User>")
            
            return result
        except Exception as e:
            import traceback
            return "Error retrieving user response"
