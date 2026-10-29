"use strict";

/* =========================================================
   Page navigation: one page visible at a time, chosen by the
   URL hash (#overview, #market, ...), so refresh and the Back
   button keep the page. Keys 1-8 switch pages when focus is not
   in a form field. Read-only: no requests to the bot server.
========================================================= */

(function () {

    const DEFAULT_PAGE = "overview";

    const $ = id => document.getElementById(id);
    const pages = () => Array.from(document.querySelectorAll(".page[data-page]"));
    const links = () => Array.from(document.querySelectorAll(".nav-link[data-page]"));

    function pageFromHash() {
        return decodeURIComponent(location.hash.replace(/^#/, "")) || DEFAULT_PAGE;
    }

    function show(name, moveFocus) {
        const all = pages();
        const target = all.find(p => p.dataset.page === name)
            || all.find(p => p.dataset.page === DEFAULT_PAGE);
        if (!target) return;

        all.forEach(p => { p.hidden = p !== target; });
        let activeLink = null;
        links().forEach(a => {
            const active = a.dataset.page === target.dataset.page;
            a.classList.toggle("active", active);
            if (active) {
                a.setAttribute("aria-current", "page");
                activeLink = a;
            } else {
                a.removeAttribute("aria-current");
            }
        });

        document.title = `${target.dataset.title || target.dataset.page} | MANTHAN 2026`;
        window.scrollTo(0, 0);
        // On narrow screens the navigation is a horizontal tab bar: keep the active tab visible.
        if (activeLink) activeLink.scrollIntoView({ block: "nearest", inline: "nearest" });

        // Charts drawn while their page was hidden have no size yet.
        if (typeof Chart !== "undefined") {
            Object.values(Chart.instances || {}).forEach(chart => chart.resize());
        }
        if (moveFocus) target.focus({ preventScroll: true });
    }

    /* ---------------- Live badges in the navigation ---------------- */

    function leadingNumber(text) {
        const match = String(text || "").match(/\d[\d,]*/);
        return match ? Number(match[0].replaceAll(",", "")) : 0;
    }

    function syncBadges() {
        document.querySelectorAll(".nav-badge[data-badge-for]").forEach(badge => {
            const n = leadingNumber($(badge.dataset.badgeFor)?.textContent);
            badge.textContent = n > 999 ? "999+" : String(n);
            badge.hidden = n === 0;
        });
    }

    function syncBotState() {
        const source = $("bot-state");
        const pill = $("nav-status");
        if (!source || !pill) return;
        setTextIfChanged($("nav-bot-state"), source.textContent.trim() || "—");
        for (const cls of ["running", "stopped", "offline"]) {
            pill.classList.toggle(cls, source.classList.contains(cls));
        }
    }

    function setTextIfChanged(el, text) {
        if (el && el.textContent !== text) el.textContent = text;
    }

    function watch(id, callback) {
        const el = $(id);
        if (!el) return;
        new MutationObserver(callback).observe(el, {
            childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ["class"]
        });
    }

    /* ---------------- Sticky offsets ---------------- */

    function trackHeaderHeight() {
        const header = document.querySelector(".app-header");
        if (!header) return;
        const apply = () => document.documentElement.style.setProperty("--header-h", `${header.offsetHeight}px`);
        apply();
        if (typeof ResizeObserver !== "undefined") new ResizeObserver(apply).observe(header);
    }

    /* ---------------- Keyboard shortcuts ---------------- */

    function onKey(event) {
        if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
        const target = event.target;
        const tag = (target.tagName || "").toLowerCase();
        if (["input", "select", "textarea"].includes(tag) || target.isContentEditable) return;
        if (document.querySelector("dialog[open]")) return;
        if (!/^[1-9]$/.test(event.key)) return;
        const link = links()[Number(event.key) - 1];
        if (link) {
            event.preventDefault();
            location.hash = link.dataset.page;
        }
    }

    function start() {
        trackHeaderHeight();
        show(pageFromHash(), false);
        window.addEventListener("hashchange", () => show(pageFromHash(), true));
        document.addEventListener("keydown", onKey);

        watch("positions-count", syncBadges);
        watch("bot-state", syncBotState);
        syncBadges();
        syncBotState();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }

})();
