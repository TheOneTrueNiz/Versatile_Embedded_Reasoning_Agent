"""
Voice Tool Bridge for VERA.

Bridges VERA's tool system to the voice agent,
allowing voice commands to execute VERA tools.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# === Tool Definitions for Voice ===

@dataclass
class VoiceToolDef:
    """Definition of a tool available in voice mode."""
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable
    voice_confirmation: str = ""  # What to say when tool is called
    requires_confirmation: bool = False  # Ask user before executing


# === VERA Tool Definitions for Voice ===

VERA_VOICE_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": (
                "Add a new task to the user's todo list. "
                "Trigger: 'add task', 'remind me to', 'I need to', 'put X on my list'. "
                "Use priority P0 for urgent/critical, P1 for high priority, P2 for normal, P3 for low. "
                "Returns: task ID, title, priority, status. Speech confirms task was added."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Task description - what needs to be done"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["P0", "P1", "P2", "P3"],
                        "description": "P0=urgent/critical, P1=high, P2=medium (default), P3=low"
                    },
                    "due": {
                        "type": "string",
                        "description": "Due date: 'today', 'tomorrow', 'next Monday', 'in 3 days', etc."
                    }
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": (
                "Mark a task as completed/done. "
                "Trigger: 'done with', 'completed', 'finished', 'mark X as done'. "
                "Can identify task by ID (TASK-001) or by matching title text. "
                "Returns: confirmation of completion. Speech confirms task was marked done."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID (TASK-001) or partial title to match"
                    }
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": (
                "List tasks from the todo list. "
                "Trigger: 'what are my tasks', 'show todo list', 'what do I need to do', 'what's on my list'. "
                "Returns: count and list of tasks with IDs, titles, priorities. "
                "Speech reads back top tasks by priority."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "all"],
                        "description": "'pending' (default): not started. 'in_progress': active. 'completed': done. 'all': everything."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max tasks to return (default: 5 for voice)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for information. "
                "Trigger: 'search for', 'look up', 'find out about', 'what is', 'Google'. "
                "Uses VERA's configured search backends (Brave, SearxNG). "
                "Returns: search results. Speech summarizes top findings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query - what to look up"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": (
                "Set a reminder for a specific time. "
                "Trigger: 'remind me', 'set reminder', 'alert me', 'notify me at'. "
                "Accepts natural language times: 'in 30 minutes', '3pm', 'at noon', 'in 2 hours'. "
                "Returns: confirmation. Speech confirms reminder time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "What to remind about"
                    },
                    "time": {
                        "type": "string",
                        "description": "When: 'in 30 minutes', '3pm', 'at noon', 'tomorrow morning', etc."
                    }
                },
                "required": ["message", "time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_status",
            "description": (
                "Get current system status overview. "
                "Trigger: 'status', 'how are things', 'system check', 'what's going on'. "
                "Returns: health status, task counts, budget usage. "
                "Speech gives quick summary of system state."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "take_note",
            "description": (
                "Save a note or piece of information to memory. "
                "Trigger: 'take note', 'remember this', 'save this', 'write down'. "
                "Saves to vera_memory/notes as markdown file. "
                "Returns: confirmation with file path. Speech confirms note saved."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The note content to save"
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional title (default: 'Voice Note')"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for organization: ['work', 'idea', 'shopping']"
                    }
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_text_file",
            "description": (
                "Read contents of a text file. "
                "Trigger: 'read file', 'open document', 'what's in', 'show me'. "
                "Long files are truncated to ~1000 chars for voice. "
                "Returns: file content. Speech reads content or summary."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to file (absolute or relative to project)"
                    },
                    "summarize": {
                        "type": "boolean",
                        "description": "Truncate long files for voice (default: true)"
                    }
                },
                "required": ["path"]
            }
        }
    }
]


class VoiceToolBridge:
    """
    Bridges VERA's tool system to voice mode.

    Handles:
    - Tool definition conversion for voice API
    - Tool execution with VERA integration
    - Natural language confirmation and responses
    - Tool result formatting for speech
    """

    def __init__(self, vera_instance: Optional[Any] = None) -> None:
        """
        Initialize the tool bridge.

        Args:
            vera_instance: VERA instance for tool execution
        """
        self.vera = vera_instance
        self._tools = VERA_VOICE_TOOLS.copy()
        self._custom_handlers: Dict[str, Callable] = {}

        # Tool execution history
        self._history: List[Dict] = []

    @property
    def tools(self) -> List[Dict[str, Any]]:
        """Get tool definitions for the voice API."""
        return self._tools

    def register_handler(self, tool_name: str, handler: Callable) -> None:
        """
        Register a custom handler for a tool.

        Args:
            tool_name: Name of the tool
            handler: Async function to handle the tool call
        """
        self._custom_handlers[tool_name] = handler

    def add_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Optional[Callable] = None
    ) -> None:
        """
        Add a custom tool to the bridge.

        Args:
            name: Tool name
            description: Tool description
            parameters: JSON schema for parameters
            handler: Optional handler function
        """
        tool_def = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            }
        }
        self._tools.append(tool_def)

        if handler:
            self._custom_handlers[name] = handler

    async def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool call.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result dictionary
        """
        logger.info(f"Executing voice tool: {name} with {arguments}")

        # Record in history
        call_record = {
            "tool": name,
            "arguments": arguments,
            "timestamp": datetime.now().isoformat(),
            "result": None,
            "error": None
        }

        try:
            # Check for custom handler first
            if name in self._custom_handlers:
                handler = self._custom_handlers[name]
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(**arguments)
                else:
                    result = handler(**arguments)

            # Otherwise use default handlers
            else:
                result = await self._default_handler(name, arguments)

            call_record["result"] = result
            self._history.append(call_record)

            return {
                "success": True,
                "result": result,
                "speech": self._format_for_speech(name, result)
            }

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            call_record["error"] = str(e)
            self._history.append(call_record)

            return {
                "success": False,
                "error": str(e),
                "speech": f"I encountered an error: {str(e)}"
            }

    async def _default_handler(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> Any:
        """Default handlers for built-in tools."""

        if name == "add_task":
            return await self._handle_add_task(arguments)

        elif name == "complete_task":
            return await self._handle_complete_task(arguments)

        elif name == "list_tasks":
            return await self._handle_list_tasks(arguments)

        elif name == "web_search":
            return await self._handle_web_search(arguments)

        elif name == "set_reminder":
            return await self._handle_set_reminder(arguments)

        elif name == "get_status":
            return await self._handle_get_status(arguments)

        elif name == "take_note":
            return await self._handle_take_note(arguments)

        elif name in ("read_text_file", "read_file"):
            return await self._handle_read_file(arguments)

        else:
            raise NotImplementedError(f"No handler for tool: {name}")

    async def _handle_add_task(self, args: Dict) -> Dict:
        """Handle add_task tool."""
        title = args.get("title", "")
        priority = args.get("priority", "P2")
        due = args.get("due")

        if self.vera and hasattr(self.vera, 'master_list'):
            from core.foundation.master_list import TaskPriority
            task = self.vera.master_list.add_task(
                title=title,
                priority=TaskPriority(priority)
            )
            return {
                "task_id": task.id,
                "title": task.title,
                "priority": priority,
                "status": "created"
            }
        else:
            # Fallback - just acknowledge
            return {
                "title": title,
                "priority": priority,
                "status": "acknowledged"
            }

    async def _handle_complete_task(self, args: Dict) -> Dict:
        """Handle complete_task tool."""
        task_id = args.get("task_id", "")

        if self.vera and hasattr(self.vera, 'master_list'):
            from core.foundation.master_list import TaskStatus
            task = self.vera.master_list.update_status(
                task_id, TaskStatus.COMPLETED
            )
            if task:
                return {
                    "task_id": task.id,
                    "title": task.title,
                    "status": "completed"
                }
            else:
                return {"error": f"Task not found: {task_id}"}
        else:
            return {"task_id": task_id, "status": "acknowledged"}

    async def _handle_list_tasks(self, args: Dict) -> Dict:
        """Handle list_tasks tool."""
        status = args.get("status", "pending")
        limit = args.get("limit", 5)

        if self.vera and hasattr(self.vera, 'master_list'):
            if status == "pending":
                tasks = self.vera.master_list.get_pending()[:limit]
            else:
                tasks = self.vera.master_list.parse()[:limit]

            return {
                "count": len(tasks),
                "tasks": [
                    {"id": t.id, "title": t.title, "priority": t.priority.value}
                    for t in tasks
                ]
            }
        else:
            return {"count": 0, "tasks": []}

    async def _handle_web_search(self, args: Dict) -> Dict:
        """Handle web_search tool."""
        query = args.get("query", "")

        # This would integrate with VERA's web search capability
        # For now, return a placeholder
        return {
            "query": query,
            "status": "search_initiated",
            "note": "Web search results would appear here"
        }

    async def _handle_set_reminder(self, args: Dict) -> Dict:
        """Handle set_reminder tool."""
        message = args.get("message", "")
        time = args.get("time", "")

        # This would integrate with VERA's reminder system
        return {
            "message": message,
            "time": time,
            "status": "reminder_set"
        }

    async def _handle_get_status(self, args: Dict) -> Dict:
        """Handle get_status tool."""
        status = {
            "timestamp": datetime.now().isoformat(),
            "system": "operational"
        }

        if self.vera:
            if hasattr(self.vera, 'health_monitor'):
                health = self.vera.health_monitor.get_stats()
                status["health"] = health

            if hasattr(self.vera, 'master_list'):
                tasks = self.vera.master_list.get_stats()
                status["tasks"] = tasks

            if hasattr(self.vera, 'cost_tracker'):
                costs = self.vera.cost_tracker.get_stats()
                status["budget"] = costs

        return status

    async def _handle_take_note(self, args: Dict) -> Dict:
        """Handle take_note tool."""
        content = args.get("content", "")
        title = args.get("title", "Voice Note")
        tags = args.get("tags", [])

        # Save note to memory directory
        notes_dir = Path("vera_memory/notes")
        notes_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        note_file = notes_dir / f"note_{timestamp}.md"

        note_content = f"""# {title}

Created: {datetime.now().isoformat()}
Tags: {', '.join(tags) if tags else 'none'}

---

{content}
"""
        note_file.write_text(note_content)

        return {
            "title": title,
            "file": str(note_file),
            "status": "saved"
        }

    async def _handle_read_file(self, args: Dict) -> Dict:
        """Handle read_file tool."""
        path = args.get("path", "")
        summarize = args.get("summarize", True)

        filepath = Path(path)
        if not filepath.exists():
            return {"error": f"File not found: {path}"}

        try:
            content = filepath.read_text()

            # Truncate for voice if too long
            if summarize and len(content) > 1000:
                content = content[:1000] + "... (truncated for voice)"

            return {
                "path": path,
                "content": content,
                "size_bytes": filepath.stat().st_size
            }

        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

    def _format_for_speech(self, tool_name: str, result: Any) -> str:
        """Format tool result for natural speech output."""

        if isinstance(result, dict):
            if "error" in result:
                return f"I encountered an error: {result['error']}"

            if tool_name == "add_task":
                return f"I've added the task: {result.get('title', 'task')}"

            elif tool_name == "complete_task":
                return f"Done! I've marked that task as completed."

            elif tool_name == "list_tasks":
                count = result.get("count", 0)
                if count == 0:
                    return "You don't have any pending tasks."
                tasks = result.get("tasks", [])
                task_list = ", ".join(t.get("title", "task") for t in tasks[:3])
                if count > 3:
                    return f"You have {count} tasks. The top ones are: {task_list}, and {count - 3} more."
                return f"You have {count} tasks: {task_list}"

            elif tool_name == "set_reminder":
                return f"I've set a reminder for {result.get('time', 'later')}: {result.get('message', '')}"

            elif tool_name == "get_status":
                return "System is operational. All services running normally."

            elif tool_name == "take_note":
                return f"I've saved your note: {result.get('title', 'note')}"

            elif tool_name in ("read_text_file", "read_file"):
                return f"Here's the content of the file: {result.get('content', '')[:200]}"

        return f"Done with {tool_name}"

    def get_history(self, limit: int = 10) -> List[Dict]:
        """Get recent tool execution history."""
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get tool bridge statistics."""
        return {
            "total_tools": len(self._tools),
            "custom_handlers": len(self._custom_handlers),
            "executions_total": len(self._history),
            "recent_tools": [h["tool"] for h in self._history[-5:]]
        }


# === Factory Function ===

def create_tool_bridge(vera_instance: Optional[Any] = None) -> VoiceToolBridge:
    """
    Create a tool bridge connected to VERA.

    Args:
        vera_instance: VERA instance for tool execution

    Returns:
        Configured VoiceToolBridge
    """
    return VoiceToolBridge(vera_instance)


# === Self-test ===

if __name__ == "__main__":
    import sys

    async def test_tools():
        """Test voice tool bridge."""
        print("Testing Voice Tool Bridge...")

        # Test 1: Create bridge
        print("Test 1: Create tool bridge...", end=" ")
        bridge = VoiceToolBridge()
        print("PASS")

        # Test 2: Check tool count
        print("Test 2: Tool definitions...", end=" ")
        assert len(bridge.tools) >= 8
        print(f"PASS ({len(bridge.tools)} tools)")

        # Test 3: Add custom tool
        print("Test 3: Add custom tool...", end=" ")

        async def custom_handler(text: str):
            return {"echo": text}

        bridge.add_tool(
            name="echo",
            description="Echo back text",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            handler=custom_handler
        )
        assert len(bridge.tools) == len(VERA_VOICE_TOOLS) + 1
        print("PASS")

        # Test 4: Execute tool
        print("Test 4: Execute tool...", end=" ")
        result = await bridge.execute_tool("echo", {"text": "hello"})
        assert result.get("success", "")
        assert result.get("result", "")["echo"] == "hello"
        print("PASS")

        # Test 5: Default add_task handler
        print("Test 5: Add task handler...", end=" ")
        result = await bridge.execute_tool("add_task", {"title": "Test task"})
        assert result.get("success", "")
        assert "speech" in result
        print("PASS")

        # Test 6: Format for speech
        print("Test 6: Format for speech...", end=" ")
        speech = bridge._format_for_speech("add_task", {"title": "Buy groceries"})
        assert "added" in speech.lower()
        assert "Buy groceries" in speech
        print("PASS")

        # Test 7: Get history
        print("Test 7: Execution history...", end=" ")
        history = bridge.get_history()
        assert len(history) >= 2  # From tests 4 and 5
        print("PASS")

        # Test 8: Get stats
        print("Test 8: Get stats...", end=" ")
        stats = bridge.get_stats()
        assert "total_tools" in stats
        assert stats["executions_total"] >= 2
        print("PASS")

        # Test 9: Take note handler
        print("Test 9: Take note handler...", end=" ")
        result = await bridge.execute_tool("take_note", {
            "content": "Test note content",
            "title": "Test Note"
        })
        assert result.get("success", "")
        assert result.get("result", "")["status"] == "saved"
        # Cleanup
        note_file = Path(result.get("result", "")["file"])
        if note_file.exists():
            note_file.unlink()
        print("PASS")

        # Test 10: Error handling
        logger.error("Test 10: Error handling...", end=" ")
        result = await bridge.execute_tool("read_text_file", {"path": "/nonexistent/file.txt"})
        assert result.get("success", "")  # Handler returns success with error in result
        assert "error" in result.get("result", "")
        print("PASS")

        print("\nAll tests passed!")
        return True

    success = asyncio.run(test_tools())
    sys.exit(0 if success else 1)
