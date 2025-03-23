import os
import sys
import argparse
import json
from pathlib import Path
from datetime import datetime
import asyncio
from typing import Dict, Any, Optional, List
import random

# Add the src directory to Python path
src_dir = str(Path(__file__).parent.parent / "src")
sys.path.append(src_dir)

from dotenv import load_dotenv
from utils.llm.engines import get_engine, invoke_engine
from utils.logger.evaluation_logger import EvaluationLogger
from utils.llm.xml_formatter import extract_tool_arguments
from content.biography.biography import Biography

load_dotenv()

# Evaluation criteria
EVALUATION_CRITERIA = {
    "insightfulness_score": {
        "description": "Reveals profound perspectives on the subject's experiences and motivations, offering readers meaningful interpretations beyond surface facts",
        "scale": "0-5",
        "guidelines": [
            "0: Completely superficial, only lists basic facts with no interpretation",
            "1: Mostly superficial with minimal interpretation of experiences",
            "2: Some attempt at interpretation but lacks depth and meaningful insights",
            "3: Good balance of facts and interpretation with some meaningful insights",
            "4: Strong insights that reveal deeper motivations and perspectives",
            "5: Exceptional insights that profoundly illuminate the subject's life and character"
        ]
    },
    "narrativity_score": {
        "description": "Employs compelling storytelling techniques that engage readers through vivid description, appropriate pacing, and emotional resonance",
        "scale": "0-5",
        "guidelines": [
            "0: No narrative structure, just a list of disconnected facts",
            "1: Basic chronology but lacks storytelling elements and engagement",
            "2: Some storytelling elements but lacks vivid description or emotional resonance",
            "3: Good narrative flow with some vivid descriptions and emotional elements",
            "4: Strong storytelling with engaging descriptions and consistent emotional resonance",
            "5: Masterful storytelling with captivating descriptions, perfect pacing, and powerful emotional impact"
        ]
    },
    "coherence_score": {
        "description": "Presents a logical flow of events with clear chronology, establishing meaningful connections between life phases while maintaining narrative continuity",
        "scale": "0-5",
        "guidelines": [
            "0: Completely disjointed with no logical flow or connections",
            "1: Mostly disconnected sections with unclear chronology",
            "2: Basic chronology but weak connections between life phases",
            "3: Clear chronology with some meaningful connections between events",
            "4: Strong logical flow with well-established connections between life phases",
            "5: Exceptional coherence with seamless transitions and profound connections across the entire life story"
        ]
    }
}

BIOGRAPHY_EVALUATION_INSTRUCTIONS = """
You are an expert literary critic specializing in biographies. You will be given two biographies (A and B) to compare. Your task is to evaluate them based on specific criteria and vote for the better one in each category.

Please carefully read through both biographies and then vote based on these criteria:

{criteria_text}

For each criterion:
1. Vote for either Biography A, Biography B, or "Tie" if they are equally good
2. Provide a detailed explanation (2-3 sentences) justifying your choice with specific examples from both biographies

Your evaluation should be objective, fair, and based solely on the biographies provided. Do not try to guess which system generated which biography.
"""

BIOGRAPHY_EVALUATION_IO = """
## Input Context

Biography A:
<A>
{biography_a_content}
</A>

Biography B:
<B>
{biography_b_content}
</B>

## Output Format
Use the tool calls to output your evaluation.

Reminder: 
- Just specify A, B, or Tie for the voting, other formats like "Biography A", "Biography B", "model_A" or "model_B", "version_A" or "model_Tie", are not allowed.
- Just specify A, B, or Tie!!!
- Wrap your output in <tool_calls>...</tool_calls> tags.

<tool_calls>
<insightfulness_score>
    <explanation>Your explanation comparing both biographies</explanation>
    <voting>A or B or Tie</voting>
</insightfulness_score>
<narrativity_score>
    <explanation>Your explanation comparing both biographies</explanation>
    <voting>A or B or Tie</voting>
</narrativity_score>
<coherence_score>
    <explanation>Your explanation comparing both biographies</explanation>
    <voting>A or B or Tie</voting>
</coherence_score>
</tool_calls>
"""

def format_evaluation_prompt(biography_a_content: str, biography_b_content: str) -> str:
    """Format the evaluation prompt with the biography content.
    
    Args:
        biography_a_content: Content of biography A
        biography_b_content: Content of biography B
    
    Returns:
        Formatted prompt string
    """
    criteria_text = ""
    for criterion, details in EVALUATION_CRITERIA.items():
        criteria_text += (f"- {criterion.replace('_', ' ').title()}: "
                f"{details['description']}\n")
        for guideline in details['guidelines']:
            criteria_text += f"  * {guideline}\n"
        criteria_text += "\n"
    
    instructions = \
        BIOGRAPHY_EVALUATION_INSTRUCTIONS.format(criteria_text=criteria_text)
    io_format = BIOGRAPHY_EVALUATION_IO.format(
        biography_a_content=biography_a_content,
        biography_b_content=biography_b_content
    )
    
    return f"{instructions}\n\n{io_format}"

def parse_evaluation_response(response: str) -> Dict[str, Any]:
    """Parse the evaluation response to extract ratings and explanations."""
    result = {}
    
    # Define criteria to extract
    criteria = ["insightfulness_score", "narrativity_score", "coherence_score"]
    
    # Extract ratings and explanations for each criterion
    for criterion in criteria:
        # Extract from first-level tags
        voting = extract_tool_arguments(response, criterion, "voting")
        explanation = extract_tool_arguments(response, criterion, "explanation")
        
        if voting and explanation:
            try:
                # Normalize voting value to handle different formats
                vote_value = voting[0].strip()
                # Convert to standard format (A, B, or Tie)
                if vote_value.lower() in ['a', 'biography a']:
                    vote_value = 'A'
                elif vote_value.lower() in ['b', 'biography b']:
                    vote_value = 'B'
                elif vote_value.lower() in ['tie', 'equal', 'both']:
                    vote_value = 'Tie'
                
                result[criterion] = {
                    "voting": vote_value,
                    "explanation": explanation[0]
                }
            except (ValueError, IndexError) as e:
                print(f"Error parsing {criterion}: {e}")
                print(f"Voting: {voting}, Explanation: {explanation}")
    
    # Print the extracted data for debugging
    print(f"Extracted evaluation data: {json.dumps(result, indent=2)}")
    
    return result

async def get_biography_markdown(
    user_id: str, 
    biography_version: Optional[int] = None,
    model_name: Optional[str] = None
) -> tuple:
    """Get the biography content in markdown format.
    
    Args:
        user_id: User ID
        biography_version: Optional biography version (uses latest if not provided)
        model_name: Optional model name for loading from baseline directories
        
    Returns:
        Tuple of (biography content in markdown format, actual version used)
    """
    # Determine the base path based on model name
    if model_name:
        base_path = f"data_{model_name}/{user_id}"
        print(f"Loading from base path: {base_path}")  # Debug print
    else:
        base_path = None  # Use default path from env
        
    try:
        # Load the biography
        biography = Biography.load_from_file(
            user_id, 
            version=biography_version or -1,
            base_path=base_path
        )
        
        # Export to markdown
        markdown_content = await biography.export_to_markdown()
        
        return markdown_content, biography.version
    except Exception as e:
        print(f"Error loading biography for {model_name}: {e}")
        raise

async def prepare_biography_pairs(user_id: str, biography_version: Optional[int] = None) -> List[Dict[str, Any]]:
    """Prepare pairs of biographies (ours vs baselines) for voting.
    
    Args:
        user_id: User ID
        biography_version: Optional biography version for our biography
        
    Returns:
        List of biography pairs with metadata
    """
    pairs = []
    
    # Get our biography
    our_bio, our_version = await get_biography_markdown(user_id, biography_version)
    
    # Get baseline biographies from model-specific directories
    for dir_name in os.listdir('.'):
        if dir_name.startswith('logs_'):
            # Extract and normalize model name
            model_name = dir_name[5:]  # Remove 'logs_' prefix
            
            try:
                baseline_bio, baseline_version = await get_biography_markdown(
                    user_id, 
                    biography_version=None,  # Always use latest for baseline
                    model_name=model_name
                )
                
                # Randomly assign positions (A or B) for fair comparison
                if random.random() < 0.5:
                    pair = {
                        'biography_A': our_bio,
                        'biography_B': baseline_bio,
                        'model_A': 'ours',
                        'model_B': model_name,
                        'version_A': our_version,
                        'version_B': baseline_version
                    }
                else:
                    pair = {
                        'biography_A': baseline_bio,
                        'biography_B': our_bio,
                        'model_A': model_name,
                        'model_B': 'ours',
                        'version_A': baseline_version,
                        'version_B': our_version
                    }
                pairs.append(pair)
                
            except Exception as e:
                print(f"Error loading baseline biography for {model_name}: {e}")
                continue
    
    return pairs

async def evaluate_biography_pair(user_id: str, pair: Dict[str, Any], our_version: int) -> Dict[str, Any]:
    """Evaluate a pair of biographies through comparative voting.
    
    Args:
        user_id: User ID
        pair: Dictionary containing biography pair data
        our_version: Version number of our biography
        
    Returns:
        Evaluation results
    """
    try:
        # Format prompt
        prompt = format_evaluation_prompt(
            biography_a_content=pair['biography_A'],
            biography_b_content=pair['biography_B']
        )
        
        # Get engine
        engine = get_engine("gpt-4o", temperature=0.5)
        
        # Call engine
        print(f"Evaluating biography pair for user {user_id}...")
        response = invoke_engine(engine, prompt)
        
        # Parse response
        evaluation = parse_evaluation_response(response)
        
        # Add metadata to evaluation results
        evaluation['metadata'] = {
            'model_A': pair['model_A'],
            'model_B': pair['model_B'],
            'version_A': pair['version_A'],
            'version_B': pair['version_B']
        }
        
        # Setup evaluation logger
        eval_logger = EvaluationLogger.setup_logger(user_id)
        
        # Log evaluation
        timestamp = datetime.now()
        eval_logger.log_prompt_response(
            evaluation_type="biography_content_comparison",
            prompt=prompt,
            response=response,
            timestamp=timestamp
        )
        
        # Log comparative evaluation results
        eval_logger.log_biography_comparison_evaluation(
            evaluation_data=evaluation,
            biography_version=our_version,  # Pass our version
            timestamp=timestamp
        )
        
        return evaluation
    
    except Exception as e:
        print(f"Error evaluating biography pair: {str(e)}")
        raise

async def main_async():
    parser = argparse.ArgumentParser(
        description="Evaluate biography content quality through comparison")
    parser.add_argument("--user_id", required=True, help="User ID")
    parser.add_argument("--biography_version", type=int, 
                        help="Biography version for our work (optional)")
    
    args = parser.parse_args()
    
    try:
        # Prepare biography pairs
        print(f"\nPreparing biography pairs for user {args.user_id}...")
        pairs = await prepare_biography_pairs(args.user_id, args.biography_version)
        
        if not pairs:
            print("No biography pairs found for comparison")
            return
        
        # Get our biography version (either specified or latest)
        our_version = args.biography_version
        if our_version is None:
            # Get latest version from first pair
            for pair in pairs:
                if pair['model_A'] == 'ours':
                    our_version = pair['version_A']
                    break
                elif pair['model_B'] == 'ours':
                    our_version = pair['version_B']
                    break
        
        if our_version is None:
            print("Could not determine our biography version")
            return
            
        # Evaluate each pair
        print(f"\nFound {len(pairs)} pairs for comparison")
        print(f"Using our biography version: {our_version}")
        
        for i, pair in enumerate(pairs, 1):
            print(f"\nEvaluating pair {i} of {len(pairs)}:")
            print(f"Model A: {pair['model_A']}")
            print(f"Model B: {pair['model_B']}")
            
            evaluation = \
                await evaluate_biography_pair(args.user_id, pair, our_version)
            
            print(f"\nComparison {i} completed")
            
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
