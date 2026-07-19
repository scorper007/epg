#!/usr/bin/env python3

import gzip
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta, timezone

SOURCE = "http://s06.wsbof.com:8080/xml/b4a9c2c7.gz"
IDS_FILE = Path("channel_ids.txt")
OUTPUT = Path("epg.xml")

# Сколько суток EPG оставлять
DAYS_AHEAD = 1

# Загружаем tvg-id наших каналов
wanted = {
    x.strip()
    for x in IDS_FILE.read_text(encoding="utf-8").splitlines()
    if x.strip() and not x.lstrip().startswith("#")
}

print(f"Каналов в плейлисте: {len(wanted)}")
print(f"Скачиваю EPG: {SOURCE}")

# Скачиваем исходный EPG
req = urllib.request.Request(
    SOURCE,
    headers={"User-Agent": "Mozilla/5.0 EPG-Updater/2.0"}
)

with urllib.request.urlopen(req, timeout=180) as r:
    raw = r.read()

print(f"Скачано: {len(raw) / 1024 / 1024:.2f} MB")

# Распаковываем gzip
try:
    data = gzip.decompress(raw)
except gzip.BadGzipFile:
    data = raw

print(f"XML после распаковки: {len(data) / 1024 / 1024:.2f} MB")

root = ET.fromstring(data)

# Создаём новый XMLTV
new_root = ET.Element("tv", root.attrib)

matched = set()

# Добавляем только наши 399 каналов
for ch in root.findall("channel"):
    cid = ch.get("id", "")

    if cid in wanted:
        new_root.append(ch)
        matched.add(cid)

# Временной диапазон:
# немного оставляем уже начавшиеся передачи
now = datetime.now(timezone.utc)

start_limit = now - timedelta(hours=6)
end_limit = now + timedelta(days=DAYS_AHEAD)

def parse_xmltv_time(value):
    if not value:
        return None

    try:
        # Пример:
        # 20260719123000 +0300

        date_part = value[:14]

        dt = datetime.strptime(
            date_part,
            "%Y%m%d%H%M%S"
        )

        parts = value.split()

        if len(parts) > 1:
            offset = parts[1]

            sign = 1 if offset[0] == "+" else -1

            hours = int(offset[1:3])
            minutes = int(offset[3:5])

            tz = timezone(
                sign * timedelta(
                    hours=hours,
                    minutes=minutes
                )
            )

            dt = dt.replace(tzinfo=tz)

        else:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None

programme_count = 0
programme_channels = set()

for pr in root.findall("programme"):

    cid = pr.get("channel", "")

    if cid not in matched:
        continue

    start = parse_xmltv_time(
        pr.get("start")
    )

    stop = parse_xmltv_time(
        pr.get("stop")
    )

    if start is None:
        continue

    # Если передача уже закончилась давно
    if stop is not None:
        if stop < start_limit:
            continue
    else:
        if start < start_limit:
            continue

    # Не берём передачи дальше 3 суток
    if start > end_limit:
        continue

    new_root.append(pr)

    programme_count += 1
    programme_channels.add(cid)

# Сохраняем XML
tree = ET.ElementTree(new_root)

tree.write(
    OUTPUT,
    encoding="utf-8",
    xml_declaration=True
)

# Каналы, которых вообще нет в источнике
missing = sorted(
    wanted - matched
)

Path("missing_ids.txt").write_text(
    "\n".join(missing) +
    ("\n" if missing else ""),
    encoding="utf-8"
)

# Каналы, которые существуют,
# но не имеют программы в выбранном диапазоне
no_programme = sorted(
    matched - programme_channels
)

Path("no_programme_ids.txt").write_text(
    "\n".join(no_programme) +
    ("\n" if no_programme else ""),
    encoding="utf-8"
)

print("--------------------------------")
print(f"Каналов запрошено: {len(wanted)}")
print(f"Каналов найдено: {len(matched)}")
print(f"Каналов отсутствует: {len(missing)}")
print(
    f"Каналов с программой: "
    f"{len(programme_channels)}"
)
print(
    f"Каналов без программы: "
    f"{len(no_programme)}"
)
print(
    f"Передач сохранено: "
    f"{programme_count}"
)
print(
    f"EPG период: примерно "
    f"{DAYS_AHEAD} суток"
)
print("--------------------------------")
