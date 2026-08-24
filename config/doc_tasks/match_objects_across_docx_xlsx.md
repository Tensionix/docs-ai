# Match Objects Across DOCX and XLSX

Use all provided files as one corpus.

Extract named objects, organizations, facilities, addresses, identifiers, dates, and other entities relevant to the user's request from DOCX/PPTX narrative text and XLSX worksheet rows. Match records that appear to describe the same real-world object, even if spelling, abbreviations, or formatting differ.

Return one `rows` item per match or unresolved candidate. Put the final table fields in `values`, using concise column names such as:

- object_name
- object_type
- docx_source
- xlsx_source
- docx_quote
- xlsx_quote
- match_status
- confidence
- mismatch_or_note

Use `result` for a short human-readable conclusion. Do not add replacements.
