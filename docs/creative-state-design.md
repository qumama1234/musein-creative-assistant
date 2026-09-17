# Multi-turn creative state: design and limitations

For production image-generation risks beyond specification management, see
[real-world-image-risks.md](real-world-image-risks.md).

## Scope

This prototype keeps the user's current creative specification aligned with the
prompt. It does not claim that an image model will obey that prompt, and it does
not inspect generated pixels.

The system separates:

- hard constraints that must survive edits and can be compared for conflicts;
- reference roles that limit how each asset may be used;
- open creative notes that remain verbatim for an LLM to interpret.

## Transaction

Each turn is parsed into a `ChangeSet`. The engine applies it to a cloned state,
checks same-turn conflicts, and commits only a valid candidate. A rejected turn
returns the previous prompt and state, so the last usable result is never lost.

Skill values carry `source=skill`. User edits carry `source=user`. Disabling a
Skill removes only values still owned exclusively by that Skill.

## Deliberate parser boundary

The bundled Chinese parser is deterministic and intentionally limited. It is a
testable adapter, not a claim of unrestricted natural-language understanding.
An LLM can later produce the same `ChangeSet` schema, but validation, state
ownership, conflict rejection, and commit must remain in deterministic code.

## Known problems

1. The rule parser covers common expressions, not arbitrary paraphrases. An
   unknown clause is preserved as a creative note, which avoids data loss but
   may miss a hard constraint.
2. Conflict detection currently handles incompatible values on the same path.
   Semantic and cross-field conflicts need a rule registry or a separate model
   judgment followed by deterministic validation.
3. Field granularity affects meaning. For example, changing light temperature
   should not replace its direction or softness; other domains will require
   similarly careful sub-fields.
4. Mixed provenance can become complex. A composed idea may be partly supplied
   by a Skill and partly by a user, so whole-field provenance is insufficient
   unless the field is decomposed.
5. "Disable Skill" is defined here as removing Skill-owned defaults. A product
   may instead want to keep visible defaults or stop only future suggestions;
   that user-facing contract must be explicit.
6. A correct specification and prompt do not prove that a generated image is
   correct. A production loop needs post-generation checks with `passed`,
   `failed`, `uncertain`, and `not_verifiable` outcomes.
7. Even visual checking is probabilistic. Brand marks, exact labels, subjective
   style, and color under changed lighting often require deterministic image
   comparison or human confirmation.
8. "Use image_B only for lighting" cannot be guaranteed by prompt text alone.
   A safer production pipeline would extract a lighting description first and
   avoid passing image_B into the final generation step when possible.

## Important boundary cases

- Subjective language next to a structured edit is preserved instead of being
  dropped or forced into a misleading field.
- Re-enabling a Skill fills only missing defaults and never overwrites a field
  already owned by the user.
