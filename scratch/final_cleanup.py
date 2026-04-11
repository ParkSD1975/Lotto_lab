import os
import re

directory = r'c:\Users\psdet\Documents\lottoanalysis'

# 1. Surgical cleanup for ai-section (Removes headers, buttons, and stray divs)
# This pattern matches from <div class="ai-section..."> until reaching <div id="dlInsightContainer">
surgical_pattern = re.compile(r'(<div class="ai-section[^"]*">).*?(<div id="dlInsightContainer">)', re.DOTALL)

# 2. Global cleanup for any missed header blocks (including the psychology icon and title)
header_block_pattern = re.compile(r'[ \t]*<div class="flex items-center (?:justify-between|gap-3) mb-6">.*?<span[^>]*>psychology</span>.*?</h3>.*?</div>', re.DOTALL)

# 3. Global cleanup for remaining refresh buttons
refresh_button_pattern = re.compile(r'[ \t]*<button onclick="DeepInsightPanel.refresh[^"]*"[^>]*>.*?</button>', re.DOTALL)

# 4. Search and destroy for "딥러닝 AI 인사이트" text specifically
insight_text_pattern = re.compile(r'딥러닝 AI 인사이트', re.DOTALL)

# 5. Search and destroy for the specific target round span if it was missed
target_round_pattern = re.compile(r'<span id="dlTargetRound"[^>]*>.*?</span>', re.DOTALL)

# 6. Search and destroy for the 1219회차 예측 text if it's hardcoded anywhere
predict_text_pattern = re.compile(r'\d+회차 예측', re.DOTALL)

files_fixed = []

for filename in os.listdir(directory):
    if filename.endswith('.html'):
        filepath = os.path.join(directory, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        orig_content = content
        
        # Apply cleanup
        content, c1 = surgical_pattern.subn(r'\1\n                            \2', content)
        content, c2 = header_block_pattern.subn('', content)
        content, c3 = refresh_button_pattern.subn('', content)
        content, c4 = insight_text_pattern.subn('', content)
        content, c5 = target_round_pattern.subn('', content)
        # 6번은 위험할 수 있으니 (다른 회차 표시에 영향) 일단 보류하거나 아주 좁게 적용
        # 하지만 사용자가 "제거해달라고" 했으니 AI 섹션 주변에 있는 것만 제거하는 게 안전함.
        # 위 1번에서 이미 제거했을 것임.

        if content != orig_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            files_fixed.append(filename)

print(f"Fixed {len(files_fixed)} files: {', '.join(files_fixed)}")
