const menuButton = document.querySelector(".menu-button");
const navigation = document.querySelector(".site-header nav");
const header = document.querySelector(".site-header");

function closeNavigation() {
  navigation?.classList.remove("open");
  menuButton?.setAttribute("aria-expanded", "false");
  menuButton?.setAttribute("aria-label", "打开导航");
}

menuButton?.addEventListener("click", () => {
  const open = navigation?.classList.toggle("open") || false;
  menuButton.setAttribute("aria-expanded", String(open));
  menuButton.setAttribute("aria-label", open ? "关闭导航" : "打开导航");
});

navigation?.addEventListener("click", event => {
  if (event.target.closest("a")) closeNavigation();
});

document.addEventListener("click", event => {
  if (!navigation?.classList.contains("open")) return;
  if (!event.target.closest(".site-header")) closeNavigation();
});

window.addEventListener("scroll", () => {
  header?.classList.toggle("scrolled", window.scrollY > 16);
}, { passive: true });

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const revealElements = document.querySelectorAll(".reveal");

if (reduceMotion || !("IntersectionObserver" in window)) {
  revealElements.forEach(element => element.classList.add("visible"));
} else {
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("visible");
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -24px" });
  revealElements.forEach(element => observer.observe(element));
}

function updateReleaseLinks(release) {
  const tag = String(release?.tag_name || "").trim();
  const assets = Array.isArray(release?.assets) ? release.assets : [];
  const installer = assets.find(asset => asset.name === "LearnNote-Setup-x64.exe");
  const extension = assets.find(asset => /^LearnNote-Browser-Extension-v[\d.]+\.zip$/.test(asset.name));
  if (!tag || !installer?.browser_download_url) return;

  document.querySelectorAll("[data-release-version]").forEach(element => {
    element.textContent = tag;
  });
  document.querySelectorAll("[data-release-link]").forEach(link => {
    link.href = installer.browser_download_url;
  });
  if (extension?.browser_download_url) {
    document.querySelectorAll("[data-extension-link]").forEach(link => {
      link.href = extension.browser_download_url;
    });
  }
}

fetch("https://api.github.com/repos/hurry060215-tech/learnnote-assistant/releases/latest", {
  headers: { Accept: "application/vnd.github+json" }
})
  .then(response => response.ok ? response.json() : null)
  .then(updateReleaseLinks)
  .catch(() => {
    // Static v0.1.26 links remain usable when GitHub API access is unavailable.
  });
