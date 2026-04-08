"""Memory system - Spark learns from interactions and remembers what works.

The memory system extracts preferences and patterns from conversations,
stores them, and surfaces relevant memories when generating nudges.
This is what makes Spark get better over time.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import anthropic

from spark.db.connection import get_session
from spark.db.models import AgentMemory, Message, MemoryType, MessageDirection

logger = logging.getLogger(__name__)

# Prompt for extracting memories from conversation
MEMORY_EXTRACTION_PROMPT = """\
Analyze this conversation between Spark (an AI co-founder) and the user.
Extract any preferences, feedback, or patterns that Spark should remember.

CONVERSATION:
{conversation}

Extract memories in this JSON format. Only include genuinely useful signals, \
not obvious things. Return an empty list if nothing notable.

```json
[
  {{
    "type": "preference|feedback|goal|relationship|pattern",
    "content": "concise description of what to remember",
    "importance": "high|medium|low"
  }}
]
```

Types:
- preference: How the user likes to work (e.g., "prefers morning commits", "hates verbose messages")
- feedback: Direct reaction to Spark's nudges (e.g., "said the auth suggestion was helpful")
- goal: Stated objective or priority (e.g., "wants to ship billing by Friday")
- relationship: Cross-project connection the user confirmed (e.g., "interested in reusing auth from ProjectA")
- pattern: Observed behavior pattern (e.g., "usually responds to specific code suggestions, ignores vague ones")

Return ONLY the JSON array, no other text.\
"""


def extract_memories(
    messages: list[dict],
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> list[dict]:
    """Extract memories from a list of messages using Claude.

    Args:
        messages: List of dicts with 'direction', 'content', 'sent_at' keys.
        api_key: Anthropic API key.
        model: Model to use.

    Returns:
        List of extracted memory dicts: {type, content, importance}.
    """
    if not messages or not api_key:
        return []

    conversation = "\n".join(
        f"{'Spark' if m['direction'] == 'outbound' else 'User'}: {m['content']}"
        for m in messages
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": MEMORY_EXTRACTION_PROMPT.format(conversation=conversation),
            }],
        )
        text = response.content[0].text.strip()

        # Parse JSON from response (handle markdown code blocks)
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        memories = json.loads(text)
        if not isinstance(memories, list):
            return []

        return [
            m for m in memories
            if isinstance(m, dict) and "type" in m and "content" in m
        ]

    except Exception as e:
        logger.error(f"Failed to extract memories: {e}")
        return []


def store_memories(
    memories: list[dict],
    source_message_id: str | None = None,
) -> int:
    """Store extracted memories in the database.

    Deduplicates by checking for very similar existing memories.

    Returns the number of new memories stored.
    """
    if not memories:
        return 0

    stored = 0
    with get_session() as session:
        existing = session.query(AgentMemory).all()
        existing_contents = {m.content.lower() for m in existing}

        for mem in memories:
            content = mem.get("content", "").strip()
            if not content:
                continue

            # Skip if we already have something very similar
            if content.lower() in existing_contents:
                continue

            memory_type = mem.get("type", "preference")
            if memory_type not in [mt.value for mt in MemoryType]:
                memory_type = MemoryType.PREFERENCE.value

            agent_memory = AgentMemory(
                memory_type=memory_type,
                content=content,
                source_message_id=source_message_id,
            )
            session.add(agent_memory)
            existing_contents.add(content.lower())
            stored += 1

    if stored:
        logger.info(f"Stored {stored} new memories")
    return stored


def recall_memories(
    memory_types: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    """Retrieve stored memories, optionally filtered by type.

    Returns list of dicts: {id, type, content, created_at}.
    """
    with get_session() as session:
        query = session.query(AgentMemory)

        if memory_types:
            query = query.filter(AgentMemory.memory_type.in_(memory_types))

        query = query.order_by(AgentMemory.created_at.desc())
        memories = query.limit(limit).all()

        return [
            {
                "id": m.id,
                "type": m.memory_type,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ]


def get_memory_context(max_items: int = 10) -> str:
    """Build a formatted memory context string for use in prompts.

    Returns a section that can be injected into nudge/reply prompts
    so Spark remembers what it has learned about the user.
    """
    memories = recall_memories(limit=max_items)
    if not memories:
        return ""

    lines = ["WHAT YOU KNOW ABOUT YOUR CO-FOUNDER (from past interactions):"]
    for m in memories:
        lines.append(f"- [{m['type']}] {m['content']}")

    return "\n".join(lines)


def process_conversation_for_memories(
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
    lookback: int = 10,
) -> int:
    """Process recent conversations and extract memories.

    Looks at the most recent messages that haven't been processed yet
    and extracts learnable patterns.

    Returns the number of new memories stored.
    """
    with get_session() as session:
        # Get recent message pairs (inbound + outbound)
        recent = (
            session.query(Message)
            .order_by(Message.sent_at.desc())
            .limit(lookback)
            .all()
        )

        if len(recent) < 2:
            return 0

        # Check if we already have memories from the most recent message
        latest_id = recent[0].id
        existing = (
            session.query(AgentMemory)
            .filter(AgentMemory.source_message_id == latest_id)
            .first()
        )
        if existing:
            return 0  # Already processed this batch

        messages = [
            {
                "direction": m.direction,
                "content": m.content,
                "sent_at": m.sent_at.isoformat() if m.sent_at else "",
            }
            for m in reversed(recent)
        ]

    extracted = extract_memories(messages, api_key, model)
    return store_memories(extracted, source_message_id=latest_id)
