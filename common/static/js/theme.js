function getTheme() {
    const storedTheme = localStorage.getItem("theme");
    const preferredTheme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    return storedTheme || preferredTheme;
}

function initTheme() {
    $("#switch-theme").change(function () {
        const theme = $(this).is(":checked") ? "dark" : "light";
        document.documentElement.setAttribute("data-bs-theme", theme);
        localStorage.setItem("theme", theme);
    });
    $("#switch-theme").prop("checked", getTheme() == "dark").trigger("change");
}

$(window).on("load", initTheme);