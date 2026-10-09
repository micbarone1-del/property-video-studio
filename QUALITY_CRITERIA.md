# QUALITY_CRITERIA.md -- what a finished video must satisfy before release (DRAFT 2026-10-09)

_Status: draft by Claude from project evidence and Relinx feedback (voice "TG style", per-agency logo, per-scene narration). Thresholds marked (proposed) are starting values to calibrate on the first 30 videos; they are not measured facts. Links: AUTOMATION_TEST_PLAN.md requirements R08/R14 and FMEA rows F07, F16-F19, F29, F30, F38, F39. Questions that must be agreed with Relinx are in RELINX_QUESTIONS.md._

## 1. Release rule (applies to every video, in pilot 100% by a human)
Each finding has a severity. **Release only if: 0 Critical, 0 Major, at most 2 Minor.**
- **Critical** (never deliver; investigate the cause): an invented fact or object; wrong property/photo; privacy or legal problem; offensive/unsafe content; unplayable file.
- **Major** (fix by rework before release): visible visual artifact longer than 1 s; voice cut off or wrong language; narration not matching the photo shown; resolution below spec; wrong/missing logo; wrong orientation.
- **Minor** (log and track): small transition imperfection, slightly flat intonation, a pause a bit long.
Method: **A** = automatic check (to build or already existing), **H** = human check. Where only H exists today it is a gap listed in section 6.

## 2. Accuracy -- no hallucinations (most important)
| ID | Criterion | Method | Threshold | Severity if failed |
|---|---|---|---|---|
| Q01 | Every number in the narration (sqm, rooms, floor, price, year) appears in the listing data | A (extract numbers, compare) + H | 100% match | Critical |
| Q02 | Every feature claimed (balcony, terrace, garden, parking, lift, sea view, renovated, energy class...) is present in the listing text or visible in a photo | A (claims list vs input) + H | 0 unsupported claims | Critical |
| Q03 | No claim the listing does not make: neighbourhood superlatives, distances, investment/return statements, legal statements | A (blocklist + LLM check) + H | 0 | Critical |
| Q04 | Names, street, city and agency spoken correctly (pronunciation check on a short list) | H | 0 mispronounced key names | Major |
| Q05 | No object, person, animal, window, door, room or furniture added, removed or morphed compared with the source photo | A (vision QC frame vs photo) + H | 0 | Critical |
| Q06 | Geometry stays stable: straight walls, same number of windows/doors, floor pattern not swimming, no melting furniture | H (+ A frame-difference) | no distortion visible at normal speed | Major (Critical if it changes the property) |
| Q07 | No garbled text/signs/numbers appearing in frames; no other agency's logo, phone number or watermark visible | A (OCR on frames) + H | 0 | Major |
| Q08 | No people, faces or number plates identifiable unless allowed by Relinx rule | A (detector) + H | 0 | Critical |

## 3. Professional look and image quality
| ID | Criterion | Method | Threshold | Severity |
|---|---|---|---|---|
| Q10 | Resolution and format: landscape 1920x1080 or portrait 1080x1920 (as requested), >= 24 fps, H.264 + AAC, yuv420p, faststart | A (ffprobe) | exact | Major |
| Q11 | Sharpness: not blurrier than the source photo; no upscale halos, noise or compression blocks | A (sharpness metric vs source, e.g. Laplacian variance ratio >= 0.8 (proposed)) + H | pass | Major |
| Q12 | Source photo gate: long side >= 1600 px and not heavily compressed; otherwise flag before generation | A | pass or flagged to operator | Major (prevent) |
| Q13 | Camera movement smooth: no jitter, jumps, sudden zoom, no flicker | H (+ A optical-flow jerk metric later) | none | Major |
| Q14 | Colour and exposure consistent across scenes (no scene much darker/yellower than neighbours) | A (mean luminance/colour difference between consecutive scenes within (proposed) 15%) + H | pass | Minor/Major |
| Q15 | No black/frozen frames, no flash at joins, transitions clean, no watermark artifact (earlier black-box bug) | A (frame scan) + H | 0 | Major |
| Q16 | Pacing: scene length 5-9 s, total length in the agreed range (proposed 40-75 s for ~8-10 photos), no scene lingering on an empty wall | A (duration) + H | in range | Minor |
| Q17 | Photos ordered logically (entrance/living -> kitchen -> bedrooms -> bathrooms -> outdoor) | A (category order) + H | pass | Minor |
| Q18 | File size and bitrate allow smooth playback over the CRM (proposed <= 60 MB for 60 s) | A | pass | Minor |

## 4. Voice and narration
_Language (decision 2026-10-09): the design is language-general (language is a request parameter; voice, narration prompt, number/unit formats and the language-dependent thresholds below -- Q04, Q20, Q26 -- are per language), but **only Italian is live**. A language becomes "supported" only after its golden set of 10 listings passes and a native-level reviewer has signed off._
| ID | Criterion | Method | Threshold | Severity |
|---|---|---|---|---|
| Q20 | Language correct (Italian), grammar and register natural, not "news-anchor/TG" style (Relinx feedback); energetic but credible | H (rubric 1-5) | >= 4 | Major |
| Q21 | Covers the main characteristics in order of importance: type + size, layout/rooms, key features (outdoor space, light, parking, lift), condition, location highlight; nothing important of the listing left out | A (coverage vs structured fields) + H | all "must-have" fields mentioned (list agreed with Relinx) | Major |
| Q22 | Voice-picture sync: narration for a scene describes what that scene shows; a feature is named while the photo that shows it is on screen (+/- 1 s) | A (per-scene text vs photo caption/vision) + H | 100% of scenes | Major |
| Q23 | At key points the voice refers to the photo ("qui il soggiorno luminoso...") without describing details that are not visible | H | natural, 0 invented detail | Major |
| Q24 | Speech not cut: lead/trail buffer present, no clipped words, no overlap between scenes | A (audio vs clip length) | 0 cut | Major |
| Q25 | Loudness -16 LUFS +/- 1 (proposed), true peak <= -1 dBTP, no clipping, no long silences (> 1.5 s) | A (ffmpeg loudnorm/ebur128) | pass | Minor/Major |
| Q26 | Speech rate comfortable (proposed 2.2-2.8 words/s) and numbers read naturally ("centoventi metri quadri") | A (words/duration) + H | in range | Minor |
| Q27 | Voice consistent across all scenes and matches the voice agreed for the agency/partner | A (same voice id) | pass | Major |
| Q28 | Narration length fits the scene (no overflow warning) | A | pass | Major |

## 5. Brand, compliance and delivery
_Decision 2026-10-09: the Property Video Studio logo/watermark is replaced by the text-only AI label (Q31, always English); the agency logo (Q30) arrives through the API and stays a separate, optional element. Consequence accepted: no brand advertising on the videos._
| ID | Criterion | Method | Threshold | Severity |
|---|---|---|---|---|
| Q30 | Agency logo (supplied through the API, same mechanism as onboarding a new agency) correct and legible if supplied; if none, neutral/no third-party branding (Relinx feedback) | A (config) + H | pass | Major |
| Q31 | AI label (decision 2026-10-09): text only "Generated with AI" (always English, never localized), light grey with a subtle shadow, same position as the former watermark (bottom-left), no logo/icon; text fixed in English, white label (no Property Video Studio logo). Legible on bright walls: contrast of label vs local background >= 3:1 (proposed) measured on sample frames | A (frame contrast) + H | present in every scene and in the final video, legible | Major |
| Q32 | Photos used only from the listing supplied by the agency; no scraped/foreign images | A (source check) | 0 foreign | Critical |
| Q33 | Delivered file plays in the Relinx player and the link works for the agreed time | A (synthetic partner probe) + H (their staging) | pass | Critical |
| Q34 | Status and `video_url` consistent: `completed` only when the file exists, is valid and was released | A | pass | Critical |

## 6. Gaps: what exists today and what must be built
- **Exists**: vision QC on clips (Florence-2 caption diff, known to be weak for physical implausibility), audio lead/trail buffer, ffprobe validity checks, per-job voice id, human QC panel, rework with caps.
- **To build (priority order)**: Q01-Q03 narration-vs-listing fact check (highest value, cheap); Q10/Q15/Q18/Q24/Q25 technical checks with ffprobe/ffmpeg in the release step (cheap, deterministic); Q12 source photo gate; Q22 per-scene voice-photo check; Q05/Q07/Q08 vision/OCR/people checks on frames; Q14 colour/exposure consistency.
- Until built, those checks are done by the human reviewer with the checklist below.

## 7. Reviewer checklist (human, per video, ~3 minutes)
1. Watch once at normal speed with sound: anything look wrong or invented? (Q05, Q06, Q13)
2. Read the narration against the listing: every number and feature supported? (Q01-Q03)
3. Voice: natural, right language, no cut words, matches the photo shown? (Q20-Q24)
4. Check logo/label/watermark and that no other brand or person appears. (Q07, Q08, Q30, Q31)
5. Play on the target player/phone; check orientation and file size. (Q10, Q33)
6. Record verdict (release / rework / reject), severity of each finding, time spent.
Reviewers (decision 2026-10-09): internal phase with Relinx = Michele + Relinx's contact (also named Michele, to be confirmed by Relinx); pilot = Michele + the agency (GIAL) looking at the video as the agency would. Automatic pre-checks are an aid, not a reviewer. Calibration: both reviewers rate the same 5 videos before the window; disagree on > 1 in 5 -> clarify rubric.

## 8. Measurement and monitoring
- Per video store: checks passed/failed by ID, severity, reviewer, review time, number of reworks, cost.
- KPIs: first-pass release rate (target >= 80% proposed), average reworks per video (<= 0.5), Critical findings per 100 videos (target 0), review minutes per video, agency acceptance rate (R08 >= 90%).
- **Golden set**: 10 reference listings (easy, hard, odd photos) rerun after every change to generation/narration/voice; compare findings, so improvements do not silently break quality.
- **Agency feedback** (decision 2026-10-09): qualitative, by voice, for the ~10 pilot videos; Michele talks to the agency and reports to Claude, who turns each remark into a finding/FMEA re-rating. Conversation guide: (1) would you publish it as is (yes / with changes / no), (2) what bothered you (voice, images, information, length, other), (3) one thing to change. No feedback endpoint is built now; revisit if volume grows.
- Every finding from a test, review or agency feedback becomes a row (or a re-rating) in the FMEA.

## 9. Open decisions
Must-have narration fields (Q21); length range (Q16); whether music is used and rules; people/plate rule (Q08); any Relinx legal requirement on the AI label (wording is fixed: "Generated with AI", English); player specs and URL lifetime (Q33); acceptance rubric thresholds after the first 30 videos. Decided 2026-10-09: reviewers, feedback channel, label style, language scope (see above).

_Assumptions (2026-10-09): photos supplied by the CRM are the high-resolution originals with reliable order and categories; if tests show otherwise, log a finding. The Relinx contact (Michele) is the test referent. A shareable summary is in QUALITY_SPEC_FOR_RELINX.md._
