from typing import Dict, List, TYPE_CHECKING, Optional
import asyncio
from agents.biography_team.base_biography_agent import BiographyConfig, BiographyTeamAgent

from agents.biography_team.session_summary_writer.prompts import (
    SESSION_SUMMARY_PROMPT,
    INTERVIEW_QUESTIONS_PROMPT,
    TOPIC_EXTRACTION_PROMPT
)
from agents.biography_team.session_summary_writer.tools import UpdateLastMeetingSummary, UpdateUserPortrait, DeleteInterviewQuestion
from agents.shared.feedback_prompts import SIMILAR_QUESTIONS_WARNING, PROCEED_WITH_WARNING_OUTPUT_FORMAT
from content.memory_bank.memory import Memory
from agents.biography_team.models import FollowUpQuestion
from agents.shared.memory_tools import Recall
from agents.shared.note_tools import AddInterviewQuestion
from content.question_bank.question import SimilarQuestionsGroup
from utils.llm.xml_formatter import extract_tool_arguments, extract_tool_calls_xml
from utils.formatter import format_similar_questions

if TYPE_CHECKING:
    from interview_session.interview_session import InterviewSession


class SessionSummaryWriter(BiographyTeamAgent):
    def __init__(self, config: BiographyConfig, interview_session: 'InterviewSession'):
        super().__init__(
            name="SessionSummaryWriter",
            description="Prepares end-of-session summaries "
                        "and manages interview questions",
            config=config,
            interview_session=interview_session
        )
        self._session_note = self.interview_session.session_note
        self._max_consideration_iterations = 3

        # Event for selected topics (used to wait for topics to be set)
        self._selected_topics_event = asyncio.Event()
        self._selected_topics = None

        # Initialize all tools
        self.tools = {
            # Summary tools
            "update_last_meeting_summary": UpdateLastMeetingSummary(
                session_note=self._session_note
            ),
            "update_user_portrait": UpdateUserPortrait(
                session_note=self._session_note
            ),
            # Question tools
            "add_interview_question": AddInterviewQuestion(
                session_note=self._session_note,
                historical_question_bank= \
                    self.interview_session.historical_question_bank,
                proposer="SessionSummaryWriter"
            ),
            "delete_interview_question": DeleteInterviewQuestion(
                session_note=self._session_note
            ),
            "recall": Recall(
                memory_bank=self.interview_session.memory_bank
            )
        }

    async def wait_for_selected_topics(self) -> List[str]:
        """Wait for selected topics to be set from user"""
        await self._selected_topics_event.wait()
        return self._selected_topics

    def set_selected_topics(self, topics: List[str]):
        """Set selected topics from user and trigger the generation event"""
        self._selected_topics = topics
        self._selected_topics_event.set()

    async def extract_session_topics(self) -> List[str]:
        """Extract main topics covered in the session from memories."""
        new_memories: List[Memory] = await self.interview_session.get_session_memories()

        # Create prompt
        prompt = TOPIC_EXTRACTION_PROMPT.format(memories_text='\n\n'.join(
            [memory.to_xml(include_source=True) for memory in new_memories]))
        self.add_event(sender=self.name,
                       tag="topic_extraction_prompt", content=prompt)

        # Get response from LLM
        response = await self.call_engine_async(prompt)
        self.add_event(sender=self.name,
                       tag="topic_extraction_response", content=response)

        # Parse topics from response (one per line)
        if "None" in response:
            return []
        topics = [
            topic.strip()
            for topic in response.split('\n')
            if topic.strip()
        ]

        return topics

    async def update_session_note(self, new_memories: List[Memory], follow_up_questions: List[Dict]):
        """Update session notes with new memories and follow-up questions."""
        # First update summaries and user portrait (can be done immediately)
        await self._update_session_summary(new_memories)

        # Wait for selected topics before managing interview questions
        selected_topics = await self.wait_for_selected_topics()
        await self._rebuild_interview_questions(follow_up_questions, selected_topics)

    async def _update_session_summary(self, new_memories: List[Memory]):
        """Update session summary and user portrait."""
        prompt = self._get_summary_prompt(new_memories)
        self.add_event(sender=self.name, tag="summary_prompt", content=prompt)

        response = await self.call_engine_async(prompt)
        self.add_event(sender=self.name,
                       tag="summary_response", content=response)

        self.handle_tool_calls(response)

    async def _rebuild_interview_questions(self, follow_up_questions: List[Dict], selected_topics: Optional[List[str]] = None):
        """Rebuild interview questions list with only essential questions."""
        # Store old questions and notes and clear them
        old_questions_and_notes = self._session_note.get_questions_and_notes_str()
        self._session_note.clear_questions()

        iterations = 0
        previous_tool_call = None
        similar_questions: List[SimilarQuestionsGroup] = []
        
        while iterations < self._max_consideration_iterations:
            prompt = self._get_questions_prompt(
                follow_up_questions, 
                old_questions_and_notes, 
                selected_topics,
                previous_tool_call=previous_tool_call,
                similar_questions=similar_questions
            )
            self.add_event(
                sender=self.name,
                tag=f"questions_prompt_{iterations}", 
                content=prompt
            )

            response = await self.call_engine_async(prompt)
            self.add_event(
                sender=self.name,
                tag=f"questions_response_{iterations}",
                content=response
            )

            # Check if agent wants to proceed with previous tool calls
            if "<proceed>true</proceed>" in response.lower():
                self.add_event(
                    sender=self.name,
                    tag=f"feedback_loop_{iterations}",
                    content="Agent chose to proceed with previous questions"
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
                similar_questions = []
                for question in proposed_questions:
                    results = \
                        self.interview_session.historical_question_bank.search_questions(
                        query=question, k=3
                    )
                    if results:
                        similar_questions.append(SimilarQuestionsGroup(
                            proposed=question,
                            similar=results
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
                sender=self.name,
                tag="warning",
                content=(
                    f"Reached max iterations "
                    f"without completing question updates"
                )
            )

    def _get_summary_prompt(self, new_memories: List[Memory]) -> str:
        summary_tool_names = [
            "update_last_meeting_summary", "update_user_portrait"]
        return SESSION_SUMMARY_PROMPT.format(
            new_memories="\n\n".join(m.to_xml() for m in new_memories),
            user_portrait=self._session_note.get_user_portrait_str(),
            tool_descriptions=self.get_tools_description(summary_tool_names)
        )

    def _get_questions_prompt(
        self, 
        follow_up_questions: List[FollowUpQuestion], 
        old_questions_and_notes: str, 
        selected_topics: Optional[List[str]] = None,
        previous_tool_call: Optional[str] = None,
        similar_questions: Optional[List[SimilarQuestionsGroup]] = None
    ) -> str:
        question_tool_names = ["add_interview_question", "recall"]
        events = self.get_event_stream_str(
            filter=[
                {"sender": self.name, "tag": "recall_response"}
            ],
            as_list=True
        )

        # Format warning if needed
        warning = (
            SIMILAR_QUESTIONS_WARNING.format(
                previous_tool_call=previous_tool_call,
                similar_questions=format_similar_questions(
                    similar_questions)
            ) if similar_questions and previous_tool_call 
            else ""
        )

        return INTERVIEW_QUESTIONS_PROMPT.format(
            questions_and_notes=old_questions_and_notes,
            selected_topics="\n".join(
                selected_topics) if selected_topics else "",
            follow_up_questions="\n\n".join([
                q.to_xml() for q in follow_up_questions
            ]),
            event_stream="\n".join(events[-10:]),
            similar_questions_warning=warning,
            warning_output_format=PROCEED_WITH_WARNING_OUTPUT_FORMAT \
                  if similar_questions else "",
            tool_descriptions=self.get_tools_description(question_tool_names)
        )
