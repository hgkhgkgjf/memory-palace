(function () {
  try {
    var normalizeLocale = function (value) {
      var locale = String(value || '').trim().toLowerCase();
      if (!locale) {
        return '';
      }
      if (locale === 'zh' || locale.indexOf('zh-') === 0) {
        return 'zh-CN';
      }
      if (locale === 'en' || locale.indexOf('en-') === 0) {
        return 'en';
      }
      return '';
    };
    var s = normalizeLocale(localStorage.getItem('memory-palace.locale'));
    if (!s) {
      var langs = navigator.languages || [navigator.language || 'en'];
      for (var i = 0; i < langs.length; i += 1) {
        s = normalizeLocale(langs[i]);
        if (s) {
          break;
        }
      }
    }
    document.documentElement.lang = s || 'en';
  } catch (e) {}
})();
