SIMILAR_QUESTIONS_WARNING = """\
<similar_questions_warning>

## Warning: Question Similarity Detected

Some of your proposed questions are similar to those previously asked.

Previous Tool Call (Pending):
<previous_tool_call>
{previous_tool_call}
</previous_tool_call>

Similar Questions Already Asked:
<similar_asked_questions>
{similar_questions}
</similar_asked_questions>

## Guidelines to Address the Warning

Please avoid asking questions that are identical or too similar to ones already posed.

1. Do Not Propose Duplicate Questions:
Examples of Duplicates (Not Allowed):
- Proposed: "Can you describe a specific challenge you encountered in working on the XX project?"
    - Existing: "Could you share more about the challenges you've faced in working on the XX project?"
- Proposed: "What was the most rewarding discovery about the XX experience?"
    - Existing: "Can you describe a particular moment that was particularly rewarding about the XX experience?"

2. Acceptable Questions (Provide New Insights):
Examples of Good Variations:
- Different Time Period/Context:
    - Existing: "What was your daily routine in college?"
    ✓ OK: "What was your daily routine in your first job?" *(different context)*

- Different Aspect/Angle:
    - Existing: "How did you feel about moving to a new city?"
    ✓ OK: "What unexpected challenges did you face when moving to the new city?" *(specific challenges)*
    ✓ OK: "Who were the first friends you made in the new city?" *(focuses on relationships)*

- Different Depth:
    - Existing: "Tell me about your favorite teacher."
    ✓ OK: "What specific lessons or advice from that teacher influenced your later life?" *(explores impact)*

## Action Required

Required Action (Choose ONE):

1. Generate Alternative Questions
   - When: Previous questions are too similar to existing ones
   - How: Provide new questions in <tool_calls></tool_calls>
   - Note: Free to use Question IDs in previous tool calls since they are pending.

2. Proceed with Original Questions
   - When: Previous questions offer unique insights despite similarities
   - How: Include <proceed>true</proceed> tag
   - Note: Leave <tool_calls></tool_calls> empty

</similar_questions_warning>
"""

PLANNER_MISSING_MEMORIES_WARNING = """\
<missing_memories_warning>
Warning: Some memories from the interview session are not yet incorporated into the plans you have generated.

Previous tool calls that already have been executed:
<previous_tool_call>
{previous_tool_call}
</previous_tool_call>

Uncovered memories that are not yet incorporated:
<missing_memory_ids>
{missing_memory_ids}
</missing_memory_ids>

Action Required:
- Generate add_plan tool calls to cover the missing memories.
- If excluding any memories, explain why in `<thinking></thinking>` tags:
  - Example Reasons:
    * Memory is trivial or not relevant

</missing_memories_warning>
"""

MISSING_MEMORIES_WARNING = """\
<missing_memories_warning>
## Warning (IMPORTANT!!!)
Some memories from the interview session are not yet incorporated into the section content. 

Previous tool calls that already have been executed:
<previous_tool_call>
{previous_tool_call}
</previous_tool_call>

Uncovered memories that are not yet incorporated:
<missing_memory_ids>
{missing_memory_ids}
</missing_memory_ids>

Action Required:
- Update the section content to incorporate the citation links for the missing memories.
- If excluding any memories, explain why in `<thinking></thinking>` tags:
  - Example Reasons:
    * Memory already covered in another section
    * Memory is trivial or not relevant

</missing_memories_warning>
"""

PROCEED_WITH_WARNING_OUTPUT_FORMAT = """
Then choose ONE of the following options:

Option 1: Proceed with warning by including the following tag:
<proceed>true</proceed>

Option 2: Address the warning by generating new tool calls to resolve the issues:
"""

WARNING_OUTPUT_FORMAT = """
About the warning:

If you decide to proceed with the warning, please include the following XML tag after providing your explanation:

<proceed>true</proceed>
"""