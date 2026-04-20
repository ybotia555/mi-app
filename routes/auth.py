@app.route("/login/<tid>",methods=["GET","POST"])
def login(tid):
    t=get_tienda(tid)
    if not t or not t.get("activa"): return redirect("/")
    tab="login"; error=""; info=""
    if request.method=="POST":
        ac=request.form.get("accion","login")
        if ac=="login":
            u=request.form.get("user","").strip()
            p=request.form.get("pass","")
            usr=db_query("SELECT * FROM users WHERE user=%s AND tienda_id=%s",(u,tid),fetchone=True)
            if usr and check_password_hash(usr["password"],p):
                session.clear(); session["user"]=u; session["tienda_id"]=tid
                r=usr.get("rol","cliente")
                if r=="admin":       return redirect("/admin")
                if r=="empleado":    return redirect("/empleado")
                if r=="domiciliario":return redirect("/domi")
                if r=="proveedor":   return redirect("/prov")
                return redirect("/tienda")
            error='<div class="al a-d">⚠️ Usuario o contraseña incorrectos.</div>'

        elif ac=="solicitar":
            # Recuperar por USUARIO + TELÉFONO
            rec_user=request.form.get("rec_user","").strip()
            rec_tel=request.form.get("rec_tel","").strip()
            def norm_tel(n):
                n=str(n or "").replace(" ","").replace("-","").replace("+","")
                if n.startswith("57") and len(n)>10: n=n[2:]
                return n
            usr=db_query("SELECT * FROM users WHERE user=%s AND tienda_id=%s",(rec_user,tid),fetchone=True)
            tel_ok = usr and norm_tel(usr.get("telefono",""))==norm_tel(rec_tel)
            if usr and tel_ok:
                cod=gcode(6)
                db_query("DELETE FROM recuperacion WHERE user=%s AND tienda_id=%s",(usr["user"],tid),commit=True)
                db_query("INSERT INTO recuperacion(user,tienda_id,cod,fecha,usado) VALUES(%s,%s,%s,%s,0)",
                         (usr["user"],tid,cod,now()),commit=True)
                info=(
                    f'<div style="background:linear-gradient(135deg,#4f46e5,#818cf8);'
                    f'border-radius:14px;padding:20px;text-align:center;margin-bottom:14px">'
                    f'<p style="color:rgba(255,255,255,.85);font-size:.79rem;margin-bottom:8px">'
                    f'✅ Identidad verificada para <strong style="color:#fff">{rec_user}</strong></p>'
                    f'<p style="color:rgba(255,255,255,.7);font-size:.74rem;margin-bottom:10px">'
                    f'Tu código de recuperación es:</p>'
                    f'<div style="font-size:2.8rem;font-weight:900;letter-spacing:.55em;color:#fff;'
                    f'background:rgba(255,255,255,.15);border-radius:10px;padding:12px 18px;'
                    f'display:inline-block;margin-bottom:8px;font-family:monospace">{cod}</div>'
                    f'<p style="color:rgba(255,255,255,.6);font-size:.72rem">'
                    f'⏱ Válido por 30 minutos · Úsalo en el formulario de abajo ↓</p>'
                    f'</div>'
                )
            elif usr and not tel_ok:
                error='<div class="al a-d">⚠️ El teléfono no coincide con el registrado para ese usuario.</div>'
            else:
                error='<div class="al a-d">⚠️ Usuario no encontrado en esta tienda.</div>'
            tab="recuperar"

        elif ac=="cambiar":
            rec_user2=request.form.get("rec_user2","").strip()
            cod=request.form.get("cod","").strip()
            nueva=request.form.get("np","")
            usr=db_query("SELECT * FROM users WHERE user=%s AND tienda_id=%s",(rec_user2,tid),fetchone=True)
            tok=None
            if usr:
                tok=db_query("SELECT * FROM recuperacion WHERE user=%s AND tienda_id=%s AND cod=%s AND usado=0",
                             (usr["user"],tid,cod),fetchone=True)
            ok,mp=ok_pass(nueva)
            if not usr:
                error='<div class="al a-d">⚠️ Usuario no encontrado.</div>'
            elif not tok:
                error='<div class="al a-d">⚠️ Código incorrecto o ya usado.</div>'
            elif not ok:
                error=f'<div class="al a-d">⚠️ {mp}</div>'
            else:
                db_query("UPDATE users SET password=%s WHERE id=%s",
                         (generate_password_hash(nueva),usr["id"]),commit=True)
                db_query("UPDATE recuperacion SET usado=1 WHERE id=%s",(tok["id"],),commit=True)
                info='<div class="al a-s">✅ Contraseña actualizada. Ya puedes ingresar.</div>'
                tab="login"

    pc=t.get("color","#4f46e5")
    tl="ac" if tab=="login" else ""
    tr="ac" if tab=="recuperar" else ""
    dpl="" if tab=="login" else "display:none"
    dpr="" if tab=="recuperar" else "display:none"
    el=error if tab=="login" else ""
    il=info  if tab=="login" else ""
    er=error if tab=="recuperar" else ""
    ir=info  if tab=="recuperar" else ""
    Q="'"
    return (f"<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Acceso &middot; {t['nombre']}</title>"
            f"<style>{css(pc)}</style></head><body>"
            f'<div class="lp" {lbg(pc)}><div class="lp-bg"></div><div class="lc">'
            f'<div class="llo">'
            f'<span class="li2">{t.get("emoji","🏪")}</span>'
            f'<h1>{t["nombre"]}</h1>'
            f'<p>{t.get("tipo","")} &middot; {t.get("ciudad","")}</p>'
            f'</div>'
            f'<div class="lt">'
            f'<button class="lt-b {tl}" onclick="st({Q}l{Q})">🔐 Ingresar</button>'
            f'<button class="lt-b {tr}" onclick="st({Q}r{Q})">🔑 Recuperar clave</button>'
            f'</div>'
            # ── Panel Login ──
            f'<div id="pl" style="{dpl}">{el}{il}'
            f'<form method="post" style="display:flex;flex-direction:column;gap:14px">'
            f'<input type="hidden" name="accion" value="login">'
            f'<div class="fg"><label>👤 Usuario</label>'
            f'<div class="input-icon"><span class="icon">👤</span>'
            f'<input type="text" name="user" placeholder="Tu usuario" required autofocus></div></div>'
            f'<div class="fg"><label>🔒 Contraseña</label>'
            f'<div class="input-pw">'
            f'<input type="password" id="pw1" name="pass" placeholder="Tu contraseña" required>'
            f'<span class="pw-eye" onclick="tpw({Q}pw1{Q},this)">👁</span>'
            f'</div></div>'
            f'<button class="btn bp blg bbl" style="font-size:.9rem">Ingresar →</button>'
            f'</form>'
            f'<a href="/registro/{tid}" class="btn bg bbl" style="margin-top:10px">✨ Crear cuenta</a>'
            f'</div>'
            # ── Panel Recuperar ──
            f'<div id="pr" style="{dpr}">{er}{ir}'
            f'<div class="al a-i" style="font-size:.79rem;margin-bottom:14px">'
            f'🔑 Identifícate con tu <strong>usuario</strong> y <strong>teléfono</strong> '
            f'para obtener un código de recuperación.</div>'
            # Paso 1: obtener código
            f'<div style="background:#f8faff;border-radius:12px;padding:14px;'
            f'border:1px solid var(--bd);margin-bottom:14px">'
            f'<p style="font-size:.72rem;font-weight:800;color:var(--mt);margin-bottom:10px">'
            f'PASO 1 — Verificar identidad</p>'
            f'<form method="post" style="display:flex;flex-direction:column;gap:9px">'
            f'<input type="hidden" name="accion" value="solicitar">'
            f'<div class="fg"><label>👤 Tu usuario</label>'
            f'<div class="input-icon"><span class="icon">👤</span>'
            f'<input type="text" name="rec_user" placeholder="Escribe tu usuario" required></div></div>'
            f'<div class="fg"><label>📱 Tu teléfono registrado</label>'
            f'<div class="input-icon"><span class="icon">📱</span>'
            f'<input type="tel" name="rec_tel" placeholder="3101234567" required></div>'
            f'<span class="ph">El mismo teléfono que pusiste al registrarte.</span>'
            f'</div>'
            f'<button class="btn bw2 bbl">🔍 Verificar y obtener código</button>'
            f'</form></div>'
            # Paso 2: cambiar contraseña
            f'<div style="background:#f8faff;border-radius:12px;padding:14px;border:1px solid var(--bd)">'
            f'<p style="font-size:.72rem;font-weight:800;color:var(--mt);margin-bottom:10px">'
            f'PASO 2 — Cambiar contraseña (con el código obtenido arriba)</p>'
            f'<form method="post" style="display:flex;flex-direction:column;gap:9px">'
            f'<input type="hidden" name="accion" value="cambiar">'
            f'<div class="fg"><label>👤 Usuario</label>'
            f'<input type="text" name="rec_user2" placeholder="Tu usuario" required></div>'
            f'<div class="fg"><label>🔢 Código de 6 dígitos</label>'
            f'<input type="text" name="cod" placeholder="• • • • • •" maxlength="6" required '
            f'style="letter-spacing:.5em;font-size:1.4rem;font-weight:900;text-align:center;'
            f'font-family:monospace"></div>'
            f'<div class="fg"><label>🔐 Nueva contraseña</label>'
            f'<div class="input-pw">'
            f'<input type="password" id="pw3" name="np" '
            f'placeholder="Nueva contraseña segura" required>'
            f'<span class="pw-eye" onclick="tpw({Q}pw3{Q},this)">👁</span>'
            f'</div>'
            f'<span class="ph">Mínimo 8 · 1 MAYÚSCULA · 1 número · 1 especial (!@#$%^&amp;*)</span>'
            f'</div>'
            f'<button class="btn bs bbl">🔐 Cambiar contraseña</button>'
            f'</form></div>'
            f'</div>'
            f'<a href="/" style="display:block;text-align:center;margin-top:16px;'
            f'font-size:.72rem;color:var(--mt)">&larr; Volver al inicio</a>'
            f'</div></div>'
            f"<script>"
            f"function st(t){{"
            f"  document.getElementById('pl').style.display=t==='l'?'':'none';"
            f"  document.getElementById('pr').style.display=t==='r'?'':'none';"
            f"  document.querySelectorAll('.lt-b').forEach(function(b,i){{"
            f"    b.classList.toggle('ac',(i===0&&t==='l')||(i===1&&t==='r'));}});}}"
            f"function tpw(id,el){{"
            f"  var i=document.getElementById(id);"
            f"  i.type=i.type==='password'?'text':'password';"
            f"  el.textContent=i.type==='text'?'🙈':'👁';}}"
            f"</script></body></html>")