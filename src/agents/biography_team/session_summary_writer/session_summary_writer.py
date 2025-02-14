from typing import Dict, List, TYPE_CHECKING, Optional
import asyncio
from agents.biography_team.base_biography_agent import BiographyConfig, BiographyTeamAgent

from agents.biography_team.session_summary_writer.prompts import (
    SESSION_SUMMARY_PROMPT,
    INTERVIEW_QUESTIONS_PROMPT,
    TOPIC_EXTRACTION_PROMPT
)
from agents.biography_team.session_summary_writer.tools import UpdateLastMeetingSummary, UpdateUserPortrait, AddInterviewQuestion, DeleteInterviewQuestion, Recall
from content.memory_bank.memory import Memory


if TYPE_CHECKING:
    from interview_session.interview_session import InterviewSession


class SessionSummaryWriter(BiographyTeamAgent):
    def __init__(self, config: BiographyConfig, interview_session: 'InterviewSession'):
        super().__init__(
            name="SessionSummaryWriter",
            description="Prepares end-of-session summaries and manages interview questions",
            config=config,
            interview_session=interview_session
        )
        self.session_note = self.interview_session.session_note
        self.max_consideration_iterations = 3

        # Event for selected topics (used to wait for topics to be set)
        self._selected_topics_event = asyncio.Event()
        self._selected_topics = None

        # Initialize all tools
        self.tools = {
            # Summary tools
            "update_last_meeting_summary": UpdateLastMeetingSummary(
                session_note=self.session_note
            ),
            "update_user_portrait": UpdateUserPortrait(
                session_note=self.session_note
            ),

            # Question tools
            "add_interview_question": AddInterviewQuestion(
                session_note=self.session_note
            ),
            "delete_interview_question": DeleteInterviewQuestion(
                session_note=self.session_note
            ),
            "recall": Recall(
                memory_bank=self.interview_session.memory_bank
            )
        }

    async def wait_for_selected_topics(self) -> List[str]:
        """Wait for selected topics to be set"""
        await self._selected_topics_event.wait()
        return self._selected_topics

    def set_selected_topics(self, topics: List[str]):
        """Set selected topics and trigger the event"""
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
        topics = [
            topic.strip()
            for topic in response.split('\n')
            if topic.strip()
        ]

        return topics

    async def update_session_note(self, new_memories: List[Dict], follow_up_questions: List[Dict]):
        """Update session notes with new memories and follow-up questions."""
        # First update summaries and user portrait (can be done immediately)
        await self._update_session_summary(new_memories)

        # Wait for selected topics before managing interview questions
        selected_topics = await self.wait_for_selected_topics()
        await self._manage_interview_questions(follow_up_questions, selected_topics)

    async def _update_session_summary(self, new_memories: List[Dict]):
        """Update session summary and user portrait."""
        prompt = self._get_summary_prompt(new_memories)
        self.add_event(sender=self.name, tag="summary_prompt", content=prompt)

        response = await self.call_engine_async(prompt)
        self.add_event(sender=self.name,
                       tag="summary_response", content=response)

        self.handle_tool_calls(response)

    async def _manage_interview_questions(self, follow_up_questions: List[Dict], selected_topics: Optional[List[str]] = None):
        """Rebuild interview questions list with only essential questions.

        Process:
        1. Clear all existing questions
        2. Perform memory searches if needed
        3. Add only important unanswered questions and worthy follow-ups

        Will iterate up to max_consideration_iterations times:
        - Each iteration either does memory search or takes actions
        - Breaks when actions are taken or max iterations reached
        """
        # Store old questions and notes and clear them
        old_questions_and_notes = self.session_note.get_questions_and_notes_str()
        self.session_note.clear_questions()

        iterations = 0
        while iterations < self.max_consideration_iterations:
            prompt = self._get_questions_prompt(
                follow_up_questions, old_questions_and_notes, selected_topics)
            self.add_event(sender=self.name,
                           tag="questions_prompt", content=prompt)

            tool_calls = await self.call_engine_async(prompt)
            self.add_event(sender=self.name,
                           tag="questions_response", content=tool_calls)

            try:
                # Check if this is a recall or action response
                is_recall = (
                    "<recall>" in tool_calls and
                    not "<add_interview_question>" in tool_calls
                )

                tool_response = self.handle_tool_calls(tool_calls)

                if is_recall:
                    # If it's a recall, add the response to events and continue
                    self.add_event(
                        sender=self.name,
                        tag="recall_response",
                        content=tool_response
                    )
                    iterations += 1
                else:
                    # If it's actions, log success and break
                    self.add_event(
                        sender=self.name,
                        tag="question_actions",
                        content="Successfully rebuilt interview questions list"
                    )
                    break

            except Exception as e:
                error_msg = (
                    f"Error rebuilding interview questions: {str(e)}\n"
                    f"Response: {tool_calls}"
                )
                self.add_event(sender=self.name, tag="error",
                               content=error_msg)
                raise

        if iterations >= self.max_consideration_iterations:
            self.add_event(
                sender=self.name,
                tag="warning",
                content=(
                    f"Reached maximum iterations ({self.max_consideration_iterations}) "
                    f"without taking actions"
                )
            )

    def _get_summary_prompt(self, new_memories: List[Dict]) -> str:
        summary_tool_names = [
            "update_last_meeting_summary", "update_user_portrait"]
        return SESSION_SUMMARY_PROMPT.format(
            new_memories="\n".join([f"- {m['text']}" for m in new_memories]),
            user_portrait=self.session_note.get_user_portrait_str(),
            tool_descriptions=self.get_tools_description(summary_tool_names)
        )

    def _get_questions_prompt(self, follow_up_questions: List[Dict], old_questions_and_notes: str, selected_topics: Optional[List[str]] = None) -> str:
        question_tool_names = ["add_interview_question", "recall"]
        events = self.get_event_stream_str(
            filter=[
                {"sender": self.name, "tag": "recall_response"}
            ],
            as_list=True
        )

        return INTERVIEW_QUESTIONS_PROMPT.format(
            questions_and_notes=old_questions_and_notes,
            selected_topics="\n".join(
                selected_topics) if selected_topics else "",
            follow_up_questions="\n\n".join([
                "<question>\n"
                f"<content>{q['content']}</content>\n"
                f"<context>{q['context']}</context>\n"
                "</question>"
                for q in follow_up_questions
            ]),
            event_stream="\n".join(events[-10:]),
            tool_descriptions=self.get_tools_description(question_tool_names)
        )
