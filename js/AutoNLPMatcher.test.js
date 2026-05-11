/**
 * Lotto Lab Self-Discovery NLP Phase 2 - AutoNLPMatcher Test Suite
 *
 * 브라우저 콘솔에서 실행 가능한 자체 테스트
 * Usage: runAutoNLPTests() 호출
 *
 * @version 1.0.0
 * @date 2026-05-08
 */

/**
 * 테스트 실행 함수
 */
window.runAutoNLPTests = async () => {
    console.log('=== AutoNLPMatcher Test Suite Start ===\n');

    // autoNLP 준비 확인
    if (!window.autoNLP || !window.autoNLP.loaded) {
        console.error('❌ window.autoNLP not loaded. Please wait for autoNLPReady event.');
        return;
    }

    const testCases = [
        // Case 1: 필터 조합 (교집합)
        {
            name: 'Case 1: 7과 8의 배수 합집합',
            input: '7과 8의 배수 합집합',
            expect: {
                filters: { min: 2 }, // 최소 2개 필터
                operations: ['union'],
                intent: 'filter_combination'
            }
        },

        // Case 2: AC값 범위 쿼리
        {
            name: 'Case 2: AC값 7~10인 조합',
            input: 'AC값 7~10인 조합',
            expect: {
                filters: ['ac', 'ac_value'], // 둘 중 하나
                numbers: { min: 2 } // 7, 10
            }
        },

        // Case 3: 모델 쿼리
        {
            name: 'Case 3: XGBoost가 추천한 1등 번호',
            input: 'XGBoost가 추천한 1등 번호',
            expect: {
                models: ['xgboost'],
                intent: 'model_query'
            }
        },

        // Case 4: 시간 윈도우 + 통계
        {
            name: 'Case 4: 최근 50회 핫번호',
            input: '최근 50회 핫번호',
            expect: {
                time_windows: ['recent_n'],
                numbers: { includes: 50 }
            }
        },

        // Case 5: 다중 필터 교집합
        {
            name: 'Case 5: 고저 4:2 홀짝 5:1 교집합',
            input: '고저 4:2 홀짝 5:1 교집합',
            expect: {
                filters: { min: 2 },
                operations: ['intersection'],
                intent: 'filter_combination'
            }
        },

        // Case 6: 다중 모델 + 통계
        {
            name: 'Case 6: AE랑 GNN 평균 추천',
            input: 'AE랑 GNN 평균 추천',
            expect: {
                models: { includes: ['autoencoder', 'gnn'] },
                statistics: ['average']
            }
        },

        // Case 7: 필터 + 시간 윈도우
        {
            name: 'Case 7: 제곱수 미출현 200회',
            input: '제곱수 미출현 200회',
            expect: {
                filters: ['square_number'],
                time_windows: ['missing_n'],
                numbers: { includes: 200 }
            }
        },

        // Case 8: 한글 변형 (모델 별칭)
        {
            name: 'Case 8: 엑스지비 추천 번호',
            input: '엑스지비 추천 번호',
            expect: {
                models: ['xgboost']
            }
        },

        // Case 9: 한글 숫자 + 연산
        {
            name: 'Case 9: 칠배수 합집합',
            input: '칠배수 합집합',
            expect: {
                numbers: { includes: 7 },
                operations: ['union']
            }
        }
    ];

    let passCount = 0;
    let failCount = 0;
    const results = [];

    // 각 테스트 실행
    for (let i = 0; i < testCases.length; i++) {
        const testCase = testCases[i];
        try {
            const startTime = performance.now();
            const result = window.autoNLP.match(testCase.input);
            const elapsed = Math.round(performance.now() - startTime);

            const validation = validateResult(result, testCase.expect);

            if (validation.passed) {
                console.log(`✅ ${testCase.name} (${elapsed}ms)`);
                passCount++;
            } else {
                console.log(`❌ ${testCase.name} (${elapsed}ms)`);
                console.log('   Expected:', testCase.expect);
                console.log('   Got:', result);
                console.log('   Reason:', validation.reason);
                failCount++;
            }

            results.push({
                name: testCase.name,
                passed: validation.passed,
                elapsed,
                result,
                reason: validation.reason
            });

        } catch (error) {
            console.log(`❌ ${testCase.name} - Exception: ${error.message}`);
            failCount++;
            results.push({
                name: testCase.name,
                passed: false,
                error: error.message
            });
        }
    }

    // 성능 테스트 (100건 매칭)
    console.log('\n=== Performance Test (100 matches) ===');
    const perfStart = performance.now();
    for (let i = 0; i < 100; i++) {
        window.autoNLP.match('7과 8의 배수 교집합');
    }
    const perfElapsed = Math.round(performance.now() - perfStart);
    console.log(`100 matches: ${perfElapsed}ms (avg: ${(perfElapsed / 100).toFixed(2)}ms per match)`);

    // 최종 결과
    console.log('\n=== Test Summary ===');
    console.log(`Total: ${testCases.length}`);
    console.log(`✅ Passed: ${passCount}`);
    console.log(`❌ Failed: ${failCount}`);
    console.log(`Success Rate: ${Math.round((passCount / testCases.length) * 100)}%`);

    if (perfElapsed > 200) {
        console.warn(`⚠️ Performance Warning: 100 matches took ${perfElapsed}ms (target: <200ms)`);
    } else {
        console.log(`✅ Performance OK: ${perfElapsed}ms`);
    }

    return {
        passed: passCount,
        failed: failCount,
        total: testCases.length,
        performance: perfElapsed,
        results
    };
};

/**
 * 결과 검증 헬퍼
 */
function validateResult(result, expect) {
    // filters 검증
    if (expect.filters) {
        if (Array.isArray(expect.filters)) {
            // 특정 key 포함 여부
            const matchedKeys = result.filters.map(f => f.key);
            const hasExpected = expect.filters.some(key => matchedKeys.includes(key));
            if (!hasExpected) {
                return {
                    passed: false,
                    reason: `Expected filters to include one of ${expect.filters.join(', ')}, got ${matchedKeys.join(', ')}`
                };
            }
        } else if (expect.filters.min) {
            if (result.filters.length < expect.filters.min) {
                return {
                    passed: false,
                    reason: `Expected at least ${expect.filters.min} filters, got ${result.filters.length}`
                };
            }
        }
    }

    // models 검증
    if (expect.models) {
        if (Array.isArray(expect.models)) {
            const matchedKeys = result.models.map(m => m.key);
            const hasExpected = expect.models.some(key => matchedKeys.includes(key));
            if (!hasExpected) {
                return {
                    passed: false,
                    reason: `Expected models to include one of ${expect.models.join(', ')}, got ${matchedKeys.join(', ')}`
                };
            }
        } else if (expect.models.includes) {
            const matchedKeys = result.models.map(m => m.key);
            const allIncluded = expect.models.includes.every(key => matchedKeys.includes(key));
            if (!allIncluded) {
                return {
                    passed: false,
                    reason: `Expected models to include all of ${expect.models.includes.join(', ')}, got ${matchedKeys.join(', ')}`
                };
            }
        }
    }

    // operations 검증
    if (expect.operations) {
        const matchedKeys = result.operations.map(o => o.key);
        const hasExpected = expect.operations.some(key => matchedKeys.includes(key));
        if (!hasExpected) {
            return {
                passed: false,
                reason: `Expected operations to include one of ${expect.operations.join(', ')}, got ${matchedKeys.join(', ')}`
            };
        }
    }

    // statistics 검증
    if (expect.statistics) {
        const matchedKeys = result.statistics.map(s => s.key);
        const hasExpected = expect.statistics.some(key => matchedKeys.includes(key));
        if (!hasExpected) {
            return {
                passed: false,
                reason: `Expected statistics to include one of ${expect.statistics.join(', ')}, got ${matchedKeys.join(', ')}`
            };
        }
    }

    // time_windows 검증
    if (expect.time_windows) {
        const matchedKeys = result.time_windows.map(t => t.key);
        const hasExpected = expect.time_windows.some(key => matchedKeys.includes(key));
        if (!hasExpected) {
            return {
                passed: false,
                reason: `Expected time_windows to include one of ${expect.time_windows.join(', ')}, got ${matchedKeys.join(', ')}`
            };
        }
    }

    // numbers 검증
    if (expect.numbers) {
        if (expect.numbers.min) {
            if (result.numbers.length < expect.numbers.min) {
                return {
                    passed: false,
                    reason: `Expected at least ${expect.numbers.min} numbers, got ${result.numbers.length}`
                };
            }
        }
        if (expect.numbers.includes !== undefined) {
            const values = result.numbers.map(n => n.value);
            if (!values.includes(expect.numbers.includes)) {
                return {
                    passed: false,
                    reason: `Expected numbers to include ${expect.numbers.includes}, got ${values.join(', ')}`
                };
            }
        }
    }

    // intent 검증
    if (expect.intent) {
        if (result.intent !== expect.intent) {
            return {
                passed: false,
                reason: `Expected intent "${expect.intent}", got "${result.intent}"`
            };
        }
    }

    return { passed: true, reason: 'All checks passed' };
}

/**
 * 개별 케이스 테스트 (디버깅용)
 */
window.testAutoNLPCase = (input) => {
    if (!window.autoNLP || !window.autoNLP.loaded) {
        console.error('❌ window.autoNLP not loaded');
        return null;
    }

    console.log(`\n=== Testing: "${input}" ===`);
    const startTime = performance.now();
    const result = window.autoNLP.match(input);
    const elapsed = Math.round(performance.now() - startTime);

    console.log('Result:', result);
    console.log(`Time: ${elapsed}ms`);

    return result;
};

console.log('[AutoNLP] Test suite loaded. Run runAutoNLPTests() to execute.');
