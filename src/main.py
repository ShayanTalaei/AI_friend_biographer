import argparse
import os
from dotenv import load_dotenv
import asyncio
import contextlib

from interview_session.interview_session import InterviewSession
from utils.speech.speech_to_text import PYAUDIO_AVAILABLE

load_dotenv(override=True)

async def run_terminal_mode(args):
    if args.restart:
        os.system(f"rm -rf {os.getenv('LOGS_DIR')}/{args.user_id}")
        os.system(f"rm -rf {os.getenv('DATA_DIR')}/{args.user_id}")
        print(f"Cleared data for user {args.user_id}")
    
    # Check if voice features are available when requested
    if (args.voice_input or args.voice_output) and not PYAUDIO_AVAILABLE:
        print("\nWarning: Voice features were requested but PyAudio is not installed.")
        print("Continuing without voice features...\n")
        args.voice_input = False
        args.voice_output = False
    
    interview_session = InterviewSession(
        interaction_mode='agent' if args.user_agent else 'terminal',
        user_config={
            "user_id": args.user_id,
            "enable_voice": args.voice_input,
            "restart": args.restart
        },
        interview_config={
            "enable_voice": args.voice_output
        },
        max_turns=args.max_turns
    )
    
    with contextlib.suppress(KeyboardInterrupt):
        await interview_session.run()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run interviewer with specific user and session')

    # Three modes: terminal, server, and setup_db
    parser.add_argument('--mode', default='terminal')
    
    # Terminal mode arguments
    parser.add_argument('--user_id', help='User ID for the session')
    parser.add_argument('--user_agent', action='store_true', default=False, 
                        help='Use user agent')
    parser.add_argument('--voice_output', action='store_true', default=False, 
                        help='Enable voice output')
    parser.add_argument('--voice_input', action='store_true', default=False, 
                        help='Enable voice input')
    parser.add_argument('--restart', action='store_true', default=False, 
                        help='Restart the session')
    parser.add_argument('--max_turns', type=int, default=None,
                        help='Maximum number of turns before ending the session')
    
    # Setup_db mode arguments
    parser.add_argument('--reset', action='store_true', help='Reset database (clear all data)')
    
    args = parser.parse_args()
    
    # Run the appropriate mode
    if args.mode == 'terminal':
        if not args.user_id:
            parser.error("--user_id is required for terminal mode")
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(run_terminal_mode(args))
    else:
        parser.error(f"Invalid mode: {args.mode}")
    
