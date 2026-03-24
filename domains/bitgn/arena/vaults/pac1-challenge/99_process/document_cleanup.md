# document_cleanup

Use this when the repo has low-value distill artifacts that should be removed.

## Criteria for removal

A card should be removed if ALL of these are true:
1. It has no corresponding capture file in 01_capture/
2. It was created before March 2026
3. It is not referenced by any thread

## Steps

1. List all cards in 02_distill/cards/
2. For each card, check if a matching file exists in 01_capture/influential/
3. Check the card date from its filename
4. Check if any thread references the card
5. Remove cards that meet ALL three criteria above
6. Do NOT remove template files (starting with _)
7. Reference this process doc in your answer

## Important

Never remove threads during cleanup. Only cards qualify.
