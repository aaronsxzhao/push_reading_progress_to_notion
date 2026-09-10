# New book synchronization

The daily sync includes shelf books and personal notebooks outside the shelf.
Books are created once using the existing title-and-author match; subsequent
runs update the existing page and deduplicate notes.

Start-date policy:

1. Prefer a positive `startReadingTime` returned by the official gateway.
2. If unavailable, use the earliest available personal note creation time or
   reading-position timestamp accompanied by positive reading/listening time.
3. Label the fallback in `Start Date Source` as an observed activity date, not a
   guaranteed first-read date. The gateway does not expose a complete per-book
   daily history; earlier activity predating the first sync may be unavailable.
4. Keep the earliest observed date across subsequent syncs. A later explicit
   start time may replace a date already labelled as an estimate. Estimates do
   not replace dates labelled as explicit start times.
5. Derive `Year Started` from the date retained in Notion. Books with no start
   time, personal notes, or positive reading/listening time stay undated.

The sync creates the `Start Date Source` text property if it is missing. Existing
unlabelled historical dates keep their provenance unknown unless changed.
Dates are interpreted in Asia/Shanghai. Invalid/missing timestamps are ignored;
publication dates, import dates and zero-duration position records are not used.

Run regression checks with `python -m unittest discover -s tests -q`.

## Reading position and existing progress formulas

Completion is permanent: an existing Read status, completion date, or stored
100% progress keeps a book Read at 100%, even if a later source position moves
backwards. An official finishTime or finishReading=1 flag also counts as completion
regardless of the current position. A finish flag without a date does not invent
a completion date. Current Page stays equal to Total Page (including when total
metadata changes); if the source omits the total, the existing total is used.
The original completion date is preserved. Highlights, thoughts, chapter
position and last-read activity continue syncing. Full estimated pages alone
are not treated as evidence of completion.

`Total Page` retains the original estimated-page convention: full book word
count divided by 550 and rounded (minimum 1 for a nonempty book). `Current Page`
is the rounded-up result of `Total Page * progress / 100`, including an explicit
0 for unread books. These are estimates for the existing Notion formula, not
printed edition page numbers. Both properties update on every successful sync;
the `Page Count` formula and progress display settings are left unchanged.

`Total Words` stores the official book-level `wordCount`, or sums every chapter's
`wordCount` from the complete official directory when the book-level field is
absent. Incomplete chapter counts remain unknown; note-only chapter metadata
must never be summed as the full book. The directory response is reused for
the current chapter to avoid duplicate requests. `Current Chapter`
resolves the current reading `chapterUid` to its title, reusing available note
metadata or fetching the official chapter directory when needed. Chapter IDs
are never treated as array positions. Unavailable chapter titles are labelled
explicitly. Missing word counts do not overwrite existing page/word counts.

Existing blank author and genre properties are filled when the source provides
them; existing nonempty values are preserved. Known categories use the English
genre map. Unmapped categories retain their original official label instead of
being discarded. Personal ratings and review fields are not invented from the
community rating or from the mere absence of a review.

Legacy WeRead pages whose official cover URL explicitly identifies the same
book ID also receive the current reading fields, even if their titles differ.
Only pages tagged WeRead and recognized official cover URL patterns participate.
Existing pages are preserved; a renamed book reuses its recognized page instead
of creating another copy. Notes sync to the primary matched page.

The cloud job allows up to 90 minutes for paced requests and quota backoff.
For a partial recovery, the manual workflow accepts `book_ids` as a comma-separated
list of stable IDs. Only those current shelf/notebook books are processed; unknown
IDs abort before writes. Leave it empty for the normal complete daily sync.

GitHub caches only public chapter metadata, never credentials, reading positions
or personal notes. It expires after seven days and refreshes immediately if the
current chapter UID is absent. Reading progress, highlights and thoughts still
come from fresh API calls on every sync. Quiet periods gradually restore request
pacing after quota backoff; server retry delays are still honored.
