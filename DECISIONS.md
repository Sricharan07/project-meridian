# Decisions

A log of the choices that shaped this, in the order they were made, with what
I tried and what the data said. Numbers come from `python -m meridian score`
and the build output at the time of writing.

## 2026-10-01

### Facts are observations, not fields on a part

The unit of knowledge is one source saying one thing in one place: "BOM row 30,
Material: Aluminium", "D-011 title block, MATERIAL: 7075-T6, Plate (SS)". A
part's material is never stored; it is worked out from its observations when
asked, and the answer says whether they agree, conflict or are missing. A
person's correction is one more observation with an author and a date. This
makes citations, BOM-versus-drawing provenance, abstention and an audit trail
fall out of the data model instead of being bolted on.

### No vector search

There are 30 drawings and 192 BOM rows. Chunk retrieval would make citations
fuzzy and mix sources in one context window, which is the thing the brief asks
me not to do. Extraction runs once, offline, and the chat model calls typed
tools over the result.

### Observations live in a JSONL file, not a database

At 2,843 observations an in-memory index over `kb/observations.jsonl` is
simpler than SQLite, loads in well under a second and diffs cleanly in git, so
a reviewer can see exactly what a rebuild changed. Revisit past roughly 100k
rows or with more than one writer.

### Title blocks are read by cell, not by layout guessing

All 22 clean sheets use one SolidWorks A3 format and the title block sits at
identical coordinates on every one. Each field is read from a fixed cell
(`meridian/sheets/template.py`). Empty fields are recorded as empty: "MATERIAL
is blank on D-002" is evidence, and the note on that sheet names the material
instead.

### Ø, ↧, ⌴ and ± are drawn, not typed

The text layer has "5,0 THRU ALL" where the sheet shows "Ø5,0 THRU ALL". The
diameter symbol is a 56-segment polyline; the depth arrow, counterbore and some
± signs are short polylines too. They are recognised by shape and put back, or
Ø262 would read as a length of 262. Rotated leaders (D-026's Ø250,0) are read in
the text's own frame so the symbol lands in front of the number.

### Two stacked numbers are a limit only if they are laid out as one

D-026 prints the build plate thickness as 25,0 over 15,0. Read naively that is
two thicknesses. SolidWorks limit dimensions share a left edge exactly, carry no
padding spaces and overlap their rows; separate dimensions that happen to stack
(D-024's 7,0 and 3,0) sit a full line apart and are padded. The rule uses that
layout, not the values. The sheet's own weight backs it up: a Ø250 disc of 316
stainless at 20 mm, less three counterbored holes, is 7822.5 g, exactly the
title-block figure. 15 or 25 mm would be 5862 g or 9783 g.

### "(SS)" is not stainless

"7075-T6, Plate (SS)" on D-011 and D-016 to D-018 is a SolidWorks material
library name. The same suffix appears on D-026's "AISI 316 Stainless Steel Sheet
(SS)", so within this corpus it cannot mean stainless. It is dropped before
material matching and the reason is kept on the observation.

### Scans are read twice, independently

The eight scans have no text layer. Tesseract at 2x is one reader, the vision
model the other; neither sees the other's answer. OCR alone gets 36 of 70 scan
title-block fields right. It reads notes well and small print badly: "6061
Alloy" came back as "606! Allay", the weight 415.3 as "4153", 3195.5 as "31985",
and most dates as noise. A field is only called confirmed when both readers
agree.

### Numbers must match exactly; text may not

String similarity said "4153" and "415.3" were 0.89 alike, which would have
confirmed a weight off by a factor of ten. A unit test caught it. Agreement now
requires the numbers in two readings to be identical, and only the surrounding
text is compared loosely.

### A reader that does not trust itself abstains

Tesseract reports per-word confidence. Below 0.4 its output is treated as no
reading at all: D-023's weight came back as "31985" at 0.35, and showing that
as a dissenting opinion would be noise, not caution.

### Scans are lined up with the template before fields are read

D-003 and D-022 are shifted and cropped by a few points and rotated by under a
degree. The printed labels ("MATERIAL:", "DRAWN", "DATE") are found by OCR and
the median offset moves the template cells: D-003 needed 7.3 pt, found from five
labels. Over a title block, a translation fitted on local labels absorbs the
small rotation.

### Links between sheets and BOM rows are curated, the linker is scored

The automatic linker (datasheet filename, shared words after translating the
Danish titles, material, quantity) agrees with the curated decision on 18 of 26
drawings. Its misses are instructive: it sends D-013 to row 31 because that row's
datasheet field names RecoaterPlate.pdf, which is D-013's file and not row 31's
sheet; and it sends D-017 to "Collimator" because the sheet's note says "Galvo
Collimator Plade". Four drawings stay ambiguous on purpose: D-006 and D-008 both
fit "Powder handling mount bracket", and D-029 and D-030 both fit "Motor plate".

### Degraded sheets are not swapped for their upstream originals

The manifest links every degraded sheet's clean original, and upstream also
publishes the STEP assembly. Neither is fetched. The point of the eight scans is
to see what the system does when it cannot read, and the 3D views are to be
built from the 2D evidence.

### Personal details are not extracted

Title blocks carry the designer's name, email and phone. They are public
upstream, but they are not engineering knowledge, so the template has no cell
for them.

### Model

`gpt-6-luna`: the cheapest current OpenAI model that reads images and calls
tools ($0.10 / $0.50 per million input / output tokens). `gpt-5-nano` is cheaper
on input but a generation older; `gpt-4.1-nano` shuts down on 2026-10-23. The
model is one setting in `.env`.

### The vision pass

`gpt-6-luna` reads 69 of the 70 scan title-block fields correctly against OCR's
36. After settling the two readings, 58 are right, 16 of them confirmed by both
readers, and none is shown as exact or confirmed while wrong. Its one miss is a
single-reader value (D-003 sheet 2 scale "1:15" for "1:5"), so it is shown with
that caveat. The whole pass over ten sheets used 30,800 input and 7,382 output
tokens: under a cent. The model sometimes copies a printed label into the value
("SHEET 3 OF 3"); that is stripped the same way as for OCR.

### Fit readings are checked against ISO 286

On D-023 the vision model read "Ø262,0 j7 +0,026/-0,026" as "H7". Under ISO 286
an H bore always has a lower deviation of zero, so "H7 ... -0,026" cannot be
right, and the parser says so on the observation. No fit relation is inferred
from a reading that fails the check, which is why the cylinder currently has no
inferred mate: the drawing does show j7, and a person can correct the reading
through review.

### ISO 286 band widths check every fit

Every fit tolerance on the clean sheets has a band (upper minus lower deviation)
exactly equal to the IT grade for its size: Ø262 H8 is +0,081/0 and IT8 for
250 to 315 mm is 81 µm; Ø8 g8 is -0,005/-0,027, a 22 µm band, IT8 for 6 to 10 mm.
So a misread digit shows up as a wrong band. `meridian/iso286.py` carries the IT
table to 500 mm and the two fixed-deviation rules. It caught three different
things: the vision model's H7 for j7 on D-023 (H rule), my own grouping error on
D-024, where "H9 +0,052" landed on the Ø3,3 holes (52 µm is IT9 for Ø22, not
Ø3,3), and the ambiguity in counterbore callouts, where it moves the fit to the
counterbore whose size it actually matches (D-027, D-030).

### Corrections are events, not edits

A correction is proposed in chat, checked automatically, and decided on the
Review page by a named person. `var/corrections.jsonl` only grows. Accepting
adds a `review` observation that supersedes the original for display; the
original keeps its id, its value and its place on the sheet, and points to its
replacement. Inferred fits are recomputed from whatever the sheets currently
say each time the knowledge base loads, so an accepted correction can create or
remove a relation, and the review page shows that impact before anyone decides,
by building the knowledge base with the candidate in place.

Run end to end on D-023: before, the cylinder had no inferred mate because its
fit readings failed the ISO check. The chat filed C-001 (j7, ISO 286: 52 µm
band is IT7 at Ø262, straddles zero as j classes do); accepting it added the
H8/j7 transition fit with the main platform, and asking the same question again
produced that answer, naming C-001 and the original "H7" reading.

### Caveats are computed, not left for the model to notice

The first chat answers were correct and incomplete. Asked which drawing documents
the recoater stage plate, the model named D-014 and never mentioned that the BOM
row's datasheet field names D-013's file, though the conflict was in the tool
result. Prompting harder did not fix it. `KnowledgeBase.attention()` now writes
those caveats as plain sentences with citations (conflicting sources, links that
are probable or ambiguous, disputed readings, failed fit checks) and puts them
first in every part result. The model relays them; it no longer has to find
them.

### Every answer is checked mechanically

`meridian/chat/verify.py` rejects an answer that cites an id that does not exist
or states a number found in no tool result. A failing answer gets one rewrite;
if it still fails it is shown with the problems listed. Writing the tests found
two holes in my own check: "Ø" counts as a letter to Python's regex, so every
diameter would have skipped it, and "DKK5,627.00" read as an identifier. Both are
pinned by tests.

### Reasoning effort

At "low", one answer in about ten refused to cite or skipped a caveat. "medium"
took the same 3 to 6 seconds and costs under a tenth of a cent per answer, so it
is the setting. Conversations are not stored at OpenAI: requests use
`store=false` and pass the encrypted reasoning back between tool rounds.

### The UI has no build step

Plain ES modules, one stylesheet, IBM Plex vendored with its licence, three.js
vendored for the 3D view. Running the app needs Python and nothing else; Node is
not involved at any point. The theme is light because the sheets are white, and
the page should not fight them.

### Known extraction errors

D-024's hole table is dense enough that its "H9 +0,052" tolerance groups with the
M4 tapped holes instead of the Ø22 bores beside them. Callout grouping is by
proximity, and here proximity is wrong.

### Measured against pasting everything into the prompt

28 questions in `eval/questions.json`, each with what a right answer must say,
what it must not claim, which sheet it must open and which evidence it should
cite. The grader is string matching on purpose: an LLM judge would need its own
evaluation. Each question is asked twice, and the same questions go to a
baseline that gets the whole BOM and every sheet's text in its prompt, 27k
tokens, with no tools. The baseline passes 12 of 28 on content; this passes 26.
Its failures are the interesting part: it told a user to change the BOM to
aluminium on their say-so, and turned OCR's "4153" into "approximately 415.3 g".
Details in `EVALUATION.md`.

### A grader fix is applied to both sides

The first run marked correct answers wrong: "back-door" for "back door",
"45,000" for "45000", "does not state" for "not recorded". Each fix to the
grader was made once and scored against the system and the baseline alike, and
every run is kept in `eval/runs/` so the history shows which gains were the
grader's and which were the system's.

### Counts come from a tool, not from the model counting

Asked how many drawings each subsystem has, one answer said "27 drawings total
... Z-axis 5". It is 30 and 8. Another refused, because nothing citable said
which subsystem a drawing belongs to. The manifest's assignment is now an
observation like any other, and `machine_overview` returns the counts. The
verifier lets small whole numbers through uncited, which is where the wrong
count slipped past; putting the number in a tool result closed it.

### The verifier's message is an instruction, not a remark

A screenshot showed an answer that began "You're right: C-001 is the correction
record ID ...". The model had cited `[C-001]`, the check rejected it, and the
rewrite replied to the check instead of the user. The feedback now asks for the
answer to be written again from the start without mentioning the check, and the
instructions reserve square brackets for cite ids.

### Every tool that names a part opens its sheet

One question was answered entirely from `get_interfaces`, and the turn opened
no drawing, because attachments were only taken from `get_part`. They are now
taken from every tool result that names a part, plus the drawings the answer
cites, and computed on the server so the model cannot forget them.

### Without a key the app still shows its work

The brief asks that the result can be reviewed when the paid service is not
available. With no `OPENAI_API_KEY`, chat replays the recorded answers from the
last evaluation run for the example questions, labelled as recordings with
their date, and for anything else shows the part's evidence without prose.
Sheets, 3D views, parts and review all work without a key. The evaluation
runs against an empty review log of its own, and `MERIDIAN_VAR` does the same
for a throwaway demo, so neither touches the real history.

### The model and the sheet point at each other

A 3D view next to a list of the dimensions it was built from says
"reconstruction from 2D evidence"; it does not show it. Each dimension now
carries where a drafter would draw it on the model and the box it was read
from on the sheet, written in the same function as the solid. The panel puts
the two side by side, and pointing at a callout, a drawn dimension or a table
row lights up the other two. The placements are checked: every drawn
dimension must be as long as its label. It has not failed yet; it would catch
a placement that drifts from the number it labels.

The section view is there because the interesting features are inside:
D-026's counterbores and D-025's countersinks only show their depth when cut,
which is why the sheets draw section views too. The cut face is found with the
stencil buffer and hatched the way a section is.


### The interface is built around one moment

The first interface was correct and looked like a template: Tailwind's stone
and teal, tinted boxes with a coloured left border, a row of monospace pills
in every sentence. The redesign starts from the one thing this app does that
a search box does not: every claim shows its source. Point at a number in an
answer and the sheet travels to where it is printed, already marked.

So the drawing is the stage, with the conversation on one side and an
inspector on the other. References are numbered the way a drawing numbers its
balloons, and the same number is pinned on the sheet. Colour carries meaning
and nothing else: one safety yellow for evidence and the main action, red only
for a disputed reading or a failed check, graphite for everything else.
Agreement is a quiet tick; a value read off the text layer needs no mark at
all. Motion is used where it explains a change of place (the sheet gliding to
a reference, an indicator sliding to the current tab) and is off for readers
who ask for reduced motion. Dark is the default because the white sheets read
best on it; light is one click away and remembered.
