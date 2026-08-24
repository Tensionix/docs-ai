# Extract Healthcare Objects

Find all healthcare-related organizations, facilities, departments, hospitals, clinics, outpatient units, laboratories, pharmacies, and medical infrastructure objects mentioned in the provided documents.

For each object, add one row with:

- exact source quote
- normalized object name
- object type when it is clear from the text
- any nearby address, locality, owner, department, or contextual detail

Put structured fields into `values` with columns:

- object_name
- object_type
- address_or_locality
- owner_or_department
- source_context
- confidence

Do not add replacements. This is a report-only task.
