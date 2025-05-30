from pathlib import Path
import csv
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from tiktoken import get_encoding

load_dotenv()

class EvaluationLogger:
    """Logger for evaluation results."""
    
    _current_logger = None
    
    def __init__(self, user_id: Optional[str] = None, session_id: Optional[int] = None):
        """Initialize evaluation logger.
        
        Args:
            user_id: Optional user ID to organize logs by user
            session_id: Optional session ID for session-based logging
        """
        self.user_id = user_id
        self.session_id = str(session_id) or ""
        self.base_dir = Path(os.getenv("LOGS_DIR", "logs"))
        
        # Create evaluations directory
        if user_id:
            self.eval_dir = self.base_dir / user_id / "evaluations"
        else:
            self.eval_dir = self.base_dir / "evaluations"
        self.eval_dir.mkdir(parents=True, exist_ok=True)
        
        self.tokenizer = get_encoding("cl100k_base")
    
    @classmethod
    def get_current_logger(cls) -> Optional['EvaluationLogger']:
        """Get the current logger instance."""
        return cls._current_logger
    
    @classmethod
    def setup_logger(
        cls,
        user_id: str,
        session_id: Optional[int] = None
    ) -> 'EvaluationLogger':
        """Setup a new evaluation logger.
        
        Args:
            user_id: User identifier
            session_id: Optional session identifier
        """
        logger = cls(user_id=user_id, session_id=session_id)
        cls._current_logger = logger
        return logger

    def log_prompt_response(
        self,
        evaluation_type: str,
        prompt: str,
        response: str,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Log prompt and response for an evaluation.
        
        Args:
            evaluation_type: Type of evaluation 
                (e.g., 'question_similarity', 'groundness')
            prompt: The prompt sent to the LLM
            response: The response received from the LLM
            timestamp: Optional timestamp (defaults to current time)
        """
        # Create a logs directory for prompts and responses
        logs_dir = self.eval_dir / \
            f"prompt_response_logs{'_session_' + self.session_id \
                                    if self.session_id else ''}"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        if timestamp is None:
            timestamp = datetime.now()
        
        # Create a timestamped filename
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        filename = logs_dir / f"{evaluation_type}_{timestamp_str}.log"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"=== TIMESTAMP: {timestamp.isoformat()} ===\n\n")
            f.write("=== PROMPT ===\n\n")
            f.write(prompt)
            f.write("\n\n=== RESPONSE ===\n\n")
            f.write(response)
            f.write("\n")
        
        print(f"Saved to {filename}")
    
    def log_question_similarity(
        self,
        target_question: str,
        similar_questions: List[str],
        similarity_scores: List[float],
        is_duplicate: bool,
        matched_question: str,
        explanation: str,
        proposer: str = "unknown",
        timestamp: Optional[datetime] = None
    ) -> None:
        """Log question similarity evaluation results.
        
        Args:
            target_question: The question being evaluated
            similar_questions: List of similar questions found
            similarity_scores: List of similarity scores
            is_duplicate: Whether the question is considered a duplicate
            matched_question: Content of the matched duplicate question
            explanation: Explanation of the similarity evaluation
            proposer: Name of the agent proposing this question
            timestamp: Optional timestamp (defaults to current time)
        """
        filename = self.eval_dir / "question_similarity.csv"
            
        file_exists = filename.exists()
        
        if timestamp is None:
            timestamp = datetime.now()
            
        with open(filename, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    'Timestamp',
                    'Proposer',
                    'Session ID',
                    'Target Question',
                    'Similar Questions',
                    'Similarity Scores',
                    'Is Duplicate',
                    'Matched Question',
                    'Explanation'
                ])
            
            writer.writerow([
                timestamp.isoformat(),
                proposer,
                self.session_id,
                target_question,
                '; '.join(similar_questions),
                '; '.join(f"{score:.2f}" for score in similarity_scores),
                is_duplicate,
                matched_question,
                explanation
            ])
    
    def log_response_latency(
        self,
        message_id: str,
        user_message_timestamp: datetime,
        response_timestamp: datetime,
        user_message_length: int
    ) -> None:
        """Log the latency between user message and system response.
        
        Args:
            message_id: Unique identifier for the message pair
            user_message_timestamp: When the user sent their message
            response_timestamp: When the response was delivered
            user_message_length: Length of the user's message in characters
        """
        # Create a logs directory for response latency
        logs_dir = self.eval_dir
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Calculate latency in seconds
        latency_seconds = (response_timestamp - user_message_timestamp).total_seconds()
        
        # Log to CSV file
        filename = logs_dir / "response_latency.csv"
        file_exists = filename.exists()
        
        with open(filename, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    'User Message ID',
                    'Session ID',
                    'Timestamp',
                    'Latency (seconds)',
                    'User Message Length'
                ])
            
            writer.writerow([
                message_id,
                self.session_id,
                user_message_timestamp.isoformat(),
                f"{latency_seconds:.3f}",
                user_message_length
            ])

    def log_conversation_statistics(
        self,
        total_turns: int,
        total_tokens: int,
        user_tokens: int,
        system_tokens: int,
        conversation_duration: float,
        total_memories: int,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Log statistics about the conversation.
        
        Args:
            total_turns: Total number of conversation turns
            total_tokens: Total number of tokens in the conversation
            user_tokens: Number of tokens in user messages
            system_tokens: Number of tokens in system messages
            conversation_duration: Duration of the conversation in seconds
            total_memories: Total number of memories in the session
            timestamp: Optional timestamp (defaults to current time)
        """
        # Create logs directory
        logs_dir = self.eval_dir
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        if timestamp is None:
            timestamp = datetime.now()
        
        # Log to CSV file
        filename = logs_dir / "conversation_statistics.csv"
        file_exists = filename.exists()
        
        with open(filename, 'a', newline='') as f:
            writer = csv.writer(f)
            
            # Create headers if file doesn't exist
            if not file_exists:
                headers = [
                    'Timestamp',
                    'Session ID',
                    'Total Turns',
                    'Total Tokens',
                    'User Tokens',
                    'System Tokens',
                    'Conversation Duration (seconds)',
                    'Average Tokens Per Turn',
                    'Total Memories'
                ]
                writer.writerow(headers)
            
            # Calculate average tokens per turn
            avg_tokens_per_turn = total_tokens / total_turns if total_turns > 0 else 0
            
            # Write row
            writer.writerow([
                timestamp.isoformat(),
                self.session_id,
                total_turns,
                total_tokens,
                user_tokens,
                system_tokens,
                f"{conversation_duration:.2f}",
                f"{avg_tokens_per_turn:.2f}",
                total_memories
            ]) 
    
    def log_biography_section_groundedness(
        self,
        section_id: str,
        section_title: str,
        groundedness_score: int,
        unsubstantiated_claims: List[str],
        unsubstantiated_details_explanation: List[str],
        overall_assessment: str,
        biography_version: int
    ) -> None:
        """Log biography groundedness evaluation results."""
        # Create a version-specific directory
        version_dir = self.eval_dir / f"biography_{biography_version}"
        version_dir.mkdir(parents=True, exist_ok=True)
        
        # Log to CSV file
        filename = version_dir / "groundedness_summary.csv"
        file_exists = filename.exists()
        
        with open(filename, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    'Section ID',
                    'Section Title',
                    'Groundedness Score',
                    'Overall Assessment',
                    'Unsubstantiated Claims',
                    'Missing Details',
                ])
            
            writer.writerow([
                section_id,
                section_title,
                groundedness_score,
                overall_assessment,
                '; '.join(unsubstantiated_claims),
                '; '.join(unsubstantiated_details_explanation),
            ])

    def log_biography_completeness(
        self,
        metrics: Dict[str, Any],
        unreferenced_details: List[Dict[str, Any]],
        biography_version: int
    ) -> None:
        """Log biography completeness evaluation results."""
        # Create a version-specific directory
        version_dir = self.eval_dir / f"biography_{biography_version}"
        version_dir.mkdir(parents=True, exist_ok=True)
        
        # Log to CSV file
        filename = version_dir / "completeness_summary.csv"
        
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Metric', 'Value'])
            
            writer.writerow(['Memory Coverage', f"{metrics['memory_recall']}%"])
            writer.writerow(['Total Memories', metrics['total_memories']])
            writer.writerow(['Referenced Memories', 
                             metrics['referenced_memories']])
            writer.writerow(['Unreferenced Memories Count', 
                             len(metrics['unreferenced_memories'])])
            
            if unreferenced_details:
                writer.writerow([])  # Empty row for separation
                writer.writerow(['Unreferenced Memory ID', 
                                 'Title', 'Importance Score'])
                for memory in unreferenced_details:
                    writer.writerow([
                        memory['id'],
                        memory['title'],
                        memory['importance_score']
                    ])

    def log_biography_overall_groundedness(
        self,
        overall_score: float,
        section_scores: List[Dict[str, Any]],
        biography_version: int,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Log the overall groundedness score for the entire biography.
        
        Args:
            overall_score: The overall groundedness score (0-100)
            section_scores: List of dictionaries with section scores
            biography_version: Version number of the biography
            timestamp: Optional timestamp (defaults to current time)
        """
        # Create a version-specific directory
        version_dir = self.eval_dir / f"biography_{biography_version}"
        version_dir.mkdir(parents=True, exist_ok=True)
        
        if timestamp is None:
            timestamp = datetime.now()
        
        # Log to CSV file
        filename = version_dir / "overall_groundedness.csv"
        file_exists = filename.exists()
        
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            
            # Write overall score
            writer.writerow(['Timestamp', 'Overall Groundedness Score'])
            writer.writerow([timestamp.isoformat(), f"{overall_score:.2f}%"])
            
            # Write section scores
            writer.writerow([])  # Empty row for separation
            writer.writerow(['Section ID', 'Section Title', 'Groundedness Score'])
            
            for section in section_scores:
                writer.writerow([
                    section['section_id'],
                    section['section_title'],
                    f"{section['evaluation']['groundedness_score']}%"
                ]) 

    def log_biography_comparison_evaluation(
        self,
        evaluation_data: Dict[str, Any],
        biography_version: int,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Log comparative evaluation results between two biographies.
        
        Args:
            evaluation_data: Dictionary containing evaluation results and metadata
            biography_version: Version number of our biography
            timestamp: Optional timestamp (defaults to current time)
        """
        # Create a version-specific directory
        version_dir = Path("logs") / self.user_id / "evaluations" / \
            f"biography_{biography_version}"
        version_dir.mkdir(parents=True, exist_ok=True)
        
        if timestamp is None:
            timestamp = datetime.now()
        
        # Log to CSV file
        filename = version_dir / "biography_comparisons.csv"
        file_exists = filename.exists()
        
        with open(filename, 'a', newline='') as f:
            writer = csv.writer(f)
            
            # Create headers if file doesn't exist
            if not file_exists:
                headers = [
                    'Timestamp',
                    'Model A',
                    'Model B',
                    'Version A',
                    'Version B',
                    'Insightfulness Winner',
                    'Insightfulness Explanation',
                    'Narrativity Winner',
                    'Narrativity Explanation',
                    'Coherence Winner',
                    'Coherence Explanation'
                ]
                writer.writerow(headers)
            
            # Extract metadata
            metadata = evaluation_data.get('metadata', {})
            model_a = metadata.get('model_A', 'unknown')
            model_b = metadata.get('model_B', 'unknown')
            version_a = metadata.get('version_A', 'unknown')
            version_b = metadata.get('version_B', 'unknown')
            
            # Extract criteria results
            insightfulness = evaluation_data.get('insightfulness_score', {})
            narrativity = evaluation_data.get('narrativity_score', {})
            coherence = evaluation_data.get('coherence_score', {})
            
            # Ensure voting values are standardized
            insightfulness_winner = insightfulness.get('voting', 'unknown')
            narrativity_winner = narrativity.get('voting', 'unknown')
            coherence_winner = coherence.get('voting', 'unknown')
            
            # Raise error if any voting value is unknown
            if 'unknown' in \
                  [insightfulness_winner, narrativity_winner, coherence_winner]:
                raise ValueError(f"Got unknown voting value in biography comparison."
                                 f" Insightfulness: {insightfulness_winner}, "
                                 f"Narrativity: {narrativity_winner}, "
                                 f"Coherence: {coherence_winner}")
            
            # Write row
            row = [
                timestamp.isoformat(),
                model_a,
                model_b,
                version_a,
                version_b,
                insightfulness_winner,
                insightfulness.get('explanation', ''),
                narrativity_winner,
                narrativity.get('explanation', ''),
                coherence_winner,
                coherence.get('explanation', '')
            ]
            writer.writerow(row)

    def log_interview_comparison_evaluation(
        self,
        evaluation_data: Dict[str, Any],
        timestamp: Optional[datetime] = None
    ) -> None:
        """Log comparative evaluation results between two interviews.
        
        Args:
            evaluation_data: Dictionary containing evaluation results and metadata
            timestamp: Optional timestamp (defaults to current time)
        """
        # Create evaluations directory
        eval_dir = Path("logs") / self.user_id / "evaluations"
        eval_dir.mkdir(parents=True, exist_ok=True)
        
        if timestamp is None:
            timestamp = datetime.now()
        
        # Log to CSV file
        filename = eval_dir / "interview_comparisons.csv"
        file_exists = filename.exists()
        
        with open(filename, 'a', newline='') as f:
            writer = csv.writer(f)
            
            # Create headers if file doesn't exist
            if not file_exists:
                headers = [
                    'Timestamp',
                    'Session ID',
                    'Model A',
                    'Model B',
                    'Smooth Score Winner',
                    'Smooth Score Explanation',
                    'Flexibility Score Winner',
                    'Flexibility Score Explanation',
                    'Comforting Score Winner',
                    'Comforting Score Explanation'
                ]
                writer.writerow(headers)
            
            # Extract metadata
            metadata = evaluation_data.get('metadata', {})
            model_a = metadata.get('model_A', 'unknown')
            model_b = metadata.get('model_B', 'unknown')
            
            # Extract criteria results
            smooth = evaluation_data.get('smooth_score', {})
            flexibility = evaluation_data.get('flexibility_score', {})
            comforting = evaluation_data.get('comforting_score', {})
            
            # Ensure voting values are standardized
            smooth_winner = smooth.get('voting', 'unknown')
            flexibility_winner = flexibility.get('voting', 'unknown')
            comforting_winner = comforting.get('voting', 'unknown')
            
            # Raise error if any voting value is unknown
            if 'unknown' in \
                   [smooth_winner, flexibility_winner, comforting_winner]:
                raise ValueError(f"Got unknown voting value in interview comparison."
                                 f" Smooth: {smooth_winner}, "
                                 f"Flexibility: {flexibility_winner}, "
                                 f"Comforting: {comforting_winner}")
            
            # Write row
            row = [
                timestamp.isoformat(),
                self.session_id,
                model_a,
                model_b,
                smooth_winner,
                smooth.get('explanation', ''),
                flexibility_winner,
                flexibility.get('explanation', ''),
                comforting_winner,
                comforting.get('explanation', '')
            ]
            writer.writerow(row)

    def log_biography_update_time(
        self,
        update_type: str,
        duration: float,
        accumulated_auto_time: float = 0.0,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Log the time taken for biography updates.
        
        Args:
            update_type: Type of update ('auto' or 'final')
            duration: Duration of the update in seconds
            accumulated_auto_time: Total time spent on auto-updates (default 0)
            timestamp: Optional timestamp (defaults to current time)
        """
        # Create logs directory
        logs_dir = self.eval_dir
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        if timestamp is None:
            timestamp = datetime.now()
        
        # Log to CSV file
        filename = logs_dir / "biography_update_times.csv"
        file_exists = filename.exists()
        
        with open(filename, 'a', newline='') as f:
            writer = csv.writer(f)
            
            # Create headers if file doesn't exist
            if not file_exists:
                headers = [
                    'Timestamp',
                    'Session ID',
                    'Update Type',
                    'Duration (seconds)',
                    'Accumulated Auto Time'
                ]
                writer.writerow(headers)
            
            # Write row
            writer.writerow([
                timestamp.isoformat(),
                self.session_id,
                update_type,
                f"{duration:.2f}",
                f"{accumulated_auto_time:.2f}"
            ]) 