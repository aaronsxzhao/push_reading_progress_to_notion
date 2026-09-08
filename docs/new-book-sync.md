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
