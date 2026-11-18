export function initializeTheme() {
    const applyTheme = (theme) => {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("liainne-theme", theme);
        const track = document.getElementById("theme-track");
        const label = document.getElementById("theme-label");
        const button = document.getElementById("theme-toggle-btn");
        if (track) track.classList.toggle("active", theme === "gray");
        if (label) label.textContent = theme === "gray" ? "Gray" : "Ballerina";
        if (button) button.setAttribute("aria-pressed", String(theme === "gray"));
    };

    window.toggleTheme = () => {
        const current = document.documentElement.getAttribute("data-theme") || "ballerina";
        applyTheme(current === "ballerina" ? "gray" : "ballerina");
    };

    applyTheme(localStorage.getItem("liainne-theme") || "ballerina");
}
