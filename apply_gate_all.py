import sys
def sub(path, pairs):
    s = open(path).read()
    for old, new in pairs:
        assert s.count(old) == 1, (path, old[:60])
        s = s.replace(old, new)
    open(path, "w").write(s)
sub("listing_scraper.py", [
("ROOM_FEATURE_CHECK_PER_CATEGORY = 3     # the best-ranked candidates asked, in ranking order, until one passes","ROOM_FEATURE_CHECK_PER_CATEGORY = 6     # every ranked candidate is asked (same pool size the quality comparison looks at)"),
('''shows it). Stops at the first "yes". A failed call keeps the photo (unknown). Never raises."""''','''shows it). Every candidate in the pool is asked (no early stop), so the selection report holds the answer for each photo. A failed call keeps the photo (unknown). Never raises."""'''),
('''        failed, passed_at = [], None
        for i, p in enumerate(plist[:ROOM_FEATURE_CHECK_PER_CATEGORY]):''','''        failed, asked, passed = [], 0, False
        for p in plist[:ROOM_FEATURE_CHECK_PER_CATEGORY]:'''),
('''            p["feature_visible"] = ok
            if ok is False:
                failed.append(p)
            else:
                passed_at = i
                break
''','''            p["feature_visible"] = ok
            asked += 1
            if ok is False:
                failed.append(p)
            else:
                passed = True
'''),
('''"checked": len(failed) + (1 if passed_at is not None else 0), "failed": len(failed), "passed": passed_at is not None}''','''"checked": asked, "failed": len(failed), "passed": passed}'''),
])
sub("test_photo_as_used.py", [
('check("F2 the check stops at the first yes (c and d are not asked)", seen == ["a", "b"], seen)','check("F2 every candidate is asked, no early stop", seen == ["a", "b", "c", "d"], seen)'),
('check("F4 nothing passes in the first 3 -> only 3 asked, nothing deleted, 4 photos stay", len(seen) == 3 and len(order) == 4 and summ["bathrooms"]["passed"] is False, (seen, summ))','check("F4 only the last passes -> all 4 asked, it goes first, nothing deleted", len(seen) == 4 and order == ["d", "a", "b", "c"] and summ["bathrooms"]["checked"] == 4, (order, seen, summ))\norder, seen, summ, by = run({"a": False, "b": False, "c": False, "d": False})\ncheck("F4b nothing passes -> all asked, order unchanged, 4 photos stay, passed False", len(seen) == 4 and order == ["a", "b", "c", "d"] and summ["bathrooms"]["passed"] is False, (order, seen, summ))'),
])
print("applicato")
