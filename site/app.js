(() => {
  document.documentElement.classList.add("js");
  const menu = document.querySelector(".burger");
  const navigation = document.querySelector("#site-nav");
  const backdrop = document.querySelector(".menu-backdrop");
  const header = document.querySelector(".header");

  const closeMenu = () => {
    document.body.classList.remove("menu-open");
    menu?.setAttribute("aria-expanded", "false");
    menu?.setAttribute("aria-label", "打开导航");
  };

  menu?.addEventListener("click", () => {
    const open = !document.body.classList.contains("menu-open");
    document.body.classList.toggle("menu-open", open);
    menu.setAttribute("aria-expanded", String(open));
    menu.setAttribute("aria-label", open ? "关闭导航" : "打开导航");
  });

  navigation?.addEventListener("click", event => {
    if (event.target.closest("a")) closeMenu();
  });
  backdrop?.addEventListener("click", closeMenu);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeMenu();
  });
  window.addEventListener("resize", () => {
    if (window.matchMedia("(min-width: 901px)").matches) closeMenu();
  });
  window.addEventListener("scroll", () => {
    header?.classList.toggle("scrolled", window.scrollY > 24);
  }, { passive: true });

  document.querySelectorAll(".appear").forEach(element => {
    element.addEventListener("animationend", () => element.classList.add("is-in"), { once: true });
  });

  requestAnimationFrame(() => requestAnimationFrame(() => {
    document.querySelectorAll(".appear, .hero-photo").forEach(element => {
      const animations = element.getAnimations?.() || [];
      if (!animations.some(animation => ["running", "finished"].includes(animation.playState))) {
        element.classList.add("is-in");
      }
    });
  }));

  const reveals = document.querySelectorAll(".reveal");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reducedMotion || !("IntersectionObserver" in window)) {
    reveals.forEach(element => element.classList.add("visible"));
  } else {
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: .12, rootMargin: "0px 0px -40px" });
    reveals.forEach(element => observer.observe(element));
  }
})();
