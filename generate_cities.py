import urllib.request
import zipfile
import io
import json
import os

url = "https://download.geonames.org/export/dump/cities1000.zip"
print(f"Downloading {url}...")
req = urllib.request.urlopen(url)
zip_file = zipfile.ZipFile(io.BytesIO(req.read()))

txt_data = zip_file.read("cities1000.txt").decode("utf-8")

cities = []
seen = set()
for line in txt_data.split('\n'):
    if not line.strip():
        continue
    parts = line.split('\t')
    if len(parts) > 14:
        name = parts[1]
        asciiname = parts[2]
        alt_names = parts[3]
        lat = float(parts[4])
        lng = float(parts[5])
        country = parts[8]
        
        # Sadece Türkiye'yi alalım ya da hepsini alalım
        # cities1000 has ~140k cities. Let's just include all.
        key = f"{name}_{country}"
        if key not in seen:
            seen.add(key)
            cities.append({"n": name, "c": country, "lt": lat, "ln": lng})
            
# Arama için kolaylık sağlamak adına TR.zip verilerini de çekelim mi?
# Actually, let's download TR.zip specifically for Turkish districts.
url_tr = "https://download.geonames.org/export/dump/TR.zip"
print(f"Downloading {url_tr}...")
req_tr = urllib.request.urlopen(url_tr)
zip_file_tr = zipfile.ZipFile(io.BytesIO(req_tr.read()))

txt_data_tr = zip_file_tr.read("TR.txt").decode("utf-8")
for line in txt_data_tr.split('\n'):
    if not line.strip():
        continue
    parts = line.split('\t')
    if len(parts) > 14:
        # P = city, village,... feature class
        feature_class = parts[6]
        if feature_class == 'P' or feature_class == 'A':
            name = parts[1]
            lat = float(parts[4])
            lng = float(parts[5])
            country = parts[8]
            
            key = f"{name}_{country}"
            if key not in seen:
                seen.add(key)
                cities.append({"n": name, "c": country, "lt": lat, "ln": lng})

cities.sort(key=lambda x: (x["c"], x["n"]))

out_dir = "/Users/aykutss/Desktop/app-kodlar/astromind/assets"
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "cities.json")

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(cities, f, ensure_ascii=False, separators=(',', ':'))

print(f"Successfully generated {out_path} with {len(cities)} locations.")
