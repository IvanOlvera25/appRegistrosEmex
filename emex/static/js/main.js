// ---------- Barra de progreso ----------
function ensureProgressBar(){
    let bar = document.getElementById('saveProgressBar');
    if(!bar){
      bar = document.createElement('div');
      bar.id = 'saveProgressBar';
      document.body.appendChild(bar);
    }
    return bar;
  }
  
  // ---------- Helpers de validación ----------
  function setError(input, msg){
    clearError(input);
    input.classList.add('invalid');
    const small = document.createElement('div');
    small.className = 'error-text';
    small.textContent = msg;
    input.insertAdjacentElement('afterend', small);
  }
  function clearError(input){
    input.classList.remove('invalid');
    const next = input.nextElementSibling;
    if(next && next.classList.contains('error-text')) next.remove();
  }
  function attachTimeValidation(form){
    const total = form.querySelector('input[name="time_total"]');
    const prod  = form.querySelector('input[name="time_productive"]');
    if(!total || !prod) return;
    function check(){
      clearError(total); clearError(prod);
      const t = parseFloat(total.value || '0');
      const p = parseFloat(prod.value  || '0');
      if(total.value!=='' && prod.value!=='' && p > t){
        setError(prod, 'El tiempo productivo no puede exceder al tiempo total.');
        return false;
      }
      return true;
    }
    total.addEventListener('input', check);
    prod.addEventListener('input', check);
    form.addEventListener('submit', (e)=>{ if(!check()) e.preventDefault(); });
  }
  function attachFuelAutofill(){
    const fuelSi   = document.getElementById('fuel_si');
    const fuelTime = document.getElementById('fuel_time');
    if(!fuelSi || !fuelTime) return;
    fuelSi.addEventListener('change', ()=>{
      if(!fuelTime.value){
        const now=new Date(), p=n=>String(n).padStart(2,'0');
        fuelTime.value = `${now.getFullYear()}-${p(now.getMonth()+1)}-${p(now.getDate())}T${p(now.getHours())}:${p(now.getMinutes())}`;
      }
    });
  }
  function attachCharCount(){
    document.querySelectorAll('textarea[name="notes"]').forEach((ta)=>{
      const max = parseInt(ta.getAttribute('maxlength') || '300', 10);
      let counter = ta.parentElement.querySelector('.charcount');
      if(!counter){
        const wrap = document.createElement('div');
        wrap.className = 'char-meta';
        counter = document.createElement('small');
        counter.className = 'charcount';
        wrap.appendChild(counter);
        ta.insertAdjacentElement('afterend', wrap);
      }
      function update(){
        const len = ta.value.length;
        counter.textContent = `${len}/${max}`;
        counter.classList.remove('near','over');
        if(len > max){ counter.classList.add('over'); }
        else if(len > max*0.8){ counter.classList.add('near'); }
      }
      ta.setAttribute('maxlength', String(max));
      ta.addEventListener('input', update);
      update();
    });
  }
  
  // ---------- INIT único ----------
  document.addEventListener('DOMContentLoaded', ()=>{
    // flashes
    setTimeout(()=>{ document.querySelectorAll('.flash').forEach(el=>el.classList.add('hide')); }, 3500);
  
    // navbar móvil
    const btn = document.getElementById('navToggle');
    const menu = document.getElementById('navMenu');
    if(btn && menu){
      btn.addEventListener('click', ()=>{
        const open = menu.classList.toggle('show');
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      menu.querySelectorAll('a').forEach(a=>{
        a.addEventListener('click', ()=>{ menu.classList.remove('show'); btn.setAttribute('aria-expanded','false'); });
      });
    }
  
    // formularios generales
    document.querySelectorAll('form.smart-form').forEach(f=> attachTimeValidation(f));
    attachFuelAutofill();
    attachCharCount();
  
    // login: toggle ojo + spinner
    const toggle = document.getElementById('togglePass');
    const pass   = document.getElementById('password');
    if(toggle && pass){
      toggle.addEventListener('click', ()=>{
        const show = pass.getAttribute('type') === 'password';
        pass.setAttribute('type', show ? 'text' : 'password');
        toggle.textContent = show ? '🙈' : '👁';
        pass.focus();
      });
    }
    const loginForm = document.getElementById('loginForm');
    if(loginForm){
      loginForm.addEventListener('submit', ()=>{
        const btn = loginForm.querySelector('.auth-submit');
        if(btn){ btn.classList.add('is-loading'); }
      });
    }
  });
  
  // ---------- progreso en submit (sin cambiar texto del botón del login) ----------
  document.addEventListener('submit', (e)=>{
    const form = e.target;
    if(!form.classList.contains('smart-form')) return;
  
    const btn = form.querySelector('button[type="submit"]');
    if(btn){
      btn.disabled = true;
      if(!btn.classList.contains('auth-submit')) btn.textContent = 'Guardando…';
    }
  
    const bar = ensureProgressBar();
    let pct = 8;
    bar.style.opacity = '1';
    bar.style.width   = pct + '%';
    const timer = setInterval(()=>{
      pct = Math.min(pct + (Math.random()*15 + 5), 85);
      bar.style.width = pct + '%';
    }, 300);
    window.addEventListener('beforeunload', ()=> clearInterval(timer), { once:true });
  });
  
  // completar y ocultar barra al cargar
  window.addEventListener('pageshow', ()=>{
    const bar = document.getElementById('saveProgressBar');
    if(bar){
      bar.style.width = '100%';
      setTimeout(()=>{ bar.style.opacity='0'; }, 250);
      setTimeout(()=>{ bar.remove(); }, 800);
    }
  });
  // ===== Dashboard: filtros, tabs y export =====
(function(){
  const table = document.getElementById('opsTable');
  if(!table) return;

  // --- refs UI ---
  const body      = table.querySelector('tbody');
  const rows      = Array.from(body?.rows || []);
  const visibleEl = document.getElementById('visibleCount');

  const fFrom    = document.getElementById('fFrom');
  const fTo      = document.getElementById('fTo');
  const fProject = document.getElementById('fProject');
  const fUnit    = document.getElementById('fUnit');
  const fSI      = document.getElementById('fSI');
  const fOT      = document.getElementById('fOT');
  const fSearch  = document.getElementById('fSearch');

  const fActor   = document.getElementById('fActor');           // hidden (valor de las tabs)
  const tabs     = Array.from(document.querySelectorAll('.tab-actor'));

  const btnApply = document.getElementById('btnApply');
  const btnClear = document.getElementById('btnClear');
  const btnExport= document.getElementById('btnExport');

  // --- helpers ---
  const val = el => (el && (el.value || '')).trim().toLowerCase();
  const pad = n  => String(n).padStart(2,'0');

  function normalizeDateInput(d){
    // input date -> 'yyyy-mm-dd' (ya viene así); si no hay, ''
    return (d || '').trim();
  }

  function toggleRouteColumn(){
    // Oculta Ruta si el modo es Operadores
    if(fActor.value === 'operator'){ table.classList.add('hide-route'); }
    else                           { table.classList.remove('hide-route'); }
  }

  function applyFilters(){
    const from = normalizeDateInput(val(fFrom));
    const to   = normalizeDateInput(val(fTo));
    const q    = val(fSearch);

    const pr   = val(fProject);
    const mu   = val(fUnit);
    const sik  = val(fSI);
    const ot   = val(fOT);          // '1' / '0' / ''

    const kind = (fActor.value || '').toLowerCase(); // '' | 'driver' | 'operator'

    let visible = 0;

    rows.forEach(tr=>{
      let ok = true;

      const d  = tr.dataset.date || '';
      if(from && d < from) ok = false;
      if(to   && d > to  ) ok = false;

      if(kind && (tr.dataset.kind || '') !== kind) ok = false;
      if(pr   && (tr.dataset.project   || '') !== pr) ok = false;
      if(mu   && (tr.dataset.mainunit  || '') !== mu) ok = false;
      if(sik  && (tr.dataset.sikind    || '') !== sik) ok = false;
      if(ot   && (tr.dataset.over      || '') !== ot ) ok = false;

      if(q){
        const hay = (tr.dataset.text || '').includes(q);
        if(!hay) ok = false;
      }

      tr.style.display = ok ? '' : 'none';
      if(ok) visible++;
    });

    if(visibleEl) visibleEl.textContent = visible;
    toggleRouteColumn();
  }

  // --- tabs (Todos / Choferes / Operadores) ---
  tabs.forEach(btn=>{
    btn.addEventListener('click', ()=>{
      tabs.forEach(b=>b.classList.remove('is-active'));
      btn.classList.add('is-active');
      tabs.forEach(b=> b.setAttribute('aria-selected','false'));
      btn.setAttribute('aria-selected','true');

      fActor.value = btn.dataset.value || '';
      applyFilters();                      // aplicar al instante en tabs (más cómodo)
    });
  });

  // --- botón Aplicar y Limpiar ---
  btnApply?.addEventListener('click', applyFilters);
  fSearch?.addEventListener('keydown', (e)=>{ if(e.key === 'Enter'){ e.preventDefault(); applyFilters(); }});

  btnClear?.addEventListener('click', ()=>{
    [fFrom,fTo,fProject,fUnit,fSI,fOT,fSearch].forEach(el=>{ if(el) el.value=''; });
    // reset tab a "Todos"
    tabs.forEach(b=>{ b.classList.remove('is-active'); b.setAttribute('aria-selected','false'); });
    const all = tabs[0]; if(all){ all.classList.add('is-active'); all.setAttribute('aria-selected','true'); }
    if(fActor) fActor.value = '';
    applyFilters();
  });

  // --- export CSV (respeta filas visibles) ---
  btnExport?.addEventListener('click', ()=>{
    const headers = Array.from(table.querySelectorAll('thead th')).map(th=>th.textContent.trim());
    const out = [headers.join(',')];
    rows.forEach(tr=>{
      if(tr.style.display === 'none') return;
      const cells = Array.from(tr.children).map(td=>{
        const t = td.innerText.replace(/\s+/g,' ').trim();
        return `"${t.replaceAll('"','""')}"`;
      });
      out.push(cells.join(','));
    });
    const blob = new Blob([out.join('\n')], {type:'text/csv;charset=utf-8;'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `emex_registros_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
  });

  // init
  applyFilters();
})();

// --- Units: buscador de chips ---
(function(){
  const search = document.getElementById('unitSearch');
  const picker = document.getElementById('unitPicker');
  if(!search || !picker) return;
  const items = Array.from(picker.querySelectorAll('.chip-unit'));
  search.addEventListener('input', ()=>{
    const q = (search.value || '').trim().toLowerCase();
    items.forEach(a=>{
      const t = (a.getAttribute('data-text') || '').toLowerCase();
      a.style.display = q && !t.includes(q) ? 'none' : '';
    });
  });
})();
