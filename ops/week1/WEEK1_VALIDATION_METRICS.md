# Week 1 Validation Metrics

## Purpose
Measure whether Vera is helping in real-world collaboration without excess noise.

## Primary Metrics
1. MCP Compliance
- hydration ACK rate
- food threshold misses (lunch/dinner)
- movement/bathroom prompt completion rate

2. Reminder Followthrough
- reminders sent
- reminders acknowledged
- tasks closed (DONE/COMPLETE)
- tasks rescheduled
- tasks abandoned (>3 avoid cycles)

3. Initiative Quality
- proactive nudges delivered
- proactive nudges acknowledged
- user-rated usefulness (simple high/ok/noisy tag)

4. Isaac Sidecar Reliability
- live lesson JOINED ACK rate
- reminder chain completions (T-30/T-10/T-2)
- assignment start-step completion rate

5. Ops Throughput (Live Testing)
- feedback items triaged/day
- draft responses prepared/day
- unresolved P0 age

## Alert Thresholds (Week 1)
1. Hard interrupt budget exceeded > 1 day in week
2. Soft nudge ACK rate < 50%
3. Lunch or dinner hard-threshold misses on 2 consecutive days
4. JOINED ACK miss rate > 20%
5. Unresolved P0 older than 48 hours

## Data Sources
- followthrough ledgers/events
- proactive/autonomy logs
- push ACK log
- calendar/task state changes
- daily cards and closeout records

## End-of-Week Report Template
1. What worked reliably
2. What was noisy or ignored
3. Top 5 rule tunings for week 2
4. Scope expansion recommendations (assistant duties + project intensity)
