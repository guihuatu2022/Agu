/**
 * 全局应用脚本。
 * 健康检查、通用工具函数。
 */

(function () {
    'use strict';

    // 顶部状态栏：数据库连接状态
    async function checkHealth() {
        const dbBadge = document.getElementById('dbStatus');
        const dateBadge = document.getElementById('dataDate');
        if (!dbBadge) return;

        try {
            const r = await fetch('/api/health');
            const data = await r.json();

            if (data.database && data.database.ok) {
                dbBadge.className = 'badge text-bg-success';
                dbBadge.innerHTML = '<i class="bi bi-database-check"></i> MySQL OK';
                dbBadge.title = '数据库版本: ' + data.database.info;
            } else {
                dbBadge.className = 'badge text-bg-warning';
                dbBadge.innerHTML = '<i class="bi bi-database-x"></i> MySQL 未连接';
                dbBadge.title = data.database ? data.database.info : '未知';
            }
        } catch (e) {
            dbBadge.className = 'badge text-bg-danger';
            dbBadge.innerHTML = '<i class="bi bi-x-circle"></i> 服务异常';
        }

        if (dateBadge) {
            const today = new Date();
            dateBadge.textContent = today.toLocaleDateString('zh-CN');
        }
    }

    // 数字格式化工具
    window.fmtPct = function (v, decimals = 2) {
        if (v == null || isNaN(v)) return '-';
        const sign = v > 0 ? '+' : '';
        const cls = v > 0 ? 'up' : (v < 0 ? 'down' : 'flat');
        return `<span class="${cls}">${sign}${v.toFixed(decimals)}%</span>`;
    };

    window.fmtPrice = function (v, decimals = 2) {
        if (v == null || isNaN(v)) return '-';
        return v.toFixed(decimals);
    };

    window.fmtAmount = function (v) {
        // 万元为单位转亿
        if (v == null || isNaN(v)) return '-';
        const yi = v / 10000;
        return yi.toFixed(2) + '亿';
    };

    // 启动
    document.addEventListener('DOMContentLoaded', () => {
        checkHealth();
        // 每30秒刷新一次健康检查
        setInterval(checkHealth, 30000);
    });
})();
