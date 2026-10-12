"""Re-runs the vision classifier on 9 real photos labelled by Michele (2026-10-12). Needs the API key and network.
Usage (from the project folder, venv active): python3 eval_photo_categories.py"""
import sys, os
sys.path.insert(0, os.getcwd())
import listing_scraper as ls
TRUTH = [("1963262854", "exterior"), ("1963262786", "kitchen"), ("1963262732", "uncategorized"), ("1963262744", "bedrooms"),
         ("1931513538", "uncategorized"), ("1931513644", "exterior"), ("1931513582", "uncategorized"), ("1931513620", "uncategorized"),
         ("1964225984", "kitchen")]
ok = 0
print("foto        vero           letto")
for i, t in TRUTH:
    got = ls._classify_photo_vision("https://pwm.im-cdn.it/image/%s/xl-c.jpg" % i, "https://pwm.im-cdn.it/image/%s/m-c.jpg" % i)[0]
    ok += got == t
    print(i, t.ljust(14), got + (" OK" if got == t else " --"))
print("giuste su %d: %d" % (len(TRUTH), ok))
