# Meridian

Chat over the drawings and bill of materials of the [OpenLPBF v2](https://github.com/DTUOpenAM/OpenLPBF_v2), a
metal laser powder-bed-fusion machine. Every fact in an answer links to where it came from: a region of a sheet, a
BOM cell, a diagram label, or a correction someone accepted. Asking about a part opens its drawing, and the 3D view
when the part has one. When the sources disagree, or a scan cannot be read, the answer says so.

Beyond the brief's required bar it also does the three bonus items: a graph of how parts, drawings, subsystems,
materials and suppliers connect, with cited paths between any two; a review loop that takes link, connection,
dispute and new-drawing corrections and measures what each one changed; and dated supplier suggestions, other sellers
for bought parts and Danish makers for custom ones, each with the basis for the match.

The assignment brief is in [docs/brief.md](docs/brief.md).

![An answer with numbered references beside the scanned sheet it cites. Pointing at reference 1 has brought the disputed material field into view, boxed in red, with the same numbers pinned on the drawing and the inspector listing what each reader saw](docs/screenshots/scan-disputed.png)

## Getting started

### What you need

- macOS or Linux. On Windows, use WSL, or follow [Without the script](#without-the-script) below.
- Python 3.11 or newer. Check with `python3 --version`. To install it: `brew install python@3.12` on macOS, or
  `sudo apt install python3.12 python3.12-venv` on Ubuntu.
- An internet connection the first time, to install three Python packages.
- Optional: an OpenAI API key, for live answers. Everything else works without one.

### 1. Start it

From the project folder:

```bash
./start.sh
```

The first run creates a virtual environment in `.venv`, installs FastAPI, uvicorn and the OpenAI client into it, and
prints `Meridian on http://localhost:8000`. Later runs start in about a second. The knowledge base in `kb/` is
already built and committed, so nothing is extracted at startup and no system packages are needed.

### 2. Open it

Go to **http://localhost:8000**. A laptop-sized window or larger shows the full layout; narrower windows stack the
panels.

### 3. Add an API key (optional)

The first run creates `.env` from `.env.example`. Open it, set the key, then stop the server with Ctrl+C and run
`./start.sh` again:

```
OPENAI_API_KEY=sk-...
```

With a key, each answer is written live and shows its time and cost underneath. Without one, the example questions
replay their recorded answers from the last evaluation run, labelled as recordings, and any other question shows
the evidence for the part it names. Drawings, 3D views and the review page work the same either way.

### Stopping, ports and starting over

- Stop the server with Ctrl+C in its terminal.
- Use another port with `PORT=8001 ./start.sh`.
- Clear the review history by deleting `var/corrections.jsonl`. It is append-only and never committed.

### Without the script

The same steps by hand, for Windows or anywhere `start.sh` cannot run. If `python3 --version` is older than 3.11,
use the newer one by name in the first command, for example `python3.12`.

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
cp .env.example .env
```

```bash
.venv/bin/python -m meridian serve --port 8000
```

On Windows, use `py -3.12 -m venv .venv`, then `.venv\Scripts\pip` and `.venv\Scripts\python` in place of the
`.venv/bin` paths, and `copy` in place of `cp`.

### If something goes wrong

| What you see | What to do |
|---|---|
| `Meridian needs Python 3.11 or newer` | Install a newer Python (above), then run `./start.sh` again |
| `permission denied: ./start.sh` | Run `bash start.sh`, or make it executable once with `chmod +x start.sh` |
| `address already in use` | Something else has port 8000: `PORT=8001 ./start.sh` |
| Chat says no API key is configured | Put the key in `.env` and restart the server |
| The page looks out of date after an update | Reload it |

## How to use it

### Ask, and see where the answer comes from

![The chat, a cited sheet and the inspector, with seven numbered callouts](docs/guide/1-ask.png)

1. **Ask a question** about any part, material, cost or interface, and press Enter. An empty chat suggests
   questions to start with.
2. **Read the answer.** Every fact carries a numbered reference. Point at a number and the drawing travels to it.
   Red numbers are readings the evidence disputes.
3. **Check the sources.** Under each answer, each number says what it is, which reader read it and what it says.
   Click one to open it on the sheet.
4. **See it on the drawing.** The same numbers are pinned where each value is printed: yellow where the readers
   agree, red where they don't. Scroll to zoom, drag to pan, double-click to fit.
5. **The inspector** lists what needs a second look first, then every title-block field and how sure its reading is.
6. **Switch views** between the sheet, the 3D reconstruction where there is one, the BOM row, suppliers and the
   part's relations.
7. **Find any part** with ⌘K (Ctrl K on Windows and Linux). The sun in the corner switches to the light theme.

### Explore a part in 3D

![The 3D tab: the sheet beside the reconstruction, with linked dimensions](docs/guide/2-model.png)

1. **Open the 3D view** from the 3D button under an answer, or the 3D tab above the sheet. Five parts have one.
2. **It is a reconstruction, not CAD:** built only from the numbers on the drawing. Drag to orbit, scroll to zoom;
   the corner button refits.
3. **Sheet, model and list are linked.** Each dimension is boxed on the sheet where it was read and drawn on the
   model. Point at any one and the other two light up; click to zoom both to it, and press Esc to let go.
4. **Section** cuts the part like the sheet's section views, hatched, and a slider moves the cut. **Dimensions**
   shows or hides the labels.
5. **The mass check** compares volume times density with the weight printed on the sheet. All five agree within
   0.75 %.

### Correct a value

![Telling the chat a value is wrong, and the correction it files](docs/guide/3-correct.png)

1. **Say what's wrong.** Tell the chat which value is wrong and what it should be. For example, ask "What does the
   build cylinder fit into?", then: "That Ø262 callout on the build cylinder drawing is wrong. The sheet prints a
   lowercase j7, not H7. It should read Ø262,0 j7 +0,026 / -0,026."
2. **A correction is filed** instead of the chat simply agreeing, with what the automatic checks found and what
   accepting it would change.
3. **It waits for review.** Pending corrections are counted on the Review tab.

![The Review page with the change, its checks and the decision](docs/guide/4-review.png)

1. **The change:** the current reading struck through and the proposed one, with only what differs marked.
2. **Automatic checks:** ISO 286, the other reader and the other sources.
3. **If accepted:** what accepting adds or clears, worked out before anyone decides.
4. **Decide.** Enter your name and a note, then accept or reject. Ask the first question again: the answer now
   gives the H8/j7 fit with the main platform, names the correction, and still cites the original "H7" reading.

### Browse every drawing

![The Drawings page, every sheet grouped by subsystem](docs/guide/5-drawings.png)

1. **Filter** to every sheet, only the degraded scans, or only the parts with a 3D reconstruction.
2. **Open a sheet** by clicking it. Its tags say whether it is a scan, whether it has a 3D model, and when its link
   to a BOM row is uncertain.

### Follow how parts connect

![The Graph page showing the path from the cylinder clamp ring to the build cylinder](docs/guide/7-graph.png)

1. **Focus on anything** from the Graph tab: a part, drawing, subsystem, material or supplier. The graph shows what
   it connects to, grouped by how. With nothing focused it shows the subsystems and the interfaces between them.
2. **Connect to** a second one to see the shortest chain of evidence between them. The chat does the same when asked
   how two parts relate, with a Graph button under the answer.
3. **Every step is cited.** A step through a shared subsystem is flagged: the parts belong together, which is not the
   same as touching.
4. **Line styles** say where each connection comes from: the BOM, a diagram, matching fits, or a drawing of a BOM row.

### Find another supplier, or someone to make it

![Asking who could make the recoater mount block, with the Suppliers tab](docs/guide/8-make.png)

1. **Ask who could make a custom part.** The answer and the Suppliers tab keep the supplier the BOM records apart
   from suggestions.
2. **What making it takes** is worked out from cited evidence: material, process and the rule that chose it, size
   from the 3D reconstruction or the sheet, the tightest tolerance, the quantity.
3. **Makers** come from a dated web search for Danish shops, checked against what their own sites state. A tick is
   a requirement their site confirms, a dashed circle one it does not mention.

![Asking where else to buy the 24 V power supply](docs/guide/9-buy.png)

1. **Ask where else to buy a bought part.** Parts over DKK 200 with something to search for were looked up once;
   for the rest, the answer says why they were not.
2. **What the BOM recorded**, unchanged.
3. **How strong each match is:** the same manufacturer part number in the seller's page address, found by the
   search but not checked further, or an equivalent part to compare against the datasheet.

### Review does more than fix values

![The Review page with the measures review has changed and a link change waiting](docs/guide/10-review-loop.png)

1. **What review has changed:** each measure before any correction and now, replayed in the order corrections were
   decided.
2. **More kinds of correction:** a value, which of two disputed scan readings is right, a drawing's BOM link, a
   connection between parts, a new drawing. Ask in chat ("D-016 documents row 81"), or use Change link on the BOM
   tab and Add a connection on the Relations tab.
3. **Checks for each kind**, such as where the automatic linker ranks a proposed row.

### Add a drawing

![The Add a drawing dialog](docs/guide/11-add-drawing.png)

**Add drawing** on the Drawings page takes a PDF, its subsystem and where it comes from. It is read the way the
supplied sheets were and filed for review:

![The new drawing waiting for review](docs/guide/12-new-drawing.png)

1. **The sheet as read**, from its text layer here; a scan goes through OCR and the vision model.
2. **What was read:** the title block, whether it repeats a known sheet, ISO 286, and the linker's best rows.
3. **Say what it documents:** the BOM rows and how sure the link is, with the linker's picks one click away.
4. **Accept** to add it to answers, search and the graph. Until then nothing else sees it.

### Keyboard

| Key | What it does |
|---|---|
| ⌘K, or Ctrl K | Find a drawing or BOM row by name |
| `/` | Jump to the question box |
| Enter, Shift+Enter | Send the question, or start a new line |
| Esc | Close the finder, or let go of a pinned dimension in the 3D view |
| Double-click a sheet | Fit it to the view |

### Things to try

| Ask | What to look for |
|---|---|
| Show me the recoater mount block. | Opens the drawing, with a 3D button for the sheet and the model side by side |
| How thick is the heating element plate? | The sheet prints a limit, 3,0 over 2,0; the model was built at 2,0, the value the title-block weight matches |
| Which drawing documents the recoater stage plate? | Names D-014 and raises that its BOM row lists D-013's file |
| Is the recoater arm made of stainless steel? | Aluminium by the BOM and the sheet's note; the scanned material field is disputed, and both readings are quoted |
| What does the recoater arm weigh? | A scanned sheet: shows what each reader saw and which ones agree |
| Is the BOM's motor plate drawing D-029 or D-030? | Says the evidence cannot tell, and why |
| What did the Box subsystem cost, and what is missing from that figure? | A total from a dated snapshot, with the rows that have no cost |
| How does the cylinder clamp ring relate to the build cylinder? | A two-step path through the print platform, both steps from the Z-axis diagram |
| Who could make the recoater mount block for us? | Requirements from the drawing, and two Danish shops checked against them |
| Is there a second source for the laser source? | Raycus and Everfoton, named as equivalents to compare against the datasheet, not the same part |
| whats the weigth of the recoter arm | Typos are fine: it still opens D-011 and gives both readings |

### All five reconstructions

Each sheet with the dimensions its model was built from boxed in yellow, beside the model:

![The five reconstructed parts, each sheet beside its model](docs/guide/6-all-models.png)

## How it works

```mermaid
flowchart LR
  subgraph build["python -m meridian build (offline, once)"]
    D[30 drawings] --> R1[PDF text layer]
    D --> R2[OCR + vision model]
    B[BOM CSV] --> R3[one row per cell]
    C[curation/] --> R4[links, diagram relations]
  end
  R1 & R2 & R3 & R4 --> O[(kb/observations.jsonl)]
  O --> K[KnowledgeBase]
  V[(var/corrections.jsonl)] --> K
  W[(kb/suppliers.jsonl)] --> K
  K --> G[graph, derived on load]
  K --> T[typed tools] --> M[gpt-6-luna] --> X[verifier] --> U[chat + evidence panel]
  G --> T
  K --> RV[review page] --> V
  S["python -m meridian suppliers (once)"] --> W
```

**Observations, not fields.** The unit of knowledge is one source saying one thing in one place: "BOM row 30,
Material: Aluminium", "D-011 title block, MATERIAL: 7075-T6, Plate (SS)". A part's material is never stored. It is
worked out when asked, along with whether its sources agree, conflict or are missing. Citations, the distinction
between a BOM claim and a drawing claim, abstention and the audit trail all come from that.

**Reading the sheets.** The 22 clean sheets are read from their PDF text layer: the title block by fixed cells, the
callouts by grouping nearby text, with the Ø, depth and counterbore symbols recognised from the drawn polylines that
replace them in the text layer. The eight scans are read twice, by tesseract and by the vision model, independently.
A value is "confirmed" only when both agree, and numbers have to agree exactly. Every fit tolerance is checked
against ISO 286.

**Links and relations.** Which BOM row a drawing documents is a curated decision with its reason
(`curation/links.csv`), and the automatic linker is scored against it. Relations come from the BOM's Interface with
column, from the system diagrams (transcribed, citing the label regions), and from matching fit sizes across sheets.
Each says which of the three it is.

**Chat.** The model sees fourteen tools over the knowledge base, never the documents. Caveats such as conflicting sources,
uncertain links and failed checks are computed and put first in every tool result, so the model relays them rather
than having to notice them. Before an answer is shown, a check rejects any citation that does not exist and any
number that is in no tool result. Which sheet and 3D view to open is decided on the server from the tools that were
called.

**3D.** Five clean, simple parts are rebuilt from their dimensions with constructive solid geometry
(`meridian/geometry.py`). Each dimension cites its callout, or says how it was measured or why it was assumed, and
says where it is drawn on the model and where it sits on the sheet; a test checks that every drawn dimension is as
long as its label. The computed mass is checked against the weight
SolidWorks printed in the title block. All five are within 0.75 %. The view says it is a reconstruction, not CAD.

**Corrections** are events. Accepting one adds an observation that supersedes the original for display. The original
keeps its id and its place on the sheet. Inferred relations are recomputed on load, so an accepted correction can
create or remove one, and the review page shows that impact before anyone decides.

**Graph.** Parts, drawings, subsystems, materials and recorded suppliers become one graph each time the knowledge
loads (`meridian/graph.py`); it is never stored. Every edge carries the cite ids it rests on. Paths prefer interfaces
from the BOM and diagrams, and only pass through a shared subsystem when nothing better exists, saying so when they do.

**Review loop.** Corrections have kinds: a value, a disputed reading settled, a BOM link, a connection added or
withdrawn, a new drawing (`meridian/corrections.py`, `meridian/ingest.py`). Each runs its own checks before anyone
decides. `meridian/learning.py` replays accepted corrections in decision order and measures the knowledge after each:
scan fields against the truth set, disputes left, wrong corrections, ISO 286 failures, link certainty, connections.

**Suppliers.** `python -m meridian suppliers` searches the web once, through OpenAI's web search, and keeps every
response with the pages it returned (`kb/suppliers/`). A suggestion is kept only if its site is one the search
returned and it is not the recorded supplier again. Custom parts are matched against makers by plain, visible rules
(`meridian/suppliers.py`). The app reads the snapshot and never searches.

The reasoning behind each choice, including the ones that did not work, is in [DECISIONS.md](DECISIONS.md).

## How well it works

Measured with `python -m meridian score` and `python -m meridian eval`. Details, error analysis and every run's raw
output are in [EVALUATION.md](EVALUATION.md).

| | |
|---|---|
| Title-block fields, clean sheets | 161 / 161 |
| Title-block fields, scans: OCR / vision model / settled | 36 / 69 / 58 of 70 |
| Scan fields shown as confirmed while wrong | 0 |
| Automatic linker against curation | 18 / 26 |
| 3D mass check, largest difference | 0.74 % |
| Chat questions passing every check, two runs | 39 / 40 and 40 / 40 |
| The original 28 of them | 27 / 28 and 28 / 28 |
| Same verdict in both runs | 39 / 40 |
| Content checks, this vs. pasting all documents into the prompt | 39 vs. 17 of 40 |
| Latency, median / 90th percentile | 4.9 s / 8.4 s, of which looking things up is about 1 ms |
| Cost per answer, median | $0.0012 |
| Supplier search: parts identified, suggestions kept, invented sites dropped | 34 of 36, 60, 0 |

## Limitations

- Callouts on scans that only the vision model read have no position on the sheet. Citing one opens the sheet but
  outlines nothing.
- Callout grouping is by proximity. On D-024 it attaches a tolerance to the wrong holes; the ISO 286 check flags it,
  but it is not fixed.
- Single-reader scan values are shown with a caveat rather than hidden. One of them, D-003 sheet 2's scale, is wrong.
- The links, diagram relations and title-block truth set were curated by one person, me. Four links are left
  ambiguous and five are marked probable.
- Supplier, price and order number answers come from a BOM snapshot (retrieved 2 September 2026), and say so. Supplier
  suggestions come from one web search on 2 October 2026; prices and stock were not checked, a "found by the search"
  seller's page was not read, and makers are matched only on what their sites state.
- Custom parts get a process from plain rules (thickness, material, wording). They are shown with each part, and can be
  wrong: a box panel with no thickness on record is assumed to be milled.
- Without an API key, recorded answers do not change after a correction is accepted. The drawings and review pages
  do.
- One user, one process: the review log has no locking.

## Models, services and data sent out

- **OpenAI `gpt-6-luna`**, through the Responses API with `store=false`.
  - At build time, each of the ten scanned sheet images and an enlarged crop of its title block are sent once to be
    transcribed. The responses are cached in `kb/vision/`, so running or rebuilding the app does not send them again.
    The title blocks include the designer's name and contact details, which are public upstream and are not extracted.
  - In chat, the question, the last few messages and the tool results are sent: extracted text from the BOM and
    drawings, never the PDFs or images.
  - `meridian eval` also sends the BOM and every sheet's extracted text, for the baseline.
  - `meridian suppliers` sends, for 36 bought parts, the part name, recorded supplier, product name or order number
    and recorded link, and for six manufacturing processes their names, to OpenAI's web search. Never drawings,
    prices or anything else from the sheets. It ran once; the responses are in `kb/suppliers/`.
  - Adding a scanned drawing in the app sends its sheet images to the vision model, as the build does.
- **Tesseract** runs locally, at build time only.
- No other services. Fonts (IBM Plex, OFL) and three.js (MIT) are vendored under `web/vendor/` with their licences.
- The upstream originals of the eight degraded sheets and the upstream CAD files were not used.

## Rebuilding and testing

The committed `kb/` is the output of a build. To rebuild it, install tesseract (`brew install tesseract`) and:

```bash
.venv/bin/pip install -r requirements-build.txt
```

```bash
.venv/bin/python -m meridian build
```

A rebuild with the vision responses cached takes about 7 seconds and makes no API calls. Then:

```bash
.venv/bin/python -m pytest
```

```bash
.venv/bin/python -m meridian score
```

```bash
.venv/bin/python -m meridian eval
```

`eval` needs a key, takes about three minutes and costs about $0.22. It writes a new folder in `eval/runs/` and refreshes
the recorded answers. After a grader fix, `eval --rescore eval/runs/<run>` scores the same answers again without asking.

```bash
.venv/bin/python -m meridian suppliers
```

Rebuilds `kb/suppliers.jsonl` from the cached searches; with `--refresh`, or for parts not searched yet, it needs a key
(the full run took 83 seconds and 650,000 input tokens). To see how lookups scale with a larger corpus:

```bash
.venv/bin/python eval/scale.py
```

## Layout

```
meridian/            the Python package
  evidence.py        Observation, Source: the data model
  sheets/            reading drawings: template, text layer, callouts, OCR, vision model
  bom.py             reading the BOM, one observation per cell
  reading.py         settling two readers into confirmed, disputed, single reader or blank
  iso286.py          tolerance grade checks
  linking.py         sheet-to-row candidates, and the curated decisions
  relations.py       stated, diagram and inferred relations
  knowledge.py       the KnowledgeBase every answer goes through
  graph.py           the graph derived from it, and paths through it
  corrections.py     proposals of every kind, checks, impact and decisions
  learning.py        what each accepted correction changed
  ingest.py          reading a drawing added in the app
  suppliers.py       supplier search, its snapshot, and matching custom parts to makers
  geometry.py        the five 3D reconstructions
  chat/              tools, instructions, the answer check and the agent loop
  server.py          the API and static files
  build.py           dataset -> kb/
  evaluation.py      the chat evaluation
web/                 the UI: plain ES modules, no build step
curation/            human decisions the build reads, with reasons
kb/                  build output: observations, relations, page images, 3D models, supplier searches
eval/                truth set, questions, every run, recorded answers, the scaling benchmark
tests/               parsing, settling, checking and correction rules
dataset/             the supplied drawings, BOM and diagrams, unchanged
docs/                the assignment brief, the annotated guide and screenshots
```

## More screenshots

The build plate in section, after clicking the counterbore depth: the sheet has zoomed to the hole callout and the
model to the counterbore, cut and hatched:

![Build plate reconstruction in section](docs/screenshots/model-3d-build-plate.png)

The correction accepted, and the same question asked again afterwards:

![Correction accepted](docs/screenshots/review-accepted.png)

![The same question after the correction](docs/screenshots/correction-after.png)

An answer that raises a datasheet conflict, with the drawing opened beside it:

![Datasheet conflict](docs/screenshots/chat-conflict.png)

The light theme, on a scanned weight the two readers disagree about:

![Light theme](docs/screenshots/light.png)

## Attribution

The dataset is curated from [DTUOpenAM/OpenLPBF_v2](https://github.com/DTUOpenAM/OpenLPBF_v2) at commit
`98f76dad`, licensed under CERN-OHL-P-2.0. See [ATTRIBUTION.md](ATTRIBUTION.md) and
`dataset/context/OpenLPBF-LICENSE.md`.
