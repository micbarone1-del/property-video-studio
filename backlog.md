# Property Video Studio — Backlog & Detailed Requirements
_Last updated: July 8, 2026_

Keep this file and status.md updated together whenever a bug is fixed, a feature's status changes, or a backlog item's requirements are refined. Entries should be dated and specific — never round up partial progress to "done."

## Automated URL-scraping workflow (photo selection and sequencing)

Scrape a property's online ad to automatically pull photos, replacing manual upload/selection for at least part of the workflow. Photo selection and sequencing must follow this agreed priority order: exterior, then living areas, then kitchen, then bedrooms, then bathrooms, then outdoor. If the scraped ad does not have enough usable photos to fill this sequence, the system must surface the gap explicitly and require manual upload — it must never silently degrade quality or substitute lower-quality or irrelevant photos to compensate. Narration sequencing/automation is not yet specified: it is unclear whether narration should be auto-generated from the scraped ad's description text, written manually per scene as today, or some hybrid of the two — this needs to be defined with the client before it can be scoped or built. The source site(s) to scrape, and how scraped photos map to specific ad fields, are also not yet specified.

## Cost report

A dedicated report, separate from the main tool, requiring its own login (its own access key, distinct from the main tool's key). Contents: a table listing every job — property name, date, number of scenes, model tier used, pre-generation cost estimate, and actual cost incurred including any reworks (itemized or totaled per property). Must be exportable as CSV so it can be shared with the business partner. Not yet built — no reporting code exists in the repository currently.

## Multi-job dashboard + concurrent queue

Submit multiple properties at once as a batch, each processed as its own job, without needing to babysit one at a time. Target concurrency (originally around 3 parallel jobs) needs to be confirmed against actual fal.ai and ElevenLabs rate limits before being implemented.

## Auto maintenance scheduler

Named as a priority item; no functional detail (what maintenance tasks, what cadence) has ever been specified. Needs requirements gathering before this can be scoped.

## YouTube auto-upload

Automatic upload of the finished video to a private YouTube channel after generation completes, via OAuth2 — removing the manual download/upload step entirely. Not yet built.

## Faster video preview

QC and final video previews have historically taken up to about 5 minutes to load, since Veo/Luma outputs are large 1080p files. Range-request streaming has been added to the download and clip-preview endpoints, which partially helps, but the originally proposed full fix — converting clips to HLS via FFmpeg so playback starts within 2-3 seconds — has not been built.

## Video library / old-job access

Interface to browse and access past jobs, currently retained for about 1 week. Needs to cover reworks too. Each rework already gets a unique job ID (parent id plus a rework suffix), so the missing piece is purely a browsing UI, ideally displayed as a version history per property.

## Watermark removal from input photos — DONE

Implemented via watermark_removal.py: fal.ai object-removal endpoint, AI-driven detection with no fixed-region assumptions (since watermark position and size vary by agency), an explicit per-photo toggle rather than automatic application to every photo, and a QC-flag fallback if removal is unreliable rather than silently using a bad result.

## Logo watermark on video — DONE

Bottom-right burn-in via MoviePy, already implemented.

## Portrait/vertical format

Blocked on model support, since Luma/Veo are primarily landscape. Two approaches were discussed but neither decided: use a different model with native portrait support, or post-process/letterbox the landscape output.

## Depth renderer for small rooms — PAUSED

Zero-hallucination camera movement via depth estimation and pixel reprojection (no generative model involved, so it cannot invent content not present in the original photo) — originally intended for small rooms where Lyra/Veo tend to degrade to a flat 2D zoom or hallucinate. Development reached a technical ceiling (movement too subtle, warping at hard depth edges) and has been paused, since Luma Ray 2 was confirmed via real-world testing to pragmatically solve the same underlying problem. Not integrated into the main pipeline.

## Human characters

Conceptually routed to Kling for character and motion realism. Never scoped beyond that.

## Virtual furniture staging

Conceptually related to human characters — a realistically furnished, human-populated room as one combined feature. Never scoped further.
