#!/usr/bin/env python3
import gzip
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE = "http://s06.wsbof.com:8080/xml/b4a9c2c7.gz"
IDS_FILE = Path("channel_ids.txt")
OUTPUT = Path("epg.xml")

wanted = {x.strip() for x in IDS_FILE.read_text(encoding="utf-8").splitlines()
          if x.strip() and not x.lstrip().startswith("#")}

req = urllib.request.Request(SOURCE, headers={"User-Agent": "Mozilla/5.0 EPG-Updater/1.0"})
with urllib.request.urlopen(req, timeout=120) as r:
    raw = r.read()

try:
    data = gzip.decompress(raw)
except gzip.BadGzipFile:
    data = raw

root = ET.fromstring(data)

# Keep channels/programmes whose XMLTV channel id exactly matches an M3U tvg-id.
# This intentionally avoids guessing incorrect mappings.
new_root = ET.Element("tv", root.attrib)
matched = set()

for ch in root.findall("channel"):
    cid = ch.get("id", "")
    if cid in wanted:
        new_root.append(ch)
        matched.add(cid)

for pr in root.findall("programme"):
    cid = pr.get("channel", "")
    if cid in matched:
        new_root.append(pr)

ET.ElementTree(new_root).write(OUTPUT, encoding="utf-8", xml_declaration=True)

missing = sorted(wanted - matched)
Path("missing_ids.txt").write_text("\n".join(missing) + ("\n" if missing else ""), encoding="utf-8")
print(f"Wanted IDs: {len(wanted)}; matched: {len(matched)}; missing: {len(missing)}")
