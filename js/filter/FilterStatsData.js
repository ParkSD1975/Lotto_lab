/**
 * js/filter/FilterStatsData.js
 * 로또 6/45 조합의 이론적 확률 분포 데이터 (총 8,145,060 조합 기준)
 */

window.FilterStatsData = {
    // 1. 총합(Total Sum) 분포 데이터 (21 ~ 255)
    THEORETICAL_SUM: {
        "21": 1, "22": 1, "23": 2, "24": 3, "25": 5, "26": 7, "27": 11, "28": 14, "29": 20, "30": 26, "31": 35, "32": 44, "33": 58, "34": 71, "35": 90, "36": 109, "37": 136, "38": 163, "39": 200, "40": 239, "41": 288, "42": 340, "43": 406, "44": 475, "45": 560, "46": 651, "47": 760, "48": 876, "49": 1012, "50": 1159, "51": 1327, "52": 1507, "53": 1713, "54": 1930, "55": 2180, "56": 2437, "57": 2736, "58": 3037, "59": 3390, "60": 3738, "61": 4151, "62": 4547, "63": 5026, "64": 5471, "65": 6020, "66": 6512, "67": 7136, "68": 7673, "69": 8377, "70": 8955, "71": 9741, "72": 10355, "73": 11226, "74": 11870, "75": 12826, "76": 13493, "77": 14533, "78": 15215, "79": 16335, "80": 17022, "81": 18219, "82": 18900, "83": 20168, "84": 20831, "85": 22165, "86": 22797, "87": 24189, "88": 24778, "89": 26218, "90": 26752, "91": 28229, "92": 28695, "93": 30195, "94": 30582, "95": 32091, "96": 32391, "97": 33894, "98": 34101, "99": 35579, "100": 35691, "101": 37128, "102": 37142, "103": 38521, "104": 38435, "105": 39739, "106": 39556, "107": 40770, "108": 40487, "109": 41595, "110": 41217, "111": 42205, "112": 41743, "113": 42595, "114": 42060, "115": 42764, "116": 42169, "117": 42717, "118": 42071, "119": 42460, "120": 41775, "121": 41999, "122": 41285, "123": 41339, "124": 40612, "125": 40489, "126": 39757, "127": 39461, "128": 38734, "129": 38274, "130": 37559, "131": 36944, "132": 36248, "133": 35489, "134": 34819, "135": 33924, "136": 33285, "137": 32263, "138": 31661, "139": 30522, "140": 29964, "141": 28717, "142": 28206, "143": 26867, "144": 26405, "145": 24985, "146": 24576, "147": 23091, "148": 22736, "149": 21199, "150": 20899, "151": 19329, "152": 19084, "153": 17498, "154": 17306, "155": 15721, "156": 15580, "157": 14013, "158": 13917, "159": 12388, "160": 12332, "161": 10857, "162": 10834, "163": 9431, "164": 9431, "165": 8116, "166": 8133, "167": 6917, "168": 6945, "169": 5837, "170": 5871, "171": 4875, "172": 4911, "173": 4028, "174": 4062, "175": 3292, "176": 3320, "177": 2661, "178": 2682, "179": 2125, "180": 2139, "181": 1675, "182": 1683, "183": 1303, "184": 1305, "185": 1000, "186": 997, "187": 756, "188": 750, "189": 562, "190": 554, "191": 411, "192": 401, "193": 295, "194": 285, "195": 208, "196": 199, "197": 144, "198": 136, "199": 98, "200": 91, "201": 65, "202": 60, "203": 42, "204": 38, "205": 26, "206": 24, "207": 16, "208": 14, "209": 9, "210": 8, "211": 5, "212": 4, "213": 3, "214": 2, "215": 1, "216": 1, "217": 0, "218": 0, "219": 0, "220": 0, "221": 0, "222": 0, "223": 0, "224": 0, "225": 0, "226": 0, "227": 0, "228": 0, "229": 0, "230": 0, "231": 0, "232": 0, "233": 0, "234": 0, "235": 0, "236": 0, "237": 0, "238": 0, "239": 0, "240": 0, "241": 0, "242": 0, "243": 0, "244": 0, "245": 0, "246": 0, "247": 0, "248": 0, "249": 0, "250": 0, "251": 0, "252": 0, "253": 0, "254": 0, "255": 0
    },

    // 2. 끝수합(Tail Sum) 분포 데이터 (0 ~ 54)
    THEORETICAL_TAIL_SUM: {},

    // 3. 이산 필터 분포 (홀짝, 저고, 소수, 합성수)
    // Values are counts of combinations having exactly K of the specific property
    COUNTS: {
        odd_even: [74613, 605682, 1850695, 2727340, 2045505, 740278, 100947],
        high_low: [100947, 740278, 2045505, 2727340, 1850695, 605682, 74613],
        prime: [736281, 2378754, 2863315, 1636180, 465465, 62062, 3003],
        composite: [5005, 90090, 593775, 1847300, 2877525, 2137590, 593775],
        square: [3262623, 3454542, 1233765, 182780, 11115, 234, 1],
        triangular: [1947792, 3392928, 2120580, 599760, 79380, 4536, 84],
        twin: [4496388, 2997592, 607620, 42640, 820, 0, 0]
    },

    // 4. AC값 분포 (0 ~ 10)
    THEORETICAL_AC: {
        "0": 0.00, "1": 0.01, "2": 0.04, "3": 0.16, "4": 0.60, "5": 2.11, "6": 6.20, "7": 15.36, "8": 27.68, "9": 31.83, "10": 16.01
    },

    init() {
        this.calcTailSum();
    },

    calcTailSum() {
        const dp = Array(7).fill(0).map(() => Array(60).fill(0));
        dp[0][0] = 1;
        for (let i = 1; i <= 45; i++) {
            const digit = i % 10;
            for (let c = 6; c >= 1; c--) {
                for (let s = 54; s >= digit; s--) {
                    dp[c][s] += dp[c - 1][s - digit];
                }
            }
        }
        for (let s = 0; s <= 54; s++) {
            if (dp[6][s] > 0) this.THEORETICAL_TAIL_SUM[s] = dp[6][s];
        }
    },

    // 활성화된 필터 설정을 받아 현재 남은 조합 비중(0.0 ~ 1.0)을 계산
    calculateProbability(filterKey, settings) {
        if (!settings) return 1.0;

        const s = settings; // settings is actually the nested settings object passed from dashboard
        const discreteValues = s.selectedRatios || s.selectedCounts || s.activeCounts || s.selectedValues || [];

        switch (filterKey) {
            case 'total_sum':
                return this._getRangeProb(this.THEORETICAL_SUM, settings.min, settings.max, settings.excludedSums);
            case 'last_digit_sum':
                return this._getRangeProb(this.THEORETICAL_TAIL_SUM, settings.min, settings.max, settings.excludedSums);
            case 'odd_even_pattern':
                return this._getDiscreteProb(this.COUNTS.odd_even, discreteValues);
            case 'high_low_pattern':
                return this._getDiscreteProb(this.COUNTS.high_low, discreteValues);
            case 'prime_number_patterns':
                return this._getDiscreteProb(this.COUNTS.prime, discreteValues);
            case 'composite_count':
                return this._getDiscreteProb(this.COUNTS.composite, discreteValues);
            case 'square_number_patterns':
                return this._getDiscreteProb(this.COUNTS.square, discreteValues);
            case 'triangular_number_patterns':
                return this._getDiscreteProb(this.COUNTS.triangular, discreteValues);
            case 'twin_number_patterns':
                return this._getDiscreteProb(this.COUNTS.twin, discreteValues);
            case 'number_range_patterns':
                return this._getNumberRangeProb(s.ranges);
            case 'ac_value':
                return this._getACProb(s.min, s.max);
            default:
                return 0.65; // Fallback for complex/unknown filters
        }
    },

    _getRangeProb(dataObj, min, max, excluded) {
        let count = 0;
        const total = 8145060;
        const start = min || 0;
        const end = max || 999;
        const exclSet = new Set(excluded || []);

        for (let v in dataObj) {
            const val = parseInt(v);
            if (val >= start && val <= end && !exclSet.has(val)) {
                count += dataObj[v];
            }
        }
        return count / total;
    },

    _getDiscreteProb(countsArr, selectedValues) {
        if (!selectedValues || selectedValues.length === 0) return 1.0;
        let count = 0;
        const total = 8145060;
        selectedValues.forEach(val => {
            let idx = val;
            if (typeof val === 'string' && val.includes(':')) {
                // "1:5" -> index 1
                idx = parseInt(val.split(':')[0]);
            } else {
                idx = parseInt(val);
            }
            if (!isNaN(idx) && countsArr[idx] !== undefined) {
                count += countsArr[idx];
            }
        });
        return count / total;
    },

    _getACProb(min, max) {
        let prob = 0;
        const start = min || 0;
        const end = max || 10;
        for (let v in this.THEORETICAL_AC) {
            const val = parseInt(v);
            if (val >= start && val <= end) {
                prob += this.THEORETICAL_AC[v];
            }
        }
        return prob / 100; // Percent based
    },

    _getNumberRangeProb(ranges) {
        if (!ranges) return 1.0;
        let prob = 1.0;
        let active = false;

        const counts = { '1_10': 10, '11_20': 10, '21_30': 10, '31_40': 10, '41_45': 5 };

        Object.keys(counts).forEach(type => {
            const f = ranges[type];
            if (f) {
                if (f.max < 6) {
                    active = true;
                    if (f.max === 0) {
                        prob *= Math.pow((45 - counts[type]) / 45, 6);
                    } else if (f.max <= 2) {
                        prob *= 0.55;
                    } else if (f.max <= 4) {
                        prob *= 0.85;
                    }
                }
                if (f.min > 0) {
                    active = true;
                    if (f.min >= 2) prob *= 0.3;
                    else prob *= 0.7;
                }
            }
        });

        const ent = ranges['entropy'];
        if (ent) {
            if (parseFloat(ent.min) > 0.5) { prob *= 0.9; active = true; }
            if (parseFloat(ent.max) < 2.5) { prob *= 0.8; active = true; }
        }

        return active ? prob : 1.0;
    }
};

window.FilterStatsData.init();
