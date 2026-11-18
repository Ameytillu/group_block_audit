# 🏨 Group Block Audit

A Streamlit app that finds **group attendees who booked outside the room block**.

Upload:
1. **Group attendee list**: Excel (.xlsx) or CSV with first/last names (a group code column is optional)
2. **Booked reservations**: the hotel system report as **PDF** (or Excel/CSV)

The app matches every attendee to the reservations and gives each one a status:

| Status | Meaning |
|---|---|
| 🟢 In Block | Exact name match, booking has a valid group code |
| 🔴 Booked Outside Block | Exact name match, booking has **no** valid group code |
| 🟠 Review: Possibly Outside Block | Near match (nickname, typo, swapped names, initial) with no valid group code |
| 🟡 Review: Possibly In Block | Near match with a valid group code |
| ⚪ No Booking Found | Attendee not found in the reservations |

It also lists **in-block reservations whose name is not on the attendee list**, and exports everything to a formatted Excel report.

---

## Folder structure

```
group_block_audit/
├── app.py                  ← Streamlit UI (upload → check → results → download)
├── core/
│   ├── names.py            ← name cleanup ("O'Brien" = "OBRIEN", "SMITH, JOHN" → John Smith)
│   ├── nicknames.py        ← Bob = Robert, Bill = William … (add your own in EXTRA_GROUPS)
│   ├── tables.py           ← reads Excel/CSV, column guessing, standard guest list
│   ├── pdf_reader.py       ← pulls names + group codes out of PDFs
│   ├── matcher.py          ← matching rules and statuses
│   └── report.py           ← Excel report export
├── sample_data/            ← fake test files (no real guests)
├── .streamlit/config.toml  ← theme, 50 MB upload limit
├── requirements.txt
└── README.md
```

## How the PDF is read

In step 3 you can choose how to read each PDF:

- **Reservation report: 'Name:' blocks**. This is chosen automatically for reports where each reservation is a block like:
  ```
  Name:  WATTS, KERRY      Res Stat-G  Adv Code-C  Gst Type-  Group-ACME26  Accommodation-HW
                           Crtd - 11/16/2026- REZTRIPRES ...
  ****************************************************
  ```
  It keeps **only the guest name, the `Group-` value and the `Crtd` (created) date**. Everything else in the block
  (address, rates, bill codes, policies, fees) is ignored. A blank `Group-` means the booking is outside the block.
  Blocks that run across a page break are handled.
- **Text lines**: for reports where each reservation is a line with the name as `LAST, FIRST`
  (Opera, OnQ and most hotel system arrival/reservation reports). A booking counts as **in block** when one of
  your valid group codes appears **on the same line** as the name. Enter the codes in the sidebar, or let the
  app take them from the attendee file's group code column.
- **Table with cell borders** / **Table without borders**: for PDFs that are real tables. You pick the
  name and group code columns.

You can check and fix every reservation the app read in an editable table before you look at the results.

**Limits**
- Scanned (image) PDFs have no text. Re-export from the hotel system, or OCR them first
  (for example, Adobe Acrobat → Scan & OCR, or `ocrmypdf input.pdf output.pdf`).
- If a report wraps the group code onto a *different line* from the name, use a table option, or
  export a report layout that keeps each reservation on one line.

---

## Run it on your computer

```bash
cd group_block_audit
python -m venv .venv
# Windows: .venv\Scripts\activate     Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
It opens at http://localhost:8501. Try it with the files in `sample_data/`.

## Push to GitHub

```bash
cd group_block_audit
git init
git add .
git commit -m "Group Block Audit app"
git branch -M main
git remote add origin https://github.com/<your-username>/group-block-audit.git
git push -u origin main
```
(First create an **empty private** repository named `group-block-audit` on github.com.)

`.gitignore` blocks `.pdf`, `.xlsx` and `.csv` files (except `sample_data/`), so real guest reports never get committed by accident.

## Deploy on Streamlit Community Cloud

1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **Create app** → choose the repo, branch `main`, main file `app.py` → **Deploy**.
3. **Make it private:** in the app's **Settings → Sharing**, restrict who can view it to invited emails.

### ⚠️ Guest data
Attendee lists and reservation reports contain guest personal data. Uploaded files are processed in memory
and are not saved by the app, but on Community Cloud they still pass through Streamlit's servers.
**Check your company's data policy first.** If in doubt, run it locally or on an internal company server.
