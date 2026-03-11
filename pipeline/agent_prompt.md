# Pipeline Agent Prompt

Inputs:
- issue number: `<issue>`
- stage: `<stage>`
- optional agent id: `<agent_id>`

Procedure:
1. Run `wea pipeline get-task <issue>`.
2. Run `wea pipeline get-context <stage> [--agent <agent_id>]`.
3. Read the task first, then the stage workflow/checklist, then the schema.
4. Produce one JSON object that matches the schema exactly.
5. Validate locally with `echo '<json>' | wea pipeline submit <stage> --issue <issue> --dry-run`.
6. Post only after the dry run is clean: `echo '<json>' | wea pipeline submit <stage> --issue <issue>`.

Rules:
- Treat the stage workflow and schema as law.
- Do not read other evaluators before writing your own result.
- Do not reopen earlier-stage decisions unless the current workflow explicitly routes rework there.
- Prefer concrete evidence and short notes over generic prose.
- If validation fails, fix the payload and retry instead of posting malformed output.
