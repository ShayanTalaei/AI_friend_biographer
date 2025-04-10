from pathlib import Path
import sys
import argparse
from typing import List, Dict, Optional
import os
import pandas as pd

# Add the src directory to Python path
src_dir = str(Path(__file__).parent.parent / "src")
sys.path.append(src_dir)

from content.biography.biography import Biography, Section
from content.memory_bank.memory_bank_vector_db import VectorMemoryBank
from utils.llm.engines import get_engine, invoke_engine
from utils.logger.evaluation_logger import EvaluationLogger
from utils.llm.xml_formatter import extract_tool_arguments

# Base evaluation instructions and format
GROUNDEDNESS_INSTRUCTIONS = r"""
You are an expert at evaluating if biographical text is grounded in source memories.

## Task

Given a biography section and its source memories, evaluate if the biographical text is substantiated by the memories. Return a score between 0-100, indicating what percentage of the biographical content is substantiated by the memories.

## Groundedness Definition

Let's define groundedness mathematically:

1. Let \(S = \{s_1, s_2, \ldots, s_n\}\) be the set of atomic information units from source memories.
2. Let \(B = \{b_1, b_2, \ldots, b_m\}\) be the set of atomic claims/statements in the biography section.
3. Define \(B_{\text{substantiated}} = \{b_i \in B \mid b_i \text{ can be derived from or substantiated by any } s_j \in S\}\).
4. The groundedness score is calculated as:

\[ \text{Groundedness Score} = \frac{|B_{\text{substantiated}}|}{|B|} \times 100 \]

### Reasonable Inference
Reasonable inference is allowed, especially in impact descriptions and contextual connections. Examples:

1. Paraphrasing with equivalent meaning:
   - Memory: "I was born in Baltimore, where my family played a pivotal role in shaping who I am today."
   - Valid inference: "Growing up in Baltimore played a significant role in shaping who I am today."

2. Logical extensions from explicit statements:
   - Memory: "I spent four years studying computer science at MIT, graduating in 2010."
   - Valid inference: "My education at MIT provided me with a strong foundation in computer science."

3. Contextual connections between related memories:
   - Memory: "I worked 80-hour weeks during my first year at the startup."
   - Valid inference: "The demanding schedule at the startup required significant personal sacrifice."

4. Impact on personal development:
  - Please DON'T be too strict on personal development claims since they are inherently subjective and not directly supported by memories. Weak connections are acceptable.

   - Memory: "My father published many books about African-American history and we discussed them often."
   - Valid inference: "It instilled in me a profound understanding of African-American history and culture."

   - Memory: "I was surrounded by books and ideas at my father's publishing company."
   - Valid inference: "This environment instilled in me a profound understanding of literature and culture."

5. General framing statements in introductions:
   - Valid statements: "This biography explores various aspects of my life journey" or "The following sections describe my personal and professional development"
   - These framing statements help orient the reader and are acceptable even without specific memory support

All reasonable inferences are acceptable, particularly when describing how experiences shaped the person's understanding, values, or perspective.

Avoid unsupported claims about specific achievements, relationships, or emotional impacts not mentioned in the memories.
"""

GROUNDEDNESS_IO_TEMPLATE = r"""
## Input Context

Biography Section:
<section_text>
{section_text}
</section_text>

Source Memories:
<memories>
{memories_xml}
</memories>

## Output Format

Return your evaluation using the following tool call format:

<thinking>
Step 1: Decompose source memories into atomic information units
- Source Memory 1: [List atomic information units]
- Source Memory 2: [List atomic information units]
...

Step 2: Decompose biography section into atomic claims/statements
- Claim 1: [Statement]
- Claim 2: [Statement]
...

Step 3: Evaluate each claim against source information
- Claim 1: [Substantiated/Unsubstantiated] - [Reasoning]
- Claim 2: [Substantiated/Unsubstantiated] - [Reasoning]
...

Step 4: Calculate groundedness score
- Total claims: [Number]
- Substantiated claims: [Number]
- Groundedness score: [Calculation] = [Final percentage]

Step 5: Summarize overall assessment
[Your overall assessment of the biography section's groundedness]
</thinking>

<tool_calls>
    <evaluate_groundedness>
        <groundedness_score>number between 0-100</groundedness_score>
        <unsubstantiated_claims>["claim 1", "claim 2", ...]</unsubstantiated_claims>
        <unsubstantiated_details_explanation>["explanation 1", "explanation 2", ...]</unsubstantiated_details_explanation>
        <overall_assessment>Your brief explanation of the evaluation</overall_assessment>
    </evaluate_groundedness>
</tool_calls>
"""

# Retry prompt templates
CONTINUATION_PROMPT_TEMPLATE = """
Your previous response was incomplete. Here's what you provided so far:

{previous_output}

Please continue from where you left off and ensure you provide the groundedness score in the XML format. Be more concise in your analysis and focus on providing the final <tool_calls> output.
"""

DIRECT_SCORE_PROMPT = """
Based on the biography section and memories you've been analyzing, please provide ONLY the groundedness score as a number between 0-100. Skip all explanations and just respond with the score in this exact format:

<tool_calls>
    <evaluate_groundedness>
        <groundedness_score>NUMBER</groundedness_score>
        <unsubstantiated_claims>[]</unsubstantiated_claims>
        <unsubstantiated_details_explanation>[]</unsubstantiated_details_explanation>
        <overall_assessment>Brief assessment</overall_assessment>
    </evaluate_groundedness>
</tool_calls>
"""

def check_existing_section_evaluation(user_id: str, version: int, section_id: str) -> Optional[Dict]:
    """Check if evaluation already exists for this biography section.
    Identifies invalid rows but does not remove them to avoid race conditions.
    
    Args:
        user_id: User ID
        version: Biography version
        section_id: Section ID to check
        
    Returns:
        Optional[Dict]: Existing evaluation results if found and valid, None otherwise
    """
    try:
        eval_path = os.path.join(
            os.getenv("LOGS_DIR"),
            user_id,
            "evaluations",
            f"biography_{version}",
            "groundedness_summary.csv"
        )
        
        if os.path.exists(eval_path):
            # Read CSV using pandas
            df = pd.read_csv(eval_path)
            
            # Find row for this section
            section_row = df[df['Section ID'] == section_id]
            
            if not section_row.empty:
                # Convert score to numeric, replacing errors with NaN
                score = pd.to_numeric(section_row['Groundedness Score'].iloc[0], errors='coerce')
                
                # Check if score is valid (> 0 and not NaN)
                if pd.isna(score) or score <= 0:
                    print(f"Found invalid score for section '{section_row['Section Title'].iloc[0]}'")
                    return None
                
                return {
                    "section_id": section_id,
                    "section_title": section_row['Section Title'].iloc[0],
                    "evaluation": {
                        "groundedness_score": score,
                        "unsubstantiated_claims": section_row['Unsubstantiated Claims'].iloc[0].split(';') if pd.notna(section_row['Unsubstantiated Claims'].iloc[0]) else [],
                        "unsubstantiated_details_explanation": section_row['Missing Details'].iloc[0].split(';') if pd.notna(section_row['Missing Details'].iloc[0]) else [],
                        "overall_assessment": section_row['Overall Assessment'].iloc[0] if pd.notna(section_row['Overall Assessment'].iloc[0]) else "No assessment provided"
                    }
                }
        return None
    except Exception as e:
        print(f"Error checking existing evaluation: {e}")
        return None

def create_evaluation_prompt(section_text: str, memories_xml: str) -> str:
    """Create the evaluation prompt with the section text and memories."""
    return GROUNDEDNESS_INSTRUCTIONS + GROUNDEDNESS_IO_TEMPLATE.format(
        section_text=section_text,
        memories_xml=memories_xml
    )

def parse_evaluation_response(output: str) -> Dict:
    """Parse the evaluation response to extract data."""
    result = {
        "groundedness_score": 0,
        "unsubstantiated_claims": [],
        "unsubstantiated_details_explanation": [],
        "overall_assessment": "No assessment provided"
    }
    
    # Parse response using XML formatter
    groundedness_scores = extract_tool_arguments(
        output, "evaluate_groundedness", "groundedness_score")
    
    if groundedness_scores:
        result["groundedness_score"] = groundedness_scores[0]
        
        # Extract other elements if we have a score
        claims = extract_tool_arguments(
            output, "evaluate_groundedness", "unsubstantiated_claims")
        result["unsubstantiated_claims"] = claims[0] if claims else []
        
        details = extract_tool_arguments(
            output, "evaluate_groundedness", "unsubstantiated_details_explanation")
        result["unsubstantiated_details_explanation"] = details[0] if details else []
        
        assessments = extract_tool_arguments(
            output, "evaluate_groundedness", "overall_assessment")
        result["overall_assessment"] = assessments[0] if assessments else "No assessment provided"
    
    return result

def evaluate_section_groundedness(
    section: Section,
    memory_bank: VectorMemoryBank,
    engine,
    logger: EvaluationLogger,
    biography_version: int
) -> Dict:
    """Evaluate how well a section's content is grounded in its source memories."""
    # Check if section has already been evaluated
    existing_eval = check_existing_section_evaluation(
        logger.user_id, 
        biography_version, 
        section.id
    )
    if existing_eval is not None:
        print(f"Found existing evaluation for section '{section.title}' with score: {existing_eval['evaluation']['groundedness_score']:.2f}%")
        return existing_eval
        
    # Get formatted memories
    memories_xml = memory_bank.get_formatted_memories_from_ids(
        section.memory_ids,
        include_source=True
    )
    
    # Prepare initial prompt
    base_prompt = create_evaluation_prompt(section.content, memories_xml)
    
    # Get max iterations from environment variable, default to 3
    max_iterations = int(os.getenv("MAX_CONSIDERATION_ITERATIONS", "3"))
    
    # Initialize result variables
    evaluation_result = None
    output = ""
    
    for iteration in range(max_iterations):
        try:
            print(f"Evaluating section '{section.title}' (attempt {iteration+1}/{max_iterations})...")
            
            # Determine prompt based on iteration
            if iteration == 0:
                # First attempt: use base prompt
                prompt = base_prompt
            elif iteration == max_iterations - 1:
                # Last attempt: use direct score prompt
                prompt = DIRECT_SCORE_PROMPT
            else:
                # Middle attempts: use continuation prompt
                prompt = base_prompt + CONTINUATION_PROMPT_TEMPLATE.format(previous_output=output)
            
            # Get evaluation using the engine
            output = invoke_engine(engine, prompt)
            
            # Log attempt
            log_type = f"biography_groundedness_section_{section.id}"
            if iteration > 0:
                log_type += f"_retry_{iteration}"
                
            logger.log_prompt_response(
                evaluation_type=log_type,
                prompt=prompt,
                response=output
            )
            
            # Parse response
            parsed_result = parse_evaluation_response(output)
            
            # If we successfully extracted a score, save the result and break
            if parsed_result["groundedness_score"]:
                evaluation_result = parsed_result
                break
            else:
                print(f"Failed to extract groundedness score on attempt {iteration+1}. Retrying...")
        
        except Exception as e:
            print(f"Error during evaluation attempt {iteration+1}: {str(e)}")
            if iteration == max_iterations - 1:
                print(f"Max retries reached. Using default values.")
    
    # If all attempts failed, use default values
    if evaluation_result is None:
        evaluation_result = {
            "groundedness_score": 0,
            "unsubstantiated_claims": [],
            "unsubstantiated_details_explanation": [],
            "overall_assessment": "Failed to evaluate after multiple attempts"
        }
    
    # Construct final result
    result = {
        "section_id": section.id,
        "section_title": section.title,
        "evaluation": evaluation_result
    }
    
    # Log evaluation results
    logger.log_biography_section_groundedness(
        section_id=section.id,
        section_title=section.title,
        groundedness_score=evaluation_result["groundedness_score"],
        unsubstantiated_claims=evaluation_result["unsubstantiated_claims"],
        unsubstantiated_details_explanation=evaluation_result["unsubstantiated_details_explanation"],
        overall_assessment=evaluation_result["overall_assessment"],
        biography_version=biography_version
    )
    
    return result

def evaluate_biography_groundedness(
    biography: Biography,
    memory_bank: VectorMemoryBank,
    engine,
    logger: EvaluationLogger
) -> List[Dict]:
    """Evaluate groundedness for all sections in a biography."""
    results = []
    
    def process_section(section: Section):
        # Evaluate current section
        if section.content and section.memory_ids:
            result = evaluate_section_groundedness(
                section, 
                memory_bank, 
                engine, 
                logger,
                biography.version
            )
            results.append(result)
        
        # Process subsections
        for subsection in section.subsections.values():
            process_section(subsection)
    
    # Skip root section and only process its subsections
    for subsection in biography.root.subsections.values():
        process_section(subsection)
    
    return results

def calculate_overall_groundedness(results: List[Dict]) -> float:
    """Calculate the overall groundedness score for the entire biography.
    
    Args:
        results: List of section evaluation results
        
    Returns:
        float: Average groundedness score across all sections
    """
    if not results:
        return 0.0
    
    total_score = 0
    for result in results:
        score = result["evaluation"]["groundedness_score"]
        # Convert to float if it's a string
        if isinstance(score, str):
            try:
                score = float(score)
            except ValueError:
                score = 0
        total_score += score
    
    return total_score / len(results)

def clean_invalid_groundedness_entries(user_id: str, version: int) -> None:
    """Clean invalid entries (score <= 0 or NaN) from the groundedness summary CSV.
    
    Args:
        user_id: User ID
        version: Biography version
    """
    eval_path = os.path.join(
        os.getenv("LOGS_DIR"),
        user_id,
        "evaluations",
        f"biography_{version}",
        "groundedness_summary.csv"
    )
    
    if not os.path.exists(eval_path):
        print("No groundedness summary file found to clean")
        return
    
    try:
        # Read CSV using pandas
        df = pd.read_csv(eval_path)
        
        # Convert score to numeric, replacing errors with NaN
        df['Groundedness Score'] = pd.to_numeric(df['Groundedness Score'], errors='coerce')
        
        # Find invalid rows (score <= 0 or NaN)
        valid_mask = (df['Groundedness Score'] > 0) & df['Groundedness Score'].notna()
        invalid_rows = ~valid_mask
        
        if invalid_rows.any():
            invalid_count = invalid_rows.sum()
            # Get the titles of invalid sections for reporting
            invalid_titles = df.loc[invalid_rows, 'Section Title'].tolist()
            
            print(f"Cleaning {invalid_count} invalid entries from groundedness_summary.csv:")
            for title in invalid_titles:
                print(f"  - {title}")
            
            # Keep only valid rows
            df_cleaned = df[valid_mask].copy()
            
            # Save cleaned DataFrame back to CSV
            df_cleaned.to_csv(eval_path, index=False)
            print(f"Successfully cleaned groundedness_summary.csv")
        else:
            print("No invalid entries found in groundedness_summary.csv")
    
    except Exception as e:
        print(f"Error cleaning groundedness summary: {e}")

def main():
    """Main function to run the biography groundedness evaluation."""
    parser = argparse.ArgumentParser(
        description='Evaluate biography groundedness for a given user'
    )
    parser.add_argument(
        '--user_id',
        type=str,
        help='ID of the user whose biography to evaluate',
        required=True
    )
    parser.add_argument(
        '--version',
        type=int,
        help='Version of the biography to evaluate',
        required=False,
        default=-1
    )
    
    args = parser.parse_args()
    
    # Initialize LLM engine with higher token limit to handle detailed analysis
    engine = get_engine("gemini-2.0-flash", max_output_tokens=8192)
    
    # Load biography and memory bank
    biography = Biography.load_from_file(args.user_id, args.version)
    memory_bank = VectorMemoryBank.load_from_file(args.user_id)
    
    # Initialize shared logger
    logger = EvaluationLogger.setup_logger(args.user_id, biography.version)
    
    # Run evaluation
    print(f"Evaluating biography groundedness for user: {args.user_id}")
    results = evaluate_biography_groundedness(biography, memory_bank, engine, logger)
    
    # Clean invalid entries from the groundedness summary CSV
    print("\nCleaning invalid entries from groundedness summary...")
    clean_invalid_groundedness_entries(args.user_id, biography.version)
    
    # Calculate and print overall groundedness score
    overall_score = calculate_overall_groundedness(results)
    print(f"\nOverall Biography Groundedness Score: {overall_score:.2f}%")
    
    # Log overall score
    logger.log_biography_overall_groundedness(
        overall_score=overall_score,
        section_scores=results,
        biography_version=biography.version
    )
    
    print("Evaluation complete. Results saved to logs directory.")

if __name__ == "__main__":
    main() 