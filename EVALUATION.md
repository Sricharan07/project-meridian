# Evaluation

What I measured, how, and where it fails. Every number here can be reproduced:

```bash
.venv/bin/python -m meridian score   # extraction and linking, no API calls
.venv/bin/python -m meridian eval    # chat questions twice, baseline, correction scenario (~2 min, ~$0.13)
.venv/bin/python -m pytest           # 84 tests: parsing, settling, checks, corrections, drawn dimensions
```

Chat results are from `eval/runs/2026-10-02T063422Z/` unless a section says otherwise. Every answer,
citation, tool call, timing and cost from every run is in those folders.

## 1. Reading the sheets

Ground truth is `eval/truth/title_blocks.csv`: every title block on all 33 sheets, typed from the rendered
sheets. Clean sheets were checked against their text layer; the eight scans were read by eye at 200 dpi.

| Sheets | Reader | Fields right |
|---|---|---|
| clean (22 drawings, 23 sheets) | PDF text layer | 161 / 161 |
| scans (8 drawings, 10 sheets) | OCR (tesseract, 2x) | 36 / 70 |
| scans | vision model (gpt-6-luna) | 69 / 70 |
| scans | both, settled | 58 / 70 |

How the 70 scan fields were settled: 16 confirmed by both readers, 22 read by one reader only (OCR gave up
or abstained below 0.4 confidence), 11 disputed, 21 blank. **No field is shown as exact or confirmed while
being wrong.** The 12 settled fields that do not match the truth are all shown as disputed or single-reader.

What the readers got wrong, in their own words:

- OCR: "6061 Alloy" → "606! Allay", weight 415.3 → "4153", 3195.5 → "31985", 7075-T6 → "7075-16", and most
  dates and scales as noise ("SCALEN:IO", "2ernoraoas").
- Vision model: D-003 sheet 2 scale "1:15" for 1:5. OCR abstained there, so the app shows it as read by the
  vision model only, which is the caveat it needs.
- Vision model, in the drawing area: D-023's "Ø262,0 j7" and "Ø264,0 j7" read as "H7". Not in the title-block
  truth set, but caught by the ISO 286 check (section 4) and correctable through review (section 6).

## 2. Linking sheets to BOM rows

`curation/links.csv` records which BOM row(s) each drawing documents, with the reason. The automatic linker
(datasheet filename, shared words after translating the Danish titles, material, quantity) is scored against it.

The linker's first choice matches the curated decision on **18 of 26** drawings; four more are left ambiguous by
the curator. The misses show what the linker cannot know:

- D-013 → row 31. Rows 28 and 31 both list RecoaterPlate.pdf, D-013's file name, and the linker took the wrong
  one. The sheet's note ("Justeringsplade til recoater", adjustment plate) settles it as row 28; row 31 belongs to
  D-014, and the app raises the datasheet conflict there.
- D-017 → row 85, "Collimator". The sheet's note says "Galvo Collimator Plade"; it is the adapter plate the galvo
  and collimator mount to, row 79.
- D-007, D-010, D-016, D-018, D-021, D-025: the right row shares few or no words with the sheet. D-010 is titled
  "Motor Plate" and is the powder stepper bracket; D-007's dispenser shaft is the BOM's "Powder roller"; D-025's
  base ring is the "Seal clamp plate". Four of the six are only "probable" to the curator as well. That judgement
  belongs in curation, with its reasons written down, not in a synonym list.

## 3. 3D reconstructions

Five clean sheets, each rebuilt only from its dimensions (`meridian/geometry.py`) and checked against the weight
SolidWorks printed in its title block. Mass depends on sizes, not positions, so this checks the dimensions most
easily misread: thicknesses and diameters.

| Drawing | Part | Computed | Title block | Difference | What the check settled |
|---|---|---|---|---|---|
| D-012 | Recoater mount block | 117,3 g | 117,3 g | -0,03 % | |
| D-015 | Silicone wiper | 4,6 g | 4,6 g | +0,74 % | density of the rubber is assumed (1,25) |
| D-025 | Bygge base ring | 77,3 g | 77,3 g | +0,04 % | thickness range 2 to 3 resolves to 3,0 |
| D-026 | Build plate | 7821,7 g | 7822,5 g | -0,01 % | thickness range 15 to 25 resolves to 20 |
| D-028 | Heating element plate | 1,2 g | 1,2 g | -0,12 % | thickness range 2 to 3 resolves to 2,0 |

The wiper's hole positions are not dimensioned. They were measured off the vector geometry at the sheet's 1:1
scale: 9,98 mm from the end, 35,71 mm pitch, the same 35,7 pitch as the M3 holes in D-013 that clamp it.

## 4. Fit readings against ISO 286

On the clean sheets, every fit tolerance that is grouped with the right feature has a band exactly equal to its IT
grade, so the check is applied to every fit reading. It found three things, none of which I was looking for when I wrote it:

| Reading | Finding |
|---|---|
| D-023 "Ø262,0 H7 +0,026 / -0,026" (vision) | An H bore has a lower deviation of 0. The sheet says j7. |
| D-024 "10 x Ø3,3 ... H9 +0,052" | 52 µm is IT9 for Ø22, not Ø3,3. The H9 belongs to the "3x Ø22,0" bores next to it; my grouping attached it to the wrong callout. |
| D-030 "Ø13,50 THRU / H6 +0,013 / 0,000 / ⌴ Ø20,00" (vision) | 13 µm is IT6 for Ø20: the fit belongs to the counterbore, and is moved there. |

## 5. Chat

28 questions in `eval/questions.json`, covering every kind the brief lists. Each says what a correct answer must
contain, must not claim, which sheet it must open, whether the 3D view must be offered, and which evidence it
should cite. Every answer must also pass the mechanical citation check. Each question was asked twice with no
shared state.

| | Run 1 | Run 2 |
|---|---|---|
| Passed every check | 26 / 28 | 27 / 28 |
| Same verdict both runs | 27 / 28 | |
| Median citation overlap between runs | 1,0 | |
| Latency, median / 90th percentile | 4,3 s / 7,1 s | |
| Cost per answer, median | $0.0009 | |
| Answers rewritten after failing the check | 1 of 56 | |
| Answers shown with a failed check | 0 of 56 | |

By category in run 1: organisation 2/3, drawing to BOM 4/4, interfaces 4/4, materials 3/3, procurement 4/5,
noisy sheets 5/5, 3D 3/3, corrections 1/1.

The two failures in run 1:

- **org-2, a real miss, in both runs.** "Which BOM rows belong to the Z-axis?" is answered correctly, but never says
  that the BOM files these rows under "Build-plate", which is the thing a reader would need to find them. The tool
  result carries that note; the model does not relay it.
- **buy-2, my grader.** The answer says DKK0.00 means the costs "weren't recorded"; the check looked for "not
  recorded". The answer is right.

### Against pasting the documents into the prompt

The baseline gets the same questions with the whole BOM and every sheet's text (OCR for the scans) in its prompt,
about 27k tokens, and no tools. It is held only to the content checks, since it cannot cite or open anything.

| | Content checks passed |
|---|---|
| This system | 26 / 28 |
| Baseline | 12 / 28 |

The difference is mostly in what the baseline does when the evidence is weak. From the same run:

- "The build plate is aluminium, not stainless steel. Please fix it." → *"Update the BOM's Build Plate material from
  Stainless steel,Steel to Aluminium ... The drawing should also be revised to specify aluminium."* It edits the
  sources on a user's say-so. This system files a correction whose material check fails against the sheet and BOM.
- "What scale is sheet 2 of the main platform drawing?" → *"1:2"*. In an earlier run, *"1:1"*. The sheet says 1:5.
- "What does the recoater arm weigh?" → *"approximately 415.3 g"*. Its OCR text says "4153"; it guessed the decimal
  point and presented the guess as the reading.
- "Is the BOM's motor plate D-029 or D-030?" → *"D-030"*, with no sign that the evidence cannot tell.
- "Who supplied the laser source and what did it cost?" → *"Max Photonics ... DKK 45,000"*, with no word that this is
  a snapshot from the BOM, not a price today.

It also costs more: $0.08 for one pass of the 28 questions, against $0.026 per pass for this system.

### How the score got here

The chat was run four times while I worked on it. I kept every run, including the ones where the grader was
wrong, because the fixes are part of the result.

| Run | Pass rate (run 1 / 2) | What changed before it |
|---|---|---|
| `061159Z` | 82 % / 89 % | first run |
| `061753Z` | 93 % / 93 % | Bug fix: a part looked up only through `get_interfaces` opened no sheet. Grader fixes: "back-door", "45,000", "does not state", "excludes" were correct answers marked wrong. |
| `062116Z` | 100 % / 93 % | Bug fix: asked how many drawings each subsystem has, one answer said "27 drawings total ... Z-axis 5" (it is 30 and 8) and another refused because subsystem membership had no citable source. The manifest's subsystem assignment is now evidence, and a `machine_overview` tool returns counts instead of leaving them to be counted. |
| `063422Z` | 93 % / 96 % | Bug fix found in a screenshot: after the verifier rejected `[C-001]` as a citation, the rewrite began *"You're right: C-001 is the correction record ID..."*, replying to the check instead of the user. |

Run 3's 100 % and run 4's 93 % are the same system within the variation the repeat runs measure; run 4 is the
code as submitted.

## 6. A correction, before and after

Scripted in `meridian/evaluation.py` with a throwaway log, so it can be rerun without touching the review history.

Before, asked "What does the build cylinder fit into?":

> The cylinder's Ø262,0 and Ø264,0 H7 callouts failed the ISO 286 check, so they can't reliably establish a fit
> into another part.

The correction proposes "Ø262,0 j7 +0,026 / -0,026". Its ISO 286 check passes (band 52 µm, IT7 at Ø262, straddles
zero as j classes do), and the review page shows that accepting it adds an inferred H8/j7 transition fit with D-003.
After it is accepted, the same question:

> The build cylinder appears to fit into the Main Platform (called "Print Platform" in the BOM): the platform
> drawing shows a Ø262,0 H8 bore and the cylinder drawing's Ø262,0 j7 diameter suggests an inferred transition
> fit. No source explicitly states that fit ... The cylinder's j7 reading was corrected by C-001 from H7.

The original "H7" observation is still there, citable, pointing at the correction that replaced it.

## 7. Failure modes worth knowing

- **Callouts read only by the vision model have no position.** On scans, a callout gets a box only if OCR also
  found it. The corrected D-023 callout opens the sheet but highlights nothing.
- **Single-reader values are shown with a caveat, not hidden.** D-003 sheet 2's scale is one of them, and it is wrong.
- **Callout grouping is by proximity.** D-024's hole table is dense enough to mis-group; ISO 286 flags the case it
  can see, and there may be others it cannot.
- **Four links are ambiguous on purpose**, and five are "probable". Answers that depend on them say so.
- **Diagram relations are my transcription.** Each cites the label boxes on the diagram so it can be checked, but
  a person decided what the arrows meant.
- **The BOM's Interface with column is sparse:** filled on 9 rows, 8 of them in the Box. Outside the Box, relations
  come from the diagrams or from matching fits.
- **The verifier allows small whole numbers** ("three drawings") without a source, because they come from counting
  a list. That is exactly where the "Z-axis 5" miscount slipped through; the fix was to put the counts in the tool
  result, not to trust the exemption.
- **Answers vary between runs.** 27 of 28 kept their verdict and citations overlapped fully at the median, but the
  wording, and occasionally what an answer chooses to mention, changes.

## 8. Cost and time

| Step | Time | Cost |
|---|---|---|
| Build, vision responses cached | 7 s | none |
| Build, first vision pass over the 10 scanned sheets | about 90 s | $0.0068 (30,800 tokens in, 7,382 out) |
| One chat answer, median | 4,3 s | $0.0009 |
| `meridian eval`: 56 answers, the baseline, the correction scenario | 2 min | about $0.13 |
