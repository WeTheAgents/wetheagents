/* MLB Betting Handbook — Client-side filtering & interaction */
(function(){
  'use strict';

  /* Strategy filtering */
  function initStrategyFilters(){
    var root = document.querySelector('[data-strat-root]');
    if(!root) return;
    var input = root.querySelector('[data-strat-search]');
    var statusSel = root.querySelector('[data-strat-status]');
    var marketSel = root.querySelector('[data-strat-market]');
    var items = root.querySelectorAll('[data-strat-item]');

    function filter(){
      var q = (input.value||'').toLowerCase();
      var st = statusSel.value;
      var mk = marketSel.value;
      items.forEach(function(el){
        var text = (el.getAttribute('data-strat-item')||'').toLowerCase();
        var elSt = el.getAttribute('data-status')||'';
        var elMk = el.getAttribute('data-market')||'';
        var show = true;
        if(q && text.indexOf(q)===-1) show=false;
        if(st && elSt!==st) show=false;
        if(mk && elMk!==mk) show=false;
        el.style.display = show?'':'none';
      });
    }
    if(input) input.addEventListener('input',filter);
    if(statusSel) statusSel.addEventListener('change',filter);
    if(marketSel) marketSel.addEventListener('change',filter);
  }

  /* Timeline filtering */
  function initTimelineFilters(){
    var root = document.querySelector('[data-tl-root]');
    if(!root) return;
    var statusSel = root.querySelector('[data-tl-status]');
    var items = root.querySelectorAll('[data-tl-item]');
    if(!statusSel) return;
    statusSel.addEventListener('change',function(){
      var st = statusSel.value;
      items.forEach(function(el){
        var elSt = el.getAttribute('data-tl-item')||'';
        el.style.display = (!st || elSt===st) ? '' : 'none';
      });
    });
  }

  /* Smooth scroll for anchor links */
  document.addEventListener('click',function(e){
    var a = e.target.closest('a[href^="#"]');
    if(!a) return;
    var target = document.querySelector(a.getAttribute('href'));
    if(target){
      e.preventDefault();
      target.scrollIntoView({behavior:'smooth',block:'start'});
    }
  });

  /* Init on load */
  document.addEventListener('DOMContentLoaded',function(){
    initStrategyFilters();
    initTimelineFilters();
    /* Mark active nav link */
    var path = location.pathname.split('/').pop()||'index.html';
    var links = document.querySelectorAll('.nav-list a');
    links.forEach(function(a){
      if(a.getAttribute('href')===path) a.classList.add('active');
    });
  });
})();
