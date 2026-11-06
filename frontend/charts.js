"use strict";

/* =========================================================
   Chart kit shared by app.js and insights.js.
   Light-theme defaults for Chart.js, charts that update in place
   (no rebuild and flicker on every poll), a hover crosshair,
   labelled reference lines and a few formatting helpers.
========================================================= */

(function () {

    const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

    const colors = () => ({
        c1: css("--chart-1"), c2: css("--chart-2"), c3: css("--chart-3"), neutral: css("--chart-neutral"),
        good: css("--chart-good"), bad: css("--chart-critical"), grid: css("--chart-grid"), axis: css("--chart-axis"),
        text: css("--text"), muted: css("--muted"), subtle: css("--subtle"), surface: css("--surface")
    });

    const alpha = (hex, a) => {
        const h = hex.replace("#", "");
        const n = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16);
        return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
    };

    const num = v => (typeof v === "number" && Number.isFinite(v)) ? v : null;

    /* ₹ in lakh / crore, the way Indian dashboards read */
    const inrShort = v => {
        const n = num(v);
        if (n === null) return "—";
        const a = Math.abs(n), s = n < 0 ? "−" : "";
        if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)}Cr`;
        if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(a >= 1e6 ? 1 : 2)}L`;
        if (a >= 1e3) return `${s}₹${(a / 1e3).toFixed(1)}k`;
        return `${s}₹${a.toFixed(0)}`;
    };

    const inr = (v, digits = 2) => {
        const n = num(v);
        return n === null ? "—" : new Intl.NumberFormat("en-IN", {
            style: "currency", currency: "INR", minimumFractionDigits: digits, maximumFractionDigits: digits
        }).format(n);
    };

    /* Vertical hairline that follows the hovered index */
    const crosshair = {
        id: "qCrosshair",
        afterDatasetsDraw(chart) {
            const active = chart.tooltip?.getActiveElements?.() || [];
            if (!active.length || chart.options.plugins?.qCrosshair === false) return;
            const x = active[0].element.x, { top, bottom } = chart.chartArea, ctx = chart.ctx;
            ctx.save();
            ctx.strokeStyle = colors().axis;
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
            ctx.restore();
        }
    };

    /* options.plugins.qRefLines.lines = [{ axis: "y"|"x", value, color, dash, label }] */
    const refLines = {
        id: "qRefLines",
        afterDatasetsDraw(chart, _args, opts) {
            const lines = opts?.lines || [];
            if (!lines.length) return;
            const { ctx, chartArea: area } = chart;
            ctx.save();
            lines.forEach(line => {
                const scale = chart.scales[line.axis === "x" ? "x" : "y"];
                if (!scale || num(line.value) === null) return;
                const p = scale.getPixelForValue(line.value);
                const vertical = line.axis === "x";
                if (vertical ? (p < area.left || p > area.right) : (p < area.top || p > area.bottom)) return;
                ctx.strokeStyle = line.color || colors().subtle;
                ctx.lineWidth = 1;
                ctx.setLineDash(line.dash || [4, 4]);
                ctx.beginPath();
                if (vertical) { ctx.moveTo(p, area.top); ctx.lineTo(p, area.bottom); }
                else { ctx.moveTo(area.left, p); ctx.lineTo(area.right, p); }
                ctx.stroke();
                if (line.label) {
                    ctx.setLineDash([]);
                    ctx.font = "600 10px Inter, system-ui, sans-serif";
                    ctx.fillStyle = line.color || colors().subtle;
                    ctx.textBaseline = "bottom";
                    if (vertical) { ctx.textAlign = "center"; ctx.fillText(line.label, p, area.top - 3); }
                    else { ctx.textAlign = "right"; ctx.fillText(line.label, area.right - 4, p - 3); }
                }
            });
            ctx.restore();
        }
    };

    function applyDefaults() {
        if (typeof Chart === "undefined" || applyDefaults.done) return;
        applyDefaults.done = true;
        const c = colors(), d = Chart.defaults;
        d.font.family = "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif";
        d.font.size = 11;
        d.color = c.subtle;
        d.animation = false;
        d.maintainAspectRatio = false;
        d.elements.line.borderWidth = 2;
        d.elements.line.tension = 0.25;
        d.elements.point.radius = 0;
        d.elements.point.hoverRadius = 4;
        d.elements.point.hoverBorderWidth = 2;
        d.elements.bar.borderRadius = 4;
        d.datasets.bar.maxBarThickness = 34;
        d.plugins.legend.labels.usePointStyle = true;
        d.plugins.legend.labels.boxWidth = 8;
        d.plugins.legend.labels.boxHeight = 8;
        d.plugins.legend.labels.color = c.muted;
        d.plugins.legend.labels.padding = 14;
        Object.assign(d.plugins.tooltip, {
            backgroundColor: "rgba(255, 255, 255, 0.98)", borderColor: "rgba(15, 23, 42, 0.12)", borderWidth: 1,
            titleColor: c.text, bodyColor: c.muted, footerColor: c.subtle, padding: 10, cornerRadius: 8,
            boxPadding: 4, usePointStyle: true, titleFont: { weight: "600" }, caretSize: 5
        });
        Chart.register(crosshair, refLines);
    }

    const isObj = v => v && typeof v === "object" && !Array.isArray(v) && typeof v !== "function";

    function merge(target, source) {
        Object.keys(source || {}).forEach(key => {
            const v = source[key];
            target[key] = isObj(v) && isObj(target[key]) ? merge({ ...target[key] }, v) : v;
        });
        return target;
    }

    /* Cartesian options with recessive grid and axes; pass overrides to merge in */
    function axes(overrides = {}) {
        const c = colors();
        const axis = { grid: { color: c.grid, drawTicks: false }, border: { color: c.axis },
                       ticks: { color: c.subtle, padding: 8, maxTicksLimit: 7 } };
        const labelledVertical = (overrides.plugins?.qRefLines?.lines || []).some(l => l.axis === "x" && l.label);
        const base = {
            responsive: true,
            interaction: { mode: "index", intersect: false },
            layout: { padding: { top: labelledVertical ? 16 : 4 } },        // room for reference-line labels
            plugins: { legend: { display: false } },
            scales: { x: merge({}, axis), y: merge({}, axis) }
        };
        if (overrides.indexAxis === "y") {                                 // every category gets its label
            base.scales.y.ticks = { ...base.scales.y.ticks, autoSkip: false, maxTicksLimit: undefined };
        }
        return merge(base, overrides);
    }

    /* Area fill that fades to transparent toward the baseline */
    const fade = (color, top = 0.22) => ctx => {
        const { chart } = ctx, area = chart.chartArea;
        if (!area) return alpha(color, top / 2);
        const g = chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
        g.addColorStop(0, alpha(color, top));
        g.addColorStop(1, alpha(color, 0));
        return g;
    };

    const instances = {};

    /* Create the chart once, then update its data/options in place on later calls */
    function upsert(id, config) {
        const host = document.getElementById(id);
        if (!host) return null;
        if (typeof Chart === "undefined") {
            host.innerHTML = `<div class="chart-placeholder">Chart library unavailable</div>`;
            return null;
        }
        applyDefaults();
        const existing = instances[id];
        const sameShape = existing && existing.config.type === config.type && existing.canvas.isConnected &&
            existing.data.datasets.length === config.data.datasets.length;
        if (sameShape) {
            existing.data.labels = config.data.labels;
            config.data.datasets.forEach((ds, i) => Object.assign(existing.data.datasets[i], ds));
            existing.options = config.options || {};
            existing.update("none");
            return existing;
        }
        if (existing) existing.destroy();
        const canvas = document.createElement("canvas");
        host.replaceChildren(canvas);
        instances[id] = new Chart(canvas, config);
        return instances[id];
    }

    function empty(id, message) {
        const host = document.getElementById(id);
        if (!host) return;
        if (instances[id]) { instances[id].destroy(); delete instances[id]; }
        host.innerHTML = `<div class="chart-placeholder">${message}</div>`;
    }

    window.QCharts = { colors, alpha, axes, merge, fade, upsert, empty, inr, inrShort, num };

})();
