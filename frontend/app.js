
"use strict";

/* =========================================================
   MANTHAN 2026 — FRONTEND DASHBOARD
   Member 1: Frontend

   Mock mode:
   http://localhost:5173/?mock=1

   Live mode:
   Uses the proposed bot HTTP API.

   SAFETY:
   - No exchange gateway access.
   - No exchange order submission.
   - No API tokens.
   - Only bot Start, Stop, and Strategy control endpoints.
========================================================= */


/* =========================================================
   1. CONFIGURATION
========================================================= */

const CONFIG = {
    mock: new URLSearchParams(window.location.search).get("mock") === "1",

    apiBase: "",

    pollInterval: 2000,

    offlineThreshold: 6000,

    heartbeatThreshold: 15000,

    maxEvents: 200,

    defaultTicker: "HAVN",

    currency: "INR"
};


/* =========================================================
   2. APPLICATION STATE
========================================================= */

const state = {
    status: null,

    positions: [],

    events: [],

    series: {},

    equity: [],

    orders: [],

    strategies: [],

    news: [],

    riskBlocks: [],

    activeTicker: CONFIG.defaultTicker,

    activeEventFilter: "ALL",

    activeTickerFilter: "ALL",

    activityPaused: false,

    positionSort: {
        key: "ticker",
        direction: "asc"
    },

    lastEventId: null,

    lastSuccessfulFetch: null,

    polling: false,

    strategyChanged: false
};


/* =========================================================
   3. DOM HELPERS
========================================================= */

function $(id) {
    return document.getElementById(id);
}


function setText(id, value) {
    const element = $(id);

    if (!element) return;

    element.textContent =
        value === null ||
        value === undefined ||
        value === ""
            ? "—"
            : String(value);
}


function setHTML(id, html) {
    const element = $(id);

    if (!element) return;

    element.innerHTML = html;
}


function showElement(id, visible) {
    const element = $(id);

    if (!element) return;

    element.hidden = !visible;
}


function setClass(id, className) {
    const element = $(id);

    if (!element) return;

    element.className = className;
}


function escapeHTML(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function safeNumber(value) {
    const number = Number(value);

    return Number.isFinite(number) ? number : null;
}


/* =========================================================
   4. NUMBER FORMATTING
========================================================= */

function formatMoney(value) {
    const number = safeNumber(value);

    if (number === null) {
        return "—";
    }

    return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(number);
}


function formatNumber(value, decimals = 2) {
    const number = safeNumber(value);

    if (number === null) {
        return "—";
    }

    return new Intl.NumberFormat("en-IN", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    }).format(number);
}


function formatPercent(value) {
    const number = safeNumber(value);

    if (number === null) {
        return "—";
    }

    const sign = number > 0 ? "+" : "";

    return `${sign}${number.toFixed(2)}%`;
}


function formatDuration(seconds) {
    const value = safeNumber(seconds);

    if (value === null) {
        return "—";
    }

    if (value < 60) {
        return `${value.toFixed(2)} s`;
    }

    const minutes = Math.floor(value / 60);

    const remainingSeconds = Math.floor(value % 60);

    return `${minutes}m ${remainingSeconds}s`;
}


function formatDate(value) {
    if (!value) return "—";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "—";
    }

    return date.toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric"
    });
}


function formatTime(value) {
    if (!value) return "—";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "—";
    }

    return date.toLocaleTimeString("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
    });
}


/* =========================================================
   5. API HELPERS
========================================================= */

async function apiGet(endpoint) {
    const response = await fetch(
        `${CONFIG.apiBase}${endpoint}`,
        {
            method: "GET",

            headers: {
                "Accept": "application/json"
            },

            cache: "no-store"
        }
    );

    if (!response.ok) {
        throw new Error(
            `GET ${endpoint} failed: ${response.status}`
        );
    }

    return response.json();
}


async function apiPost(endpoint, body = {}) {
    const response = await fetch(
        `${CONFIG.apiBase}${endpoint}`,
        {
            method: "POST",

            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json"
            },

            body: JSON.stringify(body)
        }
    );

    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
        throw new Error(
            result.error || `Request failed: ${response.status}`
        );
    }

    return result;
}


/* =========================================================
   6. FIXTURE DATA
========================================================= */

async function loadFixture(filename) {
    const response = await fetch(
        `./fixtures/${filename}.json`,
        {
            cache: "no-store"
        }
    );

    if (!response.ok) {
        throw new Error(
            `Fixture not found: ${filename}.json`
        );
    }

    return response.json();
}


async function fetchDashboardData() {

    if (CONFIG.mock) {

                const [
            status,
            positions,
            events,
            equity,
            orders,
            strategies,
            series
        ] = await Promise.all([

            loadFixture("status"),

            loadFixture("positions"),

            loadFixture("events"),

            loadFixture("equity"),

            loadFixture("orders"),

            loadFixture("strategies"),

            loadFixture(`series/${CONFIG.defaultTicker}`)

        ]);

        state.status = status;

        state.positions = positions;

        state.events = events;

        state.equity = equity;

        state.orders = orders;

        state.strategies = strategies;

        state.series[CONFIG.defaultTicker] = series;
        state.lastSuccessfulFetch = Date.now();

        return;
    }


    /* Live API mode */

    const [
        status,
        positions,
        events,
        equity,
        orders,
        strategies,
        series,
        news
    ] = await Promise.all([

        apiGet("/status"),

        apiGet("/positions"),

        apiGet(
            `/events?since=${state.lastEventId ?? 0}`
        ),

        apiGet("/equity"),

        apiGet("/orders"),

        apiGet("/strategies"),

        apiGet("/series"),

        apiGet("/news")

    ]);


    state.status = status;

    if (series && typeof series === "object" && !Array.isArray(series)) {

        state.series = series;

        const known = Object.keys(series);

        if (known.length && !known.includes(state.activeTicker)) {
            state.activeTicker = known[0];
        }

        const tickerSelector = document.getElementById("ticker-selector");

        if (
            tickerSelector &&
            known.length &&
            tickerSelector.options.length !== known.length
        ) {

            tickerSelector.innerHTML = known.map(
                ticker => `<option value="${escapeHTML(ticker)}">${escapeHTML(ticker)}</option>`
            ).join("");

            tickerSelector.value = state.activeTicker;

        }

    }

    state.news = Array.isArray(news)
        ? news
        : [];

    state.positions = Array.isArray(positions)
        ? positions
        : [];

    state.equity = Array.isArray(equity)
        ? equity
        : [];

    state.orders = Array.isArray(orders)
        ? orders
        : [];

    state.strategies = Array.isArray(strategies)
        ? strategies
        : [];


    if (Array.isArray(events)) {

        state.events = [
            ...events,
            ...state.events
        ].slice(0, CONFIG.maxEvents);


        if (events.length > 0) {

            const newestId = Math.max(
                ...events.map(event => safeNumber(event.id) ?? 0)
            );

            state.lastEventId = newestId;

        }

    }


    state.lastSuccessfulFetch = Date.now();
}


/* =========================================================
   7. HEADER STATUS
========================================================= */

function renderHeader() {

    const status = state.status;

    if (!status) return;

    const bot = status.bot || {};

    const sim = status.sim || {};


    const botState = bot.state || "OFFLINE";

    setText("bot-state", botState);

    setText("kafka-status",
        bot.kafka_connected === true
            ? "CONNECTED"
            : bot.kafka_connected === false
                ? "DISCONNECTED"
                : "—"
    );


    setText(
        "heartbeat-status",
        `Seq ${bot.last_heartbeat_seq ?? "—"}`
    );

    setText(
        "heartbeat-time",
        formatTime(bot.last_heartbeat_at)
    );


    setText(
        "simulation-status",
        sim.status || "—"
    );


    setText(
        "simulation-mode",
        sim.is_sandbox === true
            ? "SANDBOX"
            : sim.is_sandbox === false
                ? "LIVE RUN"
                : "—"
    );


    const stateElement = $("bot-state");

    if (stateElement) {

        stateElement.classList.remove(
            "running",
            "stopped",
            "offline"
        );

        if (botState === "RUNNING") {

            stateElement.classList.add("running");

        } else if (botState === "STOPPED") {

            stateElement.classList.add("stopped");

        } else {

            stateElement.classList.add("offline");

        }

    }


    const kafkaElement = $("kafka-status");

    if (kafkaElement) {

        kafkaElement.classList.toggle(
            "connected",
            bot.kafka_connected === true
        );

        kafkaElement.classList.toggle(
            "disconnected",
            bot.kafka_connected !== true
        );

    }


    renderSimulationProgress();

    renderOfflineStatus();

    renderControls();

}


/* =========================================================
   8. SIMULATION PROGRESS
========================================================= */

function renderSimulationProgress() {

    const sim = state.status?.sim || {};

    const completed = safeNumber(sim.days_completed);

    const total = safeNumber(sim.total_days);


    setText(
        "simulation-date",
        sim.current_date || "—"
    );


    setText(
        "days-completed",
        completed ?? "—"
    );


    setText(
        "total-days",
        total ?? "—"
    );


    setText(
        "simulation-stage",
        `Stage: ${sim.stage || "—"}`
    );


    setText(
        "simulation-interval",
        `Interval: ${sim.interval_seconds ?? "—"} s`
    );


    let percentage = 0;

    if (
        completed !== null &&
        total !== null &&
        total > 0
    ) {

        percentage = Math.min(
            100,
            Math.max(0, (completed / total) * 100)
        );

    }


    const fill = $("simulation-progress-fill");

    if (fill) {

        fill.style.width = `${percentage}%`;

    }


    const progress = $("simulation-progress-bar");

    if (progress) {

        progress.setAttribute(
            "aria-valuenow",
            String(percentage)
        );

    }

}


/* =========================================================
   9. OFFLINE STATUS
========================================================= */

function renderOfflineStatus() {

    const bot = state.status?.bot || {};

    const lastSeen = state.lastSuccessfulFetch;

    const elapsed = lastSeen
        ? Math.floor((Date.now() - lastSeen) / 1000)
        : null;


    const isOffline =
        elapsed === null ||
        elapsed > CONFIG.offlineThreshold / 1000;


    showElement(
        "offline-banner",
        isOffline
    );


    if (isOffline) {

        setText(
            "offline-last-seen",
            `Last seen: ${elapsed ?? "—"} s ago`
        );

    }


    const heartbeatAt = bot.last_heartbeat_at;

    if (!heartbeatAt) return;


    const heartbeatAge =
        (Date.now() - new Date(heartbeatAt).getTime()) / 1000;


    const heartbeatElement = $("heartbeat-status");

    if (heartbeatElement) {

        heartbeatElement.classList.toggle(
            "heartbeat-stale",
            heartbeatAge > CONFIG.heartbeatThreshold / 1000
        );

    }

}


/* =========================================================
   10. KPI CARDS
========================================================= */

function renderKPIs() {

    const account = state.status?.account || {};

    const stats = state.status?.stats || {};


    setText(
        "kpi-total-wealth",
        formatMoney(account.total_wealth)
    );


    setText(
        "kpi-cash",
        formatMoney(account.cash)
    );


    setText(
        "kpi-invested",
        formatMoney(account.invested)
    );


    setText(
        "kpi-net-pnl",
        formatMoney(account.net_pnl)
    );


    setText(
        "kpi-net-pnl-percent",
        formatPercent(account.net_pnl_pct)
    );


    setText(
        "kpi-orders-sent",
        stats.orders_sent
    );


    setText(
        "kpi-orders-rejected",
        stats.orders_rejected
    );


    const sent = safeNumber(stats.orders_sent);

    const rejected = safeNumber(stats.orders_rejected);


    let rejectionRate = null;

    if (
        sent !== null &&
        rejected !== null &&
        sent + rejected > 0
    ) {

        rejectionRate =
            (rejected / (sent + rejected)) * 100;

    }


    setText(
        "kpi-rejection-rate",
        rejectionRate === null
            ? "Rejection rate: —"
            : `Rejection rate: ${rejectionRate.toFixed(2)}%`
    );


    setText(
        "kpi-latency",
        stats.latency_avg_s === undefined || stats.latency_avg_s === null
            ? "—"
            : `${formatNumber(stats.latency_avg_s, 3)} s`
    );


    setText(
        "kpi-uptime",
        formatDuration(state.status?.bot?.uptime_s)
    );


    const pnl = safeNumber(account.net_pnl);

    const pnlElement = $("kpi-net-pnl");

    if (pnlElement) {

        pnlElement.classList.remove(
            "positive",
            "negative"
        );

        if (pnl !== null && pnl !== 0) {

            pnlElement.classList.add(
                pnl > 0
                    ? "positive"
                    : "negative"
            );

        }

    }

}


/* =========================================================
   11. POSITIONS TABLE
========================================================= */

function getHoldingClass(heldSince) {

    if (!heldSince) return "—";

    const start = new Date(heldSince);

    const today = new Date(
        state.status?.sim?.current_date ||
        new Date().toISOString().slice(0, 10)
    );


    if (
        Number.isNaN(start.getTime()) ||
        Number.isNaN(today.getTime())
    ) {

        return "—";

    }


    const days = Math.floor(
        (today - start) / (1000 * 60 * 60 * 24)
    );


    return days > 365
        ? "Long-term"
        : "Short-term";

}


function renderPositions() {

    const tbody = $("positions-table-body");

    if (!tbody) return;


    const positions = [...state.positions];


    if (positions.length === 0) {

        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="empty-state">
                    No open positions
                </td>
            </tr>
        `;

        setText("positions-count", "0 positions");

        return;

    }


    const { key, direction } = state.positionSort;


    positions.sort((a, b) => {

        const first = a[key] ?? "";

        const second = b[key] ?? "";


        if (
            typeof first === "number" &&
            typeof second === "number"
        ) {

            return direction === "asc"
                ? first - second
                : second - first;

        }


        return direction === "asc"
            ? String(first).localeCompare(String(second))
            : String(second).localeCompare(String(first));

    });


    tbody.innerHTML = positions.map(position => {

        const pnl = safeNumber(position.unrealized_pnl);

        const pnlClass =
            pnl === null
                ? ""
                : pnl >= 0
                    ? "positive"
                    : "negative";


        const cap = safeNumber(position.cap_used_pct);


        return `
            <tr>

                <td>
                    <strong>
                        ${escapeHTML(position.ticker || "—")}
                    </strong>
                </td>

                <td>
                    ${formatNumber(position.quantity, 0)}
                </td>

                <td>
                    ${formatMoney(position.last_close)}
                </td>

                <td>
                    ${formatMoney(position.value)}
                </td>

                <td>
                    ${formatMoney(position.avg_price)}
                </td>

                <td class="${pnlClass}">
                    ${pnl === null
                        ? "—"
                        : `${pnl > 0 ? "+" : ""}${formatMoney(pnl)}`
                    }
                </td>

                <td>

                    <div class="cap-progress">

                        <span>
                            ${cap === null
                                ? "—"
                                : `${cap.toFixed(2)}%`
                            }
                        </span>

                        <div class="cap-track">

                            <div
                                class="cap-fill"
                                style="width:${Math.min(
                                    100,
                                    Math.max(0, cap ?? 0)
                                )}%">
                            </div>

                        </div>

                    </div>

                </td>

                <td>
                    ${formatDate(position.held_since)}
                </td>

                <td>
                    ${getHoldingClass(position.held_since)}
                </td>

            </tr>
        `;

    }).join("");


    setText(
        "positions-count",
        `${positions.length} positions`
    );

}


/* =========================================================
   12. ORDERS TABLE
========================================================= */

function renderOrders() {

    const tbody = $("orders-table-body");

    if (!tbody) return;


    if (!state.orders.length) {

        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="empty-state">
                    No orders available
                </td>
            </tr>
        `;

        setText("orders-count", "0 orders");

        return;

    }


    tbody.innerHTML = state.orders.map(order => {

        const status = order.status || "—";

        const statusClass =
            status === "REJECTED"
                ? "rejected"
                : status === "UNCERTAIN"
                    ? "uncertain"
                    : status === "FILLED"
                        ? "filled"
                        : "";


        return `
            <tr class="${statusClass}">

                <td>
                    ${formatTime(order.time)}
                </td>

                <td>
                    ${escapeHTML(order.ticker || "—")}
                </td>

                <td>
                    ${escapeHTML(order.action || "—")}
                </td>

                <td>
                    ${formatNumber(order.quantity, 0)}
                </td>

                <td>
                    ${formatMoney(order.price)}
                </td>

                <td>

                    <span class="order-status ${statusClass}">
                        ${escapeHTML(status)}
                    </span>

                </td>

                <td>
                    ${escapeHTML(order.code || "—")}
                </td>

                <td>
                    ${formatMoney(order.fees)}
                </td>

                <td>
                    ${order.latency_s === undefined
                        ? "—"
                        : `${formatNumber(order.latency_s, 3)} s`
                    }
                </td>

            </tr>
        `;

    }).join("");


    setText(
        "orders-count",
        `${state.orders.length} orders`
    );


    const totalFees = state.orders.reduce(
        (sum, order) => {

            const fee = safeNumber(order.fees);

            return fee === null
                ? sum
                : sum + fee;

        },
        0
    );


    setText(
        "orders-total-fees",
        formatMoney(totalFees)
    );

}


/* =========================================================
   13. ACTIVITY FEED
========================================================= */

function getEventIcon(type) {

    const icons = {

        TICK: "●",

        SIGNAL: "↗",

        ORDER: "⇄",

        RISK_BLOCK: "⊘",

        NEWS: "◉",

        ERROR: "!",

        SYSTEM: "⚙"

    };


    return icons[type] || "•";

}


function renderActivity() {

    const feed = $("activity-feed");

    if (!feed) return;


    if (state.activityPaused) return;


    let events = [...state.events];


    if (state.activeEventFilter !== "ALL") {

        events = events.filter(
            event => event.type === state.activeEventFilter
        );

    }


    if (state.activeTickerFilter !== "ALL") {

        events = events.filter(
            event => event.ticker === state.activeTickerFilter
        );

    }


    events = events.slice(0, CONFIG.maxEvents);


    setText(
        "activity-count",
        `${events.length} events`
    );


    if (!events.length) {

        feed.innerHTML = `
            <div class="empty-state">
                No matching events
            </div>
        `;

        return;

    }


    feed.innerHTML = events.map(event => {

        const type = event.type || "SYSTEM";


        return `

            <details class="activity-row ${escapeHTML(type)}">

                <summary>

                    <span class="activity-icon">
                        ${getEventIcon(type)}
                    </span>

                    <span class="activity-time">
                        ${formatTime(event.time)}
                    </span>

                    <span class="activity-type">
                        ${escapeHTML(type)}
                    </span>

                    <span class="activity-ticker">
                        ${escapeHTML(event.ticker || "—")}
                    </span>

                    <span class="activity-message">
                        ${escapeHTML(event.message || "—")}
                    </span>

                </summary>


                <div class="activity-details">

                    <p>
                        <strong>Simulated Date:</strong>
                        ${escapeHTML(event.simulated_date || "—")}
                    </p>

                    <p>
                        <strong>Reason:</strong>
                        ${escapeHTML(event.reason || "—")}
                    </p>

                    <pre>${escapeHTML(
                        JSON.stringify(event.data ?? {}, null, 2)
                    )}</pre>

                </div>

            </details>

        `;

    }).join("");

}


/* =========================================================
   14. NEWS PANEL
========================================================= */

function renderNews() {

    const container = $("news-list");

    if (!container) return;


    if (!state.news.length) {

        container.innerHTML = `
            <div class="empty-state">
                No news available
            </div>
        `;

        return;

    }


    container.innerHTML = state.news.map(item => {

        const score = safeNumber(item.keyword_score);


        return `

            <article class="news-item">

                <div class="news-header">

                    <span class="news-ticker">
                        ${escapeHTML(item.ticker || "—")}
                    </span>

                    <span class="news-date">
                        ${escapeHTML(item.simulated_date || "—")}
                    </span>

                </div>


                <h3>
                    ${escapeHTML(item.headline || "—")}
                </h3>


                <p class="news-score">

                    Keyword Score:

                    ${score === null
                        ? "—"
                        : `${score > 0 ? "+" : ""}${score}`
                    }

                </p>


                <span class="informational-badge">
                    NOT USED FOR TRADING
                </span>

            </article>

        `;

    }).join("");

}


/* =========================================================
   15. STRATEGY SELECTOR
========================================================= */

function renderStrategies() {

    const selector = $("strategy-selector");

    if (!selector) return;


    const currentStrategy =
        state.status?.bot?.strategy || "sma_band";


    if (!state.strategies.length) {

        selector.innerHTML = `
            <option value="sma_band">
                SMA8 ±1.5%
            </option>
        `;

        return;

    }


    selector.innerHTML = state.strategies.map(strategy => {

        const comingSoon = strategy.available === false;

        return `

            <option
                value="${escapeHTML(strategy.id)}"
                ${strategy.id === currentStrategy ? "selected" : ""}
                ${comingSoon ? "disabled" : ""}>

                ${escapeHTML(strategy.name || strategy.id)}
                ${comingSoon ? " — Coming Soon" : ""}

            </option>

        `;

    }).join("");


    const selected = state.strategies.find(
        strategy => strategy.id === currentStrategy
    );


    setText(
        "strategy-description",
        selected?.description || "—"
    );


    const params = selected?.params;


    setText(
        "strategy-parameters",
        params
            ? JSON.stringify(params, null, 2)
            : "—"
    );


    selector.value = currentStrategy;

}


/* =========================================================
   16. BOT CONTROLS
========================================================= */

function renderControls() {

    const bot = state.status?.bot || {};

    const botState = bot.state || "OFFLINE";


    const isOffline = botState === "OFFLINE";

    const isStopped = botState === "STOPPED";

    const isRunning = botState === "RUNNING";


    const startButton = $("start-trading-button");

    const stopButton = $("stop-trading-button");

    const strategySelector = $("strategy-selector");


    if (startButton) {

        startButton.disabled =
            isOffline ||
            isRunning;

    }


    if (stopButton) {

        stopButton.disabled =
            isOffline ||
            isStopped;

    }


    if (strategySelector) {

        strategySelector.disabled =
            isOffline ||
            !isStopped;

    }


    setText(
        "control-bot-state",
        botState
    );


    setText(
        "control-disabled-reason",
        isOffline
            ? "Controls disabled: bot is offline."
            : isRunning
                ? "Bot is running. Stop it before changing strategy."
                : isStopped
                    ? "Bot is stopped. Ready for configuration."
                    : "—"
    );


    setText(
        "strategy-disabled-reason",
        isOffline
            ? "Strategy selection disabled: bot is offline."
            : !isStopped
                ? "Strategy can only be changed while STOPPED."
                : "Strategy selection available."
    );

}


/* =========================================================
   17. STRATEGY CHANGE
========================================================= */

async function changeStrategy(strategyId) {

    if (!strategyId) return;


    const botState = state.status?.bot?.state;


    if (botState !== "STOPPED") {

        alert(
            "Strategy can only be changed while the bot is STOPPED."
        );

        renderStrategies();

        return;

    }


    const selectedStrategy = state.strategies.find(
        strategy => strategy.id === strategyId
    );


    if (selectedStrategy?.available === false) {

        alert(
            "This strategy is coming soon."
        );

        renderStrategies();

        return;

    }


    try {

        let result;


        if (CONFIG.mock) {

            result = {

                bot: {

                    ...state.status.bot,

                    strategy: strategyId

                }

            };

        } else {

            result = await apiPost(
                "/control/strategy",
                {
                    id: strategyId
                }
            );

        }


        if (result.error) {

            throw new Error(result.error);

        }


        if (result.bot) {

            state.status.bot = result.bot;

        } else if (result.strategy) {

            state.status.bot = {
                ...state.status.bot,
                strategy: result.strategy
            };

        } else {

            throw new Error(
                "Strategy API response did not contain the resulting bot state."
            );

        }


        state.strategyChanged = true;


        showElement(
            "strategy-change-banner",
            true
        );


        renderStrategies();

        renderControls();


    } catch (error) {

        console.error(
            "Strategy change failed:",
            error.message
        );

        alert(
            `Strategy change failed: ${error.message}`
        );

        renderStrategies();

    }

}


/* =========================================================
   18. START TRADING
========================================================= */

async function startTrading() {

    const botState = state.status?.bot?.state;


    if (botState !== "STOPPED") {

        alert(
            "Bot must be STOPPED before starting."
        );

        return;

    }


    try {

        let result;


        if (CONFIG.mock) {

            result = {

                bot: {

                    ...state.status.bot,

                    state: "RUNNING"

                }

            };

        } else {

            result = await apiPost(
                "/control/start"
            );

        }


        if (result.error) {

            throw new Error(result.error);

        }


        if (!result.bot) {

            throw new Error(
                "Start API response did not contain the resulting bot state."
            );

        }


        state.status.bot = result.bot;


        renderHeader();

        renderControls();


    } catch (error) {

        console.error(
            "Start failed:",
            error.message
        );

        alert(
            `Unable to start trading: ${error.message}`
        );

    }

}


/* =========================================================
   19. STOP TRADING
========================================================= */

async function stopTrading() {

    const botState = state.status?.bot?.state;


    if (botState !== "RUNNING") {

        alert(
            "Bot is not currently running."
        );

        return;

    }


    try {

        let result;


        if (CONFIG.mock) {

            result = {

                bot: {

                    ...state.status.bot,

                    state: "STOPPED"

                }

            };

        } else {

            result = await apiPost(
                "/control/stop"
            );

        }


        if (result.error) {

            throw new Error(result.error);

        }


        if (!result.bot) {

            throw new Error(
                "Stop API response did not contain the resulting bot state."
            );

        }


        state.status.bot = result.bot;


        renderHeader();

        renderControls();


    } catch (error) {

        console.error(
            "Stop failed:",
            error.message
        );

        alert(
            `Unable to stop trading: ${error.message}`
        );

    }

}


/* =========================================================
   20. SORTABLE POSITIONS
========================================================= */

function initializePositionSorting() {

    document.querySelectorAll(
        "#positions-table .sort-button"
    ).forEach(button => {

        button.addEventListener(
            "click",
            () => {

                const key = button.dataset.sort;


                if (state.positionSort.key === key) {

                    state.positionSort.direction =
                        state.positionSort.direction === "asc"
                            ? "desc"
                            : "asc";

                } else {

                    state.positionSort.key = key;

                    state.positionSort.direction = "asc";

                }


                renderPositions();

            }
        );

    });

}


/* =========================================================
   21. ACTIVITY FILTERS
========================================================= */

function initializeActivityFilters() {

    document.querySelectorAll(
        ".filter-chip"
    ).forEach(button => {

        button.addEventListener(
            "click",
            () => {

                document.querySelectorAll(
                    ".filter-chip"
                ).forEach(chip => {

                    chip.classList.remove("active");

                });


                button.classList.add("active");


                state.activeEventFilter =
                    button.dataset.filter || "ALL";


                renderActivity();

            }
        );

    });


    const tickerFilter = $("activity-ticker-filter");


    if (tickerFilter) {

        tickerFilter.addEventListener(
            "change",
            event => {

                state.activeTickerFilter =
                    event.target.value;


                renderActivity();

            }
        );

    }


    const pauseCheckbox = $("pause-activity-feed");


    if (pauseCheckbox) {

        pauseCheckbox.addEventListener(
            "change",
            event => {

                state.activityPaused =
                    event.target.checked;


                if (!state.activityPaused) {

                    renderActivity();

                }

            }
        );

    }

}


/* =========================================================
   22. TICKER SELECTOR
========================================================= */

function initializeTickerSelector() {

    const selector = $("ticker-selector");

    if (!selector) return;


    selector.addEventListener(
        "change",
        event => {

            state.activeTicker =
                event.target.value;


            renderCharts();

        }
    );

}


/* =========================================================
   23. STRATEGY SELECTOR EVENT
========================================================= */

function initializeStrategySelector() {

    const selector = $("strategy-selector");

    if (!selector) return;


    selector.addEventListener(
        "change",
        event => {

            changeStrategy(
                event.target.value
            );

        }
    );

}


/* =========================================================
   24. CONTROL BUTTON EVENTS
========================================================= */

function initializeControls() {

    const startButton = $("start-trading-button");

    const stopButton = $("stop-trading-button");


    const dialog = $("start-confirmation-dialog");


    const confirmButton = $("confirm-start-button");

    const cancelButton = $("cancel-start-button");


    if (startButton && dialog) {

        startButton.addEventListener(
            "click",
            () => {

                if (
                    state.status?.bot?.state !== "STOPPED"
                ) {

                    return;

                }


                dialog.showModal();

            }
        );

    }


    if (confirmButton && dialog) {

        confirmButton.addEventListener(
            "click",
            async () => {

                dialog.close();

                await startTrading();

            }
        );

    }


    if (cancelButton && dialog) {

        cancelButton.addEventListener(
            "click",
            () => {

                dialog.close();

            }
        );

    }


    if (stopButton) {

        stopButton.addEventListener(
            "click",
            async () => {

                await stopTrading();

            }
        );

    }

}


/* =========================================================
   25. CHARTS
========================================================= */

/*
   Chart.js is optional in this file.

   If you use Chart.js, vendor it locally:

   frontend/vendor/chart.umd.js

   Then load it in index.html before app.js.

   If Chart.js is not available, the dashboard will continue
   working and chart containers will show a fallback message.
*/


const chartInstances = {};


function destroyChart(id) {

    if (chartInstances[id]) {

        chartInstances[id].destroy();

        delete chartInstances[id];

    }

}


function renderLineChart(
    elementId,
    labels,
    datasets,
    options = {}
) {

    const element = $(elementId);

    if (!element) return;


    if (typeof Chart === "undefined") {

        element.innerHTML = `
            <div class="chart-placeholder">
                Chart library unavailable
            </div>
        `;

        return;

    }


    destroyChart(elementId);


    const canvas = document.createElement("canvas");

    element.replaceChildren(canvas);


    chartInstances[elementId] = new Chart(
        canvas,
        {

            type: "line",

            data: {

                labels,

                datasets

            },

            options: {

                responsive: true,

                maintainAspectRatio: false,

                interaction: {

                    intersect: false,

                    mode: "index"

                },

                plugins: {

                    legend: {

                        display: true

                    }

                },

                scales: {

                    x: {

                        ticks: {

                            maxTicksLimit: 8

                        }

                    }

                },

                ...options

            }

        }
    );

}


/* =========================================================
   26. PRICE CHART
========================================================= */

function renderPriceChart() {

    const ticker = state.activeTicker;


    const data = state.series[ticker];


    if (!data || !Array.isArray(data.points)) {

        renderLineChart(
            "price-chart",
            [],
            []
        );

        return;

    }


    const points = data.points;


    const labels = points.map(
        point => point.date
    );


    const datasets = [

        {

            label: "Close",

            data: points.map(
                point => point.close ?? null
            ),

            tension: 0.2

        },

        {

            label: "SMA8",

            data: points.map(
                point => point.sma8 ?? null
            ),

            tension: 0.2

        },

        {

            label: "Upper Band",

            data: points.map(
                point => point.upper ?? null
            ),

            borderDash: [5, 5],

            pointRadius: 0

        },

        {

            label: "Lower Band",

            data: points.map(
                point => point.lower ?? null
            ),

            borderDash: [5, 5],

            pointRadius: 0

        }

    ];


    /* BUY / SELL execution markers from the bot's fills */

    const markers = Array.isArray(data.markers) ? data.markers : [];

    const markerSeries = (action, color, style) => {

        const byDate = {};

        markers
            .filter(marker => marker.action === action)
            .forEach(marker => { byDate[marker.date] = marker.price; });

        return {
            label: action,
            data: labels.map(date => byDate[date] ?? null),
            showLine: false,
            pointRadius: 7,
            pointHoverRadius: 9,
            pointStyle: style,
            rotation: action === "SELL" ? 180 : 0,
            borderColor: color,
            backgroundColor: color
        };

    };

    if (markers.length) {

        const css = getComputedStyle(document.documentElement);

        datasets.push(
            markerSeries("BUY", css.getPropertyValue("--green").trim() || "#34D399", "triangle"),
            markerSeries("SELL", css.getPropertyValue("--red").trim() || "#FB7185", "triangle")
        );

    }


    renderLineChart(
        "price-chart",
        labels,
        datasets
    );

}


/* =========================================================
   27. EQUITY CHART
========================================================= */

function renderEquityChart() {

    const labels = state.equity.map(
        item => item.date
    );


    const values = state.equity.map(
        item => item.total_wealth ?? null
    );


    renderLineChart(
        "equity-chart",
        labels,
        [

            {

                label: "Total Wealth",

                data: values,

                tension: 0.2

            }

        ]
    );

}


/* =========================================================
   28. EXPOSURE CHART
========================================================= */

function renderExposureChart() {

    const account = state.status?.account || {};


    const labels = [

        "Cash",

        ...state.positions.map(
            position => position.ticker
        )

    ];


    const values = [

        account.cash ?? null,

        ...state.positions.map(
            position => position.value ?? null
        )

    ];


    renderLineChart(
        "exposure-chart",
        labels,
        [

            {

                label: "Portfolio Exposure",

                data: values,

                tension: 0

            }

        ]
    );

}


/* =========================================================
   29. LATENCY CHART
========================================================= */

function renderLatencyChart() {

    const stats = state.status?.stats || {};


    setText(
        "latency-avg",
        stats.latency_avg_s === undefined || stats.latency_avg_s === null
            ? "—"
            : `${formatNumber(stats.latency_avg_s, 3)} s`
    );


    setText(
        "latency-p95",
        stats.latency_p95_s === undefined
            ? "—"
            : `${formatNumber(stats.latency_p95_s, 3)} s`
    );


    setText(
        "latency-max",
        stats.latency_max_s === undefined
            ? "—"
            : `${formatNumber(stats.latency_max_s, 3)} s`
    );


    const labels = state.orders.map(
        (_, index) => index + 1
    );


    const values = state.orders.map(
        order => order.latency_s ?? null
    );


    renderLineChart(
        "latency-chart",
        labels,
        [

            {

                label: "Latency (seconds)",

                data: values,

                tension: 0

            }

        ]
    );

}


/* =========================================================
   30. RISK BLOCK CHART
========================================================= */

function renderRiskChart() {

    const counts = {};


    state.events
        .filter(event => event.type === "RISK_BLOCK")
        .forEach(event => {

            const reason =
                event.reason || "Unknown";

            counts[reason] =
                (counts[reason] || 0) + 1;

        });


    renderLineChart(
        "risk-block-chart",
        Object.keys(counts),
        [

            {

                label: "Risk Blocks",

                data: Object.values(counts),

                tension: 0

            }

        ]
    );

}


/* =========================================================
   31. TRIGGER HEATMAP
========================================================= */

function renderTriggerHeatmap() {

    const container = $("trigger-heatmap");

    if (!container) return;


    const tickers = Object.keys(state.series);


    if (!tickers.length) {

        container.innerHTML = `
            <div class="empty-state">
                No trigger data available
            </div>
        `;

        return;

    }


    container.innerHTML = tickers.map(ticker => {

        const points = state.series[ticker]?.points || [];

        const latest = points.at(-1);


        if (!latest) {

            return "";

        }


        const close = safeNumber(latest.close);

        const sma = safeNumber(latest.sma8);


        let distance = null;


        if (
            close !== null &&
            sma !== null &&
            sma !== 0
        ) {

            distance = ((close / sma) - 1) * 100;

        }


        let zone = "neutral";


        if (distance !== null) {

            if (distance >= 1.5) {

                zone = "buy-zone";

            } else if (distance <= -1.5) {

                zone = "sell-zone";

            }

        }


        return `

            <div class="trigger-cell ${zone}">

                <span class="trigger-ticker">
                    ${escapeHTML(ticker)}
                </span>

                <strong>
                    ${formatPercent(distance)}
                </strong>

            </div>

        `;

    }).join("");

}


/* =========================================================
   32. RENDER ALL CHARTS
========================================================= */

function renderCharts() {

    renderPriceChart();

    renderEquityChart();

    renderExposureChart();

    renderLatencyChart();

    renderRiskChart();

    renderTriggerHeatmap();

}


/* =========================================================
   33. UPDATE FOOTER
========================================================= */

function renderFooter() {

    setText(
        "last-updated",
        `Last updated: ${new Date().toLocaleTimeString("en-IN")}`
    );


    setText(
        "connection-status",
        CONFIG.mock
            ? "Fixture mode"
            : "Connected to bot API"
    );


    showElement(
        "fixture-banner",
        CONFIG.mock
    );

}


/* =========================================================
   34. RENDER DASHBOARD
========================================================= */

function renderDashboard() {

    renderHeader();

    renderKPIs();

    renderPositions();

    renderOrders();

    renderActivity();

    renderNews();

    renderStrategies();

    renderControls();

    renderCharts();

    renderFooter();

}


/* =========================================================
   35. POLLING
========================================================= */

async function pollDashboard() {

    if (state.polling) return;


    state.polling = true;


    try {

        await fetchDashboardData();


        renderDashboard();


    } catch (error) {

        console.error(
            "Dashboard polling failed:",
            error.message
        );


        setText(
            "connection-status",
            "Connection error"
        );


        if (!state.lastSuccessfulFetch) {

            showElement(
                "offline-banner",
                true
            );

        }


    } finally {

        state.polling = false;

    }

}


/* =========================================================
   36. INITIALIZATION
========================================================= */

function initializeDashboard() {

    initializePositionSorting();

    initializeActivityFilters();

    initializeTickerSelector();

    initializeStrategySelector();

    initializeControls();


    pollDashboard();


    setInterval(
        pollDashboard,
        CONFIG.pollInterval
    );

}


/* =========================================================
   37. START APPLICATION
========================================================= */

document.addEventListener(
    "DOMContentLoaded",
    initializeDashboard
);
