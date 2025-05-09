import os
from typing import TYPE_CHECKING
from interview_session.session_models import Participant, Message
from utils.speech.speech_to_text import create_stt_engine
import time
from dotenv import load_dotenv

load_dotenv()

from utils.constants.colors import RESET, ORANGE, BLUE

if TYPE_CHECKING:
    from interview_session.interview_session import InterviewSession

class User(Participant):
    def __init__(self, user_id: str, interview_session: 'InterviewSession', enable_voice_input: bool = False):
        super().__init__(title="User", interview_session=interview_session)
        self._user_id = user_id
        self._stt_engine = create_stt_engine()
        self._voice_enabled = enable_voice_input
        
    async def on_message(self, message: Message):
        self.show_last_message_history(message)
        
        if self._voice_enabled:
            print(f"{BLUE}[1] Type response")
            print(f"[2] Voice response{RESET}")
            choice = input("Choose input method (1/2): ").strip()
            
            if choice == "2":
                user_response = self.get_voice_input()
            else:
                user_response = input(f"{ORANGE}User: {RESET}")
        else:
            user_response = input(f"{ORANGE}User: {RESET}")
            
        self.interview_session.add_message_to_chat_history(self.title, user_response)
        
    def get_voice_input(self) -> str:
        """Record and transcribe user's voice input"""
        audio_path = f"{os.getenv('DATA_DIR', 'data')}/{self._user_id}/audio_inputs/input_{int(time.time())}.wav"
        
        try:
            # Record audio
            self._stt_engine.record_audio(audio_path)
            print(f"{BLUE}Transcribing...{RESET}")
            
            # Transcribe audio
            transcribed_text = self._stt_engine.transcribe(audio_path)
            print(f"{ORANGE}User (voice): {transcribed_text}{RESET}")
            
            return transcribed_text
            
        except Exception as e:
            print(f"Error recording/transcribing audio: {e}")
            print("Falling back to text input...")
            return input(f"{ORANGE}User: {RESET}")
        
    def show_last_message_history(self, message: Message):
        print(f"{message.role}: {message.content}")