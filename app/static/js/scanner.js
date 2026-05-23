/**
 * 扫描器前端逻辑：收集筛选条件 → 调用API → 渲染结果。
 */
(function () {
    'use strict';

    // 收集所有筛选条件
    function collectParams() {
        const params = {};

        // 主力情况
        const hasForce = document.querySelector('input[name="hasForce"]:checked');
        if (hasForce) params.has_force = hasForce.value;

        const forceTypes = [];
        document.querySelectorAll('#g1 input[type="checkbox"]:checked').forEach(cb => {
            forceTypes.push(cb.value);
        });
        if (forceTypes.length) params.force_types = forceTypes;

        const ctrlMin = document.querySelector('input[data-range="control_min"]');
        const ctrlMax = document.querySelector('input[data-range="control_max"]');
        if (ctrlMin) params.control_min = parseFloat(ctrlMin.value);
        if (ctrlMax) params.control_max = parseFloat(ctrlMax.value);

        // 阶段
        const subPhases = [];
        document.querySelectorAll('#g2 input[type="checkbox"]:checked').forEach(cb => {
            subPhases.push(cb.value);
        });
        if (subPhases.length) params.sub_phases = subPhases;

        const dayMin = document.querySelector('input[data-range="day_min"]');
        const dayMax = document.querySelector('input[data-range="day_max"]');
        if (dayMin) params.days_in_phase_min = parseInt(dayMin.value);
        if (dayMax) params.days_in_phase_max = parseInt(dayMax.value);

        return params;
    }

    // 渲染结果表
    function renderResults(data) {
        const card = document.querySelector('.scanner-results .card-body');
        const countEl = document.getElementById('resultCount');

        if (!data.results || data.results.length === 0) {
            card.innerHTML = `
                <div class="text-center text-muted py-5">
                    <i class="bi bi-search" style="font-size: 3rem;"></i>
                    <div class="mt-3">没有匹配的股票</div>
                    <div class="small mt-2">尝试放宽筛选条件</div>
                </div>
            `;
            countEl.textContent = '(0只)';
            return;
        }

        countEl.textContent = `(${data.total} 只 · ${data.scan_time_ms}ms)`;

        let html = `
        <div class="table-responsive">
        <table class="table table-dark table-hover table-sm align-middle">
        <thead>
            <tr>
                <th>名称</th>
                <th>板块</th>
                <th class="text-end">收盘</th>
                <th class="text-end">涨跌</th>
                <th class="text-center">评分</th>
                <th>阶段</th>
                <th class="text-end">第N天</th>
                <th>机会</th>
                <th>主力</th>
                <th class="text-end">控盘</th>
                <th>资金</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody>
        `;

        for (const s of data.results) {
            const oppClass = s.opportunity_level?.startsWith('A级') ? 'opp-a' :
                             s.opportunity_level?.startsWith('B级') ? 'opp-b' :
                             s.opportunity_level?.startsWith('C级') ? 'opp-c' : '';
            const phaseClass = s.phase ? phaseToCss(s.phase) : 'phase-transition';
            const pctChg = parseFloat(s.pct_chg) || 0;
            const pctClass = pctChg > 0 ? 'up' : pctChg < 0 ? 'down' : 'flat';
            const pctSign = pctChg > 0 ? '+' : '';

            html += `
            <tr>
                <td>
                    <strong>${s.stock_name || s.ts_code}</strong>
                    <div class="text-muted small">${s.ts_code}</div>
                </td>
                <td><small>${s.industry || s.market || '-'}</small></td>
                <td class="text-mono text-end">${parseFloat(s.close).toFixed(2)}</td>
                <td class="text-mono text-end ${pctClass}">${pctSign}${pctChg.toFixed(2)}%</td>
                <td class="text-center"><strong>${s.score || 0}</strong></td>
                <td><span class="phase-badge ${phaseClass}">${s.sub_phase || s.phase || '-'}</span></td>
                <td class="text-mono text-end">${s.days_in_phase || '-'}</td>
                <td><span class="phase-badge ${oppClass}">${s.opportunity_level || '-'}</span></td>
                <td><small>${s.force_type || '-'}</small></td>
                <td class="text-mono text-end">${s.control_pct ? parseFloat(s.control_pct).toFixed(0) + '%' : '-'}</td>
                <td><small>${s.flow_direction || '-'}</small></td>
                <td>
                    <button class="btn btn-sm btn-outline-warning" data-action="watch" data-code="${s.ts_code}" data-name="${s.stock_name}">
                        <i class="bi bi-star"></i>
                    </button>
                </td>
            </tr>
            `;
        }

        html += '</tbody></table></div>';
        card.innerHTML = html;

        // 绑定加自选按钮
        card.querySelectorAll('button[data-action="watch"]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const code = btn.dataset.code;
                const name = btn.dataset.name;
                if (!confirm(`加入自选: ${name} (${code})？`)) return;
                try {
                    const r = await fetch('/api/watchlist', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ts_code: code, name: name }),
                    });
                    if (r.ok) {
                        btn.innerHTML = '<i class="bi bi-star-fill text-warning"></i>';
                        btn.disabled = true;
                    } else {
                        const err = await r.json();
                        alert('加入失败: ' + (err.detail || '未知错误'));
                    }
                } catch (e) {
                    alert('加入失败: ' + e.message);
                }
            });
        });
    }

    function phaseToCss(phase) {
        if (phase.includes('吸筹')) return 'phase-accumulation';
        if (phase.includes('启动')) return 'phase-startup';
        if (phase.includes('拉升')) return 'phase-rally';
        if (phase.includes('洗盘')) return 'phase-shakeout';
        if (phase.includes('派发')) return 'phase-distribution';
        if (phase.includes('杀跌')) return 'phase-decline';
        if (phase.includes('反转')) return 'phase-reversal';
        return 'phase-transition';
    }

    // 扫描按钮
    document.getElementById('btnScan')?.addEventListener('click', async () => {
        const params = collectParams();
        const card = document.querySelector('.scanner-results .card-body');
        card.innerHTML = '<div class="text-center py-5"><span class="spinner-border text-info"></span><div class="mt-3 text-muted">扫描中...</div></div>';

        try {
            const r = await fetch('/api/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(params),
            });
            const data = await r.json();
            if (data.message) {
                card.innerHTML = `<div class="alert alert-warning">${data.message}</div>`;
                return;
            }
            renderResults(data);
        } catch (e) {
            card.innerHTML = `<div class="alert alert-danger">扫描失败: ${e.message}</div>`;
        }
    });

    // 预设按钮
    document.querySelectorAll('.preset-card').forEach(card => {
        card.addEventListener('click', async () => {
            const name = card.dataset.preset;
            try {
                const r = await fetch(`/api/scan/presets/${name}`);
                const preset = await r.json();
                if (preset.error) {
                    alert(preset.error);
                    return;
                }

                // 用预设直接扫描
                const params = preset.params || {};
                const resultCard = document.querySelector('.scanner-results .card-body');
                resultCard.innerHTML = '<div class="text-center py-5"><span class="spinner-border text-info"></span><div class="mt-3 text-muted">使用预设"' + preset.name + '"扫描...</div></div>';

                const sr = await fetch('/api/scan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(params),
                });
                const data = await sr.json();
                if (data.message) {
                    resultCard.innerHTML = `<div class="alert alert-warning">${data.message}</div>`;
                    return;
                }
                renderResults(data);
            } catch (e) {
                alert('扫描失败: ' + e.message);
            }
        });
    });
})();
