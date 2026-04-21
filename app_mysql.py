# ================================================================
#  GESTORPRO v13.0 — Sistema Multi-Tienda PREMIUM
#  Colombia — Panaderías, Abarrotes y más
#
#  INSTALAR:  pip install flask werkzeug reportlab pymysql
#  EJECUTAR:  python app_mysql.py  →  http://127.0.0.1:5000
#
#  SUPER ADMIN → http://127.0.0.1:5000/super
#    usuario: superadmin  |  clave: Super@1234!

#  NUEVAS FEATURES v13:
#   ✅ Pasarela de pago: Nequi/Daviplata/Efectivo con instrucciones
#   ✅ Recuperación de contraseña por email (simulado con código)
#   ✅ Contraseña con caracteres especiales validados
#   ✅ Módulo de proveedor completo
#   ✅ Bot con imágenes, botones y preguntas abiertas
#   ✅ Promociones por tienda en bot y tienda
#   ✅ Devoluciones completo cliente+admin
#   ✅ Stock por tienda
#   ✅ CRUD domiciliarios (método crudo)
#   ✅ Checkbox tratamiento de datos
#   ✅ Empleado: proveedores, alertas, mermar stock
#   ✅ Super Admin: solo crea tiendas y credenciales
#   ✅ Exportar historial PDF por rango de fechas
#   ✅ Borrar registros desde admin/empleado
#   ✅ BD y tablas se crean automáticamente
# ================================================================

from flask import Flask, request, redirect, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors as pdf_colors
from datetime import datetime, timedelta
from dbutils.pooled_db import PooledDB
import random, io, string, re, json
import pymysql, pymysql.cursors

app = Flask(__name__)
app.secret_key = "gestorpro_v13_ultra_secure_2025"

# ================================================================
#  CONFIG MySQL — CAMBIA host/user/password
# ================================================================
import os

DB_HOST     = os.getenv("DB_HOST")
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME     = os.getenv("DB_NAME")
DB_PORT     = int(os.getenv("DB_PORT", 3306))

# ================================================================
#  CONEXION
# ================================================================
_DB_POOL = None  # Se inicializa en la primera llamada

def _get_pool():
    global _DB_POOL
    if _DB_POOL is None:
        try:
            from dbutils.pooled_db import PooledDB
            _DB_POOL = PooledDB(
                creator=pymysql,
                mincached=3,      # conexiones mínimas siempre abiertas
                maxcached=10,     # máximo en pool
                maxconnections=20,# máximo total simultáneas
                blocking=True,    # espera si no hay disponibles
                host=DB_HOST,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME,
                port=DB_PORT,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True,
                connect_timeout=10,
                read_timeout=30,
                write_timeout=30,
            )
        except ImportError:
            # Si no está dbutils, usa reconexión simple optimizada
            _DB_POOL = "SIMPLE"
    return _DB_POOL


def get_db():
    """Obtiene conexión del pool (o crea una si no hay pool)."""
    pool = _get_pool()
    if pool == "SIMPLE":
        return pymysql.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
            database=DB_NAME, port=DB_PORT, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor, autocommit=True,
            connect_timeout=10, read_timeout=30, write_timeout=30,
        )
    return pool.connection()


def db_query(sql, p=(), fetchone=False, fetchall=False, commit=False):
    """
    Ejecuta una query usando el pool de conexiones.
    Las conexiones se devuelven al pool automáticamente (no se cierran).
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, p)
            if commit:
                conn.commit()
            if fetchone:
                return cur.fetchone()
            if fetchall:
                return cur.fetchall()
            return cur.lastrowid
    except pymysql.err.OperationalError:
        # Reconexión automática si la conexión expiró
        try:
            conn.ping(reconnect=True)
            with conn.cursor() as cur:
                cur.execute(sql, p)
                if commit: conn.commit()
                if fetchone: return cur.fetchone()
                if fetchall: return cur.fetchall()
                return cur.lastrowid
        except Exception:
            return None
    finally:
        conn.close()  # Devuelve al pool, no cierra realmente


def db_multi(queries_params):
    """
    Ejecuta múltiples queries en UNA sola conexión del pool.
    Úsala cuando necesites 2+ queries seguidas (mucho más rápido).
    queries_params = [(sql, params, fetchone, fetchall), ...]
    Retorna lista de resultados en el mismo orden.
    """
    conn = get_db()
    results = []
    try:
        with conn.cursor() as cur:
            for item in queries_params:
                sql   = item[0]
                p     = item[1] if len(item) > 1 else ()
                fo    = item[2] if len(item) > 2 else False
                fa    = item[3] if len(item) > 3 else False
                cur.execute(sql, p)
                if fo:   results.append(cur.fetchone())
                elif fa: results.append(cur.fetchall())
                else:    results.append(cur.lastrowid)
    finally:
        conn.close()
    return results

# ================================================================
#  init_db — CREA BD Y TABLAS AUTOMÁTICAMENTE
# ================================================================
def init_db():
    # Paso 2: crear todas las tablas
    conn = get_db()
    try:
        with conn.cursor() as cur:

             # Tabla de chat en vivo persistente
            cur.execute("""CREATE TABLE IF NOT EXISTS chat_live(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                sesion_id VARCHAR(50) NOT NULL,
                cliente VARCHAR(100) NOT NULL,
                agente VARCHAR(100),
                mensaje TEXT NOT NULL,
                de_quien VARCHAR(20) DEFAULT 'cliente',
                leido TINYINT(1) DEFAULT 0,
                fecha VARCHAR(20),
                ultima_actividad DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                cerrado TINYINT(1) DEFAULT 0,
                INDEX idx_chat_tid(tienda_id),
                INDEX idx_chat_sid(sesion_id),
                INDEX idx_chat_act(ultima_actividad)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            # Tabla de sesiones de chat (para control de inactividad)
            cur.execute("""CREATE TABLE IF NOT EXISTS chat_sesiones(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                sesion_id VARCHAR(50) UNIQUE NOT NULL,
                cliente VARCHAR(100) NOT NULL,
                agente VARCHAR(100),
                estado VARCHAR(20) DEFAULT 'activo',
                creada DATETIME DEFAULT CURRENT_TIMESTAMP,
                ultima_actividad DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                cerrada DATETIME,
                INDEX idx_cs_tid(tienda_id),
                INDEX idx_cs_sid(sesion_id),
                INDEX idx_cs_act(ultima_actividad)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            # Tabla de aprendizaje del bot (conversaciones para mejorar)
            cur.execute("""CREATE TABLE IF NOT EXISTS bot_aprendizaje(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                pregunta TEXT NOT NULL,
                respuesta TEXT NOT NULL,
                util TINYINT(1) DEFAULT 1,
                fecha VARCHAR(20),
                veces_usada INT DEFAULT 1,
                INDEX idx_ba_tid(tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS superusers(
                id INT AUTO_INCREMENT PRIMARY KEY,
                user VARCHAR(100) UNIQUE NOT NULL,
                nombre VARCHAR(200),
                password VARCHAR(512) NOT NULL,
                email VARCHAR(200)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            # 👉 aquí dejas TODAS tus demás tablas
            # NO borres nada más de tu código

    finally:
        conn.close()

    # Paso 2: crear todas las tablas
    conn = get_db()
    try:
        with conn.cursor() as cur:

            cur.execute("""CREATE TABLE IF NOT EXISTS superusers(
                id INT AUTO_INCREMENT PRIMARY KEY,
                user VARCHAR(100) UNIQUE NOT NULL,
                nombre VARCHAR(200),
                password VARCHAR(512) NOT NULL,
                email VARCHAR(200)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS tiendas(
                id VARCHAR(100) PRIMARY KEY,
                nombre VARCHAR(200) NOT NULL,
                tipo VARCHAR(100) DEFAULT 'Tienda',
                ciudad VARCHAR(100) DEFAULT 'Fusagasuga',
                telefono VARCHAR(50),
                whatsapp VARCHAR(50),
                whatsapp_msg TEXT,
                nit VARCHAR(50),
                banco VARCHAR(100),
                cuenta VARCHAR(100),
                color VARCHAR(20) DEFAULT '#4f46e5',
                emoji VARCHAR(20) DEFAULT '🏪',
                horario VARCHAR(200),
                direccion VARCHAR(300),
                activa TINYINT(1) DEFAULT 1,
                creada VARCHAR(20)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS recuperacion(
                id INT AUTO_INCREMENT PRIMARY KEY,
                user VARCHAR(100) NOT NULL,
                tienda_id VARCHAR(100) NOT NULL,
                cod VARCHAR(10) NOT NULL,
                fecha VARCHAR(20),
                usado TINYINT(1) DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS users(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                user VARCHAR(100) NOT NULL,
                nombre VARCHAR(200),
                password VARCHAR(512) NOT NULL,
                rol VARCHAR(50) DEFAULT 'cliente',
                email VARCHAR(200),
                telefono VARCHAR(50),
                tratamiento_datos TINYINT(1) DEFAULT 1,
                fecha VARCHAR(20),
                INDEX idx_u(tienda_id),
                UNIQUE KEY uq_ut(user,tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS productos(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                nombre VARCHAR(200) NOT NULL,
                categoria VARCHAR(100) DEFAULT 'General',
                precio DECIMAL(12,2) DEFAULT 0,
                cantidad INT DEFAULT 0,
                stock_min INT DEFAULT 5,
                stock_max INT DEFAULT 100,
                unidad VARCHAR(50) DEFAULT 'unidad',
                img TEXT,
                INDEX idx_p(tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS pedidos(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                codigo VARCHAR(20),
                user VARCHAR(100),
                producto TEXT,
                cantidad INT DEFAULT 1,
                precio DECIMAL(12,2) DEFAULT 0,
                subtotal DECIMAL(12,2) DEFAULT 0,
                items LONGTEXT,
                pago VARCHAR(50) DEFAULT 'Efectivo',
                comprobante_enviado TINYINT(1) DEFAULT 0,
                entrega VARCHAR(50) DEFAULT 'recogida',
                direccion VARCHAR(300),
                estado VARCHAR(50) DEFAULT 'Pendiente',
                fecha VARCHAR(20),
                cancelable_hasta VARCHAR(20),
                INDEX idx_pe(tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS caja(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                tipo VARCHAR(20) NOT NULL,
                monto DECIMAL(14,2) DEFAULT 0,
                descripcion VARCHAR(300),
                fecha VARCHAR(20),
                INDEX idx_c(tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS proveedores(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                nombre VARCHAR(200),
                contacto VARCHAR(200),
                telefono_prov VARCHAR(50),
                producto VARCHAR(200),
                cantidad VARCHAR(50),
                precio_unit DECIMAL(12,2) DEFAULT 0,
                condicion VARCHAR(200),
                estado VARCHAR(50) DEFAULT 'Solicitado',
                fecha VARCHAR(20),
                INDEX idx_prov(tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS movimientos(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                nombre VARCHAR(200),
                tipo VARCHAR(50),
                cant INT DEFAULT 0,
                motivo VARCHAR(300),
                fecha VARCHAR(20),
                user VARCHAR(100),
                INDEX idx_mov(tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS recetas(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                nombre VARCHAR(200),
                ing TEXT,
                uds INT DEFAULT 1,
                desc_ VARCHAR(300),
                fecha VARCHAR(20),
                INDEX idx_rec(tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS produccion(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                receta VARCHAR(200),
                lotes INT DEFAULT 1,
                unids INT DEFAULT 0,
                fecha VARCHAR(20),
                user VARCHAR(100),
                INDEX idx_prod(tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS notificaciones(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                mensaje TEXT,
                leida TINYINT(1) DEFAULT 0,
                fecha VARCHAR(20),
                INDEX idx_not(tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS promociones(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                titulo VARCHAR(200),
                descripcion TEXT,
                descuento VARCHAR(50),
                desde VARCHAR(20),
                hasta VARCHAR(20),
                pids TEXT,
                activa TINYINT(1) DEFAULT 1,
                color VARCHAR(20) DEFAULT '#ef4444',
                color2 VARCHAR(20) DEFAULT '#f97316',
                fecha VARCHAR(20),
                INDEX idx_promo(tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS devoluciones(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                pedido_id INT DEFAULT 0,
                codigo VARCHAR(20),
                user VARCHAR(100),
                motivo TEXT,
                tipo_solicitud VARCHAR(20) DEFAULT 'devolucion',
                producto_cambio VARCHAR(200),
                estado VARCHAR(50) DEFAULT 'Pendiente',
                fecha VARCHAR(20),
                subtotal DECIMAL(12,2) DEFAULT 0,
                INDEX idx_dev(tienda_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            cur.execute("""CREATE TABLE IF NOT EXISTS chat_live(
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id VARCHAR(100) NOT NULL,
                cliente VARCHAR(100) NOT NULL,
                agente VARCHAR(100),
                mensaje TEXT NOT NULL,
                de_quien VARCHAR(20) DEFAULT 'cliente',
                leido TINYINT(1) DEFAULT 0,
                fecha VARCHAR(20),
                sesion_id VARCHAR(50),
                INDEX idx_chat_tid(tienda_id),
                INDEX idx_chat_sid(sesion_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

        conn.commit()
        print("  ✅ Base de datos y tablas listas.")
    finally:
        conn.close()

# ================================================================
#  DEMO DATA
# ================================================================
def init_demo():
    init_db()
    if not db_query("SELECT id FROM superusers WHERE user=%s",("superadmin",),fetchone=True):
        db_query("INSERT INTO superusers(user,nombre,password,email) VALUES(%s,%s,%s,%s)",
                 ("superadmin","Super Admin GestorPro",generate_password_hash("Super@1234!"),"super@gestorpro.co"),commit=True)

    if not db_query("SELECT id FROM tiendas WHERE id=%s",("panaderia1",),fetchone=True):
        db_query("INSERT INTO tiendas(id,nombre,tipo,ciudad,telefono,whatsapp,whatsapp_msg,nit,banco,cuenta,color,emoji,horario,direccion,activa,creada) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)",
                 ("panaderia1","Panaderia El Trigo Dorado","Panaderia","Fusagasuga","3101111111","573101111111",
                  "Hola! Me interesa hacer un pedido en El Trigo Dorado.","900111222-1","Bancolombia","123-456789-00",
                  "#b45309","🥐","Lun-Sab 6:00AM-7:00PM | Dom 7:00AM-2:00PM","Calle 5 # 3-20, Centro",now()),commit=True)
        db_query("INSERT INTO tiendas(id,nombre,tipo,ciudad,telefono,whatsapp,whatsapp_msg,nit,banco,cuenta,color,emoji,horario,direccion,activa,creada) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)",
                 ("tienda1","Abarrotes La Economia","Abarrotes","Fusagasuga","3202222222","573202222222",
                  "Hola! Me interesa hacer un pedido en La Economia.","900333444-2","Davivienda","987-654321-00",
                  "#15803d","🛒","Lun-Dom 7:00AM-9:00PM","Carrera 6 # 8-15, Las Palmas",now()),commit=True)

    if not db_query("SELECT id FROM users WHERE tienda_id=%s",("panaderia1",),fetchone=True):
        conn=get_db()
        try:
            with conn.cursor() as cur:
                for row in [
                    ("panaderia1","admin1","Carlos Mendez",generate_password_hash("Admin@1234!"),"admin","admin@trigo.com","3101234567"),
                    ("panaderia1","empleado1","Maria Lopez",generate_password_hash("Emp@1234!"),"empleado","emp@trigo.com","3107654321"),
                    ("panaderia1","domicilio1","Juan Perez",generate_password_hash("Dom@1234!"),"domiciliario","dom@trigo.com","3153333333"),
                    ("panaderia1","proveedor1","Distribuidora XYZ",generate_password_hash("Prov@1234!"),"proveedor","prov@trigo.com","3164444444"),
                    ("panaderia1","cliente1","Ana Garcia",generate_password_hash("Cli@1234!"),"cliente","ana@email.com","3175555555"),
                ]:
                    cur.execute("INSERT INTO users(tienda_id,user,nombre,password,rol,email,telefono) VALUES(%s,%s,%s,%s,%s,%s,%s)",row)
                for p in [
                    ("panaderia1","Pan Frances","Panaderia",500,80,10,200,"unidad","https://images.unsplash.com/photo-1549931319-a545dcf3bc7c?w=400"),
                    ("panaderia1","Croissant","Panaderia",2500,30,8,80,"unidad","https://images.unsplash.com/photo-1555507036-ab1f4038808a?w=400"),
                    ("panaderia1","Harina de Trigo","Insumos",4500,3,5,100,"kg","https://images.unsplash.com/photo-1586444248902-2f64eddc13df?w=400"),
                    ("panaderia1","Arepa de Choclo","Panaderia",1500,50,10,150,"unidad","https://images.unsplash.com/photo-1627308595229-7830a5c91f9f?w=400"),
                    ("panaderia1","Cafe Molido 250g","Bebidas",8500,20,5,60,"unidad","https://images.unsplash.com/photo-1559056199-641a0ac8b55e?w=400"),
                    ("panaderia1","Mantequilla 500g","Insumos",6500,15,5,50,"unidad","https://images.unsplash.com/photo-1589985270826-4b7bb135bc9d?w=400"),
                ]:
                    cur.execute("INSERT INTO productos(tienda_id,nombre,categoria,precio,cantidad,stock_min,stock_max,unidad,img) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",p)
            conn.commit()
        finally:
            conn.close()

    if not db_query("SELECT id FROM users WHERE tienda_id=%s",("tienda1",),fetchone=True):
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS comprobantes(
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    tienda_id VARCHAR(100) NOT NULL,
                    pedido_id INT NOT NULL,
                    codigo VARCHAR(20),
                    nombre_archivo VARCHAR(300),
                    datos LONGBLOB,
                    mimetype VARCHAR(100) DEFAULT 'image/jpeg',
                    fecha VARCHAR(20),
                    revisado TINYINT(1) DEFAULT 0,
                    INDEX idx_tienda (tienda_id),
                    INDEX idx_pedido (pedido_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

                cur.execute("INSERT INTO users(tienda_id,user,nombre,password,rol,email,telefono) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                            ("tienda1","admin2","Pedro Suarez",generate_password_hash("Admin@1234!"),"admin","admin@economia.com","3201234567"))

                cur.execute("INSERT INTO users(tienda_id,user,nombre,password,rol,email,telefono) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                            ("tienda1","cliente2","Roberto Silva",generate_password_hash("Cli@1234!"),"cliente","rob@email.com","3215555555"))

                for p in [
                    ("tienda1","Arroz 1kg","Granos",3800,100,20,300,"kg","https://images.unsplash.com/photo-1536304993881-ff86d42818ef?w=400"),
                    ("tienda1","Aceite Girasol 1L","Aceites",9500,40,10,100,"litro","https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?w=400"),
                    ("tienda1","Azucar x Kg","Insumos",3800,2,10,150,"kg","https://images.unsplash.com/photo-1574316071802-0d684efa7bf5?w=400"),
                ]:
                    cur.execute("INSERT INTO productos(tienda_id,nombre,categoria,precio,cantidad,stock_min,stock_max,unidad,img) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",p)

            conn.commit()
        finally:
            conn.close()

    print("  ✅ Datos demo listos.")

# ================================================================
#  HELPERS
# ================================================================
def tid_now(): return session.get("tienda_id")
def now(): return datetime.now().strftime("%Y-%m-%d %H:%M")
def hoy(): return datetime.now().strftime("%Y-%m-%d")
def fmt(n):
    try: return "$ {:,}".format(int(float(n))).replace(",",".")
    except: return "$ 0"
def gcode(n=6): return "".join(random.choices(string.digits,k=n))

def ok_pass(p):
    """Valida contraseña. Retorna (ok, mensaje_error)."""
    errores=[]
    if len(p)<8:                                          errores.append("Mínimo 8 caracteres")
    if not re.search(r"[A-Z]",p):                         errores.append("Al menos 1 letra MAYÚSCULA (A-Z)")
    if not re.search(r"\d",p):                            errores.append("Al menos 1 número (0-9)")
    if not re.search(r"[!@#$%^&*()\-_=+\[\]{};:,.<>?]",p): errores.append("Al menos 1 especial (!@#$%^&*)")
    if errores: return False, errores[0]
    return True,""

def ok_email(e): return bool(re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$",e))

def get_tienda(tid=None):
    t = tid or tid_now()
    if not t: return {}
    # Cache en session para evitar query en cada request
    cache_key = f"_tienda_{t}"
    if cache_key in session:
        return session[cache_key]
    row = db_query("SELECT * FROM tiendas WHERE id=%s", (t,), fetchone=True)
    result = dict(row) if row else {}
    if result:
        # Guarda por 5 minutos (se limpia con el logout)
        session[cache_key] = result
    return result

def get_su():
    if session.get("superadmin"): return {"user":"superadmin","nombre":"Super Admin","rol":"superadmin"}
    if session.get("user") and tid_now():
        row=db_query("SELECT * FROM users WHERE user=%s AND tienda_id=%s",(session["user"],tid_now()),fetchone=True)
        return dict(row) if row else None
    return None

def rol():
    if session.get("superadmin"): return "superadmin"
    u=get_su(); return u.get("rol") if u else None

def li():    return bool(session.get("superadmin") or (session.get("user") and tid_now()))
def is_sa(): return bool(session.get("superadmin"))
def is_ad(): return rol()=="admin"
def is_st(): return rol() in ("admin","empleado")
def is_dm(): return rol()=="domiciliario"
def is_pv(): return rol()=="proveedor"
def is_cl(): return rol()=="cliente"
def is_em(): return rol()=="empleado"

# ================================================================
#  CSS PREMIUM
# ================================================================
def css(primary="#4f46e5"):
    return """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;0,900;1,400&display=swap');
:root{
  --bg:#f0f4ff;--sf:#fff;--bd:#e2e8f4;--pr:"""+primary+""";
  --dn:#ef4444;--sc:#10b981;--wn:#f59e0b;--tx:#1e293b;--mt:#64748b;
  --sb:#0f0d2a;--wa:#25D366;--dm:#0ea5e9;--pv:#8b5cf6;
  --nq:#5f259f;--dv:#E40046;
  --shadow-sm:0 1px 3px rgba(0,0,0,.08),0 1px 2px rgba(0,0,0,.06);
  --shadow:0 4px 12px rgba(0,0,0,.08),0 2px 4px rgba(0,0,0,.04);
  --shadow-lg:0 10px 32px rgba(0,0,0,.12),0 4px 8px rgba(0,0,0,.06);
  --shadow-xl:0 20px 56px rgba(0,0,0,.2),0 8px 16px rgba(0,0,0,.08);
  --radius:14px;--radius-sm:9px;--radius-lg:20px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Plus Jakarta Sans',sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;-webkit-font-smoothing:antialiased}
a{text-decoration:none;color:inherit}

/* ══ SIDEBAR ══════════════════════════════════════════════════ */
.sidebar{width:252px;background:var(--sb);position:fixed;top:0;left:0;height:100vh;
  overflow-y:auto;z-index:200;display:flex;flex-direction:column;
  box-shadow:4px 0 28px rgba(0,0,0,.25)}
.sl{padding:22px 18px 16px;border-bottom:1px solid rgba(255,255,255,.07)}
.sl .li{font-size:2.1rem;display:block;margin-bottom:5px}
.sl h1{color:#fff;font-size:1.08rem;font-weight:900;letter-spacing:-.02em}
.sl p{color:rgba(255,255,255,.28);font-size:.6rem;margin-top:3px;letter-spacing:.1em;text-transform:uppercase}
.sidebar nav{padding:10px 0;flex:1}
.nav-section{padding:14px 18px 4px;font-size:.57rem;font-weight:800;
  color:rgba(255,255,255,.18);text-transform:uppercase;letter-spacing:.14em}
.ni{display:flex;align-items:center;gap:10px;padding:10px 18px;
  color:rgba(255,255,255,.52);font-size:.83rem;font-weight:500;
  border-left:3px solid transparent;transition:all .16s;cursor:pointer;margin:1px 0}
.ni:hover{background:rgba(255,255,255,.07);color:#fff;border-left-color:rgba(255,255,255,.2);padding-left:22px}
.ni.ac{background:linear-gradient(90deg,rgba(255,255,255,.13),rgba(255,255,255,.05));
  color:#fff;border-left-color:var(--pr);font-weight:700}
.ni .ic{font-size:.95rem;width:18px;text-align:center;flex-shrink:0}
.nb{margin-left:auto;background:var(--dn);color:#fff;font-size:.56rem;font-weight:800;
  padding:2px 6px;border-radius:99px;animation:nb-pulse 2s infinite}
@keyframes nb-pulse{0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,.4)}50%{box-shadow:0 0 0 4px rgba(239,68,68,0)}}
.sf2{padding:14px 18px;border-top:1px solid rgba(255,255,255,.07)}
.up{display:flex;align-items:center;gap:10px;background:rgba(255,255,255,.07);
  border-radius:11px;padding:10px 12px}
.av{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  color:#fff;font-weight:800;font-size:.88rem;flex-shrink:0;
  background:linear-gradient(135deg,var(--pr),#818cf8)}
.un{color:#fff;font-size:.81rem;font-weight:700}
.ur{font-size:.62rem;color:rgba(255,255,255,.32);margin-top:1px}

/* ══ MAIN ══════════════════════════════════════════════════════ */
.main{margin-left:252px;min-height:100vh;display:flex;flex-direction:column}
.tb{background:rgba(255,255,255,.96);backdrop-filter:blur(16px);border-bottom:1px solid var(--bd);
  padding:14px 28px;display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;box-shadow:0 1px 8px rgba(0,0,0,.06)}
.tb h2{font-size:1.14rem;font-weight:800;color:var(--tx)}.tb-r{display:flex;align-items:center;gap:10px}
.nw{position:relative}
.nd{position:absolute;top:-2px;right:-2px;width:8px;height:8px;background:var(--dn);
  border-radius:50%;border:2px solid #fff;animation:nb-pulse 2s infinite}
.ct{padding:28px;flex:1}

/* ══ METRIC CARDS ══════════════════════════════════════════════ */
.kg{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:14px;margin-bottom:28px}
.kc{background:var(--sf);border-radius:var(--radius);padding:18px;border:1px solid var(--bd);
  position:relative;overflow:hidden;box-shadow:var(--shadow-sm);transition:all .2s}
.kc:hover{transform:translateY(-3px);box-shadow:var(--shadow)}
.kc::before{content:'';position:absolute;top:0;left:0;right:0;height:4px;border-radius:var(--radius) var(--radius) 0 0}
.k-bl::before{background:linear-gradient(90deg,#4f46e5,#818cf8)}
.k-gr::before{background:linear-gradient(90deg,#10b981,#34d399)}
.k-rd::before{background:linear-gradient(90deg,#ef4444,#f87171)}
.k-am::before{background:linear-gradient(90deg,#f59e0b,#fbbf24)}
.k-cy::before{background:linear-gradient(90deg,#06b6d4,#67e8f9)}
.k-pu::before{background:linear-gradient(90deg,#8b5cf6,#a78bfa)}
.k-nq::before{background:linear-gradient(90deg,#5f259f,#9d4edd)}
.k-dv::before{background:linear-gradient(90deg,#E40046,#ff6b6b)}
.ki{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;
  font-size:1.2rem;margin-bottom:12px}
.k-bl .ki{background:#eff6ff}.k-gr .ki{background:#f0fdf4}.k-rd .ki{background:#fef2f2}
.k-am .ki{background:#fffbeb}.k-cy .ki{background:#ecfeff}.k-pu .ki{background:#faf5ff}
.k-nq .ki{background:#f3e8ff}.k-dv .ki{background:#fff1f2}
.kl{font-size:.65rem;color:var(--mt);text-transform:uppercase;letter-spacing:.09em;font-weight:700}
.kv{font-size:1.65rem;font-weight:900;margin-top:3px;line-height:1}
.k-bl .kv{color:#4f46e5}.k-gr .kv{color:var(--sc)}.k-rd .kv{color:var(--dn)}
.k-am .kv{color:var(--wn)}.k-cy .kv{color:#06b6d4}.k-pu .kv{color:var(--pv)}
.k-nq .kv{color:#5f259f}.k-dv .kv{color:#E40046}

/* ══ SECTIONS ══════════════════════════════════════════════════ */
.sec{background:var(--sf);border:1px solid var(--bd);border-radius:var(--radius);
  margin-bottom:22px;overflow:hidden;box-shadow:var(--shadow-sm)}
.sh{padding:16px 20px;border-bottom:1px solid var(--bd);
  display:flex;align-items:center;justify-content:space-between}
.sh h3{font-size:.93rem;font-weight:800}
.sb2{padding:20px}

/* ══ TABLES ════════════════════════════════════════════════════ */
.tw{overflow-x:auto}
table{width:100%;border-collapse:collapse}
thead tr{background:linear-gradient(90deg,#f8faff,#f1f5ff)}
th{font-size:.63rem;color:var(--mt);text-transform:uppercase;letter-spacing:.1em;
  padding:10px 13px;text-align:left;font-weight:700;border-bottom:1px solid var(--bd)}
td{padding:11px 13px;font-size:.83rem;border-bottom:1px solid var(--bd);vertical-align:middle}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:#f8faff}

/* ══ FORMS ═════════════════════════════════════════════════════ */
.fg2{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:13px}
.fg{display:flex;flex-direction:column;gap:5px}
label{font-size:.68rem;font-weight:700;color:var(--mt);text-transform:uppercase;letter-spacing:.07em}
input[type=text],input[type=number],input[type=email],input[type=password],
input[type=url],input[type=tel],input[type=date],input[type=color],input[type=file],
select,textarea{
  background:#f8faff;border:1.5px solid var(--bd);border-radius:var(--radius-sm);
  padding:9px 13px;color:var(--tx);font-family:inherit;font-size:.84rem;
  transition:all .15s;width:100%}
input:focus,select:focus,textarea:focus{
  outline:none;border-color:var(--pr);
  box-shadow:0 0 0 3px rgba(79,70,229,.12);background:#fff}
textarea{resize:vertical;min-height:72px}

/* ══ BOTONES ULTRA PREMIUM ══════════════════════════════════════ */
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:7px;
  padding:10px 20px;border-radius:var(--radius-sm);border:none;cursor:pointer;
  font-family:inherit;font-size:.82rem;font-weight:700;transition:all .18s;
  letter-spacing:.03em;white-space:nowrap;position:relative;overflow:hidden;
  text-decoration:none}
.btn::after{content:'';position:absolute;inset:0;opacity:0;transition:opacity .18s;
  background:linear-gradient(rgba(255,255,255,.15),rgba(255,255,255,0))}
.btn:hover::after{opacity:1}
.btn:active{transform:scale(.97)}

/* Primary */
.bp{background:linear-gradient(135deg,var(--pr),#6366f1);color:#fff;
  box-shadow:0 3px 12px rgba(79,70,229,.35),0 1px 3px rgba(0,0,0,.1)}
.bp:hover{box-shadow:0 6px 20px rgba(79,70,229,.45),0 2px 6px rgba(0,0,0,.12);
  transform:translateY(-2px)}

/* Success */
.bs{background:linear-gradient(135deg,#10b981,#34d399);color:#fff;
  box-shadow:0 3px 12px rgba(16,185,129,.35)}
.bs:hover{box-shadow:0 6px 20px rgba(16,185,129,.45);transform:translateY(-2px)}

/* Danger */
.bd{background:linear-gradient(135deg,#ef4444,#f87171);color:#fff;
  box-shadow:0 3px 12px rgba(239,68,68,.3)}
.bd:hover{box-shadow:0 6px 20px rgba(239,68,68,.4);transform:translateY(-2px)}

/* Warning */
.bw2{background:linear-gradient(135deg,#f59e0b,#fbbf24);color:#fff;
  box-shadow:0 3px 12px rgba(245,158,11,.35)}
.bw2:hover{box-shadow:0 6px 20px rgba(245,158,11,.45);transform:translateY(-2px)}

/* Ghost */
.bg{background:#fff;color:var(--tx);border:1.5px solid var(--bd);
  box-shadow:0 1px 4px rgba(0,0,0,.06)}
.bg:hover{background:#f8faff;border-color:#cbd5e1;box-shadow:0 3px 10px rgba(0,0,0,.08)}

/* WhatsApp */
.bwa{background:linear-gradient(135deg,#25D366,#128C7E);color:#fff;
  box-shadow:0 3px 12px rgba(37,211,102,.4)}
.bwa:hover{box-shadow:0 6px 20px rgba(37,211,102,.55);transform:translateY(-2px)}

/* Domicilio */
.bdm{background:linear-gradient(135deg,#0ea5e9,#38bdf8);color:#fff;
  box-shadow:0 3px 12px rgba(14,165,233,.35)}
.bdm:hover{transform:translateY(-2px)}

/* Proveedor */
.bpv{background:linear-gradient(135deg,#8b5cf6,#a78bfa);color:#fff;
  box-shadow:0 3px 12px rgba(139,92,246,.35)}
.bpv:hover{transform:translateY(-2px)}

/* Nequi */
.bnq{background:linear-gradient(135deg,#5f259f,#7c3aed);color:#fff;
  box-shadow:0 3px 12px rgba(95,37,159,.4)}
.bnq:hover{box-shadow:0 6px 20px rgba(95,37,159,.55);transform:translateY(-2px)}

/* Daviplata */
.bdv{background:linear-gradient(135deg,#E40046,#ff4d79);color:#fff;
  box-shadow:0 3px 12px rgba(228,0,70,.4)}
.bdv:hover{box-shadow:0 6px 20px rgba(228,0,70,.55);transform:translateY(-2px)}

/* Efectivo */
.bef{background:linear-gradient(135deg,#16a34a,#22c55e);color:#fff;
  box-shadow:0 3px 12px rgba(22,163,74,.4)}
.bef:hover{box-shadow:0 6px 20px rgba(22,163,74,.55);transform:translateY(-2px)}

/* Sizes */
.bsm{padding:6px 12px;font-size:.71rem;border-radius:7px}
.blg{padding:13px 28px;font-size:.9rem;border-radius:11px}
.bbl{width:100%;justify-content:center}

/* ══ TAGS ═══════════════════════════════════════════════════════ */
.tag{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;
  border-radius:20px;font-size:.63rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.t-bl{background:#eff6ff;color:#1d4ed8}.t-gr{background:#f0fdf4;color:#15803d}
.t-rd{background:#fef2f2;color:#dc2626}.t-am{background:#fffbeb;color:#b45309}
.t-pu{background:#faf5ff;color:#7e22ce}.t-cy{background:#ecfeff;color:#0e7490}
.t-sk{background:#e0f2fe;color:#0369a1}.t-gy{background:#f1f5f9;color:#475569}
.t-nq{background:#f3e8ff;color:#5f259f}.t-dv{background:#fff1f2;color:#E40046}

/* ══ ALERTS ═════════════════════════════════════════════════════ */
.al{padding:12px 16px;border-radius:11px;font-size:.83rem;margin-bottom:14px;
  display:flex;align-items:flex-start;gap:9px;font-weight:500;line-height:1.55}
.a-s{background:#f0fdf4;border:1px solid #bbf7d0;color:#15803d}
.a-d{background:#fef2f2;border:1px solid #fecaca;color:#dc2626}
.a-i{background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8}
.a-w{background:#fffbeb;border:1px solid #fde68a;color:#92400e}
.a-k{background:#e0f2fe;border:1px solid #bae6fd;color:#0369a1}

/* ══ PRODUCTS ═══════════════════════════════════════════════════ */
.pg{display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:20px}
.pc{background:var(--sf);border:1px solid var(--bd);border-radius:var(--radius);
  overflow:hidden;box-shadow:var(--shadow-sm);transition:all .25s}
.pc:hover{box-shadow:var(--shadow-lg);transform:translateY(-4px)}
.pc img{width:100%;height:172px;object-fit:cover;display:block}
.pcb{padding:14px}.pcn{font-weight:800;font-size:.93rem;margin-bottom:3px}
.pcc{font-size:.68rem;color:var(--mt);margin-bottom:6px}
.pcp{font-size:1.18rem;font-weight:900;color:var(--pr);margin-top:6px}
.pcf{padding:10px 14px;border-top:1px solid var(--bd);display:flex;gap:7px;flex-wrap:wrap}

/* ══ CARRITO ════════════════════════════════════════════════════ */
.cr{display:flex;justify-content:space-between;align-items:center;
  padding:12px 0;border-bottom:1px solid var(--bd)}
.cr:last-child{border-bottom:none}
.cn{font-weight:700;font-size:.89rem}.cs{font-size:.75rem;color:var(--mt);margin-top:2px}
.crt{display:flex;align-items:center;gap:8px}
.ctot{font-size:.98rem;font-weight:800;color:var(--pr)}

/* ══ PASARELA DE PAGO PREMIUM ═══════════════════════════════════ */
.pago-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px}
@media(max-width:640px){.pago-grid{grid-template-columns:1fr}}
.pago-card{
  border-radius:16px;padding:22px 16px;text-align:center;cursor:pointer;
  transition:all .2s;border:2.5px solid transparent;position:relative;
  background:var(--sf)}
.pago-card input[type=radio]{position:absolute;opacity:0;pointer-events:none}
.pago-card.nequi{border-color:#d8b4fe}
.pago-card.nequi:hover,.pago-card.nequi.sel{
  background:linear-gradient(135deg,#f5f3ff,#ede9fe);
  border-color:#5f259f;box-shadow:0 0 0 3px rgba(95,37,159,.15),var(--shadow)}
.pago-card.daviplata{border-color:#fca5a5}
.pago-card.daviplata:hover,.pago-card.daviplata.sel{
  background:linear-gradient(135deg,#fff1f2,#ffe4e6);
  border-color:#E40046;box-shadow:0 0 0 3px rgba(228,0,70,.15),var(--shadow)}
.pago-card.efectivo{border-color:#86efac}
.pago-card.efectivo:hover,.pago-card.efectivo.sel{
  background:linear-gradient(135deg,#f0fdf4,#dcfce7);
  border-color:#16a34a;box-shadow:0 0 0 3px rgba(22,163,74,.15),var(--shadow)}
.pago-check{width:22px;height:22px;border-radius:50%;border:2.5px solid var(--bd);
  display:flex;align-items:center;justify-content:center;margin:0 auto 12px;transition:.2s;font-size:.8rem}
.pago-card.sel .pago-check{background:var(--pr);border-color:var(--pr);color:#fff}
.pago-card.nequi.sel .pago-check{background:#5f259f;border-color:#5f259f}
.pago-card.daviplata.sel .pago-check{background:#E40046;border-color:#E40046}
.pago-card.efectivo.sel .pago-check{background:#16a34a;border-color:#16a34a}
.pago-icon{font-size:2.2rem;display:block;margin-bottom:8px}
.pago-name{font-weight:900;font-size:.95rem;display:block}
.pago-num{font-size:.82rem;color:var(--mt);margin-top:4px;font-weight:600}
.pago-desc{font-size:.73rem;color:var(--mt);margin-top:5px;line-height:1.4}
/* Instrucciones de pago */
.pay-instructions{display:none;border-radius:14px;padding:18px;margin-top:14px;
  border:2px solid;animation:fadeIn .3s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
.pay-instructions.nequi{background:linear-gradient(135deg,#f5f3ff,#ede9fe);border-color:#5f259f}
.pay-instructions.daviplata{background:linear-gradient(135deg,#fff1f2,#ffe4e6);border-color:#E40046}
.pay-instructions.efectivo{background:linear-gradient(135deg,#f0fdf4,#dcfce7);border-color:#16a34a}
.pay-step{display:flex;align-items:flex-start;gap:10px;margin-bottom:10px;font-size:.83rem}
.pay-step-num{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-weight:800;font-size:.72rem;flex-shrink:0;color:#fff;background:var(--pr)}
.nequi .pay-step-num{background:#5f259f}
.daviplata .pay-step-num{background:#E40046}
.efectivo .pay-step-num{background:#16a34a}
/* Comprobante upload */
.comprobante-box{border:2px dashed var(--bd);border-radius:12px;padding:20px;
  text-align:center;cursor:pointer;transition:.2s;background:#f8faff;margin-top:12px}
.comprobante-box:hover{border-color:var(--pr);background:#f0f4ff}
.comprobante-box.has-file{border-color:var(--sc);background:#f0fdf4;border-style:solid}
#comp-preview{display:none;max-width:200px;border-radius:8px;margin:10px auto 0;box-shadow:var(--shadow)}

/* ══ STORE SELECTOR ════════════════════════════════════════════ */
.ss-page{min-height:100vh;background:linear-gradient(135deg,#0f172a 0%,#1e1b4b 45%,#312e81 100%);
  display:flex;flex-direction:column;align-items:center;justify-content:center;padding:28px}
.ss-title{text-align:center;margin-bottom:40px}
.ss-title h1{color:#fff;font-size:2.5rem;font-weight:900;margin-top:14px;letter-spacing:-.03em}
.ss-title p{color:rgba(255,255,255,.48);font-size:.9rem;margin-top:8px}
.ss-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:22px;max-width:960px;width:100%}
.sc{background:#fff;border-radius:22px;padding:30px;text-align:center;cursor:pointer;
  transition:all .25s;box-shadow:0 12px 40px rgba(0,0,0,.3);border:3px solid transparent}
.sc:hover{transform:translateY(-8px);box-shadow:0 24px 64px rgba(0,0,0,.45);border-color:rgba(255,255,255,.35)}
.se{font-size:3.2rem;display:block;margin-bottom:14px}
.sc h2{font-size:1.1rem;font-weight:900;color:#1e293b;margin-bottom:5px}
.sc p{font-size:.78rem;color:#64748b}
.sbdg{display:inline-block;margin-top:12px;padding:5px 16px;border-radius:22px;
  font-size:.68rem;font-weight:700;text-transform:uppercase;color:#fff}

/* ══ LOGIN ULTRA PREMIUM ════════════════════════════════════════ */
.lp{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.lp-bg{position:fixed;inset:0;z-index:-1;overflow:hidden}
.lp-bg::before{content:'';position:absolute;width:600px;height:600px;border-radius:50%;
  background:radial-gradient(circle,rgba(79,70,229,.35),transparent 70%);top:-200px;right:-100px}
.lp-bg::after{content:'';position:absolute;width:500px;height:500px;border-radius:50%;
  background:radial-gradient(circle,rgba(56,189,248,.2),transparent 70%);bottom:-150px;left:-100px}
.lc{background:rgba(255,255,255,.97);backdrop-filter:blur(20px);
  border-radius:var(--radius-lg);padding:38px 34px;width:100%;max-width:430px;
  box-shadow:var(--shadow-xl);border:1px solid rgba(255,255,255,.8)}
.llo{text-align:center;margin-bottom:26px}
.li2{font-size:3rem;display:block;margin-bottom:10px;filter:drop-shadow(0 4px 8px rgba(0,0,0,.15))}
.llo h1{font-size:1.5rem;font-weight:900;color:var(--pr);letter-spacing:-.03em}
.llo p{color:var(--mt);font-size:.82rem;margin-top:4px}
.lt{display:flex;background:#f1f5f9;border-radius:11px;padding:4px;margin-bottom:20px;gap:4px}
.lt-b{flex:1;padding:10px;text-align:center;font-size:.74rem;font-weight:700;
  cursor:pointer;background:transparent;color:var(--mt);border:none;font-family:inherit;
  text-transform:uppercase;letter-spacing:.05em;transition:all .18s;border-radius:8px}
.lt-b.ac{background:#fff;color:var(--pr);box-shadow:0 2px 8px rgba(0,0,0,.1)}
/* Input con ojo de contraseña */
.input-pw{position:relative}
.input-pw input{padding-right:44px}
.pw-eye{position:absolute;right:13px;top:50%;transform:translateY(-50%);
  cursor:pointer;color:var(--mt);font-size:1rem;user-select:none;transition:.15s}
.pw-eye:hover{color:var(--pr)}
/* Input icons */
.input-icon{position:relative}
.input-icon input,.input-icon select{padding-left:38px}
.input-icon .icon{position:absolute;left:12px;top:50%;transform:translateY(-50%);
  font-size:.95rem;color:var(--mt);pointer-events:none}
.ph{font-size:.65rem;color:var(--mt);margin-top:4px;line-height:1.45}
.cbw{display:flex;align-items:flex-start;gap:10px;padding:13px;background:#f8faff;
  border-radius:10px;border:1.5px solid var(--bd);cursor:pointer;transition:.15s}
.cbw:hover{border-color:var(--pr)}
.cbw input[type=checkbox]{width:18px;height:18px;margin-top:1px;flex-shrink:0;accent-color:var(--pr)}
.cbw span{font-size:.8rem;color:var(--tx);line-height:1.55}
.sep{height:1px;background:var(--bd);margin:18px 0}

/* ══ CHATBOT IA PREMIUM ═════════════════════════════════════════ */
.bot-page{max-width:740px;margin:0 auto}
.bot-header{
  background:linear-gradient(135deg,var(--pr) 0%,#818cf8 50%,#06b6d4 100%);
  border-radius:18px;padding:28px;color:#fff;margin-bottom:20px;text-align:center;
  box-shadow:0 12px 32px rgba(79,70,229,.4);position:relative;overflow:hidden}
.bot-header::before{content:'';position:absolute;width:200px;height:200px;border-radius:50%;
  background:rgba(255,255,255,.08);top:-80px;right:-60px}
.bot-header::after{content:'';position:absolute;width:150px;height:150px;border-radius:50%;
  background:rgba(255,255,255,.06);bottom:-60px;left:-40px}
.bot-header h2{font-size:1.35rem;font-weight:900;margin:12px 0 6px;position:relative}
.bot-header p{font-size:.83rem;opacity:.87;position:relative}
.bot-avatar-wrap{
  width:64px;height:64px;background:rgba(255,255,255,.2);border-radius:50%;
  display:flex;align-items:center;justify-content:center;font-size:2rem;
  margin:0 auto;box-shadow:0 4px 16px rgba(0,0,0,.15);position:relative;
  border:2px solid rgba(255,255,255,.3)}
.bot-online{width:14px;height:14px;background:#4ade80;border-radius:50%;
  border:2px solid #fff;position:absolute;bottom:2px;right:2px;
  animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.5}}
.chat-wrap{display:flex;flex-direction:column;height:580px}
.chat-msgs{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;
  background:linear-gradient(180deg,#f0f4ff,#f8faff);border-radius:16px;
  margin-bottom:14px;border:1px solid var(--bd);scroll-behavior:smooth}
/* Mensajes del bot */
.bot-row{display:flex;align-items:flex-end;gap:8px;align-self:flex-start;max-width:90%;animation:msgIn .2s ease}
.bot-mini-av{width:30px;height:30px;border-radius:50%;
  background:linear-gradient(135deg,var(--pr),#818cf8);
  display:flex;align-items:center;justify-content:center;font-size:.9rem;
  flex-shrink:0;box-shadow:0 2px 8px rgba(79,70,229,.3)}
@keyframes msgIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.cb.bot{background:#fff;border:1px solid var(--bd);border-bottom-left-radius:4px;
  box-shadow:0 2px 8px rgba(0,0,0,.07);border-radius:14px}
.cb.usr{background:linear-gradient(135deg,var(--pr),#6366f1);color:#fff;
  border-bottom-right-radius:4px;align-self:flex-end;
  box-shadow:0 3px 10px rgba(79,70,229,.3);border-radius:14px;animation:msgIn .2s ease}
.cb{padding:11px 15px;font-size:.84rem;line-height:1.65}
.cb .who{font-size:.58rem;font-weight:800;margin-bottom:5px;opacity:.55;
  text-transform:uppercase;letter-spacing:.08em}
.cb .bot-img{width:100%;max-width:240px;border-radius:12px;margin-top:10px;display:block;
  cursor:pointer;transition:.2s;box-shadow:var(--shadow)}
.cb .bot-img:hover{transform:scale(1.03)}
/* Botones de opciones IA */
.cb .opts{display:flex;flex-direction:column;gap:7px;margin-top:12px}
.opt-btn{
  background:linear-gradient(90deg,#f0f4ff,#e8eeff);
  border:1.5px solid #bfdbfe;color:#1d4ed8;border-radius:24px;
  padding:8px 16px;font-size:.79rem;font-weight:700;cursor:pointer;
  font-family:inherit;transition:all .18s;text-align:left;width:100%;
  display:flex;align-items:center;gap:9px;
  box-shadow:0 1px 4px rgba(59,130,246,.1)}
.opt-btn:hover{
  background:linear-gradient(135deg,var(--pr),#6366f1);color:#fff;
  border-color:var(--pr);transform:translateX(5px);
  box-shadow:0 4px 14px rgba(79,70,229,.35)}
/* Input chat */
.chat-inp{display:flex;gap:8px;align-items:center;
  background:#fff;border-radius:24px;padding:6px 6px 6px 18px;
  border:1.5px solid var(--bd);box-shadow:var(--shadow-sm);transition:.15s}
.chat-inp:focus-within{border-color:var(--pr);box-shadow:0 0 0 3px rgba(79,70,229,.1)}
.chat-inp input{flex:1;border:none;background:transparent;outline:none;
  font-family:inherit;font-size:.86rem;color:var(--tx)}
.chat-inp button{border-radius:20px;padding:9px 18px;font-size:.82rem}
/* Typing indicator */
.typing-row{display:flex;align-items:center;gap:8px}
.typing-bubble{background:#fff;border:1px solid var(--bd);border-radius:14px;
  border-bottom-left-radius:4px;padding:12px 16px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.typing-dots{display:flex;gap:4px;align-items:center;height:16px}
.typing-dots span{width:7px;height:7px;background:var(--mt);border-radius:50%;
  animation:typing-bounce .9s infinite}
.typing-dots span:nth-child(2){animation-delay:.2s}
.typing-dots span:nth-child(3){animation-delay:.4s}
@keyframes typing-bounce{0%,80%,100%{transform:translateY(0);opacity:.6}40%{transform:translateY(-7px);opacity:1}}

/* ══ OTROS ══════════════════════════════════════════════════════ */
.wa-float{position:fixed;bottom:28px;right:28px;z-index:999;background:linear-gradient(135deg,#25D366,#128C7E);
  color:#fff;width:58px;height:58px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;box-shadow:0 4px 20px rgba(37,211,102,.55),0 2px 8px rgba(0,0,0,.1);
  text-decoration:none;transition:all .2s;font-size:1.55rem}
.wa-float:hover{transform:scale(1.12);box-shadow:0 6px 28px rgba(37,211,102,.7)}
.dc{background:var(--sf);border:2px solid var(--bd);border-radius:14px;padding:18px;margin-bottom:16px;transition:.2s}
.dc:hover{border-color:var(--dm)}.dc.enc{border-color:var(--dm);background:linear-gradient(135deg,#f0f9ff,#fff)}
.dg{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:11px 0}
.di{background:#f8faff;border-radius:9px;padding:10px}
.dl{font-size:.61rem;font-weight:700;color:var(--mt);text-transform:uppercase;letter-spacing:.07em;margin-bottom:3px}
.dv{font-size:.85rem;font-weight:700;color:var(--tx)}.dv.hl{color:var(--dm);font-size:.93rem}
.sa-page{min-height:100vh;background:linear-gradient(135deg,#0f172a,#1e293b);display:flex;align-items:center;justify-content:center;padding:20px}
.tc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:20px}
.tc{background:var(--sf);border-radius:15px;overflow:hidden;box-shadow:var(--shadow);border:2px solid var(--bd);transition:.2s}
.tc:hover{transform:translateY(-4px);box-shadow:var(--shadow-lg)}
.tc-top{padding:20px;display:flex;align-items:center;gap:14px}
.tc-em{font-size:2.4rem}.tc-info h3{font-size:.97rem;font-weight:800;margin-bottom:4px}.tc-info p{font-size:.75rem;color:var(--mt)}
.tc-stats{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--bd)}
.tc-s{padding:13px;text-align:center;border-right:1px solid var(--bd)}.tc-s:last-child{border-right:none}
.tc-sv{font-size:1.18rem;font-weight:900}.tc-sl{font-size:.62rem;color:var(--mt);text-transform:uppercase;letter-spacing:.07em}
.tc-acts{padding:13px 17px;border-top:1px solid var(--bd);display:flex;gap:8px;flex-wrap:wrap}
.promo-banner{border-radius:14px;padding:18px;color:#fff;margin-bottom:14px;position:relative;overflow:hidden}
.promo-banner::after{content:'';position:absolute;top:-30px;right:-30px;width:120px;height:120px;background:rgba(255,255,255,.08);border-radius:50%}
.promo-banner h4{font-size:.95rem;font-weight:800;margin-bottom:4px}.promo-banner p{font-size:.78rem;opacity:.9}
.promo-badge{background:rgba(255,255,255,.2);padding:4px 12px;border-radius:14px;font-size:.7rem;font-weight:800;margin-top:8px;display:inline-block}
.fr{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.mt16{margin-top:16px}.mt8{margin-top:8px}.c2{grid-column:span 2}
.tmuted{color:var(--mt);font-size:.78rem}.g2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.sep{height:1px;background:var(--bd);margin:18px 0}
.prov-card{background:var(--sf);border:1px solid var(--bd);border-radius:13px;padding:16px;margin-bottom:14px;transition:.2s}
.prov-card:hover{border-color:var(--pr);box-shadow:var(--shadow)}
.phone-outer{display:flex;justify-content:center;padding:10px 0}
.phone-device{
  width:100%;max-width:410px;
  background:#fff;
  border-radius:38px;
  box-shadow:
    0 0 0 2px #1e293b,
    0 0 0 6px #334155,
    0 0 0 8px #1e293b,
    0 24px 64px rgba(0,0,0,.35);
  overflow:hidden;
  display:flex;flex-direction:column;
  min-height:680px;position:relative}

/* Notch superior */
.phone-notch{
  background:#0f172a;height:28px;
  display:flex;align-items:center;justify-content:center;flex-shrink:0}
.phone-pill{
  width:90px;height:16px;background:#0a0f1e;
  border-radius:20px;display:flex;align-items:center;justify-content:center;gap:6px}
.phone-cam{width:8px;height:8px;border-radius:50%;background:#1e293b;border:1px solid #334155}
.phone-speaker{width:32px;height:4px;border-radius:4px;background:#1e293b}

/* Barra de estado del chat */
.phone-bar{
  padding:10px 18px;
  display:flex;align-items:center;justify-content:space-between;
  flex-shrink:0}
.phone-bar.bot-bar{background:linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%)}
.phone-bar.agent-bar{background:linear-gradient(135deg,#059669 0%,#0ea5e9 100%)}
.phone-bar-left{display:flex;align-items:center;gap:10px}
.phone-avatar{
  width:36px;height:36px;border-radius:50%;
  background:rgba(255,255,255,.25);
  display:flex;align-items:center;justify-content:center;
  font-size:1.1rem;flex-shrink:0;
  border:2px solid rgba(255,255,255,.4);
  box-shadow:0 2px 8px rgba(0,0,0,.2)}
.phone-info-name{color:#fff;font-size:.85rem;font-weight:800;line-height:1.2}
.phone-info-status{
  display:flex;align-items:center;gap:5px;
  color:rgba(255,255,255,.75);font-size:.67rem;margin-top:2px}
.phone-status-dot{
  width:7px;height:7px;border-radius:50%;background:#4ade80;
  animation:blink 2s infinite;flex-shrink:0}
.phone-bar-actions{display:flex;align-items:center;gap:8px}
.phone-bar-btn{
  background:rgba(255,255,255,.15);border:none;color:rgba(255,255,255,.85);
  border-radius:10px;padding:5px 10px;font-size:.71rem;font-weight:700;
  cursor:pointer;text-decoration:none;display:flex;align-items:center;gap:4px;
  transition:.15s}
.phone-bar-btn:hover{background:rgba(255,255,255,.25);color:#fff}
.phone-bar-btn.danger{background:rgba(239,68,68,.3);border:1px solid rgba(239,68,68,.4)}
.phone-bar-btn.danger:hover{background:rgba(239,68,68,.5)}

/* Zona de mensajes */
.phone-msgs{
  flex:1;overflow-y:auto;padding:14px 12px;
  display:flex;flex-direction:column;gap:10px;
  background:linear-gradient(180deg,#eef2f8 0%,#f4f7fb 100%);
  scroll-behavior:smooth;min-height:0}
.phone-msgs::-webkit-scrollbar{width:0}

/* === BURBUJA BOT / AGENTE (izquierda) === */
.chat-row-l{display:flex;align-items:flex-end;gap:7px;align-self:flex-start;max-width:88%;animation:bubbleIn .2s ease}
.chat-av-l{
  width:28px;height:28px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  font-size:.85rem;flex-shrink:0;
  box-shadow:0 2px 6px rgba(0,0,0,.12)}
.chat-av-l.bot-av{background:linear-gradient(135deg,#4f46e5,#7c3aed)}
.chat-av-l.agent-av{background:linear-gradient(135deg,#059669,#0ea5e9)}
.chat-bub-l{
  background:#fff;
  border-radius:18px 18px 18px 4px;
  padding:10px 13px;
  font-size:.83rem;line-height:1.65;
  box-shadow:0 2px 8px rgba(0,0,0,.08);
  max-width:100%;word-wrap:break-word;
  position:relative}
.chat-bub-l::before{
  content:'';position:absolute;bottom:0;left:-6px;
  border:6px solid transparent;border-right-color:#fff;border-bottom-color:#fff}
.chat-meta-l{font-size:.61rem;color:var(--mt);margin-top:3px;padding-left:35px}
.chat-sender{font-size:.65rem;color:var(--mt);font-weight:700;margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em}

/* === BURBUJA USUARIO / CLIENTE (derecha) === */
.chat-row-r{display:flex;flex-direction:column;align-items:flex-end;align-self:flex-end;max-width:84%;animation:bubbleIn .2s ease}
.chat-bub-r{
  background:linear-gradient(135deg,#4f46e5,#6366f1);
  color:#fff;
  border-radius:18px 18px 4px 18px;
  padding:10px 13px;
  font-size:.83rem;line-height:1.65;
  box-shadow:0 3px 12px rgba(79,70,229,.3);
  max-width:100%;word-wrap:break-word;
  position:relative}
.chat-bub-r.green-bub{background:linear-gradient(135deg,#059669,#0ea5e9)}
.chat-meta-r{font-size:.61rem;color:var(--mt);margin-top:3px;text-align:right;display:flex;align-items:center;justify-content:flex-end;gap:4px}
.check-icon{color:#4ade80;font-size:.7rem}

/* === CARD DE PRODUCTO EN BURBUJA === */
.prod-card-msg{
  background:#fff;border-radius:14px;margin-top:10px;overflow:hidden;
  box-shadow:0 3px 12px rgba(0,0,0,.1);border:1px solid rgba(0,0,0,.06);
  max-width:220px;transition:.2s;cursor:pointer}
.prod-card-msg:hover{transform:scale(1.02);box-shadow:0 6px 20px rgba(0,0,0,.15)}
.prod-card-img{width:100%;height:120px;object-fit:cover;display:block}
.prod-card-info{padding:9px 11px}
.prod-card-name{font-size:.8rem;font-weight:800;color:#1e293b;margin-bottom:3px}
.prod-card-price{font-size:.88rem;font-weight:900;color:#4f46e5}
.prod-card-stock{font-size:.67rem;color:#64748b;margin-top:2px}
/* Fallback sin imagen */
.prod-card-no-img{
  background:linear-gradient(135deg,#f0f4ff,#e8eeff);
  height:80px;display:flex;align-items:center;justify-content:center;font-size:2rem}

/* === CHIPS DE RESPUESTA RÁPIDA === */
.chips-section{
  background:#fff;border-top:1px solid #e5e7eb;
  padding:8px 12px 6px;flex-shrink:0}
.chips-label{font-size:.62rem;font-weight:800;color:var(--mt);text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}
.chips-row{
  display:flex;gap:6px;overflow-x:auto;padding-bottom:2px;
  scrollbar-width:none}
.chips-row::-webkit-scrollbar{height:0}
.chip{
  flex-shrink:0;background:#f0f4ff;border:1.5px solid #bfdbfe;
  color:#1d4ed8;border-radius:20px;padding:5px 11px;
  font-size:.72rem;font-weight:700;cursor:pointer;
  font-family:inherit;white-space:nowrap;transition:all .18s;
  display:flex;align-items:center;gap:5px;line-height:1}
.chip:hover,.chip:active{
  background:linear-gradient(135deg,#4f46e5,#6366f1);
  color:#fff;border-color:#4f46e5;transform:translateY(-1px);
  box-shadow:0 3px 10px rgba(79,70,229,.3)}
.chip.chip-green{background:#f0fdf4;border-color:#86efac;color:#15803d}
.chip.chip-green:hover{background:linear-gradient(135deg,#059669,#34d399);color:#fff;border-color:#059669}
.chip.chip-wa{background:#f0fdf4;border-color:#86efac;color:#15803d}
.chip.chip-agent{background:linear-gradient(90deg,#f0fdf4,#ecfeff);border-color:#86efac;color:#059669}
.chip.chip-agent:hover{background:linear-gradient(135deg,#059669,#0ea5e9);color:#fff;border-color:#059669}

/* === BARRA DE INPUT === */
.phone-input-bar{
  background:#fff;border-top:1px solid #e5e7eb;
  padding:8px 10px;
  display:flex;gap:8px;align-items:center;
  flex-shrink:0;border-radius:0 0 32px 32px}
.phone-input{
  flex:1;border:1.5px solid #e2e8f0;border-radius:24px;
  padding:8px 15px;font-size:.84rem;font-family:inherit;
  outline:none;background:#f8faff;transition:.15s;color:#1e293b}
.phone-input:focus{border-color:#4f46e5;background:#fff;box-shadow:0 0 0 3px rgba(79,70,229,.1)}
.phone-send{
  width:38px;height:38px;border-radius:50%;border:none;
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  flex-shrink:0;transition:all .2s}
.phone-send.send-bot{background:linear-gradient(135deg,#4f46e5,#6366f1);box-shadow:0 3px 10px rgba(79,70,229,.4)}
.phone-send.send-agent{background:linear-gradient(135deg,#059669,#0ea5e9);box-shadow:0 3px 10px rgba(5,150,105,.4)}
.phone-send:hover{transform:scale(1.1)}
.phone-send:active{transform:scale(.95)}

/* === PANEL AGENTE LADO A LADO === */
.agent-panel-grid{display:grid;grid-template-columns:260px 1fr;gap:16px;align-items:start}
.session-list{
  background:var(--sf);border-radius:16px;border:1px solid var(--bd);
  overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.05)}
.session-list-head{
  padding:14px 16px;border-bottom:1px solid var(--bd);
  background:linear-gradient(135deg,#f8faff,#f1f5ff)}
.session-list-head h3{font-size:.84rem;font-weight:800;color:var(--tx)}
.session-item{
  display:flex;align-items:center;gap:10px;
  padding:12px 14px;border-bottom:1px solid var(--bd);
  cursor:pointer;text-decoration:none;transition:.15s;color:var(--tx)}
.session-item:last-child{border-bottom:none}
.session-item:hover{background:#f8faff}
.session-item.active{background:linear-gradient(90deg,rgba(79,70,229,.08),rgba(79,70,229,.04));border-left:3px solid var(--pr)}
.session-av{
  width:36px;height:36px;border-radius:50%;
  background:linear-gradient(135deg,#f0f4ff,#e8eeff);
  display:flex;align-items:center;justify-content:center;font-size:1rem;flex-shrink:0;
  border:1.5px solid #bfdbfe}
.session-av.active-av{background:linear-gradient(135deg,var(--pr),#6366f1)}
.session-info{flex:1;min-width:0}
.session-name{font-size:.83rem;font-weight:700;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.session-last{font-size:.7rem;color:var(--mt);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.session-badge{
  background:#ef4444;color:#fff;border-radius:99px;
  padding:2px 7px;font-size:.62rem;font-weight:800;flex-shrink:0}
/* Separador de fecha en chat */
.chat-date-sep{
  text-align:center;padding:8px 0;font-size:.67rem;
  color:var(--mt);font-weight:600;
  display:flex;align-items:center;gap:8px}
.chat-date-sep::before,.chat-date-sep::after{
  content:'';flex:1;height:1px;background:var(--bd)}
/* Typing dots en chat */
.chat-typing{display:flex;align-items:center;gap:4px;padding:3px 0}
.chat-typing span{
  width:6px;height:6px;border-radius:50%;background:#94a3b8;
  animation:typing-bounce .9s infinite}
.chat-typing span:nth-child(2){animation-delay:.15s}
.chat-typing span:nth-child(3){animation-delay:.3s}
/* Badge "Cerrado" */
.chat-closed-badge{
  text-align:center;padding:10px;font-size:.77rem;font-weight:700;
  color:#dc2626;background:#fef2f2;border-radius:10px;
  border:1px solid #fecaca;margin:8px 0}

@keyframes bubbleIn{from{opacity:0;transform:translateY(6px) scale(.97)}to{opacity:1;transform:translateY(0) scale(1)}}
"""

WA_SVG='<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>'

def wa_float():
    t=get_tienda()
    wa=t.get("whatsapp","").strip().replace("+","").replace(" ","")
    if not wa or not is_cl(): return ""
    msg=t.get("whatsapp_msg","Hola!").replace(" ","%20")
    return f'<a class="wa-float" href="https://wa.me/{wa}?text={msg}" target="_blank" title="WhatsApp">{WA_SVG}</a>'

def sidebar():
    """
    Sidebar optimizado: agrupa las queries de notificaciones y chat
    en una sola llamada con db_multi() en lugar de 2-3 separadas.
    """
    u = get_su()
    if not u: return ""
    r       = rol()
    nombre  = u.get("nombre", u.get("user",""))
    inicial = nombre[0].upper() if nombre else "?"
    t       = get_tienda()

    # Agrupa las queries en una sola conexión
    unread      = 0
    chat_unread = 0
    hay_agente  = False

    if not is_sa() and tid_now():
        tid = tid_now()
        queries = [
            ("SELECT COUNT(*) as c FROM notificaciones WHERE tienda_id=%s AND leida=0", (tid,), True, False),
        ]
        if is_em():
            queries.append(
                ("SELECT COUNT(*) as c FROM chat_live WHERE tienda_id=%s AND de_quien='cliente' AND leido=0", (tid,), True, False)
            )
        if is_cl():
            queries.append(
                ("SELECT COUNT(*) as c FROM users WHERE tienda_id=%s AND rol='empleado'", (tid,), True, False)
            )
        try:
            results = db_multi(queries)
            unread = results[0]["c"] if results and results[0] else 0
            if is_em() and len(results) > 1:
                chat_unread = results[1]["c"] if results[1] else 0
            if is_cl() and len(results) > 1:
                hay_agente = (results[1]["c"] > 0) if results[1] else False
        except Exception:
            row = db_query("SELECT COUNT(*) as c FROM notificaciones WHERE tienda_id=%s AND leida=0",
                           (tid,), fetchone=True)
            unread = row["c"] if row else 0

    nb       = f'<span class="nb">{unread}</span>' if unread else ""
    chat_nb  = f'<span class="nb">{chat_unread}</span>' if chat_unread else ""

    navs = {
        "superadmin": [
            ("🏠","Panel","super","/super"),
            ("🏪","Tiendas","super","/super/tiendas"),
            ("➕","Nueva Tienda","super","/super/nueva_tienda"),
            ("👥","Admins","super","/super/usuarios"),
        ],
        "admin": [
            ("📊","Dashboard","dash","/admin"),
            ("📦","Inventario","inv","/inventario"),
            ("🧾","Pedidos","ped","/admin_pedidos"),
            ("🔄","Devoluciones","dev","/admin_devs"),
            ("🚚","Proveedores","prov","/proveedores"),
            ("🍞","Produccion","prod","/produccion"),
            ("💰","Caja","caja","/caja"),
            ("🎁","Promociones","promo","/promociones"),
            ("📈","Reportes","rep","/reportes"),
            ("👥","Usuarios","usr","/usuarios"),
            ("🏍️","Domiciliarios","dom","/domiciliarios"),
            ("🔔","Alertas","not","/notificaciones",nb),
            ("📎","Comprobantes","comp","/comprobantes_pedido"),
            ("⚙️","Configuracion","cfg","/config"),
        ],
        "empleado": [
            ("🏠","Inicio","dash","/empleado"),
            ("🧾","Pedidos","ped","/emp_pedidos"),
            ("📦","Inventario","inv","/inventario_emp"),
            ("🧾","POS Ventas","pos","/pos"),
            ("🚚","Proveedores","prov","/prov_emp"),
            ("🍞","Produccion","prod","/produccion_emp"),
            ("🔔","Alertas","not","/notificaciones_emp",nb),
            ("💰","Caja","caja","/caja_emp"),
            ("📎","Comprobantes","comp","/comprobantes_pedido"),
            ("💬","Chat en Vivo","chat","/agente_chat",chat_nb),
            ("🤖","Asistente","bot","/bot"),
        ],
        "domiciliario": [
            ("🏍️","Mis Entregas","domi","/domi"),
            ("📋","Pedidos Activos","ped","/domi_pedidos"),
            ("✅","Historial","hist","/domi_hist"),
            ("👤","Mi Perfil","perf","/perfil"),
        ],
        "proveedor": [
            ("🏠","Mi Panel","prov","/prov"),
            ("📦","Catalogo","cat","/prov_catalogo"),
            ("📋","Mis Pedidos","ped","/prov_pedidos"),
            ("👤","Mi Perfil","perf","/perfil"),
        ],
        "cliente": [
            ("🏠","Tienda","shop","/tienda"),
            ("🛒","Carrito","cart","/carrito"),
            ("📦","Mis Pedidos","ped","/mis_pedidos"),
            ("🔄","Devoluciones","dev","/mis_devs"),
            ("🤖","Asistente IA","bot","/bot"),
            *([("💬","Chat con Agente","chat","/chat_cliente")] if hay_agente else []),
            ("👤","Mi Perfil","perf","/perfil"),
        ],
    }

    nav = navs.get(r, [])
    cur = request.path
    links = ""
    for item in nav:
        icon  = item[0]; label = item[1]; href = item[3]
        extra = item[4] if len(item) > 4 else ""
        ac    = "ac" if cur == href or cur.startswith(href+"/") else ""
        links += f'<a href="{href}" class="ni {ac}"><span class="ic">{icon}</span>{label}{extra}</a>'

    col = {"superadmin":"#f9a8d4","admin":"#a5b4fc","empleado":"#6ee7b7",
           "domiciliario":"#7dd3fc","proveedor":"#c4b5fd","cliente":"#fcd34d"}
    lbl = {"superadmin":"Super Admin","admin":"Administrador","empleado":"Empleado",
           "domiciliario":"Domiciliario","proveedor":"Proveedor","cliente":"Cliente"}

    badge = ""
    if t and not is_sa():
        badge = (f'<div style="background:rgba(255,255,255,.08);border-radius:9px;'
                 f'padding:7px 11px;margin-bottom:10px;display:flex;align-items:center;gap:8px">'
                 f'<span style="font-size:1.3rem">{t.get("emoji","🏪")}</span>'
                 f'<span style="color:#fff;font-size:.76rem;font-weight:700">'
                 f'{str(t.get("nombre",""))[:20]}</span></div>')

    agent_banner = ""
    if is_cl() and hay_agente:
        agent_banner = (
            f'<a href="/chat_cliente" style="display:flex;align-items:center;gap:8px;'
            f'background:linear-gradient(135deg,#059669,#0ea5e9);border-radius:10px;'
            f'padding:9px 11px;margin-bottom:10px;text-decoration:none;'
            f'animation:nb-pulse 3s infinite">'
            f'<span style="font-size:1.1rem">💬</span>'
            f'<div><div style="color:#fff;font-size:.76rem;font-weight:800">Agente en línea</div>'
            f'<div style="color:rgba(255,255,255,.75);font-size:.65rem">Habla con nosotros ahora</div>'
            f'</div></a>')

    return (f'<aside class="sidebar">'
            f'<div class="sl"><span class="li">🏪</span><h1>GestorPro</h1>'
            f'<p>Multi-Tienda &middot; Colombia</p></div>'
            f'<nav>{links}</nav>'
            f'<div class="sf2">{agent_banner}{badge}'
            f'<div class="up"><div class="av">{inicial}</div>'
            f'<div><div class="un">{nombre[:17]}</div>'
            f'<div class="ur" style="color:{col.get(r,"#e2e8f0")}">{lbl.get(r,r)}</div>'
            f'</div></div>'
            f'<a href="/logout" class="btn bg bsm bbl" style="margin-top:9px">Cerrar sesión</a>'
            f'</div></aside>')

_CSS_CACHE = {}  # Cache del CSS por color primario

def css_cached(primary="#4f46e5"):
    """
    Versión cacheada de css_cached(). Genera el CSS solo la primera vez
    por cada color y lo reutiliza en todas las requests siguientes.
    En Railway con Railway MySQL esto ahorra ~5-15ms por request.
    """
    global _CSS_CACHE
    if primary not in _CSS_CACHE:
        _CSS_CACHE[primary] = css(primary)
    return _CSS_CACHE[primary]
def base(title, content, tid=None):
    """
    base() optimizado: usa css_cached() y agrupa la query de
    notificaciones con db_multi() en lugar de una query separada.
    """
    hs = li()
    ml = "margin-left:248px" if hs else "margin-left:0"
    t  = get_tienda(tid)
    pr = t.get("color","#4f46e5") if t else "#4f46e5"

    dot  = ""
    nb2  = ""
    if hs and is_st() and tid_now():
        row = db_query("SELECT COUNT(*) as c FROM notificaciones WHERE tienda_id=%s AND leida=0",
                       (tid_now(),), fetchone=True)
        if row and row["c"] > 0:
            dot = '<span class="nd"></span>'
        nb2 = f'<div class="nw"><a href="/notificaciones" style="font-size:1.2rem;color:var(--mt)">🔔{dot}</a></div>'

    cb2 = ""
    if is_cl():
        nc  = sum((session.get("carrito") or {}).values())
        cb2 = f'<a href="/carrito" class="btn bg bsm">🛒 ({nc})</a>'

    return (f"<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{title} &middot; GestorPro</title>"
            f"<style>{css_cached(pr)}</style>"
            # Hint al navegador para precargar conexión a Railway
            f'<link rel="preconnect" href="https://fonts.googleapis.com">'
            f"</head><body>"
            + (sidebar() if hs else "")
            + f'<div class="main" style="{ml}">'
            f'<div class="tb"><h2>{title}</h2><div class="tb-r">{nb2}{cb2}</div></div>'
            f'<div class="ct">{content}</div></div>'
            + wa_float()
            + "<script>var cb=document.getElementById('chat-box');if(cb)cb.scrollTop=cb.scrollHeight;</script>"
            + "</body></html>")

def lbg(c="#4f46e5"):
    return f'style="background:linear-gradient(135deg,{c} 0%,#1e1b4b 100%)"'

# ================================================================
#  INDEX — SELECTOR DE TIENDAS
# ================================================================
@app.route("/")
def index():
    """
    Index optimizado: UNA sola query con JOINs en lugar de 3 queries por tienda.
    Original: 1 + (3 × N_tiendas) queries. Nuevo: 4 queries totales.
    """
    tiendas = db_query("SELECT * FROM tiendas WHERE activa=1 ORDER BY nombre", fetchall=True) or []
    if not tiendas:
        return (f"<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'>"
                f"<title>GestorPro</title><style>{css_cached()}</style></head><body>"
                f'<div class="ss-page"><div class="ss-title">'
                f'<div style="font-size:3.5rem">🏪</div>'
                f'<h1>GestorPro</h1><p>Sin tiendas activas.</p></div></div></body></html>')

    ids = tuple(t["id"] for t in tiendas)
    fmt_ids = ",".join(["%s"] * len(ids))

    # Una sola query para productos disponibles por tienda
    prod_counts = db_query(
        f"SELECT tienda_id, COUNT(*) as c FROM productos WHERE tienda_id IN ({fmt_ids}) AND cantidad>0 GROUP BY tienda_id",
        ids, fetchall=True) or []
    prod_map = {r["tienda_id"]: r["c"] for r in prod_counts}

    # Una sola query para pedidos por tienda
    ped_counts = db_query(
        f"SELECT tienda_id, COUNT(*) as c FROM pedidos WHERE tienda_id IN ({fmt_ids}) GROUP BY tienda_id",
        ids, fetchall=True) or []
    ped_map = {r["tienda_id"]: r["c"] for r in ped_counts}

    # Una sola query para promos activas por tienda
    promo_counts = db_query(
        f"SELECT tienda_id, COUNT(*) as c FROM promociones WHERE tienda_id IN ({fmt_ids}) AND activa=1 GROUP BY tienda_id",
        ids, fetchall=True) or []
    promo_map = {r["tienda_id"]: r["c"] for r in promo_counts}

    cards = ""
    for t in tiendas:
        tid   = t["id"]
        n_prod  = prod_map.get(tid, 0)
        n_peds  = ped_map.get(tid, 0)
        n_promo = promo_map.get(tid, 0)
        badges = ""
        if n_promo > 0:
            s = "S" if n_promo > 1 else ""
            badges = (f'<div style="background:#ef4444;color:#fff;font-size:.65rem;'
                      f'font-weight:800;padding:3px 10px;border-radius:12px;margin-top:7px;'
                      f'display:inline-block">🎁 {n_promo} PROMO{s} ACTIVA{s}</div>')
        cards += (f'<a href="/entrar/{tid}" class="sc">'
                  f'<span class="se">{t.get("emoji","🏪")}</span>'
                  f'<h2>{t["nombre"]}</h2>'
                  f'<p>{t.get("tipo","Tienda")} &middot; {t.get("ciudad","")}</p>'
                  f'<p style="font-size:.73rem;color:#64748b;margin-top:4px">{t.get("horario","")}</p>'
                  f'<span class="sbdg" style="background:{t.get("color","#4f46e5")}">{t.get("tipo","Tienda")}</span>'
                  f'{badges}'
                  f'<div style="display:flex;gap:12px;justify-content:center;margin-top:12px">'
                  f'<span style="font-size:.72rem;color:#64748b">📦 {n_prod} productos</span>'
                  f'<span style="font-size:.72rem;color:#64748b">🧾 {n_peds} pedidos</span>'
                  f'</div></a>')

    return (f"<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>GestorPro &middot; Selecciona tu Tienda</title>"
            f"<style>{css_cached()}</style></head><body>"
            f'<div class="ss-page">'
            f'<div class="ss-title"><div style="font-size:3.5rem">🏪</div>'
            f'<h1>GestorPro</h1><p>Sistema de Gestión Multi-Tienda &middot; Colombia 🇨🇴</p></div>'
            f'<div class="ss-grid">{cards}</div>'
            f'<div style="margin-top:32px;text-align:center">'
            f'<a href="/super" style="color:rgba(255,255,255,.2);font-size:.72rem">⚙️ Acceso Administrador</a>'
            f'</div></div></body></html>')

# ================================================================
#  LOGIN / ENTRAR / REGISTRO
# ================================================================
@app.route("/entrar/<tid>")
def entrar(tid):
    t=get_tienda(tid)
    if not t or not t.get("activa"): return redirect("/")
    if session.get("user") and session.get("tienda_id")==tid:
        r=rol()
        if r=="admin": return redirect("/admin")
        if r=="empleado": return redirect("/empleado")
        if r=="domiciliario": return redirect("/domi")
        if r=="proveedor": return redirect("/prov")
        return redirect("/tienda")
    return redirect("/login/"+tid)

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
            f"<style>{css_cached(pc)}</style></head><body>"
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

# ================================================================
#  PERFIL
# ================================================================
@app.route("/registro/<tid>",methods=["GET","POST"])
def registro(tid):
    t=get_tienda(tid)
    if not t: return redirect("/")
    error=""
    if request.method=="POST":
        u=request.form.get("user","").strip()
        p=request.form.get("pass","")
        nom=request.form.get("nombre","").strip()
        ema=request.form.get("email","").strip()
        tel=request.form.get("telefono","").strip()
        td=request.form.get("td","")
        op,mp=ok_pass(p)
        if len(u)<3:
            error='<div class="al a-d">⚠️ El usuario debe tener mínimo 3 caracteres.</div>'
        elif not op:
            error=f'<div class="al a-d">⚠️ {mp}</div>'
        elif not ok_email(ema):
            error='<div class="al a-d">⚠️ El email no es válido.</div>'
        elif not tel:
            error='<div class="al a-d">⚠️ El teléfono es obligatorio.</div>'
        elif not td:
            error='<div class="al a-d">⚠️ Debes leer y aceptar la Política de Tratamiento de Datos.</div>'
        else:
            ex_u=db_query("SELECT id FROM users WHERE user=%s AND tienda_id=%s",(u,tid),fetchone=True)
            ex_e=db_query("SELECT id FROM users WHERE email=%s AND tienda_id=%s",(ema,tid),fetchone=True)
            if ex_u:
                error='<div class="al a-d">⚠️ Ese usuario ya existe en esta tienda.</div>'
            elif ex_e:
                error='<div class="al a-d">⚠️ Ese email ya está registrado.</div>'
            else:
                db_query(
                    "INSERT INTO users(tienda_id,user,nombre,password,rol,email,telefono,tratamiento_datos,fecha)"
                    " VALUES(%s,%s,%s,%s,'cliente',%s,%s,1,%s)",
                    (tid,u,nom or u,generate_password_hash(p),ema,tel,now()),commit=True)
                return redirect("/login/"+tid)
    pc=t.get("color","#4f46e5")
    nom_t=t.get("nombre","")
    ciu_t=t.get("ciudad","Colombia")
    tel_t=t.get("telefono","")
    return (f"<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Registro &middot; {nom_t}</title>"
            f"<style>{css_cached(pc)}"
            f".pass-req{{margin-top:9px;display:flex;flex-direction:column;gap:5px}}"
            f".pass-req-item{{display:flex;align-items:center;gap:8px;font-size:.74rem;color:var(--mt);transition:.2s}}"
            f".pass-req-item.ok{{color:#15803d;font-weight:600}}"
            f".req-icon{{width:17px;height:17px;border-radius:50%;border:1.5px solid #cbd5e1;"
            f"display:flex;align-items:center;justify-content:center;font-size:.6rem;flex-shrink:0;"
            f"transition:.2s;color:transparent}}"
            f".pass-req-item.ok .req-icon{{background:#15803d;border-color:#15803d;color:#fff}}"
            f".pass-bar{{height:5px;border-radius:5px;background:#e2e8f4;margin-top:9px;overflow:hidden}}"
            f".pass-bar-fill{{height:100%;border-radius:5px;transition:width .3s,background .3s;width:0}}"
            f".modal-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);"
            f"z-index:9999;align-items:center;justify-content:center;padding:16px}}"
            f".modal-box{{background:#fff;border-radius:18px;max-width:540px;width:100%;"
            f"max-height:86vh;overflow-y:auto;box-shadow:0 24px 64px rgba(0,0,0,.35)}}"
            f".modal-head{{background:linear-gradient(135deg,{pc},#818cf8);padding:18px 22px;"
            f"border-radius:18px 18px 0 0;display:flex;justify-content:space-between;align-items:center}}"
            f".modal-close{{background:rgba(255,255,255,.2);border:none;color:#fff;border-radius:50%;"
            f"width:30px;height:30px;font-size:1rem;cursor:pointer;font-weight:800;display:flex;"
            f"align-items:center;justify-content:center}}"
            f".modal-body{{padding:22px;font-size:.82rem;line-height:1.75;color:#374151}}"
            f".modal-section{{font-weight:800;color:{pc};margin:14px 0 6px;font-size:.84rem}}"
            f"</style></head><body>"

            f'<div class="lp" {lbg(pc)}><div class="lc" style="max-width:440px">'
            f'<div class="llo">'
            f'<span class="li2">{t.get("emoji","🏪")}</span>'
            f'<h1>Crear Cuenta</h1>'
            f'<p>{nom_t}</p>'
            f'</div>'
            f'{error}'
            f'<form method="post" style="display:flex;flex-direction:column;gap:12px">'

            f'<div class="fg"><label>Nombre completo</label>'
            f'<div class="input-icon"><span class="icon">👤</span>'
            f'<input type="text" name="nombre" placeholder="María García"></div>'
            f'</div>'

            f'<div class="fg"><label>Usuario <span style="color:var(--dn)">*</span></label>'
            f'<div class="input-icon"><span class="icon">🪪</span>'
            f'<input type="text" name="user" placeholder="mgarcia (mín. 3 letras)" required></div>'
            f'</div>'

            f'<div class="fg"><label>Email <span style="color:var(--dn)">*</span></label>'
            f'<div class="input-icon"><span class="icon">📧</span>'
            f'<input type="email" name="email" placeholder="maria@email.com" required></div>'
            f'</div>'

            f'<div class="fg"><label>Teléfono <span style="color:var(--dn)">*</span></label>'
            f'<div class="input-icon"><span class="icon">📱</span>'
            f'<input type="tel" name="telefono" placeholder="3101234567" required></div>'
            f'</div>'

            f'<div class="fg"><label>Contraseña <span style="color:var(--dn)">*</span></label>'
            f'<div class="input-pw">'
            f'<input type="password" id="rpass" name="pass" required '
            f'oninput="chkPass(this.value)" placeholder="Crea tu contraseña segura">'
            f'<span class="pw-eye" onclick="tpwR()" title="Ver/ocultar">👁</span>'
            f'</div>'

            f'<div class="pass-bar"><div class="pass-bar-fill" id="pbar"></div></div>'
            f'<div class="pass-req">'
            f'<div class="pass-req-item" id="p8"><div class="req-icon">✓</div> Mínimo 8 caracteres</div>'
            f'<div class="pass-req-item" id="pM"><div class="req-icon">✓</div> Al menos 1 letra MAYÚSCULA (A–Z)</div>'
            f'<div class="pass-req-item" id="pN"><div class="req-icon">✓</div> Al menos 1 número (0–9)</div>'
            f'<div class="pass-req-item" id="pE"><div class="req-icon">✓</div> Al menos 1 especial (!@#$%^&amp;*)</div>'
            f'</div></div>'

            f'<label class="cbw" style="align-items:flex-start">'
            f'<input type="checkbox" name="td" id="cb-td" required style="margin-top:3px">'
            f'<span style="font-size:.8rem;line-height:1.6">'
            f'He leído y acepto la '
            f'<a href="javascript:void(0)" onclick="document.getElementById(\'modal-td\').style.display=\'flex\'" '
            f'style="color:{pc};font-weight:700;text-decoration:underline">'
            f'Política de Tratamiento de Datos Personales</a> '
            f'según la Ley 1581 de 2012 (Habeas Data).'
            f'</span></label>'

            f'<button class="btn bs blg bbl">✨ Crear cuenta</button>'
            f'</form>'
            f'<a href="/login/{tid}" class="btn bg bbl" style="margin-top:10px">Ya tengo cuenta</a>'
            f'</div></div>'

            f'<div id="modal-td" class="modal-overlay">'
            f'<div class="modal-box">'
            f'<div class="modal-head">'
            f'<h3 style="color:#fff;font-size:.95rem;font-weight:800">📋 Política de Tratamiento de Datos Personales</h3>'
            f'<button class="modal-close" onclick="document.getElementById(\'modal-td\').style.display=\'none\'">✕</button>'
            f'</div>'

            f'<div class="modal-body"> ... </div>'

            f'<div style="padding:16px 22px;border-top:1px solid #e5e7eb;display:flex;gap:10px;justify-content:flex-end">'
            f'<button onclick="document.getElementById(\'modal-td\').style.display=\'none\'" class="btn bg bsm">Cerrar</button>'

            # ✅ FIX onclick duplicado
            f'<button onclick="document.getElementById(\'modal-td\').style.display=\'none\';document.getElementById(\'cb-td\').checked=true;" '
            f'class="btn bp" style="background:linear-gradient(135deg,{pc},#818cf8)">✅ He leído y acepto</button>'

            f'</div></div></div>'

            f"<script>"
            f"function chkPass(v){{"
            f"  var ok8=/^.{{8,}}$/.test(v);"
            f"  var okM=/[A-Z]/.test(v);"
            f"  var okN=/\\d/.test(v);"
            # ✅ FIX {} escapado
            f"  var okE=/[!@#$%^&*()\\-_=+\\[\\]{{}};:,.<>?]/.test(v);"
            f"}}"
            f"</script>"
            f"</body></html>")

@app.route("/perfil",methods=["GET","POST"])
def perfil():
    if not li(): return redirect("/")
    tid=tid_now()
    usr=db_query("SELECT * FROM users WHERE user=%s AND tienda_id=%s",(session.get("user"),tid),fetchone=True)
    if not usr: return redirect("/")
    msg=""
    if request.method=="POST":
        nom=request.form.get("nombre","").strip(); tel=request.form.get("telefono","").strip(); npa=request.form.get("pass","")
        if npa:
            ok,mp=ok_pass(npa)
            if not ok: msg=f'<div class="al a-d">{mp}</div>'
            else:
                db_query("UPDATE users SET nombre=%s,telefono=%s,password=%s WHERE id=%s",(nom or usr["nombre"],tel or usr["telefono"],generate_password_hash(npa),usr["id"]),commit=True)
                msg='<div class="al a-s">✅ Perfil y contraseña actualizados.</div>'
        else:
            db_query("UPDATE users SET nombre=%s,telefono=%s WHERE id=%s",(nom or usr["nombre"],tel or usr["telefono"],usr["id"]),commit=True)
            msg='<div class="al a-s">✅ Perfil actualizado.</div>'
        usr=db_query("SELECT * FROM users WHERE id=%s",(usr["id"],),fetchone=True)
    return base("Mi Perfil",(
        f'<div class="sec" style="max-width:480px;margin:auto"><div class="sh"><h3>👤 Mi Perfil</h3></div><div class="sb2">{msg}'
        f'<form method="post" style="display:flex;flex-direction:column;gap:12px">'
        f'<div class="fg"><label>Usuario</label><input type="text" value="{usr["user"]}" disabled></div>'
        f'<div class="fg"><label>Nombre</label><input type="text" name="nombre" value="{str(usr.get("nombre",""))}"></div>'
        f'<div class="fg"><label>Email</label><input type="text" value="{str(usr.get("email","-"))}" disabled></div>'
        f'<div class="fg"><label>Teléfono</label><input type="tel" name="telefono" value="{str(usr.get("telefono",""))}"></div>'
        f'<div class="fg"><label>Nueva contraseña (vacío = no cambiar)</label>'
        f'<input type="password" name="pass" placeholder="Min 8, MAYÚSCULA, número, especial">'
        f'<span class="ph">Min 8 | 1 MAYÚSCULA | 1 número | 1 especial (!@#$%^&*)</span></div>'
        f'<button class="btn bp">💾 Guardar cambios</button></form></div></div>'))

# ================================================================
#  SUPER ADMIN — solo crea tiendas y credenciales
# ================================================================
@app.route("/super",methods=["GET","POST"])
def super_login():
    if is_sa(): return redirect("/super/panel")
    error=""
    if request.method=="POST":
        u=request.form.get("user","").strip(); p=request.form.get("pass","")
        usr=db_query("SELECT * FROM superusers WHERE user=%s",(u,),fetchone=True)
        if usr and check_password_hash(usr["password"],p):
            session.clear(); session["superadmin"]=True; session["user"]=u; return redirect("/super/panel")
        error='<div class="al a-d">⚠️ Credenciales incorrectas.</div>'
    return (f"<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Super Admin &middot; GestorPro</title><style>{css_cached()}</style></head><body>"
            f'<div class="sa-page"><div class="lc">'
            f'<div class="llo"><span class="li2">⚙️</span><h1>Super Admin</h1><p>GestorPro &middot; Panel Global del Sistema</p></div>'
            f'{error}<form method="post" style="display:flex;flex-direction:column;gap:12px">'
            f'<div class="fg"><label>Usuario</label><input type="text" name="user" placeholder="superadmin" required autofocus></div>'
            f'<div class="fg"><label>Contraseña</label><input type="password" name="pass" required></div>'
            f'<button class="btn bp blg bbl">🔐 Acceder al sistema</button></form>'
            f'<a href="/" style="display:block;text-align:center;margin-top:14px;font-size:.72rem;color:var(--mt)">&larr; Volver al inicio</a>'
            f'</div></div></body></html>')

@app.route("/super/panel")
def super_panel():
    if not is_sa(): return redirect("/super")
    tiendas=db_query("SELECT * FROM tiendas",fetchall=True) or []
    tot_t=len(tiendas); tot_u=0
    for t in tiendas:
        r=db_query("SELECT COUNT(*) as c FROM users WHERE tienda_id=%s",(t["id"],),fetchone=True)
        tot_u+=r["c"] if r else 0
    return base("⚙️ Panel Global del Sistema",(
        f'<div class="al a-k" style="font-size:.9rem">👋 Bienvenido <strong>Super Admin</strong>. Aquí solo gestionas tiendas y credenciales de administradores. Las ventas y finanzas son privadas de cada tienda.</div>'
        f'<div class="kg">'
        f'<div class="kc k-bl"><div class="ki">🏪</div><div class="kl">Tiendas</div><div class="kv">{tot_t}</div></div>'
        f'<div class="kc k-cy"><div class="ki">👥</div><div class="kl">Total Usuarios</div><div class="kv">{tot_u}</div></div>'
        f'</div>'
        f'<div class="sec"><div class="sh"><h3>⚡ Acciones Rápidas</h3></div>'
        f'<div class="sb2" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:11px">'
        f'<a href="/super/tiendas" class="btn bp blg">🏪 Ver Tiendas</a>'
        f'<a href="/super/nueva_tienda" class="btn bs blg">➕ Nueva Tienda</a>'
        f'<a href="/super/usuarios" class="btn bg blg">👥 Ver Admins</a>'
        f'</div></div>'))

@app.route("/super/tiendas")
def super_tiendas():
    if not is_sa(): return redirect("/super")
    tiendas=db_query("SELECT * FROM tiendas",fetchall=True) or []
    cards=""
    for t in tiendas:
        nu=db_query("SELECT COUNT(*) as c FROM users WHERE tienda_id=%s",(t["id"],),fetchone=True)
        activa=t.get("activa",1)
        cards+=(f'<div class="tc" style="border-color:{t.get("color","#4f46e5")}">'
                f'<div class="tc-top"><span class="tc-em">{t.get("emoji","🏪")}</span>'
                f'<div class="tc-info"><h3>{t["nombre"]}</h3>'
                f'<p>{t.get("tipo","")} &middot; {t.get("ciudad","")}</p>'
                f'<p style="font-size:.7rem;color:var(--mt);margin-top:3px">ID: <code>{t["id"]}</code></p>'
                f'<span class="tag {"t-gr" if activa else "t-rd"}">{"Activa" if activa else "Inactiva"}</span>'
                f'</div></div>'
                f'<div class="tc-stats">'
                f'<div class="tc-s"><div class="tc-sv">{nu["c"] if nu else 0}</div><div class="tc-sl">Usuarios</div></div>'
                f'<div class="tc-s"><div class="tc-sv">{"✅" if activa else "❌"}</div><div class="tc-sl">Estado</div></div>'
                f'<div class="tc-s"><div class="tc-sv">🏪</div><div class="tc-sl">Tienda</div></div>'
                f'</div><div class="tc-acts">'
                f'<a href="/super/editar/{t["id"]}" class="btn bp bsm">✏️ Editar</a>'
                f'<a href="/super/admin/{t["id"]}" class="btn bg bsm">👥 Admins</a>'
                f'<a href="/login/{t["id"]}" target="_blank" class="btn bg bsm">🔗 Ir</a>'
                +(f'<a href="/super/desactivar/{t["id"]}" class="btn bd bsm" onclick="return confirm(\'Desactivar?\')">Desactivar</a>'
                  if activa else
                  f'<a href="/super/activar/{t["id"]}" class="btn bs bsm">Activar</a>')
                +f'<a href="/super/eliminar/{t["id"]}" class="btn bd bsm" onclick="return confirm(\'ELIMINAR {t["nombre"]}?\')">🗑️</a>'
                f'</div></div>')
    return base("🏪 Tiendas Registradas",(
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">'
        f'<p style="color:var(--mt);font-size:.84rem">{len(tiendas)} tienda(s) en el sistema</p>'
        f'<a href="/super/nueva_tienda" class="btn bp">➕ Nueva Tienda</a></div>'
        f'<div class="tc-grid">{cards}</div>'
        if cards else '<div class="al a-i">No hay tiendas. <a href="/super/nueva_tienda">Crear la primera</a></div>'))

@app.route("/super/nueva_tienda",methods=["GET","POST"])
def super_nueva_tienda():
    if not is_sa(): return redirect("/super")
    msg=""
    if request.method=="POST":
        tid_n=request.form.get("tid","").strip().lower().replace(" ","_").replace("-","_")
        nom=request.form.get("nombre","").strip()
        adm_u=request.form.get("adm_user","").strip(); adm_e=request.form.get("adm_email","").strip(); adm_p=request.form.get("adm_pass","")
        ok,mp=ok_pass(adm_p)
        ex=db_query("SELECT id FROM tiendas WHERE id=%s",(tid_n,),fetchone=True)
        if not tid_n or not nom: msg='<div class="al a-d">ID y nombre son obligatorios.</div>'
        elif ex: msg='<div class="al a-d">Ya existe una tienda con ese ID.</div>'
        elif not adm_u or not adm_e: msg='<div class="al a-d">Usuario y email del admin son obligatorios.</div>'
        elif not ok_email(adm_e): msg=f'<div class="al a-d">Email del admin no válido.</div>'
        elif not ok: msg=f'<div class="al a-d">Contraseña admin: {mp}</div>'
        else:
            db_query("INSERT INTO tiendas(id,nombre,tipo,ciudad,telefono,whatsapp,whatsapp_msg,nit,color,emoji,horario,direccion,activa,creada) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)",
                     (tid_n,nom,request.form.get("tipo","Tienda"),request.form.get("ciudad","Fusagasuga"),
                      request.form.get("telefono",""),request.form.get("whatsapp","").replace("+","").replace(" ",""),
                      f"Hola! Me interesa hacer un pedido en {nom}.",request.form.get("nit",""),
                      request.form.get("color","#4f46e5"),request.form.get("emoji","🏪"),
                      request.form.get("horario","Lun-Sab 8:00AM-6:00PM"),request.form.get("direccion",""),now()),commit=True)
            db_query("INSERT INTO users(tienda_id,user,nombre,password,rol,email,telefono,tratamiento_datos) VALUES(%s,%s,%s,%s,'admin',%s,%s,1)",
                     (tid_n,adm_u,f"Administrador {nom}",generate_password_hash(adm_p),adm_e,request.form.get("adm_tel","")),commit=True)
            msg=(f'<div class="al a-s">✅ Tienda <strong>{nom}</strong> creada!<br>'
                 f'Admin: <strong>{adm_u}</strong> | URL: <code>/login/{tid_n}</code></div>')
    return base("➕ Nueva Tienda",(
        f'<div class="sec" style="max-width:700px;margin:auto"><div class="sh"><h3>Crear Nueva Tienda</h3></div><div class="sb2">{msg}'
        f'<form method="post"><div class="fg2">'
        f'<div class="fg"><label>ID Tienda * (sin espacios)</label><input type="text" name="tid" placeholder="panaderia_real" required>'
        f'<span class="ph">Solo letras, números y guion bajo</span></div>'
        f'<div class="fg"><label>Nombre *</label><input type="text" name="nombre" placeholder="Panadería La Real" required></div>'
        f'<div class="fg"><label>Tipo</label><select name="tipo"><option>Panaderia</option><option>Abarrotes</option><option>Supermercado</option><option>Cafeteria</option><option>Restaurante</option><option>Minimarket</option></select></div>'
        f'<div class="fg"><label>Ciudad</label><input type="text" name="ciudad" value="Fusagasuga"></div>'
        f'<div class="fg"><label>Teléfono</label><input type="tel" name="telefono" placeholder="3101234567"></div>'
        f'<div class="fg"><label>WhatsApp (con 57)</label><input type="text" name="whatsapp" placeholder="573101234567"></div>'
        f'<div class="fg"><label>NIT</label><input type="text" name="nit" placeholder="900111222-1"></div>'
        f'<div class="fg"><label>Horario</label><input type="text" name="horario" value="Lun-Sab 8:00AM-6:00PM"></div>'
        f'<div class="fg c2"><label>Dirección</label><input type="text" name="direccion" placeholder="Calle 5 # 3-20, Centro"></div>'
        f'<div class="fg"><label>Color primario</label><input type="color" name="color" value="#4f46e5"></div>'
        f'<div class="fg"><label>Emoji</label><input type="text" name="emoji" value="🏪"></div>'
        f'</div>'
        f'<div style="margin:20px 0 14px;padding:16px;background:#f8faff;border-radius:11px;border:1.5px solid var(--bd)">'
        f'<p style="font-size:.82rem;font-weight:700;color:var(--mt);margin-bottom:12px;text-transform:uppercase">👤 Administrador de la Tienda</p>'
        f'<div class="fg2">'
        f'<div class="fg"><label>Usuario admin *</label><input type="text" name="adm_user" required></div>'
        f'<div class="fg"><label>Email admin *</label><input type="email" name="adm_email" required></div>'
        f'<div class="fg"><label>Teléfono admin</label><input type="tel" name="adm_tel"></div>'
        f'<div class="fg"><label>Contraseña admin *</label><input type="password" name="adm_pass" required>'
        f'<span class="ph">Min 8 | 1 MAYÚSCULA | 1 número | 1 especial</span></div>'
        f'</div></div>'
        f'<div class="fr"><button class="btn bp blg">🏪 Crear Tienda</button><a href="/super/tiendas" class="btn bg">Cancelar</a></div>'
        f'</form></div></div>'))

@app.route("/super/editar/<tid>",methods=["GET","POST"])
def super_editar(tid):
    if not is_sa(): return redirect("/super")
    t=db_query("SELECT * FROM tiendas WHERE id=%s",(tid,),fetchone=True)
    if not t: return redirect("/super/tiendas")
    msg=""
    if request.method=="POST":
        db_query("UPDATE tiendas SET nombre=%s,tipo=%s,ciudad=%s,telefono=%s,whatsapp=%s,whatsapp_msg=%s,nit=%s,banco=%s,cuenta=%s,color=%s,emoji=%s,horario=%s,direccion=%s WHERE id=%s",
                 (request.form.get("nombre",t["nombre"]).strip(),request.form.get("tipo",t.get("tipo","")),
                  request.form.get("ciudad",t.get("ciudad","")),request.form.get("telefono",t.get("telefono","")),
                  request.form.get("whatsapp","").replace("+","").replace(" ",""),
                  request.form.get("wmsg",t.get("whatsapp_msg","")),
                  request.form.get("nit",t.get("nit","")),request.form.get("banco",t.get("banco","")),
                  request.form.get("cuenta",t.get("cuenta","")),request.form.get("color",t.get("color","#4f46e5")),
                  request.form.get("emoji",t.get("emoji","🏪")),request.form.get("horario",t.get("horario","")),
                  request.form.get("direccion",t.get("direccion","")),tid),commit=True)
        t=db_query("SELECT * FROM tiendas WHERE id=%s",(tid,),fetchone=True)
        msg='<div class="al a-s">✅ Tienda actualizada.</div>'
    tipos=["Panaderia","Abarrotes","Supermercado","Cafeteria","Restaurante","Minimarket"]
    opts="".join(f'<option{"  selected" if t.get("tipo")==x else ""}>{x}</option>' for x in tipos)
    return base(f'✏️ Editar: {t["nombre"]}',(
        f'<div class="sec" style="max-width:640px;margin:auto"><div class="sh"><h3>✏️ Editar Tienda</h3></div><div class="sb2">{msg}'
        f'<form method="post"><div class="fg2">'
        f'<div class="fg"><label>Nombre</label><input type="text" name="nombre" value="{t["nombre"]}" required></div>'
        f'<div class="fg"><label>Tipo</label><select name="tipo">{opts}</select></div>'
        f'<div class="fg"><label>Ciudad</label><input type="text" name="ciudad" value="{str(t.get("ciudad",""))}"></div>'
        f'<div class="fg"><label>Teléfono</label><input type="text" name="telefono" value="{str(t.get("telefono",""))}"></div>'
        f'<div class="fg"><label>WhatsApp (con 57)</label><input type="text" name="whatsapp" value="{str(t.get("whatsapp",""))}"></div>'
        f'<div class="fg"><label>NIT</label><input type="text" name="nit" value="{str(t.get("nit",""))}"></div>'
        f'<div class="fg"><label>Banco</label><input type="text" name="banco" value="{str(t.get("banco",""))}"></div>'
        f'<div class="fg"><label>Cuenta</label><input type="text" name="cuenta" value="{str(t.get("cuenta",""))}"></div>'
        f'<div class="fg"><label>Color</label><input type="color" name="color" value="{str(t.get("color","#4f46e5"))}"></div>'
        f'<div class="fg"><label>Emoji</label><input type="text" name="emoji" value="{str(t.get("emoji","🏪"))}"></div>'
        f'<div class="fg c2"><label>Horario</label><input type="text" name="horario" value="{str(t.get("horario",""))}"></div>'
        f'<div class="fg c2"><label>Dirección</label><input type="text" name="direccion" value="{str(t.get("direccion",""))}"></div>'
        f'<div class="fg c2"><label>Mensaje WhatsApp</label><input type="text" name="wmsg" value="{str(t.get("whatsapp_msg",""))}"></div>'
        f'</div><div class="fr mt16"><button class="btn bp">💾 Guardar</button><a href="/super/tiendas" class="btn bg">Cancelar</a></div></form>'
        f'</div></div>'))

@app.route("/super/admin/<tid>",methods=["GET","POST"])
def super_admin(tid):
    if not is_sa(): return redirect("/super")
    t=get_tienda(tid); msg=""
    if not t: return redirect("/super/tiendas")
    if request.method=="POST":
        ac=request.form.get("accion","crear")
        if ac=="crear":
            u=request.form.get("user","").strip(); p=request.form.get("pass","")
            nom=request.form.get("nombre","").strip(); ema=request.form.get("email","").strip()
            ok,mp=ok_pass(p)
            ex=db_query("SELECT id FROM users WHERE user=%s AND tienda_id=%s",(u,tid),fetchone=True)
            if ex: msg='<div class="al a-d">Usuario ya existe.</div>'
            elif not ok: msg=f'<div class="al a-d">{mp}</div>'
            else:
                db_query("INSERT INTO users(tienda_id,user,nombre,password,rol,email,telefono,tratamiento_datos) VALUES(%s,%s,%s,%s,'admin',%s,%s,1)",
                         (tid,u,nom or u,generate_password_hash(p),ema,request.form.get("tel","")),commit=True)
                msg=f'<div class="al a-s">✅ Admin <strong>{u}</strong> creado.</div>'
        elif ac=="eliminar":
            db_query("DELETE FROM users WHERE id=%s AND tienda_id=%s",(request.form.get("uid",0),tid),commit=True)
            msg='<div class="al a-s">✅ Admin eliminado.</div>'
    admins=db_query("SELECT * FROM users WHERE tienda_id=%s AND rol='admin'",(tid,),fetchall=True) or []
    filas="".join(f"<tr><td><strong>{u['user']}</strong></td><td>{str(u.get('nombre',''))}</td><td>{str(u.get('email','-'))}</td><td>{str(u.get('telefono','-'))}</td>"
                  f"<td><form method='post' style='display:inline'><input type='hidden' name='accion' value='eliminar'><input type='hidden' name='uid' value='{u['id']}'><button class='btn bd bsm' onclick=\"return confirm('Eliminar admin?')\">Eliminar</button></form></td></tr>"
                  for u in admins)
    return base(f'👥 Admins: {t["nombre"]}',(
        f'<div class="g2">'
        f'<div class="sec"><div class="sh"><h3>Crear Admin</h3></div><div class="sb2">{msg}'
        f'<form method="post" style="display:flex;flex-direction:column;gap:11px"><input type="hidden" name="accion" value="crear">'
        f'<div class="fg"><label>Usuario *</label><input type="text" name="user" required></div>'
        f'<div class="fg"><label>Nombre</label><input type="text" name="nombre"></div>'
        f'<div class="fg"><label>Email *</label><input type="email" name="email" required></div>'
        f'<div class="fg"><label>Teléfono</label><input type="tel" name="tel"></div>'
        f'<div class="fg"><label>Contraseña *</label><input type="password" name="pass" required>'
        f'<span class="ph">Min 8 | 1 MAYÚSCULA | 1 número | 1 especial</span></div>'
        f'<button class="btn bp">Crear Admin</button></form></div></div>'
        f'<div class="sec"><div class="sh"><h3>Admins ({len(admins)})</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Usuario</th><th>Nombre</th><th>Email</th><th>Teléfono</th><th>Acción</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=5 class=tmuted>Sin admins</td></tr>" if not filas else filas}</tbody></table></div></div></div>'
        f'</div>'))

@app.route("/super/activar/<tid>")
def super_activar(tid):
    if not is_sa(): return redirect("/super")
    db_query("UPDATE tiendas SET activa=1 WHERE id=%s",(tid,),commit=True); return redirect("/super/tiendas")

@app.route("/super/desactivar/<tid>")
def super_desactivar(tid):
    if not is_sa(): return redirect("/super")
    db_query("UPDATE tiendas SET activa=0 WHERE id=%s",(tid,),commit=True); return redirect("/super/tiendas")

@app.route("/super/eliminar/<tid>")
def super_eliminar(tid):
    if not is_sa(): return redirect("/super")
    for tbl in ["productos","pedidos","users","proveedores","movimientos","recetas","produccion","caja","notificaciones","promociones","devoluciones"]:
        db_query(f"DELETE FROM {tbl} WHERE tienda_id=%s",(tid,),commit=True)
    db_query("DELETE FROM tiendas WHERE id=%s",(tid,),commit=True); return redirect("/super/tiendas")

@app.route("/super/usuarios")
def super_usuarios():
    if not is_sa(): return redirect("/super")
    rows=db_query("SELECT u.*,t.nombre as tnombre,t.emoji as temoji FROM users u JOIN tiendas t ON u.tienda_id=t.id WHERE u.rol='admin' ORDER BY u.tienda_id",fetchall=True) or []
    filas="".join(f"<tr><td>{str(u.get('temoji',''))} {str(u.get('tnombre',''))}</td><td><strong>{u['user']}</strong></td><td>{str(u.get('nombre',''))}</td><td>{str(u.get('email','-'))}</td><td><span class='tag t-pu'>admin</span></td></tr>" for u in rows)
    return base("👥 Todos los Administradores",(
        f'<div class="al a-i">Solo se muestran administradores. Los datos financieros de cada tienda son privados.</div>'
        f'<div class="sec"><div class="sh"><h3>Administradores ({len(rows)})</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Tienda</th><th>Usuario</th><th>Nombre</th><th>Email</th><th>Rol</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=5 class=tmuted>Sin admins</td></tr>" if not filas else filas}</tbody></table></div></div></div>'))

# ================================================================
#  ADMIN DASHBOARD
# ================================================================
@app.route("/admin")
def admin():
    if not is_ad(): return redirect("/")
    tid=tid_now(); t=get_tienda()
    np=db_query("SELECT COUNT(*) as c FROM productos WHERE tienda_id=%s",(tid,),fetchone=True)["c"]
    nped=db_query("SELECT COUNT(*) as c FROM pedidos WHERE tienda_id=%s",(tid,),fetchone=True)["c"]
    npro=db_query("SELECT COUNT(*) as c FROM promociones WHERE tienda_id=%s",(tid,),fetchone=True)["c"]
    ing=float(db_query("SELECT COALESCE(SUM(monto),0) as s FROM caja WHERE tienda_id=%s AND tipo='ingreso'",(tid,),fetchone=True)["s"] or 0)
    egr=float(db_query("SELECT COALESCE(SUM(monto),0) as s FROM caja WHERE tienda_id=%s AND tipo='egreso'",(tid,),fetchone=True)["s"] or 0)
    nl=db_query("SELECT COUNT(*) as c FROM notificaciones WHERE tienda_id=%s AND leida=0",(tid,),fetchone=True)["c"]
    bajos=db_query("SELECT * FROM productos WHERE tienda_id=%s AND cantidad<=stock_min",(tid,),fetchall=True) or []
    ultimos=db_query("SELECT * FROM pedidos WHERE tienda_id=%s ORDER BY id DESC LIMIT 5",(tid,),fetchall=True) or []
    pendientes_nequi=db_query("SELECT COUNT(*) as c FROM pedidos WHERE tienda_id=%s AND pago IN ('Nequi','Daviplata') AND estado='Pendiente'",(tid,),fetchone=True)["c"]
    al="".join(f'<div class="al a-w">⚠️ Stock bajo: <strong>{p["nombre"]}</strong> — {p["cantidad"]} {p.get("unidad","uds")}</div>' for p in bajos[:4]) or '<div class="al a-s">✅ Sin alertas de stock.</div>'
    col={"Pendiente":"t-am","Aprobado":"t-bl","En camino":"t-sk","Entregado":"t-gr","Cancelado":"t-rd","Devolucion":"t-pu"}
    filas="".join(f"<tr><td><strong>{str(p.get('codigo',''))}</strong></td><td>{str(p.get('producto',''))[:22]}</td><td>{str(p.get('user',''))}</td><td>{fmt(p.get('subtotal',0))}</td><td><span class='tag {col.get(p.get('estado',''),'t-gy')}'>{str(p.get('estado',''))}</span></td></tr>" for p in ultimos)
    nb2=f' <span class="nb">{nl}</span>' if nl else ""
    pend_pago=f'<div class="al a-w">💳 {pendientes_nequi} pedido(s) con Nequi/Daviplata pendientes de confirmar comprobante. <a href="/admin_pedidos">Ver</a></div>' if pendientes_nequi>0 else ""
    return base(f'📊 Dashboard — {t.get("nombre","")}',(
        pend_pago+
        f'<div class="kg">'
        f'<div class="kc k-bl"><div class="ki">📦</div><div class="kl">Productos</div><div class="kv">{np}</div></div>'
        f'<div class="kc k-gr"><div class="ki">💵</div><div class="kl">Ingresos</div><div class="kv" style="font-size:1.05rem">{fmt(ing)}</div></div>'
        f'<div class="kc k-rd"><div class="ki">💸</div><div class="kl">Egresos</div><div class="kv" style="font-size:1.05rem">{fmt(egr)}</div></div>'
        f'<div class="kc k-am"><div class="ki">🧾</div><div class="kl">Pedidos</div><div class="kv">{nped}</div></div>'
        f'<div class="kc k-rd"><div class="ki">⚠️</div><div class="kl">Stock Bajo</div><div class="kv">{len(bajos)}</div></div>'
        f'<div class="kc k-pu"><div class="ki">🎁</div><div class="kl">Promociones</div><div class="kv">{npro}</div></div>'
        f'<div class="kc k-bl"><div class="ki">💰</div><div class="kl">Saldo Neto</div><div class="kv" style="font-size:1.05rem">{fmt(ing-egr)}</div></div>'
        f'</div><div class="g2">'
        f'<div class="sec"><div class="sh"><h3>🔔 Alertas</h3><a href="/notificaciones" class="btn bg bsm">Ver{nb2}</a></div><div class="sb2">{al}</div></div>'
        f'<div class="sec"><div class="sh"><h3>🧾 Últimos Pedidos</h3><a href="/admin_pedidos" class="btn bg bsm">Ver todos</a></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Código</th><th>Producto</th><th>Cliente</th><th>Total</th><th>Estado</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=5 class=tmuted>Sin pedidos</td></tr>" if not filas else filas}</tbody></table></div></div></div>'
        f'<div class="sec"><div class="sh"><h3>⚡ Accesos Rápidos</h3></div>'
        f'<div class="sb2" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px">'
        f'<a href="/inventario" class="btn bp blg">📦 Inventario</a>'
        f'<a href="/admin_pedidos" class="btn bw2 blg">🧾 Pedidos</a>'
        f'<a href="/proveedores" class="btn bs blg">🚚 Proveedores</a>'
        f'<a href="/promociones" class="btn bg blg">🎁 Promociones</a>'
        f'<a href="/admin_devs" class="btn bpv blg">🔄 Devoluciones</a>'
        f'<a href="/produccion" class="btn bg blg">🍞 Producción</a>'
        f'<a href="/caja" class="btn bg blg">💰 Caja</a>'
        f'<a href="/reportes" class="btn bg blg">📈 Reportes</a>'
        f'<a href="/usuarios" class="btn bg blg">👥 Usuarios</a>'
        f'<a href="/domiciliarios" class="btn bdm blg">🏍️ Domiciliarios</a>'
        f'<a href="/config" class="btn bg blg">⚙️ Config</a>'
        f'</div></div>'))

# ================================================================
#  EMPLEADO DASHBOARD
# ================================================================
@app.route("/empleado")
def empleado():
    if not is_st(): return redirect("/")
    if is_ad(): return redirect("/admin")
    tid=tid_now()
    np=db_query("SELECT COUNT(*) as c FROM productos WHERE tienda_id=%s",(tid,),fetchone=True)["c"]
    nped=db_query("SELECT COUNT(*) as c FROM pedidos WHERE tienda_id=%s",(tid,),fetchone=True)["c"]
    bajos=db_query("SELECT * FROM productos WHERE tienda_id=%s AND cantidad<=stock_min",(tid,),fetchall=True) or []
    nprov=db_query("SELECT COUNT(*) as c FROM proveedores WHERE tienda_id=%s AND estado='Solicitado'",(tid,),fetchone=True)["c"]
    al="".join(f'<div class="al a-w">⚠️ Stock bajo: <strong>{p["nombre"]}</strong> — {p["cantidad"]} {p.get("unidad","uds")}</div>' for p in bajos[:5]) or '<div class="al a-s">✅ Sin alertas de stock.</div>'
    return base("🏠 Panel Empleado",(
        f'<div class="kg">'
        f'<div class="kc k-bl"><div class="ki">📦</div><div class="kl">Productos</div><div class="kv">{np}</div></div>'
        f'<div class="kc k-am"><div class="ki">🧾</div><div class="kl">Pedidos</div><div class="kv">{nped}</div></div>'
        f'<div class="kc k-rd"><div class="ki">⚠️</div><div class="kl">Stock Bajo</div><div class="kv">{len(bajos)}</div></div>'
        f'<div class="kc k-cy"><div class="ki">🚚</div><div class="kl">Prov. Pendientes</div><div class="kv">{nprov}</div></div>'
        f'</div>'
        f'<div class="sec"><div class="sh"><h3>🔔 Alertas de Stock</h3></div><div class="sb2">{al}</div></div>'
        f'<div class="sec"><div class="sh"><h3>⚡ Accesos Rápidos</h3></div>'
        f'<div class="sb2" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px">'
        f'<a href="/inventario_emp" class="btn bp blg">📦 Inventario</a>'
        f'<a href="/pos" class="btn bs blg">🧾 POS Ventas</a>'
        f'<a href="/prov_emp" class="btn bdm blg">🚚 Proveedores</a>'
        f'<a href="/produccion_emp" class="btn bg blg">🍞 Producción</a>'
        f'<a href="/notificaciones_emp" class="btn bw2 blg">🔔 Alertas</a>'
        f'<a href="/bot" class="btn bg blg">🤖 Asistente</a>'
        f'</div></div>'))

# ================================================================
#  INVENTARIO — ADMIN
# ================================================================
@app.route("/inventario",methods=["GET","POST"])
def inventario():
    if not is_ad(): return redirect("/")
    tid=tid_now(); msg=""
    if request.method=="POST":
        ac=request.form.get("ac","add")
        if ac=="add":
            nom=request.form.get("nombre","").strip()
            if not nom: msg='<div class="al a-d">El nombre es obligatorio.</div>'
            else:
                try:
                    db_query("INSERT INTO productos(tienda_id,nombre,categoria,precio,cantidad,stock_min,stock_max,unidad,img) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                             (tid,nom,request.form.get("categoria","General").strip(),
                              float(request.form.get("precio","0")),int(request.form.get("cantidad","0")),
                              int(request.form.get("stock_min","5")),int(request.form.get("stock_max","100")),
                              request.form.get("unidad","unidad").strip(),
                              request.form.get("img","").strip() or "https://images.unsplash.com/photo-1549931319-a545dcf3bc7c?w=400"),commit=True)
                    msg='<div class="al a-s">✅ Producto agregado.</div>'
                except Exception as e:
                    msg=f'<div class="al a-d">Error: {str(e)}</div>'
        elif ac=="del_all":
            if request.form.get("confirm_del")=="SI":
                db_query("DELETE FROM productos WHERE tienda_id=%s",(tid,),commit=True)
                msg='<div class="al a-s">✅ Inventario limpiado.</div>'
            else:
                msg='<div class="al a-d">Escribe SI para confirmar.</div>'
    prods=db_query("SELECT * FROM productos WHERE tienda_id=%s ORDER BY nombre",(tid,),fetchall=True) or []
    filas="".join(
        f"<tr><td><strong>{p['nombre']}</strong><br><span class='tmuted'>{p.get('categoria','')}</span></td>"
        f"<td>{fmt(p['precio'])}</td><td>{p['cantidad']} {p.get('unidad','')}</td><td>{p.get('stock_min','-')}</td>"
        f"<td><span class='tag {'t-rd' if p['cantidad']<=p.get('stock_min',5) else 't-gr'}'>{'Bajo' if p['cantidad']<=p.get('stock_min',5) else 'OK'}</span></td>"
        f"<td class='fr'><a href='/edit/{p['id']}' class='btn bw2 bsm'>Editar</a>"
        f"<a href='/del_prod/{p['id']}' class='btn bd bsm' onclick=\"return confirm('Eliminar {p['nombre'].replace(chr(39),'')}?')\">Eliminar</a></td></tr>"
        for p in prods)
    return base("📦 Inventario",(
        f'<div class="sec"><div class="sh"><h3>Agregar Producto</h3></div><div class="sb2">{msg}'
        f'<form method="post"><input type="hidden" name="ac" value="add"><div class="fg2">'
        f'<div class="fg"><label>Nombre *</label><input type="text" name="nombre" placeholder="Pan Francés" required></div>'
        f'<div class="fg"><label>Categoría</label><input type="text" name="categoria" placeholder="Panaderia"></div>'
        f'<div class="fg"><label>Precio (COP) *</label><input type="number" name="precio" placeholder="5000" min="0" required></div>'
        f'<div class="fg"><label>Stock Inicial *</label><input type="number" name="cantidad" placeholder="50" min="0" required></div>'
        f'<div class="fg"><label>Stock Mínimo</label><input type="number" name="stock_min" value="5" min="0"></div>'
        f'<div class="fg"><label>Stock Máximo</label><input type="number" name="stock_max" value="100" min="0"></div>'
        f'<div class="fg"><label>Unidad</label><input type="text" name="unidad" placeholder="unidad/kg/litro"></div>'
        f'<div class="fg"><label>URL Imagen</label><input type="url" name="img" placeholder="https://..."></div>'
        f'</div><div class="mt16"><button class="btn bp">💾 Guardar Producto</button></div></form></div></div>'
        f'<div class="sec"><div class="sh"><h3>Productos ({len(prods)})</h3>'
        f'<a href="/exportar_pdf/inventario" class="btn bg bsm">📄 Exportar PDF</a></div>'
        f'<div class="sb2"><div class="tw"><table>'
        f'<thead><tr><th>Nombre</th><th>Precio</th><th>Stock</th><th>Min</th><th>Estado</th><th>Acciones</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=6 class=tmuted>Sin productos</td></tr>" if not filas else filas}</tbody></table></div>'
        f'<details style="margin-top:16px"><summary style="cursor:pointer;color:var(--dn);font-size:.8rem;font-weight:700">🗑️ Limpiar todo el inventario</summary>'
        f'<form method="post" style="margin-top:10px;display:flex;gap:10px;align-items:center"><input type="hidden" name="ac" value="del_all">'
        f'<input type="text" name="confirm_del" placeholder="Escribe SI para confirmar" style="max-width:250px">'
        f'<button class="btn bd">Eliminar todo</button></form></details></div></div>'))


@app.route("/edit/<int:pid>",methods=["GET","POST"])
def edit(pid):
    if not is_ad(): return redirect("/")
    tid=tid_now()
    p=db_query("SELECT * FROM productos WHERE id=%s AND tienda_id=%s",(pid,tid),fetchone=True)
    if not p: return redirect("/inventario")
    if request.method=="POST":
        db_query("UPDATE productos SET nombre=%s,categoria=%s,precio=%s,cantidad=%s,stock_min=%s,stock_max=%s,unidad=%s,img=%s WHERE id=%s",
                 (request.form.get("nombre",p["nombre"]).strip(),request.form.get("categoria",p.get("categoria","")).strip(),
                  float(request.form.get("precio",p["precio"])),int(request.form.get("cantidad",p["cantidad"])),
                  int(request.form.get("stock_min",p.get("stock_min",5))),int(request.form.get("stock_max",p.get("stock_max",100))),
                  request.form.get("unidad",p.get("unidad","")).strip(),request.form.get("img",p.get("img","")).strip(),pid),commit=True)
        return redirect("/inventario")
    return base(f'✏️ Editar: {p["nombre"]}',(
        f'<div class="sec" style="max-width:520px;margin:auto"><div class="sh"><h3>{p["nombre"]}</h3></div><div class="sb2">'
        f'<form method="post"><div class="fg2">'
        f'<div class="fg"><label>Nombre</label><input type="text" name="nombre" value="{p["nombre"]}" required></div>'
        f'<div class="fg"><label>Categoría</label><input type="text" name="categoria" value="{str(p.get("categoria",""))}"></div>'
        f'<div class="fg"><label>Precio</label><input type="number" name="precio" value="{p["precio"]}" required></div>'
        f'<div class="fg"><label>Stock Actual</label><input type="number" name="cantidad" value="{p["cantidad"]}" required></div>'
        f'<div class="fg"><label>Stock Min</label><input type="number" name="stock_min" value="{p.get("stock_min",5)}"></div>'
        f'<div class="fg"><label>Stock Max</label><input type="number" name="stock_max" value="{p.get("stock_max",100)}"></div>'
        f'<div class="fg"><label>Unidad</label><input type="text" name="unidad" value="{str(p.get("unidad",""))}"></div>'
        f'<div class="fg"><label>URL Imagen</label><input type="url" name="img" value="{str(p.get("img",""))}"></div>'
        f'</div><div class="fr mt16"><button class="btn bs">💾 Guardar</button><a href="/inventario" class="btn bg">Cancelar</a></div></form></div></div>'))

@app.route("/del_prod/<int:pid>")
def del_prod(pid):
    if not is_ad(): return redirect("/")
    db_query("DELETE FROM productos WHERE id=%s AND tienda_id=%s",(pid,tid_now()),commit=True); return redirect("/inventario")

# ================================================================
#  INVENTARIO EMPLEADO — con merma de stock
# ================================================================
@app.route("/inventario_emp",methods=["GET","POST"])
def inventario_emp():
    if not is_st(): return redirect("/")
    tid=tid_now(); msg=""
    if request.method=="POST":
        pid=int(request.form.get("pid",0)); tipo=request.form.get("tipo","entrada")
        cant=int(request.form.get("cant",0)); motivo=request.form.get("motivo","").strip()
        p=db_query("SELECT * FROM productos WHERE id=%s AND tienda_id=%s",(pid,tid),fetchone=True)
        if p:
            if tipo in ("salida","merma") and p["cantidad"]<cant:
                msg='<div class="al a-d">Stock insuficiente.</div>'
            else:
                nueva=p["cantidad"]+cant if tipo in ("entrada","produccion") else p["cantidad"]-cant
                db_query("UPDATE productos SET cantidad=%s WHERE id=%s",(nueva,pid),commit=True)
                db_query("INSERT INTO movimientos(tienda_id,nombre,tipo,cant,motivo,fecha,user) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                         (tid,p["nombre"],tipo,cant,motivo,now(),session.get("user","")),commit=True)
                if nueva<=p.get("stock_min",5):
                    db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                             (tid,f"⚠️ Stock bajo: {p['nombre']} — {nueva} {p.get('unidad','uds')}",now()),commit=True)
                msg=f'<div class="al a-s">✅ Registrado. Stock actual: <strong>{nueva} {p.get("unidad","uds")}</strong></div>'
    prods=db_query("SELECT * FROM productos WHERE tienda_id=%s ORDER BY nombre",(tid,),fetchall=True) or []
    movs=db_query("SELECT * FROM movimientos WHERE tienda_id=%s ORDER BY id DESC LIMIT 20",(tid,),fetchall=True) or []
    opts="".join(f"<option value='{p['id']}'>{p['nombre']} (stock: {p['cantidad']} {p.get('unidad','')})</option>" for p in prods)
    tt={"entrada":"t-gr","salida":"t-am","merma":"t-rd","produccion":"t-bl"}
    filas="".join(f"<tr><td>{m.get('nombre','')}</td><td><span class='tag {tt.get(m.get('tipo',''),'t-gy')}'>{m.get('tipo','')}</span></td><td>{m.get('cant','')}</td><td>{m.get('motivo','')}</td><td>{m.get('fecha','')}</td></tr>" for m in movs)
    # Alertas de stock bajo
    bajos=db_query("SELECT * FROM productos WHERE tienda_id=%s AND cantidad<=stock_min",(tid,),fetchall=True) or []
    alerta="".join(f'<div class="al a-w">⚠️ <strong>{p["nombre"]}</strong>: {p["cantidad"]} {p.get("unidad","uds")} (mín: {p["stock_min"]})</div>' for p in bajos) if bajos else ""
    return base("📦 Movimientos de Inventario",(
        (f'<div class="sec"><div class="sh"><h3>🔔 Alertas de Stock Bajo</h3></div><div class="sb2">{alerta}</div></div>' if bajos else "")+
        f'<div class="sec"><div class="sh"><h3>Registrar Movimiento</h3></div><div class="sb2">{msg}'
        f'<form method="post"><div class="fg2">'
        f'<div class="fg"><label>Producto</label><select name="pid">{opts}</select></div>'
        f'<div class="fg"><label>Tipo</label><select name="tipo">'
        f'<option value="entrada">📥 Entrada (recibido)</option>'
        f'<option value="salida">📤 Salida (venta/uso)</option>'
        f'<option value="merma">🗑️ Merma (dañado/vencido)</option>'
        f'<option value="produccion">🍞 Producción</option>'
        f'</select></div>'
        f'<div class="fg"><label>Cantidad</label><input type="number" name="cant" min="1" required></div>'
        f'<div class="fg"><label>Motivo / Observación</label><input type="text" name="motivo" placeholder="Describe el movimiento"></div>'
        f'</div><div class="mt16"><button class="btn bp">✅ Registrar</button></div></form></div></div>'
        f'<div class="sec"><div class="sh"><h3>Historial Reciente</h3><a href="/exportar_pdf/movimientos" class="btn bg bsm">📄 Exportar PDF</a></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Producto</th><th>Tipo</th><th>Cantidad</th><th>Motivo</th><th>Fecha</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=5 class=tmuted>Sin movimientos</td></tr>" if not filas else filas}</tbody></table></div></div></div>'))

# ================================================================
#  TIENDA CLIENTE — con promociones
# ================================================================
@app.route("/tienda")
def tienda():
    if not li(): return redirect("/")
    if is_ad(): return redirect("/admin")
    if is_em(): return redirect("/empleado")
    if is_dm(): return redirect("/domi")
    if is_pv(): return redirect("/prov")
    tid=tid_now(); t=get_tienda()
    wa=t.get("whatsapp","").strip().replace("+","").replace(" ","")
    wa_msg=t.get("whatsapp_msg","Hola!").replace(" ","%20")
    prods=db_query("SELECT * FROM productos WHERE tienda_id=%s ORDER BY nombre",(tid,),fetchall=True) or []
    promos=db_query("SELECT * FROM promociones WHERE tienda_id=%s AND activa=1 AND (hasta IS NULL OR hasta>=%s)",(tid,hoy()),fetchall=True) or []
    # Banners de promociones
    ph=""
    if promos:
        ph='<div style="margin-bottom:20px">'
        for pr in promos[:3]:
            ph+=(f'<div class="promo-banner" style="background:linear-gradient(135deg,{pr.get("color","#ef4444")},{pr.get("color2","#f97316")})">'
                 f'<h4>🎁 {pr["titulo"]}</h4>'
                 f'<p>{pr.get("descripcion","")}</p>'
                 f'<span class="promo-badge">💰 {pr.get("descuento","")}</span>'
                 f'</div>')
        ph+='</div>'
    cards=""
    for p in prods:
        pr_m=next((pr for pr in promos if str(p["id"]) in (pr.get("pids") or "").split(",")),None)
        ag=p["cantidad"]==0
        badge=f"<span class='tag t-rd'>Sin stock</span>" if ag else f"<span class='tag t-gr'>Stock: {p['cantidad']}</span>"
        btn=f"<button class='btn bg bsm' disabled>Agotado</button>" if ag else f"<a href='/add_cart/{p['id']}' class='btn bp bsm'>🛒 Agregar</a>"
        wa_b=f"<a href='https://wa.me/{wa}?text={wa_msg}' target='_blank' class='btn bwa bsm'>{WA_SVG}</a>" if wa else ""
        prl=(f'<br><span style="background:#ef4444;color:#fff;font-size:.62rem;font-weight:800;padding:2px 8px;border-radius:10px;display:inline-block;margin-top:3px">'
             f'🏷️ {pr_m["descuento"]} OFF</span>') if pr_m else ""
        img=p.get("img") or "https://images.unsplash.com/photo-1549931319-a545dcf3bc7c?w=400"
        cards+=(f'<div class="pc">'
                f'<img src="{img}" alt="{p["nombre"]}" loading="lazy" onerror="this.src=\'https://images.unsplash.com/photo-1549931319-a545dcf3bc7c?w=400\'">'
                f'<div class="pcb"><div class="pcn">{p["nombre"]}{prl}</div><div class="pcc">{p.get("categoria","")}</div>{badge}'
                f'<div class="pcp">{fmt(p["precio"])}</div></div>'
                f'<div class="pcf">{btn}{wa_b}</div></div>')
    return base(f'🏪 Tienda — {t.get("nombre","")}',ph+f'<div class="pg">{cards}</div>' if cards else ph+'<div class="al a-i">No hay productos disponibles.</div>')

# ================================================================
#  CARRITO
# ================================================================
@app.route("/add_cart/<int:pid>")
def add_cart(pid):
    if not li(): return redirect("/")
    p=db_query("SELECT * FROM productos WHERE id=%s AND tienda_id=%s",(pid,tid_now()),fetchone=True)
    if p and p["cantidad"]>0:
        if "carrito" not in session or not isinstance(session["carrito"],dict): session["carrito"]={}
        a=session["carrito"].get(str(pid),0)
        if a<p["cantidad"]: session["carrito"][str(pid)]=a+1; session.modified=True
    return redirect("/tienda")

@app.route("/carrito")
def carrito():
    if not li(): return redirect("/")
    tid=tid_now(); cart=session.get("carrito") or {}
    if not isinstance(cart,dict): cart={}
    tot=0; rows=""; iv={}
    for ps,c in cart.items():
        p=db_query("SELECT * FROM productos WHERE id=%s AND tienda_id=%s",(int(ps),tid),fetchone=True)
        if not p: continue
        c=min(c,p["cantidad"])
        if c<=0: continue
        iv[ps]=c; sub=float(p["precio"])*c; tot+=sub
        rows+=(f'<div class="cr"><div><div class="cn">{p["nombre"]}</div><div class="cs">{fmt(p["precio"])} x{c} = <strong>{fmt(sub)}</strong></div></div>'
               f'<div class="crt"><div class="ctot">{fmt(sub)}</div>'
               f"<a href='/cart_menos/{p['id']}' class='btn bg bsm'>−</a>"
               f"<a href='/add_cart/{p['id']}' class='btn bg bsm'>+</a>"
               f"<a href='/cart_quit/{p['id']}' class='btn bd bsm'>✕</a></div></div>")
    session["carrito"]=iv; session.modified=True
    if not rows:
        return base("🛒 Carrito",(
            '<div class="sec" style="max-width:540px;margin:auto"><div class="sh"><h3>Carrito vacío</h3></div>'
            '<div class="sb2"><div class="al a-i">Tu carrito está vacío.</div>'
            '<a href="/tienda" class="btn bp blg bbl">🛍️ Ir a la tienda</a></div></div>'))
    nc=sum(iv.values())
    return base(f'🛒 Carrito ({nc} items)',(
        f'<div class="sec" style="max-width:640px;margin:auto"><div class="sh"><h3>Mi Carrito — {nc} item(s)</h3>'
        f'<a href="/cart_vac" class="btn bg bsm">Vaciar</a></div>'
        f'<div class="sb2">{rows}<div class="sep"></div>'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px">'
        f'<span style="font-weight:600;color:var(--mt)">TOTAL A PAGAR</span>'
        f'<span style="font-size:1.5rem;font-weight:900;color:var(--sc)">{fmt(tot)}</span></div>'
        f'<div class="fr"><a href="/tienda" class="btn bg blg">Seguir comprando</a>'
        f'<a href="/checkout" class="btn bs blg">💳 Pagar ahora</a></div></div></div>'))

@app.route("/cart_menos/<int:pid>")
def cart_menos(pid):
    if not li(): return redirect("/")
    c=session.get("carrito") or {}
    if not isinstance(c,dict): c={}
    s=str(pid)
    if s in c:
        c[s]=max(0,c[s]-1)
        if c[s]==0: c.pop(s)
    session["carrito"]=c; session.modified=True; return redirect("/carrito")

@app.route("/cart_quit/<int:pid>")
def cart_quit(pid):
    if not li(): return redirect("/")
    c=session.get("carrito") or {}
    if not isinstance(c,dict): c={}
    c.pop(str(pid),None); session["carrito"]=c; session.modified=True; return redirect("/carrito")

@app.route("/cart_vac")
def cart_vac():
    if not li(): return redirect("/")
    session["carrito"]={}; session.modified=True; return redirect("/carrito")

# ================================================================
#  CHECKOUT — PASARELA DE PAGO PREMIUM
# ================================================================
@app.route("/checkout",methods=["GET","POST"])
def checkout():
    if not li(): return redirect("/")
    tid=tid_now(); cart=session.get("carrito") or {}
    if not isinstance(cart,dict) or not cart: return redirect("/carrito")
    t=get_tienda(); err=""
    ip=[]; tp=0.0
    for ps,c in cart.items():
        p=db_query("SELECT * FROM productos WHERE id=%s AND tienda_id=%s",(int(ps),tid),fetchone=True)
        if not p: continue
        c=min(c,p["cantidad"])
        if c<=0: continue
        sub=float(p["precio"])*c; tp+=sub
        ip.append({"nombre":p["nombre"],"cant":c,"sub":sub})
    if not ip: return redirect("/carrito")

    if request.method=="POST":
        met=request.form.get("pago","Efectivo")
        ent=request.form.get("entrega","recogida")
        dir_=request.form.get("dir","").strip()
        if ent=="domicilio" and not dir_:
            err='<div class="al a-d">⚠️ La dirección es obligatoria para domicilio.</div>'
        else:
            items_list=[]; tf=0.0
            conn=get_db()
            new_cod=""
            try:
                with conn.cursor() as cur:
                    for ps,c in list(cart.items()):
                        p=db_query("SELECT * FROM productos WHERE id=%s AND tienda_id=%s",(int(ps),tid),fetchone=True)
                        if not p: continue
                        c=min(c,p["cantidad"])
                        if c<=0: continue
                        sub=float(p["precio"])*c; tf+=sub
                        items_list.append({"nombre":p["nombre"],"cantidad":c,
                                           "precio":float(p["precio"]),"subtotal":sub,"img":p.get("img","")})
                        cur.execute("UPDATE productos SET cantidad=%s WHERE id=%s",(p["cantidad"]-c,p["id"]))
                    if items_list:
                        new_cod="ORD"+str(random.randint(10000,99999))
                        items_json=json.dumps(items_list,ensure_ascii=False)
                        prod_names=", ".join(i["nombre"] for i in items_list)
                        tot_cant=sum(i["cantidad"] for i in items_list)
                        can_hasta=(datetime.now()+timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")
                        cur.execute(
                            "INSERT INTO pedidos(tienda_id,codigo,user,producto,cantidad,precio,subtotal,"
                            "items,pago,entrega,direccion,estado,fecha,cancelable_hasta) "
                            "VALUES(%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,'Pendiente',%s,%s)",
                            (tid,new_cod,session.get("user"),prod_names,tot_cant,tf,
                             items_json,met,ent,dir_,now(),can_hasta))
                        new_ped_id=cur.lastrowid
                        cur.execute("INSERT INTO caja(tienda_id,tipo,monto,descripcion,fecha) VALUES(%s,'ingreso',%s,%s,%s)",
                                    (tid,tf,f"Pedido {new_cod}",now()))
                        cur.execute("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                                    (tid,f"{'🏍️' if ent=='domicilio' else '🛍️'} Nuevo pedido {new_cod} de {session.get('user','')} — {fmt(tf)}",now()))
                        # Guardar comprobante si lo subieron
                        comp_file=request.files.get("comprobante")
                        if comp_file and comp_file.filename and met in ("Nequi","Daviplata"):
                            datos=comp_file.read()
                            mime=comp_file.mimetype or "image/jpeg"
                            nombre_a=comp_file.filename[:200]
                            cur.execute("INSERT INTO comprobantes(tienda_id,pedido_id,codigo,nombre_archivo,datos,mimetype,fecha) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                                        (tid,new_ped_id,new_cod,nombre_a,datos,mime,now()))
                            cur.execute("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                                        (tid,f"📎 Comprobante de pago recibido para {new_cod}",now()))
                conn.commit()
            finally:
                conn.close()
            session["carrito"]={}
            session["ultp"]=new_cod
            session["ultp_met"]=met
            session["ultp_tot"]=str(tf)
            session.modified=True
            return redirect("/conf_pedido")

    tel  = t.get("telefono","").strip()
    wa   = t.get("whatsapp","").strip().replace("+","").replace(" ","")
    banco= t.get("banco","").strip()
    cuenta=t.get("cuenta","").strip()

    res="".join(
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:8px 0;border-bottom:1px solid var(--bd)">'
        f'<span style="font-size:.84rem">{i2["nombre"]} '
        f'<span style="color:var(--mt)">×{i2["cant"]}</span></span>'
        f'<strong>{fmt(i2["sub"])}</strong></div>'
        for i2 in ip)

    wa_comp=f'<a href="https://wa.me/{wa}?text=Hola+envio+comprobante+de+pago" target="_blank" class="btn bwa bbl" style="margin-top:8px">{WA_SVG} También puedes enviarlo por WhatsApp</a>' if wa else ""

    return base("💳 Confirmar Compra",(
        f'<div style="max-width:900px;margin:0 auto">{err}'
        # Resumen pedido
        f'<div class="sec" style="margin-bottom:18px">'
        f'<div class="sh"><h3>🛒 Resumen</h3>'
        f'<span style="font-size:.83rem;color:var(--mt)">{sum(i["cant"] for i in ip)} ítem(s)</span></div>'
        f'<div class="sb2">{res}'
        f'<div style="display:flex;justify-content:space-between;margin-top:14px;'
        f'padding-top:13px;border-top:2.5px solid var(--bd)">'
        f'<strong style="font-size:1rem">TOTAL</strong>'
        f'<strong style="font-size:1.35rem;color:var(--sc)">{fmt(tp)}</strong></div>'
        f'</div></div>'
        # Form
        f'<form method="post" enctype="multipart/form-data" id="ckform">'
        # Métodos de pago
        f'<div class="sec"><div class="sh"><h3>💳 Método de pago</h3></div><div class="sb2">'
        f'<div class="pago-grid">'
        # Nequi
        f'<label class="pago-card nequi" id="card-Nequi" onclick="selPago(\'Nequi\')">'
        f'<input type="radio" name="pago" value="Nequi" id="r-Nequi">'
        f'<div class="pago-check" id="chk-Nequi">✓</div>'
        f'<span class="pago-icon">📱</span>'
        f'<span class="pago-name" style="color:#5f259f">Nequi</span>'
        f'<div class="pago-num">{tel or "Configura en ajustes"}</div>'
        f'<div class="pago-desc">Transferencia al instante<br>Sube tu comprobante</div></label>'
        # Daviplata
        f'<label class="pago-card daviplata" id="card-Daviplata" onclick="selPago(\'Daviplata\')">'
        f'<input type="radio" name="pago" value="Daviplata" id="r-Daviplata">'
        f'<div class="pago-check" id="chk-Daviplata">✓</div>'
        f'<span class="pago-icon">💳</span>'
        f'<span class="pago-name" style="color:#E40046">Daviplata</span>'
        f'<div class="pago-num">{tel or "Configura en ajustes"}</div>'
        f'<div class="pago-desc">Pago digital seguro<br>Sube tu comprobante</div></label>'
        # Efectivo
        f'<label class="pago-card efectivo" id="card-Efectivo" onclick="selPago(\'Efectivo\')">'
        f'<input type="radio" name="pago" value="Efectivo" id="r-Efectivo">'
        f'<div class="pago-check" id="chk-Efectivo">✓</div>'
        f'<span class="pago-icon">💵</span>'
        f'<span class="pago-name" style="color:#16a34a">Efectivo</span>'
        f'<div class="pago-num">Sin recargo</div>'
        f'<div class="pago-desc">Pagas al recibir<br>Sin pasos adicionales</div></label>'
        f'</div>'
        # Instrucciones Nequi
        f'<div class="pay-instructions nequi" id="inst-Nequi">'
        f'<p style="font-weight:800;color:#5f259f;margin-bottom:12px">📱 Cómo pagar con Nequi</p>'
        f'<div class="pay-step"><div class="pay-step-num">1</div><div>Abre la app de <strong>Nequi</strong></div></div>'
        f'<div class="pay-step"><div class="pay-step-num">2</div><div>Envía <strong>{fmt(tp)}</strong> al número <strong style="font-size:1rem;color:#5f259f">{tel or "—"}</strong></div></div>'
        f'<div class="pay-step"><div class="pay-step-num">3</div><div>Escribe tu <strong>código de pedido</strong> en el concepto</div></div>'
        f'<div class="pay-step"><div class="pay-step-num">4</div><div>Sube aquí la foto del comprobante 👇</div></div>'
        f'<div class="comprobante-box" id="comp-box" onclick="document.getElementById(\'comprobante\').click()">'
        f'<div id="comp-ph"><span style="font-size:2rem">📸</span><br>'
        f'<span style="font-weight:700;color:#5f259f">Toca para subir comprobante</span><br>'
        f'<span style="font-size:.73rem;color:var(--mt)">JPG · PNG · PDF</span></div>'
        f'<img id="comp-prev" style="display:none;max-width:220px;border-radius:10px;margin:10px auto 0">'
        f'<p id="comp-name" style="font-size:.75rem;color:var(--sc);margin-top:6px;display:none"></p>'
        f'</div>'
        f'<input type="file" id="comprobante" name="comprobante" accept="image/*,.pdf" style="display:none" onchange="prevComp(this)">'
        f'{wa_comp}'
        f'</div>'
        # Instrucciones Daviplata
        f'<div class="pay-instructions daviplata" id="inst-Daviplata">'
        f'<p style="font-weight:800;color:#E40046;margin-bottom:12px">💳 Cómo pagar con Daviplata</p>'
        f'<div class="pay-step"><div class="pay-step-num">1</div><div>Abre la app de <strong>Daviplata</strong></div></div>'
        f'<div class="pay-step"><div class="pay-step-num">2</div><div>Envía <strong>{fmt(tp)}</strong> al número <strong style="font-size:1rem;color:#E40046">{tel or "—"}</strong></div></div>'
        f'<div class="pay-step"><div class="pay-step-num">3</div><div>Escribe tu <strong>código de pedido</strong></div></div>'
        f'<div class="pay-step"><div class="pay-step-num">4</div><div>Sube aquí la foto del comprobante 👇</div></div>'
        f'<div class="comprobante-box" id="comp-box2" onclick="document.getElementById(\'comprobante\').click()">'
        f'<div><span style="font-size:2rem">📸</span><br>'
        f'<span style="font-weight:700;color:#E40046">Toca para subir comprobante</span><br>'
        f'<span style="font-size:.73rem;color:var(--mt)">JPG · PNG · PDF</span></div>'
        f'</div>'
        f'{wa_comp}'
        f'</div>'
        # Instrucciones Efectivo
        f'<div class="pay-instructions efectivo" id="inst-Efectivo">'
        f'<p style="font-weight:800;color:#16a34a;margin-bottom:12px">💵 Pago en Efectivo</p>'
        f'<div class="pay-step"><div class="pay-step-num">✓</div><div>No necesitas hacer nada ahora. <strong>Pagas al recibir</strong> tu pedido.</div></div>'
        f'<div class="pay-step"><div class="pay-step-num">ℹ</div><div>Ten el valor exacto listo. Sin recargos.</div></div>'
        f'</div>'
        f'</div></div>'
        # Entrega
        f'<div class="sec"><div class="sh"><h3>🚚 Tipo de Entrega</h3></div><div class="sb2">'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">'
        f'<label id="ent-rec" style="border:2px solid var(--pr);background:#f0f4ff;border-radius:12px;'
        f'padding:16px;cursor:pointer;transition:.15s;display:flex;align-items:center;gap:11px" onclick="selEnt(\'recogida\')">'
        f'<input type="radio" name="entrega" value="recogida" id="er" checked style="accent-color:var(--pr)">'
        f'<div><div style="font-weight:700;font-size:.88rem">🏪 Recoger en tienda</div>'
        f'<div style="font-size:.74rem;color:var(--mt)">{t.get("horario","")}</div></div></label>'
        f'<label id="ent-dom" style="border:2px solid var(--bd);border-radius:12px;padding:16px;'
        f'cursor:pointer;transition:.15s;display:flex;align-items:center;gap:11px" onclick="selEnt(\'domicilio\')">'
        f'<input type="radio" name="entrega" value="domicilio" id="ed" style="accent-color:var(--pr)">'
        f'<div><div style="font-weight:700;font-size:.88rem">🏍️ Domicilio</div>'
        f'<div style="font-size:.74rem;color:var(--mt)">30-60 min aprox.</div></div></label>'
        f'</div>'
        f'<div id="dir-wrap" style="display:none"><div class="fg"><label>📍 Dirección de entrega *</label>'
        f'<div class="input-icon"><span class="icon">📍</span>'
        f'<input type="text" name="dir" id="dir-inp" placeholder="Calle 5 # 3-20, {t.get("ciudad","Fusagasugá")}"></div></div></div>'
        f'<div class="al a-i" style="margin-top:12px;font-size:.8rem">⏱️ Tienes <strong>10 minutos</strong> para cancelar.</div>'
        f'<button class="btn bs blg bbl" style="margin-top:16px">✅ Confirmar y Pagar {fmt(tp)}</button>'
        f'</div></div>'
        f'<a href="/carrito" class="btn bg bbl" style="margin-top:-10px;margin-bottom:24px">← Volver al carrito</a>'
        f'</form>'
        f'<script>'
        f'var pagoSel="";'
        f'function selPago(m){{'
        f'  pagoSel=m;'
        f'  ["Nequi","Daviplata","Efectivo"].forEach(function(p){{'
        f'    var c=document.getElementById("card-"+p);'
        f'    var ch=document.getElementById("chk-"+p);'
        f'    var inst=document.getElementById("inst-"+p);'
        f'    if(p===m){{c.classList.add("sel");ch.style.color="#fff";if(inst)inst.style.display="block";}}'
        f'    else{{c.classList.remove("sel");ch.style.color="transparent";if(inst)inst.style.display="none";}}'
        f'  }});'
        f'  document.getElementById("r-"+m).checked=true;'
        f'}}'
        f'function selEnt(e){{'
        f'  var dw=document.getElementById("dir-wrap");'
        f'  var di=document.getElementById("dir-inp");'
        f'  var er=document.getElementById("ent-rec");'
        f'  var ed=document.getElementById("ent-dom");'
        f'  if(e==="domicilio"){{'
        f'    dw.style.display="block";di.required=true;'
        f'    ed.style.borderColor="var(--dm)";ed.style.background="#f0f9ff";'
        f'    er.style.borderColor="var(--bd)";er.style.background="";'
        f'  }}else{{'
        f'    dw.style.display="none";di.required=false;'
        f'    er.style.borderColor="var(--pr)";er.style.background="#f0f4ff";'
        f'    ed.style.borderColor="var(--bd)";ed.style.background="";'
        f'  }}'
        f'  document.getElementById(e==="domicilio"?"ed":"er").checked=true;'
        f'}}'
        f'function prevComp(inp){{'
        f'  if(inp.files&&inp.files[0]){{'
        f'    var f=inp.files[0];'
        f'    if(f.type.startsWith("image/")&&document.getElementById("comp-prev")){{'
        f'      var r=new FileReader();r.onload=function(e){{'
        f'        var img=document.getElementById("comp-prev");'
        f'        img.src=e.target.result;img.style.display="block";'
        f'        if(document.getElementById("comp-box"))document.getElementById("comp-box").classList.add("has-file");'
        f'        if(document.getElementById("comp-box2"))document.getElementById("comp-box2").classList.add("has-file");'
        f'      }};r.readAsDataURL(f);'
        f'    }}'
        f'    var nm=document.getElementById("comp-name");'
        f'    if(nm){{nm.textContent="✅ "+f.name;nm.style.display="block";}}'
        f'  }}'
        f'}}'
        f'document.getElementById("ckform").addEventListener("submit",function(e){{'
        f'  if(!pagoSel){{e.preventDefault();alert("Por favor selecciona un método de pago 💳");return false;}}'
        f'}});'
        f'</script>'))

@app.route("/conf_pedido")
def conf_pedido():
    if not li(): return redirect("/")
    cod=session.pop("ultp","-"); met=session.pop("ultp_met","Efectivo"); tf=session.pop("ultp_tot","0")
    ped=db_query("SELECT * FROM pedidos WHERE codigo=%s AND tienda_id=%s",(cod,tid_now()),fetchone=True)
    tot=fmt(ped["subtotal"]) if ped else fmt(tf)
    pid=ped["id"] if ped else 0
    ent=ped.get("entrega","recogida") if ped else "recogida"
    t=get_tienda(); wa=t.get("whatsapp","").strip().replace("+","").replace(" ","")
    wm=f"Hola! Hice el pedido {cod} por {tot}. Pago: {met}. Adjunto comprobante.".replace(" ","%20")
    wb=(f"<a href='https://wa.me/{wa}?text={wm}' target='_blank' class='btn bwa blg'>{WA_SVG} Enviar comprobante</a>") if wa else ""

    instrucciones=""
    if met in ("Nequi","Daviplata"):
        tel=t.get("telefono","") or t.get("whatsapp","")

        link2 = ""
        if wa:
            link2 = f"<a href='https://wa.me/{wa}?text={wm}' target='_blank' class='btn bwa blg bbl' style='margin-top:12px'>{WA_SVG} Enviar comprobante ahora</a>"

        instrucciones=(
            f'<div style="background:linear-gradient(135deg,#f0f9ff,#fff);border:2px solid #38bdf8;border-radius:14px;padding:18px;margin:16px 0;text-align:left">'
            f'<p style="font-weight:900;color:#0369a1;margin-bottom:10px;font-size:.95rem">💳 Pasos para completar tu pago con {met}</p>'
            f'<div style="display:flex;flex-direction:column;gap:8px;font-size:.84rem">'
            f'<p>1️⃣ Abre tu app de <strong>{met}</strong></p>'
            f'<p>2️⃣ Transfiere <strong>{tot}</strong> al número: <strong style="font-size:1.1rem;color:#0369a1">{tel}</strong></p>'
            f'<p>3️⃣ Concepto: <strong>{cod}</strong></p>'
            f'<p>4️⃣ Toma pantallazo del comprobante</p>'
            f'<p>5️⃣ Envía el comprobante por WhatsApp 👇</p>'
            f'</div>'
            f'{link2}'
            f'</div>'
        )

    dm=(f'<div class="al a-k">🏍️ <strong>Pedido a domicilio.</strong> Te contactaremos al llegar. Puedes cancelarlo en los próximos 10 minutos.</div>'
        if ent=="domicilio" else
        f'<div class="al a-i">🏪 Listo para <strong>recogida en tienda</strong>. Puedes cancelarlo en los próximos 10 minutos.</div>')

    return base("✅ Pedido Confirmado",(
        f'<div class="sec" style="max-width:520px;margin:auto;text-align:center">'
        f'<div class="sb2" style="padding:36px">'
        f'<div style="font-size:4rem;margin-bottom:14px">🎉</div>'
        f'<h2 style="font-size:1.5rem;font-weight:900;color:var(--sc);margin-bottom:8px">¡Pedido realizado!</h2>'
        f'<p style="color:var(--mt);margin-bottom:18px">Tu pedido ha sido recibido correctamente.</p>'
        f'{dm}'
        f'<div style="background:linear-gradient(135deg,#f0fdf4,#fff);border:2px solid #bbf7d0;border-radius:14px;padding:20px;margin:16px 0">'
        f'<div style="font-size:.72rem;color:var(--mt);font-weight:700;text-transform:uppercase;margin-bottom:6px">Código de pedido</div>'
        f'<div style="font-size:2rem;font-weight:900;color:var(--sc);letter-spacing:.2em">{cod}</div>'
        f'<div style="font-size:1.1rem;font-weight:700;margin-top:8px">Total: {tot}</div>'
        f'<div style="font-size:.82rem;color:var(--mt);margin-top:4px">Método: {met}</div>'
        f'</div>'
        f'{instrucciones}'
        f'<div class="fr" style="justify-content:center;flex-wrap:wrap;gap:10px">'
        f'<a href="/mis_pedidos" class="btn bp blg">📦 Ver mis pedidos</a>'
        f'<a href="/pdf_pedido/{pid}" class="btn bg blg">📄 Descargar recibo</a>'
        f'{wb}</div>'
        f'<div class="mt16"><a href="/tienda" class="btn bg bbl">Seguir comprando</a></div>'
        f'</div></div>'
    ))

# ================================================================
#  MIS PEDIDOS
# ================================================================
@app.route("/mis_pedidos")
def mis_pedidos():
    if not li(): return redirect("/")
    tid=tid_now()
    peds=db_query("SELECT * FROM pedidos WHERE tienda_id=%s AND user=%s ORDER BY id DESC",(tid,session.get("user")),fetchall=True) or []
    if not peds:
        return base("📦 Mis Pedidos",(
            '<div class="sec" style="max-width:480px;margin:auto"><div class="sb2" style="text-align:center;padding:36px">'
            '<div style="font-size:3.5rem">📭</div>'
            '<p style="color:var(--mt);margin:14px 0">No tienes pedidos aún.</p>'
            '<a href="/tienda" class="btn bp blg">🛍️ Ir a la tienda</a></div></div>'))
    col={"Pendiente":"t-am","Aprobado":"t-bl","En camino":"t-sk","Entregado":"t-gr","Cancelado":"t-rd","Devolucion":"t-pu"}
    t=get_tienda(); wa=t.get("whatsapp","").strip().replace("+","").replace(" ","")
    cards=""
    for p in peds:
        tc=col.get(p.get("estado",""),"t-gy")
        items_list=[]
        try: items_list=json.loads(p.get("items") or "[]")
        except: pass
        ih="".join(f'<div style="font-size:.8rem;color:var(--mt);padding:2px 0">• {it["nombre"]} x{it["cantidad"]} = {fmt(it["subtotal"])}</div>' for it in items_list) or f'<div style="font-size:.8rem;color:var(--mt)">{str(p.get("producto",""))}</div>'
        ei="🏍️" if p.get("entrega")=="domicilio" else "🏪"
        cb=""; dv=""; comp_wa=""
        if p.get("estado") not in ("Cancelado","Entregado"):
            try:
                lim=datetime.strptime(p.get("cancelable_hasta",""),"%Y-%m-%d %H:%M")
                if datetime.now()<=lim:
                    cb=f"<a href='/cancelar_ped/{p['id']}' class='btn bd bsm' onclick=\"return confirm('Cancelar pedido?')\">Cancelar</a>"
            except: pass
        if p.get("estado")=="Entregado":
            dv=f"<a href='/pedir_dev/{p['id']}' class='btn bpv bsm'>Devolución</a>"
        if p.get("pago") in ("Nequi","Daviplata") and p.get("estado")=="Pendiente" and wa:
            wm=f"Hola! Soy {session.get('user','')}. Mi pedido {p.get('codigo','')} por {fmt(p.get('subtotal',0))}. Adjunto comprobante.".replace(" ","%20")
            comp_wa=f"<a href='https://wa.me/{wa}?text={wm}' target='_blank' class='btn bwa bsm'>{WA_SVG} Comprobante</a>"
        cards+=(f'<div class="sec"><div class="sh">'
                f'<div><h3 style="margin-bottom:3px">#{str(p.get("codigo",""))}</h3>'
                f'<span style="font-size:.72rem;color:var(--mt)">{str(p.get("fecha",""))} &middot; {str(p.get("pago",""))} &middot; {ei} {str(p.get("entrega","")).capitalize()}</span></div>'
                f'<span class="tag {tc}">{str(p.get("estado",""))}</span></div>'
                f'<div class="sb2">{ih}'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding-top:11px;border-top:1px solid var(--bd)">'
                f'<strong style="font-size:1rem;color:var(--sc)">Total: {fmt(p.get("subtotal",0))}</strong>'
                f'<div class="fr"><a href="/pdf_pedido/{p["id"]}" class="btn bg bsm">📄 PDF</a>{cb}{dv}{comp_wa}</div>'
                f'</div></div></div>')
    return base("📦 Mis Pedidos",cards)

@app.route("/cancelar_ped/<int:pid>")
def cancelar_ped(pid):
    if not li(): return redirect("/")
    tid=tid_now()
    p=db_query("SELECT * FROM pedidos WHERE id=%s AND tienda_id=%s AND user=%s",(pid,tid,session.get("user")),fetchone=True)
    if p and p.get("estado") not in ("Cancelado","Entregado"):
        try:
            lim=datetime.strptime(p.get("cancelable_hasta",""),"%Y-%m-%d %H:%M")
            if datetime.now()<=lim:
                db_query("UPDATE pedidos SET estado='Cancelado' WHERE id=%s",(pid,),commit=True)
                items_list=[]
                try: items_list=json.loads(p.get("items") or "[]")
                except: pass
                for it in items_list:
                    pr=db_query("SELECT * FROM productos WHERE nombre=%s AND tienda_id=%s",(it["nombre"],tid),fetchone=True)
                    if pr: db_query("UPDATE productos SET cantidad=%s WHERE id=%s",(pr["cantidad"]+it["cantidad"],pr["id"]),commit=True)
                db_query("INSERT INTO caja(tienda_id,tipo,monto,descripcion,fecha) VALUES(%s,'egreso',%s,%s,%s)",
                         (tid,p.get("subtotal",0),f"Cancelación {p.get('codigo','')}",now()),commit=True)
                db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                         (tid,f"❌ Pedido {p.get('codigo','')} cancelado.",now()),commit=True)
        except: pass
    return redirect("/mis_pedidos")

# ================================================================
#  DEVOLUCIONES — CLIENTE
# ================================================================
@app.route("/pedir_dev/<int:pid>",methods=["GET","POST"])
def pedir_dev(pid):
    if not li(): return redirect("/")
    tid=tid_now()
    p=db_query("SELECT * FROM pedidos WHERE id=%s AND tienda_id=%s AND user=%s",
               (pid,tid,session.get("user")),fetchone=True)
    if not p: return redirect("/mis_pedidos")
 
    prods=db_query("SELECT * FROM productos WHERE tienda_id=%s AND cantidad>0 ORDER BY nombre",
                   (tid,),fetchall=True) or []
 
    if request.method=="POST":
        tipo_sol=request.form.get("tipo_solicitud","devolucion")
        motivo=request.form.get("motivo","").strip()
        prod_cambio=request.form.get("producto_cambio","").strip() if tipo_sol=="cambio" else ""
        try:
            db_query(
                "INSERT INTO devoluciones(tienda_id,pedido_id,codigo,user,motivo,estado,fecha,subtotal)"
                " VALUES(%s,%s,%s,%s,%s,'Pendiente',%s,%s)",
                (tid,pid,p.get("codigo",""),session.get("user",""),
                 f"[{tipo_sol.upper()}] {prod_cambio+' — ' if prod_cambio else ''}{motivo}",
                 now(),p.get("subtotal",0)),commit=True)
        except Exception:
            db_query(
                "INSERT INTO devoluciones(tienda_id,pedido_id,codigo,user,motivo,estado,fecha,subtotal)"
                " VALUES(%s,%s,%s,%s,%s,'Pendiente',%s,%s)",
                (tid,pid,p.get("codigo",""),session.get("user",""),
                 f"[{tipo_sol.upper()}] {prod_cambio+' — ' if prod_cambio else ''}{motivo}",
                 now(),p.get("subtotal",0)),commit=True)
        db_query("UPDATE pedidos SET estado='Devolucion' WHERE id=%s",(pid,),commit=True)
        icono="💸" if tipo_sol=="devolucion" else "🔁"
        label="devolución" if tipo_sol=="devolucion" else f"cambio por {prod_cambio}"
        db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                 (tid,f"{icono} Solicitud de {label} — pedido {p.get('codigo','')}",now()),commit=True)
        return redirect("/mis_devs")
 
    val=float(p.get("subtotal",0))
    cant=max(int(p.get("cantidad",1)),1)
    precio_unit=val/cant
    rango_min=precio_unit*0.80; rango_max=precio_unit*1.20
    prod_opts="".join(
        f"<option value='{pr['nombre']}'>{pr['nombre']} — {fmt(pr['precio'])} / {pr.get('unidad','u')}</option>"
        for pr in prods if rango_min<=float(pr["precio"])<=rango_max
    )
    if not prod_opts:
        prod_opts="".join(
            f"<option value='{pr['nombre']}'>{pr['nombre']} — {fmt(pr['precio'])}</option>"
            for pr in prods)
 
    items_list=[]
    try: items_list=json.loads(p.get("items") or "[]")
    except: pass
    items_html="".join(
        f'<div style="font-size:.82rem;padding:4px 0;border-bottom:1px solid #f1f5f9">'
        f'• {it["nombre"]} ×{it["cantidad"]} = {fmt(it["subtotal"])}</div>'
        for it in items_list
    ) or f'<div style="font-size:.82rem">{p.get("producto","")}</div>'
 
    Q="'"
    return base("🔄 Solicitar Devolución o Cambio",(
        f'<div class="sec" style="max-width:560px;margin:auto">'
        f'<div class="sh"><h3>Pedido #{p.get("codigo","")} &nbsp;·&nbsp; {fmt(p.get("subtotal",0))}</h3></div>'
        f'<div class="sb2">'
        f'<div style="background:#f8faff;border-radius:10px;padding:12px;margin-bottom:18px">'
        f'<p style="font-size:.71rem;font-weight:800;color:var(--mt);text-transform:uppercase;'
        f'letter-spacing:.08em;margin-bottom:7px">Productos del pedido</p>'
        f'{items_html}'
        f'</div>'
        f'<form method="post" id="fdev" style="display:flex;flex-direction:column;gap:16px">'
        # ── Tipo de solicitud ──
        f'<div class="fg"><label>¿Qué deseas hacer?</label>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px">'
        # Devolución
        f'<label id="card-dev" onclick="selTipo({Q}devolucion{Q})" style="border:2.5px solid #5f259f;'
        f'background:linear-gradient(135deg,#faf5ff,#fff);border-radius:14px;padding:18px 14px;'
        f'cursor:pointer;text-align:center;transition:all .2s;box-shadow:0 0 0 3px rgba(95,37,159,.12)">'
        f'<input type="radio" name="tipo_solicitud" value="devolucion" id="r-dev" checked style="display:none">'
        f'<div style="font-size:2rem;margin-bottom:7px">💸</div>'
        f'<div style="font-weight:900;font-size:.9rem;color:#5f259f">Devolución</div>'
        f'<div style="font-size:.72rem;color:var(--mt);margin-top:5px;line-height:1.4">'
        f'Quiero que me devuelvan el dinero</div></label>'
        # Cambio
        f'<label id="card-cam" onclick="selTipo({Q}cambio{Q})" style="border:2.5px solid var(--bd);'
        f'background:#fff;border-radius:14px;padding:18px 14px;'
        f'cursor:pointer;text-align:center;transition:all .2s">'
        f'<input type="radio" name="tipo_solicitud" value="cambio" id="r-cam" style="display:none">'
        f'<div style="font-size:2rem;margin-bottom:7px">🔁</div>'
        f'<div style="font-weight:900;font-size:.9rem;color:#0ea5e9">Cambio</div>'
        f'<div style="font-size:.72rem;color:var(--mt);margin-top:5px;line-height:1.4">'
        f'Quiero cambiarlo por otro producto</div></label>'
        f'</div></div>'
        # ── Selector de producto para cambio ──
        f'<div id="bloque-cambio" style="display:none">'
        f'<div class="fg"><label>¿Por cuál producto lo quieres cambiar?</label>'
        f'<select name="producto_cambio" style="margin-top:4px">'
        f'<option value="">Selecciona un producto...</option>'
        f'{prod_opts}'
        f'</select>'
        f'<span class="ph">Mostramos productos con precio similar a tu pedido ({fmt(val)}). '
        f'La tienda confirmará disponibilidad.</span>'
        f'</div></div>'
        # ── Motivo ──
        f'<div class="fg"><label>¿Cuál es el motivo? *</label>'
        f'<textarea name="motivo" rows="3" required '
        f'placeholder="Cuéntanos qué pasó: producto dañado, incompleto, no era lo esperado..."></textarea>'
        f'</div>'
        # ── Aviso ──
        f'<div class="al a-i" style="font-size:.79rem">'
        f'⏰ Devoluciones y cambios disponibles hasta <strong>24 horas</strong> '
        f'después de recibido el pedido.</div>'
        f'<button class="btn bpv blg bbl">📤 Enviar solicitud</button>'
        f'</form>'
        f'<a href="/mis_pedidos" class="btn bg bbl mt16">← Volver a mis pedidos</a>'
        f'</div></div>'
        f'<script>'
        f'function selTipo(t){{'
        f'  var cd=document.getElementById("card-dev");'
        f'  var cc=document.getElementById("card-cam");'
        f'  var bc=document.getElementById("bloque-cambio");'
        f'  if(t==="devolucion"){{'
        f'    cd.style.borderColor="#5f259f";cd.style.background="linear-gradient(135deg,#faf5ff,#fff)";'
        f'    cd.style.boxShadow="0 0 0 3px rgba(95,37,159,.12)";'
        f'    cc.style.borderColor="var(--bd)";cc.style.background="#fff";cc.style.boxShadow="none";'
        f'    bc.style.display="none";'
        f'    document.getElementById("r-dev").checked=true;'
        f'  }}else{{'
        f'    cc.style.borderColor="#0ea5e9";cc.style.background="linear-gradient(135deg,#f0f9ff,#fff)";'
        f'    cc.style.boxShadow="0 0 0 3px rgba(14,165,233,.12)";'
        f'    cd.style.borderColor="var(--bd)";cd.style.background="#fff";cd.style.boxShadow="none";'
        f'    bc.style.display="block";'
        f'    document.getElementById("r-cam").checked=true;'
        f'  }}'
        f'}}'
        f'</script>'))

@app.route("/mis_devs")
def mis_devs():
    if not li(): return redirect("/")
    devs=db_query("SELECT * FROM devoluciones WHERE tienda_id=%s AND user=%s ORDER BY id DESC",(tid_now(),session.get("user")),fetchall=True) or []
    col={"Pendiente":"t-am","Aprobada":"t-gr","Rechazada":"t-rd"}
    filas="".join(f"<tr><td>#{d.get('codigo','')}</td><td>{str(d.get('motivo',''))[:40]}</td><td><span class='tag {col.get(d.get('estado',''),'t-gy')}'>{d.get('estado','')}</span></td><td>{d.get('fecha','')}</td></tr>" for d in devs)
    return base("🔄 Mis Devoluciones",(
        f'<div class="sec"><div class="sh"><h3>Mis Solicitudes de Devolución</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Pedido</th><th>Motivo</th><th>Estado</th><th>Fecha</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=4 class=tmuted>Sin solicitudes</td></tr>" if not filas else filas}</tbody></table></div></div></div>'))

# ================================================================
#  ADMIN — PEDIDOS, DEVOLUCIONES
# ================================================================
@app.route("/admin_devs",methods=["GET","POST"])
def admin_devs():
    if not is_ad(): return redirect("/")
    tid=tid_now(); msg=""

    if request.method=="POST":
        did=int(request.form.get("did",0)); ac=request.form.get("ac","")
        d=db_query("SELECT * FROM devoluciones WHERE id=%s AND tienda_id=%s",(did,tid),fetchone=True)
        if d:
            if ac=="ap":
                db_query("UPDATE devoluciones SET estado='Aprobada' WHERE id=%s",(did,),commit=True)
                db_query("INSERT INTO caja(tienda_id,tipo,monto,descripcion,fecha) VALUES(%s,'egreso',%s,%s,%s)",
                         (tid,d.get("subtotal",0),f"Devolución aprobada {d.get('codigo','')}",now()),commit=True)
            elif ac=="re":
                db_query("UPDATE devoluciones SET estado='Rechazada' WHERE id=%s",(did,),commit=True)

            msg='<div class="al a-s">✅ Estado actualizado.</div>'

    devs=db_query("SELECT * FROM devoluciones WHERE tienda_id=%s ORDER BY id DESC",(tid,),fetchall=True) or []
    col={"Pendiente":"t-am","Aprobada":"t-gr","Rechazada":"t-rd"}

    filas=""
    for d in devs:
        bts=""
        if d.get("estado")=="Pendiente":
            bts=(
                f"<form method='post' style='display:inline'>"
                f"<input type='hidden' name='did' value='{d['id']}'>"
                f"<input type='hidden' name='ac' value='ap'>"
                f"<button class='btn bs bsm'>Aprobar</button></form> "
                f"<form method='post' style='display:inline'>"
                f"<input type='hidden' name='did' value='{d['id']}'>"
                f"<input type='hidden' name='ac' value='re'>"
                f"<button class='btn bd bsm'>Rechazar</button></form>"
            )

        filas+=(
            f"<tr>"
            f"<td>#{d.get('codigo','')}</td>"
            f"<td>{d.get('user','')}</td>"

            f"<td>"
            f"<span class='tag {'t-pu' if d.get('tipo_solicitud')=='devolucion' else 't-sk'}'>"
            f"{'💸 Devolución' if d.get('tipo_solicitud','devolucion')=='devolucion' else '🔁 Cambio'}"
            f"</span><br>"
            f"<span style='font-size:.74rem;color:var(--mt)'>"
            f"{d.get('producto_cambio','')}"
            f"</span><br>"
            f"{str(d.get('motivo',''))[:30]}"
            f"</td>"

            f"<td>{fmt(d.get('subtotal',0))}</td>"
            f"<td><span class='tag {col.get(d.get('estado',''),'t-gy')}'>{d.get('estado','')}</span></td>"
            f"<td>{d.get('fecha','')}</td>"
            f"<td>{bts}</td>"
            f"</tr>"
        )

    return base("🔄 Gestión de Devoluciones",(msg+
        f'<div class="sec"><div class="sh"><h3>Solicitudes ({len(devs)})</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr>'
        f'<th>Pedido</th><th>Cliente</th><th>Tipo / Detalle</th><th>Monto</th><th>Estado</th><th>Fecha</th><th>Acciones</th>'
        f'</tr></thead>'
        f'<tbody>{"<tr><td colspan=7 class=tmuted>Sin devoluciones</td></tr>" if not filas else filas}</tbody>'
        f'</table></div></div></div>'
    ))
@app.route("/admin_pedidos")
def admin_pedidos():
    """Admin: solo VE pedidos y sus ingresos. No gestiona."""
    if not is_ad(): return redirect("/")
    tid=tid_now()
    f_est=request.args.get("est","")
    f_desde=request.args.get("desde","")
    f_hasta=request.args.get("hasta","")
    q="SELECT * FROM pedidos WHERE tienda_id=%s"; params=[tid]
    if f_est: q+=" AND estado=%s"; params.append(f_est)
    if f_desde: q+=" AND fecha>=%s"; params.append(f_desde)
    if f_hasta: q+=" AND fecha<=%s"; params.append(f_hasta+" 23:59")
    q+=" ORDER BY id DESC"
    peds=db_query(q,tuple(params),fetchall=True) or []

    total_ing=sum(float(p.get("subtotal",0)) for p in peds
                  if p.get("estado") not in ("Cancelado","Devolucion"))
    total_peds=len(peds)
    pend=sum(1 for p in peds if p.get("estado")=="Pendiente")

    col={"Pendiente":"t-am","Aprobado":"t-bl","En camino":"t-sk","Enviado":"t-cy",
         "Entregado":"t-gr","Cancelado":"t-rd","Devolucion":"t-pu"}
    estados_filtro=["","Pendiente","Aprobado","En camino","Enviado","Entregado","Cancelado","Devolucion"]
    filtros_html="".join(
        f'<a href="/admin_pedidos?est={e}" '
        f'class="btn {"bp" if f_est==e else "bg"} bsm" '
        f'style="padding:5px 11px;font-size:.72rem">'
        f'{"Todos" if not e else e}</a>'
        for e in estados_filtro)

    filas="".join(
        f"<tr>"
        f"<td><strong style='color:var(--pr)'>#{p.get('codigo','')}</strong><br>"
        f"<span style='font-size:.7rem;color:var(--mt)'>{str(p.get('fecha',''))[:16]}</span></td>"
        f"<td style='font-size:.8rem'>{str(p.get('producto',''))[:28]}</td>"
        f"<td>{p.get('user','')}</td>"
        f"<td><strong style='color:var(--sc)'>{fmt(p.get('subtotal',0))}</strong></td>"
        f"<td><span class='tag {'t-nq' if p.get('pago')=='Nequi' else 't-dv' if p.get('pago')=='Daviplata' else 't-gr'}'>"
        f"{p.get('pago','')}</span></td>"
        f"<td>{'🏍️' if p.get('entrega')=='domicilio' else '🏪'} "
        f"<span style='font-size:.75rem'>{'Dom.' if p.get('entrega')=='domicilio' else 'Tienda'}</span></td>"
        f"<td><span class='tag {col.get(p.get('estado',''),'t-gy')}'>{p.get('estado','')}</span></td>"
        f"<td><a href='/pdf_pedido/{p['id']}' class='btn bg bsm'>📄</a></td>"
        f"</tr>"
        for p in peds)

    return base("🧾 Registro de Pedidos",(
        f'<div class="al a-i" style="margin-bottom:18px">👁️ El administrador consulta pedidos e ingresos. '
        f'La <strong>gestión y envío</strong> la realiza el empleado desde '
        f'<a href="/emp_pedidos" class="btn bp bsm" style="margin-left:6px">🧾 Gestión de pedidos</a></div>'
        # Métricas
        f'<div class="kg" style="margin-bottom:18px">'
        f'<div class="kc k-bl"><div class="ki">🧾</div><div class="kl">Total pedidos</div>'
        f'<div class="kv">{total_peds}</div></div>'
        f'<div class="kc k-am"><div class="ki">⏳</div><div class="kl">Pendientes</div>'
        f'<div class="kv">{pend}</div></div>'
        f'<div class="kc k-gr"><div class="ki">💵</div><div class="kl">Ingresos registrados</div>'
        f'<div class="kv" style="font-size:1.05rem">{fmt(total_ing)}</div></div>'
        f'</div>'
        # Filtros
        f'<div class="sec" style="margin-bottom:16px">'
        f'<div class="sh"><h3>Filtros</h3>'
        f'<div style="display:flex;gap:8px">'
        f'<a href="/admin_pedidos_limpiar" class="btn bd bsm" '
        f'onclick="return confirm(\'Eliminar pedidos Entregados y Cancelados?\')">🗑️ Limpiar</a>'
        f'<a href="/pdf_pedidos_rango?desde={f_desde}&hasta={f_hasta}" '
        f'target="_blank" class="btn bg bsm">📄 PDF</a>'
        f'</div></div>'
        f'<div class="sb2">'
        f'<div class="fr" style="flex-wrap:wrap;gap:5px;margin-bottom:12px">{filtros_html}</div>'
        f'<form method="get" style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">'
        f'<div class="fg"><label>Desde</label><input type="date" name="desde" value="{f_desde}"></div>'
        f'<div class="fg"><label>Hasta</label><input type="date" name="hasta" value="{f_hasta}"></div>'
        f'<button class="btn bp bsm">Filtrar por fecha</button>'
        f'<a href="/admin_pedidos" class="btn bg bsm">✕ Limpiar</a>'
        f'</form>'
        f'</div></div>'
        # Tabla
        f'<div class="sec"><div class="sh"><h3>Pedidos ({len(peds)})</h3></div>'
        f'<div class="sb2"><div class="tw"><table>'
        f'<thead><tr><th>Código / Fecha</th><th>Producto</th><th>Cliente</th>'
        f'<th>Total</th><th>Pago</th><th>Entrega</th><th>Estado</th><th>PDF</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=8 class=tmuted style=text-align:center;padding:20px>Sin pedidos con estos filtros</td></tr>" if not filas else filas}'
        f'</tbody></table></div></div></div>'))


@app.route("/admin_pedidos_limpiar")
def admin_pedidos_limpiar():
    if not is_ad(): return redirect("/")
    db_query("DELETE FROM pedidos WHERE tienda_id=%s AND estado IN ('Cancelado','Entregado')",
             (tid_now(),),commit=True)
    return redirect("/admin_pedidos")


# ── PDF de pedidos por rango ──────────────────────────────────────

@app.route("/pdf_pedidos_rango")
def pdf_pedidos_rango():
    if not is_ad(): return redirect("/")
    tid=tid_now(); t=get_tienda()
    f_desde=request.args.get("desde",""); f_hasta=request.args.get("hasta",hoy())
    q="SELECT * FROM pedidos WHERE tienda_id=%s"; params=[tid]
    if f_desde: q+=" AND fecha>=%s"; params.append(f_desde)
    if f_hasta: q+=" AND fecha<=%s"; params.append(f_hasta+" 23:59")
    q+=" ORDER BY id DESC"
    peds=db_query(q,tuple(params),fetchall=True) or []
    total=sum(float(p.get("subtotal",0)) for p in peds if p.get("estado") not in ("Cancelado","Devolucion"))
    buf=io.BytesIO(); c=pdf_canvas.Canvas(buf,pagesize=letter); W,H=letter
    pc=t.get("color","#4f46e5").lstrip("#")
    r2,g2,b2=int(pc[0:2],16)/255,int(pc[2:4],16)/255,int(pc[4:6],16)/255
    c.setFillColorRGB(r2,g2,b2); c.rect(0,H-70,W,70,fill=True,stroke=False)
    c.setFillColor(pdf_colors.white); c.setFont("Helvetica-Bold",15)
    c.drawString(36,H-38,f"{t.get('nombre','')} — Reporte de Pedidos")
    c.setFont("Helvetica",8)
    c.drawString(36,H-54,f"Período: {f_desde or 'Inicio'} → {f_hasta}  |  Total ingresos: {fmt(total)}")
    y=H-95; c.setFillColor(pdf_colors.HexColor("#1e293b"))
    c.setFont("Helvetica-Bold",7)
    for lbl,x in [("Código",36),("Producto",110),("Cliente",220),("Total",300),("Pago",360),("Estado",420),("Fecha",485)]:
        c.drawString(x,y,lbl)
    y-=13; c.setFont("Helvetica",7)
    for p in peds:
        if y<50: c.showPage(); y=H-50
        c.drawString(36,y,str(p.get("codigo",""))[:10])
        c.drawString(110,y,str(p.get("producto",""))[:18])
        c.drawString(220,y,str(p.get("user",""))[:12])
        c.drawString(300,y,fmt(p.get("subtotal",0)))
        c.drawString(360,y,str(p.get("pago",""))[:8])
        c.drawString(420,y,str(p.get("estado",""))[:10])
        c.drawString(485,y,str(p.get("fecha",""))[:10])
        y-=12; c.setStrokeColor(pdf_colors.HexColor("#e2e8f4")); c.line(30,y+5,W-30,y+5)
    c.setFillColor(pdf_colors.HexColor("#64748b")); c.setFont("Helvetica",7)
    c.drawCentredString(W/2,30,f"GestorPro | {t.get('nombre','')} | {now()}")
    c.save(); buf.seek(0)
    return send_file(buf,as_attachment=True,
                     download_name=f"Pedidos_{t.get('id','gp')}_{f_desde}_{f_hasta}.pdf",
                     mimetype="application/pdf")

@app.route("/emp_pedidos",methods=["GET","POST"])
def emp_pedidos():
    """Empleado: aprueba, asigna domiciliario, marca entregado."""
    if not is_st(): return redirect("/")
    if is_ad(): return redirect("/admin_pedidos")
    tid=tid_now(); msg=""

    if request.method=="POST":
        ac=request.form.get("ac","")
        pid=int(request.form.get("pid",0))
        p=db_query("SELECT * FROM pedidos WHERE id=%s AND tienda_id=%s",(pid,tid),fetchone=True)
        if p:
            est_actual=p.get("estado","")
            cod=p.get("codigo","")
            if ac=="aprobar" and est_actual=="Pendiente":
                db_query("UPDATE pedidos SET estado='Aprobado' WHERE id=%s",(pid,),commit=True)
                db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                         (tid,f"✅ Pedido {cod} aprobado.",now()),commit=True)
                msg='<div class="al a-s">✅ Pedido aprobado correctamente.</div>'
            elif ac=="enviar" and est_actual=="Aprobado":
                dom_id=int(request.form.get("dom_id",0))
                db_query("UPDATE pedidos SET estado='En camino' WHERE id=%s",(pid,),commit=True)
                nom_dom=""
                if dom_id:
                    d=db_query("SELECT nombre FROM users WHERE id=%s AND tienda_id=%s",(dom_id,tid),fetchone=True)
                    nom_dom=d["nombre"] if d else ""
                db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                         (tid,f"🏍️ Pedido {cod} enviado a domicilio{' — '+nom_dom if nom_dom else ''}.",now()),commit=True)
                msg='<div class="al a-s">🏍️ Pedido enviado a domicilio.</div>'
            elif ac=="listo" and est_actual=="Aprobado":
                db_query("UPDATE pedidos SET estado='Enviado' WHERE id=%s",(pid,),commit=True)
                msg='<div class="al a-s">🏪 Pedido listo para recoger en tienda.</div>'
            elif ac=="entregar" and est_actual in ("En camino","Enviado","Aprobado"):
                db_query("UPDATE pedidos SET estado='Entregado' WHERE id=%s",(pid,),commit=True)
                db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                         (tid,f"✅ Pedido {cod} entregado.",now()),commit=True)
                msg='<div class="al a-s">✅ Pedido marcado como entregado.</div>'
            elif ac=="cancelar":
                db_query("UPDATE pedidos SET estado='Cancelado' WHERE id=%s",(pid,),commit=True)
                msg='<div class="al a-d">❌ Pedido cancelado.</div>'

    # Pedidos activos (no terminados)
    peds=db_query(
        "SELECT * FROM pedidos WHERE tienda_id=%s "
        "AND estado NOT IN ('Entregado','Cancelado','Devolucion') ORDER BY id DESC",
        (tid,),fetchall=True) or []
    # Historial reciente
    hist=db_query(
        "SELECT * FROM pedidos WHERE tienda_id=%s "
        "AND estado IN ('Entregado','Cancelado') ORDER BY id DESC LIMIT 15",
        (tid,),fetchall=True) or []
    domis=db_query("SELECT id,nombre FROM users WHERE tienda_id=%s AND rol='domiciliario'",(tid,),fetchall=True) or []
    dom_opts="".join(f"<option value='{d['id']}'>{d['nombre']}</option>" for d in domis)

    # Comprobantes pendientes
    cp=db_query("SELECT COUNT(*) as c FROM comprobantes WHERE tienda_id=%s AND revisado=0",(tid,),fetchone=True)
    n_cp=cp["c"] if cp else 0
    cp_alert=(f'<div class="al a-w" style="margin-bottom:14px">📎 <strong>{n_cp} comprobante(s)</strong> '
              f'sin revisar. <a href="/comprobantes_pedido" class="btn bnq bsm" style="margin-left:6px">'
              f'Ver comprobantes</a></div>') if n_cp else ""

    col={"Pendiente":"t-am","Aprobado":"t-bl","En camino":"t-sk","Enviado":"t-cy",
         "Entregado":"t-gr","Cancelado":"t-rd","Devolucion":"t-pu"}

    cards=""
    for p in peds:
        est=p.get("estado","")
        items_list=[]
        try: items_list=json.loads(p.get("items") or "[]")
        except: pass
        items_html="".join(
            f'<div style="font-size:.79rem;padding:3px 0;border-bottom:1px solid #f1f5f9">'
            f'• {it["nombre"]} ×{it["cantidad"]} = {fmt(it["subtotal"])}</div>'
            for it in items_list
        ) or f'<div style="font-size:.79rem">{p.get("producto","")}</div>'

        # Comprobante de este pedido
        comp=db_query("SELECT * FROM comprobantes WHERE pedido_id=%s AND tienda_id=%s",(p["id"],tid),fetchone=True)
        comp_html=""
        if comp:
            rev="✅ Revisado" if comp.get("revisado") else "⚠️ Sin revisar"
            comp_html=(f'<div style="background:#f0fdf4;border-radius:8px;padding:8px 11px;'
                       f'margin-bottom:8px;font-size:.78rem;display:flex;align-items:center;gap:8px">'
                       f'📎 Comprobante adjunto — <span style="font-weight:700">{rev}</span> '
                       f'<a href="/ver_comprobante/{comp["id"]}" target="_blank" '
                       f'class="btn bp bsm" style="padding:3px 9px;font-size:.68rem">Ver</a>'
                       f'</div>')

        # Botones de acción según estado
        acciones=""
        if est=="Pendiente":
            acciones=(
                f'<form method="post" style="display:inline">'
                f'<input type="hidden" name="ac" value="aprobar">'
                f'<input type="hidden" name="pid" value="{p["id"]}">'
                f'<button class="btn bs bsm">✅ Aprobar</button></form> '
                f'<form method="post" style="display:inline">'
                f'<input type="hidden" name="ac" value="cancelar">'
                f'<input type="hidden" name="pid" value="{p["id"]}">'
                f'<button class="btn bd bsm" onclick="return confirm(\'¿Cancelar pedido?\')">❌ Cancelar</button></form>')
        elif est=="Aprobado" and p.get("entrega")=="domicilio":
            acciones=(
                f'<form method="post" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
                f'<input type="hidden" name="ac" value="enviar">'
                f'<input type="hidden" name="pid" value="{p["id"]}">'
                f'<select name="dom_id" style="flex:1;min-width:140px;font-size:.78rem;padding:6px 9px">'
                f'<option value="0">— Sin asignar domiciliario —</option>{dom_opts}</select>'
                f'<button class="btn bdm bsm">🏍️ Enviar a domicilio</button></form>')
        elif est=="Aprobado" and p.get("entrega")!="domicilio":
            acciones=(
                f'<form method="post" style="display:inline">'
                f'<input type="hidden" name="ac" value="listo">'
                f'<input type="hidden" name="pid" value="{p["id"]}">'
                f'<button class="btn bw2 bsm">🏪 Listo para recoger</button></form>')
        elif est in ("En camino","Enviado"):
            acciones=(
                f'<form method="post" style="display:inline">'
                f'<input type="hidden" name="ac" value="entregar">'
                f'<input type="hidden" name="pid" value="{p["id"]}">'
                f'<button class="btn bs bsm">✅ Marcar Entregado</button></form>')

        cards+=(
            f'<div class="dc {"enc" if est in ("En camino","Enviado") else ""}" '
            f'style="border-color:{"#0ea5e9" if est in ("En camino","Enviado") else "var(--bd)"}">'
            # Header
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">'
            f'<div>'
            f'<div style="font-size:1rem;font-weight:900;color:var(--pr)">#{p.get("codigo","")}</div>'
            f'<div style="font-size:.71rem;color:var(--mt);margin-top:2px">'
            f'{p.get("fecha","")} · {p.get("pago","")} · '
            f'{"🏍️ Domicilio" if p.get("entrega")=="domicilio" else "🏪 Recogida"}'
            f'</div></div>'
            f'<span class="tag {col.get(est,"t-gy")}">{est}</span>'
            f'</div>'
            # Info cliente + total
            f'<div class="dg" style="margin-bottom:10px">'
            f'<div class="di"><div class="dl">Cliente</div>'
            f'<div class="dv">{p.get("user","")}</div></div>'
            f'<div class="di"><div class="dl">Total</div>'
            f'<div class="dv hl">{fmt(p.get("subtotal",0))}</div></div>'
            f'</div>'
            # Dirección (si aplica)
            + (f'<div style="background:#eff6ff;border-radius:8px;padding:8px 11px;'
               f'font-size:.79rem;margin-bottom:10px">📍 {p.get("direccion","")}</div>'
               if p.get("entrega")=="domicilio" and p.get("direccion") else "")
            # Items
            + f'<div style="background:#f8faff;border-radius:8px;padding:9px;margin-bottom:10px">{items_html}</div>'
            # Comprobante
            + comp_html
            # Botones
            + f'<div class="fr" style="flex-wrap:wrap;gap:7px">{acciones}'
            + f'<a href="/pdf_pedido/{p["id"]}" class="btn bg bsm">📄 PDF</a>'
            + f'</div></div>')

    hist_filas="".join(
        f"<tr><td><strong style='color:var(--pr)'>#{p.get('codigo','')}</strong></td>"
        f"<td>{p.get('user','')}</td>"
        f"<td>{fmt(p.get('subtotal',0))}</td>"
        f"<td><span class='tag {col.get(p.get('estado',''),'t-gy')}'>{p.get('estado','')}</span></td>"
        f"<td style='font-size:.77rem;color:var(--mt)'>{str(p.get('fecha',''))[:16]}</td>"
        f"<td><a href='/pdf_pedido/{p['id']}' class='btn bg bsm'>📄</a></td></tr>"
        for p in hist)

    return base("🧾 Gestión de Pedidos",(
        msg + cp_alert +
        (f'<div class="al a-s">✅ No hay pedidos activos ahora mismo.</div>'
         if not peds else
         f'<div class="al a-i" style="margin-bottom:16px">Tienes '
         f'<strong>{len(peds)}</strong> pedido(s) por gestionar.</div>') +
        (cards if cards else "") +
        f'<div class="sec" style="margin-top:20px">'
        f'<div class="sh"><h3>📋 Historial reciente (últimos 15)</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead>'
        f'<tr><th>Código</th><th>Cliente</th><th>Total</th><th>Estado</th><th>Fecha</th><th>PDF</th></tr>'
        f'</thead><tbody>'
        f'{"<tr><td colspan=6 class=tmuted style=text-align:center;padding:16px>Sin historial</td></tr>" if not hist_filas else hist_filas}'
        f'</tbody></table></div></div></div>'))


def _set_estado_pedido(pid,estado):
    """Auxiliar para cambiar estado de pedido."""
    if not is_st(): return redirect("/")
    db_query("UPDATE pedidos SET estado=%s WHERE id=%s AND tienda_id=%s",
             (estado,pid,tid_now()),commit=True)
    return redirect("/emp_pedidos" if is_em() else "/admin_pedidos")

@app.route("/ped_aprobar/<int:pid>")
def ped_aprobar(pid): return _set_estado_pedido(pid,"Aprobado")
@app.route("/ped_enviar/<int:pid>")
def ped_enviar(pid): return _set_estado_pedido(pid,"Enviado")
@app.route("/ped_entregar/<int:pid>")
def ped_entregar(pid): return _set_estado_pedido(pid,"Entregado")

# ================================================================
#  PROMOCIONES
# ================================================================
@app.route("/promociones",methods=["GET","POST"])
def promociones():
    if not is_ad(): return redirect("/")
    tid=tid_now(); msg=""
    if request.method=="POST":
        ac=request.form.get("ac","crear")
        if ac=="crear":
            pids_sel=",".join(request.form.getlist("pids"))
            db_query("INSERT INTO promociones(tienda_id,titulo,descripcion,descuento,desde,hasta,pids,activa,color,color2,fecha) VALUES(%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s)",
                     (tid,request.form.get("titulo","").strip(),request.form.get("desc","").strip(),
                      request.form.get("descuento","").strip(),request.form.get("desde",""),request.form.get("hasta",""),
                      pids_sel,request.form.get("color","#ef4444"),request.form.get("color2","#f97316"),now()),commit=True)
            msg='<div class="al a-s">✅ Promoción creada.</div>'
        elif ac=="toggle":
            pid2=int(request.form.get("pid2",0))
            pr=db_query("SELECT activa FROM promociones WHERE id=%s AND tienda_id=%s",(pid2,tid),fetchone=True)
            if pr: db_query("UPDATE promociones SET activa=%s WHERE id=%s",(0 if pr["activa"] else 1,pid2),commit=True)
        elif ac=="del":
            db_query("DELETE FROM promociones WHERE id=%s AND tienda_id=%s",(int(request.form.get("pid2",0)),tid),commit=True)
    prods=db_query("SELECT * FROM productos WHERE tienda_id=%s ORDER BY nombre",(tid,),fetchall=True) or []
    promos=db_query("SELECT * FROM promociones WHERE tienda_id=%s ORDER BY id DESC",(tid,),fetchall=True) or []
    opts="".join(f"<option value='{p['id']}'>{p['nombre']}</option>" for p in prods)
    filas=""
    for pr in promos:
        filas+=(f"<tr><td><strong>{pr['titulo']}</strong></td><td>{pr.get('descuento','')}</td>"
                f"<td>{pr.get('desde','')} al {pr.get('hasta','')}</td>"
                f"<td><span class='tag {'t-gr' if pr.get('activa') else 't-gy'}'>{'Activa' if pr.get('activa') else 'Inactiva'}</span></td>"
                f"<td class='fr'>"
                f"<form method='post' style='display:inline'><input type='hidden' name='ac' value='toggle'><input type='hidden' name='pid2' value='{pr['id']}'><button class='btn bw2 bsm'>{'Desact.' if pr.get('activa') else 'Activar'}</button></form>"
                f"<form method='post' style='display:inline'><input type='hidden' name='ac' value='del'><input type='hidden' name='pid2' value='{pr['id']}'><button class='btn bd bsm' onclick=\"return confirm('Eliminar?')\">Eliminar</button></form>"
                f"</td></tr>")
    return base("🎁 Gestionar Promociones",(msg+
        f'<div class="sec"><div class="sh"><h3>Nueva Promoción</h3></div><div class="sb2">'
        f'<form method="post"><input type="hidden" name="ac" value="crear"><div class="fg2">'
        f'<div class="fg"><label>Título *</label><input type="text" name="titulo" placeholder="Oferta del día" required></div>'
        f'<div class="fg"><label>Descuento</label><input type="text" name="descuento" placeholder="20% OFF"></div>'
        f'<div class="fg"><label>Desde</label><input type="date" name="desde"></div>'
        f'<div class="fg"><label>Hasta</label><input type="date" name="hasta"></div>'
        f'<div class="fg"><label>Color inicio</label><input type="color" name="color" value="#ef4444"></div>'
        f'<div class="fg"><label>Color fin</label><input type="color" name="color2" value="#f97316"></div>'
        f'<div class="fg c2"><label>Descripción</label><input type="text" name="desc" placeholder="Descripción de la promo"></div>'
        f'<div class="fg c2"><label>Productos incluidos (Ctrl+click)</label><select name="pids" multiple style="min-height:80px">{opts}</select></div>'
        f'</div><div class="mt16"><button class="btn bp">🎁 Crear Promoción</button></div></form></div></div>'
        f'<div class="sec"><div class="sh"><h3>Promociones Registradas</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Título</th><th>Descuento</th><th>Vigencia</th><th>Estado</th><th>Acciones</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=5 class=tmuted>Sin promociones</td></tr>" if not filas else filas}</tbody></table></div></div></div>'))

# ================================================================
#  PDF FACTURA
# ================================================================
@app.route("/pdf_pedido/<int:pid>")
def pdf_pedido(pid):
    if not li(): return redirect("/")
    tid=tid_now(); t=get_tienda()
    p=db_query("SELECT * FROM pedidos WHERE id=%s AND tienda_id=%s",(pid,tid),fetchone=True)
    if not p: return redirect("/mis_pedidos")
    items_list=[]
    try: items_list=json.loads(p.get("items") or "[]")
    except: pass
    buf=io.BytesIO(); c=pdf_canvas.Canvas(buf,pagesize=letter); W,H=letter
    pc=t.get("color","#4f46e5").lstrip("#"); r=int(pc[0:2],16)/255; g=int(pc[2:4],16)/255; b=int(pc[4:6],16)/255
    # Header
    c.setFillColorRGB(r,g,b); c.rect(0,H-80,W,80,fill=True,stroke=False)
    c.setFillColor(pdf_colors.white); c.setFont("Helvetica-Bold",18); c.drawString(40,H-44,t.get("nombre","GestorPro"))
    c.setFont("Helvetica",8); c.drawString(40,H-60,f"NIT: {t.get('nit','')} | {t.get('ciudad','')} | Tel: {t.get('telefono','')}")
    # Recibo
    c.setFillColor(pdf_colors.HexColor("#1e293b")); c.setFont("Helvetica-Bold",13); c.drawString(40,H-110,"RECIBO DE COMPRA")
    c.setFont("Helvetica",9)
    c.drawString(40,H-128,f"Código: {p.get('codigo','')}")
    c.drawString(40,H-144,f"Fecha: {p.get('fecha','')}")
    c.drawString(40,H-160,f"Cliente: {p.get('user','')}")
    c.drawString(40,H-176,f"Pago: {p.get('pago','')}  |  Entrega: {p.get('entrega','')}")
    if p.get("direccion"): c.drawString(40,H-192,f"Dirección: {p.get('direccion','')}")
    # Items
    ty=H-232; c.setFillColorRGB(r,g,b); c.setFont("Helvetica-Bold",8)
    c.drawString(40,ty+6,"Producto"); c.drawString(300,ty+6,"Cant"); c.drawString(370,ty+6,"Precio"); c.drawRightString(W-40,ty+6,"Subtotal")
    c.setFillColor(pdf_colors.HexColor("#1e293b")); c.setFont("Helvetica",8); ry=ty-20
    if not items_list:
        items_list=[{"nombre":p.get("producto",""),"cantidad":p.get("cantidad",1),"precio":float(p.get("precio",0)),"subtotal":float(p.get("subtotal",0))}]
    for it in items_list:
        c.drawString(40,ry,str(it.get("nombre",""))[:40]); c.drawString(300,ry,str(it.get("cantidad","")))
        c.drawString(370,ry,"$ "+"{:,}".format(int(float(it.get("precio",0)))).replace(",","."))
        c.drawRightString(W-40,ry,"$ "+"{:,}".format(int(float(it.get("subtotal",0)))).replace(",",".")); ry-=18
        c.setStrokeColor(pdf_colors.HexColor("#e2e8f4")); c.line(32,ry+9,W-32,ry+9)
    ry-=10; c.setFillColor(pdf_colors.HexColor("#15803d")); c.setFont("Helvetica-Bold",11)
    c.drawRightString(W-40,ry+4,"TOTAL: $ "+"{:,}".format(int(float(p.get("subtotal",0)))).replace(",","."))
    # Footer
    c.setFillColor(pdf_colors.HexColor("#64748b")); c.setFont("Helvetica",7)
    c.drawCentredString(W/2,48,f"GestorPro | {t.get('nombre','')} | {t.get('ciudad','')} | {now()} | ¡Gracias por su compra!")
    if t.get("whatsapp"): c.drawCentredString(W/2,36,f"WhatsApp: +{t['whatsapp']}")
    c.save(); buf.seek(0)
    return send_file(buf,as_attachment=True,download_name=f"Recibo_{p.get('codigo','GP')}.pdf",mimetype="application/pdf")

# ================================================================
#  EXPORTAR PDF POR MÓDULO Y RANGO DE FECHAS
# ================================================================
@app.route("/exportar_pdf/<modulo>",methods=["GET","POST"])
def exportar_pdf(modulo):
    if not is_st(): return redirect("/")
    tid=tid_now(); t=get_tienda()
    fecha_ini=request.form.get("fecha_ini","") or request.args.get("fi","")
    fecha_fin=request.form.get("fecha_fin","") or request.args.get("ff","")
    if request.method=="GET":
        return base(f"📄 Exportar PDF — {modulo.capitalize()}",(
            f'<div class="sec" style="max-width:480px;margin:auto"><div class="sh"><h3>📄 Exportar {modulo.capitalize()} en PDF</h3></div>'
            f'<div class="sb2">'
            f'<form method="post" style="display:flex;flex-direction:column;gap:12px">'
            f'<div class="fg"><label>Fecha inicio</label><input type="date" name="fecha_ini" value="{hoy()}"></div>'
            f'<div class="fg"><label>Fecha fin</label><input type="date" name="fecha_fin" value="{hoy()}"></div>'
            f'<button class="btn bp blg">📄 Generar PDF</button></form></div></div>'))
    # Generar PDF
    buf=io.BytesIO(); c=pdf_canvas.Canvas(buf,pagesize=A4); W,H=A4
    pc=t.get("color","#4f46e5").lstrip("#"); r=int(pc[0:2],16)/255; g=int(pc[2:4],16)/255; b=int(pc[4:6],16)/255
    c.setFillColorRGB(r,g,b); c.rect(0,H-60,W,60,fill=True,stroke=False)
    c.setFillColor(pdf_colors.white); c.setFont("Helvetica-Bold",16); c.drawString(30,H-36,f"{t.get('nombre','')} — Reporte {modulo.capitalize()}")
    c.setFont("Helvetica",8); c.drawString(30,H-52,f"Período: {fecha_ini} al {fecha_fin}  |  Generado: {now()}")
    c.setFillColor(pdf_colors.HexColor("#1e293b")); y=H-90
    def draw_row(items,bold=False):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica",7)
        x=30
        for item,w in items:
            c.drawString(x,y,str(item)[:int(w/6)])
            x+=w
        y-=14
        if bold:
            c.setStrokeColor(pdf_colors.HexColor("#4f46e5")); c.line(30,y+10,W-30,y+10)
        c.setStrokeColor(pdf_colors.HexColor("#e2e8f4")); c.line(30,y+9,W-30,y+9)
        if y<60: c.showPage(); y=H-60; c.setFillColor(pdf_colors.HexColor("#1e293b"))
    if modulo=="pedidos":
        draw_row([("Código",60),("Producto",120),("Cliente",80),("Total",70),("Pago",60),("Estado",80)],True)
        rows=db_query("SELECT * FROM pedidos WHERE tienda_id=%s AND fecha>=%s AND fecha<=%s ORDER BY id DESC",(tid,fecha_ini+" 00:00",fecha_fin+" 23:59"),fetchall=True) or []
        for p in rows: draw_row([(p.get("codigo",""),60),(str(p.get("producto",""))[:18],120),(p.get("user",""),80),(fmt(p.get("subtotal",0)),70),(p.get("pago",""),60),(p.get("estado",""),80)])
        total=sum(float(p.get("subtotal",0)) for p in rows if p.get("estado") not in ("Cancelado","Devolucion"))
        y-=10; c.setFont("Helvetica-Bold",9); c.drawString(30,y,f"Total ingresos período: {fmt(total)}")
    elif modulo=="inventario":
        draw_row([("Nombre",140),("Categoría",80),("Precio",60),("Stock",50),("Min",40),("Estado",70)],True)
        prods=db_query("SELECT * FROM productos WHERE tienda_id=%s ORDER BY nombre",(tid,),fetchall=True) or []
        for p in prods: draw_row([(p["nombre"],140),(p.get("categoria",""),80),(fmt(p["precio"]),60),(f'{p["cantidad"]} {p.get("unidad","")}',50),(str(p.get("stock_min",5)),40),("BAJO" if p["cantidad"]<=p.get("stock_min",5) else "OK",70)])
    elif modulo=="caja":
        draw_row([("Tipo",60),("Monto",80),("Descripción",200),("Fecha",100)],True)
        movs=db_query("SELECT * FROM caja WHERE tienda_id=%s AND fecha>=%s AND fecha<=%s ORDER BY id DESC",(tid,fecha_ini+" 00:00",fecha_fin+" 23:59"),fetchall=True) or []
        for m in movs: draw_row([(m["tipo"].upper(),60),(fmt(m["monto"]),80),(str(m.get("descripcion",""))[:32],200),(m.get("fecha",""),100)])
        ing=sum(float(m["monto"]) for m in movs if m["tipo"]=="ingreso")
        egr=sum(float(m["monto"]) for m in movs if m["tipo"]=="egreso")
        y-=10; c.setFont("Helvetica-Bold",9)
        c.drawString(30,y,f"Ingresos: {fmt(ing)}  |  Egresos: {fmt(egr)}  |  Neto: {fmt(ing-egr)}")
    elif modulo=="movimientos":
        draw_row([("Producto",120),("Tipo",60),("Cantidad",60),("Motivo",150),("Fecha",80)],True)
        movs=db_query("SELECT * FROM movimientos WHERE tienda_id=%s AND fecha>=%s AND fecha<=%s ORDER BY id DESC",(tid,fecha_ini+" 00:00",fecha_fin+" 23:59"),fetchall=True) or []
        for m in movs: draw_row([(m.get("nombre",""),120),(m.get("tipo",""),60),(str(m.get("cant","")),60),(str(m.get("motivo",""))[:24],150),(m.get("fecha",""),80)])
    c.setFillColor(pdf_colors.HexColor("#64748b")); c.setFont("Helvetica",7)
    c.drawCentredString(W/2,30,f"GestorPro &middot; {t.get('nombre','')} &middot; Reporte generado: {now()}")
    c.save(); buf.seek(0)
    return send_file(buf,as_attachment=True,download_name=f"reporte_{modulo}_{fecha_ini}_{fecha_fin}.pdf",mimetype="application/pdf")

# ================================================================
#  POS
# ================================================================
@app.route("/pos",methods=["GET","POST"])
def pos():
    if not is_st(): return redirect("/")
    tid=tid_now(); msg=""
    if request.method=="POST":
        pid=int(request.form.get("pid",0)); cant=int(request.form.get("cant",1)); met=request.form.get("pago","Efectivo")
        p=db_query("SELECT * FROM productos WHERE id=%s AND tienda_id=%s",(pid,tid),fetchone=True)
        if not p: msg='<div class="al a-d">Producto no encontrado.</div>'
        elif p["cantidad"]<cant: msg=f'<div class="al a-d">Stock insuficiente. Solo hay {p["cantidad"]} {p.get("unidad","uds")}.</div>'
        else:
            sub=float(p["precio"])*cant; cod="POS"+str(random.randint(10000,99999))
            db_query("UPDATE productos SET cantidad=%s WHERE id=%s",(p["cantidad"]-cant,pid),commit=True)
            db_query("INSERT INTO pedidos(tienda_id,codigo,user,producto,cantidad,precio,subtotal,pago,entrega,estado,fecha) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'recogida','Entregado',%s)",
                     (tid,cod,session.get("user","emp"),p["nombre"],cant,float(p["precio"]),sub,met,now()),commit=True)
            db_query("INSERT INTO caja(tienda_id,tipo,monto,descripcion,fecha) VALUES(%s,'ingreso',%s,%s,%s)",
                     (tid,sub,f"POS: {p['nombre']} x{cant}",now()),commit=True)
            if p["cantidad"]-cant<=p.get("stock_min",5):
                db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                         (tid,f"⚠️ Stock bajo: {p['nombre']} — {p['cantidad']-cant} uds.",now()),commit=True)
            msg=f'<div class="al a-s">✅ Venta {cod}: {p["nombre"]} x{cant} = {fmt(sub)}</div>'
    prods=db_query("SELECT * FROM productos WHERE tienda_id=%s AND cantidad>0 ORDER BY nombre",(tid,),fetchall=True) or []
    opts="".join(f"<option value='{p['id']}'>{p['nombre']} — {fmt(p['precio'])} (stock: {p['cantidad']})</option>" for p in prods)
    return base("🧾 Punto de Venta",(
        f'<div class="sec" style="max-width:480px;margin:auto"><div class="sh"><h3>Registrar Venta Rápida</h3></div><div class="sb2">{msg}'
        f'<form method="post" style="display:flex;flex-direction:column;gap:13px">'
        f'<div class="fg"><label>Producto</label><select name="pid">{"<option>Sin stock disponible</option>" if not opts else opts}</select></div>'
        f'<div class="fg"><label>Cantidad</label><input type="number" name="cant" min="1" value="1" required></div>'
        f'<div class="fg"><label>Método de Pago</label>'
        f'<select name="pago"><option value="Nequi">📱 Nequi</option><option value="Daviplata">💳 Daviplata</option><option value="Efectivo">💵 Efectivo</option></select></div>'
        f'<button class="btn bs blg">✅ Registrar Venta</button></form></div></div>'))

# ================================================================
#  PROVEEDORES — ADMIN
# ================================================================
@app.route("/proveedores",methods=["GET","POST"])
def proveedores():
    if not is_ad(): return redirect("/")
    tid=tid_now(); msg=""
    if request.method=="POST":
        ac=request.form.get("ac","crear")
        if ac=="crear":
            db_query("INSERT INTO proveedores(tienda_id,nombre,contacto,telefono_prov,producto,cantidad,precio_unit,condicion,estado,fecha) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'Solicitado',%s)",
                     (tid,request.form.get("nombre","").strip(),request.form.get("contacto","").strip(),
                      request.form.get("tel_prov","").strip(),request.form.get("producto","").strip(),
                      request.form.get("cantidad","0"),float(request.form.get("precio_unit","0") or 0),
                      request.form.get("condicion","").strip(),now()),commit=True)
            db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                     (tid,f"🚚 Nueva orden proveedor: {request.form.get('nombre','')}",now()),commit=True)
            msg='<div class="al a-s">✅ Solicitud enviada.</div>'
        elif ac=="recv":
            db_query("UPDATE proveedores SET estado='Recibido' WHERE id=%s AND tienda_id=%s",(int(request.form.get("pid2",0)),tid),commit=True)
        elif ac=="del":
            db_query("DELETE FROM proveedores WHERE id=%s AND tienda_id=%s",(int(request.form.get("pid2",0)),tid),commit=True)
    provs=db_query("SELECT * FROM proveedores WHERE tienda_id=%s ORDER BY id DESC",(tid,),fetchall=True) or []
    filas=""
    for p in provs:
        rec=p.get("estado")=="Recibido"
        bts=(f"<form method='post' style='display:inline'><input type='hidden' name='ac' value='recv'><input type='hidden' name='pid2' value='{p['id']}'><button class='btn bs bsm'>✅ Recibido</button></form>"
             if not rec else "")
        bts+=(f"<form method='post' style='display:inline'><input type='hidden' name='ac' value='del'><input type='hidden' name='pid2' value='{p['id']}'><button class='btn bd bsm' onclick=\"return confirm('Eliminar?')\">🗑️</button></form>")
        filas+=f"<tr><td><strong>{p.get('nombre','')}</strong></td><td>{p.get('contacto','')}</td><td>{p.get('telefono_prov','')}</td><td>{p.get('producto','')}</td><td>{p.get('cantidad','')}</td><td>{fmt(p.get('precio_unit',0))}</td><td>{p.get('condicion','')}</td><td>{p.get('fecha','')}</td><td><span class='tag {'t-gr' if rec else 't-am'}'>{p.get('estado','')}</span></td><td class='fr'>{bts}</td></tr>"
    return base("🚚 Proveedores",(msg+
        f'<div class="sec"><div class="sh"><h3>Nueva Solicitud a Proveedor</h3></div><div class="sb2">'
        f'<form method="post"><input type="hidden" name="ac" value="crear"><div class="fg2">'
        f'<div class="fg"><label>Proveedor *</label><input type="text" name="nombre" required></div>'
        f'<div class="fg"><label>Contacto</label><input type="text" name="contacto"></div>'
        f'<div class="fg"><label>Teléfono Proveedor</label><input type="tel" name="tel_prov"></div>'
        f'<div class="fg"><label>Producto *</label><input type="text" name="producto" required></div>'
        f'<div class="fg"><label>Cantidad *</label><input type="number" name="cantidad" required></div>'
        f'<div class="fg"><label>Precio unitario</label><input type="number" name="precio_unit" min="0" step="0.01"></div>'
        f'<div class="fg"><label>Condición de pago</label><input type="text" name="condicion" placeholder="Pago a 30 días"></div>'
        f'</div><div class="mt16"><button class="btn bp">📤 Enviar Solicitud</button></div></form></div></div>'
        f'<div class="sec"><div class="sh"><h3>Historial ({len(provs)})</h3><a href="/exportar_pdf/proveedores" class="btn bg bsm">📄 PDF</a></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Proveedor</th><th>Contacto</th><th>Tel.</th><th>Producto</th><th>Cant.</th><th>P.Unit</th><th>Condición</th><th>Fecha</th><th>Estado</th><th>Acción</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=10 class=tmuted>Sin solicitudes</td></tr>" if not filas else filas}</tbody></table></div></div></div>'))

# ================================================================
#  PROVEEDORES — EMPLEADO (vista reducida + crear)
# ================================================================
@app.route("/prov_emp",methods=["GET","POST"])
def prov_emp():
    if not is_st(): return redirect("/")
    tid=tid_now(); msg=""
    if request.method=="POST":
        db_query("INSERT INTO proveedores(tienda_id,nombre,contacto,telefono_prov,producto,cantidad,condicion,estado,fecha) VALUES(%s,%s,%s,%s,%s,%s,%s,'Solicitado',%s)",
                 (tid,request.form.get("nombre","").strip(),request.form.get("contacto","").strip(),
                  request.form.get("tel_prov","").strip(),request.form.get("producto","").strip(),
                  request.form.get("cantidad","0"),request.form.get("condicion","").strip(),now()),commit=True)
        db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                 (tid,f"🚚 Empleado solicitó proveedor: {request.form.get('nombre','')}",now()),commit=True)
        msg='<div class="al a-s">✅ Solicitud enviada al administrador.</div>'
    provs=db_query("SELECT * FROM proveedores WHERE tienda_id=%s ORDER BY id DESC LIMIT 10",(tid,),fetchall=True) or []
    filas="".join(f"<tr><td><strong>{p.get('nombre','')}</strong></td><td>{p.get('producto','')}</td><td>{p.get('cantidad','')}</td><td><span class='tag {'t-gr' if p.get('estado')=='Recibido' else 't-am'}'>{p.get('estado','')}</span></td><td>{p.get('fecha','')}</td></tr>" for p in provs)
    return base("🚚 Proveedores — Empleado",(msg+
        f'<div class="sec"><div class="sh"><h3>Solicitar Proveedor</h3></div><div class="sb2">'
        f'<form method="post" style="display:flex;flex-direction:column;gap:11px">'
        f'<div class="fg"><label>Proveedor *</label><input type="text" name="nombre" required></div>'
        f'<div class="fg"><label>Contacto</label><input type="text" name="contacto"></div>'
        f'<div class="fg"><label>Teléfono</label><input type="tel" name="tel_prov"></div>'
        f'<div class="fg"><label>Producto *</label><input type="text" name="producto" required></div>'
        f'<div class="fg"><label>Cantidad *</label><input type="number" name="cantidad" required></div>'
        f'<div class="fg"><label>Condición</label><input type="text" name="condicion"></div>'
        f'<button class="btn bp">📤 Enviar</button></form></div></div>'
        f'<div class="sec"><div class="sh"><h3>Últimas solicitudes</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Proveedor</th><th>Producto</th><th>Cant.</th><th>Estado</th><th>Fecha</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=5 class=tmuted>Sin solicitudes</td></tr>" if not filas else filas}</tbody></table></div></div></div>'))

# ================================================================
#  ROL PROVEEDOR
# ================================================================
@app.route("/prov")
def prov():
    if not is_pv(): return redirect("/")
    t=get_tienda()
    return base(f'🚚 Panel Proveedor — {t.get("nombre","")}',(
        '<div class="al a-k">Como proveedor puedes ver el inventario de la tienda y el estado de las solicitudes.</div>'
        '<div class="sec"><div class="sh"><h3>⚡ Accesos Rápidos</h3></div>'
        '<div class="sb2" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:11px">'
        '<a href="/prov_catalogo" class="btn bp blg">📦 Catálogo de la Tienda</a>'
        '<a href="/prov_pedidos" class="btn bg blg">📋 Mis Solicitudes</a>'
        '<a href="/perfil" class="btn bg blg">👤 Mi Perfil</a>'
        '</div></div>'))

@app.route("/prov_catalogo")
def prov_catalogo():
    if not is_pv(): return redirect("/")
    prods=db_query("SELECT * FROM productos WHERE tienda_id=%s ORDER BY nombre",(tid_now(),),fetchall=True) or []
    filas="".join(f"<tr><td><strong>{p['nombre']}</strong></td><td>{p.get('categoria','')}</td><td>{p['cantidad']} {p.get('unidad','')}</td><td>{p.get('stock_min',5)}</td><td><span class='tag {'t-rd' if p['cantidad']<=p.get('stock_min',5) else 't-gr'}'>{'Necesita reposición' if p['cantidad']<=p.get('stock_min',5) else 'Stock OK'}</span></td></tr>" for p in prods)
    return base("📦 Catálogo de la Tienda",(
        '<div class="al a-i">Los productos con stock bajo pueden requerir tu suministro urgente.</div>'
        f'<div class="sec"><div class="sh"><h3>Inventario ({len(prods)} productos)</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Nombre</th><th>Categoría</th><th>Stock Actual</th><th>Stock Mín</th><th>Estado</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=5 class=tmuted>Sin productos</td></tr>" if not filas else filas}</tbody></table></div></div></div>'))

@app.route("/prov_pedidos")
def prov_pedidos():
    if not is_pv(): return redirect("/")
    u=get_su(); nom=str(u.get("nombre","")) if u else ""; usr=str(session.get("user",""))
    provs=db_query("SELECT * FROM proveedores WHERE tienda_id=%s AND (nombre LIKE %s OR contacto LIKE %s) ORDER BY id DESC",
                   (tid_now(),f"%{nom}%",f"%{usr}%"),fetchall=True) or []
    filas="".join(f"<tr><td><strong>{p.get('producto','')}</strong></td><td>{p.get('cantidad','')}</td><td>{p.get('condicion','')}</td><td><span class='tag {'t-gr' if p.get('estado')=='Recibido' else 't-am'}'>{p.get('estado','')}</span></td><td>{p.get('fecha','')}</td></tr>" for p in provs)
    return base("📋 Mis Solicitudes",(
        f'<div class="sec"><div class="sh"><h3>Pedidos Relacionados</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Producto</th><th>Cantidad</th><th>Condición</th><th>Estado</th><th>Fecha</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=5 class=tmuted>No hay pedidos relacionados contigo aún.</td></tr>" if not filas else filas}</tbody></table></div></div></div>'))

# ================================================================
#  DOMICILIARIO
# ================================================================
@app.route("/domi")
def domi():
    if not is_dm(): return redirect("/")
    tid=tid_now()
    act=db_query("SELECT COUNT(*) as c FROM pedidos WHERE tienda_id=%s AND entrega='domicilio' AND estado NOT IN ('Entregado','Cancelado','Devolucion')",(tid,),fetchone=True)["c"]
    eh=db_query("SELECT COUNT(*) as c FROM pedidos WHERE tienda_id=%s AND entrega='domicilio' AND estado='Entregado' AND fecha LIKE %s",(tid,hoy()+"%"),fetchone=True)["c"]
    toh=db_query("SELECT COALESCE(SUM(subtotal),0) as s FROM pedidos WHERE tienda_id=%s AND entrega='domicilio' AND estado='Entregado' AND fecha LIKE %s",(tid,hoy()+"%"),fetchone=True)["s"]
    return base("🏍️ Panel Domiciliario",(
        f'<div class="kg">'
        f'<div class="kc k-bl"><div class="ki">📋</div><div class="kl">Pedidos Activos</div><div class="kv">{act}</div></div>'
        f'<div class="kc k-gr"><div class="ki">✅</div><div class="kl">Entregados Hoy</div><div class="kv">{eh}</div></div>'
        f'<div class="kc k-am"><div class="ki">💰</div><div class="kl">Recaudado Hoy</div><div class="kv" style="font-size:1.1rem">{fmt(toh)}</div></div>'
        f'</div>'
        f'<div class="sec"><div class="sh"><h3>⚡ Accesos Rápidos</h3></div>'
        f'<div class="sb2" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:11px">'
        f'<a href="/domi_pedidos" class="btn bdm blg">📋 Ver Pedidos Activos</a>'
        f'<a href="/domi_hist" class="btn bg blg">✅ Historial</a>'
        f'<a href="/perfil" class="btn bg blg">👤 Mi Perfil</a>'
        f'</div></div>'))

@app.route("/domi_pedidos")
def domi_pedidos():
    if not is_dm(): return redirect("/")
    tid=tid_now()
    peds=db_query("SELECT * FROM pedidos WHERE tienda_id=%s AND entrega='domicilio' AND estado NOT IN ('Entregado','Cancelado','Devolucion') ORDER BY id DESC",(tid,),fetchall=True) or []
    if not peds:
        return base("📋 Pedidos a Domicilio",(
            '<div class="al a-s">✅ No hay pedidos activos a domicilio. ¡Excelente!</div>'
            '<a href="/domi_hist" class="btn bg">Ver historial</a>'))
    t=get_tienda(); cards=""
    for p in peds:
        cli=db_query("SELECT * FROM users WHERE user=%s AND tienda_id=%s",(p.get("user",""),tid),fetchone=True)
        cn=str(cli.get("nombre",p.get("user",""))) if cli else str(p.get("user",""))
        ct=str(cli.get("telefono","Sin teléfono")) if cli else "Sin teléfono"
        wa_c=""
        if ct and ct!="Sin teléfono":
            wn=("57"+ct) if not ct.startswith("57") else ct; wn=wn.replace("+","").replace(" ","")
            wm=f"Hola {cn}! Soy el domiciliario de {t.get('nombre','')}. Voy en camino con tu pedido {p.get('codigo','')}".replace(" ","%20")
            wa_c=f"<a href='https://wa.me/{wn}?text={wm}' target='_blank' class='btn bwa bsm'>{WA_SVG} WhatsApp</a>"
        items_list=[]
        try: items_list=json.loads(p.get("items") or "[]")
        except: pass
        ph="".join(f'<div style="font-size:.8rem;border-bottom:1px solid var(--bd);padding:2px 0">• {it["nombre"]} x{it["cantidad"]} = {fmt(it["subtotal"])}</div>' for it in items_list) or f'<div style="font-size:.8rem">{str(p.get("producto",""))}</div>'
        col={"Pendiente":"t-am","Aprobado":"t-bl","En camino":"t-sk"}
        est=f"<span class='tag {col.get(p.get('estado',''),'t-gy')}'>{str(p.get('estado',''))}</span>"
        cls="dc enc" if p.get("estado")=="En camino" else "dc"
        cards+=(f'<div class="{cls}">'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px">'
                f'<div><div style="font-size:1.05rem;font-weight:900">#{p.get("codigo","")}</div>'
                f'<div style="font-size:.72rem;color:var(--mt)">{p.get("fecha","")} &middot; {p.get("pago","")}</div></div>'
                f'{est}</div>'
                f'<div class="dg">'
                f'<div class="di"><div class="dl">Cliente</div><div class="dv">{cn}</div></div>'
                f'<div class="di"><div class="dl">Teléfono</div><div class="dv hl">{ct}</div></div>'
                f'<div class="di" style="grid-column:span 2"><div class="dl">Dirección de entrega</div>'
                f'<div class="dv hl">{str(p.get("direccion")) if p.get("direccion") else "<em style=color:var(--mt)>Sin dirección especificada</em>"}</div></div>'
                f'</div>'
                f'<div style="background:#f8faff;border-radius:9px;padding:10px;margin-bottom:12px">{ph}</div>'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">'
                f'<span style="font-size:.8rem;color:var(--mt)">Pago: <strong>{p.get("pago","")}</strong></span>'
                f'<span style="font-size:1.05rem;font-weight:900;color:var(--sc)">Total: {fmt(p.get("subtotal",0))}</span></div>'
                f'<div class="fr">'
                f"<a href='/domi_cam/{p['id']}' class='btn bdm bsm'>🏍️ En camino</a>"
                f"<a href='/domi_ent/{p['id']}' class='btn bs bsm'>✅ Entregado</a>"
                f'{wa_c}</div></div>')
    return base(f'📋 Pedidos a Domicilio ({len(peds)} activos)',cards)

@app.route("/domi_cam/<int:pid>")
def domi_cam(pid):
    if not is_dm(): return redirect("/")
    tid=tid_now()
    p=db_query("SELECT codigo FROM pedidos WHERE id=%s AND tienda_id=%s",(pid,tid),fetchone=True)
    db_query("UPDATE pedidos SET estado='En camino' WHERE id=%s AND tienda_id=%s",(pid,tid),commit=True)
    if p: db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",(tid,f"🏍️ Pedido {p['codigo']} va en camino.",now()),commit=True)
    return redirect("/domi_pedidos")

@app.route("/domi_ent/<int:pid>")
def domi_ent(pid):
    if not is_dm(): return redirect("/")
    tid=tid_now()
    p=db_query("SELECT codigo FROM pedidos WHERE id=%s AND tienda_id=%s",(pid,tid),fetchone=True)
    db_query("UPDATE pedidos SET estado='Entregado' WHERE id=%s AND tienda_id=%s",(pid,tid),commit=True)
    if p: db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",(tid,f"✅ Pedido {p['codigo']} entregado.",now()),commit=True)
    return redirect("/domi_pedidos")

@app.route("/domi_hist")
def domi_hist():
    if not is_dm(): return redirect("/")
    tid=tid_now()
    peds=db_query("SELECT p.*,u.nombre as cli_nombre,u.telefono as cli_tel FROM pedidos p LEFT JOIN users u ON p.user=u.user AND p.tienda_id=u.tienda_id WHERE p.tienda_id=%s AND p.entrega='domicilio' AND p.estado='Entregado' ORDER BY p.id DESC LIMIT 30",(tid,),fetchall=True) or []
    filas="".join(f"<tr><td>#{p.get('codigo','')}</td><td>{str(p.get('cli_nombre') or p.get('user',''))}</td><td>{str(p.get('cli_tel','-') or '-')}</td><td>{str(p.get('direccion') or '-')}</td><td>{fmt(p.get('subtotal',0))}</td><td>{p.get('fecha','')}</td></tr>" for p in peds)
    return base("✅ Historial de Entregas",(
        f'<div class="sec"><div class="sh"><h3>Pedidos Entregados ({len(peds)})</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Código</th><th>Cliente</th><th>Teléfono</th><th>Dirección</th><th>Total</th><th>Fecha</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=6 class=tmuted>Sin entregas</td></tr>" if not filas else filas}</tbody></table></div></div></div>'))

# ================================================================
#  DOMICILIARIOS — ADMIN CRUD COMPLETO (método crudo)
# ================================================================
@app.route("/domiciliarios",methods=["GET","POST"])
def domiciliarios():
    if not is_ad(): return redirect("/")
    tid=tid_now(); msg=""
    if request.method=="POST":
        ac=request.form.get("ac","crear")
        if ac=="crear":
            u=request.form.get("user","").strip(); p=request.form.get("pass","")
            nom=request.form.get("nombre","").strip(); tel=request.form.get("telefono","").strip(); ema=request.form.get("email","").strip()
            ok,mp=ok_pass(p)
            ex=db_query("SELECT id FROM users WHERE user=%s AND tienda_id=%s",(u,tid),fetchone=True)
            if ex: msg='<div class="al a-d">Usuario ya existe.</div>'
            elif not ok: msg=f'<div class="al a-d">{mp}</div>'
            else:
                db_query("INSERT INTO users(tienda_id,user,nombre,password,rol,email,telefono,tratamiento_datos) VALUES(%s,%s,%s,%s,'domiciliario',%s,%s,1)",
                         (tid,u,nom,generate_password_hash(p),ema,tel),commit=True)
                msg=f'<div class="al a-s">✅ Domiciliario <strong>{u}</strong> creado.</div>'
        elif ac=="editar":
            uid=int(request.form.get("uid",0)); npa=request.form.get("pass","")
            if npa:
                ok,mp=ok_pass(npa)
                if ok: db_query("UPDATE users SET nombre=%s,telefono=%s,email=%s,password=%s WHERE id=%s AND tienda_id=%s",
                                (request.form.get("nombre","").strip(),request.form.get("tel","").strip(),request.form.get("email","").strip(),generate_password_hash(npa),uid,tid),commit=True)
                else: msg=f'<div class="al a-d">{mp}</div>'
            else: db_query("UPDATE users SET nombre=%s,telefono=%s,email=%s WHERE id=%s AND tienda_id=%s",
                           (request.form.get("nombre","").strip(),request.form.get("tel","").strip(),request.form.get("email","").strip(),uid,tid),commit=True)
            if not msg: msg='<div class="al a-s">✅ Domiciliario actualizado.</div>'
        elif ac=="del":
            db_query("DELETE FROM users WHERE id=%s AND tienda_id=%s AND rol='domiciliario'",(int(request.form.get("uid",0)),tid),commit=True)
            msg='<div class="al a-s">✅ Domiciliario eliminado.</div>'
    doms=db_query("SELECT * FROM users WHERE tienda_id=%s AND rol='domiciliario' ORDER BY nombre",(tid,),fetchall=True) or []
    filas="".join(
        f"<tr><td><strong>{d['user']}</strong></td><td>{d.get('nombre','')}</td><td>{d.get('telefono','-')}</td><td>{d.get('email','-')}</td>"
        f"<td class='fr'>"
        f"<button class='btn bw2 bsm' onclick=\"editDomi({d['id']},'{d['user']}','{str(d.get('nombre','')).replace(chr(39),'')}','{d.get('telefono','')}','{d.get('email','')}')\">✏️ Editar</button>"
        f"<form method='post' style='display:inline'><input type='hidden' name='ac' value='del'><input type='hidden' name='uid' value='{d['id']}'><button class='btn bd bsm' onclick=\"return confirm('Eliminar {d['user']}?')\">🗑️</button></form>"
        f"</td></tr>"
        for d in doms)
    return base("🏍️ Gestión de Domiciliarios",(msg+
        f'<div class="g2">'
        f'<div class="sec"><div class="sh"><h3>Crear / Editar Domiciliario</h3></div><div class="sb2">'
        f'<form method="post" id="fdomi"><input type="hidden" name="ac" id="daccion" value="crear"><input type="hidden" name="uid" id="duid" value="0">'
        f'<div style="display:flex;flex-direction:column;gap:11px">'
        f'<div class="fg"><label>Usuario *</label><input type="text" name="user" id="duser" required></div>'
        f'<div class="fg"><label>Nombre</label><input type="text" name="nombre" id="dnombre"></div>'
        f'<div class="fg"><label>Teléfono</label><input type="tel" name="telefono" id="dtel"></div>'
        f'<div class="fg"><label>Email</label><input type="email" name="email" id="demail"></div>'
        f'<div class="fg"><label>Contraseña *</label><input type="password" name="pass" id="dpass" placeholder="Min 8, MAYÚSCULA, número, especial">'
        f'<span class="ph">Min 8 | 1 MAYÚSCULA | 1 número | 1 especial</span></div>'
        f'<div class="fr"><button class="btn bp" id="dbtn">Crear Domiciliario</button>'
        f'<button type="button" class="btn bg" onclick="resetDomi()">Cancelar</button></div>'
        f'</div></form></div></div>'
        f'<div class="sec"><div class="sh"><h3>Domiciliarios ({len(doms)})</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>Usuario</th><th>Nombre</th><th>Teléfono</th><th>Email</th><th>Acciones</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=5 class=tmuted>Sin domiciliarios</td></tr>" if not filas else filas}</tbody></table></div></div></div>'
        f'</div><script>'
        f'function editDomi(id,u,n,t,e){{'
        f'  document.getElementById("daccion").value="editar";'
        f'  document.getElementById("duid").value=id;'
        f'  document.getElementById("duser").value=u;'
        f'  document.getElementById("duser").disabled=true;'
        f'  document.getElementById("dnombre").value=n;'
        f'  document.getElementById("dtel").value=t;'
        f'  document.getElementById("demail").value=e;'
        f'  document.getElementById("dpass").placeholder="Dejar vacío para no cambiar";'
        f'  document.getElementById("dbtn").textContent="💾 Guardar Cambios";'
        f'  document.getElementById("fdomi").scrollIntoView({{behavior:"smooth"}});'
        f'}}'
        f'function resetDomi(){{'
        f'  document.getElementById("daccion").value="crear";'
        f'  document.getElementById("duid").value="0";'
        f'  document.getElementById("duser").value="";'
        f'  document.getElementById("duser").disabled=false;'
        f'  document.getElementById("dnombre").value="";'
        f'  document.getElementById("dtel").value="";'
        f'  document.getElementById("demail").value="";'
        f'  document.getElementById("dpass").placeholder="Min 8, MAYÚSCULA, número, especial";'
        f'  document.getElementById("dbtn").textContent="Crear Domiciliario";'
        f'}}'
        f'</script>'))

# ================================================================
#  PRODUCCIÓN
# ================================================================
@app.route("/produccion",methods=["GET","POST"])
def produccion():
    if not is_ad(): return redirect("/")
    return _prod()

@app.route("/produccion_emp",methods=["GET","POST"])
def produccion_emp():
    if not is_st(): return redirect("/")
    return _prod()

def _prod():
    tid=tid_now(); msg=""
    if request.method=="POST":
        a=request.form.get("a","reg")
        if a=="rec":
            db_query("INSERT INTO recetas(tienda_id,nombre,ing,uds,desc_,fecha) VALUES(%s,%s,%s,%s,%s,%s)",
                     (tid,request.form.get("nombre","").strip(),request.form.get("ing","").strip(),
                      int(request.form.get("uds",1)),request.form.get("desc","").strip(),now()),commit=True)
            msg='<div class="al a-s">✅ Receta guardada.</div>'
        else:
            rid=int(request.form.get("rid",0)); lotes=int(request.form.get("lotes",1))
            inid=request.form.get("inid",""); incnt=int(request.form.get("incnt","0") or 0)
            rec=db_query("SELECT * FROM recetas WHERE id=%s AND tienda_id=%s",(rid,tid),fetchone=True)
            if rec:
                unids=rec["uds"]*lotes
                if inid:
                    pr=db_query("SELECT * FROM productos WHERE id=%s AND tienda_id=%s",(int(inid),tid),fetchone=True)
                    if pr: db_query("UPDATE productos SET cantidad=%s WHERE id=%s",(max(0,pr["cantidad"]-incnt*lotes),int(inid)),commit=True)
                db_query("INSERT INTO produccion(tienda_id,receta,lotes,unids,fecha,user) VALUES(%s,%s,%s,%s,%s,%s)",
                         (tid,rec["nombre"],lotes,unids,now(),session.get("user","")),commit=True)
                msg=f'<div class="al a-s">✅ Producción: {unids} uds de {rec["nombre"]}.</div>'
    recs=db_query("SELECT * FROM recetas WHERE tienda_id=%s ORDER BY nombre",(tid,),fetchall=True) or []
    pp=db_query("SELECT * FROM produccion WHERE tienda_id=%s ORDER BY id DESC LIMIT 10",(tid,),fetchall=True) or []
    prods=db_query("SELECT * FROM productos WHERE tienda_id=%s ORDER BY nombre",(tid,),fetchall=True) or []
    or_="".join(f"<option value='{r['id']}'>{r['nombre']} ({r['uds']} uds/lote)</option>" for r in recs)
    op_="".join(f"<option value='{p['id']}'>{p['nombre']} (stock:{p['cantidad']})</option>" for p in prods)
    fr_="".join(f"<tr><td><strong>{r['nombre']}</strong></td><td>{r.get('ing','')}</td><td>{r['uds']}</td><td>{r.get('desc_','')}</td></tr>" for r in recs)
    fh_="".join(f"<tr><td>{p['receta']}</td><td>{p['lotes']}</td><td>{p['unids']}</td><td>{p.get('user','')}</td><td>{p['fecha']}</td></tr>" for p in pp)
    return base("🍞 Producción",(msg+
        f'<div class="g2">'
        f'<div class="sec"><div class="sh"><h3>Nueva Receta</h3></div><div class="sb2">'
        f'<form method="post" style="display:flex;flex-direction:column;gap:10px"><input type="hidden" name="a" value="rec">'
        f'<div class="fg"><label>Nombre *</label><input type="text" name="nombre" required></div>'
        f'<div class="fg"><label>Ingredientes</label><textarea name="ing" placeholder="Harina 500g, Azúcar 200g..."></textarea></div>'
        f'<div class="fg"><label>Uds por lote</label><input type="number" name="uds" min="1" value="12" required></div>'
        f'<div class="fg"><label>Descripción</label><input type="text" name="desc"></div>'
        f'<button class="btn bp">💾 Guardar Receta</button></form></div></div>'
        f'<div class="sec"><div class="sh"><h3>Registrar Producción</h3></div><div class="sb2">'
        f'<form method="post" style="display:flex;flex-direction:column;gap:10px"><input type="hidden" name="a" value="reg">'
        f'<div class="fg"><label>Receta</label><select name="rid">{"<option>Sin recetas</option>" if not or_ else or_}</select></div>'
        f'<div class="fg"><label>Lotes</label><input type="number" name="lotes" min="1" value="1" required></div>'
        f'<div class="fg"><label>Insumo a descontar</label><select name="inid"><option value="">ninguno</option>{op_}</select></div>'
        f'<div class="fg"><label>Cantidad insumo/lote</label><input type="number" name="incnt" min="0" value="0"></div>'
        f'<button class="btn bs">🍞 Producir</button></form></div></div></div>'
        f'<div class="sec"><div class="sh"><h3>Recetas</h3></div><div class="sb2"><div class="tw"><table><thead><tr><th>Nombre</th><th>Ingredientes</th><th>Uds/Lote</th><th>Desc.</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=4 class=tmuted>Sin recetas</td></tr>" if not fr_ else fr_}</tbody></table></div></div></div>'
        f'<div class="sec"><div class="sh"><h3>Historial Producción</h3></div><div class="sb2"><div class="tw"><table><thead><tr><th>Receta</th><th>Lotes</th><th>Unidades</th><th>Empleado</th><th>Fecha</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=5 class=tmuted>Sin producciones</td></tr>" if not fh_ else fh_}</tbody></table></div></div></div>'))

# ================================================================
#  CAJA
# ================================================================
@app.route("/caja",methods=["GET","POST"])
def caja():
    if not is_ad(): return redirect("/")
    return _caja()

@app.route("/caja_emp",methods=["GET","POST"])
def caja_emp():
    if not is_st(): return redirect("/")
    return _caja()

def _caja():
    tid=tid_now(); msg=""

    if request.method=="POST":
        ac=request.form.get("ac","add")

        if ac=="add":
            tipo=request.form.get("tipo","ingreso")
            monto=float(request.form.get("monto",0))
            desc=request.form.get("desc","").strip()

            db_query(
                "INSERT INTO caja(tienda_id,tipo,monto,descripcion,fecha) VALUES(%s,%s,%s,%s,%s)",
                (tid,tipo,monto,desc,now()),
                commit=True
            )

            msg=f'<div class="al a-s">✅ Movimiento registrado: {fmt(monto)}</div>'

        elif ac=="del_all":
            if request.form.get("confirm_del")=="SI":
                db_query("DELETE FROM caja WHERE tienda_id=%s",(tid,),commit=True)
                msg='<div class="al a-s">✅ Caja limpiada.</div>'

        elif ac=="del_one":
            cid=request.form.get("cid")
            if cid:
                db_query("DELETE FROM caja WHERE id=%s AND tienda_id=%s",(cid,tid),commit=True)
                msg='<div class="al a-s">🗑️ Registro eliminado.</div>'

    rw = db_query(
        "SELECT * FROM caja WHERE tienda_id=%s ORDER BY id DESC LIMIT 40",
        (tid,),
        fetchall=True
    ) or []

    ing = db_query(
        "SELECT COALESCE(SUM(monto),0) as s FROM caja WHERE tienda_id=%s AND tipo='ingreso'",
        (tid,),
        fetchone=True
    )["s"]

    egr = db_query(
        "SELECT COALESCE(SUM(monto),0) as s FROM caja WHERE tienda_id=%s AND tipo='egreso'",
        (tid,),
        fetchone=True
    )["s"]

    filas = "".join(
        f"<tr><td><span class='tag {'t-gr' if m['tipo']=='ingreso' else 't-rd'}'>{m['tipo'].upper()}</span></td>"
        f"<td>{fmt(m['monto'])}</td><td>{m.get('descripcion','')}</td><td>{m.get('fecha','')}</td>"
        f"<td><form method='post' style='display:inline'><input type='hidden' name='ac' value='del_one'>"
        f"<input type='hidden' name='cid' value='{m['id']}'>"
        f"<button class='btn bd bsm' onclick=\"return confirm('Eliminar este registro?')\">🗑️</button></form></td></tr>"
        for m in rw
    )

    return base("💰 Caja y Finanzas",(
        msg +
        f'<div class="kg">'
        f'<div class="kc k-gr"><div class="ki">⬆️</div><div class="kl">Ingresos</div><div class="kv" style="font-size:1.05rem">{fmt(ing)}</div></div>'
        f'<div class="kc k-rd"><div class="ki">⬇️</div><div class="kl">Egresos</div><div class="kv" style="font-size:1.05rem">{fmt(egr)}</div></div>'
        f'<div class="kc k-bl"><div class="ki">💰</div><div class="kl">Saldo Neto</div><div class="kv" style="font-size:1.05rem">{fmt(float(ing)-float(egr))}</div></div>'
        f'</div>'

        f'<div class="g2">'

        f'<div class="sec"><div class="sh"><h3>Registrar Movimiento</h3></div><div class="sb2">'
        f'<form method="post" style="display:flex;flex-direction:column;gap:11px">'
        f'<input type="hidden" name="ac" value="add">'
        f'<div class="fg"><label>Tipo</label><select name="tipo"><option value="ingreso">📈 Ingreso</option><option value="egreso">📉 Egreso</option></select></div>'
        f'<div class="fg"><label>Monto (COP)</label><input type="number" name="monto" placeholder="50000" required></div>'
        f'<div class="fg"><label>Descripción</label><input type="text" name="desc" placeholder="Descripción del movimiento"></div>'
        f'<button class="btn bp">✅ Registrar</button></form>'

        f'<div class="sep"></div>'
        f'<p style="font-size:.75rem;font-weight:700;color:var(--dn);margin-bottom:8px">⚠️ Borrar TODOS los registros de caja</p>'
        f'<form method="post" style="display:flex;gap:8px;flex-wrap:wrap">'
        f'<input type="hidden" name="ac" value="del_all">'
        f'<input type="text" name="confirm_del" placeholder="Escribe SI para confirmar" style="flex:1">'
        f'<button class="btn bd bsm">🗑️ Limpiar caja</button></form>'
        f'</div></div>'

        f'<div class="sec"><div class="sh"><h3>Movimientos Recientes</h3>'
        f'<a href="/pdf_caja" class="btn bg bsm">📄 PDF</a></div>'
        f'<div class="sb2"><div class="tw"><table>'
        f'<thead><tr><th>Tipo</th><th>Monto</th><th>Descripción</th><th>Fecha</th><th>Borrar</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=5 class=tmuted>Sin movimientos</td></tr>" if not filas else filas}</tbody>'
        f'</table></div></div></div>'

        f'</div>'
    ))

@app.route("/caja_del_one/<int:cid>", methods=["POST"])
def caja_del_one(cid):
    if not is_st(): return redirect("/")
    db_query("DELETE FROM caja WHERE id=%s AND tienda_id=%s",(cid,tid_now()),commit=True)
    return redirect("/caja" if is_ad() else "/caja_emp")

# ================================================================
#  REPORTES
# ================================================================
@app.route("/reportes")
def reportes():
    if not is_ad(): return redirect("/")
    tid = tid_now()
    f_desde = request.args.get("desde","")
    f_hasta  = request.args.get("hasta","")
    n_peds = db_query("SELECT COUNT(*) as c FROM pedidos WHERE tienda_id=%s",(tid,),fetchone=True)["c"]
    ing    = db_query("SELECT COALESCE(SUM(monto),0) as s FROM caja WHERE tienda_id=%s AND tipo='ingreso'",(tid,),fetchone=True)["s"]
    egr    = db_query("SELECT COALESCE(SUM(monto),0) as s FROM caja WHERE tienda_id=%s AND tipo='egreso'",(tid,),fetchone=True)["s"]
    mermas = db_query("SELECT COALESCE(SUM(cant),0) as s FROM movimientos WHERE tienda_id=%s AND tipo='merma'",(tid,),fetchone=True)["s"]
    top    = db_query("SELECT producto, SUM(cantidad) as total FROM pedidos WHERE tienda_id=%s GROUP BY producto ORDER BY total DESC LIMIT 5",(tid,),fetchall=True) or []
    mets   = db_query("SELECT pago, SUM(subtotal) as total FROM pedidos WHERE tienda_id=%s GROUP BY pago",(tid,),fetchall=True) or []
    prods  = db_query("SELECT * FROM productos WHERE tienda_id=%s ORDER BY nombre",(tid,),fetchall=True) or []
    th = "".join(f"<tr><td>{i+1}</td><td><strong>{r['producto'][:28]}</strong></td><td>{r['total']}</td></tr>" for i,r in enumerate(top))
    mh = "".join(f"<tr><td>{r['pago']}</td><td>{fmt(r['total'])}</td></tr>" for r in mets)
    inv= "".join(f"<tr><td><strong>{p['nombre']}</strong></td><td>{p.get('categoria','')}</td>"
                 f"<td>{p['cantidad']} {p.get('unidad','')}</td><td>{p.get('stock_min',5)}</td>"
                 f"<td><span class='tag {'t-rd' if p['cantidad']<=p.get('stock_min',5) else 't-gr'}'>{'⚠ Bajo' if p['cantidad']<=p.get('stock_min',5) else '✅ OK'}</span></td></tr>"
                 for p in prods)
    return base("📈 Reportes y Análisis",(
        f'<div class="sec"><div class="sh"><h3>📄 Exportar PDF por rango</h3></div><div class="sb2">'
        f'<form method="get" action="/pdf_reporte" target="_blank" style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">'
        f'<div class="fg"><label>Desde</label><input type="date" name="desde" value="{f_desde}"></div>'
        f'<div class="fg"><label>Hasta</label><input type="date" name="hasta" value="{f_hasta}"></div>'
        f'<div class="fg"><label>Sección</label><select name="sec">'
        f'<option value="todo">📋 Todo</option>'
        f'<option value="pedidos">🧾 Pedidos</option>'
        f'<option value="caja">💰 Caja</option>'
        f'<option value="inventario">📦 Inventario</option>'
        f'</select></div>'
        f'<button class="btn bp">📄 Generar PDF</button>'
        f'<a href="/pdf_reporte?desde={str((datetime.now()-timedelta(days=15)).strftime("%Y-%m-%d"))}&hasta={hoy()}&sec=todo" target="_blank" class="btn bg bsm">📋 Últimos 15 días</a>'
        f'<a href="/pdf_reporte?desde={hoy()[:8]}01&hasta={hoy()}&sec=todo" target="_blank" class="btn bg bsm">📅 Este mes</a>'
        f'</form></div></div>'
        f'<div class="kg">'
        f'<div class="kc k-bl"><div class="ki">🧾</div><div class="kl">Pedidos</div><div class="kv">{n_peds}</div></div>'
        f'<div class="kc k-gr"><div class="ki">💵</div><div class="kl">Ingresos</div><div class="kv" style="font-size:1.05rem">{fmt(ing)}</div></div>'
        f'<div class="kc k-rd"><div class="ki">💸</div><div class="kl">Egresos</div><div class="kv" style="font-size:1.05rem">{fmt(egr)}</div></div>'
        f'<div class="kc k-am"><div class="ki">💰</div><div class="kl">Saldo Neto</div><div class="kv" style="font-size:1.05rem">{fmt(float(ing)-float(egr))}</div></div>'
        f'<div class="kc k-rd"><div class="ki">🗑️</div><div class="kl">Mermas (uds)</div><div class="kv">{mermas}</div></div>'
        f'</div>'
        f'<div class="g2">'
        f'<div class="sec"><div class="sh"><h3>🏆 Top 5 más vendidos</h3></div><div class="sb2"><div class="tw"><table><thead><tr><th>#</th><th>Producto</th><th>Uds</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=3 class=tmuted>Sin datos</td></tr>" if not th else th}</tbody></table></div></div></div>'
        f'<div class="sec"><div class="sh"><h3>💳 Ventas por Pago</h3></div><div class="sb2"><div class="tw"><table><thead><tr><th>Método</th><th>Total</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=2 class=tmuted>Sin datos</td></tr>" if not mh else mh}</tbody></table></div></div></div>'
        f'</div>'
        f'<div class="sec"><div class="sh"><h3>📦 Estado del Inventario</h3></div><div class="sb2"><div class="tw"><table><thead><tr><th>Producto</th><th>Categoría</th><th>Stock</th><th>Mín.</th><th>Estado</th></tr></thead>'
        f'<tbody>{inv if inv else "<tr><td colspan=5 class=tmuted>Sin productos</td></tr>"}</tbody></table></div></div></div>'))

# ================================================================
#  PDF FACTURA POR PEDIDO
# ================================================================
@app.route
def pdf_pedido_2(pid):
    if not li(): return redirect("/")
    tid = tid_now(); t = get_tienda()
    p = db_query("SELECT * FROM pedidos WHERE id=%s AND tienda_id=%s",(pid,tid),fetchone=True)
    if not p: return redirect("/mis_pedidos")
    items_list = []
    try: items_list = json.loads(p.get("items") or "[]")
    except: pass
    buf = io.BytesIO(); c = pdf_canvas.Canvas(buf, pagesize=letter); W,H = letter
    pc = t.get("color","#4f46e5").lstrip("#")
    r2,g2,b2 = int(pc[0:2],16)/255, int(pc[2:4],16)/255, int(pc[4:6],16)/255
    # Header
    c.setFillColorRGB(r2,g2,b2); c.rect(0,H-72,W,72,fill=True,stroke=False)
    c.setFillColor(pdf_colors.white); c.setFont("Helvetica-Bold",17)
    c.drawString(38,H-40,t.get("nombre","GestorPro"))
    c.setFont("Helvetica",8)
    c.drawString(38,H-56,f"NIT: {t.get('nit','')} | {t.get('ciudad','')} | Tel: {t.get('telefono','')}")
    # Datos pedido
    c.setFillColor(pdf_colors.HexColor("#1e293b")); c.setFont("Helvetica-Bold",12)
    c.drawString(38,H-102,"RECIBO DE COMPRA")
    c.setFont("Helvetica",9)
    c.drawString(38,H-118,f"Código:  {p.get('codigo','')}")
    c.drawString(38,H-133,f"Fecha:   {p.get('fecha','')}")
    c.drawString(38,H-148,f"Cliente: {p.get('user','')}")
    c.drawString(38,H-163,f"Pago:    {p.get('pago','')}  |  Entrega: {p.get('entrega','').capitalize()}")
    if p.get("direccion"): c.drawString(38,H-178,f"Dirección: {p.get('direccion','')}")
    # Tabla items
    ty = H-218; c.setFillColorRGB(r2,g2,b2)
    c.rect(30,ty,W-60,22,fill=True,stroke=False)
    c.setFillColor(pdf_colors.white); c.setFont("Helvetica-Bold",8)
    c.drawString(38,ty+7,"Producto"); c.drawString(285,ty+7,"Cant.")
    c.drawString(355,ty+7,"Precio unit."); c.drawRightString(W-36,ty+7,"Subtotal")
    if not items_list:
        items_list = [{"nombre":p.get("producto",""),"cantidad":p.get("cantidad",1),
                       "precio":float(p.get("precio",0)),"subtotal":float(p.get("subtotal",0))}]
    ry = ty - 18; c.setFillColor(pdf_colors.HexColor("#1e293b")); c.setFont("Helvetica",8)
    for it in items_list:
        c.drawString(38,ry,str(it.get("nombre",""))[:38])
        c.drawString(285,ry,str(it.get("cantidad","")))
        c.drawString(355,ry,f"$ {int(float(it.get('precio',0))):,}".replace(',','.'))
        c.drawRightString(W-36,ry,f"$ {int(float(it.get('subtotal',0))):,}".replace(',','.'))
        ry -= 17; c.setStrokeColor(pdf_colors.HexColor("#e2e8f4")); c.line(30,ry+8,W-28,ry+8)
    # Total
    ry -= 8; c.setFillColor(pdf_colors.HexColor("#15803d")); c.setFont("Helvetica-Bold",11)
    c.drawRightString(W-36,ry+4,f"TOTAL: $ {int(float(p.get('subtotal',0))):,}".replace(',','.'))
    # Instrucciones de pago
    ry -= 30; met = p.get("pago","")
    tel = t.get("telefono",""); wa = t.get("whatsapp","").replace("+","").replace(" ","")
    c.setFont("Helvetica-Bold",9); c.setFillColor(pdf_colors.HexColor("#1e293b"))
    if met in ("Nequi","Daviplata") and tel:
        c.drawString(38,ry,f"📱 Pago {met}: Envía al número {tel}. Concepto: {p.get('codigo','')}")
        ry -= 14
        if wa: c.drawString(38,ry,f"📲 Envía comprobante por WhatsApp: wa.me/+{wa}")
    elif met == "Efectivo":
        c.drawString(38,ry,"💵 Pago en efectivo al recibir el pedido o en tienda.")
    # Footer
    c.setFillColor(pdf_colors.HexColor("#64748b")); c.setFont("Helvetica",7)
    c.drawCentredString(W/2,45,f"GestorPro | {t.get('nombre','')} | {t.get('ciudad','')} | {now()} | ¡Gracias por su compra!")
    if wa: c.drawCentredString(W/2,33,f"WhatsApp: +{wa}")
    c.save(); buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f"Recibo_{p.get('codigo','GP')}.pdf",
                     mimetype="application/pdf")

# ================================================================
#  PDF REPORTE POR RANGO DE FECHAS
# ================================================================
@app.route("/pdf_reporte")
def pdf_reporte():
    if not is_st(): return redirect("/")
    tid = tid_now(); t = get_tienda()
    f_desde = request.args.get("desde",""); f_hasta = request.args.get("hasta",hoy())
    sec     = request.args.get("sec","todo")
    buf = io.BytesIO(); c = pdf_canvas.Canvas(buf, pagesize=letter); W,H = letter
    pc = t.get("color","#4f46e5").lstrip("#")
    r2,g2,b2 = int(pc[0:2],16)/255, int(pc[2:4],16)/255, int(pc[4:6],16)/255
    # Header
    c.setFillColorRGB(r2,g2,b2); c.rect(0,H-72,W,72,fill=True,stroke=False)
    c.setFillColor(pdf_colors.white); c.setFont("Helvetica-Bold",16)
    c.drawString(38,H-40,f"{t.get('nombre','GestorPro')} — Reporte")
    c.setFont("Helvetica",8)
    c.drawString(38,H-56,f"Período: {f_desde or 'Inicio'} → {f_hasta}  |  Generado: {now()}")
    y = H - 100; c.setFillColor(pdf_colors.HexColor("#1e293b"))

    def section_title(text):
        nonlocal y
        if y < 120: c.showPage(); y = H - 60
        c.setFillColorRGB(r2,g2,b2); c.rect(30,y-4,W-60,20,fill=True,stroke=False)
        c.setFillColor(pdf_colors.white); c.setFont("Helvetica-Bold",10)
        c.drawString(36,y+4,text); y -= 26; c.setFillColor(pdf_colors.HexColor("#1e293b"))

    def row_line(cols, sizes, bold=False):
        nonlocal y
        if y < 60: c.showPage(); y = H - 60
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 8)
        x = 36
        for txt, sz in zip(cols, sizes):
            c.drawString(x, y, str(txt)[:int(sz*0.14)])
            x += sz
        y -= 14
        c.setStrokeColor(pdf_colors.HexColor("#e2e8f4"))
        c.line(30,y+8,W-30,y+8)

    # PEDIDOS
    if sec in ("todo","pedidos"):
        q = "SELECT * FROM pedidos WHERE tienda_id=%s"; params = [tid]
        if f_desde: q += " AND fecha>=%s"; params.append(f_desde)
        if f_hasta: q += " AND fecha<=%s"; params.append(f_hasta+" 23:59")
        q += " ORDER BY id DESC"
        peds = db_query(q, tuple(params), fetchall=True) or []
        section_title(f"🧾 PEDIDOS ({len(peds)})")
        row_line(["Código","Cliente","Producto","Total","Estado","Fecha"],[80,80,140,70,70,80],bold=True)
        for p2 in peds:
            row_line([p2.get("codigo",""),p2.get("user",""),str(p2.get("producto",""))[:20],
                      fmt(p2.get("subtotal",0)),p2.get("estado",""),str(p2.get("fecha",""))[:16]],
                     [80,80,140,70,70,80])

    # CAJA
    if sec in ("todo","caja"):
        q2 = "SELECT * FROM caja WHERE tienda_id=%s"; p2 = [tid]
        if f_desde: q2 += " AND fecha>=%s"; p2.append(f_desde)
        if f_hasta: q2 += " AND fecha<=%s"; p2.append(f_hasta+" 23:59")
        q2 += " ORDER BY id DESC"
        movs = db_query(q2, tuple(p2), fetchall=True) or []
        ing_t = sum(float(m["monto"]) for m in movs if m["tipo"]=="ingreso")
        egr_t = sum(float(m["monto"]) for m in movs if m["tipo"]=="egreso")
        section_title(f"💰 CAJA — Ingresos: {fmt(ing_t)}  Egresos: {fmt(egr_t)}  Saldo: {fmt(ing_t-egr_t)}")
        row_line(["Tipo","Monto","Descripción","Fecha"],[70,90,200,100],bold=True)
        for m in movs:
            row_line([m["tipo"].upper(),fmt(m["monto"]),str(m.get("descripcion",""))[:28],str(m.get("fecha",""))[:16]],
                     [70,90,200,100])

    # INVENTARIO
    if sec in ("todo","inventario"):
        prods = db_query("SELECT * FROM productos WHERE tienda_id=%s ORDER BY nombre",(tid,),fetchall=True) or []
        section_title(f"📦 INVENTARIO ({len(prods)} productos)")
        row_line(["Nombre","Categoría","Stock","Unidad","Mín.","Estado"],[150,90,60,60,50,60],bold=True)
        for p3 in prods:
            estado = "BAJO" if p3["cantidad"]<=p3.get("stock_min",5) else "OK"
            row_line([p3["nombre"],p3.get("categoria",""),p3["cantidad"],
                      p3.get("unidad",""),p3.get("stock_min",5),estado],
                     [150,90,60,60,50,60])

    # Footer
    c.setFillColor(pdf_colors.HexColor("#64748b")); c.setFont("Helvetica",7)
    c.drawCentredString(W/2,30,f"GestorPro | {t.get('nombre','')} | Reporte generado el {now()}")
    c.save(); buf.seek(0)
    rango = f"{f_desde}_a_{f_hasta}".replace("-","")
    return send_file(buf, as_attachment=True,
                     download_name=f"Reporte_{t.get('id','gp')}_{rango}.pdf",
                     mimetype="application/pdf")

# ================================================================
#  PDF CAJA COMPLETO
# ================================================================
@app.route("/pdf_caja")
def pdf_caja():
    if not is_ad(): return redirect("/")
    tid = tid_now(); t = get_tienda()
    movs = db_query("SELECT * FROM caja WHERE tienda_id=%s ORDER BY id DESC",(tid,),fetchall=True) or []
    ing  = sum(float(m["monto"]) for m in movs if m["tipo"]=="ingreso")
    egr  = sum(float(m["monto"]) for m in movs if m["tipo"]=="egreso")
    buf  = io.BytesIO(); c = pdf_canvas.Canvas(buf, pagesize=letter); W,H = letter
    pc   = t.get("color","#4f46e5").lstrip("#")
    r2,g2,b2 = int(pc[0:2],16)/255, int(pc[2:4],16)/255, int(pc[4:6],16)/255
    c.setFillColorRGB(r2,g2,b2); c.rect(0,H-72,W,72,fill=True,stroke=False)
    c.setFillColor(pdf_colors.white); c.setFont("Helvetica-Bold",15)
    c.drawString(38,H-40,f"{t.get('nombre','')} — Resumen de Caja")
    c.setFont("Helvetica",8); c.drawString(38,H-56,f"Generado: {now()}")
    y = H - 100; c.setFillColor(pdf_colors.HexColor("#1e293b"))
    c.setFont("Helvetica-Bold",10)
    c.drawString(38,y,f"Ingresos: {fmt(ing)}   |   Egresos: {fmt(egr)}   |   Saldo: {fmt(ing-egr)}")
    y -= 28; c.setFont("Helvetica-Bold",8)
    for lbl,col,x in [("Tipo",70,36),("Monto",90,106),("Descripción",200,196),("Fecha",100,396)]:
        c.drawString(x,y,lbl)
    y -= 14; c.setFont("Helvetica",8)
    for m in movs:
        if y < 50: c.showPage(); y = H - 50
        c.drawString(36,y,m["tipo"].upper()[:8])
        c.drawString(106,y,fmt(m["monto"]))
        c.drawString(196,y,str(m.get("descripcion",""))[:28])
        c.drawString(396,y,str(m.get("fecha",""))[:16])
        y -= 13; c.setStrokeColor(pdf_colors.HexColor("#e2e8f4")); c.line(30,y+6,W-30,y+6)
    c.setFillColor(pdf_colors.HexColor("#64748b")); c.setFont("Helvetica",7)
    c.drawCentredString(W/2,30,f"GestorPro | {t.get('nombre','')} | {now()}")
    c.save(); buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"Caja_{t.get('id','gp')}.pdf", mimetype="application/pdf")

# ================================================================
#  NOTIFICACIONES
# ================================================================
@app.route("/notificaciones_emp")
def notificaciones_emp():
    """Alertas para empleados — stock bajo + notificaciones + comprobantes."""
    if not is_st(): return redirect("/")
    tid=tid_now()
    db_query("UPDATE notificaciones SET leida=1 WHERE tienda_id=%s",(tid,),commit=True)
    nots=db_query("SELECT * FROM notificaciones WHERE tienda_id=%s ORDER BY id DESC LIMIT 20",(tid,),fetchall=True) or []
    bajos=db_query("SELECT * FROM productos WHERE tienda_id=%s AND cantidad<=stock_min ORDER BY cantidad ASC",(tid,),fetchall=True) or []
    comps_pend=db_query("SELECT COUNT(*) as c FROM comprobantes WHERE tienda_id=%s AND revisado=0",(tid,),fetchone=True)
    n_comp=comps_pend["c"] if comps_pend else 0

    al="".join(
        f'<div class="al a-w" style="flex-direction:column;align-items:flex-start">'
        f'<div>⚠️ Stock bajo: <strong>{p["nombre"]}</strong> — '
        f'{p["cantidad"]} {p.get("unidad","uds")} (mín: {p.get("stock_min",5)})</div>'
        f'<a href="/inventario_emp" class="btn bw2 bsm mt8">📦 Registrar entrada</a>'
        f'</div>'
        for p in bajos
    ) or '<div class="al a-s">✅ Todos los productos tienen stock suficiente.</div>'

    comp_banner=""
    if n_comp>0:
        comp_banner=(f'<div class="al a-w" style="font-size:.9rem">'
                     f'📎 Hay <strong>{n_comp} comprobante(s) de pago pendiente(s)</strong> de revisión. '
                     f'<a href="/comprobantes_pedido" class="btn bnq bsm" style="margin-left:8px">Ver comprobantes</a>'
                     f'</div>')

    filas="".join(
        f"<tr><td>{n.get('fecha','')}</td><td>{n.get('mensaje','')}</td>"
        f"<td><span class='tag t-gr'>Leída</span></td></tr>"
        for n in nots)

    return base("🔔 Alertas y Notificaciones",(
        comp_banner+
        f'<div class="sec"><div class="sh"><h3>⚠️ Stock Bajo ({len(bajos)})</h3></div>'
        f'<div class="sb2">{al}</div></div>'
        f'<div class="sec"><div class="sh"><h3>📬 Notificaciones recientes</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead>'
        f'<tr><th>Fecha</th><th>Mensaje</th><th>Estado</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=3 class=tmuted>Sin notificaciones</td></tr>" if not filas else filas}'
        f'</tbody></table></div></div></div>'))


@app.route("/notificaciones")
def notificaciones():
    """Notificaciones completas para admin."""
    if not is_st(): return redirect("/")
    tid=tid_now()
    db_query("UPDATE notificaciones SET leida=1 WHERE tienda_id=%s",(tid,),commit=True)
    nots=db_query("SELECT * FROM notificaciones WHERE tienda_id=%s ORDER BY id DESC LIMIT 25",(tid,),fetchall=True) or []
    bajos=db_query("SELECT * FROM productos WHERE tienda_id=%s AND cantidad<=stock_min ORDER BY cantidad ASC",(tid,),fetchall=True) or []
    comps_pend=db_query("SELECT COUNT(*) as c FROM comprobantes WHERE tienda_id=%s AND revisado=0",(tid,),fetchone=True)
    n_comp=comps_pend["c"] if comps_pend else 0

    comp_banner=""
    if n_comp>0:
        comp_banner=(f'<div class="al a-w">'
                     f'📎 <strong>{n_comp} comprobante(s) pendiente(s)</strong> de revisión. '
                     f'<a href="/comprobantes_pedido" class="btn bnq bsm" style="margin-left:8px">Ver ahora</a>'
                     f'</div>')

    al="".join(
        f'<div class="al a-w">⚠️ Stock bajo: <strong>{p["nombre"]}</strong> — '
        f'{p["cantidad"]} {p.get("unidad","uds")} (mín: {p.get("stock_min",5)})<br>'
        f'<a href="/inventario" class="btn bw2 bsm mt8">📦 Ver inventario</a></div>'
        for p in bajos
    ) or '<div class="al a-s">✅ Todos los productos tienen stock suficiente.</div>'

    filas="".join(
        f"<tr><td>{n.get('fecha','')}</td><td>{n.get('mensaje','')}</td>"
        f"<td><span class='tag t-gr'>Leída</span></td></tr>"
        for n in nots)

    return base("🔔 Notificaciones",(
        comp_banner+
        f'<div class="sec"><div class="sh"><h3>⚠️ Alertas de Stock</h3></div>'
        f'<div class="sb2">{al}</div></div>'
        f'<div class="sec"><div class="sh"><h3>📬 Historial ({len(nots)})</h3>'
        f'<form method="post" action="/notif_clear" style="display:inline">'
        f'<button class="btn bd bsm" onclick="return confirm(\'Limpiar historial?\')">🗑️ Limpiar</button>'
        f'</form></div>'
        f'<div class="sb2"><div class="tw"><table><thead>'
        f'<tr><th>Fecha</th><th>Mensaje</th><th>Estado</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=3 class=tmuted>Sin notificaciones</td></tr>" if not filas else filas}'
        f'</tbody></table></div></div></div>'))

@app.route("/ver_comprobante/<int:cid>")
def ver_comprobante(cid):
    if not is_st(): return redirect("/")
    tid=tid_now()
    comp=db_query("SELECT * FROM comprobantes WHERE id=%s AND tienda_id=%s",(cid,tid),fetchone=True)
    if not comp: return "No encontrado",404
    # Marcar como revisado
    db_query("UPDATE comprobantes SET revisado=1 WHERE id=%s",(cid,),commit=True)
    datos=comp["datos"]
    mime=comp.get("mimetype","image/jpeg")
    return send_file(io.BytesIO(datos),mimetype=mime,
                     download_name=comp.get("nombre_archivo","comprobante.jpg"))


@app.route("/comprobantes_pedido")
def comprobantes_pedido():
    """Lista de comprobantes pendientes de revisión (admin/empleado)."""
    if not is_st(): return redirect("/")
    tid=tid_now()
    comps=db_query(
        "SELECT c.*,p.estado as ped_estado FROM comprobantes c "
        "JOIN pedidos p ON c.pedido_id=p.id "
        "WHERE c.tienda_id=%s ORDER BY c.id DESC LIMIT 50",
        (tid,),fetchall=True) or []
    pending=sum(1 for c in comps if not c.get("revisado"))
    filas="".join(
        f"<tr>"
        f"<td><strong>{c.get('codigo','')}</strong></td>"
        f"<td>{c.get('fecha','')}</td>"
        f"<td>{c.get('nombre_archivo','')[:30]}</td>"
        f"<td><span class='tag {'t-rd' if not c.get('revisado') else 't-gr'}'>"
        f"{'⚠️ Pendiente' if not c.get('revisado') else '✅ Revisado'}</span></td>"
        f"<td><span class='tag {'t-am' if c.get('ped_estado')=='Pendiente' else 't-gr'}'>{c.get('ped_estado','')}</span></td>"
        f"<td><a href='/ver_comprobante/{c['id']}' target='_blank' class='btn bp bsm'>👁 Ver</a></td>"
        f"</tr>"
        for c in comps)
    return base(f"📎 Comprobantes ({pending} pendientes)",(
        f'<div class="al a-{"w" if pending else "s"}">'
        f'{"⚠️ Hay "+str(pending)+" comprobantes sin revisar." if pending else "✅ Todos los comprobantes revisados."}'
        f'</div>'
        f'<div class="sec"><div class="sh">'
        f'<h3>Comprobantes de Pago ({len(comps)})</h3>'
        f'</div>'
        f'<div class="sb2"><div class="tw"><table><thead>'
        f'<tr><th>Pedido</th><th>Fecha</th><th>Archivo</th><th>Estado</th><th>Pedido</th><th>Ver</th></tr>'
        f'</thead><tbody>'
        f'{"<tr><td colspan=6 class=tmuted>Sin comprobantes</td></tr>" if not filas else filas}'
        f'</tbody></table></div></div></div>'))
@app.route("/notif_clear", methods=["POST"])
def notif_clear():
    if not is_st(): return redirect("/")
    db_query("DELETE FROM notificaciones WHERE tienda_id=%s",(tid_now(),),commit=True)
    return redirect("/notificaciones")

# ================================================================
#  CONFIGURACIÓN TIENDA (ADMIN)
# ================================================================
@app.route("/config", methods=["GET","POST"])
def config():
    if not is_ad(): return redirect("/")
    tid = tid_now()
    t   = db_query("SELECT * FROM tiendas WHERE id=%s",(tid,),fetchone=True)
    if not t: return redirect("/admin")
    msg = ""
    if request.method == "POST":
        db_query("""UPDATE tiendas SET nombre=%s,telefono=%s,whatsapp=%s,whatsapp_msg=%s,
                    horario=%s,direccion=%s,nit=%s,banco=%s,cuenta=%s WHERE id=%s""",
                 (request.form.get("nombre",t["nombre"]).strip(),
                  request.form.get("telefono",t.get("telefono","")).strip(),
                  request.form.get("whatsapp","").replace("+","").replace(" ",""),
                  request.form.get("wmsg",t.get("whatsapp_msg","")),
                  request.form.get("horario",t.get("horario","")),
                  request.form.get("direccion",t.get("direccion","")),
                  request.form.get("nit",t.get("nit","")),
                  request.form.get("banco",t.get("banco","")),
                  request.form.get("cuenta",t.get("cuenta","")),tid),commit=True)
        t   = db_query("SELECT * FROM tiendas WHERE id=%s",(tid,),fetchone=True)
        msg = '<div class="al a-s">✅ Configuración guardada.</div>'
    ws  = (f'<div class="al a-s" style="margin-top:10px">✅ WhatsApp activo: +{t["whatsapp"]}</div>'
           if t.get("whatsapp") else '<div class="al a-w" style="margin-top:10px">⚠️ Sin WhatsApp configurado.</div>')
    return base(f"⚙️ Configuración — {t['nombre']}",(
        f'<div class="g2">'
        f'<div class="sec"><div class="sh"><h3>🏢 Datos del Negocio</h3></div><div class="sb2">{msg}'
        f'<form method="post" style="display:flex;flex-direction:column;gap:10px">'
        f'<div class="fg"><label>Nombre</label><input type="text" name="nombre" value="{t["nombre"]}" required></div>'
        f'<div class="fg"><label>NIT</label><input type="text" name="nit" value="{t.get("nit","")}"></div>'
        f'<div class="fg"><label>Teléfono</label><input type="text" name="telefono" value="{t.get("telefono","")}"></div>'
        f'<div class="fg"><label>Banco</label><input type="text" name="banco" value="{t.get("banco","")}"></div>'
        f'<div class="fg"><label>Cuenta Bancaria</label><input type="text" name="cuenta" value="{t.get("cuenta","")}"></div>'
        f'<div class="fg"><label>Horario</label><input type="text" name="horario" value="{t.get("horario","")}"></div>'
        f'<div class="fg"><label>Dirección</label><input type="text" name="direccion" value="{t.get("direccion","")}"></div>'
        f'<button class="btn bp blg">💾 Guardar</button></form></div></div>'
        f'<div class="sec"><div class="sh"><h3>💬 WhatsApp de Contacto</h3></div><div class="sb2">'
        f'<div class="al a-i">Los clientes verán un botón flotante de WhatsApp en la tienda. '
        f'Después de pagar, el sistema les dará instrucciones para enviar el comprobante aquí.</div>'
        f'<form method="post" style="display:flex;flex-direction:column;gap:10px;margin-top:12px">'
        f'<div class="fg"><label>Número WhatsApp (con 57, sin +)</label>'
        f'<input type="tel" name="whatsapp" value="{t.get("whatsapp","")}" placeholder="573101234567">'
        f'<span class="ph">Ejemplo Colombia: 573101234567</span></div>'
        f'<div class="fg"><label>Mensaje predeterminado del cliente</label>'
        f'<textarea name="wmsg">{t.get("whatsapp_msg","Hola! Me interesa hacer un pedido.")}</textarea></div>'
        f'<button class="btn bwa blg">{WA_SVG} Guardar WhatsApp</button></form>{ws}</div></div>'
        f'</div>'))

# ================================================================
#  USUARIOS (ADMIN)
# ================================================================
@app.route("/usuarios", methods=["GET","POST"])
def usuarios():
    if not is_ad(): return redirect("/")
    tid = tid_now(); msg = ""
    if request.method == "POST":
        a = request.form.get("a","crear")
        if a == "crear":
            u   = request.form.get("user","").strip(); p = request.form.get("pass","")
            r   = request.form.get("rol","cliente")
            nom = request.form.get("nombre","").strip()
            tel = request.form.get("tel","").strip()
            ema = request.form.get("email","").strip()
            ok,mp = ok_pass(p)
            ex  = db_query("SELECT id FROM users WHERE user=%s AND tienda_id=%s",(u,tid),fetchone=True)
            if ex: msg = '<div class="al a-d">Usuario ya existe.</div>'
            elif not ok: msg = '<div class="al a-d">'+mp+"</div>"
            else:
                db_query("INSERT INTO users(tienda_id,user,nombre,password,rol,email,telefono,tratamiento_datos,fecha) VALUES(%s,%s,%s,%s,%s,%s,%s,1,%s)",
                         (tid,u,nom or u,generate_password_hash(p),r,ema,tel,now()),commit=True)
                msg = f'<div class="al a-s">✅ Usuario <strong>{u}</strong> creado como {r}.</div>'
        elif a == "del":
            db_query("DELETE FROM users WHERE id=%s AND tienda_id=%s",(int(request.form.get("uid",0)),tid),commit=True)
            msg = '<div class="al a-s">✅ Usuario eliminado.</div>'
    users = db_query("SELECT * FROM users WHERE tienda_id=%s ORDER BY rol,nombre",(tid,),fetchall=True) or []
    rt    = {"admin":"t-pu","empleado":"t-bl","domiciliario":"t-sk","proveedor":"t-pu","cliente":"t-cy"}
    filas = "".join(
        f"<tr><td>{u2['id']}</td><td><strong>{u2.get('nombre',u2['user'])}</strong></td>"
        f"<td>{u2['user']}</td><td>{u2.get('email','-')}</td><td>{u2.get('telefono','-')}</td>"
        f"<td><span class='tag {rt.get(u2.get('rol',''),'t-gy')}'>{u2.get('rol','')}</span></td>"
        f"<td><form method='post' style='display:inline'><input type='hidden' name='a' value='del'>"
        f"<input type='hidden' name='uid' value='{u2['id']}'>"
        f"<button class='btn bd bsm' onclick=\"return confirm('Eliminar {u2['user']}?')\">🗑️</button></form></td></tr>"
        for u2 in users)
    return base("👥 Usuarios",(msg+
        f'<div class="sec"><div class="sh"><h3>Crear Usuario</h3>'
        f'<a href="/domiciliarios" class="btn bdm bsm">🏍️ Gestionar Domiciliarios</a></div><div class="sb2">'
        f'<form method="post"><input type="hidden" name="a" value="crear"><div class="fg2">'
        f'<div class="fg"><label>Nombre</label><input type="text" name="nombre" placeholder="María García"></div>'
        f'<div class="fg"><label>Usuario *</label><input type="text" name="user" required></div>'
        f'<div class="fg"><label>Email</label><input type="email" name="email"></div>'
        f'<div class="fg"><label>Teléfono</label><input type="tel" name="tel"></div>'
        f'<div class="fg"><label>Contraseña *</label><input type="password" name="pass" required>'
        f'<span class="ph">Min 8 | MAYÚSCULA | número | especial</span></div>'
        f'<div class="fg"><label>Rol</label><select name="rol">'
        f'<option value="cliente">Cliente</option><option value="empleado">Empleado</option>'
        f'<option value="proveedor">Proveedor</option></select></div>'
        f'</div><div class="mt16"><button class="btn bp">✚ Crear Usuario</button></div></form></div></div>'
        f'<div class="sec"><div class="sh"><h3>Usuarios Registrados ({len(users)})</h3></div>'
        f'<div class="sb2"><div class="tw"><table><thead><tr><th>ID</th><th>Nombre</th><th>Usuario</th>'
        f'<th>Email</th><th>Teléfono</th><th>Rol</th><th>Acción</th></tr></thead>'
        f'<tbody>{"<tr><td colspan=7 class=tmuted>Sin usuarios</td></tr>" if not filas else filas}</tbody>'
        f'</table></div></div></div>'))

# ================================================================
#  BOT INTELIGENTE — con imágenes, botones y promociones
# ================================================================
import urllib.request as _ureq
import uuid as _uuid_mod

CLAUDE_MODEL = "claude-sonnet-4-20250514"


# ──────────────────────────────────────────────────────────────────
#  HELPERS INTERNOS
# ──────────────────────────────────────────────────────────────────

def _hhmm():
    return datetime.now().strftime("%H:%M")

def _fmt_msg(txt):
    import html as _h
    txt = _h.escape(str(txt))
    txt = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', txt)
    txt = re.sub(r'\*([^*]+)\*',     r'<em>\1</em>',         txt)
    txt = txt.replace('\n', '<br>')
    return txt

def _prod_card(p):
    """Card visual del producto dentro de la burbuja."""
    if p.get("img"):
        img_h = (f'<img class="prod-card-img" src="{p["img"]}" loading="lazy" '
                 f'onerror="this.parentNode.innerHTML=\'<div class=prod-card-no-img>📦</div>\'">')
    else:
        img_h = '<div class="prod-card-no-img">📦</div>'
    disponible = p["cantidad"] > 0
    badge = (f'<span style="background:#dcfce7;color:#15803d;font-size:.65rem;font-weight:800;'
             f'padding:2px 7px;border-radius:10px">✅ Disponible</span>'
             if disponible else
             f'<span style="background:#fef2f2;color:#dc2626;font-size:.65rem;font-weight:800;'
             f'padding:2px 7px;border-radius:10px">❌ Agotado</span>')
    return (f'<div class="prod-card-msg" onclick="window.open(\'/tienda\',\'_blank\')" title="Ver en tienda">'
            f'{img_h}'
            f'<div class="prod-card-info">'
            f'<div class="prod-card-name">{p["nombre"]}</div>'
            f'<div class="prod-card-price">{fmt(p["precio"])}'
            f'<span style="font-size:.7rem;font-weight:400;color:#64748b"> / {p.get("unidad","u")}</span></div>'
            f'<div style="margin-top:4px">{badge}</div>'
            f'{"<div class=prod-card-stock>Stock: "+str(p["cantidad"])+" "+str(p.get("unidad",""))+"</div>" if disponible else ""}'
            f'</div></div>')


# ──────────────────────────────────────────────────────────────────
#  ENTRENAMIENTO FAQ — ULTRA COMPLETO
#  Retorna (texto, prod_obj_o_None, respondido_bool)
# ──────────────────────────────────────────────────────────────────

def _bot_faq(msg, t, productos, promos):
    tl   = msg.lower().strip()
    tel  = t.get("telefono","")
    wa   = t.get("whatsapp","").replace("+","").replace(" ","")
    nom  = t.get("nombre","la tienda")
    ciu  = t.get("ciudad","Fusagasugá")
    hor  = t.get("horario","Consultar")
    dir_ = t.get("direccion","Consultar")
    wa_lnk = (f"<a href='https://wa.me/{wa}' target='_blank' "
              f"style='color:#4f46e5;font-weight:700'>WhatsApp +{wa}</a>") if wa else f"Tel: {tel}"

    todos_prods = productos  # incluye agotados también si se necesitan
    disp_prods  = [p for p in productos if p["cantidad"] > 0]
    agotados    = [p for p in productos if p["cantidad"] <= 0]

    def primer_disp():
        for p in disp_prods:
            if p.get("img"): return p
        return disp_prods[0] if disp_prods else None

    def buscar_prod(texto):
        """Busca producto por nombre parcial."""
        for p in productos:
            palabras = [w for w in p["nombre"].lower().split() if len(w) > 2]
            if any(w in texto for w in palabras):
                return p
        return None

    # ══════════════════════════════════════════════════════════════
    #  1. SALUDOS
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["hola","buenas","hey","hi","buen dia","buen día","buenos dias","buenos días",
                              "buenas tardes","buenas noches","saludos","ey","que tal","quiubo","bien","holi"]):
        return (f"¡Hola! 👋 Bienvenido a **{nom}**.\n\n"
                f"Soy tu asistente con Inteligencia Artificial 🤖\n"
                f"Puedo ayudarte con:\n"
                f"📦 Productos y precios\n"
                f"💳 Métodos de pago\n"
                f"🏍️ Domicilios y entregas\n"
                f"🔄 Devoluciones y cambios\n"
                f"💬 Conectarte con un agente\n\n"
                f"¿En qué te ayudo hoy? 😊"), None, True

    # ══════════════════════════════════════════════════════════════
    #  2. VER CATÁLOGO COMPLETO
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["producto","catalogo","catálogo","qué tienen","que hay","qué hay",
                              "disponible","ver todo","que venden","que tienen","menú","menu",
                              "lista","lista de","qué venden","tienes","tienen","muestrame","muéstrame"]):
        if not disp_prods:
            return (f"😕 En este momento **{nom}** no tiene productos disponibles.\n\n"
                    f"¡Pronto tendremos novedades! Puedes consultarnos por {wa_lnk}"), None, True
        txt = f"📦 **Catálogo de {nom}:**\n\n"
        for p in disp_prods[:10]:
            txt += f"• **{p['nombre']}** — {fmt(p['precio'])} / {p.get('unidad','u')} ✅\n"
        if len(disp_prods) > 10:
            txt += f"\n_...y {len(disp_prods)-10} productos más en la tienda._"
        txt += f"\n\n🛒 Toca la imagen o visita nuestra tienda para comprar."
        return txt, primer_disp(), True

    # ══════════════════════════════════════════════════════════════
    #  3. STOCK DISPONIBLE
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["stock","hay disponible","hay de","cuánto hay","cuanto hay",
                              "disponibilidad","existe","tienen disponible","quedan","cuántos quedan",
                              "cuantos quedan","existe el","hay el","hay pan","hay leche","quedan unidades"]):
        prod_match = buscar_prod(tl)
        if prod_match:
            if prod_match["cantidad"] > 0:
                return (f"✅ **{prod_match['nombre']}** está disponible!\n\n"
                        f"📦 Stock actual: **{prod_match['cantidad']} {prod_match.get('unidad','unidades')}**\n"
                        f"💰 Precio: **{fmt(prod_match['precio'])}** / {prod_match.get('unidad','u')}\n\n"
                        f"🛒 ¡Agrégalo al carrito antes de que se agote!"), prod_match, True
            else:
                return (f"❌ **{prod_match['nombre']}** está **agotado** en este momento.\n\n"
                        f"😔 Lo sentimos. Puedes:\n"
                        f"• Consultar cuándo habrá disponibilidad por {wa_lnk}\n"
                        f"• Ver otros productos similares en la tienda\n"
                        f"• Activar notificaciones cuando llegue"), prod_match, True
        # Stock general
        if disp_prods:
            txt = f"📦 **Productos disponibles ahora ({len(disp_prods)}):**\n\n"
            for p in disp_prods[:8]:
                txt += f"✅ **{p['nombre']}** — {p['cantidad']} {p.get('unidad','uds')} — {fmt(p['precio'])}\n"
            return txt, primer_disp(), True
        return (f"😕 No hay productos disponibles en este momento.\n"
                f"Contáctanos por {wa_lnk} para más información."), None, True

    # ══════════════════════════════════════════════════════════════
    #  4. PRODUCTOS AGOTADOS
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["agotado","agotados","sin stock","no hay","se acabó","se acabo",
                              "no tienen","no queda","terminó","termino","sold out","acabó","acabo"]):
        if agotados:
            txt = f"❌ **Productos agotados en {nom}:**\n\n"
            for p in agotados[:8]:
                txt += f"• {p['nombre']}\n"
            txt += (f"\n✅ Tenemos **{len(disp_prods)} producto(s) disponibles**.\n"
                    f"Consúltanos cuándo reponemos por {wa_lnk}")
        else:
            txt = f"🎉 ¡Buenas noticias! Todos los productos de **{nom}** están disponibles.\n\n¡Aprovecha!"
        return txt, primer_disp(), True

    # ══════════════════════════════════════════════════════════════
    #  5. PRECIO DE PRODUCTO ESPECÍFICO
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["precio","cuánto cuesta","cuanto vale","cuánto vale","vale","cuesta",
                              "costo","cuanto es","cuánto","cuanto","tarifa","a cuánto","a cuanto"]):
        prod_match = buscar_prod(tl)
        if prod_match:
            disponible = prod_match["cantidad"] > 0
            return (f"🏷️ **{prod_match['nombre']}**\n\n"
                    f"💰 Precio: **{fmt(prod_match['precio'])}** / {prod_match.get('unidad','unidad')}\n"
                    f"{'✅ Disponible: '+str(prod_match['cantidad'])+' '+str(prod_match.get('unidad','uds')) if disponible else '❌ Agotado por el momento'}\n"
                    f"🏷️ {prod_match.get('categoria','General')}\n\n"
                    f"{'🛒 ¡Agrégalo al carrito!' if disponible else '📲 Consulta reposición: '+wa_lnk}"), prod_match, True
        # Lista de precios general
        if disp_prods:
            txt = f"💰 **Lista de precios — {nom}:**\n\n"
            for p in disp_prods[:8]:
                txt += f"• **{p['nombre']}** → {fmt(p['precio'])} / {p.get('unidad','u')}\n"
            txt += f"\nEscribe el nombre del producto para ver detalles 📋"
            return txt, primer_disp(), True
        return (f"📋 En este momento no hay productos con precio disponible.\n"
                f"Consulta por {wa_lnk}"), None, True

    # ══════════════════════════════════════════════════════════════
    #  6. PROMOCIONES Y DESCUENTOS
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["promo","oferta","descuento","descuentos","especial","rebaja","barato",
                              "económico","economico","hay promo","tienen promo","promo hoy",
                              "oferta hoy","qué ofertas","que ofertas","hay descuento","cupón","cupon"]):
        if promos:
            txt = f"🎁 **¡Promociones activas en {nom}!**\n\n"
            for pr in promos[:5]:
                txt += (f"🔥 **{pr['titulo']}**\n"
                        f"   {pr.get('descuento','')} — {pr.get('descripcion','')}\n")
                if pr.get("hasta"):
                    txt += f"   ⏰ Válida hasta: {pr['hasta']}\n"
                txt += "\n"
            txt += "¡No dejes pasar estas ofertas! 🛒"
        else:
            txt = (f"😊 No hay promociones especiales activas en este momento.\n\n"
                   f"¡Pero en **{nom}** siempre manejamos los mejores precios!\n"
                   f"Pregúntame por algún producto específico 😉")
        return txt, primer_disp(), True

    # ══════════════════════════════════════════════════════════════
    #  7. MÉTODOS DE PAGO
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["pago","pagar","nequi","daviplata","efectivo","transferencia",
                              "como pago","formas de pago","metodo","método","cómo pago","como se paga",
                              "aceptan","reciben","pago online","pago digital","consignacion","consignación"]):
        return (f"💳 **Métodos de pago en {nom}:**\n\n"
                f"📱 **Nequi**\n"
                f"   Número: **{tel or '(configura en ajustes)'}**\n"
                f"   Transfiere y sube el comprobante ✅\n\n"
                f"💳 **Daviplata**\n"
                f"   Número: **{tel or '(configura en ajustes)'}**\n"
                f"   Igual, adjunta el comprobante ✅\n\n"
                f"💵 **Efectivo**\n"
                f"   Pagas al recibir o en tienda. Sin pasos extra ✅\n\n"
                f"📲 El comprobante también puedes enviarlo por {wa_lnk}"), None, True

    # ══════════════════════════════════════════════════════════════
    #  8. CÓMO HACER UN PEDIDO
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["cómo pido","como pido","hacer pedido","hacer un pedido","cómo compro",
                              "como compro","cómo se pide","como se pide","proceso de compra",
                              "quiero comprar","quiero pedir","cómo funciona","como funciona","pasos para"]):
        return (f"🛒 **Cómo hacer un pedido en {nom}:**\n\n"
                f"**1️⃣** Ve a la **Tienda** en el menú\n"
                f"**2️⃣** Elige tus productos y agrégalos al 🛒 carrito\n"
                f"**3️⃣** Clic en **Confirmar compra**\n"
                f"**4️⃣** Elige tu método de pago (Nequi, Daviplata o Efectivo)\n"
                f"**5️⃣** Selecciona si recoges en tienda o quieres domicilio 🏍️\n"
                f"**6️⃣** Si pagaste digital, sube el comprobante 📸\n"
                f"**7️⃣** ¡Listo! Recibirás tu pedido pronto 🎉\n\n"
                f"¿Tienes alguna duda? Escríbeme 😊"), None, True

    # ══════════════════════════════════════════════════════════════
    #  9. DOMICILIOS
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["domicilio","envío","envio","delivery","llevan","mandan","a domicilio",
                              "a mi casa","reparten","traen","cobran por domicilio","costo domicilio",
                              "precio domicilio","cuánto cobran","cuanto cobran","vale el domicilio",
                              "hacen domicilio","hacen envío","hacen envio","despachan"]):
        return (f"🏍️ **Domicilios de {nom}:**\n\n"
                f"✅ Sí, hacemos domicilios en **{ciu}**\n"
                f"⏱️ Tiempo estimado: **30 – 60 minutos**\n"
                f"📦 Sin pedido mínimo requerido\n"
                f"💰 Costo del domicilio: consultar por {wa_lnk}\n\n"
                f"**¿Cómo pedirlo?**\n"
                f"Al confirmar tu compra, selecciona *🏍️ Domicilio* e ingresa tu dirección.\n\n"
                f"Cubrimos: {ciu} y zonas cercanas 📍"), None, True

    # ══════════════════════════════════════════════════════════════
    #  10. HORARIO Y UBICACIÓN
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["horario","hora","abre","cierra","cuando abren","cuándo abren",
                              "atienden","a qué hora","a que hora","ubicación","ubicacion",
                              "direccion","dirección","dónde","donde","llegar","quedan","están","estan",
                              "local","locales","sucursal"]):
        return (f"🕐 **{nom} — Horario y Ubicación:**\n\n"
                f"⏰ **Horario de atención:**\n{hor}\n\n"
                f"📍 **Dirección:**\n{dir_}\n\n"
                f"🏙️ **Ciudad:** {ciu}\n"
                f"📞 **Teléfono:** {tel}\n"
                f"💬 **WhatsApp:** {wa_lnk}"), None, True

    # ══════════════════════════════════════════════════════════════
    #  11. ESTADO DEL PEDIDO
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["pedido","orden","estado","código","codigo","rastrear","seguimiento",
                              "donde esta","dónde está","cuándo llega","cuando llega","mi pedido",
                              "ver pedido","consultar pedido","pedido mio","llegó","llego","entregaron"]):
        return (f"📦 **¿Cómo ver tu pedido?**\n\n"
                f"**Opción 1 — Desde la app:**\n"
                f"1️⃣ Inicia sesión\n"
                f"2️⃣ Ve a *📦 Mis Pedidos* en el menú\n"
                f"3️⃣ Verás el estado en tiempo real\n\n"
                f"**Estados del pedido:**\n"
                f"⏳ *Pendiente* → esperando aprobación\n"
                f"✅ *Aprobado* → siendo preparado\n"
                f"🏍️ *En camino* → ya va para donde estás\n"
                f"📦 *Entregado* → ¡llegó!\n"
                f"❌ *Cancelado* → fue cancelado\n\n"
                f"**Opción 2:** Consulta por {wa_lnk}"), None, True

    # ══════════════════════════════════════════════════════════════
    #  12. CANCELAR PEDIDO
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["cancelar","cancelo","cancelar pedido","no quiero","arrepentí","arrepenti",
                              "me equivoqué","me equivoque","anular","no lo quiero"]):
        return (f"❌ **¿Cómo cancelar tu pedido?**\n\n"
                f"Tienes **10 minutos** después de hacer el pedido para cancelar sin costo.\n\n"
                f"**Pasos:**\n"
                f"1️⃣ Ve a *📦 Mis Pedidos*\n"
                f"2️⃣ Busca tu pedido\n"
                f"3️⃣ Toca el botón **❌ Cancelar**\n\n"
                f"⚠️ Si ya pasaron los 10 minutos, contáctanos por {wa_lnk}\n"
                f"y evaluamos cada caso con gusto 😊"), None, True

    # ══════════════════════════════════════════════════════════════
    #  13. DEVOLUCIONES Y CAMBIOS
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["devolución","devolucion","cambio","cambiar","reembolso","reembolsar",
                              "problema","dañado","roto","mal estado","no sirve","no era","diferente",
                              "incompleto","falta","vino mal","llegó mal","llegó roto","politica",
                              "política","queja","reclamacion","reclamación"]):
        return (f"🔄 **Devoluciones y Cambios en {nom}:**\n\n"
                f"**💸 Devolución (dinero de vuelta):**\n"
                f"Disponible hasta **24 horas** después de recibido.\n"
                f"Ve a *Mis Pedidos* → **Solicitar devolución**\n\n"
                f"**🔁 Cambio (por otro producto):**\n"
                f"También hasta **24 horas** después de recibido.\n"
                f"Elige un producto de valor similar.\n\n"
                f"**Motivos válidos:**\n"
                f"• Producto dañado o en mal estado\n"
                f"• Producto incompleto o incorrecto\n"
                f"• No corresponde a lo pedido\n\n"
                f"Para casos urgentes: {wa_lnk}"), None, True

    # ══════════════════════════════════════════════════════════════
    #  14. HABLAR CON AGENTE / ASESOR
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["agente","asesor","persona","humano","hablar con","hablar con alguien",
                              "necesito ayuda","necesito hablar","chat","en vivo","operador",
                              "atención","atencion","soporte","ayuda","help","asistencia",
                              "me puedes ayudar","alguien me ayude","quiero hablar","comunicar"]):
        return (f"💬 **Hablar con un agente en {nom}:**\n\n"
                f"¡Claro! Puedes chatear en vivo con nuestro equipo.\n\n"
                f"**¿Cómo hacerlo?**\n"
                f"👉 Toca el botón **💬 Agente** en los botones de abajo\n"
                f"👉 O ve a *💬 Chat con Agente* en el menú lateral\n\n"
                f"**Horario de atención en vivo:**\n"
                f"⏰ {hor}\n\n"
                f"También puedes escribirnos por {wa_lnk} 📲\n\n"
                f"*El chat en vivo lo atienden nuestros empleados directamente.*"), None, True

    # ══════════════════════════════════════════════════════════════
    #  15. COMPROBANTE DE PAGO
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["comprobante","foto del pago","captura","screenshot","evidencia",
                              "enviar comprobante","subir comprobante","donde envio","donde subo",
                              "cómo envío","como envio","pago ya hice","ya pagué","ya pague"]):
        return (f"📸 **¿Cómo enviar el comprobante?**\n\n"
                f"**Opción 1 — Desde la app (recomendado):**\n"
                f"Al hacer el pedido con Nequi o Daviplata,\n"
                f"la app te pide subir la foto del comprobante. 📸\n\n"
                f"**Opción 2 — Por WhatsApp:**\n"
                f"Envíalo a {wa_lnk}\n"
                f"Indica tu código de pedido en el mensaje.\n\n"
                f"✅ Una vez verificado, tu pedido será aprobado."), None, True

    # ══════════════════════════════════════════════════════════════
    #  16. PRODUCTOS ESPECÍFICOS (pan, leche, etc.)
    # ══════════════════════════════════════════════════════════════
    prod_match = buscar_prod(tl)
    if prod_match and len(tl.split()) <= 4:
        disponible = prod_match["cantidad"] > 0
        return (f"{'✅' if disponible else '❌'} **{prod_match['nombre']}**\n\n"
                f"{'📦 Disponible: **'+str(prod_match['cantidad'])+' '+str(prod_match.get('unidad','uds'))+'**' if disponible else '😔 En este momento está **agotado**'}\n"
                f"💰 Precio: **{fmt(prod_match['precio'])}** / {prod_match.get('unidad','u')}\n"
                f"{'🛒 ¡Agrégalo al carrito!' if disponible else '📲 Consulta reposición: '+wa_lnk}"), prod_match, True

    # ══════════════════════════════════════════════════════════════
    #  17. CONTACTO
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["contacto","teléfono","telefono","comunicar","whatsapp","llamar",
                              "escribir","numero","número","como los contacto","datos de contacto"]):
        return (f"📞 **Contacta con {nom}:**\n\n"
                f"📱 **Teléfono:** {tel}\n"
                f"💬 **WhatsApp:** {wa_lnk}\n"
                f"📍 **Dirección:** {dir_}\n"
                f"🏙️ {ciu}\n"
                f"⏰ {hor}\n\n"
                f"O habla con nuestro agente en vivo 👇"), None, True

    # ══════════════════════════════════════════════════════════════
    #  18. DESPEDIDAS
    # ══════════════════════════════════════════════════════════════
    if any(w in tl for w in ["gracias","perfecto","listo","ok","chevere","genial","excelente",
                              "chao","adiós","adios","bye","hasta","de nada","muy bien","entendido",
                              "claro","buenísimo","buenisimo","crack","gracias por todo"]):
        return (f"¡Con mucho gusto! 😊 Fue un placer atenderte.\n\n"
                f"Recuerda que **{nom}** está aquí para servirte.\n"
                f"¡Hasta pronto! 🌟\n\n"
                f"*Si necesitas algo más, vuelve cuando quieras* 👋"), None, True

    return None, None, False


# ──────────────────────────────────────────────────────────────────
#  ACCESOS RÁPIDOS (Chips)
# ──────────────────────────────────────────────────────────────────

BOT_QUICK = {
    "ver_productos":   "Muéstrame todos los productos disponibles con precios",
    "ver_stock":       "¿Qué productos tienen disponibles con stock?",
    "ver_agotados":    "¿Cuáles productos están agotados?",
    "ver_promos":      "¿Qué promociones o descuentos tienen activos?",
    "como_pagar":      "¿Cómo puedo pagar? ¿Qué métodos de pago tienen?",
    "info_pago":       "¿Cómo puedo pagar mi pedido?",
    "info_domi":       "¿Hacen domicilios? ¿Cuánto demora y cuánto cuesta?",
    "info_horario":    "¿Cuál es el horario y la dirección de la tienda?",
    "como_pedir":      "¿Cómo hago un pedido? Explícame los pasos",
    "estado_pedido":   "¿Cómo consulto el estado de mi pedido?",
    "cancelar_pedido": "¿Cómo cancelo mi pedido?",
    "devolucion":      "¿Cómo hago una devolución o cambio de producto?",
    "comprobante":     "¿Cómo envío el comprobante de pago?",
    "contacto":        "¿Cuál es el teléfono y WhatsApp para contactarlos?",
    "hablar_agente":   "Necesito hablar con un agente o asesor en vivo",
}

def _chips_html(tid):
    """Genera los chips compactos en una fila scrollable."""
    chips = [
        ("ver_productos","📦 Productos"),
        ("ver_stock","✅ Disponibles"),
        ("ver_agotados","❌ Agotados"),
        ("ver_promos","🎁 Promos"),
        ("como_pagar","💳 Pagar"),
        ("como_pedir","🛒 Cómo pedir"),
        ("info_domi","🏍️ Domicilios"),
        ("info_horario","🕐 Horario"),
        ("estado_pedido","📦 Mi pedido"),
        ("cancelar_pedido","❌ Cancelar"),
        ("devolucion","🔄 Devolución"),
        ("comprobante","📸 Comprobante"),
        ("contacto","📞 Contacto"),
    ]
    html = ""
    for k, lbl in chips:
        html += (f'<form method="post" style="display:contents">'
                 f'<input type="hidden" name="msg" value="{k}">'
                 f'<button type="submit" class="chip">{lbl}</button></form>')
    # Chip agente — siempre visible con estado
    try:
        ag = db_query("SELECT COUNT(*) as c FROM users WHERE tienda_id=%s AND rol='empleado'",
                      (tid,), fetchone=True)
        hay = ag and ag["c"] > 0
    except Exception:
        hay = False
    if hay:
        html += (f'<a href="/chat_cliente" class="chip chip-agent" '
                 f'style="border-width:2px;font-weight:800;animation:nb-pulse 2s infinite">'
                 f'💬 Agente 🟢</a>')
    else:
        html += f'<span class="chip" style="opacity:.55;cursor:default;color:#64748b">💬 Sin agentes</span>'
    return html


def bot_ia_respuesta(historial_msgs, contexto_tienda, productos, promos):
    """FAQ local primero; Claude API como respaldo."""
    import json as _json
    ultimo = ""
    for m in reversed(historial_msgs):
        if m["quien"] == "Tú":
            ultimo = m.get("texto_raw", m.get("texto",""))
            break

    texto, prod_obj, ok = _bot_faq(ultimo, contexto_tienda, productos, promos)
    if ok and texto:
        return texto, prod_obj

    # Claude API
    tel  = contexto_tienda.get("telefono","")
    wa   = contexto_tienda.get("whatsapp","").replace("+","").replace(" ","")
    nom  = contexto_tienda.get("nombre","la tienda")
    ciu  = contexto_tienda.get("ciudad","Fusagasugá")
    prods_txt = "\n".join(
        f"- {p['nombre']} | {fmt(p['precio'])} | Stock: {p['cantidad']} {p.get('unidad','')} | Cat: {p.get('categoria','')}"
        for p in productos) or "Sin productos."
    promos_txt = "\n".join(
        f"- {pr['titulo']}: {pr.get('descuento','')} — {pr.get('descripcion','')}"
        for pr in promos) or "Sin promociones."
    system = (f"Eres el asistente de '{nom}', tienda en {ciu}, Colombia. "
              f"Respondes en español colombiano amigable con emojis. Máx 3 párrafos.\n"
              f"Tel: {tel} | WA: {'+'+wa if wa else 'N/D'} | Horario: {contexto_tienda.get('horario','')}\n"
              f"PAGOS: Nequi {tel}, Daviplata {tel}, Efectivo.\n"
              f"TODOS LOS PRODUCTOS (incluye agotados):\n{prods_txt}\nPROMOS:\n{promos_txt}\n"
              f"NUNCA inventes precios. Si el stock es 0, dilo claramente. Si no sabes: 'Contáctanos'.")
    msgs = []
    for m in historial_msgs[-10:]:
        if m["quien"] == "Tú":
            msgs.append({"role":"user","content":m.get("texto_raw",m.get("texto",""))})
        elif m["quien"] == "Bot" and m.get("texto_raw"):
            msgs.append({"role":"assistant","content":m["texto_raw"]})
    if not msgs or msgs[-1]["role"] != "user":
        return f"¡Hola! 👋 Soy el asistente de {nom}. ¿En qué te ayudo? 😊", None
    try:
        payload = _json.dumps({"model":CLAUDE_MODEL,"max_tokens":600,
                               "system":system,"messages":msgs}).encode("utf-8")
        req = _ureq.Request("https://api.anthropic.com/v1/messages",data=payload,
                            headers={"Content-Type":"application/json","anthropic-version":"2023-06-01"},
                            method="POST")
        with _ureq.urlopen(req,timeout=15) as resp:
            data = _json.loads(resp.read())
            return data["content"][0]["text"], None
    except Exception:
        return (f"Disculpa, tengo un problema técnico 😓\n\n"
                f"Contáctanos: 📞 {tel} | 💬 {'+'+wa if wa else 'WhatsApp'}"), None

def _generar_opciones(texto, productos, promos):
    return []


# ──────────────────────────────────────────────────────────────────
#  FUNCIÓN BOT — INTERFAZ CELULAR ULTRA PREMIUM
# ──────────────────────────────────────────────────────────────────
import urllib.request as _ureq
import uuid as _uuid_mod

CLAUDE_MODEL = "claude-sonnet-4-20250514"


# ──────────────────────────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────────────────────────

def _hhmm():
    return datetime.now().strftime("%H:%M")

def _fmt_msg(txt):
    import html as _h
    txt = _h.escape(str(txt))
    txt = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', txt)
    txt = re.sub(r'\*([^*]+)\*',     r'<em>\1</em>',         txt)
    txt = txt.replace('\n','<br>')
    return txt

def _prod_card(p):
    """Card visual del producto."""
    if p.get("img"):
        img_h = (f'<img class="prod-card-img" src="{p["img"]}" loading="lazy" '
                 f'onerror="this.parentNode.innerHTML=\'<div class=prod-card-no-img>📦</div>\'">')
    else:
        img_h = '<div class="prod-card-no-img">📦</div>'
    disp = p.get("cantidad",0) > 0
    badge = (f'<span style="background:#dcfce7;color:#15803d;font-size:.63rem;'
             f'font-weight:800;padding:2px 8px;border-radius:10px">✅ Disponible</span>'
             if disp else
             f'<span style="background:#fef2f2;color:#dc2626;font-size:.63rem;'
             f'font-weight:800;padding:2px 8px;border-radius:10px">❌ Agotado</span>')
    return (f'<div class="prod-card-msg" onclick="window.open(\'/tienda\',\'_blank\')">'
            f'{img_h}'
            f'<div class="prod-card-info">'
            f'<div class="prod-card-name">{p["nombre"]}</div>'
            f'<div class="prod-card-price">{fmt(p["precio"])}'
            f'<span style="font-size:.7rem;color:#64748b"> / {p.get("unidad","u")}</span></div>'
            f'<div style="margin-top:4px">{badge}</div>'
            f'{"<div class=prod-card-stock>"+str(p.get("cantidad",0))+" "+str(p.get("unidad",""))+" disponibles</div>" if disp else ""}'
            f'</div></div>')


# ──────────────────────────────────────────────────────────────────
#  APRENDIZAJE — guardar y recuperar respuestas aprendidas
# ──────────────────────────────────────────────────────────────────

def _aprender(tid, pregunta, respuesta):
    """Guarda una buena respuesta para futuras consultas similares."""
    try:
        ex = db_query("SELECT id,veces_usada FROM bot_aprendizaje WHERE tienda_id=%s AND pregunta=%s",
                      (tid, pregunta[:500]), fetchone=True)
        if ex:
            db_query("UPDATE bot_aprendizaje SET veces_usada=%s WHERE id=%s",
                     (ex["veces_usada"]+1, ex["id"]), commit=True)
        else:
            db_query("INSERT INTO bot_aprendizaje(tienda_id,pregunta,respuesta,fecha) VALUES(%s,%s,%s,%s)",
                     (tid, pregunta[:500], respuesta[:2000], now()), commit=True)
    except Exception:
        pass

def _buscar_aprendido(tid, pregunta):
    """Busca si ya aprendimos una respuesta para esta pregunta."""
    try:
        tl = pregunta.lower().strip()
        rows = db_query("SELECT * FROM bot_aprendizaje WHERE tienda_id=%s AND util=1 ORDER BY veces_usada DESC LIMIT 50",
                        (tid,), fetchall=True) or []
        for r in rows:
            palabras_clave = [w for w in r["pregunta"].lower().split() if len(w) > 3]
            coincidencias = sum(1 for w in palabras_clave if w in tl)
            if coincidencias >= 2 and len(palabras_clave) > 0:
                ratio = coincidencias / len(palabras_clave)
                if ratio >= 0.5:
                    return r["respuesta"]
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────────────────────────
#  FAQ ULTRA COMPLETA CON PREGUNTAS ABIERTAS
# ──────────────────────────────────────────────────────────────────

def _bot_faq(msg, t, productos, promos):
    """
    Responde preguntas abiertas.
    Retorna: (texto, prod_obj_o_None, respondido_bool)
    """
    tl   = msg.lower().strip()
    tel  = t.get("telefono","")
    wa   = t.get("whatsapp","").replace("+","").replace(" ","")
    nom  = t.get("nombre","la tienda")
    ciu  = t.get("ciudad","Fusagasugá")
    hor  = t.get("horario","Consultar")
    dir_ = t.get("direccion","Consultar")
    wa_lnk = (f"<a href='https://wa.me/{wa}' target='_blank' "
              f"style='color:#4f46e5;font-weight:700'>WhatsApp +{wa}</a>") if wa else f"Tel: {tel}"
    disp_prods = [p for p in productos if p.get("cantidad",0) > 0]
    agot_prods = [p for p in productos if p.get("cantidad",0) <= 0]

    def primer_con_img():
        for p in disp_prods:
            if p.get("img"): return p
        return disp_prods[0] if disp_prods else None

    def buscar_prod(texto):
        """Búsqueda flexible de producto."""
        mejor = None; mejor_score = 0
        for p in productos:
            palabras = [w for w in p["nombre"].lower().split() if len(w) > 2]
            score = sum(1 for w in palabras if w in texto)
            if score > mejor_score:
                mejor_score = score; mejor = p
        return mejor if mejor_score > 0 else None

    # ── 1. SALUDOS ────────────────────────────────────────────────
    if any(w in tl for w in ["hola","buenas","hey","hi","buen","buenos","buenas","saludos","ey",
                              "que tal","quiubo","good","hello","¿cómo están","como estan"]):
        return (f"¡Hola! 👋 Bienvenido a **{nom}**.\n\n"
                f"Soy tu asistente con IA 🤖. Puedo ayudarte con:\n"
                f"📦 Productos y precios\n"
                f"✅ Stock disponible\n"
                f"💳 Métodos de pago\n"
                f"🏍️ Domicilios\n"
                f"🔄 Devoluciones\n"
                f"💬 Conectarte con un agente\n\n"
                f"Usa el menú de abajo o escríbeme directamente 😊"), None, True

    # ── 2. CATÁLOGO COMPLETO ──────────────────────────────────────
    if any(w in tl for w in ["producto","catalogo","catálogo","qué tienen","que hay","qué hay",
                              "disponible","ver todo","que venden","que tienen","menú","menu",
                              "lista","qué venden","tienes","tienen","muestrame","muéstrame",
                              "qué productos","que productos","inventario","ofrecen","manejan"]):
        if not disp_prods:
            return (f"😕 **{nom}** no tiene productos disponibles en este momento.\n\n"
                    f"Contáctanos por {wa_lnk} para saber cuándo habrá disponibilidad."), None, True
        txt = f"📦 **Catálogo de {nom}** ({len(disp_prods)} productos disponibles):\n\n"
        cats = {}
        for p in disp_prods:
            cat = p.get("categoria","General")
            cats.setdefault(cat,[]).append(p)
        for cat, ps in cats.items():
            txt += f"**{cat}:**\n"
            for p in ps[:8]:
                txt += f"  • {p['nombre']} — {fmt(p['precio'])} / {p.get('unidad','u')} ✅\n"
        if len(disp_prods) > 8:
            txt += f"\n_...y más productos en la tienda_ 🛒"
        return txt, primer_con_img(), True

    # ── 3. STOCK DISPONIBLE (específico o general) ────────────────
    if any(w in tl for w in ["stock","hay de","cuánto hay","cuanto hay","disponibilidad",
                              "existe","tienen disponible","quedan","cuántos quedan","cuantos quedan",
                              "hay pan","hay leche","hay pollo","tienen el","hay stock","queda algo",
                              "disponible el","disponible la","tienen el","tienen la"]):
        prod_m = buscar_prod(tl)
        if prod_m:
            disp = prod_m.get("cantidad",0) > 0
            return (f"{'✅' if disp else '❌'} **{prod_m['nombre']}**\n\n"
                    f"{'📦 Stock: **'+str(prod_m['cantidad'])+' '+str(prod_m.get('unidad','uds'))+'**' if disp else '😔 **Agotado** por el momento'}\n"
                    f"💰 Precio: **{fmt(prod_m['precio'])}** / {prod_m.get('unidad','u')}\n\n"
                    f"{'🛒 ¡Agrégalo al carrito!' if disp else '📲 Consulta reposición: '+wa_lnk}"), prod_m, True
        # Stock general
        if disp_prods:
            txt = f"✅ **Disponibles ahora en {nom} ({len(disp_prods)}):**\n\n"
            for p in disp_prods[:10]:
                txt += f"• **{p['nombre']}** — {p['cantidad']} {p.get('unidad','uds')} — {fmt(p['precio'])}\n"
            return txt, primer_con_img(), True
        return f"😕 No hay productos disponibles ahora. Contáctanos: {wa_lnk}", None, True

    # ── 4. AGOTADOS ───────────────────────────────────────────────
    if any(w in tl for w in ["agotado","agotados","sin stock","no hay","se acabó","se acabo",
                              "no tienen","no queda","terminó","termino","se acabaron","out of stock",
                              "cuándo llega","cuando llega","cuándo reponen","cuando reponen"]):
        prod_m = buscar_prod(tl)
        if prod_m and prod_m.get("cantidad",0) <= 0:
            return (f"❌ **{prod_m['nombre']}** está **agotado**.\n\n"
                    f"Para saber cuándo habrá disponibilidad:\n"
                    f"📲 Escríbenos: {wa_lnk}\n\n"
                    f"¿Quieres ver productos similares disponibles? 📦"), prod_m, True
        if agot_prods:
            txt = f"❌ **Productos agotados en {nom} ({len(agot_prods)}):**\n\n"
            for p in agot_prods[:6]: txt += f"• {p['nombre']}\n"
            txt += f"\n✅ Tenemos **{len(disp_prods)} productos disponibles**.\n"
            txt += f"Para reposiciones: {wa_lnk}"
            return txt, primer_con_img(), True
        return f"🎉 ¡Todos los productos de **{nom}** están disponibles!\n\n¡Aprovecha! 🛒", primer_con_img(), True

    # ── 5. PRECIO ESPECÍFICO ──────────────────────────────────────
    if any(w in tl for w in ["precio","cuánto cuesta","cuanto vale","cuánto vale","vale",
                              "cuesta","costo","cuanto es","cuánto","cuanto","tarifa","a cuánto",
                              "a cuanto","cuánto me sale","cuanto me sale","sale el","sale la"]):
        prod_m = buscar_prod(tl)
        if prod_m:
            disp = prod_m.get("cantidad",0) > 0
            return (f"🏷️ **{prod_m['nombre']}**\n\n"
                    f"💰 Precio: **{fmt(prod_m['precio'])}** / {prod_m.get('unidad','unidad')}\n"
                    f"{'✅ Disponible: '+str(prod_m['cantidad'])+' '+str(prod_m.get('unidad','uds')) if disp else '❌ Agotado por el momento'}\n"
                    f"🏷️ Categoría: {prod_m.get('categoria','General')}\n\n"
                    f"{'🛒 ¡Agrégalo al carrito!' if disp else '📲 Consulta reposición: '+wa_lnk}"), prod_m, True
        if disp_prods:
            txt = f"💰 **Lista de precios — {nom}:**\n\n"
            for p in disp_prods[:8]:
                txt += f"• **{p['nombre']}** → {fmt(p['precio'])} / {p.get('unidad','u')}\n"
            txt += f"\nEscribe el nombre del producto para ver detalles 📋"
            return txt, primer_con_img(), True
        return f"📋 Sin precios disponibles ahora. Consulta: {wa_lnk}", None, True

    # ── 6. PROMOCIONES ────────────────────────────────────────────
    if any(w in tl for w in ["promo","oferta","descuento","descuentos","especial","rebaja",
                              "barato","económico","hay promo","promo hoy","oferta hoy",
                              "qué ofertas","que ofertas","hay descuento","cupón","cupon","sale"]):
        if promos:
            txt = f"🎁 **¡Promociones activas en {nom}!**\n\n"
            for pr in promos[:5]:
                txt += (f"🔥 **{pr['titulo']}**\n"
                        f"   {pr.get('descuento','')} — {pr.get('descripcion','')}\n")
                if pr.get("hasta"): txt += f"   ⏰ Hasta: {pr['hasta']}\n"
                txt += "\n"
            txt += "¡No dejes pasar estas ofertas! 🛒"
        else:
            txt = (f"😊 No hay promociones especiales ahora.\n\n"
                   f"¡Pero en **{nom}** siempre tenemos los mejores precios!\n"
                   f"Pregúntame por algún producto 😉")
        return txt, primer_con_img(), True

    # ── 7. CÓMO PAGAR ─────────────────────────────────────────────
    if any(w in tl for w in ["pago","pagar","nequi","daviplata","efectivo","transferencia",
                              "como pago","formas de pago","metodo","método","cómo pago",
                              "como se paga","aceptan","reciben","pago online","consignacion",
                              "pago digital","pasarela","medios de pago"]):
        return (f"💳 **Métodos de pago en {nom}:**\n\n"
                f"📱 **Nequi**\n"
                f"   Número: **{tel or '(ver en tienda)'}**\n"
                f"   Transfiere → sube el comprobante ✅\n\n"
                f"💳 **Daviplata**\n"
                f"   Número: **{tel or '(ver en tienda)'}**\n"
                f"   Transfiere → adjunta el comprobante ✅\n\n"
                f"💵 **Efectivo**\n"
                f"   Pagas al recibir o en tienda. Sin pasos extra ✅\n\n"
                f"📸 El comprobante también por {wa_lnk}"), None, True

    # ── 8. COMPROBANTE ────────────────────────────────────────────
    if any(w in tl for w in ["comprobante","foto del pago","captura","screenshot","evidencia",
                              "enviar comprobante","subir comprobante","donde envio","donde subo",
                              "cómo envío","como envio","ya pagué","ya pague","hice el pago"]):
        return (f"📸 **¿Cómo enviar el comprobante?**\n\n"
                f"**Opción 1 — Desde la app (recomendado):**\n"
                f"Al hacer el pedido con Nequi o Daviplata,\n"
                f"la app te pide subir la foto. 📸\n\n"
                f"**Opción 2 — Por WhatsApp:**\n"
                f"Envíalo a {wa_lnk}\n"
                f"Incluye tu código de pedido.\n\n"
                f"✅ Una vez verificado, tu pedido será aprobado."), None, True

    # ── 9. CÓMO HACER UN PEDIDO ───────────────────────────────────
    if any(w in tl for w in ["cómo pido","como pido","hacer pedido","cómo compro","como compro",
                              "cómo se pide","proceso de compra","quiero comprar","quiero pedir",
                              "cómo funciona","pasos para","cómo lo hago","como lo hago"]):
        return (f"🛒 **Cómo hacer un pedido en {nom}:**\n\n"
                f"**1️⃣** Ve a **Tienda** en el menú lateral\n"
                f"**2️⃣** Elige productos → clic en **Agregar al carrito** 🛒\n"
                f"**3️⃣** Ve a tu carrito → **Confirmar compra**\n"
                f"**4️⃣** Elige método de pago (Nequi / Daviplata / Efectivo)\n"
                f"**5️⃣** Elige entre recoger en tienda o domicilio 🏍️\n"
                f"**6️⃣** Si pagaste digital → sube el comprobante 📸\n"
                f"**7️⃣** ¡Listo! Te avisamos cuando sea aprobado 🎉\n\n"
                f"¿Tienes alguna duda? Escríbeme 😊"), None, True

    # ── 10. DOMICILIOS ────────────────────────────────────────────
    if any(w in tl for w in ["domicilio","envío","envio","delivery","llevan","mandan","a domicilio",
                              "a mi casa","reparten","traen","cobran por domicilio","costo domicilio",
                              "precio domicilio","cuánto cobran","hacen envío","despachan","envían"]):
        return (f"🏍️ **Domicilios de {nom}:**\n\n"
                f"✅ Sí, hacemos domicilios en **{ciu}**\n"
                f"⏱️ Tiempo estimado: **30 – 60 minutos**\n"
                f"📦 Sin pedido mínimo\n"
                f"💰 Costo del domicilio: consultar por {wa_lnk}\n\n"
                f"**¿Cómo pedirlo?**\n"
                f"Al confirmar tu compra selecciona *🏍️ Domicilio*\n"
                f"e ingresa tu dirección de entrega 📍"), None, True

    # ── 11. HORARIO Y UBICACIÓN ───────────────────────────────────
    if any(w in tl for w in ["horario","hora","abre","cierra","cuando abren","cuándo abren",
                              "atienden","a qué hora","a que hora","ubicación","ubicacion",
                              "direccion","dirección","dónde","donde","llegar","están","estan",
                              "abiertos","local","sucursal","tienda física"]):
        return (f"🕐 **{nom} — Horario y Ubicación:**\n\n"
                f"⏰ **Horario:**\n{hor}\n\n"
                f"📍 **Dirección:**\n{dir_}\n\n"
                f"🏙️ **Ciudad:** {ciu}\n"
                f"📞 **Tel:** {tel}\n"
                f"💬 {wa_lnk}"), None, True

    # ── 12. ESTADO DEL PEDIDO ─────────────────────────────────────
    if any(w in tl for w in ["pedido","orden","estado","código","codigo","rastrear","seguimiento",
                              "donde esta","dónde está","cuándo llega","cuando llega","mi pedido",
                              "ver pedido","llegó","llego","entregaron","lo entregaron"]):
        return (f"📦 **¿Cómo ver tu pedido?**\n\n"
                f"**En la app:**\n"
                f"1️⃣ Inicia sesión\n"
                f"2️⃣ Ve a *📦 Mis Pedidos* en el menú\n"
                f"3️⃣ Verás el estado en tiempo real\n\n"
                f"**Estados:**\n"
                f"⏳ *Pendiente* → esperando aprobación\n"
                f"✅ *Aprobado* → siendo preparado\n"
                f"🏍️ *En camino* → ya va para donde estás\n"
                f"📦 *Entregado* → ¡llegó!\n"
                f"❌ *Cancelado* → fue cancelado\n\n"
                f"También consulta por {wa_lnk}"), None, True

    # ── 13. CANCELAR PEDIDO ───────────────────────────────────────
    if any(w in tl for w in ["cancelar","cancelo","cancelar pedido","no quiero","arrepentí",
                              "me equivoqué","anular","no lo quiero","deshacer pedido"]):
        return (f"❌ **¿Cómo cancelar tu pedido?**\n\n"
                f"Tienes **10 minutos** desde que hiciste el pedido.\n\n"
                f"**Pasos:**\n"
                f"1️⃣ Ve a *📦 Mis Pedidos*\n"
                f"2️⃣ Busca tu pedido\n"
                f"3️⃣ Toca el botón **❌ Cancelar**\n\n"
                f"⚠️ Si ya pasaron los 10 minutos:\n"
                f"Contáctanos por {wa_lnk}\n"
                f"y evaluamos cada caso con gusto 😊"), None, True

    # ── 14. DEVOLUCIONES Y CAMBIOS ────────────────────────────────
    if any(w in tl for w in ["devolución","devolucion","cambio","cambiar","reembolso",
                              "problema","dañado","roto","mal estado","no sirve","no era",
                              "diferente","incompleto","falta","vino mal","llegó mal",
                              "queja","reclamacion","politica de devolucion"]):
        return (f"🔄 **Devoluciones y Cambios en {nom}:**\n\n"
                f"**💸 Devolución (dinero de vuelta):**\n"
                f"Hasta **24 horas** después de recibido.\n"
                f"Ve a *Mis Pedidos* → **Solicitar devolución**\n\n"
                f"**🔁 Cambio (por otro producto):**\n"
                f"Hasta **24 horas** después de recibido.\n"
                f"Elige un producto de valor similar.\n\n"
                f"**Motivos válidos:**\n"
                f"• Producto dañado o en mal estado\n"
                f"• Producto incompleto o incorrecto\n"
                f"• No corresponde a lo pedido\n\n"
                f"Casos urgentes: {wa_lnk}"), None, True

    # ── 15. HABLAR CON AGENTE ─────────────────────────────────────
    if any(w in tl for w in ["agente","asesor","persona","humano","hablar con","hablar con alguien",
                              "necesito ayuda","necesito hablar","chat","en vivo","operador",
                              "atención","atencion","soporte","ayuda","help","asistencia",
                              "alguien me ayude","quiero hablar","comunicar","representante",
                              "servicio al cliente"]):
        return (f"💬 **Hablar con un agente en {nom}:**\n\n"
                f"¡Claro! Nuestros asesores están listos para ayudarte.\n\n"
                f"**¿Cómo conectarte?**\n"
                f"👉 Toca el botón **💬 Agente 🟢** en el menú de abajo\n"
                f"👉 O ve a **💬 Chat con Agente** en el menú lateral\n\n"
                f"**Horario de atención en vivo:**\n"
                f"⏰ {hor}\n\n"
                f"También por {wa_lnk} 📲\n\n"
                f"*⚡ El chat se cierra automáticamente tras 5 min de inactividad.*"), None, True

    # ── 16. CONTACTO ──────────────────────────────────────────────
    if any(w in tl for w in ["contacto","teléfono","telefono","comunicar","whatsapp","llamar",
                              "escribir","numero","número","datos de contacto","cómo los contacto"]):
        return (f"📞 **Contacta con {nom}:**\n\n"
                f"📱 Tel: **{tel}**\n"
                f"💬 WhatsApp: {wa_lnk}\n"
                f"📍 {dir_}\n"
                f"🏙️ {ciu}\n"
                f"⏰ {hor}\n\n"
                f"O habla con nuestro agente en vivo 👇"), None, True

    # ── 17. PRODUCTO DIRECTO (detectado por nombre) ───────────────
    prod_m = buscar_prod(tl)
    if prod_m and len(tl.split()) <= 5:
        disp = prod_m.get("cantidad",0) > 0
        return (f"{'✅' if disp else '❌'} **{prod_m['nombre']}**\n\n"
                f"{'📦 Disponible: **'+str(prod_m['cantidad'])+' '+str(prod_m.get('unidad','uds'))+'**' if disp else '😔 **Agotado** por el momento'}\n"
                f"💰 Precio: **{fmt(prod_m['precio'])}** / {prod_m.get('unidad','u')}\n"
                f"{'🛒 ¡Agrégalo al carrito!' if disp else '📲 Consulta reposición: '+wa_lnk}"), prod_m, True

    # ── 18. DESPEDIDAS ────────────────────────────────────────────
    if any(w in tl for w in ["gracias","perfecto","listo","ok","chevere","genial","excelente",
                              "chao","adiós","adios","bye","hasta","de nada","muy bien",
                              "entendido","claro","buenísimo","gracias por todo","que dios te"]):
        return (f"¡Con mucho gusto! 😊 Fue un placer atenderte.\n\n"
                f"Recuerda que **{nom}** está aquí para ti.\n"
                f"¡Hasta pronto! 🌟"), None, True

    return None, None, False


# ──────────────────────────────────────────────────────────────────
#  ACCESOS RÁPIDOS
# ──────────────────────────────────────────────────────────────────

BOT_QUICK = {
    "ver_catalogo":    "Muéstrame el catálogo completo de productos",
    "ver_disponibles": "¿Qué productos tienen disponibles con stock?",
    "ver_agotados":    "¿Cuáles productos están agotados?",
    "ver_promos":      "¿Qué promociones o descuentos tienen activos?",
    "como_pagar":      "¿Cómo puedo pagar? Métodos de pago disponibles",
    "como_pedir":      "¿Cómo hago un pedido? Explícame los pasos",
    "info_domi":       "¿Hacen domicilios? ¿Cuánto cuesta?",
    "info_horario":    "¿Cuál es el horario y la dirección?",
    "estado_pedido":   "¿Cómo consulto el estado de mi pedido?",
    "cancelar_pedido": "¿Cómo cancelo mi pedido?",
    "devolucion":      "¿Cómo hago una devolución o cambio?",
    "comprobante":     "¿Cómo envío el comprobante de pago?",
    "hablar_agente":   "Quiero hablar con un agente o asesor en vivo",
    "contacto":        "¿Cuál es el teléfono y WhatsApp?",
}

# Menú vertical ordenado por categorías
MENU_VERTICAL = [
    ("🏷️ Productos","seccion","",False),
    ("📦 Ver catálogo completo","ver_catalogo","",True),
    ("✅ Productos disponibles","ver_disponibles","",True),
    ("❌ Productos agotados","ver_agotados","",True),
    ("🎁 Promociones activas","ver_promos","",True),
    ("💰 Pagos","seccion","",False),
    ("💳 Métodos de pago","como_pagar","",True),
    ("📸 Enviar comprobante","comprobante","",True),
    ("🛒 Pedidos","seccion","",False),
    ("🛒 Cómo hacer un pedido","como_pedir","",True),
    ("📦 Estado de mi pedido","estado_pedido","",True),
    ("❌ Cancelar pedido","cancelar_pedido","",True),
    ("🔄 Devoluciones y cambios","devolucion","",True),
    ("🚚 Entrega","seccion","",False),
    ("🏍️ Info domicilios","info_domi","",True),
    ("🕐 Horario y ubicación","info_horario","",True),
    ("💬 Soporte","seccion","",False),
    ("💬 Hablar con agente","hablar_agente","",True),
    ("📞 Contacto","contacto","",True),
]


def bot_ia_respuesta(tid, historial_msgs, contexto_tienda, productos, promos):
    """FAQ → Aprendizaje guardado → Claude API."""
    import json as _json
    ultimo = ""
    for m in reversed(historial_msgs):
        if m["quien"] == "Tú":
            ultimo = m.get("texto_raw", m.get("texto",""))
            break

    # 1. FAQ local
    texto, prod_obj, ok = _bot_faq(ultimo, contexto_tienda, productos, promos)
    if ok and texto:
        return texto, prod_obj

    # 2. Respuesta aprendida de conversaciones previas
    aprendido = _buscar_aprendido(tid, ultimo)
    if aprendido:
        return aprendido, None

    # 3. Claude API
    tel  = contexto_tienda.get("telefono","")
    wa   = contexto_tienda.get("whatsapp","").replace("+","").replace(" ","")
    nom  = contexto_tienda.get("nombre","la tienda")
    ciu  = contexto_tienda.get("ciudad","Fusagasugá")
    prods_txt = "\n".join(
        f"- {p['nombre']} | {fmt(p['precio'])} | Stock: {p['cantidad']} {p.get('unidad','')} | {p.get('categoria','')}"
        for p in productos) or "Sin productos."
    promos_txt = "\n".join(
        f"- {pr['titulo']}: {pr.get('descuento','')} — {pr.get('descripcion','')}"
        for pr in promos) or "Sin promociones."
    system = (f"Eres el asistente de '{nom}', tienda en {ciu}, Colombia. "
              f"Respondes en español colombiano amigable con emojis. Máx 3 párrafos.\n"
              f"Tel: {tel} | WA: {'+'+wa if wa else 'N/D'} | Horario: {contexto_tienda.get('horario','')}\n"
              f"PAGOS: Nequi {tel}, Daviplata {tel}, Efectivo.\n"
              f"PRODUCTOS:\n{prods_txt}\nPROMOS:\n{promos_txt}\n"
              f"Si el stock es 0, dilo claramente. NUNCA inventes precios.")
    msgs = []
    for m in historial_msgs[-12:]:
        if m["quien"] == "Tú":
            msgs.append({"role":"user","content":m.get("texto_raw",m.get("texto",""))})
        elif m["quien"] == "Bot" and m.get("texto_raw"):
            msgs.append({"role":"assistant","content":m["texto_raw"]})
    if not msgs or msgs[-1]["role"] != "user":
        return f"¡Hola! 👋 Bienvenido a {nom}. ¿En qué te ayudo? 😊", None
    try:
        payload = _json.dumps({"model":CLAUDE_MODEL,"max_tokens":700,
                               "system":system,"messages":msgs}).encode("utf-8")
        req = _ureq.Request("https://api.anthropic.com/v1/messages",data=payload,
                            headers={"Content-Type":"application/json","anthropic-version":"2023-06-01"},
                            method="POST")
        with _ureq.urlopen(req,timeout=15) as resp:
            data = _json.loads(resp.read())
            resp_text = data["content"][0]["text"]
            # Guardar para aprender
            _aprender(tid, ultimo, resp_text)
            return resp_text, None
    except Exception:
        return (f"Disculpa, tengo un problema técnico 😓\n\n"
                f"Contáctanos: 📞 {tel} | 💬 {'+'+wa if wa else 'WhatsApp'}"), None

def _generar_opciones(texto, productos, promos):
    return []


# ──────────────────────────────────────────────────────────────────
#  FUNCIÓN BOT — CELULAR CON MENÚ VERTICAL
# ──────────────────────────────────────────────────────────────────

@app.route("/bot", methods=["GET","POST"])
def bot():
    if not li(): return redirect("/")
    if request.args.get("clear"):
        session.pop("bot_hist", None)
        return redirect("/bot")
    tid    = tid_now()
    prods  = db_query("SELECT * FROM productos WHERE tienda_id=%s ORDER BY cantidad DESC,nombre",
                      (tid,), fetchall=True) or []
    promos = db_query("SELECT * FROM promociones WHERE tienda_id=%s AND activa=1 AND (hasta IS NULL OR hasta>=%s)",
                      (tid,hoy()), fetchall=True) or []
    t      = get_tienda()
    hist   = session.get("bot_hist",[])
    mostrar_menu = request.args.get("menu","") == "1" or not hist

    if request.method == "POST":
        msg_raw = request.form.get("msg","").strip()
        if msg_raw:
            msg_show = BOT_QUICK.get(msg_raw, msg_raw)
            hist.append({"quien":"Tú","texto":msg_show,"prod":None,
                         "hora":_hhmm(),"texto_raw":msg_show})
            resp_txt, prod_obj = bot_ia_respuesta(tid, hist, t, prods, promos)
            prod_data = None
            if prod_obj:
                prod_data = {"nombre":prod_obj["nombre"],
                             "precio":float(prod_obj["precio"]),
                             "cantidad":prod_obj.get("cantidad",0),
                             "unidad":prod_obj.get("unidad",""),
                             "img":prod_obj.get("img",""),
                             "categoria":prod_obj.get("categoria","")}
            hist.append({"quien":"Bot","texto":resp_txt,"prod":prod_data,
                         "hora":_hhmm(),"texto_raw":resp_txt})
            session["bot_hist"] = hist[-40:]
            mostrar_menu = False

    if not hist:
        nom = t.get("nombre","la tienda")
        bienvenida = (f"¡Hola! 👋 Soy el asistente de **{nom}**.\n\n"
                      f"Soy una IA que aprende de cada conversación.\n"
                      f"Pregúntame lo que quieras o usa el menú 👇")
        hist = [{"quien":"Bot","texto":bienvenida,"prod":None,
                 "hora":_hhmm(),"texto_raw":bienvenida}]
        session["bot_hist"] = hist

    # ── Construir burbujas ─────────────────────────────────────────
    msgs_html = ""
    for m in hist:
        hora = m.get("hora",_hhmm())
        if m["quien"] == "Tú":
            msgs_html += (
                f'<div class="chat-row-r">'
                f'<div class="chat-bub-r">{_fmt_msg(m["texto"])}</div>'
                f'<div class="chat-meta-r">{hora} <span class="check-icon">✓✓</span></div>'
                f'</div>')
        else:
            card_html = _prod_card(m["prod"]) if m.get("prod") else ""
            msgs_html += (
                f'<div class="chat-row-l">'
                f'<div class="chat-av-l bot-av">🤖</div>'
                f'<div>'
                f'<div class="chat-bub-l">{_fmt_msg(m["texto"])}{card_html}</div>'
                f'<div class="chat-meta-l">{hora}</div>'
                f'</div></div>')

    # ── Menú vertical ──────────────────────────────────────────────
    hay_agente = False
    try:
        ag = db_query("SELECT COUNT(*) as c FROM users WHERE tienda_id=%s AND rol='empleado'",
                      (tid,), fetchone=True)
        hay_agente = ag and ag["c"] > 0
    except Exception:
        pass

    menu_html = ""
    if mostrar_menu:
        menu_items = ""
        for label, key, _, es_btn in MENU_VERTICAL:
            if not es_btn:
                # Separador de sección
                menu_items += (f'<div style="font-size:.65rem;font-weight:800;color:var(--mt);'
                               f'text-transform:uppercase;letter-spacing:.09em;'
                               f'padding:10px 14px 4px;border-top:1px solid #e5e7eb;margin-top:4px">'
                               f'{label}</div>')
            else:
                menu_items += (f'<form method="post" style="display:block;padding:2px 8px">'
                               f'<input type="hidden" name="msg" value="{key}">'
                               f'<button type="submit" style="width:100%;text-align:left;'
                               f'background:transparent;border:none;padding:8px 8px;'
                               f'border-radius:8px;cursor:pointer;font-family:inherit;'
                               f'font-size:.82rem;color:#1e293b;font-weight:500;'
                               f'transition:.15s;display:flex;align-items:center;gap:8px">'
                               f'<span style="font-size:.9rem">{label.split()[0]}</span>'
                               f'<span>{" ".join(label.split()[1:])}</span>'
                               f'</button></form>')
        # Agente al final
        if hay_agente:
            menu_items += (
                f'<div style="padding:8px 8px">'
                f'<a href="/chat_cliente" style="display:flex;align-items:center;gap:8px;'
                f'background:linear-gradient(135deg,#059669,#0ea5e9);border-radius:10px;'
                f'padding:10px 12px;text-decoration:none;animation:nb-pulse 2s infinite">'
                f'<span style="font-size:1.1rem">💬</span>'
                f'<div><div style="color:#fff;font-size:.82rem;font-weight:800">Agente en línea 🟢</div>'
                f'<div style="color:rgba(255,255,255,.8);font-size:.68rem">Habla con nosotros ahora</div>'
                f'</div></a></div>')
        menu_html = (
            f'<div style="background:#fff;border-top:1px solid #e5e7eb;'
            f'overflow-y:auto;max-height:260px;flex-shrink:0">'
            f'{menu_items}'
            f'</div>')
    else:
        # Solo chips horizontales cuando no hay menú
        wa = t.get("whatsapp","").replace("+","").replace(" ","")
        chips = [("ver_catalogo","📦 Catálogo"),("ver_disponibles","✅ Disponibles"),
                 ("ver_agotados","❌ Agotados"),("ver_promos","🎁 Promos"),
                 ("como_pagar","💳 Pagar"),("info_domi","🏍️ Domicilio"),
                 ("estado_pedido","📦 Pedido"),("devolucion","🔄 Devolver")]
        chips_h = "".join(
            f'<form method="post" style="display:contents">'
            f'<input type="hidden" name="msg" value="{k}">'
            f'<button type="submit" class="chip">{lbl}</button></form>'
            for k,lbl in chips)
        if hay_agente:
            chips_h += (f'<a href="/chat_cliente" class="chip chip-agent" '
                        f'style="animation:nb-pulse 2s infinite">💬 Agente 🟢</a>')
        if wa:
            chips_h += f'<a href="https://wa.me/{wa}" target="_blank" class="chip chip-wa">💬 WhatsApp</a>'
        menu_html = (f'<div class="chips-section">'
                     f'<div class="chips-label">Accesos rápidos →</div>'
                     f'<div class="chips-row">{chips_h}</div>'
                     f'</div>')

    t_nom = t.get("nombre","")
    wa    = t.get("whatsapp","").replace("+","").replace(" ","")

    return base("🤖 Asistente Virtual",(
        f'<div class="phone-outer">'
        f'<div class="phone-device">'
        # Notch
        f'<div class="phone-notch">'
        f'<div class="phone-pill"><div class="phone-cam"></div><div class="phone-speaker"></div></div>'
        f'</div>'
        # Barra superior
        f'<div class="phone-bar bot-bar">'
        f'<div class="phone-bar-left">'
        f'<div class="phone-avatar">🤖</div>'
        f'<div>'
        f'<div class="phone-info-name">Asistente — {t_nom}</div>'
        f'<div class="phone-info-status"><div class="phone-status-dot"></div>IA · En línea 24/7</div>'
        f'</div></div>'
        f'<div class="phone-bar-actions">'
        f'<a href="/bot?menu=1" class="phone-bar-btn" title="Ver menú">☰ Menú</a>'
        f'<a href="/bot?clear=1" class="phone-bar-btn">🔄</a>'
        f'</div></div>'
        # Mensajes
        f'<div class="phone-msgs" id="chat-box">{msgs_html}</div>'
        # Menú o chips
        + menu_html +
        # Input
        f'<form method="post" id="bform" style="display:contents">'
        f'<div class="phone-input-bar">'
        f'<input type="text" name="msg" class="phone-input" id="binput" '
        f'placeholder="Escribe o elige del menú..." autocomplete="off">'
        f'<button type="submit" class="phone-send send-bot">'
        f'<svg width="16" height="16" viewBox="0 0 24 24" fill="white">'
        f'<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>'
        f'</button></div></form>'
        f'</div></div>'  # phone-device / phone-outer
        f'<p style="font-size:.7rem;color:var(--mt);text-align:center;margin-top:14px">'
        f'🤖 IA que aprende · {t_nom}</p>'
        f'<script>'
        f'var cb=document.getElementById("chat-box");'
        f'if(cb)cb.scrollTop=cb.scrollHeight;'
        # Hover en botones del menú vertical
        f'document.querySelectorAll(".phone-device button[type=submit]").forEach(function(b){{'
        f'  if(b.style.width==="100%"){{'
        f'    b.addEventListener("mouseenter",function(){{this.style.background="#f0f4ff";this.style.color="#4f46e5";}});'
        f'    b.addEventListener("mouseleave",function(){{this.style.background="transparent";this.style.color="#1e293b";}});'
        f'  }}'
        f'}});'
        f'document.getElementById("bform").addEventListener("submit",function(){{'
        f'  setTimeout(function(){{if(cb)cb.scrollTop=cb.scrollHeight;}},200);'
        f'}});'
        f'</script>'))

#  El bloque incluye: /chat_cliente + /agente_chat + /chat_api
# ================================================================

CHAT_TIMEOUT_MINUTOS = 5  # Inactividad para cerrar automáticamente


def _cerrar_sesiones_inactivas(tid):
    """Cierra sesiones inactivas por más de 5 minutos."""
    try:
        limite = (datetime.now() - timedelta(minutes=CHAT_TIMEOUT_MINUTOS)).strftime("%Y-%m-%d %H:%M:%S")
        # Obtener sesiones activas inactivas
        ses_inactivas = db_query(
            "SELECT sesion_id,cliente FROM chat_sesiones "
            "WHERE tienda_id=%s AND estado='activo' AND ultima_actividad<%s",
            (tid, limite), fetchall=True) or []
        for s in ses_inactivas:
            # Insertar mensaje de cierre automático
            db_query("INSERT INTO chat_live(tienda_id,sesion_id,cliente,mensaje,de_quien,leido,fecha) "
                     "VALUES(%s,%s,%s,'__TIMEOUT__','sistema',1,%s)",
                     (tid, s["sesion_id"], s["cliente"], now()), commit=True)
            db_query("UPDATE chat_sesiones SET estado='cerrado',cerrada=%s WHERE sesion_id=%s",
                     (now(), s["sesion_id"]), commit=True)
    except Exception:
        pass


def _actualizar_actividad(tid, sid, usuario):
    """Actualiza la marca de última actividad de la sesión."""
    try:
        ex = db_query("SELECT id FROM chat_sesiones WHERE sesion_id=%s", (sid,), fetchone=True)
        if ex:
            db_query("UPDATE chat_sesiones SET ultima_actividad=%s WHERE sesion_id=%s",
                     (now(), sid), commit=True)
        else:
            db_query("INSERT INTO chat_sesiones(tienda_id,sesion_id,cliente,estado,ultima_actividad) "
                     "VALUES(%s,%s,%s,'activo',%s)",
                     (tid, sid, usuario, now()), commit=True)
    except Exception:
        pass


@app.route("/chat_cliente", methods=["GET","POST"])
def chat_cliente():
    """
    Chat del cliente con agente.
    - Conversación persiste aunque el usuario salga de la página.
    - Se cierra automáticamente tras 5 minutos de inactividad.
    - El cliente o el agente pueden cerrar manualmente.
    """
    if not is_cl(): return redirect("/bot")
    tid = tid_now()
    u   = session.get("user","")

    # Cerrar sesiones inactivas de esta tienda
    _cerrar_sesiones_inactivas(tid)

    # Recuperar o crear sesión persistente
    # (se guarda en session de Flask; si vuelve a entrar recupera la misma)
    sid = session.get("chat_sid","")
    if sid:
        # Verificar que la sesión siga activa en BD
        ses = db_query("SELECT * FROM chat_sesiones WHERE sesion_id=%s AND estado='activo'",
                       (sid,), fetchone=True)
        if not ses:
            sid = ""  # La sesión fue cerrada o expiró
    if not sid:
        sid = str(_uuid_mod.uuid4())[:16]
        session["chat_sid"] = sid

    # Cerrar manualmente
    if request.args.get("cerrar"):
        db_query("INSERT INTO chat_live(tienda_id,sesion_id,cliente,mensaje,de_quien,leido,fecha) "
                 "VALUES(%s,%s,%s,'__CERRADO__','cliente',1,%s)",
                 (tid, sid, u, now()), commit=True)
        db_query("UPDATE chat_sesiones SET estado='cerrado',cerrada=%s WHERE sesion_id=%s",
                 (now(), sid), commit=True)
        session.pop("chat_sid", None)
        return redirect("/bot")

    if request.method == "POST":
        msg = request.form.get("msg","").strip()
        if msg:
            db_query("INSERT INTO chat_live(tienda_id,sesion_id,cliente,mensaje,de_quien,leido,fecha) "
                     "VALUES(%s,%s,%s,%s,'cliente',0,%s)",
                     (tid, sid, u, msg, now()), commit=True)
            db_query("INSERT INTO notificaciones(tienda_id,mensaje,leida,fecha) VALUES(%s,%s,0,%s)",
                     (tid, f"💬 {u}: {msg[:50]}", now()), commit=True)
            _actualizar_actividad(tid, sid, u)

    # Marcar mensajes del agente como leídos
    db_query("UPDATE chat_live SET leido=1 WHERE tienda_id=%s AND sesion_id=%s AND de_quien='agente'",
             (tid, sid), commit=True)

    msgs = db_query("SELECT * FROM chat_live WHERE tienda_id=%s AND sesion_id=%s ORDER BY id ASC LIMIT 100",
                    (tid, sid), fetchall=True) or []

    # Verificar si fue cerrado (por agente, timeout, o el mismo cliente)
    especiales = {"__CERRADO__","__TIMEOUT__"}
    cerrado = any(m.get("mensaje") in especiales for m in msgs)
    timeout = any(m.get("mensaje")=="__TIMEOUT__" for m in msgs)
    if cerrado:
        session.pop("chat_sid", None)
        msg_cierre = ("⏰ La sesión fue cerrada por inactividad (5 min)."
                      if timeout else "✅ La conversación fue cerrada.")
        return redirect(f"/bot?chat_msg={msg_cierre}")

    _actualizar_actividad(tid, sid, u)

    t = get_tienda()
    ultimo_agente = next((m for m in reversed(msgs) if m["de_quien"]=="agente"), None)

    msgs_vis = [m for m in msgs if m.get("mensaje") not in especiales]
    msgs_html = ""
    if not msgs_vis:
        msgs_html = (f'<div class="chat-row-l">'
                     f'<div class="chat-av-l agent-av">👤</div>'
                     f'<div><div class="chat-bub-l">¡Hola {u}! 👋 Estoy aquí para ayudarte.<br>'
                     f'Escribe tu mensaje y te respondo pronto 😊</div>'
                     f'<div class="chat-meta-l">{_hhmm()}</div></div></div>')
    for m in msgs_vis:
        hora = str(m.get("fecha",""))[-5:] or _hhmm()
        if m["de_quien"] == "cliente":
            msgs_html += (f'<div class="chat-row-r">'
                          f'<div class="chat-bub-r green-bub">{_fmt_msg(m["mensaje"])}</div>'
                          f'<div class="chat-meta-r">{hora} <span class="check-icon">✓✓</span></div>'
                          f'</div>')
        else:
            ag = m.get("agente","Agente") or "Agente"
            msgs_html += (f'<div class="chat-row-l">'
                          f'<div class="chat-av-l agent-av">👤</div>'
                          f'<div><div class="chat-bub-l">'
                          f'<div class="chat-sender">{ag}</div>'
                          f'{_fmt_msg(m["mensaje"])}</div>'
                          f'<div class="chat-meta-l">{hora}</div>'
                          f'</div></div>')

    # Tiempo de inactividad restante (para mostrar al usuario)
    try:
        ses_info = db_query("SELECT ultima_actividad FROM chat_sesiones WHERE sesion_id=%s", (sid,), fetchone=True)
        if ses_info and ses_info.get("ultima_actividad"):
            act = ses_info["ultima_actividad"]
            if isinstance(act, str):
                act = datetime.strptime(act, "%Y-%m-%d %H:%M:%S")
            diff = (datetime.now() - act).total_seconds()
            restante = max(0, int(CHAT_TIMEOUT_MINUTOS * 60 - diff))
            mins = restante // 60; segs = restante % 60
            inact_txt = f"⏱ Cierre por inactividad en {mins}:{segs:02d}"
        else:
            inact_txt = f"⏱ Cierre automático tras {CHAT_TIMEOUT_MINUTOS} min sin actividad"
    except Exception:
        inact_txt = f"⏱ Cierre automático tras {CHAT_TIMEOUT_MINUTOS} min sin actividad"

    estado_dot = "#4ade80" if ultimo_agente else "#fbbf24"
    estado_txt = ("✅ Agente respondió" if ultimo_agente else "⏳ Esperando agente...")

    return base("💬 Chat con Agente",(
        f'<div class="phone-outer">'
        f'<div class="phone-device">'
        f'<div class="phone-notch">'
        f'<div class="phone-pill"><div class="phone-cam"></div><div class="phone-speaker"></div></div>'
        f'</div>'
        # Barra agente
        f'<div class="phone-bar agent-bar">'
        f'<div class="phone-bar-left">'
        f'<div class="phone-avatar">👤</div>'
        f'<div>'
        f'<div class="phone-info-name">Agente — {t.get("nombre","")}</div>'
        f'<div class="phone-info-status">'
        f'<div class="phone-status-dot" style="background:{estado_dot}"></div>'
        f'{estado_txt}</div></div></div>'
        f'<div class="phone-bar-actions">'
        f'<a href="/bot" class="phone-bar-btn">🤖 Bot</a>'
        f'<a href="/chat_cliente?cerrar=1" class="phone-bar-btn danger" '
        f'onclick="return confirm(\'¿Cerrar esta conversación?\')">✕ Cerrar</a>'
        f'</div></div>'
        # Aviso de timeout
        f'<div style="background:#fffbeb;border-bottom:1px solid #fde68a;'
        f'padding:6px 14px;font-size:.71rem;color:#92400e;'
        f'display:flex;align-items:center;gap:6px;flex-shrink:0">'
        f'<span>⏱</span><span id="timeout-txt">{inact_txt}</span>'
        f'</div>'
        # Mensajes
        f'<div class="phone-msgs" id="chat-box">{msgs_html}</div>'
        # Input
        f'<form method="post" id="cform" style="display:contents">'
        f'<div class="phone-input-bar">'
        f'<input type="text" name="msg" class="phone-input" id="cinput" '
        f'placeholder="Escribe tu mensaje..." autocomplete="off">'
        f'<button type="submit" class="phone-send send-agent">'
        f'<svg width="16" height="16" viewBox="0 0 24 24" fill="white">'
        f'<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>'
        f'</button></div></form>'
        f'</div></div>'
        f'<p style="font-size:.7rem;color:var(--mt);text-align:center;margin-top:14px">'
        f'💬 Chat en vivo · Toca ✕ Cerrar cuando termines</p>'
        f'<script>'
        f'var cb=document.getElementById("chat-box");if(cb)cb.scrollTop=cb.scrollHeight;'
        # Auto-refresh solo si input vacío (no interrumpe escritura)
        f'var lastActivity=Date.now();'
        f'var timeoutMs={CHAT_TIMEOUT_MINUTOS*60*1000};'
        f'var ar=setInterval(function(){{'
        f'  var i=document.getElementById("cinput");'
        f'  if(i&&i.value==="")window.location.reload();'
        f'}},4000);'
        # Contador de inactividad en tiempo real
        f'var totalSecs={CHAT_TIMEOUT_MINUTOS*60};'
        f'var ctr=setInterval(function(){{'
        f'  totalSecs--;'
        f'  if(totalSecs<=0){{clearInterval(ctr);window.location.reload();return;}}'
        f'  var m=Math.floor(totalSecs/60);var s=totalSecs%60;'
        f'  var el=document.getElementById("timeout-txt");'
        f'  if(el)el.textContent="⏱ Cierre por inactividad en "+m+":"+(s<10?"0":"")+s;'
        f'}},1000);'
        # Reiniciar contador al escribir
        f'document.getElementById("cform").addEventListener("submit",function(){{'
        f'  clearInterval(ar);clearInterval(ctr);totalSecs={CHAT_TIMEOUT_MINUTOS*60};'
        f'  setTimeout(function(){{window.location.reload();}},600);'
        f'}});'
        f'document.getElementById("cinput").addEventListener("input",function(){{'
        f'  totalSecs={CHAT_TIMEOUT_MINUTOS*60};'
        f'}});'
        f'</script>'))


@app.route("/agente_chat", methods=["GET","POST"])
def agente_chat():
    """
    Panel del agente (empleado).
    - Ve todas las conversaciones activas.
    - Conversaciones persisten aunque el cliente salga.
    - Cierre manual o por 5 min de inactividad del cliente.
    """
    if not is_st(): return redirect("/")
    if is_ad(): return redirect("/admin")
    tid     = tid_now()
    u_agen  = session.get("user","")

    # Cerrar sesiones inactivas
    _cerrar_sesiones_inactivas(tid)

    if request.method == "POST":
        ac        = request.form.get("ac","msg")
        sid_r     = request.form.get("sid","")
        cliente_r = request.form.get("cliente","")
        if ac == "msg":
            msg_r = request.form.get("msg","").strip()
            if msg_r and sid_r:
                db_query("INSERT INTO chat_live(tienda_id,sesion_id,cliente,agente,mensaje,de_quien,leido,fecha) "
                         "VALUES(%s,%s,%s,%s,%s,'agente',1,%s)",
                         (tid, sid_r, cliente_r, u_agen, msg_r, now()), commit=True)
                db_query("UPDATE chat_live SET leido=1 "
                         "WHERE tienda_id=%s AND sesion_id=%s AND de_quien='cliente'",
                         (tid, sid_r), commit=True)
                _actualizar_actividad(tid, sid_r, cliente_r)
        elif ac == "cerrar" and sid_r:
            db_query("INSERT INTO chat_live(tienda_id,sesion_id,cliente,mensaje,de_quien,leido,fecha) "
                     "VALUES(%s,%s,%s,'__CERRADO__','agente',1,%s)",
                     (tid, sid_r, cliente_r, now()), commit=True)
            db_query("UPDATE chat_sesiones SET estado='cerrado',cerrada=%s WHERE sesion_id=%s",
                     (now(), sid_r), commit=True)

    # Sesiones activas
    sesiones = db_query(
        "SELECT cs.*,"
        "SUM(CASE WHEN cl.de_quien='cliente' AND cl.leido=0 THEN 1 ELSE 0 END) as noleidos "
        "FROM chat_sesiones cs "
        "LEFT JOIN chat_live cl ON cs.sesion_id=cl.sesion_id AND cl.tienda_id=cs.tienda_id "
        "WHERE cs.tienda_id=%s AND cs.estado='activo' "
        "GROUP BY cs.sesion_id ORDER BY cs.ultima_actividad DESC",
        (tid,), fetchall=True) or []

    # También mostrar sesiones cerradas recientes (última hora)
    cerradas = db_query(
        "SELECT * FROM chat_sesiones WHERE tienda_id=%s AND estado='cerrado' "
        "AND cerrada>=%s ORDER BY cerrada DESC LIMIT 5",
        (tid, (datetime.now()-timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")),
        fetchall=True) or []

    sid_sel    = request.args.get("sid","")
    if not sid_sel and sesiones:
        sid_sel = sesiones[0]["sesion_id"]

    msgs_sel   = []
    cliente_sel= ""
    cerrado_sel= False
    timeout_sel= False
    if sid_sel:
        msgs_sel = db_query("SELECT * FROM chat_live WHERE tienda_id=%s AND sesion_id=%s ORDER BY id ASC",
                            (tid, sid_sel), fetchall=True) or []
        if msgs_sel: cliente_sel = msgs_sel[0]["cliente"]
        especiales = {"__CERRADO__","__TIMEOUT__"}
        cerrado_sel = any(m.get("mensaje") in especiales for m in msgs_sel)
        timeout_sel = any(m.get("mensaje")=="__TIMEOUT__" for m in msgs_sel)
        db_query("UPDATE chat_live SET leido=1 "
                 "WHERE tienda_id=%s AND sesion_id=%s AND de_quien='cliente'",
                 (tid, sid_sel), commit=True)

    total_nl = sum(int(s.get("noleidos",0)) for s in sesiones)

    # ── Sidebar sesiones ─────────────────────────────────────────
    ses_html = ""
    if sesiones:
        ses_html += f'<div style="font-size:.65rem;font-weight:800;color:var(--mt);text-transform:uppercase;letter-spacing:.08em;padding:8px 12px 4px">Activas ({len(sesiones)})</div>'
        for s in sesiones:
            nl   = int(s.get("noleidos",0))
            esel = (s["sesion_id"] == sid_sel)
            badge= f'<span class="session-badge">{nl}</span>' if nl else ""
            av_c = "active-av" if esel else ""
            # Tiempo de inactividad
            try:
                act = s.get("ultima_actividad",now())
                if isinstance(act,str): act=datetime.strptime(act,"%Y-%m-%d %H:%M:%S")
                diff = int((datetime.now()-act).total_seconds())
                rest = max(0, CHAT_TIMEOUT_MINUTOS*60-diff)
                t_txt = f"⏱ {rest//60}:{rest%60:02d}" if rest > 0 else "⚠ Por cerrar"
            except Exception:
                t_txt = ""
            ses_html += (f'<a href="/agente_chat?sid={s["sesion_id"]}" '
                         f'class="session-item {"active" if esel else ""}">'
                         f'<div class="session-av {av_c}">👤</div>'
                         f'<div class="session-info">'
                         f'<div class="session-name">{s["cliente"]}</div>'
                         f'<div class="session-last">{t_txt}</div>'
                         f'</div>{badge}</a>')
    if cerradas:
        ses_html += f'<div style="font-size:.65rem;font-weight:800;color:var(--mt);text-transform:uppercase;letter-spacing:.08em;padding:8px 12px 4px;border-top:1px solid var(--bd);margin-top:8px">Cerradas recientes</div>'
        for s in cerradas:
            esel = (s["sesion_id"] == sid_sel)
            ses_html += (f'<a href="/agente_chat?sid={s["sesion_id"]}" '
                         f'class="session-item {"active" if esel else ""}" '
                         f'style="opacity:.6">'
                         f'<div class="session-av">👤</div>'
                         f'<div class="session-info">'
                         f'<div class="session-name" style="text-decoration:line-through">{s["cliente"]}</div>'
                         f'<div class="session-last">Cerrada</div>'
                         f'</div></a>')
    if not sesiones and not cerradas:
        ses_html = '<div style="padding:20px;text-align:center;color:var(--mt);font-size:.82rem">Sin conversaciones activas</div>'

    # ── Mensajes del chat seleccionado ───────────────────────────
    especiales = {"__CERRADO__","__TIMEOUT__"}
    msgs_vis = [m for m in msgs_sel if m.get("mensaje") not in especiales]
    chat_html = ""
    if not msgs_vis and sid_sel:
        chat_html = '<div style="text-align:center;padding:24px;color:var(--mt);font-size:.82rem">Sin mensajes aún.</div>'
    for m in msgs_vis:
        hora = str(m.get("fecha",""))[-5:] or ""
        if m["de_quien"] == "agente":
            chat_html += (f'<div class="chat-row-r">'
                          f'<div class="chat-bub-r green-bub">{_fmt_msg(m["mensaje"])}</div>'
                          f'<div class="chat-meta-r">{hora} <span class="check-icon">✓</span></div>'
                          f'</div>')
        else:
            chat_html += (f'<div class="chat-row-l">'
                          f'<div class="chat-av-l" style="background:linear-gradient(135deg,#f0f4ff,#bfdbfe)">👤</div>'
                          f'<div><div class="chat-bub-l">'
                          f'<div class="chat-sender">Cliente: {m["cliente"]}</div>'
                          f'{_fmt_msg(m["mensaje"])}</div>'
                          f'<div class="chat-meta-l">{hora}</div>'
                          f'</div></div>')
    if cerrado_sel:
        motivo = "⏰ Se cerró por inactividad (5 min)" if timeout_sel else "✅ Conversación cerrada"
        chat_html += f'<div class="chat-closed-badge">{motivo}</div>'

    titulo = f"💬 Chat en Vivo" + (f" · {total_nl} sin leer" if total_nl else "")

    return base(titulo,(
        f'<div class="agent-panel-grid">'
        # Sidebar
        f'<div class="session-list">'
        f'<div class="session-list-head"><h3>💬 Conversaciones</h3></div>'
        f'{ses_html}'
        f'</div>'
        # Panel celular del agente
        f'<div class="phone-outer" style="align-items:flex-start">'
        f'<div class="phone-device" style="min-height:calc(100vh - 160px)">'
        f'<div class="phone-notch">'
        f'<div class="phone-pill"><div class="phone-cam"></div><div class="phone-speaker"></div></div>'
        f'</div>'
        f'<div class="phone-bar agent-bar">'
        f'<div class="phone-bar-left">'
        f'<div class="phone-avatar">{"👤" if cliente_sel else "💬"}</div>'
        f'<div>'
        f'<div class="phone-info-name">{"Hablando con: "+cliente_sel if cliente_sel else "Selecciona un chat"}</div>'
        f'<div class="phone-info-status"><div class="phone-status-dot"></div>Agente: {u_agen}</div>'
        f'</div></div>'
        f'<div class="phone-bar-actions">'
        + (f'<form method="post" style="display:inline">'
           f'<input type="hidden" name="ac" value="cerrar">'
           f'<input type="hidden" name="sid" value="{sid_sel}">'
           f'<input type="hidden" name="cliente" value="{cliente_sel}">'
           f'<button type="submit" class="phone-bar-btn danger" '
           f'onclick="return confirm(\'¿Cerrar esta conversación?\')">✕ Cerrar</button></form>'
           if sid_sel and not cerrado_sel else "")
        + f'</div></div>'
        # Aviso timeout
        + (f'<div style="background:#f0fdf4;border-bottom:1px solid #bbf7d0;'
           f'padding:6px 14px;font-size:.71rem;color:#15803d;flex-shrink:0">'
           f'✅ Conversación con {cliente_sel} — Responde para mantener activa</div>'
           if sid_sel and not cerrado_sel else
           f'<div style="background:#fef2f2;border-bottom:1px solid #fecaca;'
           f'padding:6px 14px;font-size:.71rem;color:#dc2626;flex-shrink:0">'
           f'{"⏰ Conversación cerrada por inactividad" if timeout_sel else ("✅ Conversación cerrada" if cerrado_sel else "")}'
           f'</div>' if cerrado_sel else "")
        # Mensajes
        + f'<div class="phone-msgs" id="chat-box">'
        + (chat_html if chat_html else
           f'<div style="text-align:center;padding:40px;color:var(--mt);font-size:.82rem">'
           f'{"" if sid_sel else "👈 Selecciona una conversación de la lista"}</div>')
        + f'</div>'
        # Input
        + (f'<form method="post" id="aform" style="display:contents">'
           f'<div class="phone-input-bar">'
           f'<input type="hidden" name="ac" value="msg">'
           f'<input type="hidden" name="sid" value="{sid_sel}">'
           f'<input type="hidden" name="cliente" value="{cliente_sel}">'
           f'<input type="text" name="msg" class="phone-input" id="ainput" '
           f'placeholder="Responde al cliente..." autocomplete="off" autofocus>'
           f'<button type="submit" class="phone-send send-agent">'
           f'<svg width="16" height="16" viewBox="0 0 24 24" fill="white">'
           f'<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>'
           f'</button></div></form>'
           if sid_sel and not cerrado_sel else
           f'<div class="phone-input-bar" style="justify-content:center;flex-shrink:0">'
           f'<div style="font-size:.8rem;color:var(--mt)">'
           f'{"Chat cerrado · Sin respuesta posible" if cerrado_sel else "Selecciona un chat para responder"}'
           f'</div></div>')
        + f'</div></div>'  # phone-device / phone-outer
        + f'</div>'  # agent-panel-grid
        + f'<script>'
        + f'var cb=document.getElementById("chat-box");if(cb)cb.scrollTop=cb.scrollHeight;'
        + f'setInterval(function(){{'
        + f'  var i=document.querySelector("#aform input[name=msg]");'
        + f'  if(!i||i.value==="")window.location.reload();'
        + f'}},5000);'
        + f'</script>'))
# ================================================================
#  LOGOUT
# ================================================================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ================================================================
#  RUN
# ================================================================
if __name__ == "__main__":
    init_demo()
    print("="*70)
    print("  GestorPro v13.0 — Sistema Multi-Tienda PREMIUM")
    print("  Colombia — Panaderías, Abarrotes y más")
    print("="*70)
    print()
    print("  URL PRINCIPAL : http://127.0.0.1:5000")
    print("  SUPER ADMIN   : http://127.0.0.1:5000/super")
    print("                  superadmin / Super@1234!")
    print()
    print("  TIENDA 1 — Panadería El Trigo Dorado:")
    print("  http://127.0.0.1:5000/login/panaderia1")
    print("  admin1/Admin@1234!  |  empleado1/Emp@1234!")
    print("  domicilio1/Dom@1234!  |  proveedor1/Prov@1234!")
    print("  cliente1/Cli@1234!")
    print()
    print("  TIENDA 2 — Abarrotes La Economía:")
    print("  http://127.0.0.1:5000/login/tienda1")
    print("  admin2/Admin@1234!  |  cliente2/Cli@1234!")
    print()
    print("  INSTALAR: pip install flask werkzeug reportlab pymysql")
    print("="*70)

    # 👇 IMPORTANTE
    app.run(host="0.0.0.0", port=5000, debug=True)
