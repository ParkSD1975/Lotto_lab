import os
import re

directory = r'c:\Users\psdet\Documents\lottoanalysis'

# ai-section 태그 바로 뒤에 소제목을 추가하는 패턴
# 단, 이미 추가되어 있는지 확인하기 위해 h3 태그 유무 체크
pattern = re.compile(r'(<div class="ai-section[^"]*">)', re.IGNORECASE)
check_pattern = re.compile(r'딥러닝 Insight', re.IGNORECASE)

subtitle_html = '\n                            <h3 class="text-lg font-bold text-gray-900 mb-4">딥러닝 Insight</h3>'

files_fixed = []

for filename in os.listdir(directory):
    if filename.endswith('.html'):
        filepath = os.path.join(directory, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 이미 존재하지 않는 경우에만 추가
        if not check_pattern.search(content):
            new_content = pattern.sub(r'\1' + subtitle_html, content)
            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                files_fixed.append(filename)

print(f"Added subtitle to {len(files_fixed)} files: {', '.join(files_fixed)}")
