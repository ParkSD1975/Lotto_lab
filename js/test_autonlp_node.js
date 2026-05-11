/**
 * Node.js 환경에서 AutoNLPMatcher 간단 테스트
 */

const fs = require('fs');
const path = require('path');

// AutoNLPMatcher 클래스 로드
const AutoNLPMatcher = require('./AutoNLPMatcher.js');

// vocabulary.json 로드 (fetch 대신 fs 사용)
class NodeAutoNLPMatcher extends AutoNLPMatcher {
    async load() {
        const vocabPath = path.join(__dirname, 'vocabulary.json');
        const content = fs.readFileSync(vocabPath, 'utf8');
        this.vocabulary = JSON.parse(content);
        this._buildIndex();
        this.loaded = true;
    }
}

async function runNodeTest() {
    console.log('=== AutoNLP Node.js Test ===\n');

    const matcher = new NodeAutoNLPMatcher();

    // 로드
    const loadStart = Date.now();
    await matcher.load();
    const loadTime = Date.now() - loadStart;

    console.log('✅ Vocabulary loaded in', loadTime, 'ms');
    console.log('Stats:', matcher.stats());

    // 테스트 케이스
    const cases = [
        '7과 8의 배수 합집합',
        'AC값 7~10인 조합',
        'XGBoost가 추천한 1등 번호',
        '엑스지비 추천',
        '칠배수 교집합'
    ];

    console.log('\n=== Matching Tests ===\n');

    for (const input of cases) {
        const start = Date.now();
        const result = matcher.match(input);
        const elapsed = Date.now() - start;

        console.log(`Input: "${input}"`);
        console.log(`  Intent: ${result.intent} (${result.confidence})`);
        console.log(`  Filters: ${result.filters.map(f => f.key).join(', ')}`);
        console.log(`  Models: ${result.models.map(m => m.key).join(', ')}`);
        console.log(`  Operations: ${result.operations.map(o => o.key).join(', ')}`);
        console.log(`  Numbers: ${result.numbers.map(n => n.value).join(', ')}`);
        console.log(`  Time: ${elapsed}ms\n`);
    }

    // 성능 테스트
    console.log('=== Performance Test (100 matches) ===');
    const perfStart = Date.now();
    for (let i = 0; i < 100; i++) {
        matcher.match('7과 8의 배수 교집합');
    }
    const perfTime = Date.now() - perfStart;
    console.log(`100 matches: ${perfTime}ms (avg: ${(perfTime / 100).toFixed(2)}ms)\n`);

    if (perfTime > 200) {
        console.warn(`⚠️ Performance Warning: ${perfTime}ms > 200ms`);
    } else {
        console.log(`✅ Performance OK: ${perfTime}ms < 200ms`);
    }

    console.log('\n=== Test Complete ===');
}

runNodeTest().catch(console.error);
