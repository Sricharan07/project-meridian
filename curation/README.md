# Curation

Decisions a person made while building the knowledge base. Each one becomes an
observation with method `curated` and cites the row it came from, so an answer
that depends on a link or a diagram reading says so.

| File | What it decides |
|---|---|
| `links.csv` | Which BOM row(s) each drawing documents. `linked` when the evidence is direct (datasheet filename, same name), `probable` when it is the best candidate but some evidence disagrees, `ambiguous` when the evidence cannot separate two candidates. |
| `diagram_relations.csv` | Relationships read off the system diagrams, with the pixel box of each label so the reading can be checked against the image. |

The automatic linker in `meridian/linking.py` proposes candidates; these files
are the reviewed answer. `python -m meridian score` reports how often the
linker's first choice agreed with them.

Review status: drafted from the drawings, BOM and diagrams; pending a second
read-through.
