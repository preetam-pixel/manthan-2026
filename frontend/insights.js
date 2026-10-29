"use strict";

/* =========================================================
   Insights panels: Tax & Costs, Decision Journal, Strategy Evidence.
   Read-only: GET /tax, /journal, /evidence from the local bot server.
   All text from the server is escaped before it reaches the DOM.
========================================================= */

(function () {

    const POLL_MS = 3000;
    const charts = {};

    const $ = id => document.getElementById(id);

    const esc = value => String(value ?? "")
        .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

    const num = value => (typeof value === "number" && Number.isFinite(value)) ? value : null;

    const inr = (value, digits = 0) => {
        const n = num(value);
        if (n === null) return "—";
        return new Intl.NumberFormat("en-IN", {
            style: "currency", currency: "INR", maximumFractionDigits: digits, minimumFractionDigits: digits
        }).format(n);
    };

    const pct = (value, digits = 1, signed = true) => {
        const n = num(value);
        if (n === null) return "—";
        return `${signed && n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
    };

    const tone = value => {
        const n = num(value);
        return n === null || n === 0 ? "" : (n > 0 ? "pos" : "neg");
    };

    const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || undefined;

    async function getJSON(path) {
        const response = await fetch(path, { cache: "no-store", headers: { "Accept": "application/json" } });
        if (!response.ok) throw new Error(`${path}: ${response.status}`);
        return response.json();
    }

    function setText(id, text) {
        const el = $(id);
        if (el) el.textContent = text;
    }

    function drawChart(id, config) {
        const host = $(id);
        if (!host || typeof Chart === "undefined") return;
        if (charts[id]) charts[id].destroy();
        const canvas = document.createElement("canvas");
        host.replaceChildren(canvas);
        const grid = cssVar("--border-soft");
        const tick = cssVar("--subtle");
        config.options = Object.assign({
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: "index", intersect: false },
            plugins: { legend: { labels: { color: cssVar("--muted"), boxWidth: 12 } } },
            scales: {
                x: { ticks: { color: tick, maxTicksLimit: 8 }, grid: { color: grid } },
                y: { ticks: { color: tick }, grid: { color: grid } }
            }
        }, config.options || {});
        charts[id] = new Chart(canvas, config);
    }

    /* ---------------- Tax & Costs ---------------- */

    function renderTax(tax) {
        const years = Array.isArray(tax.years) ? tax.years : [];
        const stTax = years.reduce((s, y) => s + 0.15 * (num(y.taxable_st) ?? 0), 0);
        const ltTax = years.reduce((s, y) => s + 0.10 * (num(y.taxable_lt) ?? 0), 0);
        const lossesUsed = years.reduce((s, y) => s + (num(y.stcl) ?? 0) + (num(y.ltcl) ?? 0), 0);

        // Exchange total (as on the portal); our own tax book only covers this bot session.
        setText("cost-fees-paid", inr(num(tax.exchange_charges) ?? tax.fees_paid, 2));
        setText("cost-stcg", years.length ? inr(stTax) : "₹0");
        setText("cost-ltcg", years.length ? inr(ltTax) : "₹0");
        setText("cost-tax-loss-credits", years.length ? `${inr(lossesUsed)} offset` : "₹0");
        setText("tax-fy-label", tax.financial_year ? `Current: ${tax.financial_year}` : "—");
        setText("tax-note", tax.note || "");

        const mode = $("harvest-mode");
        if (mode) {
            mode.textContent = tax.auto_harvest ? "AUTO-HARVEST ON" : "MONITOR ONLY";
        }

        const body = $("tax-years-table")?.querySelector("tbody");
        if (body) {
            body.innerHTML = years.length ? years.map(y => `
                <tr>
                    <td>${esc(y.fy)}</td>
                    <td class="num pos">${inr(y.stcg)}</td>
                    <td class="num neg">${inr(y.stcl)}</td>
                    <td class="num pos">${inr(y.ltcg)}</td>
                    <td class="num">${inr(y.ltcg_exemption_used)}</td>
                    <td class="num">${inr((num(y.taxable_st) ?? 0) + (num(y.taxable_lt) ?? 0))}</td>
                    <td class="num"><strong>${inr(y.tax)}</strong></td>
                </tr>`).join("") +
                `<tr><td colspan="6"><strong>Total estimated tax</strong></td>
                     <td class="num"><strong>${inr(tax.total_tax_estimate)}</strong></td></tr>`
                : `<tr><td colspan="7" class="insight-empty">No realised trades yet</td></tr>`;
        }

        const list = $("harvest-list");
        if (list) {
            const items = Array.isArray(tax.harvest_candidates) ? tax.harvest_candidates : [];
            list.innerHTML = items.length ? items.map(c => `
                <li><strong>${esc(c.ticker)}</strong> · ${esc(c.quantity)} shares ·
                    unrealised loss <span class="neg num">${inr(c.unrealized_loss)}</span> ·
                    could save <span class="pos num">${inr(c.tax_saved)}</span> tax this year</li>`).join("")
                : `<li class="insight-empty">No losses worth harvesting right now</li>`;
        }
    }

    /* ---------------- Decision journal ---------------- */

    function renderJournal(journal) {
        const stats = journal.stats || {};
        setText("journal-stats",
            `${stats.decisions ?? 0} decisions · ${stats.filled ?? 0} filled · ` +
            `${stats.rejected ?? 0} rejected · ${stats.blocked ?? 0} blocked`);
        const body = $("journal-table")?.querySelector("tbody");
        if (!body) return;
        const rows = Array.isArray(journal.entries) ? journal.entries.slice(0, 60) : [];
        if (!rows.length) {
            body.innerHTML = `<tr><td colspan="11" class="insight-empty">No decisions yet</td></tr>`;
            return;
        }
        body.innerHTML = rows.map(e => {
            const gate = e.risk_approved === true ? `<span class="pos">approved</span>`
                : e.risk_approved === false ? `<span class="neg">${esc(e.risk_reason || "blocked")}</span>` : "—";
            const outcome = e.outcome
                ? `<span class="${e.outcome === "FILLED" ? "pos" : e.outcome === "REJECTED" ? "neg" : ""}">${esc(e.outcome)}${e.code ? " · " + esc(e.code) : ""}</span>`
                : `<span class="dim">not sent</span>`;
            const realised = num(e.realized_gain) === null ? "—"
                : `<span class="${tone(e.realized_gain)}">${inr(e.realized_gain)}</span> <span class="dim">${esc(e.tax_term || "")}</span>`;
            const news = num(e.news_score);
            return `
                <tr>
                    <td class="num">${esc(e.simulated_date || "—")}</td>
                    <td><strong>${esc(e.ticker)}</strong></td>
                    <td class="${e.action === "BUY" ? "pos" : "neg"}">${esc(e.action)}</td>
                    <td class="num">${esc(e.quantity)}</td>
                    <td class="num">${inr(e.fill_price ?? e.price, 2)}</td>
                    <td class="why">${esc(e.reason)}</td>
                    <td class="num ${news !== null && news <= -2 ? "neg" : ""}">${news === null ? "—" : (news > 0 ? "+" : "") + news}</td>
                    <td>${gate}</td>
                    <td>${outcome}</td>
                    <td class="num">${realised}</td>
                    <td class="num">${num(e.latency_s) === null ? "—" : (e.latency_s * 1000).toFixed(0) + " ms"}</td>
                </tr>`;
        }).join("");
    }

    /* ---------------- Strategy evidence ---------------- */

    const VERDICT = {
        sma_pro: ["chosen", "Chosen"],
        sma_band: ["baseline", "Baseline"],
    };

    function verdictFor(s) {
        if (VERDICT[s.id]) return VERDICT[s.id];
        return (num(s.return_pct) ?? 0) < 1 ? ["rejected", "Rejected"] : ["weak", "Too weak"];
    }

    function renderEvidence(ev) {
        if (!ev || !ev.dataset) {
            setText("evidence-dataset", "No evidence file yet (run scripts.build_evidence)");
            return;
        }
        const d = ev.dataset;
        setText("evidence-dataset",
            `${d.days} days · ${d.tickers.length} stocks · ${d.news_items.toLocaleString("en-IN")} headlines · ` +
            `${d.first_date} → ${d.last_date}`);
        if (ev.chosen?.why) setText("evidence-why", ev.chosen.why);

        const strategies = Array.isArray(ev.strategies) ? ev.strategies : [];
        const chosen = strategies.find(s => s.id === ev.chosen?.id) || strategies[0];
        const kpis = $("evidence-kpis");
        if (kpis && chosen) {
            const cards = [
                ["Return (500 days)", pct(chosen.return_pct), `buy & hold ${pct(d.buy_and_hold_pct)}`],
                ["After tax", pct(chosen.after_tax_return_pct), `tax est. ${inr(chosen.tax_estimate)}`],
                ["Max drawdown", pct(chosen.max_drawdown_pct, 1, false), "peak to trough"],
                ["Upside capture", pct((num(chosen.upside_capture) ?? 0) * 100, 0, false), "of rising quarters"],
                ["Downside capture", pct((num(chosen.downside_capture) ?? 0) * 100, 0, false), "of falling quarters"],
                ["Trades / fees", `${chosen.trades}`, inr(chosen.fees_paid)],
            ];
            kpis.innerHTML = cards.map(([label, value, sub]) =>
                `<div class="insight-kpi"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(sub)}</small></div>`
            ).join("");
        }

        const curves = ev.equity_curves || {};
        const series = curves.series || {};
        const palette = { sma_pro: cssVar("--green"), sma_band: cssVar("--blue"), buy_and_hold: cssVar("--subtle") };
        const labels = { sma_pro: "sma_pro (chosen)", sma_band: "sma_band (original)", buy_and_hold: "Buy & hold, equal weight" };
        drawChart("evidence-equity-chart", {
            type: "line",
            data: {
                labels: curves.dates || [],
                datasets: Object.keys(series).map(key => ({
                    label: labels[key] || key, data: series[key], borderColor: palette[key],
                    backgroundColor: palette[key], pointRadius: 0, borderWidth: key === "sma_pro" ? 2.5 : 1.5,
                    borderDash: key === "buy_and_hold" ? [5, 4] : []
                }))
            },
            options: {
                scales: {
                    x: { ticks: { color: cssVar("--subtle"), maxTicksLimit: 6 }, grid: { color: cssVar("--border-soft") } },
                    y: { ticks: { color: cssVar("--subtle"), callback: v => "₹" + (v / 100000).toFixed(1) + "L" },
                         grid: { color: cssVar("--border-soft") } }
                }
            }
        });

        const q = ev.quarters || {};
        const pick = id => strategies.find(s => s.id === id)?.quarters_pct || [];
        drawChart("evidence-quarters-chart", {
            type: "bar",
            data: {
                labels: (q.labels || []).map((l, i) => `Q${i + 1}`),
                datasets: [
                    { label: "Market (buy & hold)", data: q.market_pct || [], backgroundColor: cssVar("--subtle") },
                    { label: "sma_pro", data: pick("sma_pro"), backgroundColor: cssVar("--green") },
                    { label: "sma_band", data: pick("sma_band"), backgroundColor: cssVar("--blue") }
                ]
            },
            options: {
                scales: {
                    x: { ticks: { color: cssVar("--subtle") }, grid: { display: false } },
                    y: { ticks: { color: cssVar("--subtle"), callback: v => v + "%" }, grid: { color: cssVar("--border-soft") } }
                }
            }
        });

        const table = $("evidence-strategies")?.querySelector("tbody");
        if (table) {
            table.innerHTML = strategies.map(s => {
                const [cls, label] = verdictFor(s);
                return `
                    <tr>
                        <td><strong>${esc(s.id)}</strong></td>
                        <td class="num ${tone(s.return_pct)}">${pct(s.return_pct)}</td>
                        <td class="num ${tone(s.after_tax_return_pct)}">${pct(s.after_tax_return_pct)}</td>
                        <td class="num">${pct(s.max_drawdown_pct, 1, false)}</td>
                        <td class="num">${pct((num(s.upside_capture) ?? 0) * 100, 0, false)}</td>
                        <td class="num">${pct((num(s.downside_capture) ?? 0) * 100, 0, false)}</td>
                        <td class="num">${esc(s.trades)}</td>
                        <td class="num">${inr(s.fees_paid)}</td>
                        <td><span class="verdict ${cls}">${label}</span></td>
                    </tr>`;
            }).join("");
        }

        const grid = Array.isArray(ev.robustness_grid) ? ev.robustness_grid : [];
        const windows = [...new Set(grid.map(g => g.window))];
        const bands = [...new Set(grid.map(g => g.band))];
        const gridTable = $("evidence-grid");
        if (gridTable && grid.length) {
            gridTable.innerHTML = `<thead><tr><th>Window</th>${bands.map(b => `<th>band ${(b * 100).toFixed(1)}%</th>`).join("")}</tr></thead>
                <tbody>${windows.map(w => `<tr><th>${w} days</th>${bands.map(b => {
                    const g = grid.find(x => x.window === w && x.band === b);
                    const best = w === 8 && Math.abs(b - 0.015) < 1e-9;
                    return `<td class="num ${tone(g?.return_pct)} ${best ? "cell-best" : ""}">${pct(g?.return_pct)}
                            <span class="dim">(${pct(g?.max_drawdown_pct, 1, false)})</span></td>`;
                }).join("")}</tr>`).join("")}</tbody>`;
        }

        const news = ev.news || {};
        setText("evidence-news-sub",
            `${(news.headlines ?? 0).toLocaleString("en-IN")} headlines scored; correlation between a day's net sentiment and the ` +
            `next day's return: ${num(news.correlation_next_day) === null ? "—" : news.correlation_next_day.toFixed(3)}. ` +
            (news.conclusion || ""));
        const newsBody = $("evidence-news")?.querySelector("tbody");
        if (newsBody) {
            newsBody.innerHTML = (news.buckets || []).map(b => `
                <tr>
                    <td>${esc(b.bucket)}</td>
                    <td class="num">${esc(b.headlines)}</td>
                    <td class="num ${tone(b.next_day_return_pct)}">${pct(b.next_day_return_pct, 3)}</td>
                    <td class="num">${num(b.t_stat) === null ? "—" : b.t_stat.toFixed(1)}</td>
                </tr>`).join("");
        }

        const rejected = $("evidence-rejected");
        if (rejected) {
            rejected.innerHTML = (ev.rejected || []).map(r =>
                `<li><strong>${esc(r.idea)}</strong> — ${esc(r.why)}</li>`).join("");
        }
    }

    /* ---------------- polling ---------------- */

    async function refreshLive() {
        try { renderTax(await getJSON("/tax")); } catch (e) { /* bot offline: keep last values */ }
        try { renderJournal(await getJSON("/journal")); } catch (e) { /* bot offline */ }
    }

    async function start() {
        try { renderEvidence(await getJSON("/evidence")); } catch (e) { renderEvidence(null); }
        await refreshLive();
        setInterval(refreshLive, POLL_MS);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }

})();
