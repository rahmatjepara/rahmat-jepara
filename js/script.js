const menuToggle = document.getElementById("menuToggle");
const navMenu = document.querySelector(".nav-menu");

menuToggle.addEventListener("click", function () {
    navMenu.classList.toggle("show");
});