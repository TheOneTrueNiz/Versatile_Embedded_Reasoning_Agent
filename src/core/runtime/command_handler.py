"""
Command Handler
==============

Handles VERA slash commands (e.g., /status, /tasks, /innerlife).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.foundation.master_list import TaskStatus
from planning.project_charter import CharterStatus
from context.preferences import PreferenceCategory
from context.dnd_mode import DNDLevel
from observability.reversibility import UndoStatus


class CommandHandler:
    """Slash command routing for VERA."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._owner, name)

    async def handle_command(self, command: str) -> str:
        """
        Handle slash commands.

        Tier 1 Commands:
            /tasks - Show task summary
            /add <title> - Add a task
            /complete <id> - Complete a task
            /status - Show system status

        Tier 2 Commands:
            /decisions - Show recent decisions
            /costs - Show cost/budget status
            /git - Show git status
            /undo [id] - List undoable actions or undo specific action
        """
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # === Tier 1 Commands ===
        if cmd == '/tasks':
            return self.master_list.summarize()

        if cmd == '/add' and args:
            task = self.master_list.add_task(title=args)
            return f"Created task {task.id}: {task.title}"

        if cmd == '/complete' and args:
            task = self.master_list.update_status(args.upper(), TaskStatus.COMPLETED)
            if task:
                return f"Completed: {task.id} - {task.title}"
            return f"Task not found: {args}"

        if cmd == '/inprogress' and args:
            task = self.master_list.update_status(args.upper(), TaskStatus.IN_PROGRESS)
            if task:
                return f"Started: {task.id} - {task.title}"
            return f"Task not found: {args}"

        if cmd == '/status':
            task_stats = self.master_list.get_stats()
            panic_status = self.panic_button.get_status()
            health = self.health_monitor.get_stats()
            cost_stats = self.cost_tracker.get_stats()
            decision_stats = self.decision_ledger.get_stats()
            reversibility_stats = self.reversibility.get_stats()
            git_status = self.git_context.get_repo_status()
            spiral_stats = self.rabbit_hole.get_stats()
            pref_stats = self.preferences.get_stats()
            active_projects = len(self.charters.list_charters(status=CharterStatus.IN_PROGRESS))

            dnd_status = self.dnd.get_status()
            sentinel_stats = self.sentinel.get_statistics()
            budget_pct = cost_stats.get("budget_used_percent", cost_stats.get("budget_pct_used", 0.0))

            return f"""System Status:
- Uptime: {int((datetime.now() - self.session_start).total_seconds())}s
- Events: {self.events_processed}
- Health: {'Healthy' if health['healthy'] else 'Degraded'}
- Tasks: {task_stats['total']} total, {task_stats['pending']} pending, {task_stats['overdue']} overdue
- Tracked Processes: {panic_status['tracked_processes']}
- Safe Boot: {'Active' if self.bootloader else 'Disabled'}
- Budget: ${cost_stats['remaining_budget']:.4f} remaining ({budget_pct:.1f}% used)
- Decisions: {decision_stats['total_decisions']} logged
- Undoable Actions: {reversibility_stats['active']}
- Git: {git_status.branch if git_status.is_repo else 'Not a git repo'}{' (clean)' if git_status.is_clean else f' ({git_status.modified_count} modified)'}
- Active Projects: {active_projects}
- Preferences: {pref_stats['total_preferences']} learned
- Spiral Watch: {spiral_stats['spiraling_tasks']} tasks flagged
- DND: {'Active (' + dnd_status.level.value + ')' if dnd_status.is_active else 'Off'} ({self.dnd.get_queued_count()} queued)
- Sentinel: {sentinel_stats['state']} ({sentinel_stats['triggers']['enabled']} triggers active)"""

        # === Tier 2 Commands ===
        if cmd == '/decisions':
            return self.decision_ledger.summarize_recent(hours=24)

        if cmd == '/costs':
            stats = self.cost_tracker.get_stats()
            top_spenders = self.cost_tracker.get_top_spenders(5)
            budget_pct = stats.get("budget_used_percent", stats.get("budget_pct_used", 0.0))

            result = f"""Cost Status:
- Session Budget: ${stats['session_budget']:.4f}
- Total Cost: ${stats['total_cost']:.4f}
- Remaining: ${stats['remaining_budget']:.4f} ({100 - budget_pct:.1f}%)
- Total Calls: {stats['total_calls']}
- Cache Hit Rate: {stats['cache_hit_rate']:.1%}

Top Spending Tools:"""
            for item in top_spenders:
                tool = item.get("tool", "unknown")
                cost = float(item.get("cost", 0.0) or 0.0)
                calls = int(item.get("calls", 0) or 0)
                result += f"\n  - {tool}: ${cost:.4f} ({calls} calls)"
            return result

        if cmd == '/git':
            return self.git_context.format_status_summary()

        if cmd == '/undo':
            if args:
                action_id = args.upper()
                status, message = self.reversibility.undo(action_id)
                if status == UndoStatus.SUCCESS:
                    return f"Undone: {message}"
                return f"Undo failed ({status.value}): {message}"
            return self.reversibility.summarize_undoable()

        # === Tier 3 Commands ===
        if cmd == '/projects':
            return self.charters.summarize()

        if cmd == '/project' and args:
            if args.upper().startswith("PROJ-"):
                charter = self.charters.get_charter(args.upper())
                if charter:
                    return charter.to_markdown()
                return f"Project not found: {args}"
            charter = self.charters.create_charter(
                title=args,
                goal="(Define goal)",
                approach="(Define approach)",
                success_criteria=["(Define criteria)"],
                auto_approve=False
            )
            return f"Created draft charter: {charter.id}\nEdit at: vera_memory/charters/{charter.id}.md"

        if cmd == '/prefs':
            return self.preferences.summarize()

        if cmd == '/pref' and args:
            if '=' in args:
                key_part, value = args.split('=', 1)
                if '.' in key_part:
                    category, key = key_part.split('.', 1)
                    try:
                        cat_enum = PreferenceCategory(category)
                        self.preferences.set_preference(cat_enum, key, value.strip())
                        return f"Set preference: {category}.{key} = {value.strip()}"
                    except ValueError:
                        return f"Unknown category: {category}. Valid: {[c.value for c in PreferenceCategory]}"
                return "Format: /pref category.key=value"
            return "Format: /pref category.key=value"

        if cmd == '/spiral':
            stats = self.rabbit_hole.get_stats()
            result = f"""Spiral Detection Status:
- Tasks tracked: {stats['tasks_tracked']}
- Spiraling tasks: {stats['spiraling_tasks']}"""
            if stats['spiraling_task_ids']:
                result += f"\n- Flagged: {', '.join(stats['spiraling_task_ids'])}"
            return result

        if cmd == '/critique' and args:
            result = self.critic.review(args)
            return self.critic.format_critique(result)

        # === Proactive Intelligence Commands (Improvements #11 & #12) ===
        if cmd == '/dnd':
            if not args:
                return self.dnd.summarize()
            if args.lower() == 'off':
                self.dnd.disable_dnd()
                return "DND disabled. Queued interrupts delivered."
            if args.lower() in ['low', 'medium', 'high', 'critical']:
                level = DNDLevel(args.lower())
                self.dnd.enable_dnd(level, reason="User requested via /dnd")
                return f"DND enabled: {level.value}"
            parts = args.split()
            if len(parts) == 1 and parts[0].isdigit():
                duration = int(parts[0])
                self.dnd.enable_dnd(DNDLevel.MEDIUM, duration_minutes=duration, reason="Timed DND")
                return f"DND enabled for {duration} minutes"
            if len(parts) == 2 and parts[0].lower() in ['low', 'medium', 'high', 'critical'] and parts[1].isdigit():
                level = DNDLevel(parts[0].lower())
                duration = int(parts[1])
                self.dnd.enable_dnd(level, duration_minutes=duration, reason="Timed DND")
                return f"DND ({level.value}) enabled for {duration} minutes"
            return "Usage: /dnd [off|low|medium|high|critical|<minutes>|<level> <minutes>]"

        if cmd == '/sentinel':
            stats = self.sentinel.get_statistics()
            recs = self.sentinel.get_recommendations()
            result = f"""Sentinel Engine Status:
- State: {stats['state']}
- Triggers: {stats['triggers']['total']} total, {stats['triggers']['enabled']} enabled
- Event Queue: {stats['event_queue_size']} events
- Pending Recommendations: {len(recs)}"""
            if recs:
                result += "\n\nPending Actions:"
                for rec in recs[:3]:
                    result += f"\n  [{rec.priority.name}] {rec.description}"
            return result

        if cmd == '/innerlife':
            if not hasattr(self, 'inner_life') or not self.inner_life:
                return "Inner Life Engine not available."

            subcmd = (args.split()[0].lower() if args else "status")
            subcmd_args = " ".join(args.split()[1:]) if args and len(args.split()) > 1 else ""

            if subcmd == "status":
                stats = self.inner_life.get_statistics()
                return f"""Inner Life Engine Status:
- Enabled: {stats['enabled']}
- Interval: {stats['interval_seconds']}s
- Active hours: {'yes' if stats['within_active_hours'] else 'no'}
- Total reflections: {stats['total_reflections']}
- Personality version: v{stats['personality_version']}
- Current mood: {stats['current_mood']}
- Journal entries: {stats['journal_entries']}
- Interests: {', '.join(stats['interests']) if stats['interests'] else 'none yet'}
- Delivery channels: {', '.join(stats['delivery_channels'])}
- Last reflection: {stats['last_reflection']}
- Model override: {stats['model_override'] or 'default'}"""

            if subcmd == "reflect":
                await self._run_reflection_cycle(trigger="forced", force=True)
                return "Reflection cycle executed. Check /innerlife journal for results."

            if subcmd == "journal":
                n = 10
                if subcmd_args:
                    try:
                        n = int(subcmd_args)
                    except ValueError:
                        pass
                return self.inner_life.format_journal(n)

            if subcmd == "personality":
                return self.inner_life.format_personality()

            if subcmd == "on":
                self.inner_life.config.enabled = True
                return "Inner Life Engine enabled."

            if subcmd == "off":
                self.inner_life.config.enabled = False
                return "Inner Life Engine disabled."

            return "Usage: /innerlife [status|reflect|journal [n]|personality|on|off]"

        if cmd == '/voice':
            if not args or args.lower() in ["status", "state"]:
                return self._voice_status()

            parts = args.split()
            subcmd = parts[0].lower()

            if subcmd in ["start", "on"]:
                voice_name = parts[1] if len(parts) > 1 else "ara"
                return await self._start_voice_session(voice_name)

            if subcmd in ["stop", "off"]:
                return await self._stop_voice_session()

            if subcmd in ["ara", "eve", "leo"]:
                return await self._start_voice_session(subcmd)

            return "Usage: /voice [start|stop|status] [ara|eve|leo]"

        if cmd == '/darwin':
            stats = self.darwin.get_statistics()
            active = self.darwin.get_active_individual()
            history = self.darwin.get_evolution_history()

            result = f"""Darwinian Evolution Status:
- Enabled: {'Yes (dev_mode)' if self.darwin_enabled else 'No'}
- Current Generation: {stats['current_generation']}
- Population Size: {stats['population_size']}
- Stagnant: {'Yes' if stats['is_stagnant'] else 'No'}
- Safety Violations: {stats['safety_violations']}
- Evolution Runs: {len(history)}"""

            if active:
                result += f"\n- Active Individual: {active.individual_id}"
                if active.fitness:
                    result += f" (fitness: {active.fitness.overall_fitness():.3f})"
                result += f"\n- Mutations Applied: {len(active.mutations)}"

            if stats['best_fitness_history']:
                result += f"\n- Best Fitness History: {', '.join(f'{f:.2f}' for f in stats['best_fitness_history'][-5:])}"

            return result

        if cmd == '/mcp':
            stats = self.mcp.get_stats()
            result = f"""MCP Server Orchestration Status:
- Configured: {stats['configured_servers']} servers
- Running: {stats['running_servers']} servers
- Healthy: {stats['healthy_servers']} servers
- Total Tool Calls: {stats['total_requests']}"""

            if args and args.lower() == 'list':
                result += "\n\nServer Details:"
                for name, config in self.mcp.configs.items():
                    server = self.mcp.servers.get(name)
                    status = "Running" if server and server.process and server.process.poll() is None else "Stopped"
                    result += f"\n  [{status}] {name}: {config.command} {' '.join(config.args)}"
            else:
                result += "\n\nUse /mcp list to see server details"

            return result

        if cmd == '/help':
            return """Available commands:

Tier 1 (Tasks & Safety):
  /tasks         - Show task summary
  /add <task>    - Add a new task
  /complete <id> - Complete a task (e.g., /complete TASK-001)
  /inprogress <id> - Mark task in progress
  /stop          - Emergency shutdown (kills processes, reverts writes)

Tier 2 (Trust & Insights):
  /decisions     - Show recent decisions (last 24h)
  /costs         - Show cost/budget status
  /git           - Show git repository status
  /undo [id]     - List undoable actions or undo a specific action

Tier 3 (Productivity):
  /projects      - Show project charters summary
  /project <id|title> - View project or create new draft
  /prefs         - Show learned preferences
  /pref key=val  - Set a preference (e.g., /pref communication.length=concise)
  /spiral        - Show spiral detection status
  /critique <text> - Critique text for tone/clarity

Proactive Intelligence (#11 & #12):
  /dnd           - Show Do Not Disturb status
  /dnd off       - Disable DND mode
  /dnd <level>   - Enable DND (low/medium/high/critical)
  /dnd <mins>    - Enable medium DND for N minutes
  /dnd <level> <mins> - Enable DND at level for N minutes
  /sentinel      - Show Sentinel Engine status and pending actions

Inner Life (Proactive Consciousness):
  /innerlife           - Show inner life engine status
  /innerlife reflect   - Force an immediate reflection cycle
  /innerlife journal [n] - Show last N inner thoughts (default 10)
  /innerlife personality - Show evolved personality state
  /innerlife on|off    - Enable/disable inner life engine

Voice:
  /voice         - Show voice session status
  /voice start   - Start voice session (default: ara)
  /voice stop    - Stop voice session
  /voice <name>  - Start with specific voice (ara|eve|leo)

Self-Evolution (#22):
  /darwin        - Show Darwinian evolution status (requires dev_mode)

MCP Integration:
  /mcp           - Show MCP server status
  /mcp list      - Show detailed server list

General:
  /status        - Show full system status
  /help          - Show this help"""

        return f"Unknown command: {cmd}. Type /help for available commands."
