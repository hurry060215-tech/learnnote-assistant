const menuButton = document.querySelector(".menu-button");
const navigation = document.querySelector(".site-header nav");

menuButton?.addEventListener("click", () => {
  const open = navigation?.classList.toggle("open") || false;
  menuButton.setAttribute("aria-expanded", String(open));
  menuButton.setAttribute("aria-label", open ? "关闭导航" : "打开导航");
});

navigation?.addEventListener("click", event => {
  if (!event.target.closest("a")) return;
  navigation.classList.remove("open");
  menuButton?.setAttribute("aria-expanded", "false");
  menuButton?.setAttribute("aria-label", "打开导航");
});
