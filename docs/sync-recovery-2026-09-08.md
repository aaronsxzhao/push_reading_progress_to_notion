# WeRead sync recovery — 2026-09-08

The previous workflow reported success after an expired Cookie returned an empty bookshelf. Its last run was July 6 and the workflow was disabled. The sync now prefers the official WeRead Skills 1.0.4 API gateway via WEREAD_API_KEY, fails on incomplete reads/writes, and preserves existing Notion notes.

Live verification confirmed 170 electronic book entries and one article-collection entry. The Notion connection and a single-book progress write/read-back succeeded. A Reading Progress numeric property stores official 0–100 progress, converted to 0–1 for Notion percent formatting. Missing page counts and dates are not guessed. Audio albums and the article-collection entry are reported separately and are not imported as electronic books.

The first bulk run hit HTTP 499 / errcode -2014 (request-frequency limit). A shared limiter now keeps calls below approximately 55/minute, with 60-second cooldown and bounded retries. Run statistics report actual successes and failures.

Personal reviews are fully paginated. New notes are appended without deleting existing or manually edited content. This is not bidirectional note editing/deletion synchronization. Official read-time totals and daily buckets feed the heatmap; all reading durations use seconds.

## Deployment

Set repository Secret WEREAD_API_KEY using your key from https://weread.qq.com/r/weread-skills. Existing NOTION_TOKEN and NOTION_DATABASE_ID secrets remain required. Re-enable the existing Sync WeRead to Notion workflow and run it once. The daily schedule remains 02:00 UTC / 10:00 Asia/Shanghai; GitHub scheduling may be delayed. Heatmap publication additionally needs a working GH_TOKEN with Gist write access and COOKIE_GIST_ID.

Use Python 3.11+. For local read-only verification run `.venv/bin/python scripts/diagnose_sync.py --limit 3`. A local `.env` may hold the same configuration; never commit it. Set PROP_PROGRESS for an existing numeric property with a different name. Formula properties are not overwritten.

23 offline regression tests passed. Full bulk and scheduled-run completion must be checked separately in run logs; a working single-book test does not prove the scheduled workflow is running.

Official contract: https://github.com/Tencent/WeChatReading/tree/main/skills
