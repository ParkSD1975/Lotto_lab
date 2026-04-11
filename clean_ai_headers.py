import os
import re

dir_path = 'c:/Users/psdet/Documents/lottoanalysis'
html_files = [f for f in os.listdir(dir_path) if f.endswith('.html')]

# 패턴 1: 이미 정리된 파일 (flex gap-3 mb-6 스타일)
pattern1 = re.compile(r'[ \t]*<div class="flex items-center gap-3 mb-6">\s*<div class="flex items-center justify-center w-10 h-10 rounded-xl"\s*style="background:linear-gradient\(135deg,#3b82f6,#7c3aed\)"\s*>\s*<span class="material-symbols-outlined text-white text-xl">psychology</span>\s*</div>\s*<div>\s*<h3 class="text-xl font-extrabold text-gray-900 tracking-tight">딥러닝 AI 인사이트</h3>\s*</div>\s*</div>\s*', re.DOTALL)

# 패턴 2: 아직 정리 안된 파일 (justify-between 스타일)
pattern2 = re.compile(r'[ \t]*<div class="flex items-center justify-between mb-6">\s*<div class="flex items-center gap-3">.*?psychology.*?</h3>\s*</div>\s*</div>\s*', re.DOTALL)
# 버튼도 포함된 패턴 2 확장판
pattern2b = re.compile(r'[ \t]*<div class="flex items-center justify-between mb-6">\s*<div class="flex items-center gap-3">.*?psychology.*?</h3>\s*</div>\s*</div>\s*<button onclick="DeepInsightPanel\.refresh\(.*?\)"[^>]*>.*?</button>\s*</div>\s*', re.DOTALL)

for filename in html_files:
    path = os.path.join(dir_path, filename)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = pattern1.sub('', content)
    new_content = pattern2.sub('', new_content)
    new_content = pattern2b.sub('', new_content)
    
    if new_content != content:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated: {filename}")
