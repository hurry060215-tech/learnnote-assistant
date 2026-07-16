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
