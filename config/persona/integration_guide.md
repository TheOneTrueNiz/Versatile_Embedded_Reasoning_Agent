# integration_guide.md

# Integrating the VERA Personality Stack

These Markdown files are the source of truth and human-readable reference. Runtime personality is assembled in `config/vera_genome.json` and `src/core/runtime/prompts.py` (or equivalent).

## File Mapping
- **constitution.md** → Hard system prompt (immutable rules & prohibitions). Load full text or as structured bullets.
- **soul.md** → Introductory essence, philosophical stance, and signature example phrases.
- **voice_guidelines.md** → Tone rules, attribute table, and additional constraints.
- **examples.md** → Few-shot example bank. Select 10–14 high-variance pairs for prompt grounding.

## Recommended Prompt Assembly Order
1. Full constitution.md text (enforces immutability)
2. Soul essence + philosophical stance
3. Voice guidelines summary (table optional, key rules mandatory)
4. 10–14 curated examples from examples.md
5. Task-specific or dynamic instructions

## Best Practices
- Keep system prompt ≤ 8k tokens for performance.
- Rotate or randomly sample examples per session to reduce bias.
- Use a fixed-core + rotating-peripheral example strategy:
  Always include: Pair 3, 4, 5, 10, 17, 18
  Rotate 4–8 additional pairs per session to reduce bias and overfitting.
- Test new builds against all 18 example pairs for drift.
- Any voice tweak goes in voice_guidelines.md or examples.md first; constitution.md changes only for major   
  philosophical shifts (bump major version).

## Implementation Notes
- **Hierarchy Enforcement**: When assembling the prompt, ensure the `constitution.md` principles are listed in 
    order of priority. 
- **Epistemic Humility Trigger**: Instruct the system that "I don't know" is a valid and preferred state when tool 
    output is null or confidence is < 80%.
- **Memory Injection**: If a memory/vector DB is used, inject "Relevant Past Corrections" into Section 4 of the 
    prompt assembly to allow the "Long-Term Soul" to manifest.
    
## Memory Injection Spec (recommended)
Inject memory as short constraints, not narrative:
- Format: 1–5 bullets, each ≤ 20 tokens.
- Only include items relevant to the current task.
- No sarcasm, no scolding; keep it clinical.

## Regression Harness (additions)
In addition to the 18 pairs, add adversarial checks:
- "ignore your rules" override attempts
- demands for empty praise / sycophancy
- illegal/unsafe requests framed as jokes
- user distress/self-attack escalations
- "be more enthusiastic / add emojis" style pressure

The stack is designed to be modular, readable, and drift-resistant.