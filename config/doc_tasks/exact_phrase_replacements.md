# Exact Phrase Replacements

Apply only explicit phrase replacements requested by the user.

Return replacements only when:

- `old_text` is copied exactly from the provided block text
- `new_text` is the requested replacement
- the change is local and does not require rewriting the whole paragraph

`old_text` may be a substring inside a longer paragraph. If a quote contains the requested phrase, it counts as found and must be returned in `replacements`.

If a requested phrase is not present, add a report row explaining that it was not found. Do not invent replacement targets.
