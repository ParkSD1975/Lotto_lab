"""Hungary Hatoslottó 공식 CSV 구조 확인"""
import requests, io, csv

r = requests.get("https://bet.szerencsejatek.hu/cmsfiles/hatos.csv", timeout=20)
print("Status:", r.status_code)
print("Encoding:", r.apparent_encoding)
print("Size:", len(r.content), "bytes")

# 첫 3줄 출력
text = r.content.decode("latin-1", errors="replace")
lines = text.splitlines()
print("\n첫 5줄:")
for l in lines[:5]:
    print(repr(l))
