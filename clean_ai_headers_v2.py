import os
import re

dir_path = 'c:/Users/psdet/Documents/lottoanalysis'
html_files = [f for f in os.listdir(dir_path) if f.endswith('.html')]

# 훨씬 더 포괄적인 패턴: 'psychology'가 들어있는 flex 헤더 div 전체를 찾아서 제거
# dlInsightContainer 위의 헤더 영역을 대상으로 함
header_pattern = re.compile(r'[ \t]*<div class="flex items-center (?:justify-between|gap-3) mb-6">.*?<span[^>]*>psychology</span>.*?</h3>.*?</div>(?:\s*<button.*?</button>)?\s*</div>', re.DOTALL)

for filename in html_files:
    path = os.path.join(dir_path, filename)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = header_pattern.sub('', content)
    
    if new_content != content:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated: {filename}")
    else:
        # 혹시 dlTargetRound span이 남아있을 경우를 대비한 2차 패턴 (제목 없는 버전 등)
        round_pattern = re.compile(r'<span id="dlTargetRound"[^>]*></span>', re.DOTALL)
        new_content = round_pattern.sub('', content)
        if new_content != content:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Partially Updated (Round Span only): {filename}")
