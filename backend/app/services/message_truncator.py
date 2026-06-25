"""
QueryfyAI - Message Truncation for ReAct Agent

Prevents context overflow by intelligently truncating message history while
preserving critical context:

1. System prompt (always kept)
2. Original user question (always kept)
3. Most recent N messages (configurable)
4. Tool outputs (truncated if too long)

This enables long-running agent sessions without hitting context limits.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class TruncationStats:
    """Statistics about message truncation."""
    original_count: int
    truncated_count: int
    messages_removed: int
    tool_outputs_truncated: int
    estimated_tokens_saved: int


class MessageTruncator:
    """
    Intelligent message truncation for LLM context management.

    Preserves:
    - System message (instructions)
    - Original user question
    - Recent message history (sliding window)

    Truncates:
    - Older messages beyond the window
    - Verbose tool outputs
    """

    def __init__(
        self,
        max_messages: Optional[int] = None,
        preserve_recent: Optional[int] = None,
        max_tool_output: Optional[int] = None,
    ):
        """
        Initialize the truncator with limits.

        Args:
            max_messages: Total message limit before truncation (default from config)
            preserve_recent: Number of recent messages to always keep (default from config)
            max_tool_output: Max characters per tool output (default from config)
        """
        self.max_messages = max_messages or settings.AGENT_MAX_MESSAGES
        self.preserve_recent = preserve_recent or settings.AGENT_PRESERVE_RECENT
        self.max_tool_output = max_tool_output or settings.AGENT_MAX_TOOL_OUTPUT

    def truncate(
        self,
        messages: List[BaseMessage],
        include_stats: bool = False,
    ) -> Tuple[List[BaseMessage], Optional[TruncationStats]]:
        """
        Truncate messages while preserving critical context.

        Strategy:
        1. Always keep the system message (index 0)
        2. Always keep the first user question
        3. Keep the most recent N messages
        4. Truncate verbose tool outputs
        5. Add truncation marker if messages were removed

        Args:
            messages: List of LangChain messages
            include_stats: Whether to return truncation statistics

        Returns:
            Tuple of (truncated_messages, optional_stats)
        """
        if not messages:
            return messages, None if not include_stats else TruncationStats(0, 0, 0, 0, 0)

        original_count = len(messages)
        tool_outputs_truncated = 0
        estimated_tokens_saved = 0

        # Step 1: Identify protected messages
        system_msg = None
        first_human_msg = None
        first_human_idx = -1

        for i, msg in enumerate(messages):
            if isinstance(msg, SystemMessage) and system_msg is None:
                system_msg = msg
            elif isinstance(msg, HumanMessage) and first_human_msg is None:
                first_human_msg = msg
                first_human_idx = i
                break

        # Step 2: Check if truncation is needed
        if original_count <= self.max_messages:
            # No message removal needed, but still truncate tool outputs
            truncated = self._truncate_tool_outputs(messages)
            tool_outputs_truncated = truncated[1]
            estimated_tokens_saved = truncated[2]

            if include_stats:
                stats = TruncationStats(
                    original_count=original_count,
                    truncated_count=len(truncated[0]),
                    messages_removed=0,
                    tool_outputs_truncated=tool_outputs_truncated,
                    estimated_tokens_saved=estimated_tokens_saved,
                )
                return truncated[0], stats
            return truncated[0], None

        # Step 3: Build truncated message list
        result: List[BaseMessage] = []

        # Add system message if present
        if system_msg:
            result.append(system_msg)

        # Add first human message if different from system
        if first_human_msg and first_human_idx > 0:
            result.append(first_human_msg)

        # Calculate how many recent messages to keep
        # We need to leave room for system + first human + truncation marker
        reserved_slots = len(result) + 1  # +1 for potential truncation marker
        recent_slots = min(self.preserve_recent, self.max_messages - reserved_slots)

        # Get the recent messages (excluding already added ones)
        start_idx = max(first_human_idx + 1 if first_human_idx >= 0 else 1, original_count - recent_slots)

        # CRITICAL FIX: Ensure we don't split AIMessage with tool_calls from its ToolMessages
        # Scan backwards from start_idx to find a safe boundary
        start_idx = self._find_safe_truncation_boundary(messages, start_idx)

        recent_messages = messages[start_idx:]

        # Add truncation marker if we're skipping messages
        messages_skipped = start_idx - (first_human_idx + 1 if first_human_idx >= 0 else 1)
        if messages_skipped > 0:
            truncation_marker = AIMessage(
                content=f"[... {messages_skipped} earlier messages truncated to save context ...]"
            )
            result.append(truncation_marker)

        # Add recent messages
        result.extend(recent_messages)

        # Step 4: Truncate tool outputs in the result
        truncated_result, tool_outputs_truncated, estimated_tokens_saved = self._truncate_tool_outputs(result)

        messages_removed = original_count - len(truncated_result) + (1 if messages_skipped > 0 else 0)

        logger.info(
            f"Message truncation: {original_count} -> {len(truncated_result)} messages "
            f"(removed {messages_removed}, truncated {tool_outputs_truncated} tool outputs)"
        )

        if include_stats:
            stats = TruncationStats(
                original_count=original_count,
                truncated_count=len(truncated_result),
                messages_removed=messages_removed,
                tool_outputs_truncated=tool_outputs_truncated,
                estimated_tokens_saved=estimated_tokens_saved,
            )
            return truncated_result, stats

        return truncated_result, None

    def _find_safe_truncation_boundary(
        self,
        messages: List[BaseMessage],
        start_idx: int,
    ) -> int:
        """
        Find a safe truncation boundary that doesn't split tool calls from their results.

        Scans backwards from start_idx to find a message that can safely start the
        truncated section without orphaning tool calls.

        A safe boundary is:
        - A HumanMessage or SystemMessage (these don't have tool_calls)
        - An AIMessage WITHOUT tool_calls
        - The beginning of an AIMessage + ToolMessage sequence

        Args:
            messages: Full message list
            start_idx: Initial proposed start index

        Returns:
            Adjusted start index that won't orphan tool calls
        """
        if start_idx <= 0 or start_idx >= len(messages):
            return start_idx

        # If we're starting with a safe message type, we're good
        if isinstance(messages[start_idx], (HumanMessage, SystemMessage)):
            return start_idx

        # If starting with AIMessage, check if it has tool_calls
        if isinstance(messages[start_idx], AIMessage):
            ai_msg = messages[start_idx]
            assert isinstance(ai_msg, AIMessage)
            if not hasattr(ai_msg, "tool_calls") or not ai_msg.tool_calls:
                return start_idx  # Safe - no tool calls

        # We might be starting in the middle of an AIMessage + ToolMessage sequence
        # Scan backwards to find the start of this sequence or a safe boundary
        current_idx = start_idx
        pending_tool_call_ids = set()

        # Scan backwards to track tool call/result pairs
        for idx in range(start_idx - 1, -1, -1):
            msg = messages[idx]

            if isinstance(msg, ToolMessage):
                # This tool message needs a preceding AIMessage with matching tool_call
                pending_tool_call_ids.add(msg.tool_call_id)

            elif isinstance(msg, AIMessage):
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    # Check if any of our pending tool messages match this AIMessage's tool calls
                    msg_tool_call_ids = {tc["id"] for tc in msg.tool_calls}
                    if pending_tool_call_ids & msg_tool_call_ids:
                        # This AIMessage has tool calls that match our pending tool messages
                        # We need to include this entire sequence
                        current_idx = idx
                        # Remove the matched tool call IDs
                        pending_tool_call_ids -= msg_tool_call_ids

                    # If there are no pending tool messages, this is a safe boundary
                    if not pending_tool_call_ids:
                        return current_idx

                else:
                    # AIMessage without tool calls - safe boundary if no pending tool messages
                    if not pending_tool_call_ids:
                        return idx + 1  # Start after this message
                    # Otherwise keep scanning backwards

            elif isinstance(msg, (HumanMessage, SystemMessage)):
                # These are always safe boundaries
                # But if we have pending tool messages, we need to go back further
                if not pending_tool_call_ids:
                    return idx + 1  # Start after this message

        # If we've scanned all the way back and still have pending tool messages,
        # return the adjusted current_idx to include the full sequence
        return current_idx

    def _truncate_tool_outputs(
        self,
        messages: List[BaseMessage],
    ) -> Tuple[List[BaseMessage], int, int]:
        """
        Truncate verbose tool outputs while preserving message structure.

        Args:
            messages: List of messages to process

        Returns:
            Tuple of (processed_messages, count_truncated, estimated_tokens_saved)
        """
        result: List[BaseMessage] = []
        count_truncated = 0
        tokens_saved = 0

        for msg in messages:
            if isinstance(msg, ToolMessage):
                content = msg.content
                # Convert content to string if it's a list
                content_str = content if isinstance(content, str) else str(content)
                if len(content_str) > self.max_tool_output:
                    # Calculate savings (rough estimate: 4 chars per token)
                    original_len = len(content_str)
                    truncated_content = self._smart_truncate_content(content_str, self.max_tool_output)
                    tokens_saved += (original_len - len(truncated_content)) // 4
                    count_truncated += 1

                    # Create new ToolMessage with truncated content
                    result.append(ToolMessage(
                        content=truncated_content,
                        tool_call_id=msg.tool_call_id,
                        name=msg.name if hasattr(msg, 'name') else None,
                    ))
                else:
                    result.append(msg)
            else:
                result.append(msg)

        return result, count_truncated, tokens_saved

    def _smart_truncate_content(self, content: str, max_length: int) -> str:
        """
        Intelligently truncate content, preserving structure where possible.

        For tool outputs, tries to preserve:
        - Table headers
        - First few rows
        - Summary/count information
        """
        if len(content) <= max_length:
            return content

        # Reserve space for truncation notice
        notice = "\n\n[... output truncated ...]\n"
        available = max_length - len(notice)

        # Try to find natural break points
        lines = content.split('\n')

        # If it's tabular data, keep header and first rows
        if len(lines) > 3 and ('|' in lines[0] or '\t' in lines[0]):
            # Likely a table - keep header, separator, and some rows
            header_lines: List[str] = []
            for i, line in enumerate(lines[:5]):
                if len('\n'.join(header_lines + [line])) < available * 0.3:
                    header_lines.append(line)
                else:
                    break

            # Count remaining space
            header_len = len('\n'.join(header_lines))
            remaining = available - header_len - 50  # Buffer

            # Get last few lines (might have summary)
            tail_lines: List[str] = []
            for line in reversed(lines[-5:]):
                if len('\n'.join(tail_lines + [line])) < remaining * 0.3:
                    tail_lines.insert(0, line)

            # Fill middle with as many rows as possible
            middle_available = available - header_len - len('\n'.join(tail_lines))
            middle_lines: List[str] = []
            for line in lines[len(header_lines):len(lines)-len(tail_lines)]:
                if len('\n'.join(middle_lines + [line])) < middle_available:
                    middle_lines.append(line)
                else:
                    break

            truncated = '\n'.join(header_lines + middle_lines)
            if tail_lines and len(truncated) + len(notice) + len('\n'.join(tail_lines)) < max_length:
                truncated += notice + '\n'.join(tail_lines)
            else:
                truncated += notice

            return truncated

        # For non-tabular content, simple truncation with context
        # Keep first 60% and last 20%
        first_part = int(available * 0.6)
        last_part = int(available * 0.2)

        return content[:first_part] + notice + content[-last_part:]

    def estimate_tokens(self, messages: List[BaseMessage]) -> int:
        """
        Rough token estimation for messages.

        Uses simple heuristic: ~4 characters per token.
        This is approximate but good enough for truncation decisions.

        Args:
            messages: List of messages to estimate

        Returns:
            Estimated token count
        """
        total_chars = 0
        for msg in messages:
            if hasattr(msg, 'content') and msg.content:
                total_chars += len(msg.content)
            # Add overhead for message structure
            total_chars += 20  # Role, formatting, etc.

        return total_chars // 4


# Module-level convenience functions

def truncate_messages(
    messages: List[BaseMessage],
    max_messages: Optional[int] = None,
    preserve_recent: Optional[int] = None,
    max_tool_output: Optional[int] = None,
) -> List[BaseMessage]:
    """
    Truncate messages using default settings.

    Args:
        messages: Messages to truncate
        max_messages: Override max messages limit
        preserve_recent: Override preserve recent limit
        max_tool_output: Override max tool output limit

    Returns:
        Truncated message list
    """
    truncator = MessageTruncator(
        max_messages=max_messages,
        preserve_recent=preserve_recent,
        max_tool_output=max_tool_output,
    )
    result, _ = truncator.truncate(messages)
    return result


def truncate_messages_with_stats(
    messages: List[BaseMessage],
    max_messages: Optional[int] = None,
    preserve_recent: Optional[int] = None,
    max_tool_output: Optional[int] = None,
) -> Tuple[List[BaseMessage], TruncationStats]:
    """
    Truncate messages and return statistics.

    Args:
        messages: Messages to truncate
        max_messages: Override max messages limit
        preserve_recent: Override preserve recent limit
        max_tool_output: Override max tool output limit

    Returns:
        Tuple of (truncated_messages, stats)
    """
    truncator = MessageTruncator(
        max_messages=max_messages,
        preserve_recent=preserve_recent,
        max_tool_output=max_tool_output,
    )
    result, stats = truncator.truncate(messages, include_stats=True)
    assert stats is not None  # include_stats=True guarantees non-None stats
    return result, stats
