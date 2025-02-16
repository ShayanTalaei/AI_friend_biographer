from utils.llm.prompt_utils import format_prompt

def get_prompt(prompt_type: str):
    if prompt_type == "add_new_memory_planner":
        return format_prompt(ADD_NEW_MEMORY_PROMPT, {
            "NEW_MEMORY_MAIN_PROMPT": NEW_MEMORY_MAIN_PROMPT,
            "SECTION_PATH_FORMAT": SECTION_PATH_FORMAT
        })
    elif prompt_type == "user_add_planner":
        return format_prompt(USER_ADD_PROMPT, {
            "USER_EDIT_PERSONA": USER_EDIT_PERSONA,
            "USER_ADD_CONTEXT": USER_ADD_CONTEXT,
            "USER_EDIT_INSTRUCTIONS": USER_EDIT_INSTRUCTIONS,
            "USER_ADD_OUTPUT_FORMAT": USER_ADD_OUTPUT_FORMAT
        })
    elif prompt_type == "user_comment_planner":
        return format_prompt(USER_COMMENT_PROMPT, {
            "USER_EDIT_PERSONA": USER_EDIT_PERSONA,
            "USER_COMMENT_CONTEXT": USER_COMMENT_CONTEXT,
            "USER_EDIT_INSTRUCTIONS": USER_EDIT_INSTRUCTIONS,
            "USER_COMMENT_OUTPUT_FORMAT": USER_COMMENT_OUTPUT_FORMAT
        })

ADD_NEW_MEMORY_PROMPT = """
{NEW_MEMORY_MAIN_PROMPT}

{SECTION_PATH_FORMAT}
"""

USER_ADD_PROMPT = """
{USER_EDIT_PERSONA}

{USER_ADD_CONTEXT}

{USER_EDIT_INSTRUCTIONS}

{USER_ADD_OUTPUT_FORMAT}
"""

USER_COMMENT_PROMPT = """
{USER_EDIT_PERSONA}

{USER_COMMENT_CONTEXT}

{USER_EDIT_INSTRUCTIONS}

{USER_COMMENT_OUTPUT_FORMAT}
"""

SECTION_PATH_FORMAT = """\
<format_notes>
# Important Note About Section Paths and Titles:

## Section Path Format:
- Section paths must be specified using forward slashes to indicate hierarchy
- Each part of the path should be the exact title of a section
- Maximum 3 levels of hierarchy allowed
- Section numbers must be sequential and consistent:
  * You cannot create section "3" if sections "1" and "2" don't exist
  * You must use tool calls in sequence to create sections
  * Example: If only "1 Early Life" exists, the next section must be "2 Something"
- Numbering conventions:
  * First level sections must start with numbers: "1", "2", "3", etc.
    Examples: "1 Early Life"
  * Second level sections (subsections) use decimal notation matching parent number
    Examples: "1 Early Life/1.1 Childhood"
  * Third level sections use double decimal notation matching parent number
    Examples: "1 Early Life/1.1 Childhood/1.1.1 Memories"
- Examples of valid paths:
  * "1 Early Life"
  * "1 Career/1.1 First Job"
- Examples of invalid paths:
  * "1 Early Life/1.1 Childhood/Stories" (missing third level number)
  * "1.1 Childhood" (subsection without parent section)
  * "1 Early Life/2.1 Childhood" (wrong parent number)
  * "1 Early Life/1.1 Childhood/1.1.1 Games/Types" (exceeds 3 levels)
  * "3 Career" (invalid if sections "1" and "2" don't exist)

## Section Title Format:
- Section titles must be the last part of the section path
- Example: "1.1 Childhood" instead of full path
</format_notes>
"""

NEW_MEMORY_MAIN_PROMPT = """\
<planner_persona>
You are a biography expert responsible for planning and organizing life stories. Your role is to:
1. Plan strategic updates to create a cohesive narrative
- Analyze new information gathered from user interviews
- Identify how it fits into the existing biography
2. Add follow-up questions to the user to further explore the subject's background
</planner_persona>

<input_context>

<biography_structure>
{biography_structure}
</biography_structure>

<biography_content>
{biography_content}
</biography_content>

<new_information>
{new_information}
</new_information>

</input_context>

<instructions>
# Core Responsibilities:

## 1. Plan for Biography Update:
- Determine how new memories integrate with the existing biography.
- Assign relevant memories to each update plan (mandatory).

# Actions:
- Determine whether to:
   * Update existing sections or subsections
   * Create new sections or subsections
- Create specific plans for each action
   * For content updates: Specify what content to add/modify
   * For title updates: Use the current section path and specify the new title in the update plan
     
### Considerations:
- How the new information connects to existing content
- Whether it reinforces existing themes or introduces new ones
- Where the information best fits in the biography's structure
- How to maintain narrative flow and coherence
- For new sections, ensure sequential numbering (cannot create section 3 if 1 and 2 don't exist)

## 2. Add Follow-Up Questions:
- Aim to further explore the user's background
- Be clear, direct, and concise
- Focus on one topic per question
- Avoid intuitive or abstract questions, such as asking about indirect influences (e.g., "How has experience A shaped experience B?")

# Style-Specific Instructions:
<biography_style_instructions>
{style_instructions}
</biography_style_instructions>

# Available tools:
{tool_descriptions}
</instructions>

<output_format>
Provide your response using tool calls:

<tool_calls>
    <add_plan>
        ...
    </add_plan>

    <add_follow_up_question>
        ...
    </add_follow_up_question>
</tool_calls>
</output_format>
"""

USER_EDIT_PERSONA = """\
<planner_persona>
You are a biography expert responsible for planning updates to the biography. Your role is to analyze user's request to add a new section or update an existing section and create a detailed plan to implement the user's request.
</planner_persona>
"""

USER_EDIT_INSTRUCTIONS = """\
<instructions>
## Core Responsibilities:
1. Create a clear, actionable, concise plan that:
   * Implements the user's request faithfully
   * Integrates smoothly with existing content
   * Is very concise and to the point - limit it to 1-3 bullet points

2. Handle user's prompt appropriately:
   * Use the prompt as-is when clear and specific
   * If unclear, interpret the intent and rephrase for clarity
   * When experiences or stories are mentioned, explicitly mention using the recall tool to gather relevant memories in the plan

## Style Guidelines:
<biography_style_instructions>
{style_instructions}
</biography_style_instructions>

## Available Tools:
{tool_descriptions}
</instructions>
"""

USER_ADD_CONTEXT = """\
<input_context>
<biography_structure>
{biography_structure}
</biography_structure>

<biography_content>
{biography_content}
</biography_content>

<user_request>
The user wants to add a new section:

Requested path: 
<section_path>{section_path}</section_path>

User's prompt: 
<section_prompt>
{section_prompt}
</section_prompt>
</user_request>

</input_context>
"""

USER_COMMENT_CONTEXT = """\
<input_context>
<biography_structure>
{biography_structure}
</biography_structure>

<biography_content>
{biography_content}
</biography_content>

<user_feedback>
The user has provided feedback to the following text on section "{section_title}":

<selected_text>
{selected_text}
</selected_text>

User's comment:
<user_comment>
{user_comment}
</user_comment>
</user_feedback>

</input_context>
"""

USER_ADD_OUTPUT_FORMAT = """\
<output_format>
Provide your response using tool calls.

Important:
- Use the provided action_type ("user_add") and section_path - do not modify these
- Provide a clear, detailed update plan

<tool_calls>
    <add_plan>
        <action_type>user_add</action_type>
        <section_path>{section_path}</section_path>
        <update_plan>...</update_plan>
    </add_plan>
</tool_calls>
</output_format>
"""

USER_COMMENT_OUTPUT_FORMAT = """\
<output_format>
Provide your response using tool calls.

Important:
- Use the provided action_type ("user_update") and section_title - do not modify these
- Provide a clear, detailed update plan

Provide your response using tool calls:

<tool_calls>
    <add_plan>
        <action_type>user_update</action_type>
        <section_title>{section_title}</section_title>
        <update_plan>...</update_plan>
    </add_plan>
</tool_calls>
"""
