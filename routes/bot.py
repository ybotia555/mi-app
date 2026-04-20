from flask import request, redirect, session

def init_bot_routes(app):

    # IMPORTS AQUÍ (evita error circular)
    from app_mysql import (
        db_query, get_tienda, hoy, tid_now, li, base,
        _hhmm, _fmt_msg, _prod_card, _chips_html,
        BOT_QUICK, bot_ia_respuesta
    )

    @app.route("/bot", methods=["GET","POST"])
    def bot():

        # 🔒 Validar sesión
        if not li():
            return redirect("/")

        # 🔄 Limpiar chat
        if request.args.get("clear"):
            session.pop("bot_hist", None)
            return redirect("/bot")

        tid = tid_now()

        # 📦 Productos
        prods = db_query(
            "SELECT * FROM productos WHERE tienda_id=%s ORDER BY cantidad DESC, nombre",
            (tid,), fetchall=True
        ) or []

        # 🎯 Promociones
        promos = db_query(
            "SELECT * FROM promociones WHERE tienda_id=%s AND activa=1 AND (hasta IS NULL OR hasta>=%s)",
            (tid, hoy()), fetchall=True
        ) or []

        # 🏪 Tienda
        t = get_tienda()

        # 💬 Historial
        hist = session.get("bot_hist", [])

        # ==============================
        # PROCESAR MENSAJE
        # ==============================
        if request.method == "POST":
            msg_raw = request.form.get("msg","").strip()

            if msg_raw:
                msg_show = BOT_QUICK.get(msg_raw, msg_raw)

                hist.append({
                    "quien":"Tú",
                    "texto":msg_show,
                    "prod":None,
                    "hora":_hhmm(),
                    "texto_raw":msg_show
                })

                resp_txt, prod_obj = bot_ia_respuesta(hist, t, prods, promos)

                prod_data = None
                if prod_obj:
                    prod_data = {
                        "nombre":prod_obj["nombre"],
                        "precio":float(prod_obj["precio"]),
                        "cantidad":prod_obj["cantidad"],
                        "unidad":prod_obj.get("unidad",""),
                        "img":prod_obj.get("img",""),
                        "categoria":prod_obj.get("categoria","")
                    }

                hist.append({
                    "quien":"Bot",
                    "texto":resp_txt,
                    "prod":prod_data,
                    "hora":_hhmm(),
                    "texto_raw":resp_txt
                })

                session["bot_hist"] = hist[-40:]

        # ==============================
        # MENSAJE INICIAL
        # ==============================
        if not hist:
            nom = t.get("nombre","la tienda")

            bienvenida = (
                f"¡Hola! 👋 Bienvenido a **{nom}**.\n\n"
                f"Soy tu asistente con Inteligencia Artificial.\n"
                f"Pregúntame sobre productos, precios, stock, pagos,\n"
                f"domicilios, devoluciones o lo que necesites.\n\n"
                f"También puedes **hablar con un agente** tocando 💬 abajo 👇"
            )

            hist = [{
                "quien":"Bot",
                "texto":bienvenida,
                "prod":None,
                "hora":_hhmm(),
                "texto_raw":bienvenida
            }]

            session["bot_hist"] = hist

        # ==============================
        # CONSTRUIR CHAT
        # ==============================
        msgs_html = ""

        for m in hist:
            hora = m.get("hora", _hhmm())

            if m["quien"] == "Tú":
                msgs_html += (
                    f'<div class="chat-row-r">'
                    f'<div class="chat-bub-r">{_fmt_msg(m["texto"])}</div>'
                    f'<div class="chat-meta-r">{hora} <span class="check-icon">✓✓</span></div>'
                    f'</div>'
                )
            else:
                card_html = _prod_card(m["prod"]) if m.get("prod") else ""

                msgs_html += (
                    f'<div class="chat-row-l">'
                    f'<div class="chat-av-l bot-av">🤖</div>'
                    f'<div>'
                    f'<div class="chat-bub-l">{_fmt_msg(m["texto"])}{card_html}</div>'
                    f'<div class="chat-meta-l">{hora}</div>'
                    f'</div></div>'
                )

        t_nom = t.get("nombre","")

        wa = t.get("whatsapp","").replace("+","").replace(" ","")
        wa_chip = (
            f'<a href="https://wa.me/{wa}" target="_blank" class="chip chip-wa">💬 WhatsApp</a>'
            if wa else ""
        )

        # ==============================
        # HTML FINAL
        # ==============================
        return base("🤖 Asistente Virtual",(
            f'<div class="phone-outer">'
            f'<div class="phone-device">'

            f'<div class="phone-notch">'
            f'<div class="phone-pill"><div class="phone-cam"></div><div class="phone-speaker"></div></div>'
            f'</div>'

            f'<div class="phone-bar bot-bar">'
            f'<div class="phone-bar-left">'
            f'<div class="phone-avatar">🤖</div>'
            f'<div>'
            f'<div class="phone-info-name">Asistente — {t_nom}</div>'
            f'<div class="phone-info-status"><div class="phone-status-dot"></div>IA · En línea 24/7</div>'
            f'</div></div>'
            f'<div class="phone-bar-actions">'
            f'<a href="/bot?clear=1" class="phone-bar-btn">🔄 Nueva</a>'
            f'</div></div>'

            f'<div class="phone-msgs" id="chat-box">{msgs_html}</div>'

            f'<div class="chips-section">'
            f'<div class="chips-label">Temas →</div>'
            f'<div class="chips-row">{_chips_html(tid)}{wa_chip}</div>'
            f'</div>'

            f'<form method="post" id="bform" style="display:contents">'
            f'<div class="phone-input-bar">'
            f'<input type="text" name="msg" class="phone-input" id="binput" placeholder="Escribe..." autocomplete="off">'
            f'<button type="submit" class="phone-send send-bot">➤</button>'
            f'</div></form>'

            f'</div></div>'

            f'<script>'
            f'var cb=document.getElementById("chat-box");'
            f'if(cb)cb.scrollTop=cb.scrollHeight;'
            f'</script>'
        ))
    