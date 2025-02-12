from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import os
import json

from memory_bank.memory import Memory

class MemoryBankBase(ABC):
    """Abstract base class for memory bank implementations.
    
    This class defines the standard interface that all memory bank implementations
    must follow. Concrete implementations (e.g., VectorDB, GraphRAG) should inherit
    from this class and implement the abstract methods.
    """
    
    def __init__(self):
        self.memories: List[Memory] = []
    
    @abstractmethod
    def add_memory(
        self,
        title: str,
        text: str,
        importance_score: int,
        source_interview_response: str,
        metadata: Optional[Dict] = None
    ) -> Memory:
        """Add a new memory to the database.
        
        Args:
            title: Title of the memory
            text: Content of the memory
            importance_score: Importance score of the memory
            source_interview_response: Original response from interview that generated this memory
            metadata: Optional metadata dictionary
            
        Returns:
            Memory: The created memory object
        """
        pass
    
    @abstractmethod
    def search_memories(self, query: str, k: int = 5) -> List[Dict]:
        """Search for similar memories using the query text.
        
        Args:
            query: The search query text
            k: Number of results to return
            
        Returns:
            List[Dict]: List of memory dictionaries with similarity scores
        """
        pass
    
    def save_to_file(self, user_id: str) -> None:
        """Save the memory bank to file.
        
        Args:
            user_id: ID of the user whose memories are being saved
        """
        content_data = {
            'memories': [memory.to_dict() for memory in self.memories]
        }
        
        content_filepath = os.getenv("LOGS_DIR") + f"/{user_id}/memory_bank_content.json"
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(content_filepath), exist_ok=True)
        
        with open(content_filepath, 'w') as f:
            json.dump(content_data, f, indent=2)
            
        # Implementation-specific save
        self._save_implementation_specific(user_id)
    
    @abstractmethod
    def _save_implementation_specific(self, user_id: str) -> None:
        """Save implementation-specific data (e.g., embeddings, graph structure).
        
        Args:
            user_id: ID of the user whose data is being saved
        """
        pass
    
    @classmethod
    def load_from_file(cls, user_id: str) -> 'MemoryBankBase':
        """Load a memory bank from file.
        
        Args:
            user_id: ID of the user whose memories to load
            
        Returns:
            MemoryBankBase: Loaded memory bank instance
        """
        memory_bank = cls()
        
        content_filepath = os.getenv("LOGS_DIR") + f"/{user_id}/memory_bank_content.json"
        
        try:
            # Load content
            with open(content_filepath, 'r') as f:
                content_data = json.load(f)
                
            # Reconstruct memories
            for memory_data in content_data['memories']:
                memory = Memory.from_dict(memory_data)
                memory_bank.memories.append(memory)
                
            # Load implementation-specific data
            memory_bank._load_implementation_specific(user_id)
                
        except FileNotFoundError:
            # Create new empty memory bank if files don't exist
            memory_bank.save_to_file(user_id)
            
        return memory_bank
    
    @abstractmethod
    def _load_implementation_specific(self, user_id: str) -> None:
        """Load implementation-specific data (e.g., embeddings, graph structure).
        
        Args:
            user_id: ID of the user whose data to load
        """
        pass 