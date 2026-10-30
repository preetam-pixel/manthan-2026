"use strict";

/* =========================================================
   Insights panels: Tax & Costs, Trade Journal, Strategy Evidence.
   Read-only: GET /tax, /journal, /evidence from the local bot server
   (prices for the journal come from app.js's state.series).
   All text from the server is escaped before it reaches the DOM.
========================================================= */

(function () {

    const POLL_MS = 3000;
    const Q = window.QCharts;

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

    const signed = (value, digits = 0) => {
        const n = num(value);
        return n === null ? "—" : `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(digits)}`;
    };

    const tone = value => {
        const n = num(value);
        return n === null || n === 0 ? "" : (n > 0 ? "pos" : "neg");
    };

    async function getJSON(path) {
        const response = await fetch(path, { cache: "no-store", headers: { "Accept": "application/json" } });
        if (!response.ok) throw new Error(`${path}: ${response.status}`);
        return response.json();
    }

    function setText(id, text) {
        const el = $(id);
        if (el) el.textContent = text;
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

    /* ---------------- Trade journal ---------------- */

    const journal = { entries: [], stats: {}, filter: "ALL", ticker: "ALL", selected: null, drawn: "" };

    const keyOf = e => `${e.time}|${e.ticker}|${e.action}`;
    const wasSent = e => Boolean(e.outcome);
    const kindOf = e => wasSent(e) ? e.action : "SKIPPED";
    const isNewsVeto = e => /^news veto/.test(e.risk_reason || "");
    const isHarvest = e => /tax-loss/.test(e.reason || "");

    /* "close above SMA8 by 1.5% (+5.49%)" -> { window: 8, band: 1.5, gap: 5.49 } */
    function triggerOf(e) {
        const m = /SMA(\d+) by ([\d.]+)% \(([+-]?[\d.]+)%\)/.exec(e.reason || "");
        return m ? { window: Number(m[1]), band: Number(m[2]), gap: Number(m[3]) } : null;
    }

    function categoryOf(e) {
        if (!wasSent(e)) return isNewsVeto(e) ? "Skipped: bad news" : "Blocked by risk gate";
        if (e.outcome === "REJECTED") return "Rejected by exchange";
        if (e.outcome !== "FILLED") return "Unclear exchange answer";
        if (isHarvest(e)) return "Tax-loss harvest";
        if (triggerOf(e)) return e.action === "BUY" ? "Breakout buy" : "Exit below band";
        return e.action === "BUY" ? "Other buy" : "Other sell";
    }

    function shortWhy(e) {
        const t = triggerOf(e);
        if (!wasSent(e)) return isNewsVeto(e) ? `News veto · score ${signed(e.news_score)}` : `Blocked · ${e.risk_reason || "risk gate"}`;
        if (isHarvest(e)) return "Tax-loss harvest";
        if (t) return `${e.action === "BUY" ? "Breakout" : "Exit"} · ${t.gap > 0 ? "+" : ""}${t.gap.toFixed(2)}% vs SMA${t.window}`;
        return e.reason || "—";
    }

    const seriesOf = ticker => (typeof state !== "undefined" && state.series?.[ticker]) || null;

    /* Index of the decision day in the live price window (latest occurrence: the sandbox replays dates) */
    function decisionIndex(points, date) {
        for (let i = points.length - 1; i >= 0; i--) if (points[i].date === date) return i;
        return -1;
    }

    function renderJournalKpis(entries, stats) {
        const box = $("journal-kpis");
        if (!box) return;
        const closed = entries.filter(e => num(e.realized_gain) !== null);
        const wins = closed.filter(e => e.realized_gain > 0).length;
        const realised = closed.reduce((s, e) => s + e.realized_gain, 0);
        const vetoes = entries.filter(isNewsVeto).length;
        const latencies = entries.map(e => num(e.latency_s)).filter(v => v !== null);
        const avgLatency = latencies.length ? latencies.reduce((a, b) => a + b, 0) / latencies.length : null;
        const cards = [
            ["Decisions (session)", `${stats.decisions ?? entries.length}`, `${stats.filled ?? 0} filled · ${stats.blocked ?? 0} not sent`],
            ["Closed trades", `${closed.length}`, `in the last ${entries.length} decisions`],
            ["Win rate", closed.length ? `${Math.round(wins / closed.length * 100)}%` : "—", `${wins} of ${closed.length} sells in profit`],
            ["Realised P&L", inr(realised), "from those sells, after charges", tone(realised)],
            ["Buys skipped on news", `${vetoes}`, "headlines scored −2 or worse"],
            ["Avg decision time", avgLatency === null ? "—" : `${Math.round(avgLatency * 1000)} ms`, "prices → order sent"]
        ];
        box.innerHTML = cards.map(([label, value, sub, cls]) =>
            `<div class="insight-kpi"><span>${esc(label)}</span><strong class="${cls || ""}">${esc(value)}</strong><small>${esc(sub)}</small></div>`
        ).join("");
    }

    function renderJournalCharts(entries) {
        const c = Q.colors();
        const closed = entries.filter(e => num(e.realized_gain) !== null).reverse();
        const total = closed.reduce((s, e) => s + e.realized_gain, 0);
        setText("journal-pnl-chip", closed.length ? `Net ${inr(total)}` : "—");
        if (!closed.length) Q.empty("journal-pnl-chart", "No closed trades in the recent decisions");
        else Q.upsert("journal-pnl-chart", {
            type: "bar",
            data: {
                labels: closed.map(e => `${e.ticker} · ${e.simulated_date}`),
                datasets: [{
                    label: "Realised", data: closed.map(e => e.realized_gain),
                    backgroundColor: closed.map(e => e.realized_gain >= 0 ? c.good : c.bad),
                    borderRadius: 3, barPercentage: 0.8, categoryPercentage: 0.9
                }]
            },
            options: Q.axes({
                scales: {
                    x: { display: false },
                    y: { ticks: { callback: v => Q.inrShort(v) } }
                },
                plugins: {
                    qRefLines: { lines: [{ axis: "y", value: 0, color: c.axis, dash: [] }] },
                    tooltip: {
                        callbacks: {
                            label: item => `${item.raw >= 0 ? "Gain" : "Loss"} ${inr(item.raw)}`,
                            afterLabel: item => {
                                const e = closed[item.dataIndex];
                                return `${e.quantity} shares @ ${inr(e.fill_price ?? e.price, 2)} · ${e.tax_term === "LT" ? "long-term" : "short-term"}`;
                            }
                        }
                    }
                }
            })
        });

        const counts = {};
        entries.forEach(e => { const k = categoryOf(e); counts[k] = (counts[k] || 0) + 1; });
        const labels = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
        if (!labels.length) return Q.empty("journal-reasons-chart", "No decisions yet");
        Q.upsert("journal-reasons-chart", {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: "Decisions", data: labels.map(k => counts[k]), backgroundColor: c.c1,
                    borderRadius: 4, barPercentage: 0.62, categoryPercentage: 0.86
                }]
            },
            options: Q.axes({
                indexAxis: "y",
                interaction: { mode: "nearest", axis: "y", intersect: false },
                scales: {
                    x: { beginAtZero: true, ticks: { precision: 0 } },
                    y: { grid: { display: false }, ticks: { color: c.text } }
                },
                plugins: {
                    qCrosshair: false,
                    tooltip: { callbacks: { label: item => `${item.raw} of ${entries.length} decisions` } }
                }
            })
        });
    }

    function visibleEntries() {
        return journal.entries.filter(e =>
            (journal.filter === "ALL" || kindOf(e) === journal.filter) &&
            (journal.ticker === "ALL" || e.ticker === journal.ticker));
    }

    function renderJournalList() {
        const list = $("journal-list");
        if (!list) return;
        const rows = visibleEntries();
        if (!rows.some(e => keyOf(e) === journal.selected)) journal.selected = rows[0] ? keyOf(rows[0]) : null;
        const scroll = list.scrollTop;
        list.innerHTML = rows.length ? rows.map(e => {
            const kind = kindOf(e);
            const gain = num(e.realized_gain);
            const right = gain !== null ? `<span class="num ${tone(gain)}">${inr(gain)}</span>`
                : kind === "SKIPPED" ? `<span class="pill pill-muted">not sent</span>`
                : `<span class="num dim">${inr((e.quantity ?? 0) * (e.fill_price ?? e.price ?? 0))}</span>`;
            return `
                <li>
                    <button type="button" class="journal-row ${keyOf(e) === journal.selected ? "selected" : ""}" data-key="${esc(keyOf(e))}">
                        <span class="badge badge-${kind.toLowerCase()}">${kind === "SKIPPED" ? "SKIP" : kind}</span>
                        <span class="journal-row-main">
                            <strong>${esc(e.ticker)}</strong> <span class="dim">${esc(e.simulated_date || "")}</span>
                            <small>${esc(shortWhy(e))}</small>
                        </span>
                        <span class="journal-row-side">${right}</span>
                    </button>
                </li>`;
        }).join("") : `<li class="insight-empty">No decisions match this filter</li>`;
        list.scrollTop = scroll;
    }

    function step(state, title, text) {
        const icon = { ok: "✓", stop: "✕", info: "i", na: "–" }[state];
        return `<li class="jd-step ${state}"><span class="jd-icon" aria-hidden="true">${icon}</span>
                <div><strong>${esc(title)}</strong><p>${text}</p></div></li>`;
    }

    function explain(e, points) {
        const t = triggerOf(e);
        const price = num(e.fill_price) ?? num(e.price);
        const qty = num(e.quantity) ?? 0;
        const steps = [];

        if (isHarvest(e)) {
            steps.push(step("info", "Signal: tax-loss harvest", `${esc(e.reason)}. Selling a losing lot before the financial year
                ends books the loss so it offsets this year's taxable gains, and the tax saved beats the ₹55.34 round-trip cost.`));
        } else if (t) {
            const sma = price / (1 + t.gap / 100);
            steps.push(e.action === "BUY"
                ? step("ok", "Signal: breakout above the band", `The close <b>${inr(price, 2)}</b> finished <b>${t.gap.toFixed(2)}%</b>
                    above its ${t.window}-day average (${inr(sma, 2)}), past the <b>+${t.band}%</b> buy line. The band rule reads
                    that as the start of an up-move.`)
                : step("ok", "Signal: close fell below the band", `The close <b>${inr(price, 2)}</b> fell <b>${Math.abs(t.gap).toFixed(2)}%</b>
                    below its ${t.window}-day average (${inr(sma, 2)}), past the <b>−${t.band}%</b> exit line, so the rule sells
                    the whole position before the slide goes further.`));
        } else {
            steps.push(step("info", "Signal", esc(e.reason || "—")));
        }

        if (qty && price) {
            steps.push(step("info", "Size", e.action === "BUY"
                ? `${qty.toLocaleString("en-IN")} shares × ${inr(price, 2)} = <b>${inr(qty * price)}</b>, the strategy's fixed ticket per buy.`
                : `All ${qty.toLocaleString("en-IN")} shares held, worth <b>${inr(qty * price)}</b>.`));
        }

        const score = num(e.news_score);
        if (e.action === "SELL") {
            steps.push(step("na", "News check", "Sells never wait for headlines: getting out fast matters more."));
        } else if (isNewsVeto(e)) {
            steps.push(step("stop", "News check: vetoed", `Headlines for ${esc(e.ticker)} over the last 3 days scored <b>${signed(score)}</b>.
                Buys wait 0.5 s for the day's news and are skipped at −2 or worse: in testing, breakouts on bad news mostly failed.`));
        } else if (score !== null) {
            steps.push(step("ok", "News check: passed", `Headlines over the last 3 days scored <b>${signed(score)}</b>, above the −2 veto line.`));
        }

        if (e.risk_approved === true) {
            steps.push(step("ok", "Risk gate: approved", "Fresh prices, portfolio in sync, inside the per-stock cap, enough cash, and no other order for this stock today."));
        } else if (e.risk_approved === false && !isNewsVeto(e)) {
            steps.push(step("stop", "Risk gate: blocked", esc(e.risk_reason || "blocked")));
        }

        if (e.outcome === "FILLED") {
            const ms = num(e.latency_s) === null ? "" : ` <b>${Math.round(e.latency_s * 1000)} ms</b> after the prices arrived (window ~3 s)`;
            steps.push(step("ok", "Exchange: filled", `Filled at <b>${inr(price, 2)}</b>${ms}. Charges ${inr(e.fees, 2)}.`));
        } else if (e.outcome === "REJECTED") {
            steps.push(step("stop", "Exchange: rejected", esc(e.code || "rejected")));
        } else if (e.outcome) {
            steps.push(step("info", `Exchange: ${esc(e.outcome.toLowerCase())}`, "The answer was unclear; the bot re-read the portfolio before trading this stock again."));
        } else {
            steps.push(step("na", "Exchange", "No order was sent."));
        }

        const last = points.at(-1);
        const now = num(last?.close);
        const move = now !== null && price ? (now / price - 1) * 100 : null;
        const gain = num(e.realized_gain);
        if (gain !== null) {
            steps.push(step(gain >= 0 ? "ok" : "stop", gain >= 0 ? "Result: profit booked" : "Result: loss booked",
                `Realised <b class="${tone(gain)}">${inr(gain)}</b> (${e.tax_term === "LT" ? "long-term" : "short-term"}, after charges).` +
                (move === null ? "" : ` The price is now ${inr(now, 2)}, ${pct(move, 2)} since the sale.`)));
        } else if (move !== null && e.action === "BUY") {
            const pnl = qty * (now - price);
            steps.push(wasSent(e)
                ? step("info", "Since then", `${esc(e.ticker)} is at ${inr(now, 2)} (${esc(last.date)}): <b class="${tone(move)}">${pct(move, 2)}</b>,
                    ${inr(pnl)} on these shares.`)
                : step(move <= 0 ? "ok" : "info", "What the skip meant", `Had it bought at ${inr(price, 2)}, these shares would now be
                    <b class="${tone(move)}">${pct(move, 2)}</b> (${inr(pnl)}): the veto ${move <= 0 ? "avoided a loss" : "missed this gain"}.`));
        }
        return steps.join("");
    }

    function renderJournalDetail() {
        const box = $("journal-detail");
        if (!box) return;
        const e = journal.entries.find(x => keyOf(x) === journal.selected);
        if (!e) {
            Q.empty("journal-trade-chart", "");
            box.innerHTML = `<div class="insight-empty">Select a decision to see why it was taken</div>`;
            journal.drawn = "";
            return;
        }
        const series = seriesOf(e.ticker);
        const all = Array.isArray(series?.points) ? series.points : [];
        const i = decisionIndex(all, e.simulated_date);
        const kind = kindOf(e);
        const price = num(e.fill_price) ?? num(e.price);
        const outcome = e.outcome === "FILLED" ? ["pill-good", "Filled"] : e.outcome ? ["pill-bad", e.outcome] : ["pill-muted", "Not sent"];

        // Rebuild the frame only when the selection changes; the chart and steps refresh in place.
        if (journal.drawn !== journal.selected) {
            box.innerHTML = `
                <header class="jd-head">
                    <span class="badge badge-${kind.toLowerCase()}">${kind === "SKIPPED" ? "SKIPPED BUY" : kind}</span>
                    <h3>${esc(e.ticker)}</h3>
                    <span class="pill ${outcome[0]}">${esc(outcome[1])}</span>
                    <span class="jd-meta">${esc((e.quantity ?? 0).toLocaleString("en-IN"))} shares · ${inr(price, 2)} ·
                        ${inr((e.quantity ?? 0) * (price ?? 0))} · simulated ${esc(e.simulated_date)}</span>
                </header>
                <div class="jd-chart-wrap">
                    <div id="journal-trade-chart" class="chart" role="img" aria-label="Price around the decision"></div>
                    <div class="jd-chart-note" id="journal-trade-note"></div>
                </div>
                <ol class="jd-steps" id="journal-steps"></ol>`;
            journal.drawn = journal.selected;
        }

        const steps = $("journal-steps");
        if (steps) steps.innerHTML = explain(e, all);

        if (i < 0) {
            Q.empty("journal-trade-chart", "This day has scrolled out of the live price window");
            setText("journal-trade-note", "");
            return;
        }
        const points = all.slice(Math.max(0, i - 30), Math.min(all.length, i + 16));
        const at = points.indexOf(all[i]);
        const c = Q.colors();
        const fills = Array.isArray(series.markers) ? series.markers : [];
        const fillAt = action => points.map((p, j) =>
            j === at ? null : (fills.find(m => m.action === action && m.date === p.date)?.price ?? null));
        const markColor = kind === "BUY" ? c.good : kind === "SELL" ? c.bad : c.neutral;
        setText("journal-trade-note", `${points.length} days around the decision · the large marker is this ${kind === "SKIPPED" ? "skipped buy" : kind.toLowerCase()}`);

        Q.upsert("journal-trade-chart", {
            type: "line",
            data: {
                labels: points.map(p => p.date),
                datasets: [
                    { label: "Upper band", data: points.map(p => p.upper ?? null), borderColor: Q.alpha(c.neutral, 0.7), borderWidth: 1,
                      borderDash: [4, 4], backgroundColor: Q.alpha(c.c1, 0.07), fill: "+1", order: 5 },
                    { label: "Lower band", data: points.map(p => p.lower ?? null), borderColor: Q.alpha(c.neutral, 0.7), borderWidth: 1,
                      borderDash: [4, 4], fill: false, order: 5 },
                    { label: "SMA8", data: points.map(p => p.sma8 ?? null), borderColor: c.c2, borderWidth: 2, order: 3 },
                    { label: "Close", data: points.map(p => p.close ?? null), borderColor: c.c1, borderWidth: 2.25, order: 2 },
                    { label: "Other buys", data: fillAt("BUY"), showLine: false, pointStyle: "triangle", pointRadius: 5,
                      backgroundColor: Q.alpha(c.good, 0.55), borderColor: c.surface, borderWidth: 1, order: 1 },
                    { label: "Other sells", data: fillAt("SELL"), showLine: false, pointStyle: "triangle", rotation: 180, pointRadius: 5,
                      backgroundColor: Q.alpha(c.bad, 0.55), borderColor: c.surface, borderWidth: 1, order: 1 },
                    { label: "This decision", data: points.map((p, j) => j === at ? (price ?? p.close) : null), showLine: false,
                      pointStyle: kind === "SKIPPED" ? "crossRot" : "triangle", rotation: kind === "SELL" ? 180 : 0,
                      pointRadius: 11, pointHoverRadius: 12, borderWidth: kind === "SKIPPED" ? 3 : 2,
                      backgroundColor: markColor, borderColor: kind === "SKIPPED" ? markColor : c.surface, order: 0 }
                ]
            },
            options: Q.axes({
                scales: {
                    x: { grid: { display: false }, ticks: { maxTicksLimit: 6 } },
                    y: { beginAtZero: false, grace: "6%", position: "right", ticks: { callback: v => "₹" + v } }
                },
                plugins: {
                    legend: { display: true, position: "bottom", labels: { filter: item => !/band/.test(item.text) } },
                    qRefLines: { lines: [{ axis: "x", value: at, color: markColor, label: "decision" }] },
                    tooltip: {
                        filter: item => item.raw !== null && !/band/.test(item.dataset.label),
                        callbacks: { label: item => `${item.dataset.label}: ${inr(item.raw, 2)}` }
                    }
                }
            })
        });
    }

    function renderJournal(data) {
        const entries = Array.isArray(data.entries) ? data.entries : [];
        const stats = data.stats || {};
        setText("journal-stats",
            `${stats.decisions ?? 0} decisions · ${stats.filled ?? 0} filled · ` +
            `${stats.rejected ?? 0} rejected · ${stats.blocked ?? 0} not sent`);
        journal.entries = entries;
        journal.stats = stats;

        const select = $("journal-ticker");
        if (select) {
            const tickers = [...new Set(entries.map(e => e.ticker))].sort();
            const options = ["ALL", ...tickers];
            if ([...select.options].map(o => o.value).join() !== options.join()) {
                select.innerHTML = options.map(t => `<option value="${esc(t)}">${t === "ALL" ? "All stocks" : esc(t)}</option>`).join("");
                select.value = options.includes(journal.ticker) ? journal.ticker : "ALL";
            }
        }

        renderJournalKpis(entries, stats);
        if (document.getElementById("page-journal")?.hidden) return;     // charts need a visible page to size
        renderJournalCharts(entries);
        renderJournalList();
        renderJournalDetail();
    }

    function initJournal() {
        document.querySelectorAll("[data-journal-filter]").forEach(button => {
            button.addEventListener("click", () => {
                journal.filter = button.dataset.journalFilter;
                document.querySelectorAll("[data-journal-filter]").forEach(b => b.classList.toggle("active", b === button));
                renderJournalList();
                renderJournalDetail();
            });
        });
        $("journal-ticker")?.addEventListener("change", event => {
            journal.ticker = event.target.value;
            renderJournalList();
            renderJournalDetail();
        });
        $("journal-list")?.addEventListener("click", event => {
            const row = event.target.closest(".journal-row");
            if (!row) return;
            journal.selected = row.dataset.key;
            renderJournalList();
            renderJournalDetail();
        });
        window.addEventListener("hashchange", () => {
            if (location.hash === "#journal") setTimeout(() => renderJournal({ entries: journal.entries, stats: journal.stats }), 0);
        });
    }

    /* ---------------- Strategy evidence ---------------- */

    const VERDICT = {
        sma_news: ["chosen", "Chosen"],
        sma_pro: ["baseline", "Previous"],
        sma_band: ["baseline", "Original"],
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

        const c = Q.colors();
        const curves = ev.equity_curves || {};
        const series = curves.series || {};
        const palette = { sma_news: c.c1, sma_pro: c.c2, sma_band: c.c3, buy_and_hold: c.neutral };
        const labels = { sma_news: "sma_news (chosen)", sma_pro: "sma_pro (no news)", sma_band: "sma_band (original)",
                         buy_and_hold: "Buy & hold, equal weight" };
        Q.upsert("evidence-equity-chart", {
            type: "line",
            data: {
                labels: curves.dates || [],
                datasets: Object.keys(series).map(key => ({
                    label: labels[key] || key, data: series[key], borderColor: palette[key] || c.neutral,
                    backgroundColor: key === "sma_news" ? Q.fade(c.c1, 0.14) : palette[key] || c.neutral,
                    fill: key === "sma_news" ? "origin" : false,
                    borderWidth: key === "sma_news" ? 2.5 : 1.75, borderDash: key === "buy_and_hold" ? [5, 4] : []
                }))
            },
            options: Q.axes({
                scales: {
                    x: { grid: { display: false }, ticks: { maxTicksLimit: 6 } },
                    y: { beginAtZero: false, ticks: { callback: v => Q.inrShort(v) } }
                },
                plugins: {
                    legend: { display: true, position: "bottom" },
                    tooltip: { callbacks: { label: item => `${item.dataset.label}: ${Q.inrShort(item.raw)}` } }
                }
            })
        });

        const q = ev.quarters || {};
        const pick = id => strategies.find(s => s.id === id)?.quarters_pct || [];
        Q.upsert("evidence-quarters-chart", {
            type: "bar",
            data: {
                labels: (q.labels || []).map((l, i) => `Q${i + 1}`),
                datasets: [
                    { label: "Market (buy & hold)", data: q.market_pct || [], backgroundColor: c.neutral },
                    { label: "sma_news", data: pick("sma_news"), backgroundColor: c.c1 },
                    { label: "sma_pro", data: pick("sma_pro"), backgroundColor: c.c2 },
                    { label: "sma_band", data: pick("sma_band"), backgroundColor: c.c3 }
                ].map(ds => ({ ...ds, borderRadius: 3, borderColor: c.surface, borderWidth: { left: 1, right: 1 } }))
            },
            options: Q.axes({
                scales: {
                    x: { grid: { display: false } },
                    y: { ticks: { callback: v => v + "%" } }
                },
                plugins: {
                    qCrosshair: false,
                    legend: { display: true, position: "bottom" },
                    qRefLines: { lines: [{ axis: "y", value: 0, color: c.axis, dash: [] }] },
                    tooltip: { callbacks: { label: item => `${item.dataset.label}: ${pct(item.raw)}` } }
                }
            })
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

    let evidence = null;

    async function refreshLive() {
        try { renderTax(await getJSON("/tax")); } catch (e) { /* bot offline: keep last values */ }
        try { renderJournal(await getJSON("/journal")); } catch (e) { /* bot offline */ }
    }

    async function start() {
        initJournal();
        try { evidence = await getJSON("/evidence"); } catch (e) { evidence = null; }
        renderEvidence(evidence);
        // Evidence charts are drawn while their page may be hidden; redraw when it is opened.
        window.addEventListener("hashchange", () => {
            if (location.hash === "#evidence") setTimeout(() => renderEvidence(evidence), 0);
        });
        await refreshLive();
        setInterval(refreshLive, POLL_MS);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }

})();
