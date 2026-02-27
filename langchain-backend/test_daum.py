import requests
from bs4 import BeautifulSoup
headers = {'User-Agent': 'Mozilla/5.0'}
resp = requests.get("https://search.daum.net/search?w=tot&q=1212회+로또", headers=headers)
soup = BeautifulSoup(resp.text, 'html.parser')
box = soup.select_one('#lottoColl')
if box:
    print("Found! ", box.text[:100])
    balls = [b.text for b in box.select('.ball')]
    print("Balls: ", balls)
    balls2 = [b.text for b in box.select('.ball_lotto')]
    print("Balls2: ", balls2)
else:
    print("Not found! Let's check the HTML.")
    print(resp.text[:500])
