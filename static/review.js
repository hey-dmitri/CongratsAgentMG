// review.js — Congrats Agent frontend helpers
// Loaded on every page via base.html

document.addEventListener('DOMContentLoaded', function () {
  // Auto-dismiss alerts after 6 seconds
  document.querySelectorAll('.alert.fade.show').forEach(function (el) {
    setTimeout(function () {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
      bsAlert.close();
    }, 6000);
  });
});
